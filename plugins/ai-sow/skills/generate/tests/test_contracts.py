from __future__ import annotations

import copy
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SKILL_ROOT = Path(__file__).parents[1]
CONTRACTS = SKILL_ROOT / "contracts"
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    load_schema_registry,
    validate_contract,
    validate_final_review,
    validate_generation_hash_closure,
    validate_id_decisions,
)
from models import Diagnostic  # noqa: E402
from questions import question_sha256, validate_question_answers  # noqa: E402


SCHEMA_IDS = {
    "common.schema.json": "urn:ai-sow:generate:common:1",
    "question.schema.json": "urn:ai-sow:generate:question:1",
    "request.schema.json": "urn:ai-sow:generate:request:1",
    "input-manifest.schema.json": "urn:ai-sow:generate:input-manifest:1",
    "scope-bundle.schema.json": "urn:ai-sow:generate:scope-bundle:1",
    "delivery-bundle.schema.json": "urn:ai-sow:generate:delivery-bundle:1",
    "scope-slice.schema.json": "urn:ai-sow:generate:scope-slice:1",
    "delivery-slice.schema.json": "urn:ai-sow:generate:delivery-slice:1",
    "id-decisions.schema.json": "urn:ai-sow:generate:id-decisions:1",
    "run-plan.schema.json": "urn:ai-sow:generate:run-plan:1",
    "final-review.schema.json": "urn:ai-sow:generate:final-review:1",
    "generation-manifest.schema.json": "urn:ai-sow:generate:generation-manifest:1",
    "current.schema.json": "urn:ai-sow:generate:current:1",
}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def schemas() -> dict[str, dict[str, object]]:
    return {name: read_json(CONTRACTS / name) for name in SCHEMA_IDS}


@pytest.fixture
def registry(schemas: dict[str, dict[str, object]]) -> Registry:
    result = Registry()
    for schema in schemas.values():
        result = result.with_resource(
            str(schema["$id"]), Resource.from_contents(schema)
        )
    return result


def validator_for(
    schema_name: str,
    schemas: dict[str, dict[str, object]],
    registry: Registry,
) -> Draft202012Validator:
    return Draft202012Validator(schemas[schema_name], registry=registry)


def test_run_plan_contract_fixes_the_template_snapshot_location(
    schemas: dict[str, dict[str, object]],
) -> None:
    properties = schemas["run-plan.schema.json"]["properties"]
    assert isinstance(properties, dict)
    assert properties["templateSnapshotPath"] == {
        "const": ".ai-sow/work/run-template.xlsx"
    }


def validate_fixture(
    relative: str,
    schema_name: str,
    schemas: dict[str, dict[str, object]],
    registry: Registry,
) -> None:
    validator_for(schema_name, schemas, registry).validate(read_json(FIXTURES / relative))


def diagnostic_codes(
    value: dict[str, object],
    schema_name: str,
    schemas: dict[str, dict[str, object]],
    registry: Registry,
) -> set[str]:
    errors = tuple(validator_for(schema_name, schemas, registry).iter_errors(value))
    return {
        "CONTRACT_UNEXPECTED_PROPERTY"
        if error.validator == "additionalProperties"
        else "CONTRACT_REQUIRED"
        if error.validator == "required"
        else "CONTRACT_INVALID"
        for error in errors
    }


def contract_codes(
    value: dict[str, object],
    schema_name: str,
    schemas: dict[str, dict[str, object]],
    registry: Registry,
) -> set[str]:
    return {
        "CONTRACT_REQUIRED_PROPERTY"
        if error.validator == "required"
        else "CONTRACT_UNEXPECTED_PROPERTY"
        if error.validator == "additionalProperties"
        else "CONTRACT_INVALID"
        for error in validator_for(schema_name, schemas, registry).iter_errors(value)
    }


def request_diagnostic_codes(
    value: dict[str, object],
    schemas: dict[str, dict[str, object]],
    registry: Registry,
) -> set[str]:
    errors = tuple(
        validator_for("request.schema.json", schemas, registry).iter_errors(value)
    )
    if not errors:
        return set()
    codes = {"REQUEST_INVALID"}
    if value.get("mode") == "BROWNFIELD":
        sources = value.get("sources", [])
        if not any(
            isinstance(source, dict) and source.get("role") == "PRIOR_SOW"
            for source in sources
        ):
            codes.add("REQUEST_BROWNFIELD_PRIOR_SOW_REQUIRED")
        if value.get("currentStateDelta") is None:
            codes.add("REQUEST_BROWNFIELD_CURRENT_STATE_DELTA_REQUIRED")
    if value.get("mode") == "GREENFIELD" and any(
        isinstance(source, dict) and source.get("role") == "PRIOR_SOW"
        for source in value.get("sources", [])
    ):
        codes.add("REQUEST_GREENFIELD_PRIOR_SOW_FORBIDDEN")
    return codes


def question_fixture() -> dict[str, object]:
    return {
        "questionId": "confirm-return-api",
        "subjectIds": ["input-current-return-api"],
        "question": "当前是否已有退货申请提交接口？",
        "reason": "现状接口能力会影响本期交付边界。",
        "decisionImpact": "答案将决定接口工作方式和 Task 人天。",
        "unansweredEffect": "未回答时无法确定接口是否应纳入本期估算。",
    }


def diagnostic_codes_for_request(
    value: dict[str, object], registry: Registry
) -> set[str]:
    return {
        "CONTRACT_MIN_LENGTH"
        if item.details.get("validator") == "minLength"
        else item.code
        for item in validate_contract(value, "request.schema.json", registry)
    }


def test_question_requires_reason_impact_and_unanswered_effect(registry: Registry) -> None:
    question = {
        "questionId": "confirm-return-api",
        "subjectIds": ["input-current-return-api"],
        "question": "当前是否已有退货申请提交接口？",
    }
    codes = {
        "CONTRACT_REQUIRED_PROPERTY"
        if item.details.get("validator") == "required"
        else item.code
        for item in validate_contract(question, "question.schema.json", registry)
    }
    assert codes == {"CONTRACT_REQUIRED_PROPERTY"}


def test_answer_is_invalid_after_question_changes() -> None:
    original = question_fixture()
    answer = {
        "questionId": original["questionId"],
        "questionSha256": question_sha256(original),
        "answer": "已有，并由本项目直接修改。",
    }
    changed = {**original, "decisionImpact": "答案将改变工作方式和 Task 人天。"}
    assert {item.code for item in validate_question_answers([changed], [answer])} == {
        "QUESTION_ANSWER_HASH_MISMATCH"
    }


def test_answer_rejects_unknown_question_id() -> None:
    question = question_fixture()
    answer = {
        "questionId": "confirm-unknown-api",
        "questionSha256": question_sha256(question),
        "answer": "未知接口不存在。",
    }

    diagnostics = validate_question_answers([question], [answer])

    assert [(item.code, item.path) for item in diagnostics] == [
        ("QUESTION_ANSWER_UNKNOWN_QUESTION", "/questionnaireAnswers/0/questionId")
    ]


def test_answer_rejects_duplicate_question_id() -> None:
    question = question_fixture()
    answer = {
        "questionId": question["questionId"],
        "questionSha256": question_sha256(question),
        "answer": "已有，并由本项目直接修改。",
    }

    diagnostics = validate_question_answers([question], [answer, answer])

    assert [(item.code, item.path) for item in diagnostics] == [
        ("QUESTION_ANSWER_DUPLICATE", "/questionnaireAnswers/1/questionId")
    ]


def test_each_batched_question_is_self_contained(registry: Registry) -> None:
    value = read_json(FIXTURES / "greenfield/request.json")
    value["questions"] = [question_fixture(), {**question_fixture(), "reason": ""}]
    assert "CONTRACT_MIN_LENGTH" in diagnostic_codes_for_request(value, registry)


def test_schema_ids_are_stable(schemas: dict[str, dict[str, object]]) -> None:
    assert {name: schema["$id"] for name, schema in schemas.items()} == SCHEMA_IDS


def test_greenfield_and_brownfield_fixtures_validate_against_core_contracts(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    for mode in ("greenfield", "brownfield"):
        validate_fixture(f"{mode}/request.json", "request.schema.json", schemas, registry)
        validate_fixture(
            f"{mode}/input-manifest.json",
            "input-manifest.schema.json",
            schemas,
            registry,
        )
        validate_fixture(
            f"{mode}/scope.json", "scope-bundle.schema.json", schemas, registry
        )
        validate_fixture(
            f"{mode}/delivery.json",
            "delivery-bundle.schema.json",
            schemas,
            registry,
        )


def test_contract_tokens_are_exact(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    expected = {
        "greenfield/request.json": "ai-sow-generate-request-v1",
        "greenfield/input-manifest.json": "ai-sow-input-manifest-v1",
        "greenfield/scope.json": "ai-sow-scope-bundle-v1",
        "greenfield/delivery.json": "ai-sow-delivery-bundle-v3",
    }
    for fixture, token in expected.items():
        assert read_json(FIXTURES / fixture)["contract"] == token


def test_delivery_rejects_calculated_effort(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "greenfield/delivery.json"))
    delivery["tasks"][0]["personDays"] = 8
    assert diagnostic_codes(
        delivery, "delivery-bundle.schema.json", schemas, registry
    ) == {"CONTRACT_UNEXPECTED_PROPERTY"}


def test_delivery_rejects_legacy_multi_feature_story_shape(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "greenfield/delivery.json"))
    story = delivery["stories"][0]
    story["featureIds"] = [story.pop("featureId"), "feature-unrelated"]

    assert diagnostic_codes(
        delivery, "delivery-bundle.schema.json", schemas, registry
    ) == {"CONTRACT_REQUIRED", "CONTRACT_UNEXPECTED_PROPERTY"}


def test_delivery_story_excludes_description(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "greenfield/delivery.json"))
    delivery["stories"][0]["description"] = "不应进入稳定模型"

    assert diagnostic_codes(
        delivery, "delivery-bundle.schema.json", schemas, registry
    ) == {"CONTRACT_UNEXPECTED_PROPERTY"}


def test_acceptance_criterion_requires_exact_source_refs(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "greenfield/delivery.json"))
    delivery["acceptanceCriteria"][0].pop("sourceRefs", None)

    assert "CONTRACT_REQUIRED_PROPERTY" in contract_codes(
        delivery, "delivery-bundle.schema.json", schemas, registry
    )


def test_task_instance_effective_start_requires_base_unit(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    scope = copy.deepcopy(read_json(FIXTURES / "brownfield/scope.json"))
    item = scope["effectiveStartItems"][0]
    item["matchLevel"] = "TASK_INSTANCE"
    item.pop("baseUnit", None)

    assert "CONTRACT_REQUIRED_PROPERTY" in contract_codes(
        scope, "scope-bundle.schema.json", schemas, registry
    )


def test_capability_effective_start_allows_no_base_unit(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    scope = copy.deepcopy(read_json(FIXTURES / "brownfield/scope.json"))
    item = scope["effectiveStartItems"][0]
    item["matchLevel"] = "CAPABILITY"
    item.pop("baseUnit", None)

    assert validate_contract(scope, "scope-bundle.schema.json", registry) == ()


def test_capability_effective_start_forbids_base_unit(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    scope = copy.deepcopy(read_json(FIXTURES / "brownfield/scope.json"))
    item = next(
        item
        for item in scope["effectiveStartItems"]
        if item["matchLevel"] == "CAPABILITY"
    )
    item["baseUnit"] = "BU-BUSINESS-SERVICE-API"

    assert "CONTRACT_INVALID" in contract_codes(
        scope, "scope-bundle.schema.json", schemas, registry
    )


def test_delivery_accepts_minimal_nonduplicated_estimate_model(
    registry: Registry,
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "brownfield/delivery.json"))
    for story in delivery["stories"]:
        story.pop("storyType", None)
    for criterion in delivery["acceptanceCriteria"]:
        criterion.pop("sequence", None)
        criterion.pop("rationale", None)
    for task in delivery["tasks"]:
        task.pop("dependsOnTaskIds", None)
        task.pop("matchedEffectiveStartItemId", None)
        if "workModeEvidence" in task:
            task["workModeEvidence"].pop("effectiveStartItemName", None)

    assert validate_contract(
        delivery, "delivery-bundle.schema.json", registry
    ) == ()


def test_initial_full_compile_slices_allow_empty_replacement_set(
    registry: Registry,
) -> None:
    scope_slice = {
        "contract": "ai-sow-scope-slice-v1",
        "inputRevisionId": "000001",
        "impactPlanSha256": "0" * 64,
        "replacesFeatureIds": [],
        "newAnchorMappings": [],
        "epics": [],
        "features": [],
        "commitments": [],
        "effectiveStartItems": [],
        "designItems": [],
        "designDecisions": [],
        "integrations": [],
        "nfrs": [],
        "assumptions": [],
        "responsibilityBoundaries": [],
    }
    delivery_slice = {
        "contract": "ai-sow-delivery-slice-v3",
        "inputRevisionId": "000001",
        "scopeSha256": "1" * 64,
        "impactPlanSha256": "0" * 64,
        "replacesFeatureIds": [],
        "stories": [],
        "acceptanceCriteria": [],
        "tasks": [],
        "dependencies": [],
    }

    assert validate_contract(
        scope_slice, "scope-slice.schema.json", registry
    ) == ()
    assert validate_contract(
        delivery_slice, "delivery-slice.schema.json", registry
    ) == ()


def test_adjustment_forbids_reuse_only_project_side_work_fields(
    registry: Registry,
) -> None:
    delivery = copy.deepcopy(read_json(FIXTURES / "brownfield/delivery.json"))
    adjustment = next(
        task for task in delivery["tasks"] if task["workMode"] == "调整"
    )
    adjustment["workModeEvidence"]["projectSideWorkTypes"] = ["CONFIGURE"]
    adjustment["workModeEvidence"]["projectSideWorkCommitment"] = "配置复用能力。"

    assert validate_contract(
        delivery, "delivery-bundle.schema.json", registry
    )


def test_brownfield_request_requires_current_state_delta_and_prior_sow(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    request = copy.deepcopy(read_json(FIXTURES / "brownfield/request.json"))
    request["sources"] = [
        source for source in request["sources"] if source["role"] != "PRIOR_SOW"
    ]
    assert "REQUEST_BROWNFIELD_PRIOR_SOW_REQUIRED" in request_diagnostic_codes(
        request, schemas, registry
    )

    request = copy.deepcopy(read_json(FIXTURES / "brownfield/request.json"))
    request["currentStateDelta"] = None
    assert "REQUEST_BROWNFIELD_CURRENT_STATE_DELTA_REQUIRED" in (
        request_diagnostic_codes(request, schemas, registry)
    )


def test_greenfield_request_forbids_prior_sow(
    schemas: dict[str, dict[str, object]], registry: Registry
) -> None:
    request = copy.deepcopy(read_json(FIXTURES / "greenfield/request.json"))
    request["sources"].append(
        {
            "sourceId": "prior-sow-sample",
            "role": "PRIOR_SOW",
            "version": "1.0",
            "path": "inputs/prior-sow.md",
        }
    )
    assert "REQUEST_GREENFIELD_PRIOR_SOW_FORBIDDEN" in request_diagnostic_codes(
        request, schemas, registry
    )


def test_brownfield_fixture_covers_cross_feature_and_design_required_cases() -> None:
    scope = read_json(FIXTURES / "brownfield/scope.json")
    delivery = read_json(FIXTURES / "brownfield/delivery.json")
    assert scope["commitments"][0]["treatment"] == "CARRY_FORWARD"
    assert scope["effectiveStartItems"]
    assert len(scope["integrations"][0]["featureIds"]) == 2
    assert any(nfr["status"] == "DESIGN_REQUIRED" for nfr in scope["nfrs"])
    design_task = next(task for task in delivery["tasks"] if task["taskKind"] == "DESIGN")
    assert design_task["storyId"] == "story-refund-processing"
    assert all("storyType" not in story for story in delivery["stories"])


def valid_id_decisions() -> dict[str, object]:
    return {
        "contract": "ai-sow-id-decisions-v1",
        "decisions": [
            {
                "objectType": "FEATURE",
                "objectId": "feature-refund-processing",
                "disposition": "UNCHANGED",
                "previousId": "feature-refund-processing",
                "meaningPreserved": True,
                "rationale": "交付含义未变化，保留原有 Feature ID。",
            }
        ],
    }


def valid_final_review() -> dict[str, object]:
    return {
        "contract": "ai-sow-final-review-v1",
        "runId": "run-000001",
        "inputRevisionId": "000001",
        "scopeSha256": "1" * 64,
        "deliverySha256": "2" * 64,
        "packetSha256": "3" * 64,
        "decision": "PASS",
        "notes": [],
        "questions": [],
    }


def valid_generation_manifest() -> dict[str, object]:
    review = valid_final_review()
    return {
        "contract": "ai-sow-generation-manifest-v1",
        "generationId": "000001",
        "revisionId": "000001",
        "inputManifestPath": ".ai-sow/inputs/revisions/000001/manifest.json",
        "inputManifestSha256": "4" * 64,
        "scopePath": ".ai-sow/generations/000001/scope.json",
        "scopeSha256": "1" * 64,
        "deliveryPath": ".ai-sow/generations/000001/delivery.json",
        "deliverySha256": "2" * 64,
        "templatePath": "skills/generate/assets/sow-template.xlsx",
        "templateSha256": "5" * 64,
        "workbookPath": ".ai-sow/generations/000001/package/sow.xlsx",
        "workbookSha256": "6" * 64,
        "workbookVerification": {
            "trustState": "VERIFIED",
            "engine": {"name": "LibreOffice", "version": "LibreOffice test"},
            "storyCount": 1,
            "taskCount": 2,
            "directDays": 2.0,
            "sitDays": 0.5,
            "uatDays": 0.5,
            "totalDays": 3.0,
            "parameterStatuses": [
                {"code": "K_UAT", "status": "待样本校准"}
            ],
            "formulaErrors": [],
        },
        "notesPath": ".ai-sow/generations/000001/package/sow-notes.md",
        "notesSha256": "7" * 64,
        "scopeCompilerContract": "scope-compiler-v2",
        "deliveryCompilerContract": "delivery-compiler-v5",
        "rendererContract": "generation-renderer-v7",
        "decision": "PASS",
        "reviewMode": "AUTOMATIC_FINAL_REVIEW",
        "impact": {
            "action": "FULL_COMPILE",
            "baselineGenerationId": None,
            "baselineRevisionId": None,
            "changedSourceIds": [],
            "changedAnchorIds": [],
            "affectedFeatureIds": ["feature-refund-processing"],
            "escalation": "FULL",
            "reasonCodes": ["NO_CURRENT_GENERATION"],
        },
        "changeCounts": {
            "features": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
            "stories": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
            "acceptanceCriteria": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
            "tasks": {"affected": 0, "recomputed": 2, "reused": 0, "deleted": 0, "final": 2},
        },
        "finalReview": review,
        "finalReviewSha256": __import__("hashlib").sha256(
            canonical_json_bytes(review)
        ).hexdigest(),
        "publicationComplete": True,
    }


def test_registry_loader_loads_every_contract_once() -> None:
    registry = load_schema_registry(SKILL_ROOT)
    for schema_id in SCHEMA_IDS.values():
        assert registry.get(schema_id).contents["$id"] == schema_id


def test_canonical_json_bytes_are_utf8_sorted_compact_and_newline_terminated() -> None:
    assert canonical_json_bytes({"z": 1, "a": "中文"}) == (
        '{"a":"中文","z":1}\n'.encode("utf-8")
    )


def test_models_are_frozen() -> None:
    diagnostic = Diagnostic(code="EXAMPLE", message="示例", path="/x", details={})
    with pytest.raises(FrozenInstanceError):
        diagnostic.code = "CHANGED"  # type: ignore[misc]


def test_changed_meaning_cannot_reuse_previous_id(registry: Registry) -> None:
    value = valid_id_decisions()
    value["decisions"][0].update(
        {
            "disposition": "CHANGED",
            "previousId": value["decisions"][0]["objectId"],
            "meaningPreserved": False,
        }
    )
    assert "ID_CHANGED_REUSES_PREVIOUS" in {
        diagnostic.code for diagnostic in validate_id_decisions(value, registry)
    }


def test_blocked_review_requires_minimal_questions(registry: Registry) -> None:
    review = valid_final_review()
    review.update({"decision": "BLOCKED", "questions": []})
    assert "FINAL_REVIEW_BLOCKED_QUESTIONS_REQUIRED" in {
        diagnostic.code for diagnostic in validate_final_review(review, registry)
    }


def test_final_review_requires_exact_packet_binding(registry: Registry) -> None:
    review = valid_final_review()
    assert "FINAL_REVIEW_PACKET_HASH_MISMATCH" in {
        diagnostic.code
        for diagnostic in validate_final_review(
            review, registry, expected_packet_sha256="f" * 64
        )
    }


def test_current_pointer_has_no_mutable_status_fields(registry: Registry) -> None:
    current = {
        "contract": "ai-sow-current-v1",
        "generationId": "000001",
        "revisionId": "000001",
        "generationManifestPath": ".ai-sow/generations/000001/manifest.json",
        "generationManifestSha256": "8" * 64,
        "state": "RUNNING",
    }
    assert "CONTRACT_UNEXPECTED_PROPERTY" in {
        diagnostic.code
        for diagnostic in validate_contract(current, "current.schema.json", registry)
    }


def test_generation_hash_closure_binds_review_and_paths(registry: Registry) -> None:
    manifest = valid_generation_manifest()
    assert validate_generation_hash_closure(manifest, registry) == ()

    manifest["scopePath"] = ".ai-sow/generations/000002/scope.json"
    manifest["finalReviewSha256"] = "0" * 64
    assert {
        diagnostic.code
        for diagnostic in validate_generation_hash_closure(manifest, registry)
    } == {"GENERATION_PATH_ID_MISMATCH", "GENERATION_REVIEW_HASH_MISMATCH"}
