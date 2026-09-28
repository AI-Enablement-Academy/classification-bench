# Proposed first live smoke

Status: prepared, not authorized or dispatched. The adapter and runner have offline tests. No successful live authentication, serving, route observation or billing has been demonstrated. The candidate-experience source study and its budgets remain separate.

## Concrete proposal

Use the three fictional records in [the candidate fixture](../examples/candidate/inputs.json), its baseline rubric, one repeat and batch size one. Route `openai/gpt-4.1-nano` through the exact OpenRouter `openai` endpoint, temperature zero, at most 512 output tokens. Disable fallback, response repair, cache use and automatic inference retry. Provider concurrency and run concurrency are both one.

This produces exactly **three inference requests**. It also performs unauthenticated public catalog checks and up to one read-only generation-metadata lookup per saved completion. Those lookups are not repeats. The purpose is to verify request/response attribution, strict parsing, identity observations, usage, settlement, restart behavior and report generation. Three records do not establish model quality or repeat stability.

A public [endpoint catalog](https://openrouter.ai/api/v1/models/openai/gpt-4.1-nano/endpoints) read on 2026-09-28 reported a 1,047,576-token context ceiling, $0.0000001 per input token and $0.0000004 per output token for the `openai` endpoint. The conservative bound is rounded upward to microUSD:

`ceil((1,047,576 × 0.0000001 + 512 × 0.0000004) × 1,000,000) = 104,963 microUSD/request`.

All three bounds sum to **$0.314889**. A proposed configurable cap of **$0.50**, with `on_budget_exhausted: pause`, covers that bound. This is a suggested setting for review, not permission to spend or a hard-coded product budget. The operator can choose another cap and either `pause` or `stop`, for smoke and full runs independently. Actual short-input usage should be smaller, but no expected cost replaces the conservative reservation.

The adapter accepts the catalog's optional web-search price only for this inspected tool-free GPT-4.1 Nano/OpenAI route. Search-native routes with nonzero unbounded search charges are rejected. Discounted cached-input prices cannot exceed the regular input bound. See [adapter pricing and route boundaries](OPENROUTER.md).

## Reproduce the proposal

The catalog command reads public metadata, uses no key and makes no inference call:

```sh
python3 -m classification_bench catalog --model openai/gpt-4.1-nano --provider openai --out /tmp/openrouter-endpoint.json
python3 -m scripts.prepare_run --snapshot /tmp/openrouter-endpoint.json --directory /tmp/proposed-smoke --mode smoke --task candidate --budget-usd 0.50 --on-budget-exhausted pause
python3 -m classification_bench preview --config /tmp/proposed-smoke/config.json
```

The preparation script writes frozen task/input/experiment files, run configuration and preview. It does not open references or credentials, create an authorization file, or dispatch anything. `--mode full` instead selects the fixture's two prompts and three repeats (18 requests at batch size one); `--budget-usd` remains required and must be reviewed against that preview. A larger dataset is a separate explicitly scoped experiment.

## Authorization gate

After code, offline tests and the preview are reviewed, request explicit approval for the selected run, cap and credential use. Do not copy the source project's key. The operator supplies an authorized key in the execution environment and a private authorization JSON with exactly these fields, copied from that run's preview:

```json
{
  "schema_version": 1,
  "run_sha256": "COPY_FROM_PREVIEW",
  "plan_sha256": "COPY_FROM_PREVIEW",
  "request_count": 3,
  "scope": "openrouter:smoke",
  "cap": 500000
}
```

The file belongs at the `authorization_file` path in the generated config. It is intentionally absent in the prepared proposal. Do not paste the credential into a command argument, config, artifact or repository file. A local authorization JSON records the operator's decision; it cannot authenticate an external payer. Changing the experiment requires a new preview and grant. Raising an existing cap uses the audited [budget-increase command](RUNNER.md), not editing the original authorization.

## Authorized execution and acceptance

Only after approval and credential setup:

```sh
python3 -m classification_bench run --config /tmp/proposed-smoke/config.json
python3 -m classification_bench status --config /tmp/proposed-smoke/config.json
python3 -m classification_bench report --config /tmp/proposed-smoke/config.json --labels examples/candidate/labels.json --out /tmp/proposed-smoke/report.html
```

Check all three planned requests, immutable request/raw-response/receipt hashes, returned model and separately observed hosting-provider identity, parser outcomes, observed token fields and provider charges or retained holds. Missing provider metadata must be displayed as unverified, never inferred from the requested route. Client duration is not pure inference time; missing provider timing remains null. A valid completion's explicit `usage.cost` can settle independently of a missing generation lookup; absent or contradictory cost evidence retains a hold.

Rerunning `run` must make zero additional inference calls for completed or uncertain requests. `recover` must only inspect saved evidence. A timeout, 429, malformed response or refusal must remain in the three-position denominator with no automatic repair/retry. If provider identity or serving cannot be verified, the live gate is still pending even if all three requests are terminal. Report validity and reference agreement separately.

Complete release verification also requires a second operator to reproduce these documented commands and inspect the local report. Offline subprocess reproduction is useful evidence but does not replace that human handoff or the authorized live smoke. No publication or deployment is included.
