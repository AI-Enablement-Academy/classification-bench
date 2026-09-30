# Independent operator recheck, 2026-09-30

The documented offline workflow passed on commit `2d7de1fa119bd2d64583a0bbbad51912fdb894d3`. This is independent subagent reproduction, not human inspection. No confirmed workflow defect was found. Latest rendered report and keyboard acceptance remain pending.

## Scope and environment

- Checkout: `/Users/adamkovacs/Documents/codebuild/classification-bench`.
- Python: `3.14.6`; macOS: `26.6`, build `25G5028f`.
- Browser/version: not used or measured. The existing local-report browser policy denial prohibits browser, Computer Use, local-server and Playwright workarounds for this check.
- Evidence: [`private-data/release-acceptance-20260930/operator/recheck-164250/`](../private-data/release-acceptance-20260930/operator/recheck-164250/), ignored private data. The directory was freshly created with mode `0700`; previous evidence was preserved.
- Sources: [runner guide](RUNNER.md), [second-operator procedure](OPERATOR_CHECK.md), [custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md), and [project instructions](../AGENTS.md). The assigned goal was `/Users/adamkovacs/.codex/attachments/5825dfa2-83c2-4a41-b14b-821cd774eccd/goal-objective.md`.
- All adapters were synthetic, with `authorization_file: null` and `currency: SYN`. No provider/catalog/TLS calls, model inference, credential access, `.env` access, live authorization execution, or candidate-experience changes occurred. This is software acceptance evidence, not model performance evidence.

## Observed results

| Task | Planned requests | Completed requests | Valid / invalid requests | Planned positions | Valid / invalid / missing positions | All-field exact |
| --- | ---: | ---: | --- | ---: | --- | --- |
| candidate | 24 | 24 | 12 / 12 | 36 | 18 / 18 / 0 | 0/36 |
| product | 24 | 24 | 12 / 12 | 36 | 18 / 18 / 0 | 6/36 |
| custom | 16 | 16 | 8 / 8 | 24 | 12 / 12 / 0 | 4/24 |

Each preview listed the exact request IDs, input membership, prompt, repeat and batch. All routes were `synthetic:offline`, no request was blocked, and the largest request reservation was `1 SYN`. Total reservation bounds were `24 SYN`, `24 SYN` and `16 SYN`; these are planning bounds, not observed charges.

The request counts differ from classification positions because batches contain up to two records. Each task had two configurations and two prompts; the demos used three repeats, and the custom task used two. Every pass retained three positions, including deliberately invalid outputs.

The custom task files came from the walkthrough's first shell block. Only its temporary-directory setup changed: the existing fresh `custom` evidence directory supplied `run_dir`. Task, inputs, labels, prompts, configuration controls and synthetic cap `16` were unchanged.

### Restart, recovery and immutable outputs

For all three tasks, `status-before.json` and `status-after.json` were equal. The second `run` completed with the same saved request set. Artifact paths and SHA-256 values were identical before and after restart/recovery: 96 files for candidate, 96 for product and 64 for custom. The final SQLite counts were 24/24/16 respectively in each of `requests`, `attempts`, `execution_requests`, `verified_response_receipts`, `benchmark_observations` and `benchmark_transports`.

Each recovery result was `{"recovered": [], "status": "recovered", "unresolved": []}`. Active reservations, unknown holds and known synthetic charges were zero; the remaining caps were `1000 SYN`, `1000 SYN` and `16 SYN`. This check verifies restart and recovery of completed synthetic runs. It does not reproduce interruption or uncertain-dispatch recovery.

Repeated `export` and `report` commands targeting their existing outputs all exited `2` with `classification-bench: [Errno 17] File exists: '.../predictions.json'` or `'.../report-recheck.html'`. SHA-256 checks confirmed each existing file was unchanged. These were expected refusals; every other recorded command exited `0`.

### Full denominator and static report inspection

The evaluator's summed pass denominators were exactly 36, 36 and 24. Invalid projections remained in those totals and received no exact-agreement credit. Export files retained all 36/36/24 selected projections.

A separate copy of the custom export omitted the valid `first-label` / `short` / repeat `1` / `ticket-1` record. Offline evaluation still reported 24 positions, with 1 missing and 12 invalid. The saved run, original export and original evaluation were preserved; this projection check does not simulate a transport failure.

Static HTML parsing confirmed the reports contain the same full-denominator summary, comparison search/sort controls, pass filters, Reset filters, case details and unavailable measurement text. Candidate and product each contained 12 pass sections and 48 disclosures; custom contained 8 pass sections and 32 disclosures. Each report contained one inline script and no external script source. This inspection establishes saved markup only; it does not establish readability, rendered charts, filter behavior, sorting, keyboard navigation, focus visibility or narrow-window behavior.

## Exact command record

The following commands ran from the checkout root. `custom-setup.sh` is the archived walkthrough setup with the directory substitution described above. Each `--out` path was fresh except the six deliberate overwrite checks. The [command log](../private-data/release-acceptance-20260930/operator/recheck-164250/command-log.json) records full absolute arguments, exit codes and available stdout/stderr paths; [inspection summary](../private-data/release-acceptance-20260930/operator/recheck-164250/inspection-summary.json) records deterministic counts, output hashes and refusals.

```sh
git rev-parse HEAD
python3 --version
sw_vers
evidence="/Users/adamkovacs/Documents/codebuild/classification-bench/private-data/release-acceptance-20260930/operator/recheck-164250"
python3 -m scripts.offline_demo --task candidate --directory "$evidence"/candidate
python3 -m scripts.offline_demo --task product --directory "$evidence"/product
bash "$evidence"/custom-setup.sh
python3 -m classification_bench plan --task /Users/adamkovacs/Documents/codebuild/classification-bench/examples/candidate/task.json --experiment /Users/adamkovacs/Documents/codebuild/classification-bench/examples/candidate/experiment.json --inputs /Users/adamkovacs/Documents/codebuild/classification-bench/examples/candidate/inputs.json --out "$evidence"/candidate/plan.json
python3 -m classification_bench preview --config "$evidence"/candidate/config.json --out "$evidence"/candidate/preview-recheck.json
python3 -m classification_bench status --config "$evidence"/candidate/config.json --out "$evidence"/candidate/status-before.json
python3 -m classification_bench run --config "$evidence"/candidate/config.json --out "$evidence"/candidate/restart.json
python3 -m classification_bench recover --config "$evidence"/candidate/config.json --out "$evidence"/candidate/recovery.json
python3 -m classification_bench status --config "$evidence"/candidate/config.json --out "$evidence"/candidate/status-after.json
python3 -m classification_bench export --config "$evidence"/candidate/config.json --out "$evidence"/candidate/predictions.json
python3 -m classification_bench evaluate --task /Users/adamkovacs/Documents/codebuild/classification-bench/examples/candidate/task.json --plan "$evidence"/candidate/plan.json --labels examples/candidate/labels.json --predictions "$evidence"/candidate/predictions.json --out "$evidence"/candidate/evaluation.json
python3 -m classification_bench report --config "$evidence"/candidate/config.json --labels examples/candidate/labels.json --out "$evidence"/candidate/report-recheck.html
python3 -m classification_bench plan --task /Users/adamkovacs/Documents/codebuild/classification-bench/examples/product/task.json --experiment /Users/adamkovacs/Documents/codebuild/classification-bench/examples/product/experiment.json --inputs /Users/adamkovacs/Documents/codebuild/classification-bench/examples/product/inputs.json --out "$evidence"/product/plan.json
python3 -m classification_bench preview --config "$evidence"/product/config.json --out "$evidence"/product/preview-recheck.json
python3 -m classification_bench status --config "$evidence"/product/config.json --out "$evidence"/product/status-before.json
python3 -m classification_bench run --config "$evidence"/product/config.json --out "$evidence"/product/restart.json
python3 -m classification_bench recover --config "$evidence"/product/config.json --out "$evidence"/product/recovery.json
python3 -m classification_bench status --config "$evidence"/product/config.json --out "$evidence"/product/status-after.json
python3 -m classification_bench export --config "$evidence"/product/config.json --out "$evidence"/product/predictions.json
python3 -m classification_bench evaluate --task /Users/adamkovacs/Documents/codebuild/classification-bench/examples/product/task.json --plan "$evidence"/product/plan.json --labels examples/product/labels.json --predictions "$evidence"/product/predictions.json --out "$evidence"/product/evaluation.json
python3 -m classification_bench report --config "$evidence"/product/config.json --labels examples/product/labels.json --out "$evidence"/product/report-recheck.html
python3 -m classification_bench plan --task "$evidence"/custom/task.json --experiment "$evidence"/custom/experiment.json --inputs "$evidence"/custom/inputs.json --out "$evidence"/custom/plan.json
python3 -m classification_bench preview --config "$evidence"/custom/config.json --out "$evidence"/custom/preview-recheck.json
python3 -m classification_bench run --config "$evidence"/custom/config.json --out "$evidence"/custom/run-result.json
python3 -m classification_bench status --config "$evidence"/custom/config.json --out "$evidence"/custom/status-before.json
python3 -m classification_bench run --config "$evidence"/custom/config.json --out "$evidence"/custom/restart.json
python3 -m classification_bench recover --config "$evidence"/custom/config.json --out "$evidence"/custom/recovery.json
python3 -m classification_bench status --config "$evidence"/custom/config.json --out "$evidence"/custom/status-after.json
python3 -m classification_bench export --config "$evidence"/custom/config.json --out "$evidence"/custom/predictions.json
python3 -m classification_bench evaluate --task "$evidence"/custom/task.json --plan "$evidence"/custom/plan.json --labels "$evidence"/custom/labels.json --predictions "$evidence"/custom/predictions.json --out "$evidence"/custom/evaluation.json
python3 -m classification_bench report --config "$evidence"/custom/config.json --labels "$evidence"/custom/labels.json --out "$evidence"/custom/report-recheck.html
python3 -m classification_bench export --config "$evidence"/candidate/config.json --out "$evidence"/candidate/predictions.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench report --config "$evidence"/candidate/config.json --out "$evidence"/candidate/report-recheck.html --labels examples/candidate/labels.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench export --config "$evidence"/product/config.json --out "$evidence"/product/predictions.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench report --config "$evidence"/product/config.json --out "$evidence"/product/report-recheck.html --labels examples/product/labels.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench export --config "$evidence"/custom/config.json --out "$evidence"/custom/predictions.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench report --config "$evidence"/custom/config.json --out "$evidence"/custom/report-recheck.html --labels "$evidence"/custom/labels.json  # expected exit 2; existing bytes preserved
python3 -m classification_bench evaluate --task "$evidence"/custom/task.json --plan "$evidence"/custom/plan.json --labels "$evidence"/custom/labels.json --predictions "$evidence"/custom/predictions-one-missing.json --out "$evidence"/custom/evaluation-one-missing.json
```

## Acceptance boundary

The second-operator workflow gate passes for the generic offline CLI and three fictional tasks. The latest visual and interaction gate remains pending under the browser restriction. Provider acceptance, native-provider billing and live isolation were outside this reproduction. The full test suite was not repeated: this task changed documentation and ignored evidence only, and the parent task already verified 186 tests at this checkout.

No production files were changed and no commit was created. The recheck document applies the [anti-slop writing skill](/Users/adamkovacs/.codex/skills/anti-slop/SKILL.md).
