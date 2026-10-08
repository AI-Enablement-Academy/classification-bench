# Subscription execution and request budgets

Claude Code and Codex use the same matrix scheduler with an account-backed runtime. The adapters are implemented and covered by offline matrix, parser and isolation tests; live model acceptance remains pending. See the [active goal](NEXT_TASK_GOAL.md) and [parity matrix](FEATURE_PARITY.md).

## Request capacity is separate from dollar billing

Subscription scopes use `currency: "REQ"`, `scale: 1` and an integer `cap` counting admitted CLI requests. A batch of several input records consumes one request because it is one CLI invocation. The cap does not bound opaque internal model calls, retries or structured-output repair inside the CLI; record that workflow limitation when comparing routes. Separate repeats consume separate requests. The runtime reserves one unit before dispatch and settles one unit after an attributable response receipt is saved, including an invalid answer. This is dispatch capacity, not a dollar charge or proof of consumed provider tokens.

An ambiguous dispatch retains one unit. Recovery may inspect saved receipts but never automatically starts a replacement invocation. The existing pause/stop policy applies when request capacity is exhausted. Raising a cap uses the same run-bound, audited amendment mechanism as other scopes.

A subscription run still needs an explicit run-bound authorization file. Authentication, extra-usage settings and CLI isolation must pass preflight before admission. The request cap does not enforce a provider's token quota or establish its billing configuration.

Observed dollar cost remains unavailable when the CLI supplies no authoritative charge. Reports expose `consumed_requests` and `unresolved_request_hold` separately from dollar cost fields. A request reservation must never appear as microUSD. No API-key fallback, paid overage or credit redemption is implied.

Each scope retains one accounting unit. The [workflow scheduler](WORKFLOW.md) now coordinates dollar-backed, request-backed and synthetic groups in one experiment, with separate scopes and caps for USD, REQ and SYN and shared global/provider concurrency. It never combines incompatible units or interprets request capacity as dollar cost. Mixed-unit orchestration does not establish live account readiness.

## Offline verification

`python3 -m unittest tests.test_request_accounting -v` checks capacity exhaustion, unknown-dispatch holds, receipt recovery without redispatch, and rejection of incompatible monetary/request units. The fixtures make no provider calls and establish no live subscription availability.

Sources: [scheduler](../classification_bench/benchmark.py), [runtime contract](ADAPTER_RUNTIME.md), [atomic execution](EXECUTION_API.md), [accounting tests](../tests/test_request_accounting.py).

## Configure and check an account-backed route

Use `settings.adapter` equal to `claude_code` or `codex`. Declare the exact model ID, absolute native Mach-O CLI executable, exact `--version` output, and explicit effort. The configuration also requires `extra_usage_disabled: true`, a UTC `extra_usage_verified_at` timestamp ending in `Z`, and an `extra_usage_source` describing the actual operator check. Never invent that check. Optional timeout and output-size bounds are validated by the adapter. The provider concurrency keys are `claude_subscription` and `chatgpt_subscription`.

The declaration is an operator assertion, not an authoritative provider billing query. It must be no more than 24 hours old at preflight, admission and dispatch. [Audited same-run renewal](SUBSCRIPTION_ASSERTIONS.md) now appends an immutable run/configuration-bound assertion revision and private evidence without changing the frozen configuration, plan, request identity or provider capsule. `account-check-renew` verifies the separate authorization and evidence; it performs no dispatch and does not clear safety blocks or unknown holds. A budget increase does not renew authentication/billing assertions.

`python3 -m classification_bench preflight --config /private/run/config.json` checks runtime prerequisites without reserving capacity, creating a run database or dispatching inference. It does not require an already-written run-bound grant, although the configuration must declare its intended authorization-file path. Successful preflight does not establish model availability or authorize execution. `preview`, `run`, `status`, `recover`, `export` and `report` use the existing command shape.

Read-only checks on 8 October verified installed Codex 0.156.1 with ChatGPT authentication and Claude Code 2.1.293 with Claude.ai authentication. The checks verified version/help controls and the real OS reference/symlink/environment probe. They used synthetic guard declarations solely for read-only testing; they did not establish that paid extra usage is disabled or send a model request.

The [8 October readiness audit](SUBSCRIPTION_READINESS_20261008.md) rechecked native version/help/login status and distinguishes that support from the unresolved account prerequisites. A later operator check matched Claude's organization/billing context to the native CLI, with member/email identity unverified, and confirmed usage credits remain enabled. Codex credit fallback remains unverified despite auto-reload being off. Do not manufacture an affirmative billing guard from those observations.

The worker currently requires macOS and a native CLI executable. Script wrappers and unsupported hosts fail closed. Official authentication requires access to existing account material. Claude may require the exact login keychain file and the official security helper; Codex may read its configuration during the separate login-status probe, but that configuration is denied during inference. Built-in CLI context and the known official Claude built-ins are disclosed. This is not per-keychain-record isolation or removal of every built-in instruction. Credentials are not copied into the experiment.

## Persistent admission blocks

Observed paid overage, quota exhaustion, model-identity mismatch or CLI tool/context isolation violations block further admission for the run's scope. The first reason and evidence hash are recorded immutably. The ledger checks the guard inside the same transaction as capacity reservation, so concurrent workers cannot bypass a committed block. Already-admitted work may finish and preserve its evidence. Status reports `blocked_safety`; restart, recovery and cap increases do not clear it.

No automatic guard removal is implemented. After investigating and resolving the prerequisite, prepare separately authorized never-sent work; do not replay completed or ambiguous attempts. A future reviewed guard-release workflow must preserve the original record.
