from __future__ import annotations

TEST_LAYER = "unit"

import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
CONTRACTS = PLUGIN_ROOT / "skills/generate/contracts"
SCHEMAS = {path.name: path for path in CONTRACTS.glob('*.schema.json')}
CHINESE = re.compile(r"[\u3400-\u9fff]")


def test_contract_families_have_chinese_purpose_descriptions() -> None:
    for name, path in SCHEMAS.items():
        schema = json.loads(path.read_text(encoding="utf-8"))
        description = schema.get("description")
        assert isinstance(description, str) and description.strip(), name
        assert CHINESE.search(description), (name, description)
