# Run/case analysis acceptance fixtures

These are offline working fixtures for the 8 October analysis increment, not final release acceptance. They contain fictional example data. Generation prohibited socket connections and dispatched no inference. All HTML files have mode `0600`; the [private manifest](../private-data/report-analysis-20261008/final/verification.json) records file and generator hashes. [Syntax checks](../private-data/report-analysis-20261008/final/syntax-check.json) parsed embedded JSON and JavaScript; they do not verify rendering.

| Fixture | SHA-256 |
| --- | --- |
| [Labeled, including invalid/missing outputs](../private-data/report-analysis-20261008/final/labeled.html) | `c7160e0a25d54d840c1570048213f45c032af99195017ecefe78b5db62212872` |
| [Partial references](../private-data/report-analysis-20261008/final/partial.html) | `6c296fe69ad9544dc6a1221828b503dc9d4d3cc6fc4766cca83f160dc34c48f8` |
| [Unlabeled](../private-data/report-analysis-20261008/final/unlabeled.html) | `03dc16a681d653895b1ab7f675ba66e912f1c577515b8b885e498f938ae7b3af` |
| [All predictions missing](../private-data/report-analysis-20261008/final/all-missing.html) | `62d47e7f2b2c723a742ff980dc7e66259d83dd9b824a9e979fcad7002943c2d7` |
| [Product task, unexecuted](../private-data/report-analysis-20261008/final/product-unexecuted.html) | `4db35fa1fe52fa21936d5a819fa53bd45c397d5966be2afd7ccb042e270fe03c` |
| [Recruitment task, unexecuted](../private-data/report-analysis-20261008/final/candidate-unexecuted.html) | `ced72f50c6420462c8e8f63019108c323579ae66a4d6e0801371199ce5af1d3a` |

## Rendered checks to record

Use a permitted browser or direct operator observations. Respect the [recorded tool restriction](BROWSER_ACCEPTANCE_20261001.md); an alternate tool or transport is not a workaround. Record the exact file hash, browser, viewport, actions and observed result for each check. Every check below remains pending until those observations exist.

1. Open the labeled report. Check section navigation, typography, spacing, wrapping and comparison controls. Compare its clarity and visual quality with the recruitment reference. A readable page alone does not accept visual parity.
2. In Case explorer, select a run, a different comparison run and a case. Check predicted/reference values, invalid/missing states and exact field differences. Reload the selection URL and confirm the same choices return. Reset and use browser history; unrelated URL parameters must survive.
3. Follow a case link from Findings and follow-up. Confirm it selects the supporting run pair and case, moves to the case details and places keyboard focus appropriately. Follow prompt gain/loss and agreement-case links too.
4. In the partial-reference report, check that whole-run accuracy and its full-denominator plot are unavailable. Known-reference scores must identify their smaller denominator. Unknown references must not appear as wrong answers.
5. In the unlabeled and all-missing reports, check distinct reference/output states, planned totals and empty states. Validity and cross-run comparisons must remain usable; no invented correctness, free-cost or successful-run claim may appear.
6. Change the agreement scope and pages. Check that scoped and total eligible counts are visible, all pages are reachable, and changing only the selected case does not reset the pair table. Expand cost/source details; distinguish observed, partial, unavailable and subscription accounting.
7. At desktop and narrow/mobile widths, use keyboard controls, visible focus, scrollable tables and reduced motion. Verify no clipped controls, inaccessible evidence or unintended motion. Also check printing. Repeat task-specific labels and empty states in the product and recruitment fixtures.
8. Review findings against their supporting evidence. Confirm the observation, denominator and linked cases match; follow-ups remain suggestions; acceptance-range links disclose ties; overlapping pairs/repeats are not presented as independent samples.

The presentation view, reference sensitivity and remaining synchronized-filter/deep-analysis work are still listed in [FEATURE_PARITY.md](FEATURE_PARITY.md). Passing this fixture checklist cannot close those unimplemented gates or accept a later artifact with different bytes.
