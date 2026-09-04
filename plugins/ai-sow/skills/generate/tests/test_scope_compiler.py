from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from final_review import (  # noqa: E402
    prepare_r1_scope_join,
    prepare_r1_source_audit,
)
import scope_compiler as scope_compiler_module  # noqa: E402
from scope_compiler import (  # noqa: E402
    build_scope_closure_checkpoint,
    validate_scope_closure_checkpoint,
)
from sow_model import model_skeleton  # noqa: E402


def diagnostic_codes(result: object) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


SOURCE_SCAN_FIXTURE = FIXTURES / "pipeline/stage1/source-scan-results.json"


def source_scan_fixture() -> dict[str, object]:
    return json.loads(SOURCE_SCAN_FIXTURE.read_text(encoding="utf-8"))


def source_scan_state(
    *,
    block_ids: list[str] | None = None,
    token_budget: int | None = None,
) -> dict[str, object]:
    value = source_scan_fixture()
    revision = copy.deepcopy(value["inputRevision"])
    selected = set(block_ids or [item["blockId"] for item in revision["blocks"]])
    revision["blocks"] = [
        block for block in revision["blocks"] if block["blockId"] in selected
    ]
    for source in revision["sources"]:
        source["blockIds"] = [
            block_id for block_id in source["blockIds"] if block_id in selected
        ]
    revision["sources"] = [source for source in revision["sources"] if source["blockIds"]]
    candidate = model_skeleton(value["request"], revision)
    return {
        "contract": "ai-sow-scope-compiler-state-v1",
        "runId": "run-source-scan",
        "inputRevision": revision,
        "sourceContents": {
            block_id: content
            for block_id, content in value["sourceContents"].items()
            if block_id in selected
        },
        "baseCandidate": candidate,
        "baseCandidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        "maxInitialPacketTokens": token_budget
        or value["largeInitialPacketTokenBudget"],
        "maxOutputTokens": 8000,
        "modelProfileId": "author-source-scan-v1",
        "modelConfigSha256": "e" * 64,
        "acceptedRecords": [],
    }


def source_scan_submission(
    spec: dict[str, object],
    *,
    collection: str = "inputItems",
) -> dict[str, object]:
    value = source_scan_fixture()
    block_ids = spec["packet"]["sourceBlockIds"]
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SOURCE_SCAN_PATCH",
        "reviewedEvidenceIds": list(block_ids),
        "blockCoverage": [
            {"blockId": block_id, "disposition": "READ"}
            for block_id in block_ids
        ],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": [
                {
                    "collection": collection,
                    "node": copy.deepcopy(value["resultItemsByBlockId"][block_id]),
                }
                for block_id in block_ids
            ],
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": list(value["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def source_scan_record(
    state: dict[str, object],
    spec: dict[str, object],
    submission: dict[str, object] | None = None,
) -> dict[str, object]:
    result = submission or source_scan_submission(spec)
    packet_payload = canonical_json_bytes(
        {
            "logicalShardId": spec["logicalShardId"],
            "payload": spec["packet"],
            "evidenceCatalog": spec["evidenceCatalog"],
        }
    )
    result_payload = canonical_json_bytes(result)
    return {
        "contract": "ai-sow-action-record-v1",
        "runId": state["runId"],
        "actionId": f"action-{spec['logicalShardId']}",
        "logicalShardId": spec["logicalShardId"],
        "envelopeSha256": "a" * 64,
        "packetSha256": sha256_bytes(packet_payload),
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(state["inputRevision"])
        ),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "executionAttempt": 1,
        "status": "SUCCESS",
        "timing": {
            "queueMilliseconds": 0,
            "executionMilliseconds": 10,
            "actionMilliseconds": 10,
        },
        "modelAttempts": 1,
        "toolAttempts": 0,
        "initialPacket": {
            "bytes": len(packet_payload),
            "tokens": max(1, (len(packet_payload) + 3) // 4),
        },
        "hydrationLog": [],
        "usage": {
            "accountingMode": "LOCALLY_ESTIMATED",
            "inputTokens": max(1, (len(packet_payload) + 3) // 4),
            "cachedInputTokens": 0,
            "outputTokens": max(1, (len(result_payload) + 3) // 4),
            "reasoningTokens": None,
            "tokenizerId": "utf8-bytes-div-4",
            "tokenizerVersion": "1",
        },
        "controlPlaneTokens": 0,
        "resultPath": f"work/{spec['logicalShardId']}/submission.json",
        "submissionSha256": sha256_bytes(result_payload),
        "submission": result,
        "failure": None,
        "completedAt": "2026-09-04T00:00:00Z",
    }


def test_source_scan_packets_partition_primary_blocks_and_include_full_inventory() -> None:
    value = source_scan_fixture()
    small_state = source_scan_state(
        block_ids=value["smallBlockIds"],
        token_budget=value["smallInitialPacketTokenBudget"],
    )
    small = scope_compiler_module.prepare_action(small_state, "SOURCE_SCAN")
    large_state = source_scan_state()
    large = scope_compiler_module.prepare_action(large_state, "SOURCE_SCAN")

    assert small["outcome"] == "ACTION_REQUIRED"
    assert len(small["specs"]) == 1
    assert large["outcome"] == "ACTION_REQUIRED"
    assert len(large["specs"]) > 1
    expected_roots = [
        block["primaryCoverageBlockId"]
        for block in large_state["inputRevision"]["blocks"]
    ]
    assigned = [
        block_id
        for spec in large["specs"]
        for block_id in spec["packet"]["sourceBlockIds"]
    ]
    assert assigned == expected_roots
    assert len(assigned) == len(set(assigned))
    inventories = [spec["packet"]["fullBlockInventory"] for spec in large["specs"]]
    counts = [spec["packet"]["sourceStructureCounts"] for spec in large["specs"]]
    assert all(item == inventories[0] for item in inventories)
    assert all(item == counts[0] for item in counts)
    assert [item["blockId"] for item in inventories[0]] == expected_roots
    for spec in large["specs"]:
        assert [item["evidenceId"] for item in spec["evidenceCatalog"]] == (
            spec["packet"]["sourceBlockIds"]
        )
        assert spec["packet"]["instructionBindings"] == [
            {
                "path": path,
                "sha256": sha256_bytes((SKILL_ROOT / path).read_bytes()),
            }
            for path in (
                "prompts/fragments/roles/author.md",
                "prompts/fragments/outputs/author-result.md",
                "prompts/stage1-source-scan.md",
                "references/source-authority.md",
            )
        ]
    assert all(
        spec["packet"]["allowedWriteCollections"] == ["inputItems"]
        and "featureIds" not in spec["packet"]
        for spec in large["specs"]
    )


def test_source_scan_result_requires_read_or_parse_disposition_for_every_root() -> None:
    value = source_scan_fixture()
    state = source_scan_state(
        block_ids=value["smallBlockIds"],
        token_budget=value["smallInitialPacketTokenBudget"],
    )
    prepared = scope_compiler_module.prepare_action(state, "SOURCE_SCAN")
    spec = prepared["specs"][0]
    submission = source_scan_submission(spec)
    submission["blockCoverage"].pop()
    record = source_scan_record(state, spec, submission)

    progress = scope_compiler_module.accept_result(state, record)

    assert progress.outcome == "FAILED"
    assert [item.code for item in progress.diagnostics] == [
        "SOURCE_BLOCK_COVERAGE_INCOMPLETE"
    ]


def test_input_items_preserve_qualifiers_and_exact_source_refs() -> None:
    value = source_scan_fixture()
    state = source_scan_state(
        block_ids=value["smallBlockIds"],
        token_budget=value["smallInitialPacketTokenBudget"],
    )
    prepared = scope_compiler_module.prepare_action(state, "SOURCE_SCAN")
    records = [
        source_scan_record(state, spec) for spec in prepared["specs"]
    ]

    result = scope_compiler_module.apply_ready_group(state, records)

    expected = [
        value["resultItemsByBlockId"][block_id]
        for block_id in value["smallBlockIds"]
    ]
    assert result.diagnostics == ()
    assert result.model["inputItems"] == expected
    assert result.model["inputItems"][0]["conditions"] == [
        "当单笔退款金额超过 5000 元时"
    ]
    assert result.model["inputItems"][0]["thresholds"] == [
        "单笔退款金额 > 5000 元"
    ]
    assert result.model["inputItems"][0]["prohibitions"] == ["不得自动放行"]
    assert result.model["inputItems"][0]["applicableScopes"] == ["境内订单"]
    assert result.model["inputItems"][0]["sourceRefs"][0] == {
        "sourceId": "prd-main",
        "blockId": "block-prd-001",
        "sha256": "ee5825836cc0b035161159f377389c517becb2fe13cfdf54919cfbb23ee9d33c",
        "locator": "heading:退款规则/paragraph:1",
    }


def test_source_scan_cannot_write_epics_features_stories_or_tasks() -> None:
    value = source_scan_fixture()
    state = source_scan_state(
        block_ids=value["smallBlockIds"],
        token_budget=value["smallInitialPacketTokenBudget"],
    )
    prepared = scope_compiler_module.prepare_action(state, "SOURCE_SCAN")
    spec = prepared["specs"][0]

    for collection in ("epics", "features", "stories", "tasks"):
        submission = source_scan_submission(spec, collection=collection)
        progress = scope_compiler_module.accept_result(
            state, source_scan_record(state, spec, submission)
        )
        assert progress.outcome == "FAILED"
        assert "OWNER_WRITE_SCOPE_VIOLATION" in {
            item.code for item in progress.diagnostics
        }


def test_global_scope_capacity_exceeded_fails_before_partial_join() -> None:
    state = source_scan_state(token_budget=1)

    prepared = scope_compiler_module.prepare_action(state, "SOURCE_SCAN")

    assert prepared["outcome"] == "CONTRACT_UNSUPPORTED"
    assert prepared["specs"] == []
    assert [item["code"] for item in prepared["diagnostics"]] == [
        "GLOBAL_SCOPE_CAPACITY_EXCEEDED"
    ]


def test_source_scan_waits_for_all_siblings_before_one_candidate_apply() -> None:
    state = source_scan_state()
    prepared = scope_compiler_module.prepare_action(state, "SOURCE_SCAN")
    assert len(prepared["specs"]) > 1
    records = [source_scan_record(state, spec) for spec in prepared["specs"]]
    candidate_before = canonical_json_bytes(state["baseCandidate"])

    first_state = {**state, "acceptedRecords": [records[0]]}
    progress = scope_compiler_module.accept_result(state, records[0])

    assert progress.outcome == "ACTION_REQUIRED"
    assert canonical_json_bytes(state["baseCandidate"]) == candidate_before
    incomplete = scope_compiler_module.apply_ready_group(first_state, [records[0]])
    assert [item.code for item in incomplete.diagnostics] == [
        "SOURCE_SCAN_GROUP_INCOMPLETE"
    ]
    completed = scope_compiler_module.apply_ready_group(state, records)
    assert completed.diagnostics == ()
    assert completed.model_sha256 != state["baseCandidateSha256"]


SCOPE_JOIN_FIXTURE = FIXTURES / "pipeline/stage1/scope-join-result.json"


def scope_join_fixture() -> dict[str, object]:
    return json.loads(SCOPE_JOIN_FIXTURE.read_text(encoding="utf-8"))


def scope_proposal_state() -> dict[str, object]:
    value = scope_join_fixture()
    candidate = model_skeleton(value["request"], value["inputRevision"])
    candidate["inputItems"] = copy.deepcopy(value["inputItems"])
    return {
        "contract": "ai-sow-scope-compiler-state-v1",
        "actionKind": "SCOPE_PROPOSAL",
        "runId": "run-scope-join",
        "inputRevision": copy.deepcopy(value["inputRevision"]),
        "baseCandidate": candidate,
        "baseCandidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        "maxInitialPacketTokens": 2400,
        "maxOutputTokens": 8000,
        "modelProfileId": "author-scope-v1",
        "modelConfigSha256": "f" * 64,
        "acceptedRecords": [],
    }


def scope_proposal_submission(spec: dict[str, object]) -> dict[str, object]:
    value = scope_join_fixture()
    input_by_id = {
        item["inputItemId"]: item for item in value["inputItems"]
    }
    item_ids = list(spec["packet"]["assignedInputItemIds"])
    scope_classes = {
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
        "reviewedEvidenceIds": list(item_ids),
        "inputItemIds": list(item_ids),
        "boundaryCandidates": [
            {
                "boundaryId": f"boundary-{item_id}",
                "inputItemIds": [item_id],
                "boundarySummary": input_by_id[item_id]["text"],
                "scopeClass": scope_classes[item_id],
                "affinityKeys": [
                    "affinity-refund"
                    if item_id in {"input-refund", "input-demo-retry", "input-refund-event"}
                    else f"affinity-{item_id}"
                ],
                "independentClosureEvidence": ["来源保留独立交付边界判断。"],
            }
            for item_id in item_ids
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
                    if item_id in spec["packet"]["inputItemIdInventory"]
                ],
                "rationale": "退款需求、界面行为和已批准集成设计需要在全局合并。",
            }
        ],
        "selfCheck": {
            "completedCheckIds": list(value["requiredProposalCheckIds"]),
            "unresolvedItems": [],
        },
    }


def scope_join_state() -> dict[str, object]:
    proposal_state = scope_proposal_state()
    prepared = scope_compiler_module.prepare_action(
        proposal_state, "SCOPE_PROPOSAL"
    )
    proposal_records = [
        source_scan_record(
            proposal_state,
            spec,
            scope_proposal_submission(spec),
        )
        for spec in prepared["specs"]
    ]
    return {
        **proposal_state,
        "actionKind": "SCOPE_JOIN",
        "proposalRecords": proposal_records,
        "proposalMaxInitialPacketTokens": proposal_state[
            "maxInitialPacketTokens"
        ],
        "maxInitialPacketTokens": 20000,
    }


def execute_scope_join(
    submission: dict[str, object] | None = None,
):
    value = scope_join_fixture()
    state = scope_join_state()
    prepared = scope_compiler_module.prepare_action(state, "SCOPE_JOIN")
    assert prepared["outcome"] == "ACTION_REQUIRED"
    record = source_scan_record(
        state,
        prepared["specs"][0],
        submission or copy.deepcopy(value["joinSubmission"]),
    )
    return state, record, scope_compiler_module.apply_ready_group(state, [record])


def test_scope_proposal_sees_global_inventory_but_cannot_finalize_feature_ownership() -> None:
    state = scope_proposal_state()
    prepared = scope_compiler_module.prepare_action(state, "SCOPE_PROPOSAL")

    assert prepared["outcome"] == "ACTION_REQUIRED"
    assert len(prepared["specs"]) > 1
    expected_ids = [item["inputItemId"] for item in state["baseCandidate"]["inputItems"]]
    assigned_ids = []
    records = []
    for spec in prepared["specs"]:
        packet = spec["packet"]
        assert packet["inputItemIdInventory"] == expected_ids
        assert packet["mayFinalizeFeatureOwnership"] is False
        assert packet["allowedWriteCollections"] == []
        assert "featureIds" not in packet
        assigned_ids.extend(packet["assignedInputItemIds"])
        records.append(
            source_scan_record(state, spec, scope_proposal_submission(spec))
        )
    assert assigned_ids == expected_ids
    assert len(assigned_ids) == len(set(assigned_ids))

    result = scope_compiler_module.apply_ready_group(state, records)
    assert result.diagnostics == ()
    assert canonical_json_bytes(result.model) == canonical_json_bytes(
        state["baseCandidate"]
    )
    assert result.checkpoint["kind"] == "SCOPE_PROPOSAL"


def test_scope_join_closes_every_input_item_exactly_once() -> None:
    state, _record, result = execute_scope_join()

    assert result.diagnostics == ()
    input_ids = [item["inputItemId"] for item in state["baseCandidate"]["inputItems"]]
    closure_ids = [item["inputItemId"] for item in result.model["scopeClosure"]]
    assert sorted(closure_ids) == sorted(input_ids)
    assert len(closure_ids) == len(set(closure_ids))


def test_prd_and_selected_demo_form_requirement_union() -> None:
    _state, _record, result = execute_scope_join()

    feature = next(
        item for item in result.model["features"] if item["featureId"] == "feature-refund"
    )
    assert set(feature["requirementRefs"]) == {"input-refund", "input-demo-retry"}


def test_demo_cannot_prove_backend_data_integration_or_deployment_design() -> None:
    value = scope_join_fixture()
    submission = copy.deepcopy(value["joinSubmission"])
    design = next(
        wrapper["node"]
        for wrapper in submission["replacementSet"]["upserts"]
        if wrapper["collection"] == "designItems"
    )
    demo_item = next(
        item for item in value["inputItems"] if item["inputItemId"] == "input-demo-retry"
    )
    design["sourceRefs"] = copy.deepcopy(demo_item["sourceRefs"])
    state = scope_join_state()
    prepared = scope_compiler_module.prepare_action(state, "SCOPE_JOIN")
    record = source_scan_record(state, prepared["specs"][0], submission)

    progress = scope_compiler_module.accept_result(state, record)

    assert progress.outcome == "FAILED"
    assert "DESIGN_SOURCE_AUTHORITY_VIOLATION" in {
        item.code for item in progress.diagnostics
    }


def test_policy_instances_include_required_go_live_default_automation_and_source_gated_migration() -> None:
    _state, _record, result = execute_scope_join()

    policies = {item["policyId"]: item for item in result.model["policyInstances"]}
    assert policies["policy-sit-automation"]["inclusionPolicy"] == "DEFAULT_INCLUDED"
    assert policies["policy-uat-automation"]["inclusionPolicy"] == "DEFAULT_INCLUDED"
    assert policies["policy-go-live"]["inclusionPolicy"] == "REQUIRED"
    assert policies["policy-data-migration"]["inclusionPolicy"] == "SOURCE_GATED"
    assert policies["policy-data-migration"]["sourceRefs"]


def test_migration_policy_is_absent_without_source_gate() -> None:
    value = scope_join_fixture()
    proposal_state = scope_proposal_state()
    proposal_state["baseCandidate"]["inputItems"] = [
        item
        for item in proposal_state["baseCandidate"]["inputItems"]
        if item["inputItemId"] != "input-migration"
    ]
    proposal_state["baseCandidateSha256"] = sha256_bytes(
        canonical_json_bytes(proposal_state["baseCandidate"])
    )
    proposal_prepared = scope_compiler_module.prepare_action(
        proposal_state, "SCOPE_PROPOSAL"
    )
    proposal_records = [
        source_scan_record(
            proposal_state,
            spec,
            scope_proposal_submission(spec),
        )
        for spec in proposal_prepared["specs"]
    ]
    state = {
        **proposal_state,
        "actionKind": "SCOPE_JOIN",
        "proposalRecords": proposal_records,
        "proposalMaxInitialPacketTokens": proposal_state[
            "maxInitialPacketTokens"
        ],
        "maxInitialPacketTokens": 20000,
    }
    submission = copy.deepcopy(value["joinSubmission"])
    submission["reviewedEvidenceIds"].remove("input-migration")
    submission["replacementSet"]["upserts"] = [
        wrapper
        for wrapper in submission["replacementSet"]["upserts"]
        if not (
            wrapper["collection"] == "scopeClosure"
            and wrapper["node"]["inputItemId"] == "input-migration"
        )
        and not (
            wrapper["collection"] == "features"
            and wrapper["node"]["featureId"] == "feature-data-migration"
        )
        and not (
            wrapper["collection"] == "policyInstances"
            and wrapper["node"]["policyId"] == "policy-data-migration"
        )
    ]
    for wrapper in submission["replacementSet"]["upserts"]:
        node = wrapper["node"]
        if wrapper["collection"] == "epics" and node["epicId"] == "epic-platform":
            node["requirementRefs"].remove("input-migration")
            node["policyRefs"].remove("policy-instance-migration")
        if wrapper["collection"] == "policyInstances":
            targets = node["targetNodeIds"]
            if "feature-data-migration" in targets:
                targets.remove("feature-data-migration")
    prepared = scope_compiler_module.prepare_action(state, "SCOPE_JOIN")
    record = source_scan_record(state, prepared["specs"][0], submission)

    result = scope_compiler_module.apply_ready_group(state, [record])

    assert result.diagnostics == ()
    assert "policy-data-migration" not in {
        item["policyId"] for item in result.model["policyInstances"]
    }


def test_business_technical_delivery_is_independent_from_source_role() -> None:
    _state, _record, result = execute_scope_join()

    features = {item["featureId"]: item for item in result.model["features"]}
    assert features["feature-refund"]["scopeClass"] == "BUSINESS"
    assert features["feature-i18n"]["scopeClass"] == "TECHNICAL"
    assert features["feature-shared-pipeline"]["scopeClass"] == "DELIVERY"
    pipeline_features = [
        item
        for item in result.model["features"]
        if "input-shared-pipeline" in item["requirementRefs"]
    ]
    assert [item["featureId"] for item in pipeline_features] == [
        "feature-shared-pipeline"
    ]


def test_source_conflict_returns_input_required_without_silent_precedence() -> None:
    state = scope_join_state()
    conflict = copy.deepcopy(state["baseCandidate"]["inputItems"][0])
    conflict["inputItemId"] = "input-source-conflict"
    conflict["kind"] = "CONFLICT_CANDIDATE"
    conflict["text"] = "PRD 与 HLD 对退款补偿责任方冲突。"
    state["baseCandidate"]["inputItems"].append(conflict)
    state["baseCandidateSha256"] = sha256_bytes(
        canonical_json_bytes(state["baseCandidate"])
    )

    prepared = scope_compiler_module.prepare_action(state, "SCOPE_JOIN")

    assert prepared["outcome"] == "INPUT_REQUIRED"
    assert prepared["specs"] == []
    assert [item["code"] for item in prepared["diagnostics"]] == [
        "SOURCE_SEMANTIC_CONFLICT"
    ]


def stage_one_checkpoint_state() -> dict[str, object]:
    value = scope_join_fixture()
    source_contents = {
        item["sourceRefs"][0]["blockId"]: item["text"]
        for item in value["inputItems"]
    }
    scan_candidate = model_skeleton(value["request"], value["inputRevision"])
    scan_state = {
        "contract": "ai-sow-scope-compiler-state-v1",
        "runId": "run-r1-scope",
        "inputRevision": copy.deepcopy(value["inputRevision"]),
        "sourceContents": source_contents,
        "baseCandidate": scan_candidate,
        "baseCandidateSha256": sha256_bytes(
            canonical_json_bytes(scan_candidate)
        ),
        "maxInitialPacketTokens": 20000,
        "maxOutputTokens": 8000,
        "modelProfileId": "author-source-scan-v1",
        "modelConfigSha256": "e" * 64,
        "acceptedRecords": [],
    }
    scan_prepared = scope_compiler_module.prepare_action(scan_state, "SOURCE_SCAN")
    assert scan_prepared["outcome"] == "ACTION_REQUIRED"
    item_by_block = {
        item["sourceRefs"][0]["blockId"]: item for item in value["inputItems"]
    }
    scan_spec = scan_prepared["specs"][0]
    roots = list(scan_spec["packet"]["coverageRootIds"])
    scan_submission = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SOURCE_SCAN_PATCH",
        "reviewedEvidenceIds": roots,
        "blockCoverage": [
            {"blockId": block_id, "disposition": "READ"}
            for block_id in roots
        ],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": [
                {
                    "collection": "inputItems",
                    "node": copy.deepcopy(item_by_block[block_id]),
                }
                for block_id in roots
            ],
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": [
                "SOURCE_BLOCK_COVERAGE",
                "SOURCE_ATOMICITY",
                "QUALIFIER_PRESERVATION",
                "SOURCE_CONFLICT",
            ],
            "unresolvedItems": [],
        },
    }
    scan_record = source_scan_record(scan_state, scan_spec, scan_submission)

    join_state, _join_record, join_result = execute_scope_join()
    assert join_result.diagnostics == ()
    audit_state = {
        "runId": "run-r1-scope",
        "reviewSetId": "review-r1-scope",
        "inputRevision": copy.deepcopy(value["inputRevision"]),
        "sourceContents": source_contents,
        "scopeCandidate": join_result.model,
        "maxInitialPacketTokens": 3000,
        "maxOutputTokens": 4000,
        "modelProfileId": "reviewer-r1-v1",
        "modelConfigSha256": "9" * 64,
    }
    audit_prepared = prepare_r1_source_audit(audit_state)
    assert audit_prepared["outcome"] == "ACTION_REQUIRED"
    audit_template = json.loads(
        (FIXTURES / "pipeline/stage1/r1-source-audit-results.json").read_text(
            encoding="utf-8"
        )
    )["passResultTemplate"]
    audit_results = []
    for index, spec in enumerate(audit_prepared["specs"], 1):
        result = copy.deepcopy(audit_template)
        result.update(
            {
                "reviewResultId": f"r1-source-result-{index:03d}",
                "reviewPlanSha256": audit_prepared["reviewPlanSha256"],
                "candidateProjectionSha256": audit_prepared[
                    "sourceProjectionSha256"
                ],
                "coverageSha256": spec["packet"]["coverageSha256"],
                "sourceAuditCoverageUnion": list(
                    spec["packet"]["coverageRootIds"]
                ),
            }
        )
        audit_results.append(
            {"logicalShardId": spec["logicalShardId"], "result": result}
        )
    scope_state = {
        **audit_state,
        "sourceAuditResults": audit_results,
        "auditMaxInitialPacketTokens": audit_state[
            "maxInitialPacketTokens"
        ],
        "maxInitialPacketTokens": 30000,
    }
    r1_scope_prepared = prepare_r1_scope_join(scope_state)
    assert r1_scope_prepared["outcome"] == "ACTION_REQUIRED"
    scope_template = json.loads(
        (FIXTURES / "pipeline/stage1/r1-scope-join-result.json").read_text(
            encoding="utf-8"
        )
    )["passResultTemplate"]
    r1_scope_result = copy.deepcopy(scope_template)
    r1_scope_result.update(
        {
            "reviewPlanSha256": r1_scope_prepared["reviewPlanSha256"],
            "candidateProjectionSha256": r1_scope_prepared[
                "candidateProjectionSha256"
            ],
            "coverageSha256": r1_scope_prepared["coverageSha256"],
            "sourceAuditCoverageUnion": list(
                r1_scope_prepared["coverageRootIds"]
            ),
        }
    )
    return {
        "runId": "run-r1-scope",
        "inputRevision": copy.deepcopy(value["inputRevision"]),
        "candidate": copy.deepcopy(join_result.model),
        "actionRecords": [scan_record],
        "proposalRecords": copy.deepcopy(join_state["proposalRecords"]),
        "r1SourceResults": audit_results,
        "r1ScopeResult": r1_scope_result,
        "upstreamCheckpointSha256s": [],
    }


def test_scope_checkpoint_binds_stage_one_projection_r1_and_policy_definition() -> None:
    state = stage_one_checkpoint_state()

    result = build_scope_closure_checkpoint(state)

    assert result["outcome"] == "READY_FOR_STORY_AC"
    checkpoint = result["checkpoint"]
    fixture = json.loads(
        (
            FIXTURES
            / "pipeline/stage1/scope-closure-checkpoint.json"
        ).read_text(encoding="utf-8")
    )["checkpoint"]
    assert set(checkpoint) == set(fixture)
    assert "effectivePolicyDecisionSha256" not in checkpoint
    assert checkpoint["policyDefinitionSha256"] == state["inputRevision"][
        "deliveryPolicySha256"
    ]
    assert len(checkpoint["reviewResultSha256s"]) == (
        len(state["r1SourceResults"]) + 1
    )
    assert checkpoint["actionRecordSha256s"] == [
        sha256_bytes(canonical_json_bytes(state["actionRecords"][0]))
    ]


def test_design_coverage_requires_mechanical_and_semantic_sufficiency() -> None:
    state = stage_one_checkpoint_state()
    closure = next(
        item
        for item in state["candidate"]["scopeClosure"]
        if item["inputItemId"] == "input-i18n"
    )
    assert closure["mechanicalCoverage"] == "COMPLETE"
    assert closure["semanticSufficiency"] == "SUFFICIENT"
    assert build_scope_closure_checkpoint(state)["outcome"] == (
        "READY_FOR_STORY_AC"
    )

    mechanical_gap = copy.deepcopy(state)
    closure = next(
        item
        for item in mechanical_gap["candidate"]["scopeClosure"]
        if item["inputItemId"] == "input-i18n"
    )
    closure.update(
        {
            "mechanicalCoverage": "MISSING",
            "semanticSufficiency": "NOT_REVIEWED",
            "designCoverageStatus": "MISSING",
        }
    )
    mechanical_result = build_scope_closure_checkpoint(mechanical_gap)
    assert mechanical_result["outcome"] == "INPUT_REQUIRED"
    assert mechanical_result["questions"][0]["requiredSourceRole"] == (
        "APPROVED_DESIGN"
    )

    semantic_gap = copy.deepcopy(state)
    closure = next(
        item
        for item in semantic_gap["candidate"]["scopeClosure"]
        if item["inputItemId"] == "input-i18n"
    )
    closure.update(
        {
            "semanticSufficiency": "INSUFFICIENT",
            "designCoverageStatus": "MISSING",
        }
    )
    assert build_scope_closure_checkpoint(semantic_gap)["outcome"] == (
        "INPUT_REQUIRED"
    )


def test_scope_checkpoint_survives_downstream_additions() -> None:
    state = stage_one_checkpoint_state()
    built = build_scope_closure_checkpoint(state)
    checkpoint = built["checkpoint"]
    downstream = copy.deepcopy(state)
    downstream["candidate"]["stories"] = [
        {
            "storyId": "story-refund",
            "featureId": "feature-refund",
            "name": "提交退款并查看结果",
            "coverageSet": ["退款申请"],
            "requirementRefs": ["input-refund"],
            "designRefs": [],
            "policyRefs": [],
            "uatApplicable": True,
        }
    ]

    assert validate_scope_closure_checkpoint(checkpoint, downstream) == ()


def test_scope_or_qualifier_change_invalidates_scope_checkpoint() -> None:
    state = stage_one_checkpoint_state()
    checkpoint = build_scope_closure_checkpoint(state)["checkpoint"]

    changed_scope = copy.deepcopy(state)
    changed_scope["candidate"]["features"][0]["name"] += "变更"
    assert "SCOPE_CHECKPOINT_BINDING_STALE" in {
        item.code
        for item in validate_scope_closure_checkpoint(
            checkpoint, changed_scope
        )
    }

    changed_qualifier = copy.deepcopy(state)
    changed_qualifier["candidate"]["scopeClosure"][0][
        "preservedQualifiers"
    ].append("新增限定")
    assert "SCOPE_CHECKPOINT_BINDING_STALE" in {
        item.code
        for item in validate_scope_closure_checkpoint(
            checkpoint, changed_qualifier
        )
    }
