# Cloudflare account setup, 2026-10-02

The connected Cloudflare app found one account and successfully read the Clef and Clef Flash catalog entries. Four fresh offline previews now use that actual account in `private-data/clef-account-preparation-20261002/`. Account identifiers and API observations stay in ignored private files. The local Python runner needs API access; it does not require a deployed Worker or hosted runner. See [Clef operation](CLEF_DECISIONS.md).

## Initial app checks

The app returned HTTP 200 for account discovery, both model listings, the Flash request/response schema, account entitlements and Workers account settings. The settings report `default_usage_model: standard`; this does not establish the account's Free/Paid subscription. The returned entitlements contain no Workers AI allocation entry.

The GraphQL analytics query for this account, from 2026-10-02 00:00 UTC through 12:36:14 UTC, returned an empty `aiInferenceAdaptiveGroups` array without errors. This means no usage rows were reported for that interval. Analytics can lag and is not a remaining-quota or billing receipt.

Subscription listing returned error 10000, `Authentication error`. Token listing and token permission-group listing returned error 9109, `Unauthorized to access requested resource`. Billing status and token provisioning are therefore unresolved through this connection. No token was created or copied, `.env` was preserved, and no inference, upgrade, credit purchase or deployment occurred.

## Authorized credential setup

The user subsequently authorized checking the main environment file at `/Users/adamkovacs/Documents/codebuild/.env`. Its `CF_ACCOUNT_ID` matches the connected account. Its `CF_API_TOKEN` is active and permits token management, but lacks Workers AI and Billing Read permissions. Direct model catalog and subscription reads with that existing token returned HTTP 403. The app's authentication is separate from the process environment used by the local Python runner; using the app does not populate the runner's credential variable.

Using the authorized main token for setup, a project-specific token was created through [Cloudflare's token API](https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/). Its verified policy grants Workers AI Read, Workers AI Write and Billing Read to exactly the discovered account, without token-management or Billing Write permissions. It expires at **2026-11-01 13:03:47 UTC**. The token value is saved only as `CLOUDFLARE_CLEF_API_TOKEN` in this repository's ignored, mode-0600 `.env`. Existing entries and the main `.env` bytes were preserved. No value was displayed, committed or saved to memory.

Read-only verification returned HTTP 200 for token status (active), both Clef catalog entries and subscription listing. The returned subscriptions are Teams Free Base (account) and Cloudflare Free Plan (zone), each with price zero; no Workers Paid subscription was listed. This does not establish the exact remaining Workers AI quota. A fresh app analytics query from 00:00 UTC through 13:05:37 UTC still returned no usage rows. Sanitized evidence and token metadata are in `private-data/cloudflare-main-env-check-20261002/`; the earlier frozen previews and observations remain unchanged.

The main environment location and lookup convention are saved in shared Ruflo and a Codex memory update note, without credentials. Credential setup is complete; no additional key is needed from the operator for this prepared scope. No inference, payment change, upgrade or hosted resource was added. A future run must recheck token expiry and any scope-specific billing prerequisites.

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

Smaller requests may consume much less. Other account usage shares the allowance. Larger scopes can be spread across daily resets. Exceeding the free allocation through the direct route requires [Workers Paid](https://developers.cloudflare.com/workers/platform/pricing/), starting at $5 per account per month, plus usage above the daily allowance at $0.011 per 1,000 neurons. No Workers Paid subscription was listed in the working subscription read. This implementation does not use prepaid AI Gateway credits. The completed short-input scopes used approximately 252.818182 neurons, with no quota failure.

Free exhaustion is documented as HTTP 429 with internal code 3036; capacity exhaustion is a different error, 3040. See [Workers AI errors](https://developers.cloudflare.com/workers-ai/platform/errors/). Neither grants permission for a retry or an upgrade.

## Finish setup

1. Review today's neuron usage and actual Free/Paid entitlement in the [Cloudflare dashboard](https://dash.cloudflare.com/?to=/:account/ai/workers-ai) or other authoritative account evidence immediately before any free-only scope. Subscription reads now work with the project token; empty analytics is insufficient to assert a remaining allowance.
2. Use the existing local `CLOUDFLARE_CLEF_API_TOKEN`; check its expiry before execution. A new token is unnecessary while this one remains valid. For renewal, follow [Cloudflare's REST setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) and [token API guide](https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/), preserving account restriction and private storage. The main environment file is the authorized lookup source for setup credentials; copy only the selected project credential into an inference environment.
3. Review the actual-account previews before a new scope. Smoke and full caps remain operator settings with `pause` or `stop`. The user subsequently approved up to USD 10 total in this project; separate grants totaling USD 2.50 funded the exact prepared Clef/Flash scopes. [Live results](CLEF_LIVE_ACCEPTANCE_20261002.md) preserve their completed evidence and unknown-cost holds. Do not repeat those scopes or request their approval again.
4. Use the [operator workflow](RUNNER.md) for an approved scope. Local dollar-budget exhaustion supports `pause` or `stop`; an explicit cap increase records the operator's amendment. The runner does not automatically buy credits, upgrade, wait for a daily quota reset or settle unknown charges as zero. Preserve failures and any unresolved holds before considering remaining, never-sent requests.

Setup is complete. The separately authorized [native smoke and full runs](CLEF_LIVE_ACCEPTANCE_20261002.md) completed all 42 requests without quota failures or an upgrade. Fresh app analytics reports approximately 252.818182 neurons and 16,875 input tokens. Exact USD charges remain unavailable; retained holds are not invoices. No extra key or payment setup is needed for that completed scope. Recheck access and quota before a new scope; do not repeat these completed requests.
