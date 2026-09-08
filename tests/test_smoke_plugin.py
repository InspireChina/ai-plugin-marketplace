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
