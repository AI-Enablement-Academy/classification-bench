# Controlled comparisons and declared cohorts

The [comparison builder](../classification_bench/report_comparisons.py) describes saved configuration differences on the same task, inputs, prompt and repeat. It enumerates every eligible pair, keeps missing and invalid predictions, and supplies exact evidence links. It does not run inference, change references or infer causal effects.

The report uses this projection alongside [shared findings](../classification_bench/report_findings.py) and the [case explorer](REPORT_EXPLORER.md). The matrix and cohort table support local JavaScript pagination. Offline arithmetic and DOM tests do not establish rendered acceptance; use the [report checks](REPORT_ANALYSIS_CHECK.md) and [presentation checks](REPORT_PRESENTATION_CHECK.md) for that boundary.

## Pair eligibility and declared dimensions

Two runs qualify only when they have different configuration IDs and identical task hashes, ordered case membership, input hashes, prompt IDs, prompt hashes and repeat numbers. A pair from repeat 1 cannot silently combine with repeat 2. Different prompts belong to the separate paired prompt analysis.

Each pair follows canonical plan order: A precedes B. Positive net agreement means B gains more known-reference matches than it loses relative to A. That orientation does not select a winner.

The builder compares requested model names, configuration settings and request batch membership. Configuration IDs identify variants; they are not a requested setting. Operator-declared `model_type` differences remain separate reporting metadata and do not establish model architecture.

| Design label | Counting rule | Interpretation |
| --- | --- | --- |
| `single_varying_dimension` | Exactly one declared requested dimension differs. | Saved settings identify one difference. Undeclared provider/runtime differences may remain. |
| `confounded` | More than one declared requested dimension differs. | The observed change cannot be attributed to one setting. |
| `same_requested_settings` | No declared requested dimension differs. | Different configuration IDs do not establish different inference settings. |

Nested dictionary leaves count separately. Lists, scalar values, empty objects and object-to-scalar changes remain atomic values at their declared path. Adding a nested provider and route exposes two leaf changes. Missing values remain distinct from explicit `null`; booleans remain distinct from numbers. Settings paths use JSON Pointer escaping, so a key named `a/b` appears as `a~1b`.

Request batch changes count as one dimension. Compact pair records retain exact membership hashes and request counts; the original analysis retains each case's request membership. This avoids copying every batch's case IDs into every comparison row.

## References and full denominators

Every pair keeps its full planned case count. Prediction differences use only cases with two valid full vectors; the remaining positions appear as `not_both_valid`. Recovery from unusable to valid, loss from valid to unusable, and positions unusable in both runs remain separate counts.

Reference checks use the same known reference values and reference version in both runs. A missing or invalid prediction earns no matching credit on a known reference. An absent reference does not become an incorrect label. Different reference versions make paired reference agreement unavailable.

All-field reference agreement uses fully referenced cases. Field checks use each field's own known references. `full_denominator_rate_a` and `full_denominator_rate_b` are available only when every planned case has the required reference coverage; otherwise they remain `null`. With no known references, agreement counts, gains, losses and rates remain `null`, while prediction differences and validity remain measurable.

For example, a five-case pair can contain two full references, one route-only reference, one risk-only reference and one case without references. The all-field score denominator is 2; each field can have a denominator of 3. The planned denominator stays 5, and whole-run all-field accuracy remains unavailable. The [hand-calculated tests](../tests/test_report_comparisons.py) cover this case, including invalid predictions retained in losses.

The overview shows the minimum and maximum labeled-subset net difference across every eligible pair, with links to the exact boundary pairs and counts of ties. It reports a range of separate observations. It does not sum pair scores, combine repeated cases into independent samples or recommend the most favorable pair. All eligible pairs remain accessible in the paginated matrix.

## Declared cohort membership

The builder consumes immutable cohort declarations from [report analysis](../classification_bench/report_analysis.py). A declaration names its ID, title, source, origin, selected run IDs, optional case subset and whether it requires one selected run per configuration. The [analysis guide](FINDINGS_ANALYSIS.md) describes the shared saved-evidence boundary; the CLI accepts declarations through `report --cohorts`.

Origins are explicit: `declared_fresh`, `historical`, `imported` or `unspecified`. Repeat numbers, timestamps and model names do not supply an origin. The default all-planned cohort stays `unspecified`.

Each case retains two different denominators: selected runs and distinct configuration IDs. Three selected runs from two configurations create three run positions and two configuration identities. A configuration counts as unusable for that case only when none of its selected runs has a valid answer. `configurations_with_unusable_runs` separately counts configurations with at least one invalid or missing selected outcome, even if another selected run is usable.

The case table distinguishes valid answer differences across configurations from variability within one configuration. It counts known-field disagreements, full-reference disagreements and unusable referenced positions separately. Full-reference error counts remain unavailable when no full reference exists; field counts use their own reference coverage.

The difficult-case flag is the union of cross-configuration disagreement, a valid disagreement with a known reference field, or an unusable selected outcome. These groups overlap. It is a review aid derived from saved evidence, not a claim about intrinsic task difficulty or calibrated uncertainty.

Mixed prompts or repeats remain visible in the cohort's condition scope and cannot isolate configuration settings. Incompatible task/input membership is rejected. Repeated runs do not add configuration votes or create independent samples.

Report filters change which pair rows match the selected run scope. They do not rescore declared cohorts. The cohort panel displays matching run membership against complete declared membership and preserves evidence outside the current filter with an explicit caption. The pair scope control can expose every planned eligible pair without changing its original denominator.

The panel reads the shared filter snapshot on initialization, including filters restored from a URL. A standalone host can respond to `report-filter-request` when it has no controller object. Pagination resets only when eligible run membership changes; repeated snapshots preserve the current page.

## Python API and source identity

```python
from classification_bench.report_comparisons import (
    build_comparative_findings,
    compare_configurations,
    render_comparative_findings,
)

comparative = build_comparative_findings(analysis)
pair = compare_configurations(analysis, run_a, run_b)
html = render_comparative_findings(comparative)
```

`build_comparative_findings` returns schema version 1, the input `analysis_id` and `source_hashes`, its own deterministic `comparisons_id`, compact `pairs`, fixed-membership `cohorts`, bounded `findings`, eligibility inventory and interpretation limits. Findings use the shared finding shape plus exact `supporting_links`.

The matrix stores counters and field coverage for every eligible pair. It does not eagerly store pair-by-case objects or case-ID partitions. `compare_configurations` computes one selected pair's exact gained, lost, stable, unknown-reference and validity case-ID partitions on demand. Reversing A/B reverses directional gains and losses; it preserves case scope.

The narrative count is one comparison overview, when eligible pairs exist, plus one observation per declared cohort. It does not produce one narrative per matrix cell. Pagination limits rendered rows rather than analytical membership. The functions return detached values and leave task, predictions, references and cohort declarations unchanged.

These outputs are private saved-evidence analysis. They do not authorize provider calls, dataset publication or deployment, and do not add timing, monetary or calibration measurements that the source evidence lacks.
