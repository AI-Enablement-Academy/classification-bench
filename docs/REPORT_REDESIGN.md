# Report redesign, 2026-09-30

The local HTML report now opens with a concise experiment header and the full configuration comparison. The comparison keeps model names prominent, identifies the requested provider, and shows missing or invalid selected predictions beside exact agreement. It retains separate cost units and request coverage. Pass filters affect only the detailed evidence; the comparison and whole-experiment counts stay unfiltered.

The comparison supports text search and keyboard-operated column buttons. Rates, counts, duration, and coverage sort from explicit numeric values in the generated HTML. Unavailable numeric values sort last. Observed cost has no sort button because rows can contain different currencies or synthetic accounting units. Each request has a collapsed, escaped raw usage view beneath its identity and telemetry tables, so saved usage fields remain inspectable without changing the source evidence.

Automated checks: the final `python3 -m unittest discover -s tests -v` run passed 186 tests with no skips, including 23 report tests. Report tests check counts, coverage, escaping, links, controls, sort attributes, native token aliases and requested provider display. Fresh product and candidate demos each completed 24 synthetic requests and retained all 36 classification positions. The generated private HTML's JavaScript passed a syntax check. No provider inference was made.

Fresh reports are in `private-data/report-redesign-20260930/product/report-latest.html` and the corresponding `candidate/report-latest.html`. Earlier saved reports remain unchanged.

Visual appearance and live keyboard behavior remain unverified. The local-file browser policy for this task does not permit a rendering workaround. Review the generated HTML directly in an allowed local browser session before treating the visual design as accepted.

Implementation: [report generator](../classification_bench/report.py), [report UI tests](../tests/test_report_ux.py).

## Presentation reference

The updated goal names [Recruitly's model benchmarks](https://recruitly.io/ai/model-benchmarks) as a presentation reference. Its public page content was checked on 2026-09-30: a searchable model table places quality, failures, cost and latency together, with methodology explained separately. This is a content-structure observation, not a rendered visual comparison.

The current local report follows that comparison-first structure through prominent configuration/model names, search, numeric sorting and adjacent agreement, invalid-output, cost and duration information. Detailed evidence remains expandable below the overview. Its design and metrics remain specific to this generic categorical benchmark: full planned denominators and unavailable measurements stay explicit, and currencies remain separate. Recruitly's scores, confidence thresholds and operational fallback policy are not adopted as benchmark rules.

Rendered polish relative to the reference remains pending the [visual and interaction checklist](REPORT_UX_CHECK.md). Source inspection alone cannot establish equivalent visual quality.

## Cloudflare reference, inspected 2026-10-02

The public [Decision Model Leaderboard](https://clef-evals.workers-ai-mle.workers.dev/) was inspected with the bundled Browser, including rendered screenshots and the Charts and Methodology tabs. It uses horizontal score bars, quality-versus-latency scatter plots, selected-model area profiles, and calibration-versus-quality plots. The leaderboard has search and row-level benchmark breakdowns, while methodology and source qualifications are separate.

Its most useful patterns for this report are a comparison overview, deliberate selection, chart links into evidence, and visible provenance and measurement limitations. Its methodology distinguishes author-reported Clef results from upstream community results and warns that latency from different serving stacks is not directly comparable. Our client request duration must remain labeled as such. Probability output alone does not establish calibration; a calibration plot needs a separately defined, evaluated metric.

The displayed model list includes Clef, Clef-Flash, Jev, Decider, Kev, GLiNER-based models and other community models. This is a dated discovery reference, not an exhaustive or verified runnable catalog. No listed external score is imported as a result of this benchmark, and no extra adapter or inference scope follows from a model appearing there. Verify a candidate's native interface, artifact/version, access and billing before adding it to an experiment.

Model-type groups and execution-route categories answer different questions. General LLM, fine-tuned LLM and classification/decision are operator-declared reporting groups; a decision model can itself be derived from a fine-tuned LLM. Unspecified metadata stays visible. Changing a declaration creates a new frozen plan rather than relabeling historical evidence.
