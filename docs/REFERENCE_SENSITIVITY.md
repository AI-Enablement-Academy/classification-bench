# Hypothetical reference sensitivity

Reference sensitivity shows how explicit alternative labels change agreement with saved predictions. It is an offline analysis of the same evidence. It makes no model calls, edits no reference files and does not replace earlier evaluations. A gain means closer agreement with a hypothetical key on these inputs. It does not establish better performance on new inputs or adjudicate the alternative label.

The generic [builder and report panel](../classification_bench/report_sensitivity.py) apply the [existing evaluator](../classification_bench/core.py). The source project's [pinned sensitivity builder](https://github.com/adambkovacs/candidate-experience-benchmark/blob/6243eb3d234cebf2671ff8b3f42fef28e4ffed77/scripts/analyze_reference_sensitivity_v1.py) supplies the functional reference: source-bound alternatives, fixed denominators, separate hypothetical results and exact changed-case evidence. The generic implementation accepts arbitrary tasks, fields, label vocabularies and case IDs.

## Declare the alternatives

Create a private JSON file containing a list of scenarios. Every scenario needs a unique ID, a title, nonempty operator provenance and at least one change. Each change supplies a case ID and one or more replacement field labels from the task's allowed vocabulary.

```json
[
  {
    "id": "routing-review-1",
    "title": "Alternative destination for a reviewed case",
    "provenance": "Operator review on 2026-10-08; unresolved reading of the routing SOP",
    "changes": [
      {"id": "case/alpha", "labels": {"destination": "ship"}}
    ]
  }
]
```

Only declare alternatives that have a documented reason. The tool neither invents alternatives nor automatically enumerates combinations. To test a combination, declare another scenario containing all its changes. Every scenario starts independently from the saved references.

The builder rejects duplicate scenario IDs, duplicate case IDs within a scenario, unknown cases or fields, labels outside the vocabulary, empty changes, extra keys and replacements equal to the saved label. A replacement requires an available saved reference for that exact case and field. Null, omitted and absent references cannot be filled through sensitivity. Adding reference coverage belongs in a separately versioned reference evaluation.

## Generate results

Use the offline CLI to create a separate JSON result:

```sh
python3 -m classification_bench sensitivity \
  --task private-data/task.json \
  --plan private-data/plan.json \
  --predictions private-data/predictions.json \
  --labels private-data/labels.json \
  --scenarios private-data/scenarios.json \
  --out private-data/hypothetical-sensitivity.json
```

For incomplete references, add `--allow-partial-references`. The [report command](../classification_bench/cli.py) accepts `--scenarios` to embed the same analysis in its private report. Python callers use `build_sensitivity(task, plan, predictions, labels, scenarios)` and `render_sensitivity(data)`. References and scenarios are offline report inputs, never inference capsule inputs.

File output is created exclusively with owner-only mode `0600`; an existing destination is rejected without overwrite. `--out -` writes the private JSON result to standard output instead.

## Read the results

The output records source hashes for the task, plan, saved predictions, saved references and supplied scenario list. Its `sensitivity_id` binds the complete result. Each scenario carries `hypothetical: true`, `status: hypothetical_not_applied`, a normalized `scenario_sha256`, a separate hypothetical reference document hash, an evaluation hash and a `result_sha256`. Normalized scenario hashes follow canonical task/plan change order; source hashes still record differences in the original scenario-list order.

`baseline.evaluation` contains the evaluator's original result. Each scenario's `evaluation` is a separate hypothetical result. The original caller objects are untouched, and the builder writes no files. A permanent correction still requires a new reference version and a new evaluation; hypothetical results do not authorize that correction.

Every baseline and scenario run retains its stable report `run_id`, configuration, prompt, repeat and planned validity counts. Run IDs do not change with alternative references. [Evidence links](../classification_bench/report_findings.py) restore the saved run and changed case in the report explorer.

Run results expose:

- `all_fields`: planned denominator, fully referenced denominator, correct count, known-reference subset rate and whole-run rate. Whole-run rate is unavailable with incomplete references.
- `baseline_all_fields` and `all_fields_delta`: the saved values and exact signed differences for that same coverage.
- `fields`, `baseline_fields` and `field_deltas`: agreement, reference coverage, class support, TP/FP/FN, precision, recall, F1, macro F1, confusion and unavailable-prediction counts.
- `case_deltas`: every changed reference case, its original prediction status, saved and hypothetical values, field credit differences, exact agreement differences and supporting evidence URL. Invalid raw predictions remain visible as invalid evidence.
- `gained_ids` and `lost_ids`: changed cases whose exact agreement credit increases or decreases. A partially referenced case has no exact agreement credit, though its known fields can have field deltas.

Missing and invalid predictions earn zero agreement credit where a reference is known. They remain in every applicable denominator and contribute false negatives for their known reference classes. Replacing a label can move these false negatives between classes without making the prediction valid.

The evaluator's arithmetic convention assigns zero precision when TP + FP is zero, zero recall when TP + FN is zero, and zero F1 when precision + recall is zero. Macro F1 includes those values. The class tables disclose the convention; no reference support means no measured class recall.

Scenario summaries count improved, declined, unchanged and unavailable runs. Repeats, configurations and overlapping scenarios reuse the same cases. These counts are descriptive and must not be pooled as independent samples. No overall sensitivity score or statistical certainty is invented.

With no known reference fields, an empty scenario list returns `status: unavailable`, null reference agreement metrics and an explicit unavailable panel. With references and no scenarios, it returns `status: no_scenarios`. Declared replacements for unavailable references are always rejected.

## Inspection and verification

The offline panel offers a keyboard-accessible scenario selector, native field/class/case details, visible focus, captions, row and column table headers, and focusable horizontal table regions. Operator task text, field names, labels, titles and provenance are escaped. The panel uses no remote resources. With JavaScript disabled, all scenario details remain available.

[Sensitivity tests](../tests/test_report_sensitivity.py) verify manually calculated gains/losses, combined alternatives, class/confusion deltas, partial and unlabeled references, missing/invalid predictions, immutable source hashes, strict validation, reproducibility, encoded case links, HTML escaping and offline DOM selection. Run them with:

```sh
python3 -m unittest tests.test_report_sensitivity -v
```

These checks verify deterministic data and DOM behavior. They do not verify rendered typography, mobile layout, keyboard focus visibility or reduced-motion acceptance. The exact generated report still needs the [rendered report checklist](REPORT_UX_CHECK.md). The [recorded private-report Browser restriction](BROWSER_ACCEPTANCE_20261001.md) remains an acceptance limitation until an allowed operator session provides observations.
