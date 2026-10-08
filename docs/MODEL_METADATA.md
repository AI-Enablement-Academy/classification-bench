# Explicit model declarations

Model family, declared purpose and training lineage are separate optional declarations. They do not determine the existing `model_type` reporting group, execution route, output interface or evaluator behavior. The harness never fills them from a model name, adapter, label vocabulary or measured result. This implements the distinctions required by [the active goal](NEXT_TASK_GOAL.md).

Add `model_metadata` to an experiment configuration. The following is an illustrative declaration, not verified information about a real model:

```json
{
  "id": "example",
  "model": "vendor/exact-model",
  "model_type": "llm",
  "model_metadata": {
    "schema_version": 1,
    "family": {
      "value": "Operator-declared model family",
      "status": "operator_declared",
      "provenance": "Experiment author's recorded model-card attribution",
      "source_urls": ["https://example.org/model-card"]
    },
    "declared_purpose": {
      "value": "Categorical classification for this experiment",
      "status": "operator_declared",
      "provenance": "Experiment author's stated intended use",
      "source_urls": []
    },
    "training_lineage": {
      "value": "Exact training claim reviewed by the operator",
      "status": "operator_verified",
      "provenance": "Operator's retained review note identifying the reviewed claim",
      "source_urls": ["https://example.org/training-record"],
      "reviewed_at": "2026-10-08T12:00:00Z"
    }
  },
  "settings": {}
}
```

Each axis is optional. An omitted axis is unknown; an explicit unknown is exactly `{"status":"unknown"}`. Missing metadata remains absent from the original configuration. No family, purpose or lineage is inferred from `model_type`, including a `fine_tuned_llm` reporting group.

Known declarations have exactly `value`, `status`, `provenance` and `source_urls`. Status is `operator_declared` or `operator_verified`. A verified declaration also requires `reviewed_at`, an aware UTC ISO8601 timestamp ending in `Z`. Every training-lineage claim requires at least one source URL. Every verified axis requires at least one URL. An ordinary family or purpose declaration may instead identify its operator provenance without a public URL. Text is bounded to 4,000 characters, source lists to 20 distinct URLs and each URL to 2,048 characters. Only absolute HTTP(S) URLs without userinfo, whitespace, control characters or backslashes are accepted.

`operator_verified` records the operator's assertion that they reviewed the cited claim on the supplied date. The report calls this an **Operator verified declaration** and states that the harness has not independently verified the source or claim. It does not establish the provider's actual serving model, an architecture, a causal explanation for performance or a verified training procedure. The code makes no source fetch and imposes no freshness claim on a historical review date.

The complete original metadata participates in the existing configuration and request hashes. Changing a value, source, status or review date changes the frozen identity. [The scheduler's adapter boundary](../classification_bench/benchmark.py) strips `model_metadata` and `model_type` before constructing strict provider adapters. Metadata remains in the plan and run identity; inference settings, input capsules and provider messages receive no declaration text. Experiments without metadata preserve their original request identities and configuration bytes.

[The projection helper](../classification_bench/model_metadata.py) creates an explicit per-axis view and a separate `metadata_sha256` when metadata is supplied. [The report](../classification_bench/report.py) includes per-run declarations, exact source URLs and review dates. The explorer shows selected A/B context without changing case denominators or selection. The presentation has a bounded declaration-context slide and exact explorer links for complete run inspection. HTML escapes declaration text; the explorer also validates URL protocols before creating source links. Unknown axes remain visible.

[Private downloads](../classification_bench/report_exports.py) allowlist the exact declarations and their provenance. Sanitized downloads retain only metadata identity, supplied status and each axis's declaration status; values, provenance, URLs and review dates are omitted. Sanitized output is not an anonymity guarantee. No arbitrary configuration or provider payload is added to these exports.

[Offline tests](../tests/test_model_metadata.py) cover legacy identity, canonical metadata changes, invalid provenance/URLs, explicit unknowns, source/status separation, report/presentation escaping, selected A/B DOM behavior and private/sanitized exports. DOM checks establish source and behavior only; rendered acceptance remains subject to the existing [report UX gate](REPORT_UX_CHECK.md).

```sh
python3 -m unittest tests.test_model_metadata -v
```
