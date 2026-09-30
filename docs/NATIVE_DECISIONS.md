# Native decision adapters

Liquid d1, Upstage Solar Decide and Alibaba Qwen decision-model-preview use native categorical requests through the existing matrix runner. Provider contracts and source links are recorded in [decision provider contracts](DECISION_PROVIDER_CONTRACTS.md). OpenAI's announced API is [pending a verified public contract](OPENAI_DECISIONS_STATUS.md).

| Adapter setting | Model | Credential environment variable |
| --- | --- | --- |
| `liquid_decide` | `d1:free` | `LIQUID_API_KEY` |
| `solar_decide` | `solar-decide` | `UPSTAGE_API_KEY` |
| `qwen_decision` | `decision-model-preview` | `DASHSCOPE_API_KEY` |

Each request contains one input record. Each categorical output field becomes one typed choice question. The state preserves the record, each question uses the original prompt as its instructions, and the task's labels supply the option IDs and descriptions. Existing task files have no separate label-description field; these adapters do not invent definitions. Put the reviewed classification rubric in the prompt. Reference answers remain outside the inference capsule.

The [proposed three-request acceptance scopes](NATIVE_SMOKE_PLAN.md) fix the fictional inputs, prompt and proposed cap for each provider. No native execution is authorized.

These implementations have offline tests. They have not been verified with live provider calls. The previous OpenRouter smoke approval does not authorize these providers. Their native endpoints, credentials and evidence are separate from the OpenRouter chat route.

## Review billing before preparation

Run preparation requires an operator-reviewed billing snapshot. The snapshot binds a provider source URL and its raw-byte SHA-256, observation and expiry timestamps, a conservative input allowance, rates, and a per-request fee. Retain the raw source bytes alongside the reviewed snapshot so the billing assertion can be audited later. Preflight requires the bound source to remain unchanged and the review to remain current. A matching page hash proves that the page bytes are unchanged; it does not prove that the operator extracted the right rate or that their account has that price.

The documented direct routes provide no enforceable output-token cap. Nonzero output pricing is therefore unsupported. Metered Liquid and Solar remain blocked: the reviewed direct-route documentation does not establish the required price evidence, and Liquid also lacks a published context cap. Metered Qwen requires the full published context allowance per question plus the request fee, conservatively multiplied by the number of questions. Free-route admission is an explicit operator attestation; the source hash alone does not establish an account entitlement. Missing billing evidence is a blocker, not an invitation to copy the price of a different model or serving route. In particular, an OpenRouter Solar price does not establish a direct Upstage price.

The snapshot has these fields:

| Field | Meaning |
| --- | --- |
| `source_url` | Allowed official provider billing evidence URL |
| `response_sha256` | SHA-256 of the exact source response bytes |
| `observed_at`, `valid_until` | UTC timestamps bounding the operator's review |
| `max_input_tokens` | Input allowance per question; metered routes require the full published context cap |
| `input_usd_per_token` | Reviewed USD input rate as a decimal string |
| `output_usd_per_token` | Must be the reviewed zero output rate |
| `request_usd` | Reviewed request fee as a decimal string |
| `basis` | `free` or `metered`, consistent with the rates |

Do not use a fabricated snapshot to enable dispatch. Liquid's `:free` model name alone is insufficient price evidence. Qwen's current limited-time-free statement must still be reviewed for the actual region and account. See [the source review](DECISION_PROVIDER_CONTRACTS.md) for unresolved direct-route pricing details.

## Prepare a run without inference

From the repository root, use a fresh private directory and an actual reviewed billing file:

```sh
python3 -m scripts.prepare_decision_run \
  --directory private-data/liquid-smoke \
  --adapter liquid_decide \
  --billing-snapshot /private/path/liquid-billing.json \
  --task product --mode smoke \
  --budget-usd 0.50 --on-budget-exhausted pause
```

Choose `solar_decide` or `qwen_decision` for the other routes. Qwen also requires `--workspace-id YOUR_WORKSPACE_ID --region cn-beijing` or `--region ap-southeast-1`. The helper prepares three requests for the fictional product smoke. Full mode prepares 18 requests, covering both prompts and three repeats. Both modes require an explicit budget; `pause` and `stop` have the same [audited behavior](RUNNER.md#at-the-budget-limit) as other adapters.

Preparation reads no credential, creates no authorization, and makes no model call. Inspect `preview.json` before approving the exact provider, task, request count and total cap. Keep any authorized key in the ignored local `.env`, with permissions `0600`, using the matching variable above. Never put credentials in JSON, command arguments, reports or commits. The runner rejects a generic supplied API key for native routes to prevent accidental reuse of an OpenRouter key.

After a separate scope approval, follow the [runner's run-bound authorization workflow](RUNNER.md). First live verification should use one provider and the three-request fictional smoke. Check saved raw responses, full-denominator outcomes, probabilities, identity evidence, budget holds and restart behavior before approving a larger comparison.

## Cost and identity remain evidence

Native response usage is retained, including probability distributions and confidence. A valid categorical answer can coexist with unresolved billing. These documented responses do not establish an exact USD charge, so observed cost stays unknown and its reservation remains encumbered. A free-price assertion at admission does not create a zero-charge receipt.

Returned model identity is checked against the configured native model. This is response evidence, not an independent billing or routing attestation. Raw response and transport evidence are preserved; restart recovery never makes a replacement inference call. Unsupported controls remain visible as blockers rather than being silently dropped. Qwen documents possible truncation for overlong context. The adapter rejects payloads above its conservative byte allowance, but exact provider framing and tokenization have not been live-verified; keep the first smoke inputs small.
