# Independent operator check: 2026-09-28

At the user's request, two separate subagents performed the [operator checklist](OPERATOR_CHECK.md) against commit `4613b8f249db347b2203478647455ac116d1d1b0`. One ran the workflow; the other inspected the generated report artifacts. This was independent agent verification, not human inspection. Python was 3.14.6 on macOS 26.6 arm64. No browser was used and no provider calls or credentials were involved.

## Workflow: passed

Both fictional demos completed 24 of 24 requests and retained 36 classification positions: 18 valid, 18 deliberately invalid, zero missing. The candidate rerun preserved all request IDs and left the database at 24 unique attempts. Recovery returned no recovered or unresolved work; final status remained completed. Both databases contain 24 requests, attempts, receipts and observations, with matching receipt/attempt identities. Every documented command exited successfully.

## Report artifacts: passed; browser inspection pending

The independent static review found no confirmed defect. Both reports retain the full denominator, separate invalid outcomes from valid disagreement, and contain all seven filter selectors with matching section attributes and options. Each includes 4 condition articles, 12 pass sections, 12 supporting-case blocks and 6 inline charts. Empty measurements display `unavailable`. Scripts are inline and require no external resources.

Review verdict: **APPROVE for static report inspection**. **RESIDUAL:** rendered readability, filter clicks and opening case details remain unverified because the browser tool denied local-file access. No alternate access route was used. Static verification does not close the browser interaction gate.

The private evidence archive is `private-data/operator-check-20260928/`, ignored by Git. It contains command output, the verification summary, both run directories and a SHA-256 manifest. Original absolute paths remain in saved configs to preserve their bindings; the copies are evidence, not portable run configurations.

Report SHA-256 values:

- Candidate: `e165a0e653ee333579175bf0cb35ed742b5fe4c7a276b3e1d30b62cf00f18613`
- Product: `dc369239560b50a6c512a7f379162a37100a31c5aceed60871387cce36e0c1d1`

Independent operator execution is verified. Browser inspection and live verification of the updated adapter identity path remain separate, pending release checks.

## User-supplied interaction evidence

The user subsequently supplied eight copied report views, four for each fixture. Their contents demonstrate these states:

| Report | All prompts/passes | Selected prompt | Selected prompt and pass | Expanded cases |
| --- | --- | --- | --- | --- |
| Product | 12 pass sections | baseline: 6 sections | baseline/pass 1: 2 sections | 3 invalid case rows |
| Candidate | 12 pass sections | explicit: 6 sections | explicit/pass 2: 2 sections | 3 valid-but-disagreeing case rows |

Every view retains the whole-experiment totals: 36 positions, 18 valid, 18 invalid, zero missing. Provenance hashes remain identical within each four-view sequence. The expanded rows include input text, references, predictions and outcome labels. This verifies the demonstrated filtering and expansion through user-supplied browser text, not direct agent browser observation. It does not prove visual readability, reset-to-All behavior, collapse behavior or interactions with the other five selectors.

Exact supplied text and SHA-256 digests are archived privately under `private-data/operator-check-20260928/user-pasted-views/`. Layout inspection and live verification of the updated adapter identity path remain pending. The earlier browser limitation describes the initial agent inspection, before these additional user-supplied views.

## User visual confirmation

The user confirmed both reports looked good and were readable, while explicitly distinguishing that result from an absence of UI/UX improvement opportunities. Combined with the supplied filtered and expanded report text, this provides user-observed layout and interaction evidence. The agent did not directly inspect rendered pixels. Reset/collapse and the remaining selector combinations were not separately demonstrated. Live verification of the updated adapter identity path is still pending.
