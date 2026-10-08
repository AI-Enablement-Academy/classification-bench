# OpenRouter adapter contract

`classification_bench.adapters.OpenRouterAdapter` prepares one nonstreaming chat completion for a pinned model and provider. It makes one HTTP attempt. The runner must save `TransportResult.raw_bytes` before calling `parse`, including HTTP error or partial response bodies. A timeout leaves dispatch and billing uncertain; neither the adapter nor recovery retries it.

The adapter has offline tests and partial live evidence from the [authorized smoke](LIVE_SMOKE_RESULT.md): two HTTP 200 responses, saved raw evidence and reported charges after a sandbox correction. Both outputs fail strict validation; an earlier attempt remains unknown. Initial generation lookups were unavailable; later metadata named a dated model identifier different from the request alias, retained as an unresolved strict identity comparison. This is not a release-complete or model-quality claim.

## Public model discovery

`fetch_model_catalog(*, catalog_fetch=None, now=None, query=None, offset=0, limit=1000)` reads one public text-model catalog page. The CLI exposes it through `models`:

```sh
python3 -m classification_bench models --limit 100 --out private-data/openrouter-models.json
python3 -m classification_bench models --query 'classification' --offset 0 --limit 100 --out private-data/openrouter-model-search.json
```

Neither discovery nor `catalog` reads a credential or submits inference. The [models API](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties) supports explicit offset, limit and text search. A saved page includes the exact response text, SHA-256, source URL, observation time, returned/total counts and next offset. `complete` means the page contains the entire matching collection; a later final page can have no next offset while still omitting earlier pages. The helper refuses inconsistent pagination metadata and never follows an API-supplied URL. Each response is limited to 2 MB; request a smaller page if it exceeds that limit.

Discovery preserves declared model IDs, aliases, modalities, prices, parameters and reasoning metadata. It also keeps dynamic routers and variants visible with their incompatibility reason. This adapter requires an exact non-router slug and a pinned endpoint snapshot. Model-level reasoning capability and `reasoning_budget_eligibility: requires_pinned_endpoint_snapshot` are separate facts: an effort selector does not prove that a particular route has an enforceable cost bound. No model roster or architecture guess determines eligibility.

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

Create the snapshot with `fetch_endpoint_snapshot(model, provider)`, which reads OpenRouter's public [per-model endpoint catalog](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model) without a key or inference call. The CLI exposes this as `catalog`. The helper selects one endpoint by its exact `tag`, copies its prices and supported parameters, and uses `context_length` as a conservative prompt ceiling when `max_prompt_tokens` is null. It refuses a missing hard limit. OpenRouter's [routing rules](https://openrouter.ai/docs/guides/routing/provider-selection) let a base provider slug match regional and variant endpoints, so the helper rejects a base slug when variants exist; select a full endpoint tag such as `deepinfra/turbo`. Prices are USD per token except `request`, which is USD per request. The numbers above are illustrative, not a current quote. The model, provider tag, controls, limits and every price component must match the selected endpoint. `temperature` and `top_p` are optional when advertised. Seed, tools supplied by the experiment, response repair, model substitutions and BYOK configurations remain unsupported.

The helper also reads the public [model metadata endpoint](https://openrouter.ai/docs/api/api-reference/models/get-a-model-by-its-slug). It stores `model_identity` with the requested ID, canonical ID, source URL, time, exact response text and SHA-256. New snapshots retain the complete endpoint response as `endpoint_evidence`; provider name, pricing schedule and parameter claims must agree with those bytes. Before each live admission, the adapter fetches both sources again. Canonical identity, reasoning capability, endpoint capability, price schedule or documented provider-protocol drift blocks admission. Unrelated descriptive metadata can change; fresh response digests remain admission evidence. The illustrative legacy snapshot above omits these optional bindings and remains usable for offline preparation and historical parsing.

Live preflight and direct dispatch require frozen model identity evidence. An old snapshot that lacks it stays readable offline but cannot establish a live capability contract. In captured model metadata, omitted `reasoning` denotes a non-reasoning model under the [models guide](https://openrouter.ai/docs/guides/overview/models); the [OpenAPI schema](https://openrouter.ai/openapi.json) defines an optional object, not a top-level null value. Explicit null is rejected. Old snapshots that retain active/default reasoning metadata without the newer combined-budget evidence also stay readable offline when no explicit reasoning control was requested, but both live gates refuse them before network I/O. New snapshots and explicitly requested reasoning controls remain strictly validated at construction.

## Reasoning controls and route eligibility

Use a canonical `settings.reasoning` object, for example `{"effort":"high","exclude":true}`. `settings.effort: "high"` is a shorthand for `reasoning.effort`. Declaring the effort twice is rejected. `adapter.requested_controls` returns a copy of the exact canonical request controls for the frozen manifest; no implicit effort substitution or configuration mutation occurs.

The [reasoning guide](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) describes model-specific effort metadata. This adapter accepts gateway efforts `max`, `xhigh`, `high`, `medium`, `low`, `minimal` and `none` only when the frozen model advertises that exact choice. An omitted `supported_efforts` means no effort selection; a null value permits the gateway choices. Mandatory reasoning cannot be disabled. `max_tokens` requires advertised budget support and a positive budget below the configured total output cap. Effort and budget cannot both be declared. `enabled` and `exclude` must be booleans; contradictory settings and unknown options such as `mode` are rejected. These are requested gateway controls, not proof of a particular internal compute allocation.

Enabled reasoning, including a known active or uncertain model default, also requires a documented combined completion budget. The initial contracts cover canonical OpenAI-author models on explicitly declared OpenAI or Azure OpenAI endpoints that advertise `max_completion_tokens`. The adapter checks the captured provider name/tag and canonical model author; an Azure endpoint hosting another author's model does not inherit this contract. [OpenAI's token documentation](https://developers.openai.com/api/docs/guides/token-counting) and [Azure OpenAI's reasoning documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/reasoning) specify that this cap includes visible output, reasoning and formatting tokens. `reasoning_bound` freezes the selected protocol version and source URL.

Other providers remain visible in discovery. Their enabled reasoning is rejected until a documented bound is implemented. An explicitly disabled reasoning configuration can use the ordinary endpoint contract when disabling is advertised and allowed. Legacy snapshots without reasoning evidence add no reasoning support claim. A response that spends its cap on reasoning and returns empty content remains invalid, with its usage and charge preserved.

## Price schedules and account policy

For the documented native OpenAI protocols, `pricing_bound` retains the complete schedule and its sources. It accepts prompt-token threshold overrides; the condition applies when prompt tokens are strictly greater than the threshold, as described by the [models documentation](https://openrouter.ai/docs/guides/overview/models) and [official pricing schema](https://github.com/OpenRouterTeam/terraform-provider-openrouter/blob/main/docs/data-sources/model.md). The bound takes the highest reachable prompt/cache-read/cache-write/one-hour-write rate and highest reachable completion rate, retaining earlier high rates even if a later override is cheaper. Discounts do not reduce the reservation. Time-based or unknown conditions, unknown components, nonzero request fees and separate nonzero internal-reasoning charges are rejected. [Cache-write prices](https://openrouter.ai/docs/guides/best-practices/prompt-caching) are input-token rates and can exceed ordinary prompt prices.

Native search is optional under the documented [OpenAI](https://developers.openai.com/api/docs/guides/tools-web-search) and [Azure OpenAI](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search) tool protocols. Fee-excluding routes require advertised tools and tool-choice controls and send `tools: []`, `tool_choice: "none"`. Every request explicitly disables the `web` and `response-healing` plugins. The [shared plugin schema](https://github.com/OpenRouterTeam/docs/blob/main/api_reference/overview.mdx) supports `enabled: false` for both. This adapter does not repair or retry malformed output. The older separately inspected nano snapshot exception remains readable; other ordinary routes retain the existing conservative scalar-price restrictions.

**Request flags alone do not establish the effective account policy.** OpenRouter's [plugin settings](https://openrouter.ai/docs/guides/features/plugins/overview) can enforce account/organization defaults with “Prevent overrides.” Before paid admission, supply `settings.account_policy_assertion` with these exact fields:

```json
{
  "source": "operator evidence reference identifying the account settings review",
  "verified_at": "2026-10-08T11:00:00Z",
  "web_disabled_or_overridable": true,
  "response_healing_disabled_or_overridable": true
}
```

The source and timestamp above are a template, not verified account evidence. Check the account used for the run and replace them. Both assertions must be true. The assertion must be less than 24 hours old and cannot be future-dated; `verify_live_snapshot()` rejects unavailable or expired policy before reading live catalogs. `dispatch()` checks freshness again before transport, including when policy expires after preflight. `account_policy_prerequisite` exposes a separate versioned hash, expiry and `operator_declared` status. The prepared bound source binds its hash separately from endpoint evidence. The monetary bound is conditional on the provider honoring the operator-declared account policy. The adapter does not claim independent policy verification or inspect credentials/account settings. Old results remain readable; refresh policy through a newly frozen configuration before further admission.

`prepare` rounds `max_prompt_tokens × input-rate ceiling + max_output_tokens × completion-rate ceiling` up to integer microUSD. Reasoning is part of the total completion cap, so it adds no second completion term. Scalar legacy routes use their original prompt/completion rates. The request freezes the exact model/provider, disabled fallback, required parameters, supported output cap and price ceilings, including `max_price.request=0`. The runner checks the current operator prerequisite and catalogs before each paid admission. Endpoint observation time is historical evidence; account-policy freshness is a separate gate. Prepared bytes and implementation digests changed with the explicit plugin policy, so saved results remain readable while old implementation bindings cannot silently resume dispatch.

Usage and response-cache bypass are requested. Provider prompt caching remains separately observable; these flags do not prove every cache layer was disabled. An accepted catalog entry does not establish capacity or an eventual bill. The ledger retains unresolved charges and records any above-bound amount in full.

On 2026-10-08, public GET evidence for `openai/gpt-6.1-sol-pro` / `azure/eu` advertised the supported protocol and controls. Its retained schedule produced a conservative input ceiling of USD 0.0000055/token and completion ceiling of USD 0.0000165/token; a 128-token offline request reserved 5,777,112 microUSD against the full prompt ceiling. The regression fixture retains that public projection and original response hash. This check made zero dispatches and read no credential. It establishes catalog/price compatibility only. Actual account-policy confirmation and separately authorized live acceptance remain pending.

OpenRouter's [chat completion endpoint](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) provides the completion response, model and usage. Its [provider routing guidance](https://openrouter.ai/docs/guides/routing/provider-selection) describes exact provider selection and fallback controls. The [usage documentation](https://openrouter.ai/support/) describes `usage.include` and cost. The adapter requires a JSON object in message content with `request_id` and one ordered `predictions` entry per input ID. Each entry has `id` and `prediction`. Task vocabulary validation remains with the evaluator. Invalid content remains an invalid attempt; it is not repaired or sent again.

The completion body may omit the actual hosting provider. If it includes a provider value that differs from the pinned route, parsing marks the response invalid while preserving its usage and cost, except for the explicitly observed `openai` routing tag / `OpenAI` display-name pair. The raw returned name is preserved; no general fuzzy matching is used. After saving the completion, call `lookup_generation(response_id, api_key)` and save that separate raw result. `parse_generation` checks the exact generation ID and accepts either the requested model ID or the canonical ID captured in the verified snapshot. Without that binding, only the requested ID is accepted. It preserves the actual metadata model separately and extracts `provider_name`, cost and provider generation time from OpenRouter's [generation metadata endpoint](https://openrouter.ai/docs/api/api-reference/generations/get-generation). The requested provider slug and observed provider name are separate evidence. If the metadata lookup fails, report the hosting provider as unverified. A valid completion `usage.cost` can still settle the charge; hold it only when no trustworthy cost field is available.

Only the isolated network child may receive the API key. The key is absent from prepared request bytes and manifests. If a service reflects the key in a response body, the adapter replaces those bytes with `[REDACTED_API_KEY]` and marks `redacted=true`; the runner stores that bounded redacted evidence. HTTP redirects and inherited proxies are disabled. `TransportResult.truncated` or `error` makes a 200 body invalid, while a no-response transport exception remains outcome unknown.

The scheduler calls this provider through [OpenRouterRuntime](ADAPTER_RUNTIME.md); credentials, transport and optional generation lookup are runtime responsibilities.
