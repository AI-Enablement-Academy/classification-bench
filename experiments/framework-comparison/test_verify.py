"""A generated fixture directory alone must never verify as an executed run."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class VerifierEvidenceTests(unittest.TestCase):
    def test_missing_execution_evidence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(HERE / 'make_fixtures.py'), tmp], check=True, capture_output=True)
            result = subprocess.run([sys.executable, str(HERE / 'verify.py'), tmp], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing inspect attempt audit', result.stderr)
            self.assertNotIn('audit_prompt_bytes', result.stdout)


if __name__ == '__main__':
    unittest.main()
