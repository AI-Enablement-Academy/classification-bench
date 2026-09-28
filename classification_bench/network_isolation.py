"""macOS file-isolated HTTPS transport for the pinned OpenRouter adapter.

The operating-system profile permits TCP port 443, not a domain allowlist.
The trusted adapter supplies the fixed endpoint and must reject redirects.
"""

import base64
import errno
import json
import os
from pathlib import Path
import tempfile

from .adapters import OpenRouterAdapter, PreparedRequest, TransportResult
from .isolation import (IsolationError, IsolationUnavailable, SandboxedPythonWorker,
                        _ancestors, _literal, _subpath)


_CERT_PATHS = ("/etc/ssl", "/private/etc/ssl")
_DNS_FILES = ("/etc/resolv.conf", "/private/etc/resolv.conf",
              "/etc/hosts", "/private/etc/hosts")


class NetworkSandboxedPythonWorker(SandboxedPythonWorker):
    """Preserve capsule-only data access while permitting outbound HTTPS."""

    def __init__(self, *, timeout_seconds=60, max_output_bytes=1_600_000):
        super().__init__(timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)

    def _profile(self, capsule):
        base = super()._profile(capsule)
        literals = set()
        for path in (*_CERT_PATHS, *_DNS_FILES):
            literals |= _ancestors(path)
        rules = " ".join(_literal(path) for path in sorted(literals))
        certs = " ".join(_subpath(path) for path in _CERT_PATHS)
        return (base + f"(allow file-read* {rules} {certs})"
                '(allow network-outbound (remote tcp "*:443"))'
                '(allow network-outbound (remote udp "*:53"))'
                '(allow mach-lookup (global-name "com.apple.mDNSResponder"))')

    def probe(self):
        """Prove file denials and port-443 allowance under this exact profile."""
        self._require_host()
        source = r'''
import json, os, socket, sys
root = os.path.dirname(sys.argv[1])
def read(path):
    try:
        with open(path, 'rb') as stream:
            return stream.read().decode('ascii')
    except OSError as exc:
        return exc.errno
with socket.socket() as client:
    client.settimeout(1)
    network = client.connect_ex(('127.0.0.1', 443))
print(json.dumps({'capsule': read(sys.argv[1]),
                  'reference': read(os.path.join(root, 'reference')),
                  'symlink': read(os.path.join(root, 'reference-link')),
                  'network': network,
                  'environment_keys': sorted(os.environ)}))
'''
        with tempfile.TemporaryDirectory(prefix="classification-network-probe-", dir="/private/tmp") as temp:
            root = Path(temp)
            capsule = root / "capsule"
            capsule.write_bytes(b"allowlisted-capsule")
            (root / "reference").write_bytes(b"synthetic-reference")
            (root / "reference-link").symlink_to(root / "reference")
            result = self._launch(capsule, source)
        if result.returncode != 0:
            raise IsolationUnavailable(f"network sandbox preflight child failed with status {result.returncode}")
        try:
            observation = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IsolationUnavailable("network sandbox preflight emitted invalid evidence") from exc
        if (observation.get("capsule") != "allowlisted-capsule" or
                observation.get("reference") not in (errno.EPERM, errno.EACCES) or
                observation.get("symlink") not in (errno.EPERM, errno.EACCES) or
                observation.get("network") not in (0, errno.ECONNREFUSED) or
                observation.get("environment_keys") != ["LANG", "LC_ALL", "PYTHONIOENCODING"]):
            raise IsolationUnavailable("network sandbox preflight did not prove required allow/deny behavior")
        return {"platform": "Darwin", "capsule_read": True, "reference_denied": True,
                "symlink_denied": True, "tcp_443_allowed": True, "environment_scrubbed": True}


_CHILD_SUFFIX = r'''
import base64 as _b64, json as _json, sys as _sys
with open(_sys.argv[1], 'rb') as _stream:
    _capsule = _json.load(_stream)
_adapter = OpenRouterAdapter(_capsule['config'])
if _capsule['action'] == 'dispatch':
    _p = _capsule['prepared']
    _prepared = PreparedRequest(_b64.b64decode(_p['body']), _p['reserve_microusd'],
                                _p['bound_source'], _p['route'], _p['request_id'],
                                tuple(_p['expected_ids']))
    _result = _adapter.dispatch(_prepared, _capsule['api_key'])
elif _capsule['action'] == 'lookup_generation':
    _result = _adapter.lookup_generation(_capsule['response_id'], _capsule['api_key'])
else:
    raise ValueError('unsupported sandbox action')
print(_json.dumps({'raw_bytes': _b64.b64encode(_result.raw_bytes).decode('ascii'),
                   'http_status': _result.http_status,
                   'duration_ms': _result.duration_ms,
                   'error': _result.error, 'redacted': _result.redacted,
                   'truncated': _result.truncated}, separators=(',', ':')))
'''


def _source():
    # The child has no repository read grant. Embed only the installed trusted
    # adapter code; its dependencies are Python's pinned standard library.
    source = Path(__file__).with_name("adapters.py").read_text(encoding="utf-8")
    return source + "\n" + _CHILD_SUFFIX


def _call(capsule, worker):
    worker = worker or NetworkSandboxedPythonWorker()
    with tempfile.TemporaryDirectory(prefix="classification-network-call-", dir="/private/tmp") as temp:
        path = Path(temp) / "capsule.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            json.dump(capsule, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result = worker.run(path, _source())
    try:
        value = json.loads(result.stdout)
        raw = base64.b64decode(value["raw_bytes"], validate=True)
        return TransportResult(raw, value["http_status"], value["duration_ms"],
                               value["error"], value["redacted"], value["truncated"])
    except (ValueError, KeyError, TypeError) as exc:
        raise IsolationError("sandboxed transport returned invalid evidence") from exc


def isolated_dispatch(adapter, prepared, api_key, *, worker=None):
    """Perform one provider attempt in a file-isolated child; never retry."""
    if not isinstance(adapter, OpenRouterAdapter) or not isinstance(prepared, PreparedRequest):
        raise IsolationError("OpenRouter adapter and prepared request required")
    if not isinstance(api_key, str) or not api_key:
        raise IsolationError("API key required")
    capsule = {"action": "dispatch", "config": adapter.config, "api_key": api_key,
               "prepared": {"body": base64.b64encode(prepared.body).decode("ascii"),
                            "reserve_microusd": prepared.reserve_microusd,
                            "bound_source": prepared.bound_source, "route": prepared.route,
                            "request_id": prepared.request_id, "expected_ids": list(prepared.expected_ids)}}
    return _call(capsule, worker)


def isolated_lookup_generation(adapter, response_id, api_key, *, worker=None):
    """Fetch generation metadata through the same file boundary."""
    if not isinstance(adapter, OpenRouterAdapter) or not isinstance(response_id, str) or not response_id:
        raise IsolationError("OpenRouter adapter and response ID required")
    if not isinstance(api_key, str) or not api_key:
        raise IsolationError("API key required")
    return _call({"action": "lookup_generation", "config": adapter.config,
                  "response_id": response_id, "api_key": api_key}, worker)
