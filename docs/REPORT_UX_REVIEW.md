# Report UI/UX review

Reviewed on 2026-09-28 using the redesign-existing-projects skill, current report source, eight user-supplied report views and the user's confirmation that both reports were readable. An independent Sol high agent reviewed the code-level opportunities. This was a focused audit, not a rendered redesign. No report UI changes were made.

Verdict: **APPROVE with RESIDUAL improvements**. No confirmed BLOCKING defect. The report is useful; readability does not imply the interface is finished.

## Priorities

1. **RESIDUAL: compare configurations before opening detailed evidence.** The whole-experiment summary shows coverage, while scores are spread across separate condition articles. Add a compact configuration × prompt comparison table with exact agreement, repeat range, invalid/missing counts, duration and observed cost when available. Retain denominators and distinguish estimates from charges; avoid an unexplained composite winner. Sources: [condition articles](../classification_bench/report.py#L473), [summary](../classification_bench/report.py#L521).
2. **RESIDUAL: show filter results and provide a reset.** Current selectors hide pass sections without a visible match count, empty-state explanation or reset control. Add “Showing N of M pass sections,” a Reset filters button, and an explicit no-matches message. Keep whole-experiment totals clearly unfiltered. Sources: [selectors and filtering](../classification_bench/report.py#L492).
3. **RESIDUAL: reduce evidence density in the primary reading path.** Every pass shows long request IDs, multiple model identities, receipt hashes and telemetry tables. Keep outcome/quality/cost summaries visible and put full request evidence behind a clearly named disclosure. Evidence must stay accessible and unchanged. Source: [request tables](../classification_bench/report.py#L277).
4. **RESIDUAL: make long reports easier to navigate.** Add condition/pass anchors, a compact contents list, a main landmark and skip link. Improve table captions and row headers where the first column identifies a case or measure. Retain native select/details keyboard behavior and verify focus during a permitted browser check. Sources: [table generation](../classification_bench/report.py#L29), [page structure](../classification_bench/report.py#L515).
5. **RESIDUAL: improve quantitative scanning.** Add tabular numerals, right-align numeric columns, constrain prose width and distinguish metrics from descriptive evidence. Consider a plainly labeled synthetic-run notice near the title. Preserve exact values and unavailable states. Source: [styles and header](../classification_bench/report.py#L515).

## Recommended scope

Start with the comparison overview and filter feedback, then progressive disclosure/navigation. Keep the current Python-generated self-contained HTML, system fonts, inline assets and private local operation. External fonts, decorative imagery, animation libraries and framework migration do not improve this benchmark workflow enough to justify their cost.

These are implementation proposals, not claims of tested improvements. Any UI patch should preserve scoring and evidence output, receive focused regression coverage, and be rendered and exercised before visual success is claimed. The skill requires before/after rendering for UI changes; browser policy restrictions remain in force and must not be bypassed.
