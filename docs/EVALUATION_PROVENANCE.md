# Versioned evaluation provenance

New offline evaluations include an explicit scoring algorithm version, deterministic source hashes and an `evaluation_id`. These fields distinguish the scoring implementation from task, plan, reference and selected-prediction content. Historical saved evaluations remain untouched and readable; their absent implementation provenance means unspecified, rather than the current version.

[Core evaluation](../classification_bench/core.py) retains metric schema 1 for complete references and schema 2 for incomplete references. Metric arithmetic and the four logical `source_hashes` keys remain unchanged. New computations add `evaluation_provenance` and `evaluation_id`, so their complete JSON bytes intentionally differ from earlier unversioned computations. [The compatibility test](../tests/test_unlabeled_evaluation.py) checks the old metric-payload hashes after excluding only these new fields.

## Provenance and identity

[The provenance module](../classification_bench/evaluation_provenance.py) produces a strict schema-1 object with:

| Field | Meaning |
| --- | --- |
| `scope` | `categorical_evaluation` or `categorical_case_analysis`. |
| `algorithm` / `algorithm_version` | Explicit algorithm family and positive version. Source changes are separately detectable even when arithmetic has not changed. |
| `source_sha256` | SHA-256 of exact installed Python source-file bytes, using package-relative names. |
| `implementation_sha256` | Hash of the canonical source-hash mapping. |
| `provenance_sha256` | Hash of the canonical provenance object, excluding only this hash field. |

Evaluation scope covers `core.py` and `evaluation_provenance.py`. Case-analysis scope also covers `report_analysis.py` and `model_metadata.py`, which it uses for validated run/case projections and configuration metadata. The case-analysis scope does not claim to cover findings, metric panels, presentation, HTML rendering, third-party libraries or provider execution.

`evaluation_id` binds the evaluator provenance hash and the four canonical logical input hashes: task, plan, references and selected predictions. An omitted reference uses `null`, not a fabricated reference hash. A new reference, scoring version or scoring source produces a distinct evaluation identity. It does not change the model run/request identity or rewrite an earlier evaluation.

[New case analyses](../classification_bench/report_analysis.py) include the current evaluation record, current case-analysis record and matching evaluation identity. Their `analysis_id` binds these implementation records alongside operations and supplied cohort/source content. Existing logical run IDs still identify the same requested conditions and inputs.

These hashes identify source bytes observed during computation. They do not reconstruct an interpreter/environment, authenticate references, prove independently dispatched repeats or verify provider serving. Preserve the installed build and its environment when reproducing old arithmetic; a digest alone is not an archived executable environment.

Report source tables disclose the scoring algorithm, evaluation identity and
implementation/provenance hashes. Both private and sanitized downloads include
strictly validated provenance with fixed package-relative source names. Export
rejects incomplete records or an evaluation identity that does not match the
four input hashes. Legacy supplied analyses with no provenance are explicitly
marked unversioned; they are never labeled as the current evaluator.

## Frozen workflows and historical reads

New [workflow preparations](WORKFLOW.md) produce manifest schema 2 and bind `evaluation_provenance` into `workflow_sha256`. The workflow specification remains schema 1. Preparation still reads no references or credentials and creates no execution database or live authority.

`workflow.load(path)` validates the frozen record's shape, source scope and internal hashes along with all existing source/derived bindings. It does not require that the local evaluator match: status, prediction export, raw recovery and inference do not score references and remain available after an evaluator update.

`workflow.load(path, require_current_evaluation=True)` requires an exact evaluator match for schema-2 workflows. [Workflow report snapshots](../classification_bench/workflow_execution.py) use this check before opening references or building scores. A changed evaluator fails with guidance to use standalone `evaluate` for a new current-version evaluation or prepare a new report workflow. It never relabels the old workflow's frozen evaluator as the new build.

Legacy schema-1 workflows remain structurally readable. They did not freeze an evaluator, so reports disclose that frozen evaluator as unspecified and label newly computed scores with current provenance. Historical saved report/evaluation bytes do not change when code changes.

## Offline verification

```sh
python3 -m unittest tests.test_evaluation_provenance tests.test_unlabeled_evaluation tests.test_workflow_prepare tests.test_workflow_execution -v
```

[Provenance tests](../tests/test_evaluation_provenance.py) cover deterministic installed-file hashes, algorithm/source identity changes, malformed or rehashed mismatches, complete/partial/unlabeled scoring, unchanged run identities, legacy workflows and the separation between scoring drift and non-scoring status/export/recovery/inference. No test dispatches a real provider.
