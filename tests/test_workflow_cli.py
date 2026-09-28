"""A second operator can reproduce both fixtures using only documented commands."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def invoke(self, *args):
        result = subprocess.run([sys.executable, '-m', *args], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_both_task_demos_status_rerun_and_private_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in ('candidate', 'product'):
                directory = Path(tmp)/fixture
                outcome = self.invoke('scripts.offline_demo', '--task', fixture, '--directory', str(directory))
                self.assertEqual(outcome['live_model_calls'], 0)
                self.assertEqual(outcome['execution']['completed_requests'], 24)
                config = str(directory/'config.json')
                status = self.invoke('classification_bench', 'status', '--config', config)
                self.assertEqual(status['status'], 'completed')
                rerun = self.invoke('classification_bench', 'run', '--config', config)
                self.assertEqual(rerun['completed_requests'], 24)
                report_path = directory/'second-report.html'
                report = self.invoke('classification_bench', 'report', '--config', config,
                                     '--labels', str(ROOT/'examples'/fixture/'labels.json'),
                                     '--out', str(report_path))
                self.assertEqual(report['visibility'], 'private-local')
                html = report_path.read_text()
                self.assertIn('Observed position outcomes', html)
                self.assertIn('Requested provider', html)
                self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)

    def test_budget_amount_validation(self):
        from scripts.prepare_run import budget_units
        import argparse
        self.assertEqual(budget_units('0.50'), 500000)
        for value in ('NaN','Infinity','0','-1','0.0000001'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                budget_units(value)
