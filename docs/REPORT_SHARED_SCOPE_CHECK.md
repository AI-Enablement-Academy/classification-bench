# Inspecting shared report scope

Fresh private artifacts live in `private-data/report-shared-scope-20261008/final/`. The generator forbids socket connections. [The manifest](../private-data/report-shared-scope-20261008/final/verification.json) binds source and artifact hashes; [script checks](../private-data/report-shared-scope-20261008/final/syntax-check.json) record offline verification. [Fixture source bindings](../private-data/report-shared-scope-20261008/final/fixture-source-bindings.json) also bind the saved generator, controlled task/plan/predictions/references and test fixture source. Earlier reports remain preserved.

All examples are fictional. The additional `controlled-cohorts.html` uses handcrafted predictions and explicitly fictional historical/fresh cohort declarations. Those declarations exercise the UI; they are not actual provider observations or evidence of new inference. No provider calls or real model-quality claims are part of this fixture generation.

In an allowed operator session, record the exact HTML hash, browser/version and viewport. Start with [the presentation checklist](REPORT_PRESENTATION_CHECK.md), then inspect:

1. Select a prompt and repeat in the shared controls. Confirm the pass list, condition rows, plot and evidence views agree. Condition metrics must still state that they cover all repeats; whole-experiment totals must remain fixed.
2. Change the same prompt through a nearby comparison/pass control. Confirm all aliases show the same selection. Test model-group and adapter-category rails, unavailable metadata, lifecycle scope, zero matching runs and reset.
3. Follow a section heading and a supporting case link, then reload. Confirm filters and exact evidence survive navigation. An explicitly selected run outside the filters must remain inspectable with its scope disclosed.
4. Search a case ID or input phrase. Check visible/planned counts, literal punctuation, no matches, reset and typing focus. The selected case remains inspectable outside search; scores must not change.
5. In controlled comparisons, inspect declared configuration differences, known-reference coverage, invalid/missing counts and exact A/B evidence. Check every eligible pair is reachable through pagination. A confounded pair must not be described as a single-setting effect.
6. Select each fictional cohort. Compare selected runs, distinct configurations, reference coverage, unusable counts and within-configuration variation. Apply a repeat filter and reload: matching membership changes, but the declared cohort totals must remain fixed and explicitly labeled.
7. Select a controlled finding in Presentation and follow both range-boundary links. Confirm exact A/B run IDs, then return to the same presentation slide.
8. Check desktop and narrow layouts, visible keyboard focus, overflow, reduced motion and print. Record actual defects against the pinned recruitment reference; correct arithmetic and DOM tests do not establish visual quality.

[Shared filter tests](../tests/test_report_filters.py), [case-search tests](../tests/test_report_case_search.py), [comparison tests](../tests/test_report_comparisons.py) and [integrated navigation tests](../tests/test_report_shared_workflow.py) provide offline evidence. The [recorded private-artifact Browser restriction](BROWSER_ACCEPTANCE_20261001.md) remains in force; no alternate rendering route was used. Rendered acceptance remains pending.
