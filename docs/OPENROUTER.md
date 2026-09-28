# OpenRouter adapter contract

`classification_bench.adapters.OpenRouterAdapter` prepares one nonstreaming chat completion for a pinned model and provider. It makes one HTTP attempt. The runner must save `TransportResult.raw_bytes` before calling `parse`, including HTTP error or partial response bodies. A timeout leaves dispatch and billing uncertain; neither the adapter nor recovery retries it.

The adapter is offline tested. That does not establish live serving, exact route availability, or charge behavior. A live smoke needs its own authorization and stored provider receipts.

## Configuration

Use an experiment configuration with `model` set to an exact OpenRouter slug and `settings` containing:

```json
{
  "adapter": "openrouter",
  "provider": "provider-slug",
  "max_output_tokens": 128,
  "temperature": 0,
  "endpoint_snapshot": {
    "model_id": "author/exact-model",
    "provider_tag": "provider-slug",
    "observed_at": "2026-09-28T12:00:00Z",
    "source_url": "https://openrouter.ai/api/v1/models/author/exact-model/endpoints",
    "max_prompt_tokens": 4096,
    "max_completion_tokens": 1024,
    "supported_parameters": ["max_completion_tokens", "temperature"],
    "pricing": {"prompt": "0.000001", "completion": "0.000002", "request": "0"}
  }
}
```

Create the snapshot with `fetch_endpoint_snapshot(model, provider)`, which reads OpenRouter's public [per-model endpoint catalog](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints) without a key or inference call. The repository CLI also exposes this as `catalog`. The helper selects one endpoint by its exact `tag`, copies its prices and supported parameters, and uses `context_length` as a conservative prompt ceiling when `max_prompt_tokens` is null. It refuses a missing hard limit. OpenRouter's [routing rules](https://openrouter.ai/docs/guides/routing/provider-selection) let a base provider slug match regional and variant endpoints, so the helper rejects a base slug when variants exist; select a full endpoint tag such as `deepinfra/turbo`. Prices are USD per token except `request`, which is USD per request. The numbers above are illustrative, not a current quote. The model, provider tag, controls, input ceiling, output ceiling and every price component must match the selected endpoint. A cache read price at or below the prompt price fits within the prompt-token bound; [OpenRouter's caching guide](https://openrouter.ai/docs/guides/best-practices/prompt-caching) describes the lower read rate. The inspected `openai/gpt-4.1-nano` route through `openai` is the sole exception for nonzero catalog `web_search` pricing: this adapter sends no tools or plugins, and that route's search is optional. Other routes with nonzero `web_search` pricing are rejected because a model may initiate billable search without an explicit tool. A nonzero request fee or another unbounded component is rejected. The request includes `max_price.request=0` as an additional route guard. `temperature` and `top_p` are optional when the selected endpoint lists them as supported. The adapter currently rejects effort, seed, tools, response repair, model aliases and BYOK configurations.

`prepare` computes an integer microUSD reservation by rounding up `max_prompt_tokens × prompt price + max_output_tokens × completion price`. It puts the exact model, provider allowlist, disabled provider fallback, required parameters, supported output-limit parameter and price ceilings in the request. It requests usage and disables response caching by header. The runner calls `verify_live_snapshot()` immediately before each paid admission. That reads the catalog again and rejects a changed endpoint capability or price. A saved run can resume with its original snapshot if the current catalog still matches; the original observation time remains evidence, not a freshness gate. An accepted catalog entry does not prove capacity or a future provider bill; the ledger retains unresolved charges and records any above-bound observed amount in full.

OpenRouter's [chat completion endpoint](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) provides the completion response, model and usage. Its [provider routing guidance](https://openrouter.ai/docs/guides/routing/provider-selection) describes exact provider selection and fallback controls. The [usage documentation](https://openrouter.ai/support/) describes `usage.include` and cost. The adapter requires a JSON object in message content with `request_id` and one ordered `predictions` entry per input ID. Each entry has `id` and `prediction`. Task vocabulary validation remains with the evaluator. Invalid content remains an invalid attempt; it is not repaired or sent again.

The completion body may omit the actual hosting provider. If it includes a provider slug that differs from the pinned route, parsing marks the response invalid while preserving its usage and cost. After saving the completion, call `lookup_generation(response_id, api_key)` and save that separate raw result. `parse_generation` checks the generation and model IDs and extracts `provider_name`, cost and provider generation time from OpenRouter's [generation metadata endpoint](https://openrouter.ai/docs/api/api-reference/generations/get-generation). The requested provider slug and observed provider name are separate evidence. If the metadata lookup fails, report the hosting provider as unverified. A valid completion `usage.cost` can still settle the charge; hold it only when no trustworthy cost field is available.

Only the isolated network child may receive the API key. The key is absent from prepared request bytes and manifests. If a service reflects the key in a response body, the adapter replaces those bytes with `[REDACTED_API_KEY]` and marks `redacted=true`; the runner stores that bounded redacted evidence. HTTP redirects and inherited proxies are disabled. `TransportResult.truncated` or `error` makes a 200 body invalid, while a no-response transport exception remains outcome unknown.
