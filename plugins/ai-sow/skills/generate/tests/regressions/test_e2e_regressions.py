"""Append-only minimal reproductions discovered by the frozen E2E campaign."""

from __future__ import annotations

TEST_LAYER = "integration"

import sys
import pytest
import json
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


def test_scope_join_packet_exposes_responsibility_boundary_inventory() -> None:
    from test_scope_compiler import owner_input_case, scope_owner_runtime, seal_scope_work
    from stage_planner import materialize_packet, DependencyResultRef, _effective_success
    request, revision, contents, _ = owner_input_case()
    plan, items, contexts, ledger, sizing = runtime = scope_owner_runtime(request, revision, contents)
    for work in plan["works"][:-1]:
        seal_scope_work(runtime, work["logicalWorkId"])
    root = plan["works"][-1]
    refs = []
    for key in root["packetPlan"]["dependencyLogicalWorkIds"]:
        digest, record = _effective_success(runtime[3], key)
        refs.append(DependencyResultRef(key, digest, runtime[3].normalized_results[record.normalized_result_sha256]))
    packet = json.loads(materialize_packet(plan, root["logicalWorkId"], 1, items, contexts, refs, runtime[3]))
    scope_context = next(ref["canonicalContent"] for ref in packet["contextRefs"] if ref["canonicalContent"].get("kind") == "SCOPE_CONTEXT")
    assert scope_context["responsibilityBoundaries"] == request["responsibilityBoundaries"]
    assert scope_context["responsibilityBoundaries"]
    assert packet["workItems"] == []


def test_story_checkpoint_revalidates_records_against_group_base_candidate(
    tmp_path: Path,
) -> None:
    from test_orchestrator import write_run_store_request, write_budget_policy, submit_prototype
    from stage_driver import stage_result
    from contracts import sha256_bytes
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=write_run_store_request(tmp_path), budget_policy=write_budget_policy(tmp_path)
    )
    story_actions = []
    for _ in range(30):
        assert result['outcome'] == 'ACTIVE', result
        actions = result['nextAction'].get('actions', [result['nextAction']])
        if actions[0]['actionContractId'] == 'TASK-v2': break
        for action in actions:
            packet_path = tmp_path/action['packetPath']
            envelope_path = packet_path.parent/'envelope.json'
            if action['actionContractId'] == 'STORY_AC-v1':
                story_actions.append((action, envelope_path, envelope_path.read_bytes()))
            recorded = submit_prototype(tmp_path, action, stage_result(action['actionContractId'][:-3], json.loads(packet_path.read_bytes())))
            assert recorded['record']['outcome'] == 'SUCCEEDED', recorded
        result = orchestrator_module.run_mode(tmp_path, 'resume')
    else: pytest.fail('Story checkpoint failed to advance to Task')
    assert story_actions
    root = tmp_path/'.ai-sow/work/runs'/result['state']['runId']/'stages'
    scope = json.loads(next((root/'SCOPE/checkpoints').glob('*.json')).read_bytes())
    story = json.loads(next((root/'STORY_AC/checkpoints').glob('*.json')).read_bytes())
    assert story['candidateSha256'] != scope['candidateSha256']
    assert result['state']['currentCandidateSha256'] == story['candidateSha256']
    for action, path, raw in story_actions:
        assert path.read_bytes() == raw
        assert action['baseCandidateSha256'] == scope['candidateSha256']
        assert sha256_bytes(raw) == sha256_bytes(canonical_json_bytes(action))
    assert orchestrator_module.run_mode(tmp_path, 'resume')['outcome'] == 'ACTIVE'
    action, path, raw = story_actions[0]
    value = json.loads(raw)
    value['baseCandidateSha256'] = story['candidateSha256']
    path.write_bytes(canonical_json_bytes(value))
    assert orchestrator_module.run_mode(tmp_path, 'resume')['outcome'] == 'BLOCKED'
