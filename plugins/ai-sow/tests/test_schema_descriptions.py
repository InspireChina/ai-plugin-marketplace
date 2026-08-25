from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
SCHEMAS = {
    "Project": PLUGIN_ROOT / "skills/setup/contracts/project.schema.json",
    "Source Requirements": PLUGIN_ROOT
    / "skills/analyze-requirement/contracts/source-requirements.schema.json",
    "As-Is": PLUGIN_ROOT / "skills/analyze-as-is/contracts/asis.schema.json",
    "Design": PLUGIN_ROOT / "skills/generate-design/contracts/design.schema.json",
    "Technical Requirements": PLUGIN_ROOT
    / "skills/generate-design/contracts/technical-requirements.schema.json",
    "Delivery": PLUGIN_ROOT / "skills/generate-story/contracts/delivery.schema.json",
    "Estimate": PLUGIN_ROOT / "skills/generate-task/contracts/estimate.schema.json",
    "Manifest": PLUGIN_ROOT / "skills/generate-sow/contracts/manifest.schema.json",
}
STABLE_OBJECT_DEFS = {
    "Project": (),
    "Source Requirements": (
        "sourceDocument",
        "normalizedItem",
        "source",
        "epic",
        "feature",
    ),
    "As-Is": (
        "repositorySnapshot",
        "priorSowSnapshot",
        "analysisScope",
        "topicAssessment",
        "item",
        "commitment",
        "effectiveStartItem",
        "coverage",
        "uncertainty",
        "evidence",
    ),
    "Design": ("designItem", "architectureDelta", "decision", "scopeDecision"),
    "Technical Requirements": ("sourceInput", "designDerived", "epic", "feature"),
    "Delivery": (
        "gap",
        "story",
        "acceptanceCriterion",
        "integration",
        "assumption",
        "assumptionStory",
    ),
    "Estimate": ("workModeEvidence", "task"),
    "Manifest": ("digest", "repository", "priorSow"),
}
CHINESE = re.compile(r"[\u3400-\u9fff]")


def test_stable_fields_have_chinese_descriptions() -> None:
    assert set(SCHEMAS) == {
        "Project",
        "Source Requirements",
        "As-Is",
        "Design",
        "Technical Requirements",
        "Delivery",
        "Estimate",
        "Manifest",
    }
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
