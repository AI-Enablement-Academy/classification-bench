"""macOS file-isolated HTTPS transport for the pinned OpenRouter adapter.

The operating-system profile permits TCP port 443, not a domain allowlist.
The trusted adapter supplies the fixed endpoint and must reject redirects.
"""

import base64
import errno
import json
import os
from pathlib import Path
import ssl
import tempfile

from .adapters import OpenRouterAdapter, PreparedRequest, TransportResult
from .isolation import (IsolationError, IsolationUnavailable, SandboxedPythonWorker,
                        _ancestors, _literal, _subpath)


_CERT_PATHS = ("/etc/ssl", "/private/etc/ssl")
_DNS_FILES = ("/etc/resolv.conf", "/private/etc/resolv.conf",
              "/etc/hosts", "/private/etc/hosts")
_HOMEBREW_TLS_LIBRARIES = (
    "/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib",
    "/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib",
)


def _exact_https_runtime_files():
    """Return file aliases and real targets, never a Homebrew subtree grant."""
    paths = set()
    defaults = ssl.get_default_verify_paths()
    # The child has a scrubbed environment. Use OpenSSL's compiled default,
    # never a parent SSL_CERT_FILE override that could name reference data.
    candidates = [*(_HOMEBREW_TLS_LIBRARIES), defaults.openssl_cafile,
                  *(_DNS_FILES)]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            paths.add(str(path))
            paths.add(str(path.resolve()))
    return paths


class NetworkSandboxedPythonWorker(SandboxedPythonWorker):
    """Preserve capsule-only data access while permitting outbound HTTPS."""

    def __init__(self, *, timeout_seconds=60, max_output_bytes=1_600_000):
        super().__init__(timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)

    def _profile(self, capsule):
        base = super()._profile(capsule)
        literals = set()
        for path in (*_CERT_PATHS, *_exact_https_runtime_files()):
            literals |= _ancestors(path)
        rules = " ".join(_literal(path) for path in sorted(literals))
        certs = " ".join(_subpath(path) for path in _CERT_PATHS)
        return (base + f"(allow file-read* {rules} {certs})"
                '(allow file-read-metadata (literal "/var"))'
                '(allow network-outbound (literal "/private/var/run/mDNSResponder"))'
                '(allow network-outbound (remote tcp "*:443"))'
                '(allow network-outbound (remote udp "*:53"))'
                '(allow network-outbound (remote tcp "*:53"))'
                '(allow mach-lookup (global-name "com.apple.mDNSResponder"))')

    def probe(self, *, require_https=True):
        """Prove the OS boundary; live admissions also require public HTTPS."""
        if type(require_https) is not bool:
            raise IsolationError("require_https must be a boolean")
        self._require_host()
        source = f"REQUIRE_HTTPS = {require_https}\n" + r'''
import json, os, socket, ssl, sys, urllib.request
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
context = ssl.create_default_context()
ca_count = len(context.get_ca_certs())
dns_resolved = False
public_https = False
if REQUIRE_HTTPS:
    resolved = socket.getaddrinfo('openrouter.ai', 443, type=socket.SOCK_STREAM)
    dns_resolved = bool(resolved)
    request = urllib.request.Request('https://openrouter.ai/api/v1/models',
                                     headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=8, context=context) as response:
        public_https = response.status == 200 and bool(response.read(1))
print(json.dumps({'capsule': read(sys.argv[1]),
                  'reference': read(os.path.join(root, 'reference')),
                  'symlink': read(os.path.join(root, 'reference-link')),
                  'network': network,
                  'ca_count': ca_count,
                  'dns_resolved': dns_resolved,
                  'public_https': public_https,
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
            detail = result.stderr.decode("utf-8", errors="replace")[-600:].strip()
            raise IsolationUnavailable(
                f"network sandbox preflight child failed with status {result.returncode}"
                + (f": {detail}" if detail else ""))
        try:
            observation = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IsolationUnavailable("network sandbox preflight emitted invalid evidence") from exc
        if (observation.get("capsule") != "allowlisted-capsule" or
                observation.get("reference") not in (errno.EPERM, errno.EACCES) or
                observation.get("symlink") not in (errno.EPERM, errno.EACCES) or
                observation.get("network") not in (0, errno.ECONNREFUSED) or
                type(observation.get("ca_count")) is not int or observation["ca_count"] < 1 or
                (require_https and observation.get("dns_resolved") is not True) or
                (require_https and observation.get("public_https") is not True) or
                observation.get("environment_keys") != ["LANG", "LC_ALL", "PYTHONIOENCODING"]):
            raise IsolationUnavailable("network sandbox preflight did not prove required HTTPS and allow/deny behavior")
        return {"platform": "Darwin", "capsule_read": True, "reference_denied": True,
                "symlink_denied": True, "tcp_443_allowed": True, "environment_scrubbed": True,
                "default_ca_loaded": True,
                "dns_resolved": observation.get("dns_resolved") is True,
                "public_https": observation.get("public_https") is True}

    def run(self, capsule_path, trusted_source):
        """Launch under the same OS profile after the caller's pre-grant probe.

        The matrix runner calls ``probe()`` immediately before durable
        admission. A second destination GET here would occur after admission
        and could create an unknown hold without attempting the paid POST.
        ``_launch`` still applies the deny-by-default sandbox to this child.
        """
        capsule = self._capsule(capsule_path)
        if (capsule.is_relative_to(self.runtime_root) or
                capsule.is_relative_to(self.runtime_alias) or
                capsule.is_relative_to(Path("/System"))):
            raise IsolationError("capsule cannot reside inside an allowed runtime")
        result = self._launch(capsule, trusted_source)
        if result.returncode != 0:
            raise IsolationError(f"sandboxed worker exited with status {result.returncode}")
        return result


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
