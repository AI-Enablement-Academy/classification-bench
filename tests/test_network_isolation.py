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

from classification_bench.adapter_runtime import OpenRouterRuntime
from classification_bench.adapters import OpenRouterAdapter, PreparedRequest
from classification_bench.isolation import IsolationError, IsolationUnavailable, WorkerResult
from classification_bench.network_isolation import (
    NetworkSandboxedPythonWorker, _exact_https_runtime_files,
    isolated_dispatch, isolated_lookup_generation,
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

    def test_live_preflight_then_dispatch_has_no_second_public_probe(self):
        worker = NetworkSandboxedPythonWorker()
        probes = []

        def prove_once():
            probes.append("public HTTPS GET")
            if len(probes) > 1:
                raise IsolationUnavailable("transient public catalog failure")
            return {"public_https": True}

        response = {"raw_bytes": base64.b64encode(b'{"id":"fixture"}').decode(),
                    "http_status": 200, "duration_ms": 1,
                    "error": None, "redacted": False, "truncated": False}
        runtime = OpenRouterRuntime()
        with patch.object(worker, "probe", side_effect=prove_once), patch.object(
                worker, "_launch", return_value=WorkerResult(json.dumps(response).encode(), b"", 0)) as launch, patch.object(
                OpenRouterAdapter, "verify_live_snapshot", return_value={"catalog_sha256": "a" * 64}):
            source = runtime.preflight(self.adapter, self.prepared, worker)
            result = runtime.dispatch(self.adapter, self.prepared, "fixture-secret", worker)
        self.assertIn("catalog:" + "a" * 64, source)
        self.assertEqual(result.raw_bytes, b'{"id":"fixture"}')
        self.assertEqual(probes, ["public HTTPS GET"])
        self.assertEqual(launch.call_count, 1)

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
        self.assertIn('(remote tcp "*:53")', profile)
        self.assertIn('(allow file-read-metadata (literal "/var"))', profile)
        self.assertIn('(allow network-outbound (literal "/private/var/run/mDNSResponder"))', profile)
        self.assertIn("(deny default)", profile)
        self.assertNotIn('(subpath "/Users")', profile)
        self.assertNotIn('(subpath "/opt/homebrew")', profile)
        self.assertNotIn("classification-bench", profile)

    def test_profile_grants_only_exact_tls_cert_and_resolver_files(self):
        worker = NetworkSandboxedPythonWorker()
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            capsule = Path(temp) / "capsule"
            capsule.write_bytes(b"fixture")
            with patch.object(worker, "_require_host"):
                profile = worker._profile(capsule)
        for path in _exact_https_runtime_files():
            self.assertIn(f'(literal "{path}")', profile)
            self.assertNotIn(f'(subpath "{path}")', profile)
        if Path("/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib").is_file():
            self.assertIn('(literal "/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib")', profile)
            self.assertIn('(literal "/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib")', profile)
        self.assertNotIn('(subpath "/opt/homebrew/Cellar")', profile)

    def test_parent_ca_environment_cannot_grant_reference_file(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            secret = Path(temp) / "reference"
            secret.write_bytes(b"reference data")
            with patch.dict(os.environ, {"SSL_CERT_FILE": str(secret)}):
                paths = _exact_https_runtime_files()
                worker = NetworkSandboxedPythonWorker()
                capsule = Path(temp) / "capsule"
                capsule.write_bytes(b"fixture")
                with patch.object(worker, "_require_host"):
                    profile = worker._profile(capsule)
        self.assertNotIn(str(secret), paths)
        self.assertNotIn(f'(literal "{secret}")', profile)

    def test_preflight_requires_default_ca_dns_and_public_https_before_admission(self):
        worker = NetworkSandboxedPythonWorker()
        base = {"capsule": "allowlisted-capsule", "reference": 1, "symlink": 1,
                "network": 61, "ca_count": 100, "dns_resolved": True,
                "public_https": True,
                "environment_keys": ["LANG", "LC_ALL", "PYTHONIOENCODING"]}
        sources = []

        def launch(_capsule, source):
            sources.append(source)
            return WorkerResult(json.dumps(base).encode(), b"", 0)

        with patch.object(worker, "_require_host"), patch.object(worker, "_launch", side_effect=launch):
            proof = worker.probe()
        self.assertTrue(proof["default_ca_loaded"] and proof["dns_resolved"] and proof["public_https"])
        self.assertIn("ssl.create_default_context()", sources[0])
        self.assertIn("socket.getaddrinfo('openrouter.ai'", sources[0])
        self.assertIn("https://openrouter.ai/api/v1/models", sources[0])
        self.assertTrue(sources[0].startswith("REQUIRE_HTTPS = True\n"))
        self.assertNotIn("chat/completions", sources[0])
        for field, value in (("ca_count", 0), ("dns_resolved", False), ("public_https", False)):
            broken = {**base, field: value}
            with patch.object(worker, "_require_host"), patch.object(
                    worker, "_launch", return_value=WorkerResult(json.dumps(broken).encode(), b"", 0)):
                with self.assertRaisesRegex(IsolationUnavailable, "required HTTPS"):
                    worker.probe()
        offline = {**base, "dns_resolved": False, "public_https": False}
        with patch.object(worker, "_require_host"), patch.object(
                worker, "_launch", return_value=WorkerResult(json.dumps(offline).encode(), b"", 0)) as launch:
            proof = worker.probe(require_https=False)
        self.assertTrue(proof["default_ca_loaded"])
        self.assertFalse(proof["dns_resolved"] or proof["public_https"])
        self.assertTrue(launch.call_args.args[1].startswith("REQUIRE_HTTPS = False\n"))

    def test_real_network_profile_proves_reference_symlink_and_environment_denial(self):
        if platform.system() != "Darwin":
            self.skipTest("real sandbox-exec preflight requires macOS")
        try:
            proof = NetworkSandboxedPythonWorker().probe(require_https=False)
        except IsolationUnavailable as exc:
            self.skipTest(f"sandbox unavailable in enclosing runtime: {exc}")
        self.assertTrue(all(proof[key] for key in
                            ("capsule_read", "reference_denied", "symlink_denied",
                             "tcp_443_allowed", "environment_scrubbed",
                             "default_ca_loaded")))


if __name__ == "__main__":
    unittest.main()
