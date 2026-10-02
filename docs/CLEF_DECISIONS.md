# Cloudflare Clef decisions

The `clef_decide` and `clef_flash_decide` adapters run the native Cloudflare Workers AI decision models through the existing categorical matrix. Cloudflare's [Clef](https://developers.cloudflare.com/workers-ai/models/clef/) and [Clef Flash](https://developers.cloudflare.com/workers-ai/models/clef-flash/) pages identify the model routes, request selectors, 65,536-token contexts, and typed question contract. The [Workers AI REST guide](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) documents bearer authentication and the `success`/`result` response envelope.

| Adapter | Native model route | Request selector | Published input price |
| --- | --- | --- | --- |
| `clef_decide` | `@cf/cloudflare/clef` | `clef` | $0.24 per million input tokens |
| `clef_flash_decide` | `@cf/cloudflare/clef-flash` | `clef-flash` | $0.09 per million input tokens |

The prices come from [Cloudflare's Workers AI pricing page](https://developers.cloudflare.com/workers-ai/platform/pricing/). That page lists input tokens for these models and no output-token rate. The adapter reserves a full 65,536-token context at the model's published rate for each request: 15,729 micro-USD for Clef or 5,899 micro-USD for Flash, rounded up. Each request has one record and all its choice questions. Cloudflare's [open-weight implementation](https://huggingface.co/Cloudflare/clef/blob/main/joint_schema_model.py) builds one model input and reports one `usage.input_tokens` value for the combined questions. Hosted accounting has not been live verified. The runner retains the reservation as an unknown-cost hold because response usage does not establish an exact USD charge. Free daily allocation does not reduce this bound.

Preparation requires a reviewed billing snapshot with the existing native snapshot fields. Set `source_url` to the selected model page above; set `response_sha256` to the SHA-256 of its exact fetched response bytes, `max_input_tokens` to `65536`, `basis` to `metered`, `input_usd_per_token` to `0.00000024` for Clef or `0.00000009` for Flash, and both `output_usd_per_token` and `request_usd` to `0`. Set `observed_at` and `valid_until` to UTC times bounding the operator's review. The fetch requests Cloudflare's documented Markdown representation with `Accept: text/markdown` and an identifying `classification-bench/1.0` user agent, without redirects or proxies. Hash those exact Markdown response bytes, not a browser-rendered HTML page. Live preflight fetches the source again and rejects a changed or expired snapshot. The operator must confirm the price and account plan; matching bytes alone cannot do that.

From the repository root, capture the exact bytes and digest with the same fetch used at preflight:

```sh
python3 - <<'PY'
from pathlib import Path
from hashlib import sha256
from classification_bench.decision_adapters import _cloudflare_billing_fetch

url = 'https://developers.cloudflare.com/workers-ai/models/clef/'
raw = _cloudflare_billing_fetch(url)
Path('/private/path/clef-source.md').write_bytes(raw)
print(sha256(raw).hexdigest())
PY
```

Review and retain the captured source before recording its digest in the snapshot. Use the Flash URL and a separate source file for Flash.

Prepare an offline preview with the account ID, reviewed snapshot, and a budget policy:

```sh
python3 -m scripts.prepare_decision_run \
  --directory private-data/clef-smoke \
  --adapter clef_decide \
  --account-id YOUR_32_HEX_CLOUDFLARE_ACCOUNT_ID \
  --billing-snapshot /private/path/clef-billing.json \
  --task product --mode smoke \
  --budget-usd 0.25 --on-budget-exhausted pause
```

Change the adapter to `clef_flash_decide` and use its own reviewed source and rate for Flash. Smoke mode prepares three fictional requests; full mode prepares 18 across both prompts and three repeats. Preparation makes no inference call and creates no authorization. A $0.25 cap covers all 18 Flash reservations, but only 15 Clef reservations, so inspect `preview.json` and choose a cap and `pause` or `stop` policy that fit the intended scope. An offline preview does not authorize live dispatch.

The live route requires a Cloudflare Workers AI token in the private `CLOUDFLARE_CLEF_API_TOKEN` environment variable. [Cloudflare's REST setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) describes obtaining an account ID and token with Workers AI Read and Edit permissions. Do not put the token in the config, snapshot, CLI arguments, or a committed file. The transport sends one POST to the pinned Cloudflare API host, blocks redirects and proxy use, and makes no automatic retry.

The [account setup check](CLOUDFLARE_ACCOUNT_SETUP.md) records current connector access, actual-account previews, daily free-capacity bounds and the remaining billing/token prerequisites. Published free allowance does not prove the account's remaining quota or clear unresolved dollar holds.

The adapter accepts a successful REST envelope only when `result.model` matches the selected request model and each typed choice uses a configured label. It records `probabilities` and `confidence` separately in raw response evidence and parsed usage. The model field is a response echo, not independent proof of provider identity. Missing, malformed, or incomplete responses remain invalid or unknown outcomes in the full denominator. The adapter rejects requests whose serialized body exceeds the 65,536-byte allowance, but this cannot prove that state plus provider framing fits the model context. The [model page](https://developers.cloudflare.com/workers-ai/models/clef/) says long state may be truncated. Keep the first smoke inputs small and inspect raw evidence. Cloudflare's model pages document optional image input, but this adapter currently supports text and JSON state only; it never reads image paths or remote URLs. No Cloudflare inference request has been made for this implementation.
