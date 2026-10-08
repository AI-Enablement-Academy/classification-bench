# Generic offline operator acceptance, 2026-10-08

Two fresh fictional tasks completed initialization, import, validation, planning, generic preflight, preview, synthetic execution, recovery, export, evaluation and report generation through the documented CLI. Recruitment used CSV with complete references; an unrelated warehouse task used nested JSONL with partial references. A separate import with no references and an unlabeled evaluation/report also succeeded.

This closes a bounded software-reproduction check. It does not establish live provider serving, actual budget exhaustion, an aggregate cross-run cap, ambiguous-dispatch recovery, model quality or rendered report acceptance. The synthetic transport returned fixed test answers and settled zero charges.

This was a delegated agent operator pass following [task setup](TASK_SETUP.md), [the custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md), [runner operation](RUNNER.md), [formats](FORMATS.md) and [the operator checklist](OPERATOR_CHECK.md). The agent previously contributed setup/evaluation code; this is not blind third-party or human acceptance. No engine/report edits, model-specific controller, provider inference, credential lookup/copying or source-project mutation formed part of this pass.

## Checkout, environment and evidence

The pass began from clean commit `8a4c9c4e8122cc2ad2f5e222704b20815aa775ec`. Python was `3.14.6`; the host was `macOS-26.6-arm64-arm-64bit-Mach-O`. No browser was invoked.

Private evidence lives in [operator-generic-20261008](../private-data/operator-generic-20261008/). It is ignored by Git and available only in this checkout; another clone will not contain it. The [environment record](../private-data/operator-generic-20261008/environment.json), [reconciled audit](../private-data/operator-generic-20261008/acceptance-evidence.json) and [expected rejection transcript](../private-data/operator-generic-20261008/expected-rejections.json) retain the exact paths, hashes, outcomes and commands.

During final inspection, other agents had uncommitted changes in `cli.py`, `report.py`, `report_findings.py` and `RUNNER.md`. Those paths are recorded in the audit. This pass did not edit them. The CLI privacy correction now makes JSON outputs owner-only even without the shell's `umask`; see [its tests](../tests/test_cli_privacy.py). These operator commands used `umask 077` throughout.

At the permission inspection, all 440 existing files were `0600` and all 283 directories were `0700`; none allowed group or other access. The subsequently written audit JSON was independently checked as `0600`. Each of the six HTML reports was `0600`. The audit includes exact report, plan, prediction, evaluation and request-capsule hashes.

## Fresh task definitions

Both tasks supplied stable IDs, two named input fields, two categorical decisions, two prompt variants, a rubric, an SOP, two independently dispatched repeats, batch size two and explicit smoke/full splits. Each matrix had `first-label` and deliberately `invalid-label` synthetic configurations. Only user-authored source/setup/config files changed between tasks.

| Task | Source and decisions | References | Full-run membership |
| --- | --- | --- | --- |
| `operator-fictional-feedback-20261008` | Four CSV feedback records; `interaction_signal` has positive/mixed/negative/needs_review labels, and `review_action` has none/clarify labels. The fictional rubric does not infer hiring suitability or company policy. | Four complete separate CSV references and owner notes. | Three held-out records; the one-record smoke split is separate. |
| `operator-stock-routing-20261008` | Four JSONL records with nested note/bay selectors; `disposition` has release/inspect/hold labels and `urgency` has routine/urgent labels. | One full reference, two partial references and one unlabeled record. Notes remain separate. | All four imported inputs; the one-record smoke is a separate reviewed run and intentionally overlaps this full matrix. |

Recruitment's frozen setup-manifest byte SHA-256 is `4ba8e1e55f5daafe94453970e4eb42b61e7fe508dd69c2f2de9aa471a1564a8a`; warehouse's is `6c274dfc6da229c990043b009a6ce907d6f3c417549fb4bffc816ce831f386da`. All frozen source and derived bytes matched their pre-execution hashes after evaluation/reporting and passed `validate` again.

The reference-free warehouse import omitted the reference source entirely. It retained the same task, input and prompt bytes, generated the same plan as the partial-reference import, and evaluated the existing predictions without further dispatch. Its manifest declared `unlabeled` and created no accuracy-reference file.

## Recorded commands and results

The exact executable command transcripts are retained in six shell files. They contain direct `python3 -m classification_bench` invocations, absolute config/source paths and fresh output names:

| Transcript | CLI calls | Result |
| --- | ---: | --- |
| [01-import.sh](../private-data/operator-generic-20261008/01-import.sh) | 6 | Both `init → import → validate` sequences succeeded. |
| [02-plan-preview.sh](../private-data/operator-generic-20261008/02-plan-preview.sh) | 15 | Five plans, preflights and previews succeeded. Every preflight reported ready with zero dispatches; every preview route was `synthetic:offline`. |
| [03-run-first.sh](../private-data/operator-generic-20261008/03-run-first.sh) | 8 | Five synthetic runs, two status checks and one recovery completed. The intended pause/stop probes completed because charges were zero. |
| [04-amend-restart-export.sh](../private-data/operator-generic-20261008/04-amend-restart-export.sh) | 22 | The same cap amendment applied idempotently; all five restarts, recoveries, status checks and exports succeeded. |
| [05-evaluate-report.sh](../private-data/operator-generic-20261008/05-evaluate-report.sh) | 14 | Five evaluations/reports, an additional unlabeled evaluation/report and both final frozen validations succeeded. |
| [06-unlabeled-import.sh](../private-data/operator-generic-20261008/06-unlabeled-import.sh) | 5 | Reference-free init/import/validate/plan/evaluate succeeded using saved predictions. |

All 70 CLI calls above exited zero. The following generic pattern supplied the full pipeline; exact split paths and configs are in the transcripts:

```sh
umask 077
python3 -m classification_bench init --spec SELECTED_SETUP --directory NEW_REVIEWED
python3 -m classification_bench import --spec REVIEWED_SETUP --directory NEW_FROZEN
python3 -m classification_bench validate --directory FROZEN
python3 -m classification_bench plan --task TASK --experiment EXPERIMENT --inputs INPUTS --out NEW_PLAN
python3 -m classification_bench preflight --config CONFIG --out NEW_PREFLIGHT
python3 -m classification_bench preview --config CONFIG --out NEW_PREVIEW
python3 -m classification_bench run --config CONFIG --out NEW_RUN_RESULT
python3 -m classification_bench status --config CONFIG --out NEW_STATUS
python3 -m classification_bench recover --config CONFIG --out NEW_RECOVERY
python3 -m classification_bench export --config CONFIG --out NEW_PREDICTIONS
python3 -m classification_bench evaluate --task TASK --plan PLAN --labels REFERENCES --predictions PREDICTIONS --out NEW_EVALUATION
python3 -m classification_bench report --config CONFIG --labels REFERENCES --out NEW_REPORT
```

For warehouse partial scoring/reporting, the commands added `--allow-partial-references`. The unlabeled commands omitted `--labels`. Each smoke/full definition used its own directory, database and scope; no previous live scope or budget was opened.

| Synthetic run | Requests / dispatch intents | Planned classification positions | Valid / invalid positions | Terminal state |
| --- | ---: | ---: | ---: | --- |
| Recruitment smoke | 8 / 8 | 8 | 4 / 4 | completed |
| Recruitment full | 16 / 16 | 24 | 12 / 12 | completed |
| Recruitment stop-policy probe | 16 / 16 | 24 | 12 / 12 | completed; no budget exhaustion |
| Warehouse smoke | 8 / 8 | 8 | 4 / 4 | completed |
| Warehouse full | 16 / 16 | 32 | 16 / 16 | completed |
| Total across these separate test runs | 64 / 64 | 96 | 48 / 48 | zero unknown holds |

The stop-policy probe deliberately used a separate synthetic run to inspect exhaustion behavior. It is not a new repeat within the recruitment full experiment, and these totals are workflow counts rather than pooled quality measurements. There were no missing selected predictions in these completed runs.

## Evaluation and reference protection

Recruitment smoke's first-label passes matched 1/1 reference; its invalid passes matched 0/1. Recruitment full's first-label and invalid passes each retained denominator three and matched 0/3. These hand-checked fixed answers test scoring, not recruitment-model performance.

Warehouse full retained denominator four in every pass. All-field whole-run scores remained `null` because only one case had every reference. Each first-label pass matched 1/1 on the explicitly named fully referenced subset; each invalid pass matched 0/1. `disposition` had two known references and one first-label match; `urgency` had two known references and two first-label matches. Invalid passes retained false negatives on those known labels. Unavailable labels created no support or invented errors.

The unlabeled evaluation retained all 32 planned positions and 16 invalid outputs. Its reference hash, all-field accuracy, scored-subset accuracy and per-field scores were `null`. Re-evaluation from the separately frozen unlabeled import produced the identical evaluation JSON and made no inference calls.

The audit verified all 64 persisted request-body and manifest byte hashes. Unique owner-note and unselected-source canaries existed in frozen provenance, but were absent from plans, exported input documents, effective prompts and actual request capsules. Reference/adjudication files were never CLI arguments to planning, preflight, preview or execution. This proves allowlisted material separation for these runs; it does not claim OS process isolation for the synthetic adapter.

## Recovery, amendment and refusal checks

Before restart, the audit recorded every request, attempt, dispatch event, receipt and immutable raw artifact hash. After `run → recover → status → export` and report generation, all five ledgers had the same dispatch/attempt/receipt counts and all 256 raw artifact hashes remained unchanged. Every recovery returned empty `recovered` and `unresolved` lists. No request was dispatched again.

The recruitment smoke's completed scope accepted the documented run-bound amendment from total cap 2 to total cap 8 SYN. Repeating the identical amendment left one amendment event, preserved the original config and did not create dispatches. This establishes idempotent amendment handling on a completed zero-charge run; it does not demonstrate resuming paused work.

Five expected refusal commands exited 2:

| Probe | Observed result |
| --- | --- |
| Re-import into the existing frozen directory | `File exists`; frozen bytes remained unchanged. |
| Export to the existing predictions path | `File exists`; no overwrite occurred. |
| Report to the existing HTML path | `File exists`; no overwrite occurred. |
| Supply partial labels without the opt-in flag | Rejected the incomplete decision vector; no evaluation file was created. |
| Attach the full configuration to the smoke database | `benchmark configuration changed for this database`; no dispatch occurred. |

Exact arguments, stdout, stderr and exit codes are in [expected-rejections.json](../private-data/operator-generic-20261008/expected-rejections.json).

## Report verification boundary

Six private HTML files were produced without editing engine or report code. All 42 inline JavaScript blocks passed `node --check`; all 30 embedded JSON blocks parsed; none referenced an external script. The [audit](../private-data/operator-generic-20261008/acceptance-evidence.json) records exact hashes.

The complete recruitment report hash is `6f32f0101f75f9f965e7bc6d689b2396060f2407016359c32aa08313566e0554`. Warehouse partial and unlabeled report hashes are respectively `3af860d8268409cae3b203a863d62738401d27e43bd2d85b581c844efb5410f5` and `891a757f98c2c41517438260d4003e275c334035b22437e6b86ba6eb0c7a993b`.

No visual, keyboard, filter-interaction, responsive, print or browser-download observation was performed. The [permitted rendered checklist](REPORT_SHARED_SCOPE_CHECK.md) and [presentation checklist](REPORT_PRESENTATION_CHECK.md) remain separate gates.

## Findings and remaining acceptance gaps

The tested generic setup/execution/export/scoring/report path had no confirmed BLOCKING feature failure. Its bounded verdict is **APPROVE**, with these confirmed residuals. This verdict does not close missing goal requirements.

| Classification | One-line reason and follow-up |
| --- | --- |
| RESIDUAL: synthetic budget example | A positive SYN cap bounds active reservations; zero settled charges let every sequential request finish, so the current generic synthetic example cannot demonstrate cumulative pause/stop exhaustion. Document that distinction and retain separate fee/request-cap acceptance. |
| RESIDUAL: generic smoke/full aggregate guidance | Separate run databases/scopes are documented, but there is no documented generic cross-run aggregate-cap configuration; attempting to share a database is rejected. A single-run shared matrix cap does not prove aggregate smoke/full enforcement. |
| RESIDUAL: general preflight discoverability | `preflight --config` works for synthetic tasks, but the main custom-task command sequences omit it; it is discoverable from CLI help and subscription documentation. Add it to the generic walkthrough. |

Required acceptance still includes actual pause/stop exhaustion with charges or request-count consumption, safe recovery from a genuinely ambiguous/interrupted dispatch, an enforceable aggregate experiment cap across the intended scopes/units, authorized live acceptance for required provider routes, blind independent/human operation as applicable, and permitted rendered report/presentation checks. A SYN total cannot be added to USD or subscription request units to establish a monetary budget.

No provider call, account change, credential transfer, dataset upload or publication was authorized or performed by this acceptance pass.
