"""Offline checks for native decision dispatch and its child transport."""

import base64
from contextlib import redirect_stdout
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib import error

from classification_bench.adapters import PreparedRequest
from classification_bench.decision_adapters import DecisionAdapter
from classification_bench.decision_network import _CHILD, isolated_decision_dispatch
from classification_bench.isolation import IsolationError


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status


class FakeOpener:
    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.exception is not None:
            raise self.exception
        return self.response


def run_child(capsule, opener):
    """Execute the exact child source with urllib replaced before any open."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "capsule.json"
        path.write_text(json.dumps(capsule), encoding="utf-8")
        output = io.StringIO()
        with patch.object(sys, "argv", ["decision-child", str(path)]), \
                patch("urllib.request.build_opener", return_value=opener) as build, \
                redirect_stdout(output):
            exec(compile(_CHILD, "<decision-child>", "exec"), {"__name__": "__main__"})
        return json.loads(output.getvalue()), build.call_args


def capsule(kind="liquid_decide", **extra):
    return {"kind": kind, "body": base64.b64encode(b'{"state":"synthetic"}').decode(),
            "api_key": "synthetic-key", **extra}


def untrusted_adapter(kind="liquid_decide", *, workspace="example", region="ap-southeast-1"):
    """The dispatch boundary must also defend against a mutated adapter object."""
    adapter = object.__new__(DecisionAdapter)
    adapter.kind = kind
    adapter.provider = {"liquid_decide": "liquid", "solar_decide": "upstage",
                        "qwen_decision": "qwen"}[kind]
    adapter.model = {"liquid_decide": "d1:free", "solar_decide": "solar-decide",
                     "qwen_decision": "decision-model-preview"}[kind]
    adapter.config = {"settings": {"workspace_id": workspace, "region": region}}
    return adapter


class DecisionNetworkTests(unittest.TestCase):
    def test_capsule_contains_only_dispatch_material_and_private_file(self):
        adapter = untrusted_adapter("qwen_decision")
        prepared = PreparedRequest(b'{"state":"synthetic"}', 1, "synthetic-source",
                                   "qwen:decision-model-preview", "request-1", ("case-1",))
        seen = {}

        class Worker:
            def run(self, path, source):
                seen["capsule"] = json.loads(Path(path).read_text(encoding="utf-8"))
                seen["mode"] = Path(path).stat().st_mode & 0o777
                seen["source"] = source
                return SimpleNamespace(stdout=json.dumps({
                    "raw_bytes": base64.b64encode(b"response").decode(),
                    "http_status": 200, "duration_ms": 2, "error": None,
                    "redacted": False, "truncated": False,
                }).encode())

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "environment-secret",
                                     "PRIVATE_REFERENCE_PATH": "/private/reference.json"}):
            result = isolated_decision_dispatch(adapter, prepared, "synthetic-key", worker=Worker())
        self.assertEqual(result.raw_bytes, b"response")
        self.assertEqual(set(seen["capsule"]), {"kind", "body", "api_key", "workspace_id", "region"})
        self.assertEqual(seen["capsule"]["api_key"], "synthetic-key")
        self.assertEqual(base64.b64decode(seen["capsule"]["body"]), prepared.body)
        self.assertNotIn("environment-secret", json.dumps(seen["capsule"]))
        self.assertNotIn("/private/reference.json", json.dumps(seen["capsule"]))
        self.assertEqual(seen["mode"], 0o600)
        self.assertEqual(seen["source"], _CHILD)

    def test_child_uses_pinned_endpoints_one_post_and_no_redirect_handler(self):
        routes = (
            ("liquid_decide", {}, "https://api.liquid.ai/decisions/v1/systemone"),
            ("solar_decide", {}, "https://api.upstage.ai/v1/systemone"),
            ("qwen_decision", {"workspace_id": "example", "region": "ap-southeast-1"},
             "https://example.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/systemone"),
        )
        for kind, extra, endpoint in routes:
            with self.subTest(kind=kind):
                opener = FakeOpener(Response(b"{}"))
                value, build = run_child(capsule(kind, **extra), opener)
                self.assertEqual(value["http_status"], 200)
                self.assertEqual(len(opener.calls), 1)
                request, timeout = opener.calls[0]
                self.assertEqual(request.full_url, endpoint)
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(request.data, b'{"state":"synthetic"}')
                self.assertEqual(timeout, 60)
                self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")
                handlers = build.args
                self.assertEqual(len(handlers), 2)
                self.assertEqual(handlers[0].proxies, {})
                self.assertIsNone(handlers[1].redirect_request(request, None, 302, "redirect", {},
                                                                 "https://other.example/"))

    def test_http_error_and_redirect_are_recorded_without_retry(self):
        for status in (429, 302):
            with self.subTest(status=status):
                response = error.HTTPError("https://api.liquid.ai/decisions/v1/systemone", status,
                                           "provider response", {}, io.BytesIO(b"provider body"))
                opener = FakeOpener(exception=response)
                value, _ = run_child(capsule(), opener)
                self.assertEqual(value["http_status"], status)
                self.assertEqual(base64.b64decode(value["raw_bytes"]), b"provider body")
                self.assertIsNone(value["error"])
                self.assertEqual(len(opener.calls), 1)

    def test_partial_read_and_transport_error_preserve_distinct_evidence(self):
        class PartialResponse(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b"partial bytes", 20)

        partial, _ = run_child(capsule(), FakeOpener(PartialResponse(b"")))
        self.assertEqual(base64.b64decode(partial["raw_bytes"]), b"partial bytes")
        self.assertEqual(partial["error"], "IncompleteRead")
        self.assertFalse(partial["truncated"])
        failed_opener = FakeOpener(exception=error.URLError("synthetic failure"))
        failed, _ = run_child(capsule(), failed_opener)
        self.assertIsNone(failed["http_status"])
        self.assertEqual(base64.b64decode(failed["raw_bytes"]), b"")
        self.assertEqual(failed["error"], "URLError")
        self.assertEqual(len(failed_opener.calls), 1)

    def test_truncation_and_credential_redaction(self):
        long_body = b"x" * 1_000_001
        value, _ = run_child(capsule(), FakeOpener(Response(long_body)))
        self.assertEqual(len(base64.b64decode(value["raw_bytes"])), 1_000_000)
        self.assertTrue(value["truncated"])
        value, _ = run_child(capsule(), FakeOpener(Response(b"before synthetic-key after")))
        self.assertEqual(base64.b64decode(value["raw_bytes"]), b"before [REDACTED_API_KEY] after")
        self.assertTrue(value["redacted"])

    def test_qwen_route_rejects_malicious_workspace_before_transport(self):
        for workspace in ("evil.example", "bad/path", "-leading", "a" * 64):
            with self.subTest(workspace=workspace):
                opener = FakeOpener(Response(b"{}"))
                with self.assertRaisesRegex(ValueError, "invalid Qwen route"):
                    run_child(capsule("qwen_decision", workspace_id=workspace,
                                      region="ap-southeast-1"), opener)
                self.assertEqual(opener.calls, [])

    def test_parent_rejects_route_mismatch_before_worker(self):
        adapter = untrusted_adapter()
        prepared = PreparedRequest(b"{}", 1, "source", "wrong:route", "request-1", ("case-1",))
        with self.assertRaisesRegex(IsolationError, "route mismatch"):
            isolated_decision_dispatch(adapter, prepared, "synthetic-key", worker=object())


if __name__ == "__main__":
    unittest.main()
