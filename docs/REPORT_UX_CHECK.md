# Check the updated report

This checklist covers the report UX update. It makes no provider calls. Use a freshly generated report; existing saved HTML does not change when the generator changes.

1. In the comparison overview, find one row for each configuration and prompt. The bundled fixtures have four rows. Product first-label rows should show 3/9 exact agreement; candidate first-label rows should show 0/9. Deliberately invalid rows should retain all nine positions and show nine invalid predictions. Missing measurements must remain unavailable.
2. Select one prompt: the filter result count should show 6 of 12 pass sections. Select one pass: it should show 2 of 12. The whole-experiment totals and comparison overview remain unfiltered and labeled as such.
3. Use Reset filters: all 12 pass sections should return. For a custom matrix with incompatible model/provider options, verify that no matches produces an explicit message and that reset restores results.
4. Use the contents links to reach a condition and a pass. Check that links do not lead to hidden sections after filtering.
5. Expand Full request identity and telemetry evidence. Confirm request identities, receipt hashes, tokens and costs remain available. Collapse it and confirm the measurement summary remains visible.
6. Expand Supporting cases. Confirm inputs, references, predictions and outcomes remain present.
7. Navigate using Tab and Shift-Tab. Check that the skip link, filters, reset, contents links and disclosures can be reached and that focus is visible. On a narrow window, confirm tables remain readable through their scroll area.

Report the exact file, browser/version, successful steps and any failures. Source-level and automated checks do not establish rendered layout or keyboard behavior. The previously accepted report's visual result does not automatically apply to this changed UI.
