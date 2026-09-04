"""Append-only minimal reproductions discovered by the frozen E2E campaign."""

from __future__ import annotations

import sys
from pathlib import Path


TESTS_ROOT = Path(__file__).parents[1]
SCRIPTS_ROOT = TESTS_ROOT.parent / "scripts"
for path in (TESTS_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import scope_compiler as scope_compiler_module  # noqa: E402
from contracts import canonical_json_bytes  # noqa: E402
import orchestrator as orchestrator_module  # noqa: E402
from runtime.project_io import ProjectFiles  # noqa: E402
from test_e2e import (  # noqa: E402
    _actions,
    _execution_facts,
    _prepare_project,
    _submission,
)
from test_scope_compiler import scope_join_state  # noqa: E402


def test_scope_join_packet_exposes_responsibility_boundary_inventory() -> None:
    state = scope_join_state()

    prepared = scope_compiler_module.prepare_action(state, "SCOPE_JOIN")

    assert prepared["outcome"] == "ACTION_REQUIRED"
    packet = prepared["specs"][0]["packet"]
    assert packet["responsibilityBoundaryIds"] == state["baseCandidate"]["project"][
        "responsibilityBoundaries"
    ]


def test_story_checkpoint_revalidates_records_against_group_base_candidate(
    tmp_path: Path,
) -> None:
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=_prepare_project(tmp_path)
    )
    files = ProjectFiles.open(tmp_path)
    while result.get("outcome") == "ACTIVE":
        actions = _actions(result["nextAction"])
        for action in actions:
            packet = files.read_json(action["packetPath"])
            files.publish_new(
                action["outputPath"],
                canonical_json_bytes(_submission(action, packet)),
            )
            execution_path = f".ai-sow/work/executions/{action['actionId']}.json"
            files.publish_new(
                execution_path, canonical_json_bytes(_execution_facts())
            )
            result = orchestrator_module.run_mode(
                tmp_path,
                "submit",
                action_id=action["actionId"],
                result=action["outputPath"],
                execution=execution_path,
            )
        if actions[0]["stage"] == "STORY_AC":
            assert result.get("outcome") == "ACTIVE", result
            assert _actions(result["nextAction"])[0]["stage"] == "TASK"
            return
    raise AssertionError(result)
