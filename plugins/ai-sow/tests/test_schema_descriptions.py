from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
CONTRACTS = PLUGIN_ROOT / "skills/generate/contracts"
SCHEMAS = {
    "Common": CONTRACTS / "common.schema.json",
    "Request": CONTRACTS / "request.schema.json",
    "Input Revision": CONTRACTS / "input-revision.schema.json",
    "SOW Model": CONTRACTS / "sow-model.schema.json",
    "Run State": CONTRACTS / "run-state.schema.json",
    "Action": CONTRACTS / "action.schema.json",
    "Stage Checkpoint": CONTRACTS / "stage-checkpoint.schema.json",
    "Review Repair": CONTRACTS / "review-repair.schema.json",
    "Artifact Approval": CONTRACTS / "artifact-approval.schema.json",
    "Generation Manifest": CONTRACTS / "generation-manifest.schema.json",
    "Current": CONTRACTS / "current.schema.json",
}
CHINESE = re.compile(r"[\u3400-\u9fff]")


def test_contract_families_have_chinese_purpose_descriptions() -> None:
    assert len(SCHEMAS) == 11
    for name, path in SCHEMAS.items():
        schema = json.loads(path.read_text(encoding="utf-8"))
        description = schema.get("description")
        assert isinstance(description, str) and description.strip(), name
        assert CHINESE.search(description), (name, description)
