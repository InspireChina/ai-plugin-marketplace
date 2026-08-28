from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
FIXTURE_ROOT = SKILL_ROOT / "tests/fixtures/regression-findings"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.diagnostics import diagnostic_codes
from runtime.fact_source import validate_unique_fact_sources
from runtime.text_gates import validate_text_gates


def findings() -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(FIXTURE_ROOT.glob("[A-E]-*.json"))
    ]


def test_golden_set_preserves_all_26_windows_findings_and_routes() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    cases = findings()

    assert len(cases) == manifest["totalFindings"] == 26
    assert len({case["findingId"] for case in cases}) == 26
    assert Counter(case["category"] for case in cases) == Counter(manifest["categories"])
    assert {case["expectedLayer"] for case in cases} <= {"script", "haiku", "opus"}
    assert manifest["claudeRoutes"]["factual"] == "Haiku 4.5"
    assert manifest["codexRoutes"]["factual"] == "gpt-5.6-luna/low"


def test_a_and_e_findings_are_caught_by_shared_text_gates(tmp_path: Path) -> None:
    for case in findings():
        if case["category"] not in {"A", "E"}:
            continue
        diagnostics = validate_text_gates(
            tmp_path,
            [(str(case["path"]), str(case["text"]))],
        )
        assert str(case["expectedCode"]) in diagnostic_codes(diagnostics), case["findingId"]


def test_c_findings_are_caught_by_unique_fact_source_gate() -> None:
    for case in findings():
        if case["category"] != "C":
            continue
        diagnostics = validate_unique_fact_sources(
            [
                (str(case["path"]), str(case["text"])),
                (str(case["duplicatePath"]), str(case["text"])),
            ]
        )
        assert "DUPLICATE_FACT_STATEMENT" in diagnostic_codes(diagnostics), case["findingId"]


def test_d_findings_remain_reserved_for_deep_judgment_review() -> None:
    deep = [case for case in findings() if case["category"] == "D"]

    assert deep
    assert all(case["expectedLayer"] == "opus" for case in deep)
    assert all(case["codexRoute"] == "gpt-5.6-sol/max" for case in deep)
