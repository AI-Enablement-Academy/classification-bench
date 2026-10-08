# Check the updated report

## Current acceptance procedure

The 8 October follow-up generated exact files in
[`private-data/report-release-20261008-v1/`](../private-data/report-release-20261008-v1/).
Start with `product-workflow.html` and `candidate-workflow.html`, then the six
data-state reports and `sensitivity.html` below. `openrouter-workflow.html`
contains the one completed live smoke and its unexecuted full phase.
`inspection.json` records all ten report hashes; `verification.json` records
fictional source/fixture hashes. All remain **pending rendered acceptance**.

Generate a fresh all-state fixture set after the final code change:

```sh
python3 -m scripts.report_acceptance_fixtures --directory /private/new-report-check
```

Use a new directory for each build. `verification.json` binds the exact report,
evaluation, prediction, reference and operation files to their source hashes.
All fixtures are fictional and generated offline. The Python network guard is
not process isolation. A `pending` rendered result in that manifest stays
pending until a permitted browser or human operator completes these checks.

Also generate the two managed smoke/full reports using [WORKFLOW.md](WORKFLOW.md).
The [recorded installed workflow acceptance](WORKFLOW_ACCEPTANCE_20261008.md)
identifies its own exact artifacts; older HTML does not update with the source.
Record the report path and SHA-256 before checking it. Do not treat a successful
static/DOM check or an older visually accepted file as approval of a new build.

1. Open `complete.html`, `invalid.html`, `partial.html`, `unlabeled.html`,
   `all-missing.html` and `failed.html`. Each has nine planned outputs across
   three repeats of the same three cases. Complete has nine valid outputs;
   invalid, partial and unlabeled each have eight valid and one invalid output.
   All-missing and failed each retain nine missing outputs; failed additionally
   identifies six fictional failed requests. Partial has one referenced case
   per repeat. Unlabeled must show unavailable accuracy throughout, including
   presentation mode. Repeated cases must not be described as independent data.
2. Inspect the overview, findings, per-field metrics and supporting cases.
   Follow an error/finding link to its exact run and case. Compare the displayed
   numerator, denominator and scope with the saved evaluation. Missing costs,
   tokens and timing stay unavailable. These fixtures must never become a real
   provider cost or speed ranking.
3. Select two distinct runs in the case explorer, open a disagreement and copy
   its URL. Reload the copied URL and use Back/Forward. The same run pair and
   case must return. A/B predictions, reference and invalid/missing status must
   match the original selected runs.
4. Exercise shared filters, prompt/repeat filters and case search. Try a
   no-match search and reset it. Whole-experiment totals stay fixed, scope
   counts change correctly, and retained selections outside the current view
   are disclosed. Clear filters to restore the full experiment.
5. In `sensitivity.html`, inspect the illustrative alternate reference. Confirm
   the UI labels its findings hypothetical and links the changed case. Saved
   references and the normal evaluation must remain unchanged. Check repeat,
   agreement/deferral and difficult-case views without pooling cases or
   selectively hiding eligible pairs.
6. Download a private evidence export and a sanitized export. Check their
   declared source hashes, scope and allowlisted fields. Confirm sanitized data
   omits raw input text and private notes. A real browser save is required for
   this step; a DOM test capturing bytes does not establish native saving.
7. Enter presentation mode. Move forward/backward with its buttons and
   documented keyboard controls, follow an evidence link and return to the
   report. Verify the title, measurement limits and task-specific conclusions
   remain readable. Check print preview for clipped text or hidden content.
8. In each managed workflow report, switch smoke/full phases and open a run,
   comparison and case. Reload the outer URL and check that phase and inner
   selection survive. Download each standalone phase report and confirm it
   contains the selected phase, its provenance and its own denominator.
   Workflow totals must account for both phases without pooling their accuracy.
9. Use Tab and Shift-Tab from the skip link through navigation, filters, chart
   links, comparisons, disclosures and presentation controls. Every action must
   have visible focus and a usable keyboard path. Inspect desktop and a narrow
   mobile-sized window: headings, labels and tables must remain readable;
   overflow must be contained and controls reachable.
10. Enable reduced motion through the browser or OS and repeat navigation and
    presentation transitions. Content must remain available without animation.
    Compare the visual hierarchy, typography, spacing and evidence navigation
    with the pinned recruitment reference. Record concrete defects rather than
    accepting visual parity from source tests.

Record browser/version, viewport, reduced-motion setting, exact artifact hashes,
steps passed, failures and screenshots where permitted. The agent must respect
the [existing browser restriction](BROWSER_ACCEPTANCE_20261001.md); this manual
operator procedure does not authorize an alternate automated rendering route.

## Historical 2 October fixture checklist

The following section preserves the earlier model-type/plot checks and their
exact historical fixtures. It does not accept a current generator build.

This checklist covers the model-type and comparison-plot update. It makes no provider calls. Use the exact current fixtures below; existing saved HTML does not change when the generator changes. Offline DOM checks exercise controls but cannot establish rendered appearance, focus visibility or narrow-window layout. These operator checks are the permitted manual acceptance path; the recorded Browser refusal prohibits an agent rendering workaround.

Fresh private examples are under `private-data/report-model-types-20261002/`:

- `mixed-unexecuted-v3/report.html`: four explicitly unexecuted configurations, eight comparison conditions and 72 planned positions, all missing. Each of General LLM, Fine-tuned LLM, Classification / decision and Unspecified has two conditions. Each adapter category, OpenRouter, Synthetic, Native decisions and Other declared adapter, has two. These declarations exercise the UI; they are not model-performance evidence or runnable provider configurations.
- `final/product.html` and `final/candidate.html`: four conditions, 36 planned positions and 24 completed synthetic requests each. Type metadata was omitted and all four conditions remain Unspecified. Synthetic duration is excluded from the comparison plot.
- `final/clef-full.html` and `final/clef-flash-full.html`: each has two prompt conditions, 18 valid saved requests/positions and three passes per prompt. Each row has 6/9 all-field exact agreement, zero missing/invalid, and 9/9 measured client requests. These frozen plans omit model type, so both conditions remain Unspecified. Dollar charges are unavailable and retained holds remain visible. Reports were regenerated from verified historical evidence with network connections forbidden; no extra inference occurred.

The adjacent `mixed-unexecuted-v3/verification.json` and `final/verification.json` bind the report hashes and generator sources. Earlier HTML is preserved; inspect these versions for this acceptance check.

1. In the comparison overview, find one row for each configuration and prompt. The product and candidate fixtures each have four rows; the mixed fixture has eight and each native full report has two. Product first-label rows should show 3/9 exact agreement; candidate first-label rows should show 0/9. Deliberately invalid rows should retain all nine positions and show nine invalid predictions. Missing measurements must remain unavailable.
2. In the mixed fixture, try each model group, then adapter categories, model/provider/route/prompt selectors and search. Each group alone should show two rows; an incompatible group/category pair must show an explicit no-match state. Reset comparison view must restore all eight rows and both All selections. Group counts describe all planned conditions and must not change with filtering. Whole-experiment totals must remain 72 positions, all missing.
3. Sort exact agreement and duration in both directions. Missing values should stay last. Observed cost is not sortable because rows may use different units. Whole-experiment totals must remain fixed while comparison filters change.
4. Select two Compare checkboxes. Confirm the side-by-side area matches each original row's agreement numerator/denominator, missing/invalid counts, duration coverage and cost units. A third selection must not silently replace a selected row. Filter a selected row out of the table; its retained comparison must clearly disclose that it is outside the current view. Clear selections and confirm the empty comparison guidance returns.
5. In either native full report, locate Agreement and client request duration. Both points must disclose 6/9 agreement and 9/9 duration coverage on hover or keyboard focus. Filter to one prompt: only its point should remain, axes must stay fixed, and totals must remain 18 positions. Click a point after pass filters hide its condition; the target must be revealed before navigation. In the synthetic fixtures, verify zero plotted conditions and four synthetic exclusions. In the unexecuted fixture, verify that absent measurements are counted and the empty guidance is clear. Never present client duration as pure inference time.
6. Use the sticky section navigation while scrolling. Check the active-section indication, click targets and heading offsets. Content must remain readable without animation. With reduced motion enabled in the operating system, smooth scrolling and transitions must stop.
7. In the synthetic fixtures' separate pass filters, select one prompt: the result count should show 6 of 12 pass sections. Select one pass: it should show 2 of 12. Comparison values and whole-experiment totals must remain fixed. Reset filters must restore all 12 passes. For incompatible options, verify an explicit no-match message.
8. Use contents links and condition links in the comparison table to reach a condition or pass. Filtered targets must be revealed before navigation.
9. Expand Full request identity and telemetry evidence. Confirm request identities, receipt hashes, tokens and costs remain available. Collapse it and confirm the measurement summary remains visible. Expand Supporting cases and confirm inputs, references, predictions and outcomes are present.
10. Navigate using Tab and Shift-Tab. Check that the skip link, both category rails, selectors, selection checkboxes, plot links, resets, contents links and disclosures can be reached and that focus is visible. On a narrow window, confirm navigation remains accessible by horizontal scrolling and tables and chart remain readable. Point labels must be usable with keyboard focus, not depend only on a mouse hover.

Report the exact file, browser/version, successful steps and any failures. Source-level and automated checks do not establish rendered layout or keyboard behavior. The previously accepted report's visual result does not automatically apply to this changed UI.
