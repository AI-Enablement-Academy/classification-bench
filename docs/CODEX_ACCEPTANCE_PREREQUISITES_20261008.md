# Codex acceptance prerequisites: 8 October 2026

## Credit authorization update, 8 October 2026

The user has explicitly approved consumption of existing Claude and Codex
credits. This supersedes the credit-exclusion prerequisite below: enabled or
unknown credit state is no longer itself a blocker once the approval applies
through an honest, run-bound version 2 assertion and exact dispatch grant.
Preserve the historical account observations and uncertainty; do not declare
credits disabled without evidence. See [the assertion contract](SUBSCRIPTION_ASSERTIONS.md).

Live execution remains pending on one unanswered question: whether exactly one
Claude invocation and one Codex invocation, with no retry or top-up, are
acceptable despite no verified hard USD cap. The project USD 10 ceiling remains
unchanged. No account change, top-up or live run follows from this note. The
[combined CLI credit smoke plan](CLI_CREDIT_SMOKE_PLAN_20261008.md) records the
scope, monetary limit and remaining authorization question. Model entitlement
and actual serving remain unverified.

**Live Codex acceptance remains blocked by billing evidence.** The workspace spend-limit alternative examined here does not establish that the selected native CLI invocation cannot consume existing paid credits. The local model catalog supplies an explicit smoke candidate, `gpt-6.1-sol` with `low` effort, but does not prove that CLI 0.156.1 can serve it.

This was a bounded read-only investigation at repository commit `8ed870e`. It inspected local configuration source, the existing command builder, selected noncredential model-catalog fields and official OpenAI documentation. The local source was version 0.153.4, so it is not runtime proof for the selected CLI 0.156.1. It did not repeat the earlier CLI help/login-status checks, run inference, change account settings, inspect credential files, or create an account assertion. The earlier [subscription readiness audit](SUBSCRIPTION_READINESS_20261008.md) retains the native executable/version evidence and the observed billing prerequisites.

## One alternative examined: workspace spend limits

Business workspaces can apply monthly limits to additional eligible credit usage after included seat usage; individual overrides take precedence over seat limits. The documentation does not establish a zero-credit limit with a hard per-invocation guarantee for the current account. No applicable Business workspace, role or effective limit was verified in this investigation. [OpenAI: Business credits and spend controls](https://help.openai.com/en/articles/20001155-managing-credits-and-spend-controls-in-chatgpt-business)

Enterprise/Edu credit-based workspaces have a documented zero **overage** limit. It blocks new requests that use credits after the shared pool is exhausted. It does not prevent consuming the remaining pool, and work already in progress can settle beyond the limit. Per-user limits can also be exceeded by a task that began below its limit. Token-based workspaces have a different control: a $0 workspace budget blocks spend for affected metered usage. These are workspace controls, not a documented switch attached to one CLI invocation. [OpenAI: Enterprise/Edu limits and overages](https://help.openai.com/en/articles/20001001-manage-usage-limits-and-overages-in-chatgpt-enterprise-and-edu)

OpenAI's Codex guide explicitly limits these controls to eligible activity under the workspace's agreement. They do not cover every kind of Codex usage or API Platform billing. Therefore the token-based $0 contract cannot be applied to this account or the chosen CLI route without evidence of the actual billing model and coverage. [OpenAI: Codex workspace usage controls](https://learn.chatgpt.com/docs/enterprise/usage-limits)

The documented `forced_chatgpt_workspace_id` setting restricts ChatGPT authentication to a workspace; it does not select a billing policy. The current [subscription command builder](../classification_bench/subscription_adapters.py) forces ChatGPT authentication but does not supply that workspace restriction. A future workspace-specific admission contract would need to bind the applicable workspace, verify support on its selected native executable and freeze the effective control. No workspace ID or such contract was created here. [OpenAI: configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## Explicit model candidate and evidence boundary

The local catalog `/Users/adamkovacs/.codex/models_cache.json` supplied this selected-field observation:

```json
{
  "client_version": "0.160.0",
  "fetched_at": "2026-10-08T03:44:20.076821Z",
  "model": {
    "default_reasoning_level": "low",
    "slug": "gpt-6.1-sol",
    "supported_reasoning_efforts": [
      "low", "medium", "high", "xhigh", "max", "ultra"
    ],
    "visibility": "list"
  }
}
```

The SHA-256 of those exact parsed fields, serialized as UTF-8 JSON with sorted keys and compact separators, is `208c97d2a7b8d383be493bde9218156d234553c1e2477de78105159af9fc7a78`. Account identity fields and the whole-file hash were not retained. The catalog can refresh independently; this is a captured local advertisement, not independently authenticated remote availability evidence.

Proposed minimal smoke controls are `model="gpt-6.1-sol"` and `effort="low"`. The catalog came from client 0.160.0, while the selected native executable is `/opt/homebrew/Caskroom/codex/0.156.1/bin/codex`. Neither cache visibility nor a syntactically valid model request establishes serving availability on that executable/account. `low` is already accepted by the subscription adapter; it supplies no token, money or credit bound. The catalog's other levels do not expand the adapter's accepted control set.

## Actionable prerequisite

Obtain a provider-backed answer for the actual CLI account and route: whether an existing applicable workspace control can exclude **all paid-credit consumption for the proposed invocation**, including any fallback after included usage. The answer must distinguish consuming an existing credit pool from buying credits or accruing overage, and explain when the control is enforced. Preserve only dated minimum policy evidence and private account/workspace matching evidence.

If a qualifying control is already configured, verify its effective scope without changing it. If a policy change is required, the operator must first authorize that exact account/workspace change. A provider confirmation, account-policy change or model request was not performed by this audit. Until the billing prerequisite is actually established, retain the blocked gate and do not set `extra_usage_disabled` to `true`. Then, and only then, freeze the native executable/model/effort and a genuine run-bound assertion in the separately authorized one-case smoke plan. [Assertion contract](SUBSCRIPTION_ASSERTIONS.md), [live workflow plan](LIVE_WORKFLOW_PLAN_20261008.md)

No new confirmed code defect was identified in this bounded investigation. This is an unresolved external acceptance prerequisite; request caps and existing isolation controls do not establish the missing billing guarantee.
