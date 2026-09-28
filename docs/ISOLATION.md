# Offline worker isolation

`SandboxedPythonWorker` runs trusted, short-lived Python source in a macOS
`sandbox-exec` child. It is a reference-data boundary for a future provider
adapter, not a provider adapter or permission to dispatch a request. The caller
supplies one absolute regular-file capsule. The child receives that path as its
only argument and may read the file, its pinned Python runtime, and Apple's
`/System` tree. Ancestor directory metadata is also readable for path traversal.
It does not inherit the parent working directory or environment. The caller
cannot place a capsule inside the runtime or `/System` allowance.

Before each run, `probe()` starts a separate sandboxed child with synthetic
files. It requires successful reading of an allowlisted capsule and OS-level
`EPERM` or `EACCES` for a neighboring reference file, a symlink to that file,
and a loopback network connection. It also checks the child has only `LANG`,
`LC_ALL`, and `PYTHONIOENCODING` in its environment. If the host is unsupported,
`sandbox-exec` cannot apply a profile, or any required denial is absent, the
worker raises `IsolationUnavailable` and never runs the requested source
without the sandbox. A surrounding sandbox can itself prevent nested
`sandbox-exec`; this is an explicit unavailable result, not a passing probe.

The child starts with `-I -S`, no stdin, a 60-second maximum configurable
deadline, and a new process session. On timeout, the process group is killed.
The resolved interpreter's Homebrew formula root (when applicable), its alias,
and `/System` are allowed; `HOME` and the repository are not allowed. Capsules
must be absolute regular files rather than symlinks. The caller should construct
them from verified, minimal request material, without evaluator labels or
reference answers. This API does not construct or attest the capsule.

Example with synthetic input:

```python
from classification_bench.isolation import SandboxedPythonWorker

worker = SandboxedPythonWorker(timeout_seconds=5)
proof = worker.probe()
result = worker.run("/private/tmp/my-private-capsule", "import sys; print(open(sys.argv[1]).read())")
```

The checked property is the observed file and network boundary for this child
on this host. It is not a general containment guarantee for malicious Python or
native code, and it does not prove that caller-supplied source, capsule content,
provider attribution, or billing evidence is truthful. There is no provider
call, credential access, or subscription/API adapter here. The benchmark's
broader requirement is described in [Evidence contracts](EVIDENCE_CONTRACTS.md).

## Network-capable matrix worker

The new `NetworkSandboxedPythonWorker` preserves reference and symlink file denials and a scrubbed environment while permitting TCP443, DNS and specific certificate/resolver reads. Its real OS probe passes in the final integrated offline suite. The trusted OpenRouter adapter uses fixed HTTPS endpoints with redirects and proxies disabled. No live provider call was made to establish this file-boundary test; DNS/TLS connectivity to the provider remains part of the authorized smoke. See [current status](IMPLEMENTATION_STATUS.md).
