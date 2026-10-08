# Report downloads and privacy modes

The private [report](../classification_bench/report.py) offers two deliberate download projections: sanitized metrics and indexed decisions, or private inputs, labels and findings. The download button creates a local `.json.gz` file. It makes no upload, provider call or publication request. The [export builder](../classification_bench/report_exports.py) selects fields explicitly; it does not serialize the entire analysis or copy arbitrary provider metadata.

The data-scope selector applies to the downloaded file. The HTML report itself remains private: it includes input text, reference labels and both compressed export payloads. Selecting sanitized data does not sanitize the HTML. Share only the selected sanitized file when that scope is appropriate; dataset publication still requires separate authorization.

## Choose the data scope

Sanitized is the initial selection. It omits input text, raw case/configuration/prompt IDs, model names, task/field/label names, operator narrative and provenance strings. Categorical predictions and references use field positions and numeric label indexes. Stable case hashes let the selected data join across runs, metrics, prompt transitions, pairs and cohorts.

These identifiers are pseudonymous, not anonymous. Their construction binds the task source digest and original case ID; it does not use a secret anonymization key. Source digests, repeated patterns and aggregate results may still be sensitive. Sanitized data is not automatically approved for public release.

Private is an explicit selection. It adds the selected input capsules, valid predictions, available references, task and taxonomy names, configuration/prompt IDs, model names, scoped finding text and declared cohort/scenario provenance. The panel announces that this mode includes inputs and references. Keep the archive and extracted JSON private.

Both modes exclude raw provider responses, invalid raw predictions, arbitrary operation fields, operation reasons, prompt text, configuration settings and opaque receipt/provider payloads. Neither mode reads credential files or exports environment/credential fields from execution metadata. The private projection is also an allowlist. User-supplied input or provenance text can itself be sensitive; its inclusion in the private mode is deliberate, not automatic redaction.

## Included data

| Data | Sanitized projection | Private projection |
| --- | --- | --- |
| Source identity | Analysis ID, field-metrics ID and task/plan/prediction/reference/operation/cohort source hashes | Same source identity |
| Task taxonomy | Field index and label count | Task name, field names and declared labels |
| Runs and cases | Run/request/configuration/prompt hashes, repeat, prediction/reference status, exact-match state, pseudonymous case ID and indexed vectors | Raw case ID, selected input, valid prediction/reference values, configuration ID, prompt ID and model name |
| Coverage and class metrics | Full planned counts, known reference coverage, support, TP/FP/FN, explicit ratio numerators/denominators, confusion, invalid/missing counts and pseudonymous supporting IDs | Same numeric evidence with field/label names and raw supporting IDs |
| Prompt transitions | Run hashes, signed net gain, planned/scored denominators and gained/lost/stable/unknown/unusable case sets | Same measures with raw case IDs |
| Agreement pairs | Every supplied eligible pair, accepted-correct/error/reference-unknown and deferred counts/IDs, acceptance rate and measured cost coverage | Same pair evidence with raw case IDs |
| Cohorts | Pseudonymous cohort ID, selected run/case hashes, planned runs, distinct configurations and disagreement/error/unusable sets | Declared cohort ID, title, origin and source |
| Findings | Finding/run hashes, supporting case hashes and denominator | Kind, title, observation, scope and suggested follow-up |
| Hypothetical sensitivity | Scenario/result/reference/source hashes, changed case hashes, baseline/hypothetical numeric scores and class/confusion tables | Scenario ID, title, provenance, raw changed IDs and named class/field tables |

This is a selected projection, not a backup of all source evidence. Reference-bearing data remains an offline evaluation/report input; it must not be passed to an inference capsule. Original sources and historical evaluations remain unchanged.

Missing references stay unavailable. Invalid and missing predictions remain in the planned denominator and in applicable known-reference scoring denominators. The [field metrics](../classification_bench/report_metrics.py) distinguish undefined precision/recall/F1 from zero performance; the existing evaluator macro convention is recorded separately. [Hypothetical sensitivity](REFERENCE_SENSITIVITY.md) uses its disclosed evaluator convention and never applies an alternative to the saved key.

Monetary totals retain integer micro-USD values and observed-request coverage. Unknown charges are null. Subscription invocations and unresolved request holds remain request counts, not dollar charges. Synthetic observations are identified as excluded from actual provider cost. Large integers remain exact JSON bytes through compression and download; consumers must preserve those integers when parsing them.

## Hashes and compressed files

Downloads use names such as `benchmark-<analysis-prefix>-sanitized.json.gz` and `benchmark-<analysis-prefix>-private.json.gz`. A local archive tool can extract the UTF-8 JSON. Gzip is compression, not encryption; the browser and extraction tool control the resulting file permissions.

The panel's **Exact download byte hashes** disclosure reports two different artifacts:

- **Download SHA-256 and compressed byte count:** the exact `.json.gz` bytes produced by the button.
- **JSON SHA-256 and uncompressed UTF-8 byte count:** the exact decompressed JSON, including its final newline.

The JSON uses sorted keys, explicit nulls, UTF-8 text and a fixed formatting convention. Gzip uses a zero timestamp, so repeated rendering with the same implementation produces the same archive bytes. The button decodes embedded base64 into a binary blob; it does not parse and reserialize the payload in JavaScript. This preserves integers beyond JavaScript's exact-number range.

Logical `source_hashes` inside the JSON are separate canonical-JSON digests of the original analysis inputs. They are not the archive hash or the formatted export hash. Omitted references have a null source hash. Recomputing a logical source hash requires the corresponding original source; the allowlisted export intentionally omits some source content. Hashes establish byte identity and source bindings, not authenticity signatures or reference correctness.

Derived findings and field metrics must identify the same analysis. Sensitivity must match the task, plan, saved prediction and saved reference hashes. The builder rejects mismatched joins rather than mixing evaluations from different sources.

## Generate and verify

Generate the private report through the [CLI](../classification_bench/cli.py) and its verified saved-evidence snapshot:

```sh
python3 -m classification_bench report \
  --config private-data/config.json \
  --labels private-data/labels.json \
  --out private-data/report.html
```

Omit `--labels` for an unlabeled report. Add `--allow-partial-references` when supplying an incomplete reference file. Optional `--scenarios` and `--cohorts` files provide declared hypothetical alternatives and run cohorts. Open the report locally, inspect the scope notice, choose a mode and press **Download compressed JSON**. The report command creates mode-0600 HTML and refuses overwrite; browser downloads have their own storage behavior.

Python callers can reuse `build_report_exports(analysis, findings=..., field_metrics=..., sensitivity=...)`. It returns canonical payload strings, filenames, exact UTF-8 byte counts and SHA-256 hashes for both modes. `render_downloads(exports)` embeds the compressed browser download controls. Both functions preserve their caller's source objects.

[Export tests](../tests/test_report_exports.py) check privacy canaries, joinable pseudonymous IDs, mismatched source rejection, integer precision, deterministic payloads, exact gzip/JSON hashes, local download scope selection and no source mutation. [Workflow tests](../tests/test_report_workflow.py) cover CLI scenarios/cohorts, private output permissions, no overwrite and integration with report evidence. Run the focused checks with:

```sh
python3 -m unittest tests.test_report_exports tests.test_report_workflow -v
```

These are offline source and DOM checks. They do not establish rendered layout, visible keyboard focus, browser download policy, mobile behavior or print quality. The [latest shared-report fixtures](REPORT_PRESENTATION_CHECK.md) provide exact artifacts and download inspection steps. The exact report and presentation still need the [rendered acceptance checklist](REPORT_UX_CHECK.md); the [recorded Browser restriction](BROWSER_ACCEPTANCE_20261001.md) remains a separate limitation.
