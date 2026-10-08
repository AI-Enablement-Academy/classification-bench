# Shared report filters

The report uses one filter state for pass tables, condition comparisons, plots and case evidence. Changing a prompt in either table changes the same state. Whole-experiment totals stay fixed, and a filtered view always reports its visible planned runs and run-case positions alongside those totals.

The metadata comes from the frozen configuration in [report analysis](../classification_bench/report_analysis.py) and the local [native](../classification_bench/decision_adapters.py) and [subscription](../classification_bench/subscription_adapters.py) adapter contracts. A model name does not establish a provider, architecture or serving identity. Explicit configuration values take precedence over contract defaults. Unknown interfaces and missing values stay unavailable. A literal declared value such as `unavailable` remains distinct from missing metadata.

| Filter key | Meaning |
| --- | --- |
| `model_group` | Operator-declared general LLM, fine-tuned LLM or classification / decision group; unspecified stays separate. |
| `model` | Requested model string. |
| `provider` | Declared requested provider or the native / subscription account contract. |
| `execution_route` | Declared adapter identity. |
| `output_interface` | Declared interface or a verified local adapter output contract. |
| `effort` | Declared effort or string reasoning setting. |
| `prompt` | Frozen prompt condition. |
| `repeat` | Planned repeat number. |
| `lifecycle` | Whole runs containing at least one case with the selected saved lifecycle state. |
| `api_route` | Requested API / account route, separate from execution route. |
| `adapter_category` | Adapter-category navigation rail, using the same state. |

Lifecycle and prediction validity describe different facts. For example, a run containing a refused case may also contain valid, invalid and missing predictions. Selecting `refused` retains every planned case in that run. It does not recalculate a score over the refused cases. Repeated run-case positions also do not create new distinct cases.

A condition comparison retains every planned repeat. Selecting repeat 1 of 2 can leave one pass visible while the condition aggregate still includes both repeats. The condition scope records `visibleRuns`, `totalRuns` and `partial`, so consumers can disclose that difference. Filtering changes evidence visibility; it never silently recalculates condition metrics. An exact selected run, comparison run or case outside the filter scope remains selected and is disclosed as an evidence exception.

## Integration contract

[report_filters.py](../classification_bench/report_filters.py) provides `build_report_filter_data(analysis)`, the pure `filter_report_runs(data, selected_filters)` projection and `render_report_filters(analysis)`. The projection carries the analysis identity, source hashes and a content hash. It includes allowlisted metadata and counts, without raw inputs, predictions or arbitrary configuration settings.

The controller exposes `window.reportFilters`:

| Method | Behavior |
| --- | --- |
| `getState()` | Returns a detached current snapshot. |
| `setFilters(values)` | Merges canonical filter keys with opaque option IDs; validates the entire update before changing state. An empty string clears a dimension. |
| `setValue(key, value)` | Selects an exact declared raw value. `undefined` clears a dimension; `null` selects unavailable metadata. |
| `reset()` | Clears every shared dimension. |
| `matchesValue(key, value)` | Checks the selected raw value for navigation rails. `undefined` checks an unapplied dimension. |
| `matches(runIds)` | Checks whether any supplied run ID belongs to the eligible scope. |
| `refreshAliases()` | Replaces legacy select options with canonical options and binds newly parsed controls. Call this after later report controls appear. |

Primary and mirrored selects use `data-report-filter` with a canonical key. The controller also recognizes existing `data-filter` and `data-comparison-filter` names for model, provider, route, effort, prompt and repeat. The old route controls map to `api_route`. A consumer must remove its independent filter gating and apply the shared scope instead.

Each `report-filter-change` event carries `eligibleRunIds`, `selectedFilters`, `selectedValues`, `whole`, `visible`, `conditionScopes`, `filterDataId`, `scopeRule` and `conditionRule`. Both count objects include runs, planned positions, conditions, distinct cases, valid predictions, invalid predictions and missing predictions. Consumers can request another snapshot with `report-filter-request` or send an opaque-ID update through `report-filter-set`. Late consumers can also read `getState()` directly.

The URL stores stable option IDs as `rf_<key>` parameters in the existing fragment query. Updates preserve the heading, explorer selections, case search, presentation state and unrelated parameters. Fragment values take precedence over URL-query values. Reset writes empty fragment values to override a filter inherited from the URL query. An unrecognized linked option leaves that dimension unapplied and displays a notice. No raw metadata value becomes a CSS selector or URL parameter.

Without JavaScript, the report keeps all planned evidence visible and explains that shared filtering is unavailable. The panel uses labeled native selects, keyboard focus indicators and live scope counts. It loads no external resources.

## Verification boundary

[test_report_filters.py](../tests/test_report_filters.py) checks deterministic metadata, hashes, source immutability, whole and visible counts, partial condition scopes, unsupported routes, missing values and arbitrary text. Its manual fixture has 12 runs and 36 planned positions: selecting the general LLM group and repeat 1 leaves 2 runs and 6 positions, including 1 valid, 1 invalid and 4 missing predictions. Lifecycle selection retains whole runs.

DOM checks cover mirrored controls, reset, delayed aliases, exact raw values, zero-result groups, URL preservation, history changes and HTML injection escaping. These checks establish controller behavior in a DOM environment. They do not replace the browser or human acceptance checks in [REPORT_UX_CHECK.md](REPORT_UX_CHECK.md).
