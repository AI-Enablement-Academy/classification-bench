# Proposed native provider acceptance scopes

This plan prepares separate acceptance scopes for the [native adapters](NATIVE_DECISIONS.md). It grants no spending or credential access. No native request has been sent. The core release does not depend on completion of these provider-specific scopes.

| Scope | Native model | Requests | Proposed total cap | Exhaustion policy | Remaining prerequisites |
| --- | --- | --- | --- | --- | --- |
| Liquid product smoke | `d1:free` | 3 | USD 0.25 | pause | Reviewed free entitlement and source snapshot; authorized Liquid key |
| Solar product smoke | `solar-decide` | 3 | USD 0.25 | pause | Reviewed free entitlement and source snapshot; authorized Upstage key. Direct metered admission is blocked. |
| Qwen product smoke | `decision-model-preview` | 3 | USD 0.25 | pause | Reviewed regional/account billing snapshot; workspace ID and region; authorized DashScope key |
| Cloudflare product smoke | `clef` | 3 | USD 0.25 | pause | Actual account ID, reviewed published-price snapshot and account billing; separately authorized Clef token |
| Cloudflare Flash product smoke | `clef-flash` | 3 | USD 0.25 | pause | Actual account ID, reviewed published-price snapshot and account billing; separately authorized Clef token |

These are proposed independent caps, not an approved pooled budget. Each provider/model needs its own reviewed preview and run-bound approval. Previous OpenRouter approvals are completed and cannot fund these calls. Liquid metered admission is also blocked. [Provider contract sources and limits](DECISION_PROVIDER_CONTRACTS.md) and [Clef operation](CLEF_DECISIONS.md) explain the billing boundaries. Both smoke and full caps are operator settings; USD 0.25 is a proposal, not a hardwired requirement.

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

1. Establish actual route/account billing evidence. Retain the source bytes and create the reviewed snapshot described in [native operation](NATIVE_DECISIONS.md). Do not manufacture a free entitlement from a model name or page hash.
2. Run `python3 -m scripts.prepare_decision_run` with the selected adapter, `--task product --mode smoke --budget-usd 0.25 --on-budget-exhausted pause`, the reviewed billing snapshot and a fresh private directory. Qwen additionally needs its actual workspace ID and region; Clef needs its actual `--account-id`. This step performs no inference and creates no authorization. An offline placeholder account preview is a software check and must be replaced with an actual-account preview before authorization.
3. Inspect the resulting preview: exactly three requests, declared route/model, frozen task and prompt, per-request bounds and their total, and no unexplained blockers. If the proposed cap cannot cover the conservative bounds, revise the proposal before approval. Never silently raise it.
4. Present that exact preview, provider, task, three-attempt scope, total cap and credential source for explicit authorization. No authorization is currently requested because the provider-specific prerequisites above remain unresolved.

## Acceptance after a separately authorized run

Preserve each raw response and receipt, exact request binding, returned model, native answers, probabilities, confidence, usage and client duration. Record absent provider identity or billing evidence as unavailable. A valid categorical response does not establish independent routing identity or a zero charge.

Generate the private report from the verified snapshot and separate full-denominator reference agreement from schema validity. Three fictional cases test integration; they do not establish model quality or repeatability. Inspect every invalid, missing or uncertain outcome without retrying it.

Inspect local status, run explicit recovery and verify that a completed restart adds no dispatch. Recovery may reconcile saved receipts and ledger state; it performs no inference. Retain unresolved costs as holds. Record each provider's acceptance result and remaining limitations separately. A failed or uncertain scope is evidence to investigate, not permission for a replacement call.
