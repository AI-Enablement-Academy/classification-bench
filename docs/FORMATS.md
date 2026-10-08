# v0.1 file formats

Every file is UTF-8 JSON. Unknown structural keys are rejected. IDs must be unique nonempty strings. Current task input values are strings, so a task with candidate and job-description inputs supplies two named text fields rather than a nested object.

## Task

See [the example](../examples/task.json). `name` identifies the task. `input_keys` lists exactly which inputs are allowed. `fields` declares one or more objects with `name` and `labels`; each field needs at least two distinct string labels. Include an explicit unknown/insufficient-evidence label when the task requires it. An invalid model response is a separate evaluator state, not that semantic label.

## Experiment

See [the example](../examples/experiment.json). `configs` contains objects with `id`, `model`, and optional `settings`. The offline planner treats settings as JSON-compatible metadata. The matrix runner additionally validates settings through the selected adapter; the OpenRouter adapter checks supported controls against its frozen endpoint snapshot and a fresh catalog comparison before admission. Requested controls are distinct from observed provider evidence. `prompts` contains `id` and `text`. Positive integers `repeats` and `batch_size` define the matrix and shared context membership.

Each configuration can also declare `model_type`: `llm`, `fine_tuned_llm` or `decision`. These map to the report's General LLMs, Fine-tuned LLMs and Classification/decision models groups. Omit the field when unknown; the report shows Unspecified. This is an operator-declared reporting group, independent of the execution route, not a verified architecture or training-history claim. A decision model may itself be a fine-tuned LLM. The field belongs beside `id` and `model`, outside adapter `settings`.

For example, `{ "id": "decision-a", "model": "clef", "model_type": "decision", "settings": { "adapter": "clef_decide" } }` illustrates grouping only, not a complete runnable provider configuration. Configure account/billing controls as described in [native operation](NATIVE_DECISIONS.md). The full configuration is content-bound into request IDs: declare type before planning, and preserve existing historical plans when the declaration changes. Omitted metadata preserves existing plan identities.

Prompt text can include the full task rubric. The offline planner preserves prompt bytes. The OpenRouter adapter renders them in a system message and serializes the allowlisted records and field vocabulary in a user message; exact rendered bytes are stored in execution evidence. Other methods must declare their own role and input semantics. Configurations and prompts are expanded in declaration order, followed by repeat and batch order. This deterministic order is not a counterbalanced real execution schedule.

## Inputs and reference labels

Inputs use `{ "records": [{ "id": "example-1", "input": { "description": "...", "audience": "..." } }] }`. The `input` object's keys must exactly match `input_keys`. An accidental `labels` field on the record is rejected.

Complete reference files use `{ "records": [{ "id": "example-1", "labels": { "segment": "teams", "urgency": "later" } }] }`. The default evaluator requires IDs to equal the plan's input IDs and every reference to have exactly the task fields and allowed string values. Reference versions are separate files. Keep an external review record for changes.

The Python evaluator also supports explicitly absent or partial references. Call `evaluate(task, plan, labels=None, predictions=saved_predictions)` for unlabeled analysis. To evaluate a supplied partial document, pass `allow_partial_references=True`; the default continues to reject incomplete references. In that mode, missing record IDs, omitted task fields and `null` label values mean unavailable reference labels. An empty `records` list is allowed. Duplicate or unexpected IDs, extra fields, notes, unknown label strings and non-string non-null values remain errors. Unlabeled inputs retain their planned positions and output-validity outcomes. They receive no invented accuracy score.

## Plan

The planner emits `schema_version`, `task`, `experiment`, and `requests`. A request includes `request_id`, `config_id`, `prompt_id`, `repeat`, `batch_index`, and ordered `items`. The request hash binds the full effective task/configuration/prompt and membership, even though the shared definitions appear once at plan level.

The evaluator reconstructs and validates the full matrix before accepting predictions. A request ID is a content binding, not proof that a model executed it. The authorization-gated matrix runner stores raw-attempt evidence and verified request-bound receipts; a plan alone still does not establish execution. See [the runner](RUNNER.md).

## Saved predictions

See [the example](../examples/predictions.json). Each record has exactly `config_id`, `prompt_id`, `repeat`, `id`, and `prediction`. The first four identify the scheduled position. `prediction` should map every task field to one allowed string value. Missing positions remain missing; malformed prediction objects remain invalid. Duplicate or unexpected positions cause evaluation to fail rather than selecting a convenient attempt.

Use a separate export for each selected attempt set. The evaluator does not select a retry or reconstruct a response from partial output.

## Evaluation

Complete references retain the existing `schema_version: 1` result, including its source hashes and field structure. Setting `allow_partial_references=True` with complete references produces the same result. The implementation and saved-result compatibility checks are in [core.py](../classification_bench/core.py) and [test_unlabeled_evaluation.py](../tests/test_unlabeled_evaluation.py).

Top-level fields include `source_hashes`, `positions`, `missing`, `invalid`, and `conditions`. Each condition contains `passes`, exact-agreement `pass_score_mean` and `pass_score_range`, and `repeat_comparisons`.

Each pass reports its full `denominator`, `all_field_exact`, `all_field_exact_rate`, missing/invalid counts and field metrics. Each field includes a confusion matrix, `unscored_by_true_label`, and per-label precision/recall/F1/support/TP/FP/FN. Macro-F1 includes all declared labels; zero-division values are defined as zero.

Repeat comparisons report comparable/excluded counts, changed and excluded IDs, flip counts and rates for the entire output vector and for each field. Rates are null if no comparable valid outputs exist. Source hashes bind canonical JSON documents with sorted keys, compact separators and UTF-8 encoding; they are not file-byte hashes.

### Partial and unlabeled evaluation

Missing reference coverage produces `schema_version: 2`. It preserves the full planned `positions` count, each pass's full input `denominator`, and missing/invalid output counts. A prediction is valid only when its entire vector contains every declared field with an allowed label; an individually correct field in an invalid vector does not earn score credit. Each pass also includes `valid` and `valid_rate`, calculated over that full denominator.

Top-level and per-pass `reference_coverage` contain the following values. Coverage counts distinct imported inputs, rather than treating repeats or configurations as new reference cases.

| Field | Meaning |
| --- | --- |
| `status` | `partial` if any reference labels are known; otherwise `unlabeled`. |
| `input_count` | Number of distinct planned input IDs. |
| `fully_labeled_ids` | IDs with references for every task field, in input order. |
| `partially_labeled_ids` | IDs with some known task fields, in input order. |
| `unlabeled_ids` | IDs with no known reference fields, in input order. |
| `known_field_labels` | Number of known input/field reference labels. |
| `expected_field_labels` | `input_count` multiplied by the number of task fields. |
| `fields` | For each task field: `known_ids`, `missing_ids`, `reference_denominator`, `reference_missing` and `reference_coverage`. |

Each pass's `all_field_exact` and `all_field_exact_rate`, and each condition's `pass_score_mean` and `pass_score_range`, are `null` when references are incomplete. They cannot describe whole-dataset accuracy from a partial reference set. A separately named `scored_subset` reports `scope: "fully_labeled_records"`, its exact `ids`, `denominator`, `all_field_exact` and `all_field_exact_rate`. Its denominator includes missing and invalid predictions among those fully referenced inputs. The condition's `scored_subset_score_mean` and `scored_subset_score_range` summarize that same reference subset across repeats. Subset scores are `null` when no fully referenced inputs exist.

Per-field metrics use only inputs with known references for that field. Each field adds `reference_denominator`, `reference_missing`, `reference_coverage`, `correct` and `accuracy`. Confusion, support, precision, recall, F1 and false negatives are computed on the disclosed known-reference denominator. Missing or invalid predictions remain false negatives for known labels; unavailable references add neither support nor false negatives. When a field has no references, `correct`, `accuracy`, `confusion`, `labels` and `macro_f1` are `null`, and `unscored_by_true_label` is an empty object.

Repeat comparisons require valid predictions and remain identical with complete, partial or absent references. An omitted reference document sets `source_hashes.labels` to `null`; a supplied partial or empty document retains its canonical JSON hash. Corrections to labels produce a new evaluation and source hash; they do not modify previous evaluations, predictions or raw evidence. Request lifecycle details such as failed, refused or never-sent remain in the separate [runner evidence](RUNNER.md); the evaluator does not infer those states from a missing prediction.

For offline analysis extensions, `validated_positions(task, plan, predictions)` validates the canonical full plan and returns ordered `record_ids` and `positions`, raw `supplied` predictions, full-vector `valid` predictions and ordered `invalid` position keys. Keys are `(config_id, prompt_id, repeat, case_id)` Python tuples. `validate_reference_labels(labels, task, ids, allow_partial=True)` returns only known non-null field values by case ID. Neither helper creates reference labels or selects a favorable attempt.
