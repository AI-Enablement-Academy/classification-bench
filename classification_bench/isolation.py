"""Offline macOS sandbox-exec boundary for a short-lived Python child.

The child can read one capsule and its pinned Python/system runtime, but no
reference files or network. This does not authorize provider execution.
"""

import errno
import json
import math
import os
import platform
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


class IsolationUnavailable(RuntimeError):
    """The required OS sandbox could not be applied or verified."""


class IsolationError(RuntimeError):
    """The worker failed or its input violates the isolation contract."""


class IsolationTimeout(IsolationError):
    """The child exceeded its wall-clock deadline and was killed."""


@dataclass(frozen=True)
class WorkerResult:
    stdout: bytes
    stderr: bytes
    returncode: int


def _literal(path):
    value = os.fspath(path)
    if not value.startswith("/") or any(ord(char) < 32 or char in '"\\' for char in value):
        raise IsolationError("sandbox path must be absolute without controls, quotes, or backslashes")
    return f'(literal "{value}")'


def _subpath(path):
    value = os.fspath(path)
    _literal(value)  # Apply the same profile-escaping validation.
    return f'(subpath "{value}")'


def _ancestors(path):
    path = Path(path)
    return {str(path), *(str(parent) for parent in path.parents)}


class SandboxedPythonWorker:
    """Run trusted Python source in a verified, deny-by-default macOS child."""

    def __init__(self, *, timeout_seconds=5, max_output_bytes=1_000_000):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 60:
            raise IsolationError("timeout_seconds must be positive and at most 60")
        if type(max_output_bytes) is not int or max_output_bytes < 512:
            raise IsolationError("max_output_bytes must be an integer of at least 512")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.sandbox = Path("/usr/bin/sandbox-exec")
        self.python = Path(sys.executable)
        self.runtime_root = Path(sys.base_prefix).resolve()
        self.runtime_alias = Path(sys.base_prefix)
        # Homebrew framework Python needs its formula's shared files as well
        # as the framework prefix. Both paths are pinned to this interpreter.
        if self.runtime_root.parent.name == "Versions" and self.runtime_root.name[:1].isdigit():
            self.runtime_root = self.runtime_root.parents[3]
            self.runtime_alias = self.runtime_alias.parents[3]

    def _require_host(self):
        if platform.system() != "Darwin":
            raise IsolationUnavailable("macOS sandbox-exec is required; this platform is unsupported")
        if not self.sandbox.is_file():
            raise IsolationUnavailable("/usr/bin/sandbox-exec is unavailable")
        real_python = self.python.resolve()
        if not real_python.is_file() or not real_python.is_relative_to(self.runtime_root):
            raise IsolationUnavailable("Python executable is outside its pinned runtime root")

    @staticmethod
    def _capsule(path):
        supplied = Path(path)
        if not supplied.is_absolute():
            raise IsolationError("capsule path must be absolute")
        try:
            info = supplied.lstat()
        except FileNotFoundError as exc:
            raise IsolationError("capsule file is missing") from exc
        if not stat.S_ISREG(info.st_mode):
            raise IsolationError("capsule must be a regular file, not a symlink")
        return supplied.resolve(strict=True)

    def _profile(self, capsule):
        self._require_host()
        real_python = self.python.resolve()
        # Exact ancestor literals permit pathname traversal, not sibling data.
        literals = _ancestors(capsule) | _ancestors(self.python) | _ancestors(real_python)
        literals |= _ancestors(self.runtime_root) | _ancestors(self.runtime_alias)
        system_roots = ("/System",)
        for root in system_roots:
            literals |= _ancestors(root)
        rules = " ".join(_literal(path) for path in sorted(literals))
        subpaths = " ".join(_subpath(path) for path in
                            sorted({str(self.runtime_root), str(self.runtime_alias), *system_roots}))
        return f'(version 1)(deny default)(allow process*)(allow file-read* {rules} {subpaths})'

    def _launch(self, capsule, source):
        if not isinstance(source, str) or not source:
            raise IsolationError("trusted worker source must be a nonempty string")
        profile = self._profile(capsule)
        command = [str(self.sandbox), "-p", profile, str(self.python), "-I", "-S",
                   "-c", source, str(capsule)]
        # No inherited HOME, PATH, provider keys, proxy settings, or Python hooks.
        environment = {"LANG": "C", "LC_ALL": "C", "PYTHONIOENCODING": "utf-8"}
        try:
            child = subprocess.Popen(command, cwd="/", env=environment,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, close_fds=True,
                                     start_new_session=True)
        except OSError as exc:
            raise IsolationUnavailable(f"cannot launch sandbox-exec: {exc}") from exc
        output = {child.stdout: bytearray(), child.stderr: bytearray()}
        deadline = time.monotonic() + self.timeout_seconds
        try:
            with selectors.DefaultSelector() as selector:
                for stream in output:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IsolationTimeout("sandboxed child exceeded timeout and was killed")
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fileobj.fileno(), min(65536, self.max_output_bytes + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        output[key.fileobj].extend(chunk)
                        if sum(map(len, output.values())) > self.max_output_bytes:
                            raise IsolationError("sandboxed child output exceeds configured limit")
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except (IsolationError, subprocess.TimeoutExpired) as exc:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            for stream in output:
                stream.close()
            if isinstance(exc, subprocess.TimeoutExpired):
                raise IsolationTimeout("sandboxed child exceeded timeout and was killed") from exc
            raise
        stdout, stderr = (bytes(output[child.stdout]), bytes(output[child.stderr]))
        if child.returncode in (71, 134) or b"sandbox_apply: Operation not permitted" in stderr:
            raise IsolationUnavailable("macOS sandbox profile could not be applied")
        return WorkerResult(stdout, stderr, child.returncode)

    def probe(self):
        """Require actual capsule allow and reference, symlink, network denials."""
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
try:
    with socket.socket() as client:
        network = client.connect_ex(('127.0.0.1', 9))
except OSError as exc:
    network = exc.errno
print(json.dumps({'capsule': read(sys.argv[1]),
                  'reference': read(os.path.join(root, 'reference')),
                  'symlink': read(os.path.join(root, 'reference-link')),
                  'network': network,
                  'environment_keys': sorted(os.environ)}))
'''
        with tempfile.TemporaryDirectory(prefix="classification-isolation-", dir="/private/tmp") as temp:
            root = Path(temp)
            capsule = root / "capsule"
            capsule.write_bytes(b"allowlisted-capsule")
            (root / "reference").write_bytes(b"synthetic-reference")
            (root / "reference-link").symlink_to(root / "reference")
            result = self._launch(capsule, source)
        if result.returncode != 0:
            raise IsolationUnavailable(f"sandbox preflight child failed with status {result.returncode}")
        try:
            observation = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise IsolationUnavailable("sandbox preflight emitted invalid evidence") from exc
        denied = {errno.EPERM, errno.EACCES}
        if (observation.get("capsule") != "allowlisted-capsule" or
                observation.get("reference") not in denied or
                observation.get("symlink") not in denied or
                observation.get("network") not in denied or
                observation.get("environment_keys") != ["LANG", "LC_ALL", "PYTHONIOENCODING"]):
            raise IsolationUnavailable("sandbox preflight did not prove required allow/deny behavior")
        return {"platform": "Darwin", "capsule_read": True,
                "reference_denied": True, "symlink_denied": True,
                "network_denied": True, "environment_scrubbed": True}

    def run(self, capsule_path, trusted_source):
        """Run a trusted offline worker only after the live boundary probe passes."""
        self.probe()
        capsule = self._capsule(capsule_path)
        if capsule.is_relative_to(self.runtime_root) or capsule.is_relative_to(self.runtime_alias):
            raise IsolationError("capsule cannot reside inside the Python runtime allowance")
        if capsule.is_relative_to(Path("/System")):
            raise IsolationError("capsule cannot reside inside a system runtime allowance")
        result = self._launch(capsule, trusted_source)
        if result.returncode != 0:
            raise IsolationError(f"sandboxed worker exited with status {result.returncode}")
        return result
