from __future__ import annotations

import copy
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
import orchestrator as orchestrator_module  # noqa: E402
from models import Diagnostic, RenderedPackage, WorkbookAudit  # noqa: E402
from package_renderer import PackageRenderError  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402
from test_scope_compiler import stage_one_checkpoint_state  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def test_public_parser_exposes_exact_host_neutral_operations() -> None:
    parser = orchestrator_module._parser()
    mode_action = next(
        action for action in parser._actions if action.dest == "mode"
    )
    assert tuple(mode_action.choices) == (
        "start",
        "submit",
        "hydrate",
        "resume",
        "approve",
        "abandon",
        "status",
    )


def test_public_dispatch_rejects_retired_stage_mode(tmp_path: Path) -> None:
    result = orchestrator_module.run_mode(tmp_path, "prepare")

    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "CLI_MODE_INVALID"


def test_public_start_emits_and_accepts_path_locked_fresh_action(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)

    started = orchestrator_module.run_mode(
        tmp_path, "start", request=request_path
    )

    assert started["outcome"] == "ACTIVE"
    next_action = started["nextAction"]
    actions = (
        next_action["actions"]
        if next_action["kind"] == "MODEL_ACTION_GROUP"
        else [next_action]
    )
    assert actions
    assert all(
        action["executionPolicy"]["contextPolicy"] == "FRESH_NO_HISTORY"
        and action["executionPolicy"]["inheritConversation"] is False
        for action in actions
    )
    files = ProjectFiles.open(tmp_path)
    recorded = None
    for action in actions:
        packet = files.read_json(action["packetPath"])
        coverage = list(packet["payload"]["coverageRootIds"])
        inventory = {
            item["blockId"]: item
            for item in packet["payload"]["fullBlockInventory"]
        }
        evidence = {
            item["evidenceId"]: item for item in packet["evidenceCatalog"]
        }
        submission = {
            "contract": "ai-sow-stage-result-v1",
            "resultKind": "SOURCE_SCAN_PATCH",
            "reviewedEvidenceIds": coverage,
            "blockCoverage": [
                {"blockId": block_id, "disposition": "READ"}
                for block_id in coverage
            ],
            "replacementSet": {
                "expectedNodeHashes": {},
                "upserts": [
                    {
                        "collection": "inputItems",
                        "node": {
                            "inputItemId": f"input-{block_id}",
                            "kind": (
                                "DESIGN_DECISION"
                                if inventory[block_id]["sourceRole"] == "HLD"
                                else "REQUIREMENT"
                            ),
                            "text": evidence[block_id]["content"],
                            "conditions": [],
                            "thresholds": [],
                            "prohibitions": [],
                            "applicableScopes": ["退款能力"],
                            "sourceRefs": [
                                {
                                    "sourceId": inventory[block_id]["sourceId"],
                                    "blockId": block_id,
                                    "sha256": evidence[block_id]["sha256"],
                                    "locator": inventory[block_id]["locator"],
                                }
                            ],
                        },
                    }
                    for block_id in coverage
                ],
                "deletes": [],
            },
            "selfCheck": {
                "completedCheckIds": list(
                    packet["payload"]["requiredCheckIds"]
                ),
                "unresolvedItems": [],
            },
        }
        files.publish_new(
            action["outputPath"], canonical_json_bytes(submission)
        )
        execution_path = f"execution-{action['actionId']}.json"
        write_json(tmp_path / execution_path, execution_facts())
        recorded = orchestrator_module.run_mode(
            tmp_path,
            "submit",
            action_id=action["actionId"],
            result=action["outputPath"],
            execution=execution_path,
        )
        assert recorded["outcome"] == "ACTIVE", recorded

    assert recorded is not None
    assert recorded["state"]["wait"] == "MODEL"
    next_actions = (
        recorded["nextAction"]["actions"]
        if recorded["nextAction"]["kind"] == "MODEL_ACTION_GROUP"
        else [recorded["nextAction"]]
    )
    assert {action["promptId"] for action in next_actions} == {
        "stage1-scope-proposal-v1"
    }


def write_run_store_request(project: Path, name: str = "primary") -> str:
    inputs = project / "inputs"
    inputs.mkdir(exist_ok=True)
    prd_path = inputs / f"{name}-prd.md"
    hld_path = inputs / f"{name}-hld.md"
    prd_path.write_text(
        f"# {name} 范围\n\n用户提交退款并看到处理结果。\n",
        encoding="utf-8",
    )
    hld_path.write_text(
        f"# {name} 目标架构\n\n门户调用退款服务并支持生产回退。\n",
        encoding="utf-8",
    )
    path = project / f"{name}-request.json"
    write_json(
        path,
        {
            "contract": "ai-sow-generate-request-v2",
            "project": {
                "projectId": "project-run-store",
                "name": "Run Store 测试项目",
                "plannedEffectiveDate": "2026-10-01",
            },
            "mode": "GREENFIELD",
            "responsibilityBoundaries": [
                {
                    "responsibilityBoundaryId": "responsibility-vendor",
                    "party": "VENDOR",
                    "name": "供应商交付责任",
                    "responsibilities": ["实现并验证范围内能力"],
                }
            ],
            "sources": [
                {
                    "sourceId": f"prd-{name}",
                    "role": "PRD",
                    "path": prd_path.relative_to(project).as_posix(),
                    "status": "APPROVED",
                },
                {
                    "sourceId": f"hld-{name}",
                    "role": "HLD",
                    "path": hld_path.relative_to(project).as_posix(),
                    "status": "APPROVED",
                },
            ],
            "questions": [],
            "questionnaireAnswers": [],
            "currentStateDelta": None,
        },
    )
    return path.name


def managed_snapshot(project: Path) -> dict[str, bytes]:
    root = project / ".ai-sow"
    if not root.exists():
        return {}
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def active_marker(project: Path) -> dict[str, object]:
    return json.loads(
        (project / ".ai-sow/work/active-run.json").read_text(encoding="utf-8")
    )


def reserve_marker_again(project: Path) -> dict[str, object]:
    marker = active_marker(project)
    marker.update({"status": "RESERVED", "stateSha256": None})
    write_json(project / ".ai-sow/work/active-run.json", marker)
    return marker


def test_start_creates_one_active_run_and_orthogonal_state(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    result = orchestrator_module.start(tmp_path, request_path)

    assert result["outcome"] == "ACTIVE"
    state = result["state"]
    assert (state["route"], state["phase"], state["wait"], state["result"]) == (
        "FULL_COMPILE",
        "PREPARE",
        "NONE",
        None,
    )
    marker = active_marker(tmp_path)
    assert marker["status"] == "ACTIVE"
    assert marker["runId"] == state["runId"]
    assert marker["inputRevisionSha256"] != marker["requestSha256"]
    revision_manifests = list(
        (tmp_path / ".ai-sow/inputs/revisions").glob("*/manifest.json")
    )
    assert len(revision_manifests) == 1
    assert marker["inputRevisionSha256"] == sha256_bytes(
        revision_manifests[0].read_bytes()
    )
    assert marker["stateSha256"] == sha256_bytes(
        (tmp_path / marker["statePath"]).read_bytes()
    )


def test_same_request_start_is_idempotent(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    first = orchestrator_module.start(tmp_path, request_path)
    before = managed_snapshot(tmp_path)
    second = orchestrator_module.start(tmp_path, request_path)

    assert second == first
    assert managed_snapshot(tmp_path) == before
    assert len(list((tmp_path / ".ai-sow/work/runs").iterdir())) == 1


def test_start_rejects_tampered_bound_input_revision(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, request_path)
    marker = active_marker(tmp_path)
    (tmp_path / marker["inputRevisionPath"]).write_bytes(b"{}\n")

    result = orchestrator_module.resume(tmp_path)

    assert result["outcome"] == "BLOCKED"
    assert [item["code"] for item in result["diagnostics"]] == [
        "RUN_INPUT_REVISION_HASH_MISMATCH"
    ]


def test_different_request_returns_run_in_progress_without_mutation(
    tmp_path: Path,
) -> None:
    first_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, first_path)
    second_path = write_run_store_request(tmp_path, "different")
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.start(tmp_path, second_path)

    assert result["outcome"] == "RUN_IN_PROGRESS"
    assert [item["code"] for item in result["diagnostics"]] == ["RUN_IN_PROGRESS"]
    assert managed_snapshot(tmp_path) == before


def test_candidate_snapshots_are_sequential_immutable_and_hash_named(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    files = ProjectFiles.open(tmp_path)
    run_id = started["state"]["runId"]

    first = orchestrator_module._append_candidate_snapshot(
        files, run_id, {"contract": "ai-sow-model-v1", "nodes": ["one"]}
    )
    first_payload = files.read_bytes(first["path"])
    second = orchestrator_module._append_candidate_snapshot(
        files, run_id, {"contract": "ai-sow-model-v1", "nodes": ["two"]}
    )

    assert Path(first["path"]).name == f"000001-{first['sha256']}.json"
    assert Path(second["path"]).name == f"000002-{second['sha256']}.json"
    assert files.read_bytes(first["path"]) == first_payload
    state = orchestrator_module.status(tmp_path)["state"]
    assert state["currentCandidatePath"] == second["path"]
    assert state["currentCandidateSha256"] == second["sha256"]


def test_abandon_persists_terminal_state_before_clearing_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, request_path)
    marker = active_marker(tmp_path)
    original = ProjectFiles.unlink_exact

    def assert_terminal_before_unlink(
        files: ProjectFiles, relative_path: str, *, expected_payload: bytes
    ) -> bool:
        current_marker = files.read_json(orchestrator_module.ACTIVE_RUN_PATH)
        state = files.read_json(current_marker["statePath"])
        assert state["phase"] == "DONE"
        assert state["wait"] == "NONE"
        assert state["result"] == "ABANDONED"
        return original(files, relative_path, expected_payload=expected_payload)

    monkeypatch.setattr(ProjectFiles, "unlink_exact", assert_terminal_before_unlink)
    result = orchestrator_module.abandon(tmp_path)

    assert result["outcome"] == "ABANDONED"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()
    terminal_payload = canonical_json_bytes(result["state"])
    terminal_path = orchestrator_module._state_snapshot_path(
        str(result["state"]["runId"]), sha256_bytes(terminal_payload)
    )
    assert (tmp_path / terminal_path).read_bytes() == terminal_payload


def test_crash_resume_never_starts_a_second_run(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    first = orchestrator_module.start(tmp_path, request_path)
    marker = reserve_marker_again(tmp_path)
    (tmp_path / marker["statePath"]).unlink()
    (tmp_path / marker["bindingPath"]).unlink()

    second = orchestrator_module.start(tmp_path, request_path)

    assert second["state"]["runId"] == first["state"]["runId"]
    assert len(list((tmp_path / ".ai-sow/work/runs").iterdir())) == 1


def test_crash_after_marker_before_state_recovers_without_second_run(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    marker = reserve_marker_again(tmp_path)
    (tmp_path / marker["statePath"]).unlink()
    (tmp_path / marker["bindingPath"]).unlink()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"]["runId"] == started["state"]["runId"]
    assert active_marker(tmp_path)["status"] == "ACTIVE"


def test_crash_after_state_before_revision_binding_recovers_deterministically(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    marker = reserve_marker_again(tmp_path)
    state_payload = (tmp_path / marker["statePath"]).read_bytes()
    (tmp_path / marker["bindingPath"]).unlink()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"] == started["state"]
    assert (tmp_path / marker["statePath"]).read_bytes() == state_payload
    assert (tmp_path / marker["bindingPath"]).is_file()


def test_crash_after_revision_before_state_pointer_recovers_deterministically(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    marker = reserve_marker_again(tmp_path)
    state_payload = (tmp_path / marker["statePath"]).read_bytes()
    binding_payload = (tmp_path / marker["bindingPath"]).read_bytes()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"] == started["state"]
    assert (tmp_path / marker["statePath"]).read_bytes() == state_payload
    assert (tmp_path / marker["bindingPath"]).read_bytes() == binding_payload
    assert active_marker(tmp_path)["stateSha256"] == sha256_bytes(state_payload)


def test_crash_after_new_state_before_marker_keeps_previous_snapshot_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    files = ProjectFiles.open(tmp_path)
    marker = active_marker(tmp_path)
    previous_state = copy.deepcopy(started["state"])
    next_state = {
        **previous_state,
        "route": "DELTA_COMPILE",
    }
    original_write_atomic = ProjectFiles.write_atomic

    def crash_before_marker(
        self: ProjectFiles, relative_path: str, payload: bytes
    ) -> None:
        if relative_path == orchestrator_module.ACTIVE_RUN_PATH:
            raise RuntimeError("simulated marker crash")
        original_write_atomic(self, relative_path, payload)

    monkeypatch.setattr(ProjectFiles, "write_atomic", crash_before_marker)
    with pytest.raises(RuntimeError, match="simulated marker crash"):
        orchestrator_module._write_active_state(files, marker, next_state)
    monkeypatch.setattr(ProjectFiles, "write_atomic", original_write_atomic)

    resumed = orchestrator_module.status(tmp_path)

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"] == previous_state


def test_crash_after_action_plan_before_state_replays_plan_into_active_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    original_write_state = orchestrator_module._write_active_state

    def crash_before_state(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated plan/state crash")

    monkeypatch.setattr(orchestrator_module, "_write_active_state", crash_before_state)
    with pytest.raises(RuntimeError, match="simulated plan/state crash"):
        orchestrator_module._issue_action_group(
            files,
            run_id,
            (action_spec("story-feature-001"),),
            max_concurrency=1,
            group_deadline_milliseconds=600000,
            shard_deadline_milliseconds=480000,
            pipeline_step="STORY_AC",
        )
    monkeypatch.setattr(orchestrator_module, "_write_active_state", original_write_state)

    resumed = orchestrator_module.run_mode(tmp_path, "status")

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"]["wait"] == "MODEL"
    assert resumed["state"]["expectedActionIds"]
    assert resumed["nextAction"]["kind"] == "MODEL_ACTION"


def test_crash_after_success_record_before_state_replays_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))
    write_action_result(files, envelope)
    record_execution(files, envelope, execution_facts())
    original_write_state = orchestrator_module._write_active_state

    def crash_before_state(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated record/state crash")

    monkeypatch.setattr(orchestrator_module, "_write_active_state", crash_before_state)
    with pytest.raises(RuntimeError, match="simulated record/state crash"):
        orchestrator_module.submit(
            tmp_path, envelope["actionId"], envelope["outputPath"]
        )
    monkeypatch.setattr(orchestrator_module, "_write_active_state", original_write_state)

    resumed = orchestrator_module.status(tmp_path)

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"]["wait"] == "NONE"
    assert resumed["state"]["expectedActionIds"] == []
    assert resumed["state"]["budget"]["modelActionsCompleted"] == 1


def stage_result() -> dict[str, object]:
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": ["evidence-001"],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": [],
            "deletes": [],
        },
        "selfCheck": {"completedCheckIds": [], "unresolvedItems": []},
    }


def action_spec(logical_shard_id: str) -> dict[str, object]:
    evidence = [
        {
            "evidenceId": f"evidence-{index:03d}",
            "locator": f"fixture:{index}",
            "content": f"第 {index} 条测试证据。",
        }
        for index in range(1, 4)
    ]
    for item in evidence:
        item["sha256"] = sha256_bytes(str(item["content"]).encode("utf-8"))
    return {
        "logicalShardId": logical_shard_id,
        "stage": "STORY_AC",
        "role": "AUTHOR",
        "promptId": "stage2-story-ac-v1",
        "promptPath": "prompts/fragments/execution-envelope.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": ["references/story-authoring.md"],
        "evidenceCatalog": evidence,
        "packet": {"subjectIds": [logical_shard_id]},
        "modelProfileId": "model-profile-v1",
        "modelConfigSha256": "d" * 64,
        "maxOutputTokens": 12000,
    }


def test_public_review_specs_are_issued_in_bounded_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [action_spec(f"review-shard-{index:02d}") for index in range(1, 10)]
    captured: list[dict[str, object]] = []
    state = {"runId": "run-000000000001"}
    monkeypatch.setattr(
        orchestrator_module,
        "_issue_action_group",
        lambda _files, _run_id, selected, **_kwargs: captured.extend(selected),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_read_active_marker",
        lambda _files: {"runId": state["runId"]},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_recover_active_run",
        lambda _files, _marker: state,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_public_active_result",
        lambda _files, current: {"outcome": "ACTIVE", "state": current},
    )

    result = orchestrator_module._issue_public_specs(
        object(),
        state,
        "STORY_DESIGN",
        {
            "outcome": "ACTION_REQUIRED",
            "specs": specs,
            "pendingLogicalShardIds": [
                spec["logicalShardId"] for spec in specs
            ],
        },
    )

    assert result["outcome"] == "ACTIVE"
    assert [item["logicalShardId"] for item in captured] == [
        f"review-shard-{index:02d}" for index in range(1, 9)
    ]


def prepare_action_run(tmp_path: Path) -> tuple[ProjectFiles, str, dict[str, object]]:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path)
    files = ProjectFiles.open(tmp_path)
    run_id = started["state"]["runId"]
    initial = orchestrator_module._append_candidate_snapshot(
        files, run_id, {"contract": "ai-sow-model-v1", "nodes": []}
    )
    return files, run_id, initial


def execution_facts(
    *, accounting_mode: str = "PROVIDER_REPORTED", status: str = "SUCCESS"
) -> dict[str, object]:
    estimated = accounting_mode == "LOCALLY_ESTIMATED"
    return {
        "status": status,
        "failure": None
        if status == "SUCCESS"
        else {
            "code": "HOST_EXECUTION_FAILED",
            "message": "fixture worker 未返回可接受结果。",
        },
        "timing": {
            "queueMilliseconds": 7,
            "executionMilliseconds": 93,
            "actionMilliseconds": 110,
        },
        "modelAttempts": 1,
        "toolAttempts": 2,
        "usage": {
            "accountingMode": accounting_mode,
            "inputTokens": 100,
            "cachedInputTokens": 10,
            "outputTokens": 20,
            "reasoningTokens": None if estimated else 4,
            "tokenizerId": "utf8-bytes-div-4" if estimated else None,
            "tokenizerVersion": "1" if estimated else None,
        },
        "controlPlaneTokens": 12,
    }


def record_execution(
    files: ProjectFiles,
    envelope: dict[str, object],
    facts: dict[str, object],
) -> None:
    result = orchestrator_module.record_execution(
        files.root, envelope["actionId"], facts
    )
    assert result["outcome"] == "RECORDED", result


def issue_actions(
    files: ProjectFiles,
    run_id: str,
    logical_shard_ids: tuple[str, ...],
) -> dict[str, object]:
    return orchestrator_module._issue_action_group(
        files,
        run_id,
        [action_spec(shard_id) for shard_id in logical_shard_ids],
        max_concurrency=min(2, len(logical_shard_ids)),
        group_deadline_milliseconds=120000,
        shard_deadline_milliseconds=90000,
    )


def write_action_result(files: ProjectFiles, envelope: dict[str, object]) -> None:
    files.publish_new(envelope["outputPath"], canonical_json_bytes(stage_result()))


def test_action_envelope_is_hash_bound_and_fresh_no_history(tmp_path: Path) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))

    assert envelope["kind"] == "MODEL_ACTION"
    assert envelope["executionPolicy"]["contextPolicy"] == "FRESH_NO_HISTORY"
    assert envelope["executionPolicy"]["inheritConversation"] is False
    assert envelope["instructionManifest"]["executionEnvelope"]["sha256"] == (
        sha256_bytes(
            (SKILL_ROOT / "prompts/fragments/execution-envelope.md").read_bytes()
        )
    )
    assert envelope["instructionManifest"]["prompt"]["sha256"] == sha256_bytes(
        (SKILL_ROOT / envelope["promptPath"]).read_bytes()
    )
    issued_path = envelope["recordPath"].replace("record.json", "issued.json")
    issued = files.read_json(issued_path)
    assert issued["envelopeSha256"] == sha256_bytes(
        files.read_bytes(envelope["recordPath"].replace("record.json", "envelope.json"))
    )
    assert issued["packetSha256"] == sha256_bytes(files.read_bytes(envelope["packetPath"]))
    with pytest.raises(ProjectIOError) as conflict:
        files.publish_new(
            envelope["recordPath"].replace("record.json", "envelope.json"),
            b"tampered",
        )
    assert conflict.value.code == "PROJECT_CONTENT_CONFLICT"


def test_tampered_packet_is_rejected_without_advancing_run_state(tmp_path: Path) -> None:
    files, run_id, initial = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))
    files.write_atomic(envelope["packetPath"], canonical_json_bytes({"tampered": True}))

    result = orchestrator_module.hydrate(
        tmp_path, envelope["actionId"], ["evidence-001"]
    )

    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "ACTION_BINDING_INVALID"
    state = orchestrator_module.status(tmp_path)["state"]
    assert state["currentCandidateSha256"] == initial["sha256"]
    assert state["expectedActionIds"] == [envelope["actionId"]]


def test_hydrate_enforces_allowlist_two_rounds_and_deduplication(
    tmp_path: Path,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))
    action_id = envelope["actionId"]

    first = orchestrator_module.hydrate(tmp_path, action_id, ["evidence-001", "evidence-001"])
    assert first["outcome"] == "HYDRATED"
    assert first["evidenceIds"] == ["evidence-001"]
    before = managed_snapshot(tmp_path)
    reused = orchestrator_module.hydrate(tmp_path, action_id, ["evidence-001"])
    assert reused["outcome"] == "REUSED"
    assert managed_snapshot(tmp_path) == before
    assert orchestrator_module.hydrate(tmp_path, action_id, ["evidence-002"])[
        "outcome"
    ] == "HYDRATED"

    over_limit = orchestrator_module.hydrate(tmp_path, action_id, ["evidence-003"])
    assert over_limit["outcome"] == "BLOCKED"
    assert over_limit["diagnostics"][0]["code"] == "ACTION_HYDRATION_LIMIT_EXCEEDED"
    not_allowed = orchestrator_module.hydrate(tmp_path, action_id, ["outside-allowlist"])
    assert not_allowed["diagnostics"][0]["code"] == "ACTION_EVIDENCE_NOT_ALLOWED"


def test_submit_is_single_write_and_idempotent_for_same_hash(tmp_path: Path) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))
    write_action_result(files, envelope)
    record_execution(files, envelope, execution_facts())

    first = orchestrator_module.submit(tmp_path, envelope["actionId"], envelope["outputPath"])
    before = managed_snapshot(tmp_path)
    second = orchestrator_module.submit(tmp_path, envelope["actionId"], envelope["outputPath"])

    assert first["outcome"] == "RECORDED"
    assert second == first
    assert managed_snapshot(tmp_path) == before
    files.write_atomic(envelope["outputPath"], canonical_json_bytes({**stage_result(), "reviewedEvidenceIds": []}))
    changed = orchestrator_module.submit(tmp_path, envelope["actionId"], envelope["outputPath"])
    assert changed["diagnostics"][0]["code"] == "ACTION_SUBMISSION_CONFLICT"


def test_retry_replaces_expected_action_and_rejects_late_result(tmp_path: Path) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    group = issue_actions(files, run_id, ("story-feature-001", "story-feature-002"))
    first, failed = group["actions"]
    write_action_result(files, first)
    record_execution(files, first, execution_facts())
    orchestrator_module.submit(tmp_path, first["actionId"], first["outputPath"])

    record_execution(files, failed, execution_facts(status="FAILED"))
    retry = orchestrator_module._retry_action(files, failed["actionId"])
    assert retry["actionId"] != failed["actionId"]
    assert retry["executionAttempt"] == 2
    for field in (
        "logicalShardId",
        "packetSha256",
        "modelConfigSha256",
        "baseCandidateSha256",
    ):
        actual = retry.get(field) or retry["executionPolicy"].get(field)
        expected = failed.get(field) or failed["executionPolicy"].get(field)
        assert actual == expected
    assert files.read_json(failed["recordPath"])["status"] == "FAILED"

    write_action_result(files, failed)
    late = orchestrator_module.submit(tmp_path, failed["actionId"], failed["outputPath"])
    assert {item["code"] for item in late["diagnostics"]} >= {"ACTION_NOT_EXPECTED"}


def test_public_submit_retries_failed_execution_without_result_and_exhausts_budget(
    tmp_path: Path,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    first = issue_actions(files, run_id, ("story-feature-001",))
    first_execution = "execution-first-failed.json"
    write_json(tmp_path / first_execution, execution_facts(status="FAILED"))

    retried = orchestrator_module.run_mode(
        tmp_path,
        "submit",
        action_id=first["actionId"],
        execution=first_execution,
    )

    assert retried["outcome"] == "ACTIVE", retried
    retry = retried["nextAction"]
    assert retry["kind"] == "MODEL_ACTION"
    assert retry["actionId"] != first["actionId"]
    assert retry["executionAttempt"] == 2
    assert not (tmp_path / first["outputPath"]).exists()
    assert files.read_json(first["recordPath"])["status"] == "FAILED"

    retry_execution = "execution-retry-failed.json"
    write_json(tmp_path / retry_execution, execution_facts(status="LATE"))
    exhausted = orchestrator_module.run_mode(
        tmp_path,
        "submit",
        action_id=retry["actionId"],
        execution=retry_execution,
    )

    assert exhausted["outcome"] == "SYSTEM_FAILED", exhausted
    assert exhausted["diagnostics"][0]["code"] == "BUDGET_EXCEEDED"
    terminal = orchestrator_module.status(tmp_path)
    assert terminal["state"]["phase"] == "DONE"
    assert terminal["state"]["result"] == "SYSTEM_FAILED"


@pytest.mark.parametrize("crash_site", ("retry_action", "state_pointer"))
def test_failed_retry_recovers_from_each_persisted_crash_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_site: str,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    first = issue_actions(files, run_id, ("story-feature-001",))
    execution_path = "execution-first-failed.json"
    write_json(tmp_path / execution_path, execution_facts(status="FAILED"))

    if crash_site == "retry_action":
        original_persist = orchestrator_module._persist_issued_action

        def persist_then_crash(files_arg, envelope, packet_payload):
            original_persist(files_arg, envelope, packet_payload)
            if envelope["executionAttempt"] == 2:
                raise RuntimeError("simulated crash after retry action persistence")

        monkeypatch.setattr(
            orchestrator_module, "_persist_issued_action", persist_then_crash
        )
    else:
        original_write = orchestrator_module._write_active_state

        def state_pointer_crash(files_arg, marker, state):
            retry_path = (
                tmp_path
                / f".ai-sow/work/runs/{run_id}/actions/{first['actionId']}/retry.json"
            )
            if retry_path.is_file():
                raise RuntimeError("simulated crash before state pointer swap")
            return original_write(files_arg, marker, state)

        monkeypatch.setattr(
            orchestrator_module, "_write_active_state", state_pointer_crash
        )

    with pytest.raises(RuntimeError):
        orchestrator_module.run_mode(
            tmp_path,
            "submit",
            action_id=first["actionId"],
            execution=execution_path,
        )

    monkeypatch.undo()
    recovered = orchestrator_module.run_mode(tmp_path, "status")
    retry = recovered["nextAction"]
    assert recovered["outcome"] == "ACTIVE"
    assert retry["executionAttempt"] == 2
    assert retry["actionId"] != first["actionId"]
    assert recovered["state"]["expectedActionIds"] == [retry["actionId"]]
    assert recovered["state"]["budget"]["modelActionsStarted"] == 2
    assert recovered["state"]["budget"]["modelActionsCompleted"] == 1

    replayed = orchestrator_module.run_mode(
        tmp_path,
        "submit",
        action_id=first["actionId"],
        execution=execution_path,
    )
    assert replayed["outcome"] == "ACTIVE"
    assert replayed["nextAction"]["actionId"] == retry["actionId"]


def test_usage_distinguishes_provider_and_local_unknown_reasoning(tmp_path: Path) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    group = issue_actions(files, run_id, ("story-feature-001", "story-feature-002"))
    records = []
    for envelope, mode in zip(
        group["actions"], ("PROVIDER_REPORTED", "LOCALLY_ESTIMATED"), strict=True
    ):
        write_action_result(files, envelope)
        record_execution(files, envelope, execution_facts(accounting_mode=mode))
        records.append(
            orchestrator_module.submit(
                tmp_path, envelope["actionId"], envelope["outputPath"]
            )["record"]
        )

    assert records[0]["usage"]["accountingMode"] == "PROVIDER_REPORTED"
    assert records[0]["usage"]["tokenizerId"] is None
    assert records[1]["usage"]["accountingMode"] == "LOCALLY_ESTIMATED"
    assert records[1]["usage"]["reasoningTokens"] is None
    assert records[1]["usage"]["tokenizerVersion"] == "1"


def test_action_record_preserves_time_token_attempt_hydration_and_control_facts(
    tmp_path: Path,
) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    envelope = issue_actions(files, run_id, ("story-feature-001",))
    orchestrator_module.hydrate(tmp_path, envelope["actionId"], ["evidence-001"])
    facts = execution_facts(accounting_mode="LOCALLY_ESTIMATED")
    record_execution(files, envelope, facts)
    write_action_result(files, envelope)
    record = orchestrator_module.submit(
        tmp_path, envelope["actionId"], envelope["outputPath"]
    )["record"]

    assert record["timing"] == facts["timing"]
    assert record["modelAttempts"] == 1
    assert record["toolAttempts"] == 2
    assert record["controlPlaneTokens"] == 12
    assert record["initialPacket"]["bytes"] > 0
    assert record["hydrationLog"][0]["returnedEvidenceIds"] == ["evidence-001"]
    assert record["hydrationLog"][0]["bytes"] > 0
    assert record["hydrationLog"][0]["tokens"] > 0


def test_budget_exceeded_preserves_sibling_and_stops_new_action(tmp_path: Path) -> None:
    files, run_id, _ = prepare_action_run(tmp_path)
    group = issue_actions(files, run_id, ("story-feature-001", "story-feature-002"))
    successful, failing = group["actions"]
    write_action_result(files, successful)
    record_execution(files, successful, execution_facts())
    sibling_record = orchestrator_module.submit(
        tmp_path, successful["actionId"], successful["outputPath"]
    )["record"]
    record_execution(files, failing, execution_facts(status="FAILED"))
    retry = orchestrator_module._retry_action(files, failing["actionId"])
    action_count = len(list((tmp_path / f".ai-sow/work/runs/{run_id}/actions").iterdir()))

    record_execution(files, retry, execution_facts(status="FAILED"))
    exceeded = orchestrator_module._retry_action(files, retry["actionId"])

    assert exceeded["outcome"] == "SYSTEM_FAILED"
    assert exceeded["diagnostics"][0]["code"] == "BUDGET_EXCEEDED"
    assert len(list((tmp_path / f".ai-sow/work/runs/{run_id}/actions").iterdir())) == action_count
    assert files.read_json(successful["recordPath"]) == sibling_record
    state = orchestrator_module.status(tmp_path)["state"]
    assert state["phase"] == "DONE"
    assert state["result"] == "SYSTEM_FAILED"
    assert state["expectedActionIds"] == []


def test_group_records_do_not_advance_candidate_until_one_group_apply(
    tmp_path: Path,
) -> None:
    files, run_id, initial = prepare_action_run(tmp_path)
    group = issue_actions(files, run_id, ("story-feature-001", "story-feature-002"))
    for envelope in group["actions"]:
        write_action_result(files, envelope)
        record_execution(files, envelope, execution_facts())
        orchestrator_module.submit(tmp_path, envelope["actionId"], envelope["outputPath"])
        assert orchestrator_module.status(tmp_path)["state"]["currentCandidateSha256"] == (
            initial["sha256"]
        )

    applied = orchestrator_module._apply_ready_group(
        files,
        run_id,
        group["groupId"],
        {"contract": "ai-sow-model-v1", "nodes": ["merged"]},
    )
    candidate_files = list(
        (tmp_path / f".ai-sow/work/runs/{run_id}/candidates").iterdir()
    )
    replayed = orchestrator_module._apply_ready_group(
        files,
        run_id,
        group["groupId"],
        {"contract": "ai-sow-model-v1", "nodes": ["merged"]},
    )

    assert applied == replayed
    assert len(candidate_files) == 2
    assert len(list((tmp_path / f".ai-sow/work/runs/{run_id}/candidates").iterdir())) == 2


ROUTE_MATRIX_PATH = FIXTURES / "pipeline/routes/route-matrix.json"


def route_matrix() -> dict[str, object]:
    return json.loads(ROUTE_MATRIX_PATH.read_text(encoding="utf-8"))


def route_case(case: dict[str, object]) -> tuple[dict[str, object], dict[str, object], object]:
    matrix = route_matrix()
    state = copy.deepcopy(matrix["baseState"])
    input_revision = json.loads(
        (ROUTE_MATRIX_PATH.parent / matrix["inputRevisionFixture"]).read_text(
            encoding="utf-8"
        )
    )
    current_generation = copy.deepcopy(matrix["baseCurrentGeneration"])
    roots = {
        "state": state,
        "inputRevision": input_revision,
        "currentGeneration": current_generation,
    }
    for mutation in case["mutations"]:
        parts = mutation["target"].split(".")
        if len(parts) == 1:
            roots[parts[0]] = copy.deepcopy(mutation["value"])
            continue
        target = roots[parts[0]]
        for part in parts[1:-1]:
            target = target[int(part)] if part.isdigit() else target[part]
        last = parts[-1]
        if last.isdigit():
            target[int(last)] = copy.deepcopy(mutation["value"])
        else:
            target[last] = copy.deepcopy(mutation["value"])
    return roots["state"], roots["inputRevision"], roots["currentGeneration"]


def route_cases(*names: str) -> list[dict[str, object]]:
    wanted = set(names)
    return [
        case
        for case in route_matrix()["cases"]
        if not wanted or case["name"] in wanted
    ]


@pytest.mark.parametrize("case", route_cases(), ids=lambda case: case["name"])
def test_route_matrix_selects_reuse_render_only_full_and_delta_deterministically(
    case: dict[str, object],
) -> None:
    state, input_revision, current_generation = route_case(case)
    before = copy.deepcopy((state, input_revision, current_generation))

    first = orchestrator_module.plan_route(state, input_revision, current_generation)
    second = orchestrator_module.plan_route(state, input_revision, current_generation)

    expected = case["expected"]
    assert first == second
    assert first.route == expected["route"]
    assert first.lowest_recovery_stage == expected["lowestRecoveryStage"]
    assert list(first.changed) == expected["changed"]
    if diagnostic_code := expected.get("diagnosticCode"):
        assert [item.code for item in first.diagnostics] == [diagnostic_code]
    elif first.route in {"REUSE", "RENDER_ONLY", "DELTA_COMPILE"}:
        assert first.diagnostics == ()
    assert len(first.proof_sha256) == 64
    assert (state, input_revision, current_generation) == before


def test_old_generation_is_not_read_or_converted_and_routes_full_compile() -> None:
    class LegacyGeneration(dict):
        def get(self, key: object, default: object = None) -> object:
            if key == "contract":
                return "ai-sow-generation-manifest-v1"
            raise AssertionError(f"旧 generation 不得读取字段：{key}")

    base = route_cases("reuse")[0]
    state, input_revision, _ = route_case(base)

    decision = orchestrator_module.plan_route(
        state,
        input_revision,
        LegacyGeneration(),
    )

    assert decision.route == "FULL_COMPILE"
    assert decision.lowest_recovery_stage == "STAGE_1"
    assert decision.changed == ("generationProofClosure",)


def test_render_only_requires_self_contained_review_and_checkpoint_proof() -> None:
    template_case = route_cases("template-only")[0]
    state, input_revision, current_generation = route_case(template_case)
    assert orchestrator_module.plan_route(
        state, input_revision, current_generation
    ).route == "RENDER_ONLY"

    corruptions = (
        ("selfContained", False),
        ("reviewDecision", "BLOCKED"),
        ("scopeCheckpoint", "BLOCKED"),
    )
    for kind, value in corruptions:
        broken = copy.deepcopy(current_generation)
        if kind == "selfContained":
            broken["selfContained"] = value
        elif kind == "reviewDecision":
            broken["proofClosure"]["reviewDecision"]["decision"] = value
        else:
            broken["proofClosure"]["stageCheckpoints"]["SCOPE_CLOSURE"][
                "decision"
            ] = value
        decision = orchestrator_module.plan_route(state, input_revision, broken)
        assert decision.route == "FULL_COMPILE"
        assert [item.code for item in decision.diagnostics] == [
            "GENERATION_PROOF_CLOSURE_INVALID"
        ]


def test_revision_storage_path_is_not_part_of_semantic_input_hash() -> None:
    reuse_case = route_cases("reuse")[0]
    state, input_revision, current_generation = route_case(reuse_case)
    input_revision["sources"][0]["path"] = (
        ".ai-sow/inputs/revisions/revision-new/sources/source-prd/raw.md"
    )

    decision = orchestrator_module.plan_route(
        state, input_revision, current_generation
    )

    assert decision.route == "REUSE"
    assert decision.changed == ()


@pytest.mark.parametrize(
    "case",
    route_cases(
        "semantic-input",
        "delivery-policy",
        "scope-checkpoint",
        "effective-policy-decision",
        "story-checkpoint",
        "catalog-semantics",
        "estimation-method",
        "task-checkpoint",
        "review-decision",
        "catalog-and-template",
    ),
    ids=lambda case: case["name"],
)
def test_delta_route_selects_lowest_safe_stage_from_projection_changes(
    case: dict[str, object],
) -> None:
    state, input_revision, current_generation = route_case(case)

    decision = orchestrator_module.plan_route(state, input_revision, current_generation)

    assert decision.route == "DELTA_COMPILE"
    assert decision.lowest_recovery_stage == case["expected"]["lowestRecoveryStage"]
    stage = decision.lowest_recovery_stage
    expected_invalidations = {
        "STAGE_1": ("SCOPE_CLOSURE", "STORY_AC", "TASK", "REVIEW", "ARTIFACT"),
        "STAGE_2": ("STORY_AC", "TASK", "REVIEW", "ARTIFACT"),
        "STAGE_3": ("TASK", "REVIEW", "ARTIFACT"),
        "REVIEW": ("REVIEW", "ARTIFACT"),
    }
    assert decision.invalidated == expected_invalidations[stage]


def test_input_diagnostic_prevents_any_model_action() -> None:
    case = route_cases("input-gap")[0]
    state, input_revision, current_generation = route_case(case)
    before = copy.deepcopy((state, input_revision, current_generation))

    decision = orchestrator_module.plan_route(state, input_revision, current_generation)

    assert decision.lowest_recovery_stage is None
    assert decision.changed == ()
    assert decision.invalidated == ()
    assert [item.code for item in decision.diagnostics] == ["HLD_REQUIRED"]
    assert (state, input_revision, current_generation) == before


def test_route_decision_hash_binds_all_inputs_and_cannot_change_after_prepare() -> None:
    case = route_cases("reuse")[0]
    state, input_revision, current_generation = route_case(case)
    baseline = orchestrator_module.plan_route(state, input_revision, current_generation)

    changed_state = copy.deepcopy(state)
    changed_state["rendererSha256"] = "0" * 64
    changed_input = copy.deepcopy(input_revision)
    changed_input["templateSha256"] = "0" * 64
    changed_generation = copy.deepcopy(current_generation)
    changed_generation["proofClosure"]["artifactManifest"]["sha256"] = "0" * 64
    decisions = (
        orchestrator_module.plan_route(changed_state, input_revision, current_generation),
        orchestrator_module.plan_route(state, changed_input, current_generation),
        orchestrator_module.plan_route(state, input_revision, changed_generation),
    )

    assert all(item.proof_sha256 != baseline.proof_sha256 for item in decisions)
    with pytest.raises(FrozenInstanceError):
        baseline.proof_sha256 = "0" * 64  # type: ignore[misc]


def test_missing_design_blocks_before_story_actions() -> None:
    state = stage_one_checkpoint_state()
    closure = next(
        item
        for item in state["candidate"]["scopeClosure"]
        if item["inputItemId"] == "input-i18n"
    )
    closure.update(
        {
            "mechanicalCoverage": "MISSING",
            "semanticSufficiency": "NOT_REVIEWED",
            "designCoverageStatus": "MISSING",
        }
    )

    result = orchestrator_module.advance_stage_one(state)

    assert result["outcome"] == "INPUT_REQUIRED"
    assert result["lowestRecoveryStage"] == "STAGE_1"
    assert result["nextAction"] is None
    assert result["questions"][0]["requiredSourceRole"] == "APPROVED_DESIGN"
    assert "Story" in result["questions"][0]["unansweredConsequence"]


def test_conflict_or_blocked_delivery_disposition_cannot_enter_stage_two() -> None:
    for field, value in (
        ("disposition", "CONFLICT"),
        ("deliveryDisposition", "BLOCKED"),
    ):
        state = stage_one_checkpoint_state()
        state["candidate"]["scopeClosure"][0][field] = value

        result = orchestrator_module.advance_stage_one(state)

        assert result["outcome"] == "INPUT_REQUIRED"
        assert result["nextAction"] is None
        assert result["lowestRecoveryStage"] == "STAGE_1"
        assert {item.code for item in result["diagnostics"]} == {
            "SCOPE_CLOSURE_BLOCKED"
        }


def test_stage_one_orchestrator_exposes_minimal_host_neutral_sequence() -> None:
    complete = stage_one_checkpoint_state()

    no_scan = {**complete, "actionRecords": []}
    assert orchestrator_module.advance_stage_one(no_scan)["actionKind"] == (
        "SOURCE_SCAN"
    )

    no_proposal = {**complete, "proposalRecords": []}
    assert orchestrator_module.advance_stage_one(no_proposal)["actionKind"] == (
        "SCOPE_PROPOSAL"
    )

    no_join = copy.deepcopy(complete)
    no_join["candidate"]["scopeClosure"] = []
    assert orchestrator_module.advance_stage_one(no_join)["actionKind"] == (
        "SCOPE_JOIN"
    )

    no_audit = {**complete, "r1SourceResults": []}
    assert orchestrator_module.advance_stage_one(no_audit)["actionKind"] == (
        "R1_SOURCE_INDEPENDENT_SCAN"
    )

    no_r1_join = {**complete, "r1ScopeResult": None}
    assert orchestrator_module.advance_stage_one(no_r1_join)["actionKind"] == (
        "R1_SCOPE_JOIN"
    )

    ready = orchestrator_module.advance_stage_one(complete)
    assert ready["outcome"] == "READY_FOR_STORY_AC"
    assert ready["nextPhase"] == "STORY_AC"
    assert ready["nextAction"] is None


def test_stage_two_orchestrator_waits_then_builds_host_neutral_checkpoint() -> None:
    from test_delivery_compiler import (  # noqa: PLC0415
        story_stage_state,
        story_submission_for_spec,
    )
    from test_scope_compiler import source_scan_record  # noqa: PLC0415

    state = story_stage_state(token_budget=3000)
    waiting = orchestrator_module.advance_stage_two(state)
    records = [
        source_scan_record(state, spec, story_submission_for_spec(state, spec))
        for spec in waiting["specs"]
    ]
    ready = orchestrator_module.advance_stage_two(
        {**state, "storyActionRecords": records}
    )

    assert waiting["outcome"] == "ACTION_REQUIRED"
    assert waiting["joinRequired"] is True
    assert ready["outcome"] == "READY_FOR_TASK"
    assert ready["nextPhase"] == "TASK"
    assert ready["nextAction"] is None


def test_stage_three_orchestrator_hydrates_without_cli_and_builds_checkpoint() -> None:
    from test_task_compiler import (  # noqa: PLC0415
        task_stage_state,
        task_submission_for_spec,
    )
    from test_scope_compiler import source_scan_record  # noqa: PLC0415

    state = task_stage_state()
    waiting = orchestrator_module.advance_stage_three(state)
    records = [
        source_scan_record(state, spec, task_submission_for_spec(state, spec))
        for spec in waiting["specs"]
    ]
    ready = orchestrator_module.advance_stage_three(
        {**state, "taskActionRecords": records}
    )

    assert waiting["outcome"] == "ACTION_REQUIRED"
    assert waiting["actionKind"] == "TASK"
    assert ready["outcome"] == "READY_FOR_REVIEW"
    assert ready["nextPhase"] == "REVIEW"
    assert ready["nextAction"] is None


def test_review_orchestrator_exposes_fresh_host_neutral_actions() -> None:
    from test_layered_review import review_state  # noqa: PLC0415

    result = orchestrator_module.advance_review(review_state())

    assert result["outcome"] == "ACTION_REQUIRED"
    assert result["reviewKind"] == "STORY_DESIGN"
    assert result["lowestRecoveryStage"] == "REVIEW"
    assert result["nextAction"] is None
    assert result["specs"]


def reviewed_artifact_state() -> dict[str, object]:
    from test_layered_review import review_state  # noqa: PLC0415

    state = review_state()
    candidate_sha256 = sha256_bytes(canonical_json_bytes(state["candidate"]))
    state["reviewDecision"] = {
        "contract": "ai-sow-layered-review-decision-v1",
        "runId": state["runId"],
        "candidateSha256": candidate_sha256,
        "scopeClosureCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["scopeClosureCheckpoint"])
        ),
        "storyAcCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["storyAcCheckpoint"])
        ),
        "taskCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["taskCheckpoint"])
        ),
        "reviewResultSha256s": ["9" * 64],
        "decision": "PASS",
    }
    return state


def fixture_renderer(root: Path):
    calls = {"count": 0}

    def render(reviewed_model, *, template_path, review_decision):
        calls["count"] += 1
        output = root / f"render-{calls['count']}" / "output"
        output.mkdir(parents=True)
        workbook = output / "sow.xlsx"
        notes = output / "sow-notes.md"
        workbook.write_bytes(b"verified-workbook")
        notes.write_text("# 已验证候选说明\n", encoding="utf-8")
        return RenderedPackage(
            root=str(output.parent),
            workbook_path=str(workbook),
            notes_path=str(notes),
            workbook_sha256=sha256_bytes(workbook.read_bytes()),
            notes_sha256=sha256_bytes(notes.read_bytes()),
            files=("output/sow-notes.md", "output/sow.xlsx"),
            workbook_audit=WorkbookAudit(
                trust_state="VERIFIED",
                story_count=len(reviewed_model["stories"]),
                task_count=len(reviewed_model["tasks"]),
                direct_days=10.0,
                sit_days=1.0,
                uat_days=1.0,
                total_days=12.0,
                parameter_statuses=(("K_COMPLEXITY_M", "固定规则"),),
                formula_errors=(),
                engine_name="LibreOffice",
                engine_version="fixture",
            ),
        )

    return render


def test_draft_is_verified_before_request_approval_and_manifest_binds_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = ProjectFiles.open(project)
    state = reviewed_artifact_state()

    monkeypatch.setattr(orchestrator_module, "prepare_draft", fixture_renderer(tmp_path))
    result = orchestrator_module.prepare_artifact(
        state,
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )

    assert result["outcome"] == "REQUEST_APPROVAL"
    assert result["nextAction"]["kind"] == "REQUEST_APPROVAL"
    assert "候选" in result["summary"]
    manifest = files.read_json(result["artifactManifestPath"])
    assert manifest["candidateSha256"] == sha256_bytes(
        canonical_json_bytes(state["candidate"])
    )
    assert manifest["sourceManifestSha256"] == state["candidate"]["project"][
        "sourceManifestSha256"
    ]
    assert manifest["stageCheckpointSha256s"] == [
        state["reviewDecision"][field]
        for field in (
            "scopeClosureCheckpointSha256",
            "storyAcCheckpointSha256",
            "taskCheckpointSha256",
        )
    ]
    assert manifest["taskCatalogSemanticSha256"] == state["taskCheckpoint"][
        "taskCatalogSemanticSha256"
    ]
    assert manifest["taskEstimationMethodSha256"] == state["taskCheckpoint"][
        "taskEstimationMethodSha256"
    ]
    assert manifest["rendererContract"] == "generation-renderer-v8"
    assert manifest["workbookVerification"]["trustState"] == "VERIFIED"


def test_artifact_renderer_uses_context_scoped_project_temporary_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = ProjectFiles.open(project)
    state = reviewed_artifact_state()
    observed_roots: list[Path] = []

    def render(reviewed_model, *, template_path, review_decision):
        del template_path, review_decision
        root = Path(
            orchestrator_module._PROJECT_LOCAL_TEMPFILE.mkdtemp(
                prefix="ai-sow-draft-"
            )
        )
        observed_roots.append(root)
        output = root / "output"
        output.mkdir()
        workbook = output / "sow.xlsx"
        notes = output / "sow-notes.md"
        workbook.write_bytes(b"verified-workbook")
        notes.write_text("# 已验证候选说明\n", encoding="utf-8")
        return RenderedPackage(
            root=str(root),
            workbook_path=str(workbook),
            notes_path=str(notes),
            workbook_sha256=sha256_bytes(workbook.read_bytes()),
            notes_sha256=sha256_bytes(notes.read_bytes()),
            files=("output/sow-notes.md", "output/sow.xlsx"),
            workbook_audit=WorkbookAudit(
                trust_state="VERIFIED",
                story_count=len(reviewed_model["stories"]),
                task_count=len(reviewed_model["tasks"]),
                direct_days=10.0,
                sit_days=1.0,
                uat_days=1.0,
                total_days=12.0,
                parameter_statuses=(("K_COMPLEXITY_M", "固定规则"),),
                formula_errors=(),
                engine_name="LibreOffice",
                engine_version="fixture",
            ),
        )

    monkeypatch.setattr(orchestrator_module, "prepare_draft", render)
    result = orchestrator_module.prepare_artifact(
        state,
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )

    expected = project / ".ai-sow/work/runs" / str(state["runId"]) / "render-temp"
    assert result["outcome"] == "REQUEST_APPROVAL"
    assert len(observed_roots) == 1
    assert observed_roots[0].parent == expected
    assert not observed_roots[0].exists()
    assert not expected.exists()


def test_each_regenerated_artifact_uses_a_new_immutable_version_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = ProjectFiles.open(project)
    renderer = fixture_renderer(tmp_path)
    monkeypatch.setattr(orchestrator_module, "prepare_draft", renderer)
    state = reviewed_artifact_state()

    first = orchestrator_module.prepare_artifact(
        state,
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )
    first_bytes = files.read_bytes(first["artifactManifestPath"])
    second = orchestrator_module.prepare_artifact(
        state,
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )

    assert first["artifactManifestPath"] != second["artifactManifestPath"]
    assert files.read_bytes(first["artifactManifestPath"]) == first_bytes


def test_missing_or_failed_office_never_creates_approval_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    def failed_renderer(*_args, **_kwargs):
        raise PackageRenderError("OFFICE_ENGINE_UNAVAILABLE", "未安装 LibreOffice")

    monkeypatch.setattr(orchestrator_module, "prepare_draft", failed_renderer)
    result = orchestrator_module.prepare_artifact(
        reviewed_artifact_state(),
        ProjectFiles.open(project),
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )

    assert result["outcome"] == "SYSTEM_FAILED"
    assert result["nextAction"] is None
    assert not (project / ".ai-sow/work/runs").exists()


def prepare_fixture_artifact(
    project: Path,
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project.mkdir()
    files = ProjectFiles.open(project)
    monkeypatch.setattr(orchestrator_module, "prepare_draft", fixture_renderer(scratch))
    result = orchestrator_module.prepare_artifact(
        reviewed_artifact_state(),
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )
    return files, result, files.read_json(result["artifactManifestPath"])


def test_approval_and_promote_are_idempotent_and_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    files, prepared, _manifest = prepare_fixture_artifact(
        project, tmp_path / "scratch", monkeypatch
    )

    first = orchestrator_module.approve(
        project, prepared["artifactManifestSha256"]
    )
    approval_before = files.read_bytes(first["approvalPath"])
    current_before = files.read_bytes(".ai-sow/current.json")
    replay = orchestrator_module.approve(
        project, prepared["artifactManifestSha256"]
    )

    assert first["outcome"] == "PUBLISHED"
    assert replay["outcome"] == "REUSED"
    assert files.read_bytes(first["approvalPath"]) == approval_before
    assert files.read_bytes(".ai-sow/current.json") == current_before
    stale = orchestrator_module.approve(project, "0" * 64)
    assert stale["outcome"] == "BLOCKED"
    assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_NOT_FOUND"
    assert files.read_bytes(".ai-sow/current.json") == current_before


@pytest.mark.parametrize(
    ("decision_kind", "extra", "expected_outcome"),
    [
        (
            "EXCLUDE_DEFAULT_AUTOMATION",
            {
                "excludedPolicyInstanceIds": ["policy-instance-sit"],
                "reason": "客户明确排除默认 SIT 自动化。",
            },
            "READY_FOR_STORY_AC",
        ),
        ("ABANDON", {"reason": "用户终止本轮。"}, "ABANDONED"),
    ],
)
def test_exclude_and_abandon_never_write_approval_generation_or_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision_kind: str,
    extra: dict[str, object],
    expected_outcome: str,
) -> None:
    project = tmp_path / decision_kind.lower()
    files, prepared, manifest = prepare_fixture_artifact(
        project, tmp_path / f"scratch-{decision_kind.lower()}", monkeypatch
    )
    decision = {
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
        "decision": decision_kind,
        **extra,
    }
    write_json(project / "decision.json", decision)

    result = orchestrator_module.approve(
        project,
        prepared["artifactManifestSha256"],
        "decision.json",
    )

    assert result["outcome"] == expected_outcome
    artifact_root = Path(prepared["artifactManifestPath"]).parent
    assert not (project / artifact_root / "approval.json").exists()
    assert not (project / ".ai-sow/current.json").exists()
    assert not (project / ".ai-sow/generations").exists()
    if decision_kind == "EXCLUDE_DEFAULT_AUTOMATION":
        candidate = files.read_json(result["candidatePath"])
        policy = files.read_json(result["effectivePolicyDecisionPath"])
        assert policy["policy-instance-sit"] == "EXCLUDED"
        assert candidate["stories"] == []
        assert candidate["tasks"] == []
        assert candidate["decisions"][-1]["kind"] == "EXCLUDED_BY_USER"
        assert candidate["decisions"][-1]["subjectIds"] == [
            "policy-instance-sit"
        ]
        stale = orchestrator_module.approve(
            project, prepared["artifactManifestSha256"]
        )
        assert stale["outcome"] == "BLOCKED"
        assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_STALE"
