# Case search and shared report scope

[The case explorer](../classification_bench/report_explorer.py) searches case IDs and the selected runs' input text. Matching is a literal, case-insensitive substring after Unicode NFC normalization. Leading and trailing query whitespace is ignored. Structured input keys and scalar values are searchable, including nested objects and arrays. Quotes, backslashes and punctuation remain literal; search does not interpret regular expressions. Predictions, reference labels, lifecycle states and error messages are excluded.

Search changes visible case-table rows only. Every planned row remains in the data, the case chooser retains every planned case, and metrics keep their original denominators. The live count states the visible and total planned case counts for the selected runs. A selected case outside the search remains available in the detail panel, with an explicit disclosure. No matches shows a clear-search control and a readable empty state. Typing keeps focus in the search field; clearing the query restores every row and returns focus there.

The caseSearch fragment parameter records the query beside run, compareRun and case. Search updates preserve the fragment heading, presentation state, shared report filters and unrelated URL parameters. Permalinks and history restore the query and exact selection. An explicitly empty fragment query overrides an older inbound search parameter. Selection changes and evidence inspection retain the current query; they never silently substitute a matching case for the selected evidence. Reset case selection resets the selected run/case; Clear case search resets the query.

## Shared run filters

The explorer listens for report-filter-change events whose detail contains eligibleRunIds, an array of frozen run IDs. Unknown IDs are ignored; a malformed payload is ignored. The explorer reads an existing window.reportFilters.getState() snapshot after initializing its URL selection. If that controller is not present, report-filter-request asks a host to re-emit the current scope. The host owns the report filter values and their URL state.

Run chooser options outside the shared scope are hidden and disabled. Exact selected A/B runs remain available and receive an outside-scope disclosure. No run or case is automatically replaced because a filter changed. The scope count retains the whole report's planned run denominator.

Prompt and agreement lists require both source runs to match shared filters. They retain full report pair totals beside the filtered count, and every included pair keeps its full planned case denominator. An exact selected A/B pair outside the shared scope is a disclosed evidence exception, placed first rather than represented as a matching pair. Agreement's selected-pair/all-pair control still applies. Pagination resets when the run scope changes; an identical repeated scope does not reset the page. Changing only the selected case does not rebuild comparison lists.

## Verification boundary

[Case-search tests](../tests/test_report_case_search.py) check structured text, Unicode, literal punctuation, selected evidence, missing/unlabeled states, focus, no matches, reset, URL restoration, presentation links, shared scope, exact A/B exceptions and pagination. [Existing explorer tests](../tests/test_report_explorer.py) retain their broader counts, evidence, money and navigation checks. These source and DOM checks are offline and do not render the private artifacts or establish visual acceptance.

The current tool-policy restriction still prohibits private-artifact rendering through alternative tools or routes. Permitted rendered checks remain pending under [the report UX checklist](REPORT_UX_CHECK.md) and [feature parity R4/R6/R7/R19](FEATURE_PARITY.md). The [active goal](NEXT_TASK_GOAL.md) requires synchronized scope, preserved denominators and exact evidence links.
