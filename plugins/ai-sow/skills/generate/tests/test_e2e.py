from __future__ import annotations

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
        "status": "SUCCESS",
        "failure": None,
        "timing": {
            "queueMilliseconds": 0,
            "executionMilliseconds": 1,
            "actionMilliseconds": 1,
        },
        "modelAttempts": 1,
        "toolAttempts": 0,
        "usage": {
            "accountingMode": "LOCALLY_ESTIMATED",
            "inputTokens": 1,
            "cachedInputTokens": 0,
            "outputTokens": 1,
            "reasoningTokens": None,
            "tokenizerId": "fixture-v1",
            "tokenizerVersion": "1",
        },
        "controlPlaneTokens": 0,
    }


def _source_scan_result(packet: Mapping[str, object]) -> dict[str, object]:
    fixture = _load(FIXTURES / "stage1/scope-join-result.json")
    by_text = {item["text"]: item for item in fixture["inputItems"]}
    payload = packet["payload"]
    inventory = {item["blockId"]: item for item in payload["fullBlockInventory"]}
    evidence = {item["evidenceId"]: item for item in packet["evidenceCatalog"]}
    roots = list(payload["coverageRootIds"])
    upserts = []
    for block_id in roots:
        evidence_item = evidence[block_id]
        node = copy.deepcopy(by_text[evidence_item["content"]])
        block = inventory[block_id]
        node["sourceRefs"] = [
            {
                "sourceId": block["sourceId"],
                "blockId": block_id,
                "sha256": evidence_item["sha256"],
                "locator": block["locator"],
            }
        ]
        upserts.append({"collection": "inputItems", "node": node})
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SOURCE_SCAN_PATCH",
        "reviewedEvidenceIds": roots,
        "blockCoverage": [
            {"blockId": block_id, "disposition": "READ"} for block_id in roots
        ],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": upserts,
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": list(payload["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def _scope_proposal_result(packet: Mapping[str, object]) -> dict[str, object]:
    payload = packet["payload"]
    items = {item["inputItemId"]: item for item in payload["localInputItems"]}
    assigned = list(payload["assignedInputItemIds"])
    scope_class = {
        "input-refund": "BUSINESS",
        "input-demo-retry": "BUSINESS",
        "input-i18n": "TECHNICAL",
        "input-shared-pipeline": "DELIVERY",
        "input-language-design": "TECHNICAL",
        "input-release-design": "DELIVERY",
        "input-refund-event": "TECHNICAL",
        "input-migration": "TECHNICAL",
    }
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SCOPE_PROPOSAL",
        "reviewedEvidenceIds": assigned,
        "inputItemIds": assigned,
        "boundaryCandidates": [
            {
                "boundaryId": f"boundary-{item_id}",
                "inputItemIds": [item_id],
                "boundarySummary": items[item_id]["text"],
                "scopeClass": scope_class[item_id],
                "affinityKeys": [
                    "affinity-refund"
                    if item_id in {"input-refund", "input-demo-retry", "input-refund-event"}
                    else f"affinity-{item_id}"
                ],
                "independentClosureEvidence": ["来源保留独立交付边界判断。"],
            }
            for item_id in assigned
        ],
        "crossShardAffinities": [
            {
                "affinityKey": "affinity-refund",
                "inputItemIds": [
                    item_id
                    for item_id in (
                        "input-refund",
                        "input-demo-retry",
                        "input-refund-event",
                    )
                    if item_id in payload["inputItemIdInventory"]
                ],
                "rationale": "退款需求、界面行为和已批准集成设计需要在全局合并。",
            }
        ],
        "selfCheck": {
            "completedCheckIds": list(payload["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def _replace_source_refs(value: object, by_old_block: Mapping[str, object]) -> object:
    if isinstance(value, list):
        return [_replace_source_refs(item, by_old_block) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"sourceId", "blockId", "sha256", "locator"}:
        replacement = by_old_block.get(str(value["blockId"]))
        return copy.deepcopy(replacement) if replacement is not None else value
    return {key: _replace_source_refs(item, by_old_block) for key, item in value.items()}


def _scope_join_result(packet: Mapping[str, object]) -> dict[str, object]:
    fixture = _load(FIXTURES / "stage1/scope-join-result.json")
    payload = packet["payload"]
    current_by_id = {item["inputItemId"]: item for item in payload["inputItems"]}
    by_old_block = {
        item["sourceRefs"][0]["blockId"]: current_by_id[item["inputItemId"]]["sourceRefs"][0]
        for item in fixture["inputItems"]
    }
    result = _replace_source_refs(copy.deepcopy(fixture["joinSubmission"]), by_old_block)
    result["reviewedEvidenceIds"] = list(payload["inputItemIds"])
    boundary_ids = list(payload["responsibilityBoundaryIds"])
    for wrapper in result["replacementSet"]["upserts"]:
        if wrapper["collection"] == "integrations":
            wrapper["node"]["responsibilityBoundaryIds"] = boundary_ids[:1]
    return result


def _story_result(packet: Mapping[str, object]) -> dict[str, object]:
    fixture = _load(FIXTURES / "stage2/story-ac-results.json")
    payload = packet["payload"]
    assigned = set(payload["assignedObligationIds"])
    upserts = []
    for wrapper in fixture["replacementSet"]["upserts"]:
        wrapper = copy.deepcopy(wrapper)
        obligation_ids = set(wrapper["node"].pop("fixtureObligationIds", []))
        if obligation_ids.intersection(assigned):
            upserts.append(wrapper)
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": list(payload["assignedEvidenceIds"]),
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": upserts,
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": list(payload["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def _task_result(packet: Mapping[str, object]) -> dict[str, object]:
    fixture = _load(FIXTURES / "stage3/task-results.json")
    payload = packet["payload"]
    assigned = set(payload["assignedStoryIds"])
    rows = {
        row["工作类型ID"]: row["rowSemanticSha256"]
        for row in payload["taskStandardCompactIndex"]
    }
    upserts = []
    for wrapper in fixture["replacementSet"]["upserts"]:
        wrapper = copy.deepcopy(wrapper)
        story_ids = set(wrapper["node"].pop("fixtureStoryIds", []))
        if not story_ids.intersection(assigned):
            continue
        if wrapper["collection"] == "tasks":
            wrapper["node"]["rowSemanticSha256"] = rows[wrapper["node"]["workTypeId"]]
        upserts.append(wrapper)
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": list(payload["assignedEvidenceIds"]),
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": upserts,
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": list(payload["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def _review_result(action: Mapping[str, object], packet: Mapping[str, object]) -> dict[str, object]:
    payload = packet["payload"]
    result = {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": f"result-{action['logicalShardId']}",
        "reviewSetId": payload["reviewSetId"],
        "runId": payload["runId"],
        "kind": payload["reviewKind"] if "reviewKind" in payload else action["stage"],
        "reviewPlanSha256": payload["reviewPlanSha256"],
        "candidateProjectionSha256": payload["candidateProjectionSha256"],
        "coverageSha256": payload["coverageSha256"],
        "completedCheckIds": list(payload["requiredCheckIds"]),
        "decision": "PASS",
        "findings": [],
    }
    if action["stage"] in {"SOURCE_AUDIT", "SOURCE_SCOPE"}:
        result["sourceAuditCoverageUnion"] = list(payload["coverageRootIds"])
    if action["stage"] == "THEME_JOIN":
        result["leafReviewResultSha256s"] = list(payload["leafReviewResultSha256s"])
    return result


def _submission(action: Mapping[str, object], packet: Mapping[str, object]) -> dict[str, object]:
    prompt = action["promptId"]
    if prompt == "stage1-source-scan-v1":
        return _source_scan_result(packet)
    if prompt == "stage1-scope-proposal-v1":
        return _scope_proposal_result(packet)
    if prompt == "stage1-scope-join-v1":
        return _scope_join_result(packet)
    if prompt == "stage2-story-ac-v1":
        return _story_result(packet)
    if prompt == "stage3-task-v1":
        return _task_result(packet)
    return _review_result(action, packet)


def _bind_existing_node_hashes(
    submission: dict[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    replacement = submission.get("replacementSet")
    if not isinstance(replacement, dict):
        return submission
    existing = {
        f"{collection}:{node[id_field]}": node
        for collection, id_field in NODE_ID_FIELDS.items()
        for node in candidate.get(collection, [])
        if isinstance(node, Mapping) and isinstance(node.get(id_field), str)
    }
    targets: set[str] = set()
    for wrapper in replacement.get("upserts", []):
        if not isinstance(wrapper, Mapping):
            continue
        collection = wrapper.get("collection")
        node = wrapper.get("node")
        id_field = NODE_ID_FIELDS.get(str(collection))
        if isinstance(node, Mapping) and id_field is not None:
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                targets.add(f"{collection}:{node_id}")
    targets.update(
        item
        for item in replacement.get("deletes", [])
        if isinstance(item, str)
    )
    replacement["expectedNodeHashes"] = {
        key: sha256_bytes(canonical_json_bytes(existing[key]))
        for key in sorted(targets & set(existing))
    }
    return submission


def _actions(next_action: Mapping[str, object]) -> list[Mapping[str, object]]:
    return (
        list(next_action["actions"])
        if next_action["kind"] == "MODEL_ACTION_GROUP"
        else [next_action]
    )


def drive_fixture_host(
    project: Path,
    fixture_name: str = "greenfield",
    submission_factory: object | None = None,
    terminal_outcomes: tuple[str, ...] = ("REQUEST_APPROVAL",),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    result = orchestrator_module.run_mode(
        project, "start", request=_prepare_project(project, fixture_name)
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
            packet = files.read_json(action["packetPath"])
            submission = (
                submission_factory(action, packet)
                if callable(submission_factory)
                else _submission(action, packet)
            )
            candidate = files.read_json(result["state"]["currentCandidatePath"])
            assert isinstance(candidate, Mapping)
            submission = _bind_existing_node_hashes(submission, candidate)
            files.publish_new(
                action["outputPath"],
                canonical_json_bytes(submission),
            )
            execution_path = f".ai-sow/work/executions/{action['actionId']}.json"
            files.publish_new(execution_path, canonical_json_bytes(_execution_facts()))
            result = orchestrator_module.run_mode(
                project,
                "submit",
                action_id=action["actionId"],
                result=action["outputPath"],
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


def test_full_compile_reaches_verified_request_approval_then_publishes(
    tmp_path: Path,
) -> None:
    result, trace = drive_fixture_host(tmp_path)

    assert result["outcome"] == "REQUEST_APPROVAL"
    assert result["state"]["phase"] == "AWAITING_APPROVAL"
    assert result["state"]["wait"] == "APPROVAL"
    assert {action["promptId"] for action in trace} >= {
        "stage1-source-scan-v1",
        "stage1-scope-proposal-v1",
        "stage1-scope-join-v1",
        "review-source-audit-v1",
        "review-source-scope-v1",
        "stage2-story-ac-v1",
        "stage3-task-v1",
        "review-story-design-v1",
        "review-task-estimation-v1",
    }
    assert all(
        action["executionPolicy"]["contextPolicy"] == "FRESH_NO_HISTORY"
        and action["executionPolicy"]["inheritConversation"] is False
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


def test_exclusion_decision_invalidates_suffix_and_immediately_issues_stage_two(
    tmp_path: Path,
) -> None:
    prepared, _trace = drive_fixture_host(tmp_path)
    decision = _artifact_decision(
        tmp_path,
        prepared,
        "EXCLUDE_DEFAULT_AUTOMATION",
        excludedPolicyInstanceIds=["policy-instance-sit"],
        reason="客户明确排除默认 SIT 自动化。",
    )
    _write_json(tmp_path / "exclude.json", decision)

    excluded = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
        decision="exclude.json",
    )

    assert excluded["outcome"] == "ACTIVE", excluded
    assert excluded["state"]["phase"] == "STORY_AC"
    assert excluded["state"]["wait"] == "MODEL"
    assert {item["kind"] for item in excluded["state"]["checkpointRefs"]} == {
        "SCOPE_CLOSURE"
    }
    assert {
        action["promptId"] for action in _actions(excluded["nextAction"])
    } == {"stage2-story-ac-v1"}
    stale = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
    )
    assert stale["outcome"] == "BLOCKED"
    assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_STALE"


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


def test_exclusion_recovers_after_decision_before_transition_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _trace = drive_fixture_host(tmp_path)
    decision = _artifact_decision(
        tmp_path,
        prepared,
        "EXCLUDE_DEFAULT_AUTOMATION",
        excludedPolicyInstanceIds=["policy-instance-sit"],
        reason="客户明确排除默认 SIT 自动化。",
    )
    _write_json(tmp_path / "exclude-crash.json", decision)
    original = ProjectFiles.publish_new
    failed = False

    def fail_transition_once(self, relative_path, payload):
        nonlocal failed
        if "/invalidations/exclusion-" in relative_path and not failed:
            failed = True
            raise ProjectIOError("FAULT_INJECTED", relative_path, "injected")
        return original(self, relative_path, payload)

    monkeypatch.setattr(ProjectFiles, "publish_new", fail_transition_once)
    interrupted = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=prepared["artifactManifestSha256"],
        decision="exclude-crash.json",
    )
    assert interrupted["outcome"] == "BLOCKED"

    resumed = orchestrator_module.run_mode(tmp_path, "status")

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"]["phase"] == "STORY_AC"
    assert resumed["state"]["wait"] == "MODEL"


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

    resumed = orchestrator_module.run_mode(tmp_path, "status")

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


def test_exact_replay_reuses_without_launching_reviewer(tmp_path: Path) -> None:
    result, trace = drive_fixture_host(tmp_path)
    approved = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=result["artifactManifestSha256"],
    )
    assert approved["outcome"] == "PUBLISHED"
    generation_before = (tmp_path / ".ai-sow/current.json").read_bytes()

    replay = orchestrator_module.run_mode(tmp_path, "start", request="request.json")

    assert replay["outcome"] == "REUSED"
    assert replay["nextAction"]["kind"] == "DONE"
    assert replay["nextAction"]["result"] == "REUSED"
    assert (tmp_path / ".ai-sow/current.json").read_bytes() == generation_before
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()
    assert any(action["role"] == "REVIEWER" for action in trace)


def test_exact_input_revision_rechecks_renderer_before_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _trace = drive_fixture_host(tmp_path)
    approved = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=result["artifactManifestSha256"],
    )
    assert approved["outcome"] == "PUBLISHED"
    monkeypatch.setattr(orchestrator_module, "_renderer_sha256", lambda: "0" * 64)

    replay = orchestrator_module.run_mode(tmp_path, "start", request="request.json")

    assert replay["outcome"] == "REQUEST_APPROVAL", replay
    assert replay["state"]["route"] == "RENDER_ONLY"
    assert replay["artifactManifestSha256"] != result["artifactManifestSha256"]


def test_reuse_and_render_only_launch_no_reviewer(tmp_path: Path) -> None:
    result, _trace = drive_fixture_host(tmp_path)
    published = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=result["artifactManifestSha256"],
    )
    assert published["outcome"] == "PUBLISHED"

    reused = orchestrator_module.run_mode(tmp_path, "start", request="request.json")
    assert reused["outcome"] == "REUSED"

    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    template.parent.mkdir(parents=True)
    shutil.copyfile(SKILL_ROOT / "assets/sow-template.xlsx", template)
    with zipfile.ZipFile(template, "a") as archive:
        archive.comment = b"e2e-render-only-v1"

    rendered = orchestrator_module.run_mode(
        tmp_path,
        "start",
        request="request.json",
    )

    assert rendered["outcome"] == "REQUEST_APPROVAL", rendered
    assert rendered["state"]["route"] == "RENDER_ONLY"
    run_root = tmp_path / ".ai-sow/work/runs" / rendered["state"]["runId"]
    assert not (run_root / "actions").exists()
    assert rendered["artifactManifestSha256"] != result["artifactManifestSha256"]


def test_input_gap_resume_uses_new_revision_and_lowest_stage(tmp_path: Path) -> None:
    request_path = _prepare_project(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request_path)
    assert started["outcome"] == "ACTIVE"
    old_run_id = started["state"]["runId"]
    old_revision = started["state"]["currentInputRevisionSha256"]
    request = _load(tmp_path / request_path)
    request["project"]["name"] = "匿名退款能力交付（补全输入）"
    _write_json(tmp_path / request_path, request)

    resumed = orchestrator_module.run_mode(tmp_path, "resume", request=request_path)

    assert resumed["outcome"] == "ACTIVE"
    assert resumed["state"]["runId"] != old_run_id
    assert resumed["state"]["currentInputRevisionSha256"] != old_revision
    assert resumed["state"]["route"] == "FULL_COMPILE"
    assert _actions(resumed["nextAction"])[0]["promptId"] == "stage1-source-scan-v1"
    old_states = [
        _load(path)
        for path in (
            tmp_path / f".ai-sow/work/runs/{old_run_id}/states"
        ).glob("state-*.json")
    ]
    assert any(
        state["phase"] == "DONE" and state["result"] == "ABANDONED"
        for state in old_states
    )


def test_stage_one_repair_preserves_unaffected_downstream_artifacts(
    tmp_path: Path,
) -> None:
    first, _trace = drive_fixture_host(tmp_path)
    published = orchestrator_module.run_mode(
        tmp_path,
        "approve",
        artifact_manifest_sha256=first["artifactManifestSha256"],
    )
    assert published["outcome"] == "PUBLISHED"
    current = _load(tmp_path / ".ai-sow/current.json")
    manifest = _load(tmp_path / current["generationManifestPath"])
    baseline = _load(tmp_path / manifest["sowModelPath"])
    downstream = {
        collection: copy.deepcopy(baseline[collection])
        for collection in (
            "stories",
            "acceptanceCriteria",
            "tasks",
            "dependencies",
            "effectiveStartMatches",
        )
    }
    request = _load(tmp_path / "request.json")
    request["project"]["name"] = "匿名退款能力交付（增量复核）"
    _write_json(tmp_path / "request.json", request)

    started = orchestrator_module.run_mode(
        tmp_path, "start", request="request.json"
    )
    assert started["state"]["route"] == "DELTA_COMPILE"
    repaired, trace = drive_result_host(tmp_path, started)

    assert repaired["outcome"] == "REQUEST_APPROVAL", repaired
    candidate = _load(tmp_path / repaired["state"]["currentCandidatePath"])
    assert {
        collection: candidate[collection] for collection in downstream
    } == downstream
    assert trace[0]["promptId"] == "stage1-source-scan-v1"
    assert all(
        action["executionPolicy"]["contextPolicy"] == "FRESH_NO_HISTORY"
        for action in trace
    )


def test_parallel_review_and_theme_join_cover_all_roots(tmp_path: Path) -> None:
    result, trace = drive_fixture_host(tmp_path)
    assert result["outcome"] == "REQUEST_APPROVAL"
    by_prompt: dict[str, list[dict[str, object]]] = {}
    for action in trace:
        by_prompt.setdefault(str(action["promptId"]), []).append(action)
    for prompt in ("review-story-design-v1", "review-task-estimation-v1"):
        actions = by_prompt[prompt]
        required = actions[0]["group"]["requiredLogicalShardIds"]
        assert len(actions) > 1
        assert {action["logicalShardId"] for action in actions} == set(required)
        assert all(action["group"]["maxConcurrency"] > 1 for action in actions)
    joins = by_prompt["review-theme-join-v1"]
    assert len(joins) == 2
    files = ProjectFiles.open(tmp_path)
    for action in joins:
        packet = files.read_json(action["packetPath"])
        assert packet["payload"]["leafReviewResultSha256s"]
        assert len(packet["payload"]["leafResults"]) == len(
            packet["payload"]["leafReviewResultSha256s"]
        )


def test_r2_r3_conflict_is_preserved_by_theme_join_and_explicitly_adjudicated(
    tmp_path: Path,
) -> None:
    emitted: set[str] = set()

    def submissions(
        action: Mapping[str, object], packet: Mapping[str, object]
    ) -> dict[str, object]:
        payload = packet["payload"]
        if action["promptId"] in {
            "review-story-design-v1",
            "review-task-estimation-v1",
        } and "feature-refund" in payload["subjectIds"]:
            review_kind = str(payload["reviewKind"])
            if review_kind not in emitted:
                emitted.add(review_kind)
                result = _review_result(action, packet)
                finding_id = (
                    "finding-story-refund-split"
                    if review_kind == "STORY_DESIGN"
                    else "finding-story-refund-keep"
                )
                result["decision"] = "OWNER_FIX_REQUIRED"
                result["findings"] = [
                    {
                        "findingId": finding_id,
                        "type": "OWNER_FIX_REQUIRED",
                        "owner": (
                            "STAGE_2"
                            if review_kind == "STORY_DESIGN"
                            else "STAGE_3"
                        ),
                        "subjectIds": ["feature-refund"],
                        "evidenceIds": [payload["evidenceIds"][0]],
                        "summary": (
                            "退款 Story 应拆分。"
                            if review_kind == "STORY_DESIGN"
                            else "退款 Story 应保持单一边界。"
                        ),
                    }
                ]
                return result
        if action["promptId"] == "review-theme-join-v1":
            result = _review_result(action, packet)
            findings = [
                copy.deepcopy(finding)
                for leaf in payload["leafResults"]
                for finding in leaf["findings"]
            ]
            if findings:
                result["decision"] = "OWNER_FIX_REQUIRED"
                result["findings"] = findings
            return result
        if action["promptId"] == "review-adjudication-v1":
            selected = next(
                finding
                for finding in payload["findings"]
                if finding["findingId"] == "finding-story-refund-split"
            )
            result = _review_result(action, packet)
            result.update(
                {
                    "propositionId": payload["propositionId"],
                    "selectedFindingIds": [selected["findingId"]],
                    "decision": "OWNER_FIX_REQUIRED",
                    "findings": [copy.deepcopy(selected)],
                }
            )
            return result
        return _submission(action, packet)

    result, trace = drive_fixture_host(
        tmp_path,
        submission_factory=submissions,
        terminal_outcomes=("OWNER_FIX_REQUIRED",),
    )

    assert result["outcome"] == "OWNER_FIX_REQUIRED", result
    prompts = [str(action["promptId"]) for action in trace]
    adjudication_index = prompts.index("review-adjudication-v1")
    assert emitted == {"STORY_DESIGN", "TASK_ESTIMATION"}
    assert prompts.index("review-theme-join-v1") < adjudication_index
    action = next(
        action
        for action in trace
        if action["promptId"] == "review-adjudication-v1"
    )
    packet = ProjectFiles.open(tmp_path).read_json(action["packetPath"])
    assert packet["payload"]["findingIds"] == [
        "finding-story-refund-keep",
        "finding-story-refund-split",
    ]
    assert action["executionPolicy"]["contextPolicy"] == "FRESH_NO_HISTORY"


def test_r1_finding_repairs_and_rechecks_scope_before_any_stage_two_action(
    tmp_path: Path,
) -> None:
    first_scope_review = True

    def submissions(
        action: Mapping[str, object], packet: Mapping[str, object]
    ) -> dict[str, object]:
        nonlocal first_scope_review
        if action["promptId"] == "review-source-scope-v1" and first_scope_review:
            first_scope_review = False
            result = _review_result(action, packet)
            result["decision"] = "OWNER_FIX_REQUIRED"
            finding = {
                "findingId": "finding-feature-label",
                "type": "OWNER_FIX_REQUIRED",
                "owner": "STAGE_1",
                "subjectIds": ["feature-refund"],
                "evidenceIds": [packet["payload"]["coverageRootIds"][0]],
                "summary": "Feature 名称需要明确复核标记。",
            }
            result["findings"] = [finding, copy.deepcopy(finding)]
            return result
        if action["promptId"] == "repair-stage1-v1":
            payload = packet["payload"]
            assert [item["findingId"] for item in payload["findings"]] == [
                "finding-feature-label"
            ]
            feature = copy.deepcopy(
                next(
                    item
                    for item in payload["candidate"]["features"]
                    if item["featureId"] == "feature-refund"
                )
            )
            feature["name"] = f"{feature['name']}（已复核）"
            return {
                "contract": "ai-sow-stage-result-v1",
                "resultKind": "PATCH",
                "reviewedEvidenceIds": [
                    item["findingId"] for item in payload["findings"]
                ],
                "replacementSet": {
                    "expectedNodeHashes": {
                        "features:feature-refund": sha256_bytes(
                            canonical_json_bytes(
                                next(
                                    item
                                    for item in payload["candidate"]["features"]
                                    if item["featureId"] == "feature-refund"
                                )
                            )
                        )
                    },
                    "upserts": [{"collection": "features", "node": feature}],
                    "deletes": [],
                },
                "selfCheck": {
                    "completedCheckIds": list(payload["requiredCheckIds"]),
                    "unresolvedItems": [],
                },
            }
        return _submission(action, packet)

    result, trace = drive_fixture_host(
        tmp_path, submission_factory=submissions
    )

    assert result["outcome"] == "REQUEST_APPROVAL", result
    prompts = [str(action["promptId"]) for action in trace]
    repair_index = prompts.index("repair-stage1-v1")
    scope_review_indexes = [
        index
        for index, prompt in enumerate(prompts)
        if prompt == "review-source-scope-v1"
    ]
    story_index = prompts.index("stage2-story-ac-v1")
    assert len(scope_review_indexes) == 2
    assert scope_review_indexes[0] < repair_index < scope_review_indexes[1] < story_index
    candidate = _load(tmp_path / result["state"]["currentCandidatePath"])
    feature = next(
        item for item in candidate["features"] if item["featureId"] == "feature-refund"
    )
    assert feature["name"].endswith("（已复核）")


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
