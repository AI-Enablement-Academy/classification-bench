# Implementation status: 2026-09-28

The first runner and report are implemented and offline verified. The release is not complete: live verification and a human second-operator handoff remain pending. The repository is private; the active candidate-experience benchmark was not edited or rerun.

## Verified locally

`python3 -m unittest discover -s tests -v` passed **136 tests with no skips** on macOS after running outside the enclosing development sandbox. The original baseline passed 78 tests. The expanded suite includes actual reference/symlink denials and environment scrubbing under both offline and HTTPS-enabled profiles, crash/receipt recovery, atomic shared budgets and cap-amendment races, mocked HTTP errors/partial bodies and identity checks, matrix ordering and process locking, pause/stop/top-up behavior, immutable report snapshots, and subprocess reproduction of both fictional task workflows.

The fictional candidate and product demos each complete 24 synthetic requests, retaining all 36 planned positions. Re-running a completed matrix preserves its request count. Generated reports are private local HTML files with mode 0600. Browser visual inspection was blocked by the browser tool's local-file URL policy; HTML generation, escaping, report calculations, filter code and supporting cases have automated tests, but visual rendering is unverified.

The final scoped independent code review returned **APPROVE**, with no confirmed BLOCKING findings. RESIDUAL: directly invoking `python3 scripts/prepare_run.py` does not resolve the package in an uninstalled checkout; the documented `python3 -m scripts.prepare_run` command works and was reproduced. This is an optional invocation convenience, not a failure of the supported workflow.

## Implemented boundaries

- Deterministic task/input/prompt/configuration/repeat/batch planning and preview; reference labels remain outside execution inputs.
- An adapter protocol, one pinned OpenRouter implementation, a public catalog helper and explicit unsupported-configuration rows. No subscription or native specialist method is substituted.
- A shared SQLite ledger, verified raw artifacts, durable transport metadata, process-locked orchestration, per-provider concurrent-request limits and declaration order within configurations.
- Explicit no-retry inference, retained unknown-cost holds, safe never-sent continuation, parsed-outcome recovery after receipt publication, and visible preflight blockers.
- Operator-configurable caps for smoke and full runs, `pause` or `stop` at exhaustion, and conditional run-bound cap increases with immutable history. Increases do not clear holds or above-bound freezes.
- A private report from one locked verified snapshot with full-denominator quality, class errors/support, prompt deltas, repeat ranges/flips, record-level outcomes, route filters, requested versus observed identity, and nullable timing/token/cost measurements.

The live child permits TCP443 and DNS under an OS file boundary. The trusted HTTP adapter pins destinations and rejects redirects; the OS rule is not a domain allowlist. The coordinator has access to local files; reference isolation is enforced for the inference child, not the whole operator account. Local authorization files are operator assertions and do not authenticate a payer.

## Pending gates

The [three-request smoke proposal](LIVE_SMOKE_PLAN.md) has no authorization or credential. Its suggested $0.50 cap is configurable; the observed catalog yields $0.314889 in summed conservative reservations. Only public endpoint metadata was fetched. No model request, credential lookup/transfer, public deployment or dataset publication occurred.

The following remain unverified: live serving and authentication, actual returned model/provider evidence, provider billing and timing behavior, browser rendering, and a second human operator's reproduction. Missing generation metadata is explicitly unverified, not silently inferred from the requested route. An observed completion charge may settle independently; missing or conflicting charge evidence retains a hold.

Use [RUNNER.md](RUNNER.md) for complete commands and [LIVE_SMOKE_PLAN.md](LIVE_SMOKE_PLAN.md) for the approval gate. Historical contract documents describe the checkpoint they introduced; this page records the integrated implementation's current status.
