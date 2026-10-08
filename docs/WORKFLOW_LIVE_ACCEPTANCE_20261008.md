# OpenRouter workflow smoke, 8 October 2026

The current managed workflow completed one authorized OpenRouter request: one
fictional product case, one valid output and **60 microUSD ($0.000060)** in
recorded charges. Recovery dispatched nothing and retained exactly one attempt.
This accepts the named route and workflow integration, not model quality,
repeatability, other models or the Claude Code/Codex routes.

The provider's raw cost was USD 0.0000593; the integer ledger rounds it up to
60 microUSD. Independent read-only review returned **APPROVE**, with no
confirmed BLOCKING or RESIDUAL money, privacy or replay finding in this scope.
It verified the exact grants, authoritative database binding, raw artifacts,
single dispatch, settlement, recovery counts and unchanged historical ledgers.

## Scope and authority

The [reviewed plan](LIVE_WORKFLOW_PLAN_20261008.md) reconciles all saved project
ledgers against the user's existing USD 10 authorization. The root operator
bound that authorization to a new USD 0.30 aggregate allocation and this exact
USD 0.15 smoke phase. Historical allocations remain USD 3.50, so retained
allocations total USD 3.80. The full phase was prepared but not authorized or
dispatched in this acceptance action. No funds, credentials or authority came
from the separate reference project.

| Frozen control | Value |
| --- | --- |
| Workflow format | Schema 2, including frozen evaluator provenance |
| Workflow SHA-256 | `a7b6277fbd2269a0bd85c7273cb7a1c4fbfedef586445b4c6e897a5645c1d9e9` |
| Smoke run SHA-256 | `d2037072a872107749294cb994b899e6e0009c49d77bdb89ffa42aa1fdf735c7` |
| Model / endpoint | `openai/gpt-4.1-nano` / `openai` |
| Canonical model | `openai/gpt-4.1-nano-2025-04-14` |
| Inputs | Fictional product `toy-a`, baseline prompt, repeat 1, batch size 1 |
| Controls | Temperature 0; maximum 512 output tokens; total/provider concurrency 1 |
| Request bound / phase cap | 104,963 / 150,000 microUSD; pause at exhaustion |
| Authentication | Existing ignored private project `.env`; no credential copied |

Private evidence is under
[`private-data/live-workflow-plan-20261008/`](../private-data/live-workflow-plan-20261008/).
`openrouter-approved-spec.json`, `openrouter-accepted/workflow.json`,
`approved-openrouter-smoke.json` and
`openrouter-smoke-authorization-provenance.json` preserve the exact scope and
authorization source. The earlier unapproved proposal is retained separately.

The account check matched the full hash of the local key to its workspace's key
row. Web-search override prevention was off; response healing and its override
prevention were off. The private policy record retains only the match result,
settings and observation time. The bound remains conditional on OpenRouter
honoring those controls. No account settings changed.

## Execution and evidence

An initial read-only preflight omitted the credential argument and correctly
returned not ready before admission. Preflight with the existing project key
then passed current endpoint, identity and account-policy checks. Both records
are preserved. The workflow dispatched once; there was no automatic retry.

The output was `segment: teams`, `urgency: now`. The receipt reported 241 input
tokens and 88 output tokens. Client request duration was 1.544 seconds; this is
not pure inference time. All five stored evidence objects passed SHA-256 and
private-permission checks. `openrouter-live-verification.json` records the
checks and exact recovery attempt counts. The smoke ledger has no active
reservation or unresolved hold; an absent hold value in exported operation
telemetry is not itself the ledger proof of zero.

The immediate generation-metadata lookup returned HTTP 404. That immutable
response and the operation's `unverified:AdapterError` identity status remain
unchanged. One later **read-only metadata lookup**, with no inference, returned
HTTP 200 and matched the saved generation to OpenAI and the frozen canonical
model. It also reported the same rounded 60-microUSD charge and 971 milliseconds
of provider generation time. The separate recheck response hash is
`6e41debea70fec04fefcd3b1a9aa3f95091fec6edbe19ab0acd40f9b250e76e1`.
This supplemental verification does not silently replace original operation
telemetry; reports using that telemetry still show its original unavailable
provider timing and unverified identity status.

Project recorded charges are now 373 microUSD. Prior unresolved holds remain
559,151 microUSD, so recorded exposure is 559,524 microUSD. Those older holds
were neither released nor retried. Retained allocation headroom is USD 6.20;
it is distinct from exposure-based arithmetic and does not authorize account
upgrades or payment changes.

## Remaining acceptance

Claude Code and Codex still require truthful paid-fallback prerequisites before
their live smoke. The matched Claude billing organization currently has usage
credits enabled; Codex's disabled auto-reload does not exclude existing-credit
fallback. See [subscription readiness](SUBSCRIPTION_READINESS_20261008.md).

Offline tests and this live response do not accept visual quality. Exact final
report files still need the permitted checks in [REPORT_UX_CHECK.md](REPORT_UX_CHECK.md).
Other native providers retain their separate statuses. The repository stays
private through completion and the public-release audit.
