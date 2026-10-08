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

Use `settings.adapter` equal to `claude_code` or `codex`. Declare the exact model ID, absolute native Mach-O CLI executable, exact `--version` output, and explicit effort. Legacy settings require `extra_usage_disabled: true`, a UTC `extra_usage_verified_at` timestamp ending in `Z`, and an `extra_usage_source` describing the actual operator check. Never invent that check. Version 2 account assertions support explicit paid-credit permission as described below. Optional timeout and output-size bounds are validated by the adapter. The provider concurrency keys are `claude_subscription` and `chatgpt_subscription`.

New live work in the `claude-haiku-...` namespace has the following explicit capability checks, verified against official documentation on 8 October 2026:

| Exact model ID | Accepted effort | CLI requirement |
| --- | --- | --- |
| `claude-haiku-4-5` | `not_applicable` | Existing exact-version and required-control preflight |
| `claude-haiku-4-5-20251001` | `not_applicable` | Existing exact-version and required-control preflight |
| `claude-haiku-5-5` | `low`, `medium`, `high`, `xhigh`, `max` | Claude Code 2.1.293 or later; native version output such as `2.1.293 (Claude Code)` |

Haiku 4.5 does not support effort, so its command omits `--effort`. New Haiku 5.5 work requires an explicit supported level and emits that flag. Its `not_applicable` setting, insufficient or unparseable native version, and unrecognized `claude-haiku-...` IDs are rejected before the preflight worker, isolation probe or admission. Dispatch repeats the same checks before invoking a worker. The minimum-version check uses the frozen declaration; successful preflight still verifies the actual executable's identical version output and required flags. Validation for other model families remains unchanged. [Haiku 4.5 model specification](https://platform.claude.com/docs/en/models/haiku-4-5/overview), [Claude Code model and effort controls](https://code.claude.com/docs/en/model-config)

Historically accepted configurations remain constructible, and their frozen requests and saved receipts remain reproducible and readable through status, export, report and recovery. This includes older Haiku 5.5/`not_applicable` and unverified Haiku/`not_applicable` records. Construction or offline preparation is not current live capability approval: those combinations cannot pass the new live preflight or dispatch gate. No new capability annotation is inserted into a historical request body.

These checks establish a documented request configuration, not account entitlement, serving availability or observed applied effort. Provider or managed settings can limit the applied level; the evidence continues to label the frozen level `requested_effort`. A supported model/effort never replaces the actual billing assertion or live dispatch authorization. [Claude Code effort limits](https://code.claude.com/docs/en/model-config#organization-effort-limits)

The declaration is an operator assertion, not an authoritative provider billing query. It must be no more than 24 hours old at preflight, admission and dispatch. [Audited same-run renewal](SUBSCRIPTION_ASSERTIONS.md) now appends an immutable run/configuration-bound assertion revision and private evidence without changing the frozen configuration, plan, request identity or provider capsule. `account-check-renew` verifies the separate authorization and evidence; it performs no dispatch and does not clear safety blocks or unknown holds. A budget increase does not renew authentication/billing assertions.

`python3 -m classification_bench preflight --config /private/run/config.json` checks runtime prerequisites without reserving capacity, creating a run database or dispatching inference. It does not require an already-written run-bound grant, although the configuration must declare its intended authorization-file path. Successful preflight does not establish model availability or authorize execution. `preview`, `run`, `status`, `recover`, `export` and `report` use the existing command shape.

Read-only checks on 8 October verified installed Codex 0.156.1 with ChatGPT authentication and Claude Code 2.1.293 with Claude.ai authentication. The checks verified version/help controls and the real OS reference/symlink/environment probe. They used synthetic guard declarations solely for read-only testing; they did not establish that paid extra usage is disabled or send a model request.

The [8 October readiness audit](SUBSCRIPTION_READINESS_20261008.md) rechecked native version/help/login status and distinguishes that support from the unresolved account prerequisites. A later operator check matched Claude's organization/billing context to the native CLI, with member/email identity unverified, and confirmed usage credits remain enabled. Codex credit fallback remains unverified despite auto-reload being off. Do not manufacture an affirmative billing guard from those observations.

The worker currently requires macOS and a native CLI executable. Script wrappers and unsupported hosts fail closed. Official authentication requires access to existing account material. Claude may require the exact login keychain file and the official security helper; Codex may read its configuration during the separate login-status probe, but that configuration is denied during inference. Built-in CLI context and the known official Claude built-ins are disclosed. This is not per-keychain-record isolation or removal of every built-in instruction. Credentials are not copied into the experiment.

## Persistent admission blocks

Observed paid overage without an explicit admitted paid-credit approval, quota exhaustion, model-identity mismatch, CLI tool/context isolation violations or a mismatched version 2 receipt policy block further admission for the run's scope. Approved overage remains telemetry and does not by itself invalidate an otherwise valid response or create a block. The first blocking reason and evidence hash are recorded immutably. The ledger checks the guard inside the same transaction as capacity reservation, so concurrent workers cannot bypass a committed block. Already-admitted work may finish and preserve its evidence. Status reports `blocked_safety`; restart, recovery and cap increases do not clear it.

No automatic guard removal is implemented. After investigating and resolving the prerequisite, prepare separately authorized never-sent work; do not replay completed or ambiguous attempts. A future reviewed guard-release workflow must preserve the original record.

## Explicit paid-credit policy

The default remains deny. Enabled paid usage or an unknown setting does not authorize spending. A version 2 assertion separates the observed account state from explicit permission to use existing account credits. It does not enable overage, redeem or purchase credits, change an account, use API authentication, fall back to a billing API or top up a balance. [Implementation](../classification_bench/subscription_adapters.py)

For new work, replace the three legacy `extra_usage_*` setting fields with one `settings.account_assertion` object using these exact fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `2` |
| `extra_usage_disabled` | Boolean `true` when actually disabled, `false` when actually enabled, or `null` when unknown |
| `verified_at`, `source` | The actual dated operator observation and its provenance; freshness remains 24 hours |
| `paid_credit_authorization` | `null` for deny, or the explicit approval object below |
| `account_check_sha256` | Lowercase SHA-256 of the exact private account-observation/approval evidence bytes |
| `account_check_file` | Absolute path to that nonempty, mode-0600 evidence file, at most 1,000,000 bytes |

The approval object requires exactly `approved: true`, a positive integer `request_cap`, an actual UTC `approved_at` timestamp and a nonempty `source` identifying the explicit human permission. No defaults provide permission. Permission has no invented 24-hour expiration: it persists for its unchanged run/configuration/scope/cap. The account observation remains subject to 24-hour freshness. An approval in the future is rejected.

`request_cap` covers the whole shared REQ scope. It is not a separate request allowance for every configuration. A combined scope with one frozen Claude request and one frozen Codex request uses a total scope cap of 2; each approval binds the same scope cap and its exact configuration's one-request membership through the immutable run, configuration and plan. Another repeat or changed membership changes the run and requires a matching dispatch grant. Raising the ledger's shared cap beyond the paid approval refuses admission until a newer explicit paid approval covers it. [Admission ledger](../classification_bench/subscription_assertions.py), [mixed-route regression](../tests/test_subscription_runtime.py)

The existing exact run-bound dispatch authorization remains required. Initial binding copies the checked evidence into the private content-addressed store, so restart verifies the retained copy rather than requiring the original source file forever. Pure preflight can inspect the configured evidence without creating a database; it is not dispatch authorization. Paid dispatch uses a bound ledger revision, and parsing/recovery compare the receipt policy to the exact immutable admission revision. A later approval cannot authorize an earlier unapproved receipt. A later policy change does not alter an earlier approved result. [Renewal and policy revisions](SUBSCRIPTION_ASSERTIONS.md)

The ledger settles one REQ per attributable response and retains one REQ for an ambiguous dispatch. Actual subscription USD remains unknown when no authoritative charge is exposed; API-equivalent CLI cost is not an invoice. This opt-in does not enforce or claim the project's USD 10 aggregate ceiling. Paid native execution within that ceiling still needs an enforceable monetary bound or a separately explicit scope exception before dispatch. [Active spending boundary](NEXT_TASK_GOAL.md), [accounting tests](../tests/test_request_accounting.py)
