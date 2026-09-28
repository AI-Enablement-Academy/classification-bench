# Live identity smoke result

The operator explicitly approved the prepared three-request fictional product smoke, allowing up to $1 if needed. Execution retained the reviewed $0.50 cap and pause policy; no increase was needed. Existing repository-local credential use was authorized. No credentials are included here.

The run is `private-data/identity-proposal-20260928/config.json`, with run hash `bac714eccb69d027a942cca1cfbf85dc2df48f074bfb9994633118175621aeb1` and plan hash `bd0be80544880f755b48fbf03b2959cdea5ff9ec3bba6d55e3d2742fb298b70c`. Its three records use the product baseline prompt, one repeat, batch size one, temperature zero and 512 maximum output tokens. The route is OpenRouter `openai/gpt-4.1-nano` via `openai`. Conservative reservations total $0.314889.

## Verified outcome

All three requests completed once and parsed valid. All three agree exactly with the fictional reference labels; this tiny smoke does not establish model quality. Raw response hashes, receipt hashes and request/attempt/manifest/input bindings were independently verified. All three positions remain in the report denominator, with no invalid or missing outputs.

| Record | Input/output tokens | Client duration | Later provider generation time | Reported cost | Rounded ledger charge |
| --- | --- | --- | --- | --- | --- |
| toy-a | 239 / 87 | 1331 ms | 967 ms | $0.0000587 | 59 microUSD |
| toy-b | 243 / 89 | 1594 ms | 1358 ms | $0.0000599 | 60 microUSD |
| toy-c | 225 / 81 | 1397 ms | 1020 ms | $0.0000549 | 55 microUSD |

Reported charges sum to $0.0001735; conservative per-request rounding produces a ledger total of **$0.000174**. There are no active reservations or unknown holds in this run. This does not clear the separate historical smoke hold. Reasoning/cache counts were returned as zero. Pure inference time remains unavailable.

Recovery found no unresolved work. Restart preserved exactly three settled attempts and three dispatch events. An initial restart command omitted the credential environment and failed before admission; loading the authorized environment and repeating the command completed without additional dispatch.

## Identity and metadata timing

The frozen public catalog binds the requested alias to `openai/gpt-4.1-nano-2025-04-14`. Every admission records the corresponding identity digest. Each completion returned the requested alias and provider display name OpenAI.

Immediate generation metadata lookups returned 404. These immutable artifacts and the original report remain unchanged. Later read-only lookups returned HTTP 200 for all three saved response IDs. Raw bodies and SHA-256 digests are saved under `metadata-followup/`; the current adapter parser validates the frozen canonical model, matching response IDs and OpenAI provider. Generation costs match the completion costs exactly and the rounded ledger values. These lookups performed no inference and created no repeats.

Independent review: **APPROVE**, no confirmed BLOCKING findings. RESIDUAL: this run did not exercise an immediate successful metadata lookup or its successful identity display in the HTML. The original report truthfully retains unavailable generation metadata; later verification is separate. Metadata identifies OpenAI but does not prove the exact serving endpoint tag or endpoint price.

## Evidence and remaining gate

Private evidence: `preview.json`, `authorization.json`, `execution.json`, `recovery.json`, `restart.json`, `run.sqlite`, immutable `artifacts/objects`, `metadata-followup/verification.json` and `report.html` in the run directory. None is published or tracked. The candidate-experience project was untouched.

The current adapter now has live identity evidence. The revised report still needs the [visual and keyboard check](REPORT_UX_CHECK.md); no browser-policy bypass was attempted. See [implementation status](IMPLEMENTATION_STATUS.md) for the complete boundary and [historical smoke](LIVE_SMOKE_RESULT.md) for the preserved earlier observations.
