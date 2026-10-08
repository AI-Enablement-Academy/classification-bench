# Repeat changes and evidence origin

[Repeat analysis](../classification_bench/report_repeats.py) compares every pair of planned repeats within the same frozen configuration and prompt. It keeps the saved case membership, input content and source hashes fixed. A repeated observation of the same case is not a new independent sample, and agreement between outputs does not establish correctness.

A flip requires two valid full categorical predictions. All fields use that validity rule: an output with one invalid field is excluded from every field comparison. The report shows all-field and per-field flip numerators, their comparable denominators and the excluded count against every planned case. A zero comparable denominator gives an unavailable rate, rather than zero. Missing, invalid, refused, unknown and never-sent states remain visible through their original status, lifecycle, parser result and supplied reason.

The hand-counted fixture in [the tests](../tests/test_report_repeats.py) has three planned repeats over four cases. The first pair has two comparable cases, two full-vector flips and two excluded cases. Each of its two fields flips once, giving `1/2`, while the full-vector rate is `2/2`. The report links each changed or excluded case to the exact A/B runs. A valid field inside an invalid full output never enters the comparable subset.

Ranges retain every planned repeat. The example's all-field exact agreement ranges from `1/4` to `2/4`; validity ranges from `2/4` to `3/4`. Filtering a repeat out of the visible scope does not change these saved ranges. Full-denominator agreement is unavailable without complete references. Known-reference ranges remain separate, with their reference coverage. Unlabeled inputs can still show valid-output label changes; they cannot receive invented accuracy scores.

## Reusable API

| Function | Result |
| --- | --- |
| `build_repeat_analysis(analysis, *, origin_declarations=None)` | A deterministic schema-1 projection with runs, condition ranges, every repeat pair, compact case states, source hashes and a content-derived `repeat_analysis_id`. |
| `repeat_case_details(data, pair_id, *, field=None, outcome="all")` | Exact case partitions and reasons on demand. Outcomes are `all`, `changed`, `stable` or `excluded`; a field name selects that field's changes. |
| `build_repeat_findings(data)` | Canonical findings shared by the report and presentation. Each narrative states planned and comparable scope, field changes, exclusions, reference coverage, origin limits and exact boundary evidence. |
| `render_repeat_analysis(data)` | An offline section with scoped styles, bounded tables, condition ranges and selected-pair field/case details. |

The projection stores compact case states once per run. It does not copy inputs, raw invalid predictions or reference labels into each pair. Pair case reasons are derived from those retained states when requested. Source hashes bind the task, plan, selected predictions, references, operations and cohort declarations. They identify supplied content; they do not authenticate receipts or prove fresh dispatch.

Supplemental findings preserve explicit origin sources in both the observation and structured metrics. They link the minimum and maximum measured all-field rates and each field's measured boundaries. These links explain the ranges; they do not select a preferred model or pool overlapping pair counts into accuracy. The suggested follow-up is to inspect changed and unusable cases together and audit dispatch provenance before attributing changes to fresh model variability.

## Planned repeats and declared origins

Distinct planned request identities establish separate planned positions. A repeat index, valid prediction, finished lifecycle state or response pointer does not establish that a fresh request was independently dispatched. With no origin source, the report states that dispatch/import origin is unspecified.

Optional declarations use this shape:

```json
[
  {
    "run_id": "the exact saved run ID",
    "origin": "replay",
    "source": "the operator's immutable replay manifest"
  }
]
```

Accepted origins are `declared_fresh`, `historical`, `imported`, `replay` and `unspecified`. Each run can have one optional whole-run declaration. The source must be nonempty, and duplicate or unknown run IDs are rejected. The separate `origin_declarations_sha256` binds this input without changing historical analysis sources. Even `declared_fresh` remains an operator declaration, rather than verified execution evidence.

Existing [cohort declarations](CONTROLLED_COMPARISONS.md) also appear with their exact source and case membership. A declaration covering one of four cases describes those cohort cases only. It does not label the entire run fresh or imported. Conflicting whole-run and cohort declarations remain visible together; the report does not silently choose one. Synthetic outputs are labeled as pipeline behavior rather than model variability.

The [report CLI](../classification_bench/cli.py) accepts `--repeat-origins` as an optional JSON path, and `generate_report` accepts `repeat_origins`. Both are offline reporting inputs, not inference instructions.

## Shared scope and navigation

The renderer reads `window.reportFilters.getState()` after initializing exact URL selection and listens for `report-filter-change`. Both source runs must be eligible for a pair to match. Visible counts appear beside the full planned pair and condition totals. All planned pairs remain accessible through the pair-scope control.

An explicitly selected A/B pair outside the shared scope remains visible as a disclosed evidence exception. Filtering does not replace that selection or recalculate its metrics. Pagination resets when eligibility changes, while an equivalent repeated scope and a case-only selection change preserve pair pages. The case outcome view has its own visible/planned count; a case outside that view remains selected in the explorer.

Evidence links overlay their exact run, comparison run and case on the current report URL. They retain the latest shared filters, case search, presentation state and unrelated parameters. Clearing a retained pair removes its comparison-run URL selection while keeping the remaining report state. Keyboard controls use native buttons/selects, scrollable tables have accessible labels, focus is visible and reduced-motion preferences are respected. No external resources or model calls are used.

Without JavaScript, the first pair, condition, field and case pages remain readable and exact links still identify saved evidence. Page counts disclose their bounded preview. Interactive pagination and scoped selection require local JavaScript.

## Verification boundary

[Repeat tests](../tests/test_report_repeats.py) check manually calculated counts against the existing evaluator, partial/unlabeled and unusable states, exact case reasons, source immutability, explicit replay and subset provenance, single-repeat/synthetic cases, arbitrary text escaping, shared scope, pagination and report/presentation reuse. These source and DOM checks are offline. They do not render private artifacts or establish visual acceptance.

The current tool-policy restriction still prohibits private-artifact rendering through alternative routes. Permitted observations remain pending under [REPORT_UX_CHECK.md](REPORT_UX_CHECK.md), [feature parity R10](FEATURE_PARITY.md) and the [active goal](NEXT_TASK_GOAL.md).
