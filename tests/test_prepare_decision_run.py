"""Native run preparation is offline, private, and never an authorization."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrepareDecisionTests(unittest.TestCase):
    def test_each_native_route_prepares_without_secrets_or_dispatch(self):
        sources = {
            'liquid_decide': 'https://docs.liquid.ai/lfm/models/decision-models',
            'solar_decide': 'https://console.upstage.ai/api/systemone',
            'qwen_decision': 'https://help.aliyun.com/en/model-studio/decision-model-preview',
        }
        with tempfile.TemporaryDirectory() as tmp:
            for adapter, source in sources.items():
                for mode, policy, count in [('smoke', 'pause', 3), ('full', 'stop', 18)]:
                    with self.subTest(adapter=adapter, mode=mode):
                        snapshot = Path(tmp) / 'billing.json'
                        # Synthetic evidence for preparation only; the digest cannot
                        # pass a live source check and this grants no authorization.
                        snapshot.write_text(json.dumps({
                            'source_url': source, 'response_sha256': 'a' * 64,
                            'observed_at': '2026-09-30T00:00:00Z',
                            'valid_until': '2026-10-01T00:00:00Z',
                            'max_input_tokens': 65536 if adapter == 'qwen_decision' else 524288,
                            'input_usd_per_token': '0', 'output_usd_per_token': '0',
                            'request_usd': '0', 'basis': 'free',
                        }))
                        directory = Path(tmp) / f'{adapter}-{mode}'
                        args = [sys.executable, '-m', 'scripts.prepare_decision_run',
                                '--directory', str(directory), '--adapter', adapter,
                                '--billing-snapshot', str(snapshot), '--mode', mode,
                                '--budget-usd', '0.75', '--on-budget-exhausted', policy]
                        if adapter == 'qwen_decision':
                            args += ['--workspace-id', '123456', '--region', 'cn-beijing']
                        result = subprocess.run(args, cwd=ROOT, capture_output=True,
                                                text=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        output = json.loads(result.stdout)
                        self.assertEqual(output['request_count'], count)
                        self.assertEqual(output['model_calls'], 0)
                        self.assertEqual(output['cap_micro_usd'], 750000)
                        config = json.loads((directory / 'config.json').read_text())
                        self.assertEqual(config['on_budget_exhausted'], policy)
                        self.assertFalse((directory / 'authorization.json').exists())
                        self.assertFalse((directory / 'run.sqlite').exists())
                        self.assertFalse((directory / 'labels.json').exists())
                        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                        for path in directory.iterdir():
                            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_qwen_requires_explicit_workspace_and_region(self):
        result = subprocess.run(
            [sys.executable, '-m', 'scripts.prepare_decision_run',
             '--directory', '/unused', '--adapter', 'qwen_decision',
             '--billing-snapshot', '/unused.json', '--mode', 'smoke',
             '--budget-usd', '0.50'], cwd=ROOT, capture_output=True, text=True,
            timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Qwen requires', result.stderr)

    def test_clef_preparation_is_offline_and_keeps_separate_model_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind, model, rate, bound in (
                    ('clef_decide', 'clef', '0.00000024', 15729),
                    ('clef_flash_decide', 'clef-flash', '0.00000009', 5899)):
                with self.subTest(kind=kind):
                    snapshot = Path(tmp) / f'{kind}-billing.json'
                    snapshot.write_text(json.dumps({
                        'source_url': f'https://developers.cloudflare.com/workers-ai/models/{model}/',
                        'response_sha256': 'a' * 64,
                        'observed_at': '2026-10-02T00:00:00Z',
                        'valid_until': '2026-10-03T00:00:00Z',
                        'max_input_tokens': 65536,
                        'input_usd_per_token': rate, 'output_usd_per_token': '0',
                        'request_usd': '0', 'basis': 'metered'}))
                    directory = Path(tmp) / kind
                    result = subprocess.run([
                        sys.executable, '-m', 'scripts.prepare_decision_run',
                        '--directory', str(directory), '--adapter', kind,
                        '--account-id', 'a' * 32, '--billing-snapshot', str(snapshot),
                        '--mode', 'smoke', '--budget-usd', '0.25',
                        '--on-budget-exhausted', 'pause'],
                        cwd=ROOT, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertEqual(output['request_count'], 3)
                    self.assertEqual(output['model_calls'], 0)
                    self.assertEqual(output['sum_request_bounds_micro_usd'], 3 * bound)
                    self.assertFalse((directory / 'authorization.json').exists())
                    self.assertFalse((directory / 'run.sqlite').exists())
                    config = json.loads((directory / 'experiment.json').read_text())
                    self.assertEqual(config['configs'][0]['model'], model)
                    self.assertEqual(config['configs'][0]['settings']['account_id'], 'a' * 32)
