from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
CONTRACTS = PLUGIN_ROOT / "skills/generate/contracts"
SCHEMAS = {
    "Generate Request": CONTRACTS / "request.schema.json",
    "Input Manifest": CONTRACTS / "input-manifest.schema.json",
    "Scope Bundle": CONTRACTS / "scope-bundle.schema.json",
    "Delivery Bundle": CONTRACTS / "delivery-bundle.schema.json",
}
STABLE_OBJECT_DEFS = {
    "Generate Request": (
        "project",
        "source",
        "questionnaireAnswer",
        "currentStateDelta",
        "responsibilityBoundary",
    ),
    "Input Manifest": (
        "project",
        "source",
        "questionnaireAnswer",
        "responsibilityBoundary",
    ),
    "Scope Bundle": (
        "epic",
        "feature",
        "scopeDecision",
        "commitment",
        "effectiveStartItem",
        "designItem",
        "designDecision",
        "integration",
        "nfr",
        "assumption",
        "responsibilityBoundary",
    ),
    "Delivery Bundle": (
        "story",
        "acceptanceCriterion",
        "task",
        "workModeEvidence",
        "dependency",
    ),
}
CHINESE = re.compile(r"[\u3400-\u9fff]")


def test_stable_fields_have_chinese_descriptions() -> None:
    assert set(SCHEMAS) == set(STABLE_OBJECT_DEFS)
    for name, path in SCHEMAS.items():
        schema = json.loads(path.read_text(encoding="utf-8"))
        objects = [("$", schema)] + [
            (f"$defs/{definition}", schema["$defs"][definition])
            for definition in STABLE_OBJECT_DEFS[name]
        ]
        for object_path, value in objects:
            for field, definition in value.get("properties", {}).items():
                description = definition.get("description")
                assert isinstance(description, str) and description.strip(), (
                    name,
                    object_path,
                    field,
                )
                assert CHINESE.search(description), (
                    name,
                    object_path,
                    field,
                    description,
                )
