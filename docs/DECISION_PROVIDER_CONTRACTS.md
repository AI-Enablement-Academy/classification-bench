# Decision provider contracts

Checked against public provider documentation on 2026-09-30. These are direct, native decision routes. No paid call or credential-backed probe was made for this review. The endpoints and examples below are documentation evidence, not a live service acceptance result. The benchmark must preserve the raw response, treat a missing answer or model identity as an unresolved classification outcome, and record missing usage as unavailable billing evidence.

## Common request and result shape

The three providers document a System One request with `model`, `state`, and a `questions` map. For categorical classification, each question uses `type: "choice"`, an `instructions` string, and a `criteria` map from option ID to description. The response contains `answers[question_id].type`, `.choice`, `.probabilities`, and `.confidence`. The selected option and probability map are separate evidence; `confidence` is not the selected option's probability. The benchmark sends one record per request and one typed question for each categorical field. Cost admission must account for every question because the providers may meter shared state again for each one. [Liquid](https://docs.liquid.ai/lfm/models/decision-models), [Upstage](https://console.upstage.ai/api/systemone), [Alibaba Cloud](https://help.aliyun.com/en/model-studio/decision-model-api).

```json
{
  "model": "PROVIDER_MODEL_ID",
  "state": "The case text or a structured JSON state",
  "questions": {
    "label": {
      "type": "choice",
      "instructions": "Choose the category that best fits the state.",
      "criteria": {
        "category_a": "Definition of category A",
        "category_b": "Definition of category B"
      }
    }
  }
}
```

The option descriptions and instructions are task rubric text, not provider policy. The benchmark should keep reference labels out of the request, check that every returned probability key belongs to the enrolled option set, and retain the provider's numeric values without replacing them with `confidence`. [Liquid choice example](https://docs.liquid.ai/lfm/models/decision-models), [Upstage choice example](https://console.upstage.ai/api/systemone), [Alibaba choice example](https://help.aliyun.com/en/model-studio/decision-model-api).

## Liquid d1

- Route: `POST https://api.liquid.ai/decisions/v1/systemone`, bearer key from `LIQUID_API_KEY`, model `d1:free`. Liquid's examples accept plain-text state or a JSON object. [Liquid decision model guide](https://docs.liquid.ai/lfm/models/decision-models).
- Documented choice response: echoed `model`, `answers[label].type`, `.choice`, `.probabilities`, `.confidence`, and `usage.input_tokens` plus `usage.output_tokens`. Liquid states `output_tokens` is always zero. Its examples do not show a request ID. [Liquid decision model guide](https://docs.liquid.ai/lfm/models/decision-models).
- Published price or hard bound: the documented model ID includes `:free`, but the guide does not state a durable price, request quota, choice count, or d1 context cap. A billing admission rule needs a separately reviewed, current provider price or free-route attestation; the model ID alone is not a numeric USD upper bound. [Liquid decision model guide](https://docs.liquid.ai/lfm/models/decision-models).

## Upstage Solar Decide

- Route: `POST https://api.upstage.ai/v1/systemone`, bearer Upstage API key, model `solar-decide`. The docs use `UPSTAGE_API_KEY` as the key placeholder. `state` may be a string or any JSON value. At least one question is required. Solar Decide is beta, and Upstage warns that the schema may change before general availability. [Upstage System One API](https://console.upstage.ai/api/systemone).
- Choice accepts 2 to 26 options; 27 produces HTTP 422 in the documented example. The stated context window is 512K tokens. The example response echoes `model` and includes `answers` and `usage.input_tokens`/`usage.output_tokens`; it does not show a request ID. Upstage says output tokens are not billed, although its example records four output tokens. Keep the observed count and billing rule distinct. [Upstage System One API](https://console.upstage.ai/api/systemone).
- Upstage's public [API pricing page](https://www.upstage.ai/pricing/api) does not list a Solar Decide rate. The native route therefore needs a separately reviewed price snapshot and upper bound before paid admission. The price for a different Solar model is not evidence for this route.

## Alibaba Cloud decision-model-preview

- Route: `POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone` in Beijing or `POST https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/systemone` in Singapore. `{WorkspaceId}` must be an actual workspace ID for the chosen region. Authentication is `Authorization: Bearer $DASHSCOPE_API_KEY`; model is `decision-model-preview`. There is no documented generic hostname for this API. [Alibaba Decision Model API](https://help.aliyun.com/en/model-studio/decision-model-api).
- `state` may be a string, object, or array. Choice criteria are an option-name to description map, with 1 to 255 options. `instructions` is optional. There is no hard question-count limit in the API reference, though it recommends at most 16. The context maximum is 65,536 tokens; an overlong state may be rejected or truncated. [Alibaba Decision Model API](https://help.aliyun.com/en/model-studio/decision-model-api).
- Response fields include echoed `model`, `request_id`, `answers[label]` with choice/probabilities/confidence, `usage.input_tokens`, and `latency_ms`. Its model info lists maximum output length zero and says batch inference is unsupported. That is compatible with multiple typed questions in one synchronous request; it does not establish a batch jobs route. [Alibaba Decision Model API](https://help.aliyun.com/en/model-studio/decision-model-api), [model info](https://help.aliyun.com/en/model-studio/decision-model-preview).
- The current model info lists both regions as "Limited-time free" without a lasting price or end date. Recheck the region's actual price before a paid run and bind any operator-reviewed billing assumption to that run. [Alibaba model info](https://help.aliyun.com/en/model-studio/decision-model-preview).

## Billing and identity boundary

The direct provider docs do not expose a request parameter that caps billable USD or output length for these native decision calls. A caller-set reservation is an accounting control, not proof of a provider charge maximum. Admission should use a documented rate or an operator-reviewed current free-route attestation, an enforced question count and input cap, and a conservative allowance for provider tokenization and repeated state metering across questions. A returned token count alone cannot establish the pre-dispatch bound. Exact response cost is unavailable in the cited direct examples, so settled cost needs separately verified billing evidence or an explicit unresolved state. [Liquid](https://docs.liquid.ai/lfm/models/decision-models), [Upstage](https://console.upstage.ai/api/systemone), [Alibaba Cloud](https://help.aliyun.com/en/model-studio/decision-model-api), [adapter runtime contract](ADAPTER_RUNTIME.md).

OpenRouter separately lists [Solar Decide](https://openrouter.ai/upstage/solar-decide) at $0.05 per million input tokens and zero output-token price through its Decisions API. That is a price for the OpenRouter route, not a published direct Upstage price. OpenRouter says its platform fee applies when buying credits, rather than on each inference request. [OpenRouter pricing explanation](https://openrouter.ai/business). This repository's direct Upstage route must not silently substitute OpenRouter as its provider.
