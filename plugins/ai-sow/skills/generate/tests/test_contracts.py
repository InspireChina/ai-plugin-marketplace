from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SKILL_ROOT = Path(__file__).parents[1]
CONTRACTS = SKILL_ROOT / "contracts"
FIXTURES = SKILL_ROOT / "fixtures"
SCHEMA_IDS = {
    "common.schema.json": "urn:ai-sow:generate:common:1",
    "request.schema.json": "urn:ai-sow:generate:request:1",
    "input-manifest.schema.json": "urn:ai-sow:generate:input-manifest:1",
    "scope-bundle.schema.json": "urn:ai-sow:generate:scope-bundle:1",
    "delivery-bundle.schema.json": "urn:ai-sow:generate:delivery-bundle:1",
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
