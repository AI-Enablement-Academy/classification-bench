# Proposed native provider acceptance scopes

This plan prepares separate acceptance scopes for the [native adapters](NATIVE_DECISIONS.md). The proposal itself grants no spending or credential access. The user subsequently authorized smoke tests and runs up to USD 10 total in this project; the exact Clef/Flash smoke and full scopes are now [completed](CLEF_LIVE_ACCEPTANCE_20261002.md). Other provider prerequisites remain below. The core release does not depend on completion of these provider-specific scopes.

| Scope | Native model | Requests | Scope cap | Exhaustion policy | Status / remaining prerequisites |
| --- | --- | --- | --- | --- | --- |
| Liquid product smoke | `d1:free` | 3 | USD 0.25 | pause | Reviewed free entitlement and source snapshot; authorized Liquid key |
| Solar product smoke | `solar-decide` | 3 | USD 0.25 | pause | Reviewed free entitlement and source snapshot; authorized Upstage key. Direct metered admission is blocked. |
| Qwen product smoke | `decision-model-preview` | 3 | USD 0.25 | pause | Reviewed regional/account billing snapshot; workspace ID and region; authorized DashScope key |
| Cloudflare product smoke | `clef` | 3 | USD 0.25 | pause | Completed with valid responses; exact USD charges unavailable |
| Cloudflare Flash product smoke | `clef-flash` | 3 | USD 0.25 | pause | Completed with valid responses; exact USD charges unavailable |

Liquid/Solar/Qwen caps remain proposals. The completed Cloudflare scopes had separate run-bound grants: USD 0.25 per smoke and USD 1.00 per full run, totaling USD 2.50 within the user's USD 10 aggregate allowance. Each additional provider/model needs a reviewed preview, suitable credentials and a run-bound allocation within that aggregate budget. Previous OpenRouter approvals are completed and cannot fund these calls. Liquid metered admission is also blocked. [Provider contract sources and limits](DECISION_PROVIDER_CONTRACTS.md) and [Clef operation](CLEF_DECISIONS.md) explain the billing boundaries. Both smoke and full caps remain operator settings.

The [Cloudflare account setup check](CLOUDFLARE_ACCOUNT_SETUP.md) resolved the actual account ID, catalog/schema access and local credential setup. The account-restricted project token is active and expires 2026-11-01 13:03:47 UTC. Subscription reads list no Workers Paid plan. Fresh actual-account smoke/full previews and reviewed public-price snapshots are in `private-data/clef-account-preparation-20261002/`; the previews themselves create no authorization. Later grants and completed results are preserved separately. Fresh app analytics reports 42 requests and approximately 252.818182 neurons with no quota failures; this does not establish exact dollar charges or a future remaining allowance.

## Fixed fictional task

Use `examples/product/task.json` and `examples/product/inputs.json`, record order `toy-a`, `toy-b`, `toy-c`. Select only the existing `baseline` prompt, one repeat and batch size one. Each HTTP request contains one record and two typed choice questions: `segment` and `urgency`. The scope is three HTTP inference attempts and six field decisions per provider. No retries, fallback, repair calls or additional prompt conditions are included.

The following SHA-256 values bind actual file bytes, except the prompt digest, which binds its exact UTF-8 string:

| Input | SHA-256 |
| --- | --- |
| `examples/product/task.json` | `b478463d954d3a0ee2433257769c5cd66adbdc8acf8575f561fe085c6d945f03` |
| `examples/product/inputs.json` | `1af415b441c3421a3eb84c1fba272edec74bfaac7e5c0802528b83cb1d28296d` |
| `baseline` prompt text | `722bf0d3ebed4fa71739315426d19d2280a8827342cfe4f2a996ed32b574f975` |

Reference labels are read only during offline evaluation, where their digest is recorded as evaluation provenance. They must not enter execution planning, the run configuration, execution manifest, request body or inference capsule.

## Before requesting execution approval

Apply this checklist to a new proposal. The completed Cloudflare scopes already have grants and preserved results; do not repeat their approval or dispatch.

1. Establish actual route/account billing evidence. Retain the source bytes and create the reviewed snapshot described in [native operation](NATIVE_DECISIONS.md). Do not manufacture a free entitlement from a model name or page hash.
2. Run `python3 -m scripts.prepare_decision_run` with the selected adapter, `--task product --mode smoke --budget-usd 0.25 --on-budget-exhausted pause`, the reviewed billing snapshot and a fresh private directory. Qwen additionally needs its actual workspace ID and region; Clef needs its actual `--account-id`. This step performs no inference and creates no authorization. An offline placeholder account preview is a software check and must be replaced with an actual-account preview before authorization.
3. Inspect the resulting preview: exactly three requests, declared route/model, frozen task and prompt, per-request bounds and their total, and no unexplained blockers. If the proposed cap cannot cover the conservative bounds, revise the proposal before approval. Never silently raise it.
4. Bind any new scope to the user's remaining aggregate allowance and the exact preview, provider, task, attempt count, cap and credential source. The other provider-specific prerequisites above remain unresolved; a budget approval does not create missing credentials or establish account billing.

## Acceptance after a separately authorized run

Preserve each raw response and receipt, exact request binding, returned model, native answers, probabilities, confidence, usage and client duration. Record absent provider identity or billing evidence as unavailable. A valid categorical response does not establish independent routing identity or a zero charge.

Generate the private report from the verified snapshot and separate full-denominator reference agreement from schema validity. Three fictional cases test integration; they do not establish model quality or repeatability. Inspect every invalid, missing or uncertain outcome without retrying it.

Inspect local status, run explicit recovery and verify that a completed restart adds no dispatch. Recovery may reconcile saved receipts and ledger state; it performs no inference. Retain unresolved costs as holds. Record each provider's acceptance result and remaining limitations separately. A failed or uncertain scope is evidence to investigate, not permission for a replacement call.
