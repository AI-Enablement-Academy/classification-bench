# Clef live acceptance, 2026-10-02

Both native Cloudflare routes completed the prepared fictional product smoke and full scopes. All **42 of 42** planned requests returned saved HTTP 200 responses and valid typed choices. References were read only during offline evaluation. The calls used the local Python runner and its account-restricted project token, with no deployed Worker or hosted runner.

The user explicitly authorized this project's smoke tests and runs up to **USD 10 total**. Four exact run-bound grants allocated USD 2.50 of that allowance. No source-project approval was reused, and no subscription, payment method or credit purchase was changed.

| Scope | Requests / valid responses | Conditions | Cap | Unresolved cost hold |
| --- | ---: | --- | ---: | ---: |
| Clef smoke | 3 / 3 | baseline, one pass | USD 0.25 | USD 0.047187 |
| Clef-Flash smoke | 3 / 3 | baseline, one pass | USD 0.25 | USD 0.017697 |
| Clef full | 18 / 18 | baseline and explicit, three fresh passes each | USD 1.00 | USD 0.283122 |
| Clef-Flash full | 18 / 18 | baseline and explicit, three fresh passes each | USD 1.00 | USD 0.106182 |

All scopes use pause at budget exhaustion. Caps were unchanged. The aggregate **USD 0.454188** is a conservative retained hold, not an observed invoice charge. Exact dollar charges were unavailable for all 42 requests; a recorded known-charge sum of zero does not establish zero actual cost. Native probabilities, confidence and token usage were preserved.

## Account observations

The connected Cloudflare app's Workers AI analytics through **2026-10-02 13:25:17 UTC** reports 42 inferences, 16,875 input tokens, zero output tokens and approximately 252.818182 neurons. Saved response token totals match that input count exactly. No quota, capacity or preflight failure occurred. This demonstrates that these scopes were served on the account; it is not a dollar receipt or a guarantee of future remaining quota.

The published [Workers AI allowance](https://developers.cloudflare.com/workers-ai/platform/pricing/) is 10,000 neurons per account per day. Actual consumption for these short inputs was far below the earlier full-context planning bounds. Working subscription reads listed no Workers Paid subscription. These observed runs establish no need for an upgrade for this completed scope. Larger inputs and other account usage can change the next scope's funding requirement.

## Evaluation and recovery

Each three-item pass matched the fictional reference on all fields for **2/3 items**. Every full condition retained its nine planned positions across three separately dispatched passes, with six all-field exact matches, zero missing and zero invalid predictions. The smokes were separate integration scopes and were not counted as additional full passes. Three fictional cases cannot establish a model-quality ranking or calibrated confidence.

All four scopes returned `recovered` during explicit recovery. A completed-run restart returned `completed` for each, with unchanged request, attempt, response and receipt fingerprints and no additional dispatch. No retry, fallback or repair inference occurred.

The returned selector matched `clef` or `clef-flash`. This is a model echo from the response, not independent provider routing attestation. Client request duration is measured; pure inference time is unavailable. Exact charges remain unresolved and their holds stay in the ledgers.

## Private evidence

The actual-account frozen preparations and grants remain in `private-data/clef-account-preparation-20261002/`. The aggregate allocation, execution stdout/stderr, recovery/restart records, analytics observation, verification summary and four local reports remain in `private-data/native-acceptance-20261002/`. These files are ignored; credentials and account identifiers are excluded from this document.

- [Aggregate allocation](../private-data/native-acceptance-20261002/aggregate-allocation.json)
- [Verified scope results](../private-data/native-acceptance-20261002/verification-summary.json)
- [Account analytics observation](../private-data/native-acceptance-20261002/account-analytics-after.json)
- [Clef full report](../private-data/native-acceptance-20261002/clef-full.report.html)
- [Clef-Flash full report](../private-data/native-acceptance-20261002/clef-flash-full.report.html)

This establishes live native integration at the enrolled implementation used for these runs. Later code changes require historical read verification; they do not permit repeating the completed scopes. Latest report rendering remains a separate [acceptance check](REPORT_UX_CHECK.md). Liquid, Solar, Qwen and OpenAI Decisions retain their separately documented acceptance boundaries.
