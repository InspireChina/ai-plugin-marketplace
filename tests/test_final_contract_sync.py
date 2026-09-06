from pathlib import Path
import ast
import unittest
import importlib.util
import tempfile


ROOT = Path(__file__).resolve().parents[1]


class FinalContractSyncTests(unittest.TestCase):
    def test_prior_and_demo_descriptions_match_effective_contract(self):
        for relative in ('README.md', 'docs/AI_SOW_PLUGIN_DESIGN.md', 'docs/CONTEXT.md'):
            text = (ROOT / 'plugins/ai-sow' / relative).read_text()
            with self.subTest(path=relative):
                self.assertNotIn('不自动证明', text)
                self.assertNotIn('往期合同本身不证明', text)
                self.assertIn('合同推定', text)
                self.assertIn('静态 HTML/CSS/JavaScript bundle', text)

    def test_current_docs_reject_retired_tokens(self):
        spec = importlib.util.spec_from_file_location('final_repository_validator', ROOT / 'scripts/validate_repository.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for token in ('currentStateDelta', 'REFERENCE_ONLY', 'RENDER_ONLY', 'DELTA_COMPILE',
                          '固定 3×8', 'stage approval', 'Demo-as-current-state'):
                (root / 'README.md').write_text(token)
                self.assertTrue(module.validate_current_behavior_text(root), token)
            (root / 'README.md').write_text('FULL_COMPILE 自动封存')
            self.assertEqual(module.validate_current_behavior_text(root), [])

    def test_approval_and_ownership_are_explicit(self):
        for relative in ('README.md', 'plugins/ai-sow/README.md',
                         'plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md',
                         'plugins/ai-sow/skills/generate/SKILL.md'):
            text = (ROOT / relative).read_text()
            with self.subTest(path=relative):
                self.assertIn('两份 Excel', text)
                self.assertIn('PairDecision', text)
                self.assertIn('自动封存', text)
        design = (ROOT / 'plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md').read_text()
        for term in ('PriorStateSnapshot', 'ChangeGraph', 'Scope 独占',
                     'pair harness 不属于插件业务 Owner', '模板是'):
            self.assertIn(term, design)

    def test_obsolete_benchmark_execution_entry_is_removed(self):
        self.assertFalse((ROOT / 'plugins/ai-sow/tests/support/run_pipeline_benchmark.py').exists())
        path = ROOT / 'plugins/ai-sow/tests/support/analyze_historical_benchmark.py'
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertIn('已取代', text)
        for token in ('public_prepare', 'session.json', 'baseline-init', 'next-action'):
            self.assertNotIn(token, text)

    def test_copy_smoke_does_not_infer_freshness_from_envelope_version(self):
        text = (ROOT / 'plugins/ai-sow/tests/support/smoke_plugin.py').read_text()
        self.assertNotIn('"executionPolicy" not in action', text)
        self.assertIn('fixtureProcessIsolation', text)
        self.assertIn('actualProviderVerified', text)
        self.assertIn('fresh_fixture_worker.py', text)
