# Presenting saved benchmark evidence

The private report's presentation uses the same frozen analysis and findings as its case explorer. It runs offline and makes no model calls. [Presentation code](../classification_bench/report_presentation.py), [analysis](../classification_bench/report_analysis.py), [findings](../classification_bench/report_findings.py) and [field metrics](../classification_bench/report_metrics.py) define the data and measurement rules.

The sequence explains task scope, output coverage, field errors, paired prompt changes, repeat differences, accepted agreement errors and deferrals, cost coverage, hypothetical reference sensitivity and follow-up experiments. Every comparison retains its own denominator. Repeated cases and overlapping pairs are not independent samples. The first planned run and first declared field provide a disclosed class-metric example; it does not imply a preferred configuration.

## Integration

Call render_presentation(analysis, findings, sensitivity=sensitivity, field_metrics=field_metrics). The return value is a self-contained HTML section with scoped CSS, inert JSON and JavaScript. The optional sensitivity and field-metric projections must match the analysis source hashes. Compute them once and share them with the report. The renderer never changes the inputs or re-scores evidence.

Eleven stable slides explain the experiment. The finding chooser includes every deterministic finding and mounts one detail at a time. Summary tables and charts show at most six rows in planned order and disclose their scope. Supporting case links show at most eight IDs; the report retains every finding, run, pair, case and source identity. The presentation does not copy the explorer's case predictions or quadratic agreement-pair data into a second payload.

Cost displays use observed USD charges and request coverage. Incomplete coverage is not a total price. Unknown charges, holds, subscription invocations and synthetic measurements remain distinct. The presentation does not derive a timing or token comparison from the analysis schema; those comparisons require the report's recorded measurements and coverage. Client request duration is not pure inference latency.

## Local links and controls

The existing report explorer uses run, compareRun and case parameters. The presentation preserves those and all unrelated search and fragment parameters, adding presentation=1 or 0, slide, reveal and finding after the fragment heading. For example, a fragment can identify presentation-heading with slide=prompts, reveal=1 and the currently selected run/case. Stable slide keys are scope, overview, outputs, fields, prompts, repeats, agreement, cost, sensitivity, finding and limits. Finding IDs bind their source analysis.

Next and Previous traverse reveals before moving between slides. The slide chooser jumps to a slide's first reveal state. The finding chooser changes the selected detail. The permalink opens the exact selected slide and reveal. Browser history and fragment changes restore the view. Unknown slides, finding IDs and invalid reveal values produce a notice and a readable fallback.

Start presentation opens an overlay and makes surrounding content inert. Escape and Return to report leave the overlay and restore focus. Evidence links leave presentation mode, retain the slide for return, and restore the exact supporting runs and case in the explorer. Report links reach the full findings, downloads and hypothetical sensitivity sections.

Arrow keys, Page Up/Down, Space, Home and End work in the presentation stage. Inputs, selectors, text areas, buttons, links, editable content and scrollable tables keep their own keys. Focus is visible and stays inside the active overlay. Reduced-motion preferences disable presentation transitions. Printing exposes every slide and reveal, including the selected finding detail. Without JavaScript, every narrative slide and reveal remains readable and the first finding retains its evidence links.

## Acceptance boundary

[Offline presentation tests](../tests/test_report_presentation.py) check exact scope/counts, partial and absent references, source identity, escaping, bounded payloads, hypothetical sensitivity, shared field metrics, URL restoration, focus, navigation and evidence selection. DOM checks exercise behavior without rendering private artifacts. They do not verify typography, layout, chart appearance, responsiveness, contrast, hover behavior or printed pagination.

Rendered acceptance remains pending. The current tool-policy denial prohibits rendering these private artifacts through alternative tools or routes. Do not bypass it or substitute source/DOM tests for rendered acceptance. A permitted operator review must name the exact report artifact and browser/version, then cover desktop and narrow layouts, labeled/partial/unlabeled/invalid/missing outcomes, keyboard focus, table scrolling, URL reload, evidence exits, reduced motion, hover/press feedback and print output. Follow [the report UX checklist](REPORT_UX_CHECK.md) and [feature parity R18/R19](FEATURE_PARITY.md).

The visual and navigation reference is pinned to candidate-experience-benchmark commit 6243eb3d234cebf2671ff8b3f42fef28e4ffed77: [presentation HTML](https://github.com/adambkovacs/candidate-experience-benchmark/blob/6243eb3d234cebf2671ff8b3f42fef28e4ffed77/public-site/presentation.html) and [navigation script](https://github.com/adambkovacs/candidate-experience-benchmark/blob/6243eb3d234cebf2671ff8b3f42fef28e4ffed77/public-site/meetup-presentation.js). The implementation adapts its narrative hierarchy, exact evidence links and controlled reveals to arbitrary task names, fields, labels and run rosters. Reading the pinned source does not establish visual parity.
