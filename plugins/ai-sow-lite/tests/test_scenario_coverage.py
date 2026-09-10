from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
CHECKER = PLUGIN / "tests/support/check_scenario_coverage.py"
D09 = "docs/design/detailed/D09-validation-and-implementation.md"
CATALOG = "docs/design/08-scenario-catalog.md"


def load_checker():
    if not CHECKER.is_file():
        raise AssertionError("scenario coverage checker is not implemented")
    spec = importlib.util.spec_from_file_location("scenario_coverage", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScenarioCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = load_checker()
        self.temporary = tempfile.TemporaryDirectory(prefix="lite-coverage-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "plugin"
        for relative in (D09, CATALOG):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PLUGIN / relative, target)
        evidence = self.root / "evidence/synthetic receipt.txt"
        evidence.parent.mkdir()
        evidence.write_text("合成文件；只测试引用可达，不是场景执行证据。\n", encoding="utf-8")

    def ledger(self):
        """Synthetic data only; parser authority is checked independently below."""
        index = self.checker.load_scenario_index(self.root)
        records = [dict(id=identifier, **assignment, state="unsupported", evidence_refs=[],
                        limitation="合成测试只核对 ledger 结构，没有执行该业务场景。")
                   for identifier, assignment in index.items()]
        by_id = {row["id"]: row for row in records}
        by_id["IN01"].update(state="verified", evidence_refs=["evidence/synthetic receipt.txt"], limitation="")
        by_id["FS05"].update(
            state="covered_by_mechanism", evidence_refs=["evidence/synthetic receipt.txt"], limitation="",
            mechanism_refs=[dict(id="atomic-current", applicability="合成关联：请求重放复用已生效指针，不重复应用。")],
        )
        for identifier in ("AN27", "AN28", "FS13", "OB11"):
            by_id[identifier].update(state="conditional", limitation="合成测试未启动 worker，只核对条件实验的登记。")
        return dict(schema_version="1.0", scenarios=records, mechanisms=[dict(
            id="atomic-current", state="verified", evidence_refs=["evidence/synthetic receipt.txt"], limitation="",
        )])

    @staticmethod
    def scenario(ledger, identifier):
        return next(row for row in ledger["scenarios"] if row["id"] == identifier)

    def assert_diagnostic(self, ledger, code):
        errors = self.checker.validate_ledger(ledger, self.root)
        self.assertTrue(any(error.startswith(code + ":") for error in errors), errors)

    def test_index_covers_the_163_catalog_ids_and_preserves_composite_stages(self):
        index = self.checker.load_scenario_index(self.root)
        expected_ids = {f"{prefix}{number:02}" for prefix, count in
                        (("IN", 21), ("AN", 43), ("CL", 29), ("XL", 26), ("FS", 18), ("OB", 19), ("X", 7))
                        for number in range(1, count + 1)}
        self.assertEqual(set(index), expected_ids)
        for identifier, owner, stage in (
            ("IN01", "D01", "I2"), ("IN17", "D03", "I2；原型 I4"),
            ("IN21", "D04B", "I1 工具 / I2 活动"),
            ("AN18", "D02", "I1 合同 / I2 语义"),
            ("AN27", "D04", "条件实验；首版不启用委派"),
            ("CL04", "D05", "I3；复杂组合 I4"), ("CL21", "D05", "I3 基础 / I4 复杂修改"),
            ("FS12", "D00", "I1"), ("FS13", "D07", "条件实验；首版不启用委派"),
            ("OB01", "D08", "I1 事件 / I2 宿主"),
            ("OB12", "D08", "I2 基线 / I4 固定长例与对照"),
            ("OB19", "D08", "I1.1 早期探针 / I1 事件 / I2 集成"),
            ("X07", "D04", "I2"),
        ):
            with self.subTest(identifier=identifier):
                self.assertEqual(index[identifier], dict(owner=owner, earliest_increment=stage))

    def test_source_catalog_and_d09_fail_closed_on_drift_or_duplicates(self):
        original_d09 = (self.root / D09).read_text(encoding="utf-8")
        original_catalog = (self.root / CATALOG).read_text(encoding="utf-8")
        catalog_row = next(line for line in original_catalog.splitlines() if line.startswith("| IN01 |"))
        cases = (
            (original_d09, original_catalog.replace(catalog_row, ""), "SOURCE_COUNT"),
            (original_d09, original_catalog.replace(catalog_row, catalog_row + "\n" + catalog_row), "SOURCE_DUPLICATE_ID"),
            (original_d09, original_catalog.replace("| IN01 |", "| IN99 |", 1), "SOURCE_ID_MISMATCH"),
            (original_d09.replace("IN01—IN03", "IN01—IN04", 1), original_catalog, "SOURCE_DUPLICATE_ID"),
            (original_d09.replace("IN01—IN03", "IN03—IN01", 1), original_catalog, "SOURCE_RANGE"),
            (original_d09.replace("IN01—IN03", "IN01—AN03", 1), original_catalog, "SOURCE_RANGE"),
            (original_d09.replace("| 场景 | 主责 | 最早增量 |", "| 场景 | 已改变 | 最早增量 |", 1), original_catalog, "SOURCE_TABLE"),
        )
        for d09, catalog, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(self.checker.CoverageError, "^" + code + ":"):
                    self.checker.parse_scenario_index(d09, catalog)

    def test_valid_ledger_is_read_only_and_accepts_all_four_states(self):
        ledger = self.ledger()
        before = copy.deepcopy(ledger)
        self.assertEqual(self.checker.validate_ledger(ledger, self.root), [])
        self.assertEqual(ledger, before)
        ledger["scenarios"].reverse()
        self.assertEqual(self.checker.validate_ledger(ledger, self.root), [])

    def test_scenario_set_rejects_missing_duplicate_and_unknown_ids(self):
        for change, code in (
            (lambda rows: rows.pop(0), "MISSING_SCENARIO"),
            (lambda rows: rows.append(copy.deepcopy(rows[0])), "DUPLICATE_SCENARIO"),
            (lambda rows: rows[0].update(id="ZZ99"), "UNKNOWN_SCENARIO"),
        ):
            with self.subTest(code=code):
                ledger = self.ledger()
                change(ledger["scenarios"])
                self.assert_diagnostic(ledger, code)

    def test_owner_and_earliest_increment_must_match_d09_exactly(self):
        for identifier, field, value, code in (
            ("IN01", "owner", "D08", "OWNER_MISMATCH"),
            ("IN21", "earliest_increment", "I1", "STAGE_MISMATCH"),
            ("IN17", "earliest_increment", "I4", "STAGE_MISMATCH"),
            ("AN27", "earliest_increment", "I4", "STAGE_MISMATCH"),
        ):
            with self.subTest(identifier=identifier, field=field):
                ledger = self.ledger()
                self.scenario(ledger, identifier)[field] = value
                self.assert_diagnostic(ledger, code)

    def test_unknown_states_are_not_treated_as_coverage(self):
        for state in ("passed", "VERIFIED", None, [], {}):
            with self.subTest(state=state):
                ledger = self.ledger()
                self.scenario(ledger, "IN01")["state"] = state
                self.assert_diagnostic(ledger, "STATE")

    def test_verified_and_mechanism_covered_scenarios_require_evidence(self):
        for identifier in ("IN01", "FS05"):
            for refs in ([], "evidence/synthetic receipt.txt", [42], ["evidence/missing.txt"], ["evidence"]):
                with self.subTest(identifier=identifier, refs=refs):
                    ledger = self.ledger()
                    self.scenario(ledger, identifier)["evidence_refs"] = refs
                    self.assert_diagnostic(ledger, "EVIDENCE")

    def test_references_reject_absolute_traversal_url_and_noncanonical_paths(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("not plugin evidence", encoding="utf-8")
        for ref in (str(outside), "../outside.txt", "evidence/../../outside.txt", "evidence/../" + D09,
                    "https://example.org/evidence", r"C:\evidence.txt", "evidence\\receipt.txt",
                    "evidence/synthetic receipt.txt#section", "./evidence/synthetic receipt.txt"):
            with self.subTest(ref=ref):
                ledger = self.ledger()
                self.scenario(ledger, "IN01")["evidence_refs"] = [ref]
                self.assert_diagnostic(ledger, "EVIDENCE")

    def test_symlink_evidence_and_authority_cannot_escape_plugin(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "evidence/link.txt"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        ledger = self.ledger()
        self.scenario(ledger, "IN01")["evidence_refs"] = ["evidence/link.txt"]
        self.assert_diagnostic(ledger, "EVIDENCE")
        authority = self.root / D09
        authority.unlink()
        authority.symlink_to(PLUGIN / D09)
        self.assert_diagnostic(ledger, "SOURCE_PATH")

    def test_non_ascii_evidence_path_inside_plugin_is_valid(self):
        path = self.root / "evidence/合成凭据 with spaces.md"
        path.write_text("合成引用测试。", encoding="utf-8")
        ledger = self.ledger()
        self.scenario(ledger, "IN01")["evidence_refs"] = [path.relative_to(self.root).as_posix()]
        self.assertEqual(self.checker.validate_ledger(ledger, self.root), [])

    def test_nonverified_states_require_a_limitation_beyond_a_placeholder(self):
        for state in ("unsupported", "conditional"):
            for limitation in (None, "", "  ", "TBD", "未验证"):
                with self.subTest(state=state, limitation=limitation):
                    ledger = self.ledger()
                    self.scenario(ledger, "IN02").update(state=state, limitation=limitation)
                    self.assert_diagnostic(ledger, "LIMITATION")

    def test_mechanism_coverage_requires_a_declared_verified_mechanism(self):
        for state in ("unsupported", "conditional"):
            with self.subTest(state=state):
                ledger = self.ledger()
                ledger["mechanisms"][0].update(state=state, limitation="该机制尚未运行合成以外的验证。")
                self.assert_diagnostic(ledger, "MECHANISM_NOT_VERIFIED")
        ledger = self.ledger()
        self.scenario(ledger, "FS05")["mechanism_refs"][0]["id"] = "missing-mechanism"
        self.assert_diagnostic(ledger, "UNKNOWN_MECHANISM")
        ledger["mechanisms"] = []
        self.assert_diagnostic(ledger, "UNKNOWN_MECHANISM")

    def test_mechanism_declarations_must_be_unique_and_evidenced(self):
        ledger = self.ledger()
        ledger["mechanisms"].append(copy.deepcopy(ledger["mechanisms"][0]))
        self.assert_diagnostic(ledger, "DUPLICATE_MECHANISM")
        for refs in ([], ["evidence/missing.txt"]):
            with self.subTest(refs=refs):
                ledger = self.ledger()
                ledger["mechanisms"][0]["evidence_refs"] = refs
                self.assert_diagnostic(ledger, "EVIDENCE")

    def test_mechanism_coverage_requires_specific_applicability_and_no_chains(self):
        for applicability in ("", " ", "TBD", "待补"):
            with self.subTest(applicability=applicability):
                ledger = self.ledger()
                self.scenario(ledger, "FS05")["mechanism_refs"][0]["applicability"] = applicability
                self.assert_diagnostic(ledger, "APPLICABILITY")
        ledger = self.ledger()
        self.scenario(ledger, "FS05")["mechanism_refs"] = []
        self.assert_diagnostic(ledger, "MECHANISM_REFS")
        ledger = self.ledger()
        ledger["mechanisms"][0]["state"] = "covered_by_mechanism"
        self.assert_diagnostic(ledger, "STATE")

    def test_malformed_shapes_and_misspelled_fields_return_diagnostics(self):
        for ledger in (None, [], {}, {"schema_version": "wrong", "scenarios": [], "mechanisms": []}):
            with self.subTest(ledger=ledger):
                self.assertTrue(self.checker.validate_ledger(ledger, self.root))
        for change in (
            lambda ledger: ledger.update(scenarios={}),
            lambda ledger: ledger.update(mechanisms=None),
            lambda ledger: ledger["scenarios"].append(None),
            lambda ledger: ledger["mechanisms"].append([]),
            lambda ledger: ledger["scenarios"][0].update(id=[]),
            lambda ledger: ledger["scenarios"][0].update(earliest="I2"),
            lambda ledger: ledger["mechanisms"][0].update(id={}),
            lambda ledger: self.scenario(ledger, "FS05").update(mechanism_refs=[None]),
        ):
            ledger = self.ledger()
            change(ledger)
            self.assertTrue(self.checker.validate_ledger(ledger, self.root))

    def invoke(self, payload, *, reference="docs/validation/synthetic-ledger.json"):
        script = self.root / "tests/support/check_scenario_coverage.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CHECKER, script)
        ledger_path = self.root / "docs/validation/synthetic-ledger.json"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_bytes(payload)
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(script), "--ledger", reference],
            cwd=self.root.parent, capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

    def test_standalone_cli_checks_structure_only_without_modifying_the_ledger(self):
        payload = json.dumps(self.ledger(), ensure_ascii=False).encode("utf-8")
        process = self.invoke(payload)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["scenario_count"], 163)
        self.assertEqual(report["state_counts"], dict(verified=1, covered_by_mechanism=1, unsupported=157, conditional=4))
        self.assertEqual(report["semantic_verification"], "not_performed")
        self.assertEqual((self.root / "docs/validation/synthetic-ledger.json").read_bytes(), payload)
        self.assertEqual(process.stderr, "")

    def test_cli_rejects_bad_ledger_json_and_escaping_input_without_traceback(self):
        for payload in (b"{", b"\xff", b'{"schema_version":"1.0","schema_version":"2.0"}', b'{"scenarios":NaN}'):
            with self.subTest(payload=payload):
                process = self.invoke(payload)
                self.assertEqual(process.returncode, 1)
                self.assertFalse(json.loads(process.stdout)["ok"])
                self.assertNotIn("Traceback", process.stderr)
        process = self.invoke(b"{}", reference="../outside.json")
        self.assertEqual(process.returncode, 1)
        self.assertFalse(json.loads(process.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
