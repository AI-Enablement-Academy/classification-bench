# Combined native CLI credit smoke proposal, 8 October 2026

The proposed action is exactly **one Claude Code invocation and one Codex
invocation for fictional product case `toy-a`**, run sequentially through the
generic workflow. The user's latest instruction authorizes using existing
account credits. That authorization does not establish an enforceable charge
bound or remove this project's USD 10 ceiling. The remaining clarification is
whether the user accepts the disclosed monetary exception for these two smoke
requests.

This document is a reviewable scope proposal. It creates no runtime
configuration, account assertion, authorization file, ledger or provider
request. The new credit-authorization guard and its offline verification must
be integrated before a final private workflow is prepared. No disabled-credit
assertion may be manufactured to pass the older guard.

## Exact smoke scope

| Control | Claude Code | Codex |
| --- | --- | --- |
| Adapter / provider capacity key | `claude_code` / `claude_subscription` | `codex` / `chatgpt_subscription` |
| Requested model | `claude-haiku-4-5-20251001` | `gpt-6.1-sol` |
| Effort | `not_applicable`; omit `--effort` | `low` |
| Exact native executable | `/Users/adamkovacs/.local/share/claude/versions/2.1.293` | `/opt/homebrew/Caskroom/codex/0.156.1/bin/codex` |
| Exact version output | `2.1.293 (Claude Code)` | `codex-cli 0.156.1` |
| Executable SHA-256 | `4e21122a227857da1178aca3299700c1fd7f2b77c93f12e73c2c76db796a105e` | `0196e89fe5a7598f816ee54232c3d7c26d75e502ab5cfe2c9240e81d90f7255a` |
| Authentication source | Existing official Claude.ai first-party Max login | Existing official ChatGPT login |
| Input membership | `toy-a` only | `toy-a` only |
| Phase / condition | `smoke`; `baseline`; repeat 1; batch size 1 | `smoke`; `baseline`; repeat 1; batch size 1 |
| Request cap | `REQ: 1` for this route | `REQ: 1` for this route |
| Local bounds | `timeout_seconds: 180`; `max_output_bytes: 65536` | `timeout_seconds: 180`; `max_output_bytes: 65536` |
| Exhaustion behavior | `pause` | `pause` |

The combined smoke has two planned invocations and two planned case positions.
Global concurrency is one; each provider limit is one. Execute Claude first,
preserve its outcome, then admit Codex only if its own prerequisites and the
combined authorization still hold. A quota failure, uncertain launch or invalid
output does not authorize a replacement request.

The managed workflow uses one shared REQ scope with total cap 2. Both v2
paid-credit guards therefore declare `request_cap: 2` for that shared scope;
each frozen configuration contains exactly one request. This is not two
requests per route. The exact workflow/phase grant and immutable membership
prevent expanding either route without a new plan and corresponding approval.

The task is `fictional-product-fit`, with fields `segment` (`teams`, `solo`) and
`urgency` (`now`, `later`). Input `toy-a` has description `A shared planning
board` and audience `Small creative studio`. Reuse the existing product
`baseline` prompt verbatim. The [retained Claude task, input and prompt
candidate](../private-data/claude-acceptance-plan-20261008/) supplies the source
material; reference labels and adjudication notes stay outside planning and
inference capsules. The final source hashes and workflow identities must be
frozen after integration rather than copied from the old false-guard packet.

The [earlier Claude candidate](CLAUDE_ACCEPTANCE_PLAN_20261008.md) supports the
exact dated Haiku 4.5 ID and unsupported effort setting. Its prior proposed
account-setting change remains historical; this combined proposal authorizes no
account change. The [Codex prerequisite investigation](CODEX_ACCEPTANCE_PREREQUISITES_20261008.md)
supports `gpt-6.1-sol` with `low` effort as a local catalog candidate. That
catalog came from client 0.160.0, whereas this proposal selects CLI 0.156.1.
Account entitlement and actual serving availability remain unverified for both
routes. A valid live response must establish the selected route's observable
model identity and task output.

No full phase is authorized. If workflow preparation requires dormant full
phase caps, those fields grant no dispatch authority and must be excluded from
the smoke authorization. There is no automatic retry, top-up, API-key fallback,
credit purchase, subscription upgrade or account-setting change in this scope.

## Current project accounting

The [OpenRouter workflow acceptance](WORKFLOW_LIVE_ACCEPTANCE_20261008.md) and
its [private verification record](../private-data/live-workflow-plan-20261008/openrouter-live-verification.json)
retain the following project figures:

| Quantity | microUSD | USD |
| --- | ---: | ---: |
| Existing project ceiling | 10,000,000 | 10.00 |
| Known recorded charges | 373 | 0.000373 |
| Active monetary reservations | 0 | 0.000000 |
| Unresolved historical holds | 559,151 | 0.559151 |
| Recorded exposure | 559,524 | 0.559524 |
| Retained allocations | 3,800,000 | 3.80 |
| Allocation headroom | 6,200,000 | 6.20 |

Preparation rechecked all seven historical USD ledger hashes against the
[retained inventory](../private-data/live-workflow-plan-20261008/inventory.json).
All matched. A SQLite read transaction using `mode=ro` and `query_only=ON`
confirmed the accepted OpenRouter smoke's 60-microUSD charge and zero active
reservation or hold. The database and existing sidecar hashes did not change.
The native executable hashes in the scope table also matched during this
preparation. These checks establish retained local evidence, not new account
billing observations.

The USD 6.20 figure already retains historical allocations and the OpenRouter
USD 0.30 workflow allocation. Do not reuse the earlier USD 6.50 figure, release
old holds, or add charges and holds to allocations that already contain them.
This proposal creates no new monetary allocation. `REQ` capacity remains
separate from USD accounting; one request is never recorded as zero-dollar
usage merely because its actual charge is unavailable. See the [aggregate
budget contract](AGGREGATE_BUDGET.md) and [subscription accounting](SUBSCRIPTION_RUNNER.md).

## Monetary limit and one clarification

Neither selected account-backed invocation has a verified hard USD or credit
bound. One `REQ` bounds admitted CLI invocations; it does not bound opaque
internal model calls, retries or output repair. Timeout and captured-output
limits bound local execution and evidence size, not provider tokens or settled
charges.

Claude's installed `--max-budget-usd` flag works in print mode and checks a
client-side cost estimate that can differ from the bill. Claude documents that
the Pro/Max session cost figure is not subscription billing. Therefore the
flag's API-equivalent estimate cannot guarantee the charge against the existing
subscription credit balance. [Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
[Claude cost accounting](https://code.claude.com/docs/en/costs)

Codex CLI 0.156.1 help exposes no per-invocation USD or credit cap. The current
official configuration reference documents experimental rollout token
accounting, without a dollar-charge guarantee. OpenAI documents that included
usage is consumed first, then existing credits; an in-progress task can settle
with a negative balance after concurrent depletion. Disabled auto-reload limits
new automatic purchases, not consumption of existing credits. [Codex configuration
reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[OpenAI credit management](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans)

Claude and OpenAI document account usage dashboards. Those records can support
later reconciliation, but the inspected documentation establishes no
authoritative settlement receipt tied to one native CLI invocation. Concurrent
sessions and shared account features prevent attributing a balance delta to
this smoke alone. CLI estimates and token counts must remain distinct from
authoritative charges. [Claude credit management](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans),
[OpenAI credit management](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans)

The only unresolved authorization question is:

> Does your approval include exactly one Claude smoke and one Codex smoke,
> with one invocation each and no retry or top-up, acknowledging that their
> unknown credit charges cannot be guaranteed to fit within this project's
> remaining USD 10 allowance?

Credit use itself is already approved. A reply accepting this exception would
apply only to these two invocations, and would not increase the general project
allowance or authorize further account changes or inference. Without that
clarification or a verified enforceable provider charge bound, retain the
monetary gate and do not dispatch.

## Preparation and acceptance boundary

After the credit guard and offline checks pass, prepare a new private source
set, deterministic preview and exact workflow/phase/request identities for
review. Retain the old Claude packet unchanged. Bind truthful, fresh account
evidence and the latest credit approval plus any accepted monetary exception to
the final run-specific authorization. A prior observation, source string or
timestamp cannot prove a current account setting or entitlement.

Read-only preflight must verify the frozen native binary/version/help,
official account authentication and enforced capsule/reference isolation.
Retain Claude's recorded organization/billing-context match with its explicit
unverified member/email limitation. Recheck Codex's applicable account context
without publishing identifiers or copying credentials. [Readiness audit](SUBSCRIPTION_READINESS_20261008.md),
[runtime contract](ADAPTER_RUNTIME.md), [assertion contract](SUBSCRIPTION_ASSERTIONS.md)

Each dispatched invocation must preserve raw output and an execution receipt
before parsing. Preserve failed, invalid, refused, uncertain and never-sent
positions in the full planned denominator. Recovery may inspect saved evidence
but must not automatically redispatch an uncertain request. Record observable
model identity, effort, CLI version, token counts, timing and charge provenance;
unavailable charges stay unknown. Neither success on one fictional case nor
offline tests establish benchmark quality, repeatability or full release
acceptance.

This preparation performed no inference, browser action, credential read/copy,
account change, runtime configuration write or authorization write. Live
acceptance remains pending.
