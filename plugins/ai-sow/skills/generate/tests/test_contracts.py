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


SCHEMA_IDS = {
    "common.schema.json": "urn:ai-sow:generate:common:1",
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
        else "CONTRACT_INVALID"
        for error in errors
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
        "greenfield/delivery.json": "ai-sow-delivery-bundle-v1",
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
    assert not any(story.get("storyType") == "DESIGN" for story in delivery["stories"])


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
        "notesPath": ".ai-sow/generations/000001/package/sow-notes.md",
        "notesSha256": "7" * 64,
        "scopeCompilerContract": "scope-compiler-v1",
        "deliveryCompilerContract": "delivery-compiler-v1",
        "rendererContract": "generation-renderer-v1",
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
            "features": {"added": 1, "updated": 0, "removed": 0},
            "recomputedStories": 1,
            "recomputedTasks": 2,
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
