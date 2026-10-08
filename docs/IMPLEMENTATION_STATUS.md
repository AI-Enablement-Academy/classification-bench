# Implementation status: 2026-10-08

## Explicit credit policy and fictional Pages preview

The runner now supports an explicit version-2 paid-credit policy. It records
truthful enabled/unknown account state separately from human approval, retains
private evidence, binds the exact run/configuration and shared REQ scope cap,
and verifies receipt policy against immutable admission history. Legacy v1
assertions keep their original bytes and default-deny behavior. Standing
permission persists across fresh account observations. An explicit denial
revokes it; stale approval cannot be restored by a later observation.
See [subscription assertions](SUBSCRIPTION_ASSERTIONS.md).

Independent review found and repaired a BLOCKING stale-approval resurrection
bug. Final verdict: **APPROVE**, no remaining BLOCKING findings. **RESIDUAL:**
REQ limits cannot guarantee the USD 10 ceiling for native subscription credits;
the [exact two-request monetary exception](CLI_CREDIT_SMOKE_PLAN_20261008.md)
still awaits a user answer. Credit-use permission itself is already granted.
No new provider inference, credential copy, account change or top-up occurred.

Final full suite: **697 tests passed in 121.247 seconds, no skips**. The
implementation's 90 focused checks and independent reviewer's 85 checks passed.
A fresh wheel/venv completed both fictional managed workflows (28 CLI calls)
and the CSV guide (11 Python invocations) from an unrelated working directory.
All 40 installed package source hashes matched. [Private verification](../private-data/credit-preview-20261008/verification.json)
retains logs, digests and exact source identities.

The [public fictional preview](https://ai-enablement-academy.github.io/classification-bench-preview/)
is deployed from a separate static repository; the harness repository remains
private. Its builder, recursive privacy audit and 13 focused tests passed
independent review. The 19-file bundle contains only newly invented data,
including 36 embedded downloads and both workflow phases. Every served file
matches the audited bytes. [Publication and inspection instructions](PUBLIC_PREVIEW.md)
explain the exact fixtures and verification boundary.

Implementation checkpoint `cc179da` was pushed and verified against the
private remote with a clean worktree. [Delivery evidence](../private-data/credit-preview-20261008/delivery-verification.json)
records the exact commit. [Shared memory verification](../private-data/credit-preview-20261008/memory-verification.json)
confirms identical decision content in both canonical stores and fresh isolated
retrieval of the global marker, new decision and ReasoningBank pattern 499.

**The goal remains incomplete.** Native Claude Code/Codex live acceptance and
exact rendered acceptance are pending. HTTP delivery, source checks and Node
control tests do not establish visual, keyboard, print or native-download
acceptance. The recorded browser restriction remains in force.


## Haiku controls and historical reads: verified follow-up

The subscription adapter now supports the documented Haiku 5.5 effort levels
with Claude Code 2.1.293 or later. Capability/version checks run before live
preflight and dispatch. Historical construction, request reproduction, saved
status, exports, reports and completed recovery remain readable; unknown model
capabilities cannot start new execution. The paid-usage guard is unchanged.
See [the capability contract](SUBSCRIPTION_RUNNER.md).

Independent review caught and resolved a historical-read regression in the
initial correction. The revised code received **APPROVE**, with no remaining
scoped code findings. The older [Claude smoke packet](CLAUDE_ACCEPTANCE_PLAN_20261008.md)
now qualifies its preparation-version limitation without changing its private
candidate files or proposed one-request Haiku 4.5 scope.

Final full suite: **663 tests passed in 80.231 seconds, no skips**, exit 0.
A fresh wheel and isolated virtual environment again completed both fictional
managed workflows (28 CLI calls) and the CSV guide (11 Python invocations) from
an unrelated working directory. All 40 installed package source hashes matched
the revised checkout. [Private verification](../private-data/subscription-controls-20261008/verification.json)
retains the final test log digest and installed-operator evidence.

Implementation checkpoint `b5f798d` was pushed and verified against the private
remote with a clean worktree. [Shared memory verification](../private-data/subscription-controls-20261008/memory-verification.json)
confirms the new decision in both canonical stores and fresh retrieval of that
decision, the global marker and ReasoningBank pattern 498.

The [expanded release audit](RELEASE_ACCEPTANCE_AUDIT.md) now covers all nine
goal sections. Claude/Codex live acceptance and exact rendered report acceptance
remain pending. No provider inference or account change occurred in this follow-up.


## Evaluation provenance, deeper findings and current OpenRouter acceptance

New [evaluations](EVALUATION_PROVENANCE.md) bind scoring algorithm/source identity
to their inputs. New schema-2 workflows freeze that evaluator; historical reads
remain available, while scoring with a changed frozen evaluator fails explicitly.
Reports and allowlisted downloads disclose current and frozen provenance.

Shared findings now include per-class support, precision/recall/F1, all tied
lowest supported recall classes, and compatible quality/cost/token/timing
comparisons. Partial coverage, unknown charges, unresolved holds, synthetic
measurements, tokenizer differences and provider attribution constrain which
comparisons appear. Missing/invalid predictions retain their denominators.
Independent provenance, export, fixture and operational reviews returned
**APPROVE**, with no remaining confirmed BLOCKING or RESIDUAL findings in those
scopes. Two imported provider-attribution residuals were repaired and retested.

Final `python3 -m unittest discover -s tests -v`: **653 tests pass in 85.974
seconds, no skips**, exit 0 (`/tmp/classification-release-final-20261008.log`).
A newly built wheel installed in a fresh isolated virtual environment passed
28 managed-workflow CLI commands across both fictional examples, then all 11
Python invocations in the CSV setup/import/evaluation guide. All 40 installed
package source hashes matched the checkout. This verifies the recorded host
and existing build prerequisites, not every platform.

The [current OpenRouter workflow smoke](WORKFLOW_LIVE_ACCEPTANCE_20261008.md)
completed one valid response for 60 microUSD, within the existing USD 10 project
authority. Recovery made zero dispatches. A separate read-only metadata recheck
confirmed the canonical model/provider after an initial saved 404; original
telemetry remains unchanged. Project known charges are 373 microUSD, old holds
remain 559,151 microUSD, and retained allocations total USD 3.80.

Ten exact private reports under `private-data/report-release-20261008-v1/`
passed 107 JavaScript syntax and 81 JSON parsing checks. `verification.json`
binds all-state fictional fixtures; `inspection.json` also binds both example
workflow reports and the current live workflow report.
`installed-operator-verification.json` retains the fresh installation evidence.
These are offline/source checks, not rendered acceptance. Follow the updated
[operator checklist](REPORT_UX_CHECK.md).

**The goal remains incomplete.** [Claude Code/Codex readiness](SUBSCRIPTION_READINESS_20261008.md)
still lacks the required paid-fallback conditions for live acceptance. Exact
rendered visual, keyboard, responsive and interaction acceptance remains open
under the recorded tool-policy boundary. Other native providers retain their
separate statuses. The [requirement audit](GOAL_AUDIT_20261008.md) distinguishes
these acceptance gates from the implementation gaps resolved by this increment.
Public release remains after completion, final license choice and release audit.

## Frozen smoke/full workflow and model declarations

[One workflow specification](WORKFLOW.md) now freezes source inputs, smoke/full selections and repeats, separate USD/REQ/SYN aggregate and phase caps, exhaustion policy and shared provider/concurrency controls. Preparation creates no execution database, credentials or live authorization. Selected-phase execution verifies separate exact approval before deriving child authorization records; the shared scheduler preserves independent accounting, account guards, blocked causes and ambiguous holds.

Combined reports verify exact group coverage against each frozen phase plan under one runner lock. References are opened offline and validated against the complete frozen input source before projection. Whole-workflow planned/outcome counts include every scheduled repetition, while analysis, accuracy and comparisons remain scoped to the selected phase. Portable local links retain phase plus detailed selection; standalone phase downloads retain their own workflow/phase provenance.

[Explicit model metadata](MODEL_METADATA.md) separates family, declared purpose and sourced training lineage. Unknowns stay explicit, operator verification is labeled as a declaration, and no architecture or causal conclusions are inferred from model names. Metadata enters plan identity and allowlisted report outputs, while strict execution adapters receive only their supported controls. Omitted metadata retains historical request identities.

Final `python3 -m unittest discover -s tests -v`: **624 tests pass in 98.014 seconds, no skips**, exit 0 (`/tmp/classification-workflow-final-20261008.log`). Independent scoped reviews returned **APPROVE** after the reproduced blockers were fixed. A fresh installed package passed 28 CLI commands across both fictional examples; its final source hashes matched the repository. Two final private combined reports passed all 34 JavaScript and 26 JSON script checks. The seven new DOM tests explicitly disclose their iframe/history/download harness limits.

Verification and the remaining acceptance gates are recorded in [workflow acceptance](WORKFLOW_ACCEPTANCE_20261008.md). The repository stays private. Apache-2.0 remains the provisional public-release preference, with MIT an alternative; publication follows completion, license selection and the history/data/redistribution audit.

## Aggregate accounting, account checks and OpenRouter controls

[Aggregate accounting](AGGREGATE_BUDGET.md) now reserves whole smoke/full child caps in one authoritative database, preserves separate allocations/charges/reservations/unknown holds, and propagates committed overruns and execution safety blocks to siblings. Version-2 runner configurations retain logical provider IDs while using run-qualified SQLite identities, so overlapping smoke/full inputs do not collide. The aggregate CLI supports creation, status during an active run and exact-specification-bound cap amendments. Parent blocks and freezes remain visible before child allocation and do not consume pause/stop controls.

[Subscription assertion renewal](SUBSCRIPTION_ASSERTIONS.md) appends dated operator evidence without changing frozen inputs, configuration or request identity. Preflight reads current verified history without creating state; admission checks the exact selected revision in the same transaction as reservation and dispatch intent. Claude Code/Codex require this account guard separately from generic REQ accounting. Renewal does not clear a safety block, stop control or unresolved hold and does not independently verify provider billing settings.

[OpenRouter discovery and reasoning controls](OPENROUTER.md) retain public catalog/model/endpoint evidence, canonical controls, documented combined completion bounds and conservative supported tier/cache prices. An explicit fresh operator plugin-policy assertion is a separate prerequisite. It is conditional evidence, not independent account verification. Legacy completed results remain readable; missing model identity or an active/default reasoning configuration without a documented bound cannot authorize live preflight or direct dispatch. Captured omission of reasoning metadata follows the official non-reasoning contract; explicit null remains malformed.

Independent aggregate/CLI, runtime/guard, parent-block/freeze and OpenRouter reviews returned **APPROVE** after the confirmed blockers were repaired. Reviews exercised actual CLI subprocesses, a runner-held lock, real-process ledger races, an offline runner overrun with saved receipts, revision races and frozen historical response evidence. No provider inference, credential copying, account-setting change or source-project mutation occurred. Public model reads and private read-only account observations are readiness evidence only.

Final `python3 -m unittest discover -s tests -v`: **559 tests pass in 101.531 seconds, no skips**, exit 0 (`/tmp/classification-managed-verified.log`). The final independent OpenRouter subset passed 60 tests; the aggregate/models CLI and private-output subset passed 23. The historical compatibility fixture preserves captured original request/snapshot hashes without requiring Git history at test runtime. `git diff --check` passed.

Two **RESIDUAL** limitations remain documented: a proven local guard expiry after durable intent uses the conservative unknown-outcome path and retains invocation capacity; pending historical raw recovery across changed implementation hashes requires the original verified parser build, preserving its evidence/reservation without replay. Neither permits extra dispatch or silently releases exposure.

At this earlier checkpoint, automatic phase selection, mixed-unit scheduling, combined reports and distinct model metadata were pending; the workflow checkpoint above supersedes those implementation gaps. The expanded goal remains active. Current-route live acceptance, clean-install independent operation and exact rendered report/presentation acceptance remain separate gates. The repository remains private; the Apache-2.0/MIT public-release milestone follows completion and the release audit.

## Repeat analysis and operator reproduction, 2026-10-08

[Repeat analysis](REPEAT_ANALYSIS.md) now presents all-field/per-field flips, comparable and excluded denominators, original case reasons, whole-repeat agreement/validity ranges and exact A/B evidence. Historical/imported/replay/declared-fresh sources retain their scope and do not establish fresh dispatch. Report and presentation use the same source-bound findings. Optional `report --repeat-origins` declarations affect offline reporting only.

Independent repeat/integration review returned **APPROVE**, with no remaining confirmed BLOCKING or RESIDUAL findings. The reviewer separately verified a 180-position, 40-pair fixture, the real `--repeat-origins` CLI path and generated-report DOM navigation without changing dispatch counts. The final `python3 -m unittest discover -s tests -v` run passed **446 tests in 66.070 seconds, no skips**, exit 0 (`/tmp/classification-repeat-final.log`). Nine fresh [inspection artifacts](REPORT_REPEAT_CHECK.md) passed 72 JavaScript syntax checks, 54 JSON parses, mode-0600 checks and source/artifact hashing. Generation denied socket connections. These are offline fixtures, not provider-performance or rendered-acceptance evidence.

The [generic operator pass](GENERIC_OPERATOR_ACCEPTANCE_20261008.md) completed two unrelated tasks through the documented CLI, preserving 64 one-time synthetic dispatches and all 256 raw artifact hashes across restart/recovery. It does not prove cumulative exhaustion: synthetic charges settle at zero. Documentation now explains that boundary and includes generic preflight commands. [The execution audit](EXECUTION_GAP_AUDIT_20261008.md) identifies aggregate budgets, mixed-unit phase orchestration, account-guard renewal and OpenRouter controls/discovery as remaining implementation work. Current live-route and exact rendered gates remain pending.

The separate private-output checkpoint `4d02424` protects every CLI JSON file with exclusive mode-0600 creation. Independent privacy review returned APPROVE; stdout redirection and historical output permissions remain explicit limits. No provider inference, credential copy or source-project mutation occurred in this increment. Public release remains a post-completion milestone with an unsettled license choice.

## Shared report scope, case search and controlled comparisons, 2026-10-08

[Shared filters](REPORT_FILTERS.md) now synchronize requested model/group/provider, execution route, output interface, reasoning, prompt, repeat, lifecycle and API route across report controls and views. Matching selects whole runs, preserves full condition metrics and discloses partial scope. [Case search](REPORT_CASE_SEARCH.md) retains selected evidence, planned denominators and local URL state. Ordinary heading/evidence links preserve the rest of that state.

[Controlled comparisons](CONTROLLED_COMPARISONS.md) enumerate eligible configuration pairs with the same task, ordered input, prompt and repeat. They disclose changed settings, confounding, known-reference coverage and invalid/missing outcomes, without causal or independent-sample claims. Declared cohort views separate run positions from distinct configurations, retain unusable outcomes and distinguish cross-configuration disagreement from within-configuration variation. Shared report and presentation findings link exact range boundaries and cases.

Independent review identified and corrected invalid-adapter category selection, navigation that dropped filter state, and initial comparison scope on URL reload. Final `python3 -m unittest discover -s tests -v`: **430 tests pass in 69.747 seconds, no skips**, exit 0 (`/tmp/classification-shared-final-20261008.log`). Independent reviews returned APPROVE with no remaining confirmed BLOCKING or RESIDUAL findings in their scopes. Eight fresh [inspection artifacts](REPORT_SHARED_SCOPE_CHECK.md) passed all 56 JavaScript and 40 JSON script checks, source hashing and mode-0600 verification, with network connections forbidden during generation. No provider call, credential copying or source-project mutation occurred. Operator/live route acceptance and rendered report/presentation verification remain required; this increment does not complete the full goal.

## Shared analysis and presentation, 2026-10-08

The report now shares deterministic findings with an eleven-slide [presentation](PRESENTATION.md), [hypothetical reference sensitivity](REFERENCE_SENSITIVITY.md), full class metrics and [allowlisted downloads](REPORT_EXPORTS.md). Class tables expose support, TP/FP/FN, precision, recall, F1, confusion and missing/invalid outcomes, with coverage and undefined ratios disclosed. Sensitivity compares explicit operator alternatives against unchanged saved predictions and references. Downloads offer pseudonymous and private JSON archives with exact byte hashes; neither mode includes opaque provider output.

Presentation controls preserve exact run/case selections, expose every finding and return to supporting evidence. Keyboard, focus, reduced-motion, print and no-JavaScript behavior have offline coverage. These checks do not establish rendered typography, layout or recruitment-level visual parity. The [inspection record](REPORT_PRESENTATION_CHECK.md) names fresh fictional fixtures and the outstanding visual gate.

The final full offline suite passed 388 tests in 38.998 seconds without skips (exit 0; `/tmp/classification-presentation-verified-20261008.log`). Independent sensitivity, presentation and export/CLI reviews returned APPROVE. Review corrected sensitivity output permissions to 0600 with exclusive creation. No inference, credential copying or source-project mutation occurred.

The broader goal remains active: synchronized report-wide filters, case search, richer controlled comparisons and cohort presentation, operator/live route acceptance, and exact-artifact rendered verification remain required. Deep analysis and visual quality apply to every user-defined task, not only the recruitment example.

## Optional references and evidence-linked analysis, 2026-10-08

The evaluator and CLI now support absent references and explicitly opted-in partial references. Schema 2 separates reference coverage, known-field/subset scores and full planned output counts; whole-run accuracy remains unavailable with incomplete references. Complete-reference schema 1 outputs retain their prior canonical bytes. An independent review compared 100 generated complete evaluations with the previous evaluator and checked 1,824 partial-reference support/FN calculations without finding a discrepancy.

The report integrates a generic run/case explorer, exact A/B field/status differences, local fragment selection URLs, paired prompt gains/losses, all eligible agreement pairs and cost/source disclosure. Paginated pair tables retain all results and do not rebuild on case-only changes; a 60-run/1,770-pair fixture exercises navigation. Monetary values retain exact decimal units in the browser. [Deterministic findings](FINDINGS_ANALYSIS.md) explain coverage, field errors/class support, prompt effects, repeats, cost coverage and the all-pairs acceptance range, with exact supporting links and interpretation limits.

Final verification: `python3 -m unittest discover -s tests -v` passed **338 tests in 31.237 seconds, no skips**, exit 0; log `/tmp/classification-bench-analysis-verified-20261008.log`. Independent core/findings and report/CLI reviews returned **APPROVE**, with no remaining confirmed BLOCKING or RESIDUAL findings in those review scopes. Review resolved eager pair rendering, source-alias mutation and a legacy synthetic-unit regression. Six [private working fixtures](REPORT_ANALYSIS_CHECK.md) were generated with network connections forbidden; embedded JavaScript/JSON syntax, source hashes and mode 0600 were verified. These checks are not rendered acceptance.

No inference, credential copying or source-project mutation occurred. The expanded goal remains incomplete: presentation, reference sensitivity, synchronized report-wide filtering, richer controlled cross-configuration analysis, full metric presentation, operator/live route acceptance and rendered visual-quality gates still require work. The user's requirement for recruitment-level analytical depth and visual quality is now explicit in [the goal](NEXT_TASK_GOAL.md).

## Generic task and subscription foundation, 2026-10-08

The [expanded goal](NEXT_TASK_GOAL.md) is active. Its [source-pinned parity matrix](FEATURE_PARITY.md) covers 59 requirements against candidate-experience-benchmark commit `6243eb3`. The earlier visual-only completion scope is superseded.

Implemented this increment: private JSON/JSONL/CSV task initialization/import/validation with frozen source bytes and separated references; Claude Code/Codex runtime adapters; read-only preflight; request-count accounting with unknown dollar cost; and persistent scope admission blocks for observed quota, paid-overage or isolation failures. See [task setup](TASK_SETUP.md) and [subscription operation](SUBSCRIPTION_RUNNER.md). Two unrelated imported tasks completed synthetic run/export/evaluation, and the documented operator example ran successfully. Partial and absent references are imported honestly, but corresponding evaluation/report support remains pending.

The final command `python3 -m unittest discover -s tests -v` passed **272 tests in 26.104 seconds, no skips**, exit 0. Independent bounded reviews returned **APPROVE** after correcting interrupted CLI output classification. New coverage includes real SQLite admission/block races, real macOS reference/symlink/environment probes, both CLI matrix routes with fake transports, no-dispatch preflight, quota/overage halts, and recovery without duplicate dispatch. The full log was inspected at `/tmp/classification-bench-foundation-final-20261008.log`.

Read-only installed CLI authentication checks succeeded; no model inference was dispatched. These checks do not establish model availability, actual extra-usage-off status, live acceptance, rendered report acceptance or full feature parity. The next increment is optional/partial-reference evaluation, followed by the report analyses and interactions listed in the parity matrix. Existing provider evidence and budgets were preserved.

## Earlier release evidence

The first runner and report are implemented and offline verified. The completed, separately authorized product smoke verified the OpenRouter adapter with three valid responses and independently checked delayed identity metadata; see [live identity results](LIVE_IDENTITY_SMOKE_RESULT.md). The release is not complete: updated report visual/keyboard verification remains pending. The user confirmed report readability and supplied filtering/expansion evidence; independent subagent operator reproduction passed; see [operator results](OPERATOR_CHECK_RESULT.md). The repository is private; the active candidate-experience benchmark was not edited or rerun.

## Model groups and comparison plot, 2026-10-02

The report now has explicit operator-declared General LLM, Fine-tuned LLM and Classification / decision groups, plus Unspecified for omitted metadata. These reporting groups are independent of adapter categories and do not certify architecture or training history. Group counts cover every planned configuration-prompt condition; both rails compose with existing filters and reset together. Full experiment totals stay fixed. The [format](FORMATS.md) freezes `model_type` into plan/request identities. The runner removes only this reporting metadata before calling strict provider adapters, preserving their controls and enrolled adapter/runtime source bytes.

The [comparison plot](REPORT_EXPLORER.md) shows full-denominator exact agreement against mean measured client request duration. Point links and visible value labels include measurement coverage. Axes stay fixed across filtering; synthetic timing is excluded and unavailable measurements are counted. The plot does not establish pure inference time, calibration or a model ranking.

The final `python3 -m unittest discover -s tests -v` run passed **203 tests in 55.050 seconds, with no skips**. Independent review returned **APPROVE**, with no confirmed BLOCKING or RESIDUAL findings. Review exposed and resolved two reachable feature failures: structured JSON metadata crashing the report, and reporting-only `model_type` being rejected by strict provider adapters. Regression checks cover accepted structured metadata, normal typed OpenRouter/Clef previews, retained plan bindings and a complete typed synthetic run. Offline jsdom checks cover type/route composition, reset, selected comparisons, plot filtering and hidden-target reveal; they do not establish rendered layout or focus behavior.

The final reports in `private-data/report-model-types-20261002/final/` were regenerated from saved product, candidate, four native and OpenRouter scopes with network connections forbidden. All **441 source files** across those scopes retained their SHA-256 digests. The saved OpenRouter completion and delayed metadata parsers validated all three responses and their 174 microUSD charges; its 31 archive files and three dispatch events remained unchanged. Native reports retain the 42 valid observations and USD 0.454188 unresolved holds. No additional inference or synthetic matrix execution occurred during regeneration. [Private verification](../private-data/report-model-types-20261002/final/verification.json) binds the report and generator hashes.

The final unexecuted mixed fixture in `private-data/report-model-types-20261002/mixed-unexecuted-v3/` has eight conditions, two in each model group, and all 72 planned positions missing. It exercises declarations and missing-data controls with zero calls; its adapter declarations are not runnable-provider or model-quality evidence. All eight final report files passed embedded JavaScript syntax checks and retain mode 0600; [syntax evidence](../private-data/report-model-types-20261002/final/syntax-check.json) records their hashes. Earlier reports remain preserved. The exact latest rendered acceptance remains pending under [the recorded Browser restriction](BROWSER_ACCEPTANCE_20261001.md); use the [updated checklist](REPORT_UX_CHECK.md).

## Clef and report explorer extension, 2026-10-02

Native [Cloudflare Clef and Clef-Flash](CLEF_DECISIONS.md) now use the Workers AI typed decision routes, a dedicated credential variable, pinned transport, strict REST-envelope parsing and conservative input-price reservations. Public model documentation was fetched successfully as Markdown through the exact preflight helper; generic JSON fetching returned HTTP 403 and was replaced for these sources. At the adapter implementation checkpoint, no Cloudflare inference or credential transfer was performed. Hosted billing, independent returned identity and possible near-context state truncation remain acceptance limits; unknown charges stay held.

Four private offline previews in `private-data/clef-preparation-20261002-verified/` cover smoke and full for each model: 3/18 requests and 6/36 field decisions. Reservation sums are 47,187/283,122 microUSD for Clef and 17,697/106,182 for Flash. Example caps are USD 0.25/1.00 with pause; caps and pause/stop remain operator settings. These original previews explicitly use placeholder account IDs, bind captured public source bytes and create no authorization.

The subsequent [Cloudflare account setup check](CLOUDFLARE_ACCOUNT_SETUP.md) discovered the actual account and successfully read both catalog entries and the Flash schema. Fresh previews in `private-data/clef-account-preparation-20261002/` use that account and preserve the original placeholder files. Initially, the connector denied subscription and token-management reads; today's analytics returned no usage rows, which does not prove remaining free quota. Both smokes fit a fresh daily allowance at conservative context bounds.

After explicit user authorization to inspect the main `/Users/adamkovacs/Documents/codebuild/.env`, its active token was used for setup to create a project-specific token restricted to the discovered account, with Workers AI Read/Write and Billing Read. The project token is active, expires 2026-11-01 13:03:47 UTC, and is saved only in the ignored mode-0600 local `.env`. Existing keys and main environment bytes were preserved. Catalog and subscription reads returned HTTP 200; no Workers Paid subscription was listed. The main environment location is saved in Ruflo and Codex memory, without values.

The user's subsequent USD 10 aggregate inference approval funded the exact prepared Clef/Flash smoke and full scopes, with separate grants totaling USD 2.50. [Live acceptance](CLEF_LIVE_ACCEPTANCE_20261002.md) completed all 42 requests with valid HTTP 200 responses, preserved all planned positions, and verified no added dispatch on recovery/completed restart. Fresh connected-app analytics reports 16,875 input tokens and approximately 252.818182 neurons, matching local token totals and well below the published daily allowance. No quota failure, subscription/payment change or hosted resource was added. Exact dollar charges remain unavailable; USD 0.454188 remains held. Returned selectors are model echoes, not independent identity attestations. Liquid/Solar/Qwen live acceptance and latest report rendering remain separate pending gates.

The [report explorer](REPORT_EXPLORER.md) adds explicit adapter categories, model/provider/route/prompt filtering, two-condition comparison with clear selection controls, native route options before any response, links that reveal hidden evidence, and sticky active section navigation. Whole-experiment totals remain fixed; condition values retain all planned passes. Reduced-motion support disables smooth scrolling and transitions. The candidate-experience presentation was inspected as a read-only source reference, without modifying that project.

The earlier explorer checkpoint passed **194 tests with no skips**, including local jsdom control checks. jsdom executes the generated controls without rendering layout; it does not establish visual, keyboard-focus or narrow-window acceptance. Independent native and report review returned **APPROVE**, after resolving the documentation-fetch, native-filter and hidden-target issues. A pre-existing historical-adapter test now deterministically checks the enrolled-build mismatch and asserts no dispatch, rather than accepting an error that depended on a random artifact shard's existence. Production historical-read behavior was unchanged.

Shared Ruflo retrieval succeeded for `decisions/codebuild/codex-global-memory-20260928`. The verified extension decision and reusable report/native-fetch patterns were saved back; read-only checks found the matching decision content in both canonical databases and the patterns in canonical ReasoningBank. No running session was repointed or restarted.

Fresh product and candidate workflows in `private-data/report-explorer-20261002/` each completed 24 synthetic requests and retained 36 planned positions. Their mode-0600 reports passed JavaScript syntax checks. An additional explicitly unexecuted mixed-roster UI fixture has five configurations and ten comparison rows, with all 90 planned positions missing; it makes no claim about model results. Earlier reports were preserved.

Current read-only export of the saved OpenRouter smoke retained three operations and three predictions with network connections forbidden. All 31 saved file digests stayed unchanged. This extends the historical read check; it does not attest live dispatch of this new build. Latest rendered report acceptance remains pending under the [documented Browser rejection](BROWSER_ACCEPTANCE_20261001.md) and [updated checklist](REPORT_UX_CHECK.md). No workaround was attempted.

## Release audit checkpoint, 2026-09-30

The [requirement-by-requirement audit](RELEASE_ACCEPTANCE_AUDIT.md) separates core release gates from native-provider acceptance. A fresh [independent operator recheck](OPERATOR_RECHECK_20260930.md) reproduced candidate, product and custom workflows at `2d7de1f`: 24/24/16 completed synthetic requests, all 36/36/24 planned positions retained, unchanged artifacts after completed restart/recovery, and six expected overwrite refusals. No provider calls were made. The latest rendered report remains unaccepted.

Saved OpenRouter evidence passes current read-only export and response/metadata parsers: three settled attempts, three dispatch events and USD 0.000174 charged. Adapter and transport source hashes still match; the runtime module changed when native support was added. This establishes historical protocol evidence, not live dispatch of the entire current build. The [native smoke proposals](NATIVE_SMOKE_PLAN.md) require separate billing evidence and authorization.

## Native providers and report extension checkpoint, 2026-09-30

The new native adapters cover Liquid `d1:free`, Upstage `solar-decide` and Alibaba `decision-model-preview`. [Provider contracts](DECISION_PROVIDER_CONTRACTS.md) bind the documented native routes. [Native operation](NATIVE_DECISIONS.md) explains the separate keys, reviewed billing evidence, one-record call topology and unresolved-charge holds. No native provider call has been made; provider acceptance and billing evidence remain pending. [OpenAI Decisions](OPENAI_DECISIONS_STATUS.md) is announced but has no verified public contract in this implementation.

The [report redesign](REPORT_REDESIGN.md) puts model comparisons first, with search, numeric sorting, visible missing/invalid counts and expandable raw usage. Fresh fictional product and candidate workflows each completed 24 synthetic requests and preserved 36 classification positions. Their private HTML and embedded JavaScript syntax were checked. Direct rendered appearance and keyboard behavior remain pending under the local-file browser restriction. Use the [visual checklist](REPORT_UX_CHECK.md).

The final integrated suite passed **186 tests with no skips** on macOS: `python3 -m unittest discover -s tests -v` (47.157 seconds). Native fixtures cover fixed routes, credential separation, typed responses, malformed values, billing bounds and expiry, partial transport, unknown-cost holds, pause/stop, receipt recovery and no replay. Native token counts now reach both operation exports and report summaries. A multi-configuration preflight failure test exposed a scheduler reclaim loop; the scheduler now claims its selected request atomically, preserving default claim order for other callers.

Independent review: **APPROVE**, no confirmed BLOCKING findings remain. **RESIDUAL:** billing/free entitlement remains an operator assertion; a matching source hash does not prove an account rate. **RESIDUAL:** Qwen provider framing near the context limit may reject or truncate input. **RESIDUAL, unconfirmed:** one baseline run hit a macOS process-group EPERM while cleaning up an output-limited child. Ten isolated repeats and the final integrated suite passed; no speculative isolation change was made.

## Previous verification, 2026-09-28

`python3 -m unittest discover -s tests -v` passed **160 tests with no skips** on macOS after running outside the enclosing development sandbox. The original baseline passed 78 tests. The expanded suite includes actual reference/symlink denials and environment scrubbing under both offline and HTTPS-enabled profiles, crash/receipt recovery, atomic shared budgets and cap-amendment races, mocked HTTP errors/partial bodies and identity checks, matrix ordering and process locking, pause/stop/top-up behavior, immutable report snapshots, and subprocess reproduction of both fictional task workflows.

The fictional candidate and product demos each complete 24 synthetic requests, retaining all 36 planned positions. Re-running a completed matrix preserves its request count. Generated reports are private local HTML files with mode 0600. Browser visual inspection was blocked by the browser tool's local-file URL policy; HTML generation, escaping, report calculations, filter code and supporting cases have automated tests, and the user subsequently confirmed visual readability; direct agent rendering remains unverified.

The [custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md) defines an independent fictional support-routing task without either fixture helper. Its documented offline command sequence was executed in a fresh directory: 16 requests, 24 classification positions, 12 deliberately invalid outcomes, zero missing positions and no unresolved recovery work. It produced a private local report. This is command-level reproduction, not human visual verification.

A follow-up audit added nested reasoning/cache token extraction, separately labeled frozen-price estimates, a registered adapter runtime contract, and historical report/export reads that preserve the original source hashes. New dispatch still requires the exact enrolled implementation. See the [acceptance audit](ACCEPTANCE_AUDIT.md) and [adapter runtime contract](ADAPTER_RUNTIME.md).

The final scoped independent code review returned **APPROVE**, with no confirmed BLOCKING findings. RESIDUAL: directly invoking `python3 scripts/prepare_run.py` does not resolve the package in an uninstalled checkout; the documented `python3 -m scripts.prepare_run` command works and was reproduced. This is an optional invocation convenience, not a failure of the supported workflow. RESIDUAL: an older pending run requires its enrolled code version to dispatch or recover after implementation changes; read-only historical reports and exports remain available.

The generic OpenRouter identity update captures the public requested-to-canonical model mapping with raw bytes and a digest, revalidates it before admission, and displays completion and generation model identities separately. Older snapshots without that mapping retain exact matching. The integrated update passed independent review with no confirmed BLOCKING or RESIDUAL findings. Its new identity path now has live evidence from the [authorized product smoke](LIVE_IDENTITY_SMOKE_RESULT.md): three valid responses, matching delayed canonical-model/provider metadata, $0.000174 rounded charges, and no new dispatch on restart.

## Implemented boundaries

- Deterministic task/input/prompt/configuration/repeat/batch planning and preview; reference labels remain outside execution inputs.
- An adapter protocol, one pinned OpenRouter implementation, native Liquid/Solar/Qwen categorical implementations, a public OpenRouter catalog helper and explicit unsupported-configuration rows. Unsupported methods are never silently substituted.
- A shared SQLite ledger, verified raw artifacts, durable transport metadata, process-locked orchestration, per-provider concurrent-request limits and declaration order within configurations.
- Explicit no-retry inference, retained unknown-cost holds, safe never-sent continuation, parsed-outcome recovery after receipt publication, and visible preflight blockers.
- Operator-configurable caps for smoke and full runs, `pause` or `stop` at exhaustion, and conditional run-bound cap increases with immutable history. Increases do not clear holds or above-bound freezes.
- A private report from one locked verified snapshot with full-denominator quality, class errors/support, prompt deltas, repeat ranges/flips, record-level outcomes, route filters, requested versus observed identity, and nullable timing/token/cost measurements.

The live child permits TCP443 and DNS under an OS file boundary. The trusted HTTP adapter pins destinations and rejects redirects; the OS rule is not a domain allowlist. The coordinator has access to local files; reference isolation is enforced for the inference child, not the whole operator account. Local authorization files are operator assertions and do not authenticate a payer.

## Historical smoke and remaining gates

The [authorized three-request smoke](LIVE_SMOKE_RESULT.md) produced one unknown transport attempt and two HTTP 200 responses after a reviewed sandbox correction. At that historical smoke checkpoint, the private, ignored repository `.env` contained only the operator-authorized OpenRouter key. It was not tracked or embedded in code. Two separately archived run definitions preserve the original runtime identity and the never-sent suffix; the suffix cap subtracts the first hold from the approved $0.50 total.

Observed rounded ledger charges are $0.000139, and the unresolved original hold is $0.104963: total accounted exposure $0.105102. A corrected parser recognizes the exact `OpenAI` display name for the pinned `openai` route. Versioned offline re-evaluation still finds both outputs invalid (malformed JSON and an out-of-vocabulary label), preserving the original observations and complete missing/invalid denominators. No retries or new repeats were made.

Authentication, serving, saved raw evidence, charge settlement and private report generation have live evidence. Both initial generation lookups returned 404. Later read-only lookups returned matching response IDs, provider and charges, but a dated model identifier different from the requested alias; the strict identity check rejects that mismatch. The new metadata and timing are archived separately without changing the original reports or ledger. Report readability is user-confirmed, with user-supplied prompt/pass filtering and expansion evidence; independent operator reproduction passed as recorded in [OPERATOR_CHECK_RESULT.md](OPERATOR_CHECK_RESULT.md); [OPERATOR_CHECK.md](OPERATOR_CHECK.md) provides the concrete offline handoff. The first release is not complete. That historical scope is exhausted. A separately approved product smoke subsequently verified the current identity path; see [its result](LIVE_IDENTITY_SMOKE_RESULT.md). No requests remain in the new three-position scope either.

Use [RUNNER.md](RUNNER.md) for complete commands and [LIVE_SMOKE_PLAN.md](LIVE_SMOKE_PLAN.md) for the approval gate. Historical contract documents describe the checkpoint they introduced; this page records the integrated implementation's current status.

A focused [UI/UX review](REPORT_UX_REVIEW.md) identified comparison, filter-feedback, evidence-density and navigation improvements. These improvements are now implemented, with focused offline regression coverage. Fresh reports were generated for both fixtures; the changed UI still needs the [updated visual/interaction check](REPORT_UX_CHECK.md).

The report UX implementation passed independent review with no BLOCKING findings. RESIDUAL: existing pass-level cost charts show recorded sums without per-pass coverage counts; the new comparison table exposes coverage. Both fresh demos completed 24 synthetic requests and preserved all 36 positions. Task, plan, reference and prediction hashes match the earlier reports.
