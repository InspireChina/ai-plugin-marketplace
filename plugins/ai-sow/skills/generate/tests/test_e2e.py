from __future__ import annotations

TEST_LAYER = "e2e"

import copy
import json
import shutil
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures/pipeline"
NODE_ID_FIELDS = {
    "inputItems": "inputItemId",
    "scopeClosure": "inputItemId",
    "epics": "epicId",
    "features": "featureId",
    "designItems": "designItemId",
    "integrations": "integrationId",
    "nfrs": "nfrId",
    "policyInstances": "policyInstanceId",
    "scopeAnnotations": "annotationId",
    "stories": "storyId",
    "acceptanceCriteria": "acceptanceCriterionId",
    "deliveryAnnotations": "annotationId",
    "tasks": "taskId",
    "dependencies": "dependencyId",
    "effectiveStartMatches": "taskId",
    "estimationAnnotations": "annotationId",
}
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(SKILL_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "tests"))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
import orchestrator as orchestrator_module  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _prepare_project(project: Path, fixture_name: str = "greenfield") -> str:
    from test_contracts import valid_run_budget_policy

    _write_json(project / "budget.json", valid_run_budget_policy())
    fixture = FIXTURES / f"e2e/{fixture_name}"
    request = _load(fixture / "request.json")
    for source in request["sources"]:
        target = project / source["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture / f"{source['sourceId'].split('-')[0]}.md", target)
    _write_json(project / "request.json", request)
    return "request.json"


def _execution_facts() -> dict[str, object]:
    return {
        "failureKind": None,
        "diagnostic": None,
        "usage": {
            "provenance": "LOCALLY_ESTIMATED",
            "inputTokens": 1,
            "outputTokens": 1,
            "cachedInputTokens": 0,
            "reasoningTokens": None,
        },
        "timing": {
            "startedAtUtc": "2026-09-05T00:00:00Z",
            "endedAtUtc": "2026-09-05T00:00:01Z",
        },
    }


def _submission(action: Mapping[str, object], packet: Mapping[str, object]) -> dict[str, object]:
    from stage_driver import stage_result
    from test_scope_compiler import scope_owner_result
    kind = action['actionContractId'][:-3]
    return scope_owner_result(kind, packet) if kind.startswith('PRIOR_') else stage_result(kind, packet)


def _actions(next_action: Mapping[str, object]) -> list[Mapping[str, object]]:
    return (
        list(next_action["actions"])
        if next_action.get("kind") == "MODEL_ACTION_GROUP"
        else [next_action]
    )


def drive_fixture_host(
    project: Path,
    fixture_name: str = "greenfield",
    submission_factory: object | None = None,
    terminal_outcomes: tuple[str, ...] = ("REQUEST_APPROVAL",),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    result = orchestrator_module.run_mode(
        project, "start", request=_prepare_project(project, fixture_name), budget_policy="budget.json"
    )
    return drive_result_host(
        project,
        result,
        submission_factory,
        terminal_outcomes=terminal_outcomes,
    )


def drive_result_host(
    project: Path,
    result: Mapping[str, object],
    submission_factory: object | None = None,
    terminal_outcomes: tuple[str, ...] = ("REQUEST_APPROVAL",),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    result = dict(result)
    trace: list[dict[str, object]] = []
    files = ProjectFiles.open(project)
    while result.get("outcome") == "ACTIVE":
        next_action = result.get("nextAction")
        assert isinstance(next_action, Mapping), result
        current_actions = _actions(next_action)
        trace.extend(dict(action) for action in current_actions)
        for action in current_actions:
            provider_request = json.loads(orchestrator_module.read_provider_request(project, action["actionId"]))
            assert [message["role"] for message in provider_request["messages"]] == ["system", "user"]
            assert provider_request["maxOutputTokens"] == action["executionLimits"]["maxOutputTokens"]
            packet = json.loads(provider_request["messages"][1]["content"])
            assert canonical_json_bytes(packet) == files.read_bytes(action["packetPath"])
            submission = (
                submission_factory(action, packet)
                if callable(submission_factory)
                else _submission(action, packet)
            )
            files.publish_new(
                action["resultPath"],
                canonical_json_bytes(submission),
            )
            execution_path = f".ai-sow/work/executions/{action['actionId']}.json"
            files.publish_new(execution_path, canonical_json_bytes(_execution_facts()))
            result = orchestrator_module.run_mode(
                project,
                "submit",
                action_id=action["actionId"],
                result=action["resultPath"],
                execution=execution_path,
            )
            assert result.get("outcome") in {"ACTIVE", *terminal_outcomes}, result
    return result, trace


def _artifact_decision(
    project: Path,
    prepared: Mapping[str, object],
    decision: str,
    **extra: object,
) -> dict[str, object]:
    manifest = _load(project / str(prepared["artifactManifestPath"]))
    return {
        "contract": "ai-sow-approval-v1",
        "runId": manifest["runId"],
        "artifactManifestSha256": prepared["artifactManifestSha256"],
        "reviewDecisionSha256": manifest["reviewDecisionSha256"],
        "candidateSha256": manifest["candidateSha256"],
        "sourceManifestSha256": manifest["sourceManifestSha256"],
        "templateSha256": manifest["templateSha256"],
        "effectivePolicyDecisionSha256": manifest[
            "effectivePolicyDecisionSha256"
        ],
        "decision": decision,
        **extra,
    }


def test_fresh_run_independence_full_compile_reaches_verified_approval_then_publishes(
    tmp_path: Path,
) -> None:
    result, trace = drive_fixture_host(tmp_path)

    assert result["outcome"] == "REQUEST_APPROVAL"
    assert result["state"]["phase"] == "AWAITING_FINAL_REVIEW"
    assert result["state"]["wait"] == "APPROVAL"
    assert {action["actionContractId"] for action in trace} >= {
        "SOURCE_SCAN-v1",
        "SCOPE_SYNTHESIS-v1",
        "ARTIFACT_VISUAL_REVIEW-v1",
        "SOURCE_AUDIT-v1",
        "SOURCE_SCOPE-v1",
        "STORY_AC-v1",
        "TASK-v1",
        "STORY_DESIGN-v1",
        "TASK_ESTIMATION-v1",
    }
    assert all(
        action["contract"] == "ai-sow-action-v3" and "executionPolicy" not in action
        for action in trace
    )
    approved = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=result["artifactManifestSha256"],
    )
    assert approved["outcome"] == "PUBLISHED", approved
    assert (tmp_path / approved["workbookPath"]).is_file()
    assert (tmp_path / approved["notesPath"]).is_file()
    assert approved["state"]["phase"] == "DONE"
    assert approved["state"]["result"] == "PUBLISHED"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()

    # Final E2E gate: the same request always compiles independently of this
    # completed generation. The local zero-read boundary is tested separately.
    original_root = tmp_path / ".ai-sow/work/runs" / result["state"]["runId"]
    original_plan = next((original_root / "stages/SCOPE/plans").glob("*.json")).read_bytes()
    run_ids = {result["state"]["runId"]}
    for history in ("present", "corrupt", "deleted"):
        if history == "corrupt":
            for root in (tmp_path / ".ai-sow/generations", tmp_path / ".ai-sow/work/runs"):
                for path in root.rglob("*.json"):
                    path.write_bytes(b"corrupt hidden history")
            (tmp_path / ".ai-sow/current.json").write_bytes(b"corrupt current")
        elif history == "deleted":
            shutil.rmtree(tmp_path / ".ai-sow/generations")
            shutil.rmtree(tmp_path / ".ai-sow/work/runs")
            (tmp_path / ".ai-sow/current.json").unlink()
        started = orchestrator_module.run_mode(tmp_path, "start", request="request.json", budget_policy="budget.json")
        assert started["outcome"] == "ACTIVE", started
        state = started["state"]
        assert state["route"] == "FULL_COMPILE"
        assert state["runId"] not in run_ids
        run_ids.add(state["runId"])
        new_root = tmp_path / ".ai-sow/work/runs" / state["runId"]
        assert next((new_root / "stages/SCOPE/plans").glob("*.json")).read_bytes() == original_plan
        assert orchestrator_module.abandon(tmp_path)["outcome"] == "ABANDONED"


def test_hash_bound_abandon_decision_terminates_run_and_permanently_stales_artifact(
    tmp_path: Path,
) -> None:
    prepared, _trace = drive_fixture_host(tmp_path)
    decision = _artifact_decision(
        tmp_path,
        prepared,
        "ABANDON",
        reason="用户终止本轮。",
    )
    _write_json(tmp_path / "abandon.json", decision)

    abandoned = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
        decision="abandon.json",
    )

    assert abandoned["outcome"] == "ABANDONED", abandoned
    assert abandoned["state"]["phase"] == "DONE"
    assert abandoned["state"]["result"] == "ABANDONED"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()
    stale = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
    )
    assert stale["outcome"] == "BLOCKED"
    assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_STALE"


def test_public_abandon_at_approval_writes_hash_bound_terminal_decision(
    tmp_path: Path,
) -> None:
    prepared, _trace = drive_fixture_host(tmp_path)

    abandoned = orchestrator_module.run_mode(tmp_path, "abandon")

    assert abandoned["outcome"] == "ABANDONED", abandoned
    assert abandoned["state"]["phase"] == "DONE"
    decisions = sorted((tmp_path / ".ai-sow/work/runs").glob("*/decisions/abandon-*.json"))
    assert len(decisions) == 1
    terminal_decision = _load(decisions[0])
    assert terminal_decision["artifactManifestSha256"] == prepared[
        "artifactManifestSha256"
    ]
    stale = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
    )
    assert stale["outcome"] == "BLOCKED"
    assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_STALE"


def test_abandon_recovers_after_decision_before_state_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _trace = drive_fixture_host(tmp_path)
    decision = _artifact_decision(
        tmp_path,
        prepared,
        "ABANDON",
        reason="用户终止本轮。",
    )
    _write_json(tmp_path / "abandon-crash.json", decision)
    original = orchestrator_module._write_active_state
    failed = False

    def fail_terminal_once(files, marker, state):
        nonlocal failed
        if state.get("result") == "ABANDONED" and not failed:
            failed = True
            raise ProjectIOError("FAULT_INJECTED", marker["statePath"], "injected")
        return original(files, marker, state)

    monkeypatch.setattr(orchestrator_module, "_write_active_state", fail_terminal_once)
    interrupted = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
        decision="abandon-crash.json",
    )
    assert interrupted["outcome"] == "BLOCKED"

    resumed = orchestrator_module.run_mode(tmp_path, "resume")

    assert resumed["outcome"] == "ABANDONED", resumed
    assert resumed["state"]["phase"] == "DONE"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()


def test_brownfield_without_prior_sow_defaults_to_new_baseline(tmp_path: Path) -> None:
    result, trace = drive_fixture_host(tmp_path, "brownfield")

    assert result["outcome"] == "REQUEST_APPROVAL"
    assert trace
    revision = json.loads(
        next((tmp_path / ".ai-sow/inputs/revisions").glob("*/manifest.json")).read_text(
            encoding="utf-8"
        )
    )
    assert revision["priorSowState"] == "NOT_PROVIDED"
    assert revision["priorSowSha256s"] == []



def test_public_fixture_logs_have_no_absolute_paths_private_source_or_evidence_text(
    tmp_path: Path,
) -> None:
    result, _trace = drive_fixture_host(tmp_path)
    assert result["outcome"] == "REQUEST_APPROVAL"
    records = sorted(
        tmp_path.glob(".ai-sow/work/runs/*/actions/*/record.json")
    )
    assert records
    for record_path in records:
        record_text = record_path.read_text(encoding="utf-8")
        record = json.loads(record_text)
        packet = json.loads(
            (record_path.parent / "packet.json").read_text(encoding="utf-8")
        )
        assert "submission" not in record
        assert "evidenceCatalog" not in record
        assert str(tmp_path) not in record_text
        for evidence in packet.get("evidenceCatalog", []):
            content = evidence.get("content")
            if content:
                assert content not in record_text
