"""Sandboxed, one-attempt HTTPS transport for native System One adapters."""

import base64
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .adapters import PreparedRequest, TransportResult
from .decision_adapters import DecisionAdapter
from .isolation import IsolationError, IsolationUnavailable
from .network_isolation import NetworkSandboxedPythonWorker


class DecisionNetworkWorker(NetworkSandboxedPythonWorker):
    def probe_endpoint(self, endpoint):
        """Prove local file denial and verified TLS to the exact native host."""
        super().probe(require_https=False)
        url = urlsplit(endpoint)
        if url.scheme != "https" or not url.hostname or url.port is not None:
            raise IsolationError("invalid native endpoint")
        source = ("import json, socket, ssl\n"
                  f"host = {url.hostname!r}\n"
                  "with socket.create_connection((host, 443), timeout=8) as raw:\n"
                  "    with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as tls:\n"
                  "        print(json.dumps({'host': host, 'version': tls.version()}))\n")
        with tempfile.TemporaryDirectory(prefix="classification-decision-probe-", dir="/private/tmp") as temp:
            capsule = Path(temp) / "capsule"
            capsule.write_bytes(b"probe")
            result = self._launch(capsule, source)
        if result.returncode != 0:
            raise IsolationUnavailable("native HTTPS sandbox preflight failed")
        try:
            value = json.loads(result.stdout)
        except (UnicodeError, ValueError) as exc:
            raise IsolationUnavailable("native HTTPS sandbox preflight returned invalid evidence") from exc
        if value.get("host") != url.hostname or not isinstance(value.get("version"), str):
            raise IsolationUnavailable("native TLS identity was not observed")
        return value


_CHILD = r'''
import base64, http.client, json, socket, sys, time
from urllib import error, request

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def capture(stream, limit):
    pieces = []
    size = 0
    failure = None
    while size <= limit:
        try:
            part = stream.read(min(65536, limit + 1 - size))
        except http.client.IncompleteRead as exc:
            part = exc.partial
            failure = 'IncompleteRead'
        except (OSError, TimeoutError) as exc:
            part = b''
            failure = type(exc).__name__
        if part:
            pieces.append(part)
            size += len(part)
        if not part or failure:
            break
    raw = b''.join(pieces)
    return raw[:limit], len(raw) > limit, failure

with open(sys.argv[1], 'r', encoding='utf-8') as stream:
    capsule = json.load(stream)
kind = capsule['kind']
if kind == 'liquid_decide':
    endpoint = 'https://api.liquid.ai/decisions/v1/systemone'
elif kind == 'solar_decide':
    endpoint = 'https://api.upstage.ai/v1/systemone'
elif kind == 'qwen_decision':
    import re
    workspace, region = capsule['workspace_id'], capsule['region']
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,62}', workspace) or region not in ('ap-southeast-1', 'cn-beijing'):
        raise ValueError('invalid Qwen route')
    endpoint = f'https://{workspace}.{region}.maas.aliyuncs.com/compatible-mode/v1/systemone'
else:
    raise ValueError('unsupported native adapter')
body = base64.b64decode(capsule['body'], validate=True)
key = capsule['api_key']
req = request.Request(endpoint, data=body,
                      headers={'Authorization': 'Bearer ' + key,
                               'Content-Type': 'application/json', 'Accept': 'application/json'},
                      method='POST')
opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
start = time.monotonic_ns()
try:
    try:
        response = opener.open(req, timeout=60)
    except error.HTTPError as exc:
        response = exc
    with response:
        status = response.status if hasattr(response, 'status') else response.code
        raw, truncated, failure = capture(response, 1_000_000)
    transport_error = failure
except (OSError, TimeoutError, socket.timeout, error.URLError) as exc:
    status, raw, truncated, transport_error = None, b'', False, type(exc).__name__
key_bytes = key.encode('utf-8')
redacted = key_bytes in raw
if redacted:
    raw = raw.replace(key_bytes, b'[REDACTED_API_KEY]')
print(json.dumps({'raw_bytes': base64.b64encode(raw).decode('ascii'),
                  'http_status': status, 'duration_ms': (time.monotonic_ns()-start)//1_000_000,
                  'error': transport_error, 'redacted': redacted, 'truncated': truncated},
                 separators=(',', ':')))
'''


def isolated_decision_dispatch(adapter, prepared, api_key, *, worker=None):
    if not isinstance(adapter, DecisionAdapter) or not isinstance(prepared, PreparedRequest):
        raise IsolationError("native adapter and prepared request required")
    if not isinstance(api_key, str) or not api_key or prepared.route != f"{adapter.provider}:{adapter.model}":
        raise IsolationError("native credential or route mismatch")
    capsule = {"kind": adapter.kind, "body": base64.b64encode(prepared.body).decode("ascii"),
               "api_key": api_key}
    if adapter.kind == "qwen_decision":
        capsule["workspace_id"] = adapter.config["settings"]["workspace_id"]
        capsule["region"] = adapter.config["settings"]["region"]
    worker = worker or DecisionNetworkWorker()
    with tempfile.TemporaryDirectory(prefix="classification-decision-call-", dir="/private/tmp") as temp:
        path = Path(temp) / "capsule.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            json.dump(capsule, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result = worker.run(path, _CHILD)
    try:
        value = json.loads(result.stdout)
        raw = base64.b64decode(value["raw_bytes"], validate=True)
        if (type(value["duration_ms"]) is not int or type(value["redacted"]) is not bool or
                type(value["truncated"]) is not bool or
                (value["http_status"] is not None and type(value["http_status"]) is not int) or
                (value["error"] is not None and not isinstance(value["error"], str))):
            raise ValueError("invalid native transport fields")
        return TransportResult(raw, value["http_status"], value["duration_ms"],
                               value["error"], value["redacted"], value["truncated"])
    except (ValueError, KeyError, TypeError) as exc:
        raise IsolationError("sandboxed native transport returned invalid evidence") from exc
