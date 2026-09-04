from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from final_review import (  # noqa: E402
    prepare_r1_scope_join,
    prepare_r1_source_audit,
    r1_results_reusable,
    validate_r1_scope_join_result,
    validate_r1_source_audit_result,
)
import orchestrator as orchestrator_module  # noqa: E402
from sow_model import apply_replacement, model_skeleton  # noqa: E402


R1_SCOPE_INPUT = SKILL_ROOT / "fixtures/pipeline/stage1/scope-join-result.json"
R1_SOURCE_RESULTS = (
    SKILL_ROOT / "fixtures/pipeline/stage1/r1-source-audit-results.json"
)
R1_SCOPE_RESULTS = (
    SKILL_ROOT / "fixtures/pipeline/stage1/r1-scope-join-result.json"
)


def r1_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def r1_base_state() -> dict[str, object]:
    value = r1_fixture(R1_SCOPE_INPUT)
    candidate = model_skeleton(value["request"], value["inputRevision"])
    candidate["inputItems"] = copy.deepcopy(value["inputItems"])
    outcome = apply_replacement(
        candidate,
        value["joinSubmission"]["replacementSet"],
        owner_stage="STAGE_1",
    )
    assert outcome.diagnostics == ()
    source_contents = {
        item["sourceRefs"][0]["blockId"]: item["text"]
        for item in value["inputItems"]
    }
    return {
        "runId": "run-r1-scope",
        "reviewSetId": "review-r1-scope",
        "inputRevision": copy.deepcopy(value["inputRevision"]),
        "sourceContents": source_contents,
        "scopeCandidate": outcome.candidate,
        "maxInitialPacketTokens": 3000,
        "maxOutputTokens": 4000,
        "modelProfileId": "reviewer-r1-v1",
        "modelConfigSha256": "9" * 64,
    }


def bound_source_audit_results(
    state: dict[str, object],
    prepared: dict[str, object],
) -> list[dict[str, object]]:
    template = r1_fixture(R1_SOURCE_RESULTS)["passResultTemplate"]
    results = []
    for index, spec in enumerate(prepared["specs"], 1):
        result = copy.deepcopy(template)
        result.update(
            {
                "reviewResultId": f"r1-source-result-{index:03d}",
                "reviewSetId": state["reviewSetId"],
                "runId": state["runId"],
                "reviewPlanSha256": prepared["reviewPlanSha256"],
                "candidateProjectionSha256": prepared[
                    "sourceProjectionSha256"
                ],
                "coverageSha256": spec["packet"]["coverageSha256"],
                "sourceAuditCoverageUnion": list(
                    spec["packet"]["coverageRootIds"]
                ),
            }
        )
        assert validate_r1_source_audit_result(
            state,
            prepared,
            spec["logicalShardId"],
            result,
        ) == ()
        results.append(
            {"logicalShardId": spec["logicalShardId"], "result": result}
        )
    return results


def r1_scope_state() -> tuple[dict[str, object], dict[str, object]]:
    state = r1_base_state()
    audit_prepared = prepare_r1_source_audit(state)
    assert audit_prepared["outcome"] == "ACTION_REQUIRED"
    state.update(
        {
            "sourceAuditResults": bound_source_audit_results(
                state, audit_prepared
            ),
            "auditMaxInitialPacketTokens": state["maxInitialPacketTokens"],
            "maxInitialPacketTokens": 30000,
        }
    )
    prepared = prepare_r1_scope_join(state)
    assert prepared["outcome"] == "ACTION_REQUIRED", prepared.get(
        "diagnostics"
    )
    return state, prepared


def bound_scope_result(
    state: dict[str, object],
    prepared: dict[str, object],
    template_name: str = "passResultTemplate",
) -> dict[str, object]:
    result = copy.deepcopy(r1_fixture(R1_SCOPE_RESULTS)[template_name])
    result.update(
        {
            "reviewSetId": state["reviewSetId"],
            "runId": state["runId"],
            "reviewPlanSha256": prepared["reviewPlanSha256"],
            "candidateProjectionSha256": prepared[
                "candidateProjectionSha256"
            ],
            "coverageSha256": prepared["coverageSha256"],
            "sourceAuditCoverageUnion": list(prepared["coverageRootIds"]),
        }
    )
    return result


def test_r1_source_audit_never_receives_author_input_item_patch() -> None:
    state = r1_base_state()
    prepared = prepare_r1_source_audit(state)

    assert prepared["outcome"] == "ACTION_REQUIRED"
    assert len(prepared["specs"]) > 1
    expected_roots = prepared["coverageRootIds"]
    assigned = []
    for spec in prepared["specs"]:
        validated_spec, packet_payload = orchestrator_module._validated_action_spec(
            spec
        )
        assert validated_spec["role"] == "REVIEWER"
        assert packet_payload
        packet = spec["packet"]
        assert packet["authorPatchVisible"] is False
        assert "scopeCandidate" not in packet
        assert "inputItems" not in packet
        assert packet["allCoverageRootIds"] == expected_roots
        assigned.extend(packet["coverageRootIds"])
    assert assigned == expected_roots
    assert len(assigned) == len(set(assigned))


def test_r1_scope_join_binds_all_ordered_audit_leaf_hashes() -> None:
    state, prepared = r1_scope_state()
    validated_spec, packet_payload = orchestrator_module._validated_action_spec(
        prepared["specs"][0]
    )
    assert validated_spec["stage"] == "SOURCE_SCOPE"
    assert packet_payload

    ordered = prepared["orderedAuditResultHashes"]
    assert [item["logicalShardId"] for item in ordered] == sorted(
        item["logicalShardId"] for item in state["sourceAuditResults"]
    )
    expected = {
        item["logicalShardId"]: sha256_bytes(
            canonical_json_bytes(item["result"])
        )
        for item in state["sourceAuditResults"]
    }
    assert ordered == [
        {
            "logicalShardId": shard_id,
            "reviewResultSha256": expected[shard_id],
        }
        for shard_id in sorted(expected)
    ]
    assert prepared["specs"][0]["packet"]["orderedAuditResultHashes"] == ordered


def test_r1_scope_join_detects_missing_qualifier_integration_and_nfr() -> None:
    state, prepared = r1_scope_state()
    result = bound_scope_result(state, prepared, "defectResultTemplate")

    diagnostics = validate_r1_scope_join_result(state, prepared, result)

    assert diagnostics == ()
    assert result["decision"] == "OWNER_FIX_REQUIRED"
    assert {item["findingId"] for item in result["findings"]} == {
        "finding-missing-qualifier",
        "finding-missing-integration",
        "finding-missing-nfr",
    }


def test_r1_scope_join_diagnoses_conflicting_duplicate_finding_ids() -> None:
    state, prepared = r1_scope_state()
    result = bound_scope_result(state, prepared, "defectResultTemplate")
    duplicate = copy.deepcopy(result["findings"][0])
    duplicate["summary"] += "冲突改写"
    result["findings"].append(duplicate)

    diagnostics = validate_r1_scope_join_result(state, prepared, result)

    assert "REVIEW_FINDING_ID_CONFLICT" in {
        item.code for item in diagnostics
    }


def test_r1_source_union_is_exact_for_multi_shard_audit() -> None:
    state, prepared = r1_scope_state()
    result = bound_scope_result(state, prepared)
    assert validate_r1_scope_join_result(state, prepared, result) == ()

    result["sourceAuditCoverageUnion"].pop()
    diagnostics = validate_r1_scope_join_result(state, prepared, result)

    assert "R1_SCOPE_RESULT_BINDING_MISMATCH" in {
        item.code for item in diagnostics
    }


def test_r1_pass_is_invalid_after_stage_one_projection_or_source_change() -> None:
    state, prepared = r1_scope_state()
    result = bound_scope_result(state, prepared)
    assert r1_results_reusable(state, result)

    changed_candidate = copy.deepcopy(state)
    changed_candidate["scopeCandidate"]["features"][0]["name"] += "变更"
    assert not r1_results_reusable(changed_candidate, result)

    changed_source = copy.deepcopy(state)
    changed_source["inputRevision"]["sources"][0]["status"] = "SELECTED"
    assert not r1_results_reusable(changed_source, result)
