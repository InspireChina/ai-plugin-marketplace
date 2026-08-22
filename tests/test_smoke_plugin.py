from __future__ import annotations

import importlib.util
import json
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

        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_smoke(
                REPO_ROOT / "plugins/ai-sow",
                Path(temp_dir),
                copy_plugin=True,
            )
            self.assertEqual(report["pluginName"], "ai-sow")
            self.assertEqual(report["pluginVersion"], "0.1.0-beta.1")
            self.assertEqual(report["setupOutcome"], "OK")
            self.assertEqual(report["validatorCount"], 5)
            self.assertEqual(report["generateOutcome"], "OK")
            self.assertTrue(Path(report["workbookPath"]).is_file())

            setup_project = json.loads(
                (Path(report["greenfieldProject"]) / ".ai-sow/project.json").read_text()
            )
            self.assertEqual(
                setup_project,
                {
                    "projectId": "smoke-greenfield",
                    "name": "Smoke Greenfield",
                    "pluginVersion": "0.1.0-beta.1",
                    "sowStandardVersion": "1.3",
                },
            )
            self.assertTrue(report["asisOwnsTechnicalIntake"])


if __name__ == "__main__":
    unittest.main()
