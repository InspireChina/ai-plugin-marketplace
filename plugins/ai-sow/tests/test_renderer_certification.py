from __future__ import annotations

import ast
import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]


OWNER_CONTRACTS = {
    "analyze-requirement": {
        "requirements": "source-requirements.schema.json",
        "sourceDisposition": "source-disposition.schema.json",
    },
    "analyze-as-is": {"asis": "asis.schema.json"},
    "generate-design": {
        "design": "design.schema.json",
        "technicalRequirements": "technical-requirements.schema.json",
    },
    "generate-story": {"delivery": "delivery.schema.json"},
    "generate-task": {"estimate": "estimate.schema.json"},
}


def renderer_coverage(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "RENDERER_SCHEMA_COVERAGE"
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, dict)
    return value


def renderer_assignment(path: Path, name: str) -> dict[str, str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, dict)
    return value


def test_every_owner_schema_collection_has_renderer_release_coverage() -> None:
    for owner, contracts in OWNER_CONTRACTS.items():
        skill_root = PLUGIN_ROOT / "skills" / owner
        renderer = skill_root / "scripts/render_review.py"
        source = renderer.read_text(encoding="utf-8")
        coverage = renderer_coverage(renderer)
        required: set[str] = set()
        for document_name, schema_name in contracts.items():
            schema = json.loads(
                (skill_root / "contracts" / schema_name).read_text(encoding="utf-8")
            )
            required.update(
                f"{document_name}.{field}" for field in schema.get("required", [])
            )

        assert set(coverage) == required, owner
        for projection in coverage.values():
            assert projection.startswith("@mechanical:") or f"## {projection}" in source


def test_requirement_renderer_covers_every_epic_and_feature_schema_field() -> None:
    skill_root = PLUGIN_ROOT / "skills/analyze-requirement"
    schema = json.loads(
        (skill_root / "contracts/source-requirements.schema.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        f"{collection}.{field}"
        for collection in ("epic", "feature")
        for field in schema["$defs"][collection]["properties"]
    }
    coverage = renderer_assignment(
        skill_root / "scripts/render_review.py",
        "RENDERER_FIELD_COVERAGE",
    )

    assert set(coverage) == required
