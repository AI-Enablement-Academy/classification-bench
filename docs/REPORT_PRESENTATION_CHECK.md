# Inspecting the shared report and presentation

Fresh private fictional fixtures are in `private-data/report-presentation-20261008/final/`. The generator forbade socket connections and made no inference calls. Earlier artifacts remain unchanged. [Verification](../private-data/report-presentation-20261008/final/verification.json) records report, example and generator hashes; [syntax checks](../private-data/report-presentation-20261008/final/syntax-check.json) record seven HTML files with five JavaScript and three JSON scripts each. Every file is mode 0600. These are offline checks, not rendered acceptance.

The fixtures cover complete references (`labeled.html`), partial references (`partial.html`), no references (`unlabeled.html`), absent predictions (`all-missing.html`), an explicit hypothetical label alternative (`sensitivity.html`), and unrelated product/candidate task definitions with no executed predictions. The alternate label is a fictional inspection scenario, not a reference correction or model-quality claim.

## Operator inspection

An allowed operator should record the report SHA-256, browser/version, viewport and observations. Follow [the existing UX checklist](REPORT_UX_CHECK.md), then inspect these additions:

1. Open the labeled report. Read Findings and follow-up, then follow a field-error case link. Confirm the exact run, case and reference/prediction values match the claim.
2. Expand a pass's class metrics. Check support, confusion, TP/FP/FN and undefined ratios. Compare partial, unlabeled and missing fixtures: unavailable reference scores must not appear as zero accuracy.
3. Open the sensitivity fixture. Select its alternative, inspect the changed case and compare baseline/hypothetical counts. Confirm the result is visibly hypothetical and saved references remain the baseline.
4. Start Presentation. Use Next, Previous, the slide chooser and keyboard controls. Check readable hierarchy, chart labels, table overflow and progressive reveals at desktop and narrow widths.
5. Select a finding and follow its evidence link. Confirm presentation closes on the exact explorer selection; return to the same slide. For agreement ranges, inspect both minimum and maximum comparison links. Reload a presentation permalink and verify its selection.
6. Check visible focus, Escape, reduced motion and print preview. Inspect all slides without JavaScript as a separate fallback check.
7. In Downloads, read the disclosure and download the default pseudonymous archive. Extract its JSON locally and compare compressed/uncompressed hashes with the displayed values. Select private mode and confirm its disclosure accurately describes included inputs and references. Neither download uploads anything.
8. Compare the reading order, spacing, typography, charts and transitions against the [pinned recruitment presentation](https://github.com/adambkovacs/candidate-experience-benchmark/blob/6243eb3d234cebf2671ff8b3f42fef28e4ffed77/public-site/presentation.html). Record concrete defects rather than treating correct DOM behavior as proof of visual parity.

The [recorded Browser restriction](BROWSER_ACCEPTANCE_20261001.md) still governs automated private-artifact rendering. No alternative tool or localhost route was used to bypass it. Rendered observations and recruitment-level visual acceptance remain pending.
