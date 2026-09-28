# v0.1 file formats

Every file is UTF-8 JSON. Unknown structural keys are rejected. IDs must be unique nonempty strings. Current task input values are strings, so a task with candidate and job-description inputs supplies two named text fields rather than a nested object.

## Task

See [the example](../examples/task.json). `name` identifies the task. `input_keys` lists exactly which inputs are allowed. `fields` declares one or more objects with `name` and `labels`; each field needs at least two distinct string labels. Include an explicit unknown/insufficient-evidence label when the task requires it. An invalid model response is a separate evaluator state, not that semantic label.

## Experiment

See [the example](../examples/experiment.json). `configs` contains objects with `id`, `model`, and optional `settings`. The offline planner treats settings as JSON-compatible metadata. The matrix runner additionally validates settings through the selected adapter; the OpenRouter adapter checks supported controls against its frozen endpoint snapshot and a fresh catalog comparison before admission. Requested controls are distinct from observed provider evidence. `prompts` contains `id` and `text`. Positive integers `repeats` and `batch_size` define the matrix and shared context membership.

Prompt text can include the full task rubric. The offline planner preserves prompt bytes. The OpenRouter adapter renders them in a system message and serializes the allowlisted records and field vocabulary in a user message; exact rendered bytes are stored in execution evidence. Other methods must declare their own role and input semantics. Configurations and prompts are expanded in declaration order, followed by repeat and batch order. This deterministic order is not a counterbalanced real execution schedule.

## Inputs and reference labels

Inputs use `{ "records": [{ "id": "example-1", "input": { "description": "...", "audience": "..." } }] }`. The `input` object's keys must exactly match `input_keys`. An accidental `labels` field on the record is rejected.

Reference files use `{ "records": [{ "id": "example-1", "labels": { "segment": "teams", "urgency": "later" } }] }`. IDs must exactly equal the plan's input IDs; each reference must have exactly the task fields and an allowed value. Reference versions are separate files. Keep an external review record for changes.

## Plan

The planner emits `schema_version`, `task`, `experiment`, and `requests`. A request includes `request_id`, `config_id`, `prompt_id`, `repeat`, `batch_index`, and ordered `items`. The request hash binds the full effective task/configuration/prompt and membership, even though the shared definitions appear once at plan level.

The evaluator reconstructs and validates the full matrix before accepting predictions. A request ID is a content binding, not proof that a model executed it. The authorization-gated matrix runner stores raw-attempt evidence and verified request-bound receipts; a plan alone still does not establish execution. See [the runner](RUNNER.md).

## Saved predictions

See [the example](../examples/predictions.json). Each record has exactly `config_id`, `prompt_id`, `repeat`, `id`, and `prediction`. The first four identify the scheduled position. `prediction` should map every task field to one allowed string value. Missing positions remain missing; malformed prediction objects remain invalid. Duplicate or unexpected positions cause evaluation to fail rather than selecting a convenient attempt.

Use a separate export for each selected attempt set. The evaluator does not select a retry or reconstruct a response from partial output.

## Evaluation

Top-level fields include `source_hashes`, `positions`, `missing`, `invalid`, and `conditions`. Each condition contains `passes`, exact-agreement `pass_score_mean` and `pass_score_range`, and `repeat_comparisons`.

Each pass reports its full `denominator`, `all_field_exact`, `all_field_exact_rate`, missing/invalid counts and field metrics. Each field includes a confusion matrix, `unscored_by_true_label`, and per-label precision/recall/F1/support/TP/FP/FN. Macro-F1 includes all declared labels; zero-division values are defined as zero.

Repeat comparisons report comparable/excluded counts, changed and excluded IDs, flip counts and rates for the entire output vector and for each field. Rates are null if no comparable valid outputs exist. Source hashes bind canonical JSON documents with sorted keys, compact separators and UTF-8 encoding; they are not file-byte hashes.
