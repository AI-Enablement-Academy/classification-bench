# Findings from saved evidence

The local report builds its findings from the same validated run and case data used by the explorer. This step is offline: it sends no inputs to a model and incurs no inference charges. The generic data projection in [report_analysis.py](../classification_bench/report_analysis.py) feeds [report_findings.py](../classification_bench/report_findings.py); a future presentation can consume the same findings rather than calculate a second set of numbers.

## What each finding means

Every finding includes its source hashes, exact run IDs, case IDs, comparison scope, denominator and a content-derived finding ID. Evidence links restore the corresponding run, comparison run and case in the report. A reference correction changes the analysis and findings identities while the identity of the original model run stays fixed.

The current deterministic observations cover:

- Output validity and reference coverage for every planned run, including invalid and missing predictions.
- Exact agreement on fully referenced cases. With incomplete references, this is explicitly a subset score and whole-run accuracy remains unavailable.
- Per-field agreement, known class support, valid disagreement patterns and unusable predictions. Missing references and unobserved classes are disclosed.
- Paired prompt gains and losses with configuration and repeat held fixed. Recovery of valid output is separate and may overlap an agreement gain.
- Each repeat pair's label changes among two valid predictions, with the excluded cases and full planned denominator retained.
- An overview across every eligible agreement pair: acceptance range, pairs with joint errors and pairs with unknown references. Range-boundary links disclose ties. The explorer retains each pair's accepted-correct, accepted-error, accepted-reference-unknown and deferred cases; the narrative does not duplicate thousands of pair tables. Agreement is not proof of correctness.
- Actual dollar-cost coverage for each run. Missing costs are unavailable, subscription invocations are not dollar charges, and synthetic amounts do not support real-provider cost comparisons.

Suggested follow-ups appear separately from observations. They propose inspecting evidence, adjudicating references, checking receipts or testing a revised prompt on new inputs. They are not model-generated explanations of why a configuration behaved as it did, and they do not authorize further inference.

## Reading the denominators

A run's planned case count does not change when output or references are missing. A field can have fewer known references than the run's planned count. Prompt comparisons retain both the known-reference subset and the full planned count. Repeat flip rates use cases with two valid predictions and report excluded cases alongside them. Each agreement pair retains its own full planned denominator.

Do not add overlapping pair counts or repeated-case observations together as independent samples. A high agreement rate on these inputs is not a universal model ranking, evidence of calibration, or a deployment guarantee.

## Verification and remaining work

[Finding tests](../tests/test_report_findings.py) check exact counts, missing references, unavailable costs, all eligible pairs, source correction identities, reproducibility, HTML escaping and encoded evidence URLs. [Explorer tests](../tests/test_report_explorer.py) check selection and URL behavior offline. These are not rendered visual acceptance.

This increment establishes reusable evidence-linked observations. It does not close the full presentation requirement: richer cross-configuration quality/cost/timing narratives, controlled reasoning and batching comparisons, reference sensitivity, a presentation view, synchronized report-wide filters and rendered visual quality remain acceptance work in [the parity matrix](FEATURE_PARITY.md). The release must match the recruitment reference's analytical depth and visual quality across arbitrary tasks, including partial and unlabeled datasets.
