"""Offline tests for the network child boundary and real OS preflight."""

import base64
import json
import os
import platform
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classification_bench.adapters import OpenRouterAdapter, PreparedRequest
from classification_bench.isolation import IsolationError, IsolationUnavailable, WorkerResult
from classification_bench.network_isolation import (
    NetworkSandboxedPythonWorker, isolated_dispatch, isolated_lookup_generation,
)


class RecordingWorker:
    def __init__(self, output=None):
        self.output = output or {"raw_bytes": base64.b64encode(b'{"id":"fixture"}').decode(),
                                 "http_status": 200, "duration_ms": 7,
                                 "error": None, "redacted": False, "truncated": False}
        self.path = None
        self.capsule = None
        self.mode = None
        self.source = None

    def run(self, path, source):
        self.path = path
        self.mode = stat.S_IMODE(os.stat(path).st_mode)
        self.capsule = json.loads(Path(path).read_text())
        self.source = source
        return WorkerResult(json.dumps(self.output).encode(), b"", 0)


class NetworkIsolationTests(unittest.TestCase):
    def setUp(self):
        self.adapter = object.__new__(OpenRouterAdapter)
        self.adapter.config = {"id": "fixture", "model": "vendor/model", "settings": {}}
        self.prepared = PreparedRequest(b'{"body":"fixture"}', 3, "source", "openrouter:vendor/model:pinned",
                                        "request-1", ("case-1",))

    def test_dispatch_capsule_is_private_ephemeral_and_child_receives_only_transport_inputs(self):
        worker = RecordingWorker()
        result = isolated_dispatch(self.adapter, self.prepared, "fixture-secret", worker=worker)
        self.assertEqual(result.raw_bytes, b'{"id":"fixture"}')
        self.assertEqual(result.http_status, 200)
        self.assertEqual(worker.mode, 0o600)
        self.assertEqual(worker.capsule["action"], "dispatch")
        self.assertEqual(worker.capsule["api_key"], "fixture-secret")
        self.assertEqual(base64.b64decode(worker.capsule["prepared"]["body"]), self.prepared.body)
        self.assertNotIn("labels", worker.capsule)
        self.assertNotIn("fixture-secret", worker.source)
        self.assertFalse(worker.path.exists())
        self.assertIn("_adapter.dispatch", worker.source)

    def test_generation_lookup_uses_same_boundary_and_removes_capsule(self):
        worker = RecordingWorker()
        result = isolated_lookup_generation(self.adapter, "generation-1", "fixture-secret", worker=worker)
        self.assertEqual(result.duration_ms, 7)
        self.assertEqual(worker.capsule["action"], "lookup_generation")
        self.assertEqual(worker.capsule["response_id"], "generation-1")
        self.assertFalse(worker.path.exists())
        self.assertIn("_adapter.lookup_generation", worker.source)

    def test_malformed_child_evidence_fails_closed_and_cleans_capsule(self):
        worker = RecordingWorker(output={"raw_bytes": "not-base64", "http_status": 200,
                                         "duration_ms": 1, "error": None,
                                         "redacted": False, "truncated": False})
        with self.assertRaisesRegex(IsolationError, "invalid evidence"):
            isolated_dispatch(self.adapter, self.prepared, "fixture-secret", worker=worker)
        self.assertFalse(worker.path.exists())

    def test_profile_keeps_https_port_bounded_and_has_no_home_or_repo_subpath(self):
        worker = NetworkSandboxedPythonWorker()
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            capsule = Path(temp) / "capsule"
            capsule.write_bytes(b"fixture")
            with patch.object(worker, "_require_host"):
                profile = worker._profile(capsule)
        self.assertIn('(remote tcp "*:443")', profile)
        self.assertIn('(remote udp "*:53")', profile)
        self.assertIn("(deny default)", profile)
        self.assertNotIn('(subpath "/Users")', profile)
        self.assertNotIn("classification-bench", profile)

    def test_real_network_profile_proves_reference_symlink_and_environment_denial(self):
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec preflight requires macOS")
        try:
            proof = NetworkSandboxedPythonWorker().probe()
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in enclosing runtime: {exc}")
        self.assertTrue(all(proof[key] for key in
                            ("capsule_read", "reference_denied", "symlink_denied",
                             "tcp_443_allowed", "environment_scrubbed")))


if __name__ == "__main__":
    unittest.main()
