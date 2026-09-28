# Implementation status: 2026-09-28

The first runner and report are implemented and offline verified. The authorized smoke has partial live evidence, documented below. The release is not complete: live verification and browser report inspection remain pending. Independent subagent operator reproduction passed; see [operator results](OPERATOR_CHECK_RESULT.md). The repository is private; the active candidate-experience benchmark was not edited or rerun.

## Verified locally

`python3 -m unittest discover -s tests -v` passed **154 tests with no skips** on macOS after running outside the enclosing development sandbox. The original baseline passed 78 tests. The expanded suite includes actual reference/symlink denials and environment scrubbing under both offline and HTTPS-enabled profiles, crash/receipt recovery, atomic shared budgets and cap-amendment races, mocked HTTP errors/partial bodies and identity checks, matrix ordering and process locking, pause/stop/top-up behavior, immutable report snapshots, and subprocess reproduction of both fictional task workflows.

The fictional candidate and product demos each complete 24 synthetic requests, retaining all 36 planned positions. Re-running a completed matrix preserves its request count. Generated reports are private local HTML files with mode 0600. Browser visual inspection was blocked by the browser tool's local-file URL policy; HTML generation, escaping, report calculations, filter code and supporting cases have automated tests, but visual rendering is unverified.

The [custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md) defines an independent fictional support-routing task without either fixture helper. Its documented offline command sequence was executed in a fresh directory: 16 requests, 24 classification positions, 12 deliberately invalid outcomes, zero missing positions and no unresolved recovery work. It produced a private local report. This is command-level reproduction, not human visual verification.

A follow-up audit added nested reasoning/cache token extraction, separately labeled frozen-price estimates, a registered adapter runtime contract, and historical report/export reads that preserve the original source hashes. New dispatch still requires the exact enrolled implementation. See the [acceptance audit](ACCEPTANCE_AUDIT.md) and [adapter runtime contract](ADAPTER_RUNTIME.md).

The final scoped independent code review returned **APPROVE**, with no confirmed BLOCKING findings. RESIDUAL: directly invoking `python3 scripts/prepare_run.py` does not resolve the package in an uninstalled checkout; the documented `python3 -m scripts.prepare_run` command works and was reproduced. This is an optional invocation convenience, not a failure of the supported workflow. RESIDUAL: an older pending run requires its enrolled code version to dispatch or recover after implementation changes; read-only historical reports and exports remain available.

The generic OpenRouter identity update captures the public requested-to-canonical model mapping with raw bytes and a digest, revalidates it before admission, and displays completion and generation model identities separately. Older snapshots without that mapping retain exact matching. The integrated update passed independent review with no confirmed BLOCKING or RESIDUAL findings. Its new identity path has offline coverage; it has not been exercised in another live inference run.

## Implemented boundaries

- Deterministic task/input/prompt/configuration/repeat/batch planning and preview; reference labels remain outside execution inputs.
- An adapter protocol, one pinned OpenRouter implementation, a public catalog helper and explicit unsupported-configuration rows. No subscription or native specialist method is substituted.
- A shared SQLite ledger, verified raw artifacts, durable transport metadata, process-locked orchestration, per-provider concurrent-request limits and declaration order within configurations.
- Explicit no-retry inference, retained unknown-cost holds, safe never-sent continuation, parsed-outcome recovery after receipt publication, and visible preflight blockers.
- Operator-configurable caps for smoke and full runs, `pause` or `stop` at exhaustion, and conditional run-bound cap increases with immutable history. Increases do not clear holds or above-bound freezes.
- A private report from one locked verified snapshot with full-denominator quality, class errors/support, prompt deltas, repeat ranges/flips, record-level outcomes, route filters, requested versus observed identity, and nullable timing/token/cost measurements.

The live child permits TCP443 and DNS under an OS file boundary. The trusted HTTP adapter pins destinations and rejects redirects; the OS rule is not a domain allowlist. The coordinator has access to local files; reference isolation is enforced for the inference child, not the whole operator account. Local authorization files are operator assertions and do not authenticate a payer.

## Pending gates

The [authorized three-request smoke](LIVE_SMOKE_RESULT.md) produced one unknown transport attempt and two HTTP 200 responses after a reviewed sandbox correction. A private, ignored repository `.env` contains only the operator-authorized OpenRouter key. It is not tracked or embedded in code. Two separately archived run definitions preserve the original runtime identity and the never-sent suffix; the suffix cap subtracts the first hold from the approved $0.50 total.

Observed rounded ledger charges are $0.000139, and the unresolved original hold is $0.104963: total accounted exposure $0.105102. A corrected parser recognizes the exact `OpenAI` display name for the pinned `openai` route. Versioned offline re-evaluation still finds both outputs invalid (malformed JSON and an out-of-vocabulary label), preserving the original observations and complete missing/invalid denominators. No retries or new repeats were made.

Authentication, serving, saved raw evidence, charge settlement and private report generation have live evidence. Both initial generation lookups returned 404. Later read-only lookups returned matching response IDs, provider and charges, but a dated model identifier different from the requested alias; the strict identity check rejects that mismatch. The new metadata and timing are archived separately without changing the original reports or ledger. Browser rendering remains pending; independent operator reproduction passed as recorded in [OPERATOR_CHECK_RESULT.md](OPERATOR_CHECK_RESULT.md); [OPERATOR_CHECK.md](OPERATOR_CHECK.md) provides the concrete offline handoff. The first release is not complete. Further inference needs a new explicit request scope; no approved positions remain.

Use [RUNNER.md](RUNNER.md) for complete commands and [LIVE_SMOKE_PLAN.md](LIVE_SMOKE_PLAN.md) for the approval gate. Historical contract documents describe the checkpoint they introduced; this page records the integrated implementation's current status.
