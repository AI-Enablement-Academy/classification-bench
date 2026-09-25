"""Synthetic OS-boundary tests; no benchmark data or provider access."""

import os
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classification_bench.isolation import (
    IsolationError,
    IsolationTimeout,
    IsolationUnavailable,
    SandboxedPythonWorker,
)


class IsolationTests(unittest.TestCase):
    def test_nonfinite_timeout_is_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(IsolationError):
                SandboxedPythonWorker(timeout_seconds=value)

    def test_unsupported_platform_fails_closed(self):
        with patch("classification_bench.isolation.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(IsolationUnavailable, "unsupported"):
                SandboxedPythonWorker().probe()

    def test_capsule_validation_rejects_relative_missing_and_symlink(self):
        worker = SandboxedPythonWorker()
        with self.assertRaises(IsolationError):
            worker._capsule("relative-file")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(IsolationError):
                worker._capsule(root / "missing")
            actual = root / "actual"
            actual.write_bytes(b"synthetic")
            link = root / "link"
            link.symlink_to(actual)
            with self.assertRaises(IsolationError):
                worker._capsule(link)

    def test_real_os_denials_and_scrubbed_environment(self):
        worker = SandboxedPythonWorker()
        # A skipped positive test is never proof that this host is supported.
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec probe requires macOS")
        try:
            proof = worker.probe()
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in this enclosing runtime: {exc}")
        self.assertEqual(proof["platform"], "Darwin")
        self.assertTrue(all(proof[key] for key in
                            ("capsule_read", "reference_denied", "symlink_denied",
                             "network_denied", "environment_scrubbed")))
        with tempfile.TemporaryDirectory(prefix="classification-run-", dir="/private/tmp") as directory:
            capsule = Path(directory) / "capsule"
            capsule.write_bytes(b"capsule-only")
            (Path(directory) / "reference").write_bytes(b"synthetic-reference")
            source = "import os,sys; print(open(sys.argv[1],'rb').read().decode()); print(os.getenv('FAKE_PROVIDER_KEY'))"
            with patch.dict(os.environ, {"FAKE_PROVIDER_KEY": "synthetic-secret"}):
                result = worker.run(capsule, source)
            self.assertEqual(result.stdout, b"capsule-only\nNone\n")

    def test_timeout_kills_child(self):
        worker = SandboxedPythonWorker(timeout_seconds=1)
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec timeout requires macOS")
        try:
            worker.probe()
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in this enclosing runtime: {exc}")
        with tempfile.TemporaryDirectory(prefix="classification-timeout-", dir="/private/tmp") as directory:
            capsule = Path(directory) / "capsule"
            capsule.write_bytes(b"synthetic")
            with self.assertRaises(IsolationTimeout):
                worker.run(capsule, "while True: pass")

    def test_output_limit_stops_child(self):
        worker = SandboxedPythonWorker(max_output_bytes=512)
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec output limit requires macOS")
        try:
            worker.probe()
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in this enclosing runtime: {exc}")
        with tempfile.TemporaryDirectory(prefix="classification-output-", dir="/private/tmp") as directory:
            capsule = Path(directory) / "capsule"
            capsule.write_bytes(b"synthetic")
            with self.assertRaisesRegex(IsolationError, "output exceeds"):
                worker.run(capsule, "import sys; sys.stdout.write('x' * 10000)")


if __name__ == "__main__":
    unittest.main()
