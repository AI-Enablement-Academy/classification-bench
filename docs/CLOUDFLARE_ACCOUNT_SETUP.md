# Cloudflare account setup, 2026-10-02

The connected Cloudflare app found one account and successfully read the Clef and Clef Flash catalog entries. Four fresh offline previews now use that actual account in `private-data/clef-account-preparation-20261002/`. Account identifiers and API observations stay in ignored private files. The local Python runner needs API access; it does not require a deployed Worker or hosted runner. See [Clef operation](CLEF_DECISIONS.md).

## Verified access and remaining limits

The app returned HTTP 200 for account discovery, both model listings, the Flash request/response schema, account entitlements and Workers account settings. The settings report `default_usage_model: standard`; this does not establish the account's Free/Paid subscription. The returned entitlements contain no Workers AI allocation entry.

The GraphQL analytics query for this account, from 2026-10-02 00:00 UTC through 12:36:14 UTC, returned an empty `aiInferenceAdaptiveGroups` array without errors. This means no usage rows were reported for that interval. Analytics can lag and is not a remaining-quota or billing receipt.

Subscription listing returned error 10000, `Authentication error`. Token listing and token permission-group listing returned error 9109, `Unauthorized to access requested resource`. Billing status and token provisioning are therefore unresolved through this connection. No token was created or copied, `.env` was preserved, and no inference, upgrade, credit purchase or deployment occurred.

## Free capacity and payment threshold

[Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) includes 10,000 neurons per account per day, resetting at 00:00 UTC. Clef and Flash are absent from the page's models requiring paid billing; this supports Free availability but does not prove live entitlement on this account. Published input rates are 21,818 neurons per million tokens for Clef and 8,182 for Flash. Their [model](https://developers.cloudflare.com/workers-ai/models/clef/) [pages](https://developers.cloudflare.com/workers-ai/models/clef-flash/) give a 65,536-token context.

The following planning bounds round up per request: `ceil(65,536 × neurons_per_million / 1,000,000)`. They are estimates, not measured consumption or Cloudflare's verified rounding method.

| Proposal | Requests | Neuron bound | Fits an unused daily allowance? |
| --- | ---: | ---: | --- |
| Clef smoke | 3 | 4,290 | Yes |
| Flash smoke | 3 | 1,611 | Yes |
| Both smokes | 6 | 5,901 | Yes |
| Clef full | 18 | 25,740 | No |
| Flash full | 18 | 9,666 | Yes, little headroom |
| Both fulls | 36 | 35,406 | No |

Smaller requests may consume much less. Other account usage shares the allowance. The published limits do not justify requesting funds for the two smokes yet; verify the actual plan and available allowance before dispatch. Larger scopes can be spread across daily resets. Exceeding the free allocation through the direct route requires [Workers Paid](https://developers.cloudflare.com/workers/platform/pricing/), starting at $5 per account per month, plus usage above the daily allowance at $0.011 per 1,000 neurons. An existing paid subscription could already cover the base fee; its presence is unverified. This implementation does not use prepaid AI Gateway credits.

Free exhaustion is documented as HTTP 429 with internal code 3036; capacity exhaustion is a different error, 3040. See [Workers AI errors](https://developers.cloudflare.com/workers-ai/platform/errors/). Neither grants permission for a retry or an upgrade.

## Finish setup

1. Check the account's Workers plan and today's neuron usage in the [Cloudflare dashboard](https://dash.cloudflare.com/?to=/:account/ai/workers-ai). Alternatively, reconnect the app with billing read access; analytics reads already work. Recheck immediately before any free-only scope.
2. Follow [Cloudflare's REST setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) to create a dedicated token with Workers AI Read and Edit permissions restricted to the discovered account. Put it only in this repository's ignored, mode-0600 `.env` as `CLOUDFLARE_CLEF_API_TOKEN`. Preserve existing entries and keep the token out of chat, config and CLI arguments.
3. Review the actual-account previews. Smoke caps are illustrative USD 0.25 per model; full caps are illustrative USD 1.00 per model. Both use `pause`. These remain operator settings and confer no authorization. The [smoke plan](NATIVE_SMOKE_PLAN.md) requires a separate run-bound approval after billing and credential prerequisites are resolved.
4. Use the [operator workflow](RUNNER.md) for an approved scope. Local dollar-budget exhaustion supports `pause` or `stop`; an explicit cap increase records the operator's amendment. The runner does not automatically buy credits, upgrade, wait for a daily quota reset or settle unknown charges as zero. Preserve failures and any unresolved holds before considering remaining, never-sent requests.

Setup and offline preparation can proceed without payment. Live acceptance remains pending account billing review, a dedicated local token and approval of the exact scope.
