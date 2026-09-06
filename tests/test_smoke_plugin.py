from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_PATH = REPO_ROOT / "plugins/ai-sow/tests/support/smoke_plugin.py"


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("ai_sow_smoke", SMOKE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import smoke module: {SMOKE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PluginSmokeTests(unittest.TestCase):
    def test_copied_plugin_runs_outside_marketplace(self) -> None:
        run_smoke = load_smoke_module().run_smoke

        temp_dir = Path(tempfile.mkdtemp(prefix="ai-sow-root-smoke-"))
        try:
            report = run_smoke(
                REPO_ROOT / "plugins/ai-sow",
                temp_dir,
                copy_plugin=True,
            )
            self.assertEqual(report["pluginName"], "ai-sow")
            self.assertEqual(report["pluginVersion"], "0.1.0-beta.2")
            self.assertEqual(report["publicSkills"], ["generate"])
            self.assertEqual(report["greenfieldOutcome"], "PUBLISHED")
            self.assertEqual(report["brownfieldOutcome"], "PUBLISHED")
            self.assertEqual(report["blockedResumeOutcome"], "PUBLISHED")
            self.assertEqual({run["change"] for run in report["freshRuns"]}, {"same-input", "template-bytes", "business-input"})
            self.assertTrue(all(run["route"] == "FULL_COMPILE" and run["outcome"] == "PUBLISHED" and run["actionCount"] > 0 for run in report["freshRuns"]))
            self.assertEqual(report["hostInterface"], "PYTHON_API_NEXT_ACTION")
            self.assertEqual(report["marketplaceReadCount"], 0)
            for path in report["workbookPaths"]:
                self.assertTrue(Path(path).is_file())
        except Exception:
            self.assertTrue((temp_dir / "failure-receipt.json").is_file())
            raise
        else:
            shutil.rmtree(temp_dir)

    def test_root_smoke_test_does_not_delete_failed_evidence(self) -> None:
        run_smoke = load_smoke_module().run_smoke
        work_dir = Path(tempfile.mkdtemp(prefix="ai-sow-root-smoke-failure-"))
        try:
            with self.assertRaises(FileNotFoundError):
                run_smoke(
                    work_dir / "missing-plugin",
                    work_dir,
                    copy_plugin=True,
                )
            receipt_path = work_dir / "failure-receipt.json"
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "FAILED")
        finally:
            shutil.rmtree(work_dir)


if __name__ == "__main__":
    unittest.main()
