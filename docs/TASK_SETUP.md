# Import and freeze your own task

The setup commands turn selected JSON, JSONL or CSV records into the existing [task, experiment and input formats](FORMATS.md). You supply the task policy, field names, label vocabulary, stable IDs, input mappings and prompt files. Initialization, import and validation run offline and require no credentials.

`init` validates the setup structure and writes a new private `setup.json`. It resolves selected file paths relative to the original setup file, but does not read those files. Review that file before `import` reads the selected records and instructions and freezes their exact bytes in a fresh private directory. `validate` checks hashes and rebuilds the derived documents from the frozen copies; it does not read the original files.

```sh
python3 -m classification_bench init --spec /private/selected/setup.json --directory /private/reviewed
python3 -m classification_bench import --spec /private/reviewed/setup.json --directory /private/frozen
python3 -m classification_bench validate --directory /private/frozen
```

Each destination directory must be new. Directories use permissions `0700`, and files use `0600`. The import validates source content before creating the destination and publishes its manifest last. An interrupted file write can leave an incomplete directory; `validate` rejects it. Select a fresh destination for the next import.

## Setup specification

A setup is a JSON object with `schema_version: 1` and these fields:

| Field | Contract |
| --- | --- |
| `task` | Existing task object: `name`, `input_keys`, and categorical `fields` with `name` and `labels`. Each decision field has at least two distinct string labels. |
| `source` | Selected input file: `path`, explicit `format` (`json`, `jsonl` or `csv`), and optional JSON `records_path`. |
| `mapping` | Stable `id` selector and an `inputs` object mapping every task input key to a selector. Optional `split` selector reads a split name from each input record. |
| `references` | Optional, separate `source` and `mapping`. Its mapping has `id`, a `labels` selector for every decision field, and optional `notes`. A combined input/reference source file is supported; exported capsules contain only selected inputs. |
| `instructions` | Optional `rubric` and `sop` file paths. |
| `prompts` | One or more objects with a unique `id` and selected text-file `path`. |
| `configs` | Existing experiment configurations, including model and adapter settings. |
| `repeats`, `batch_size` | Positive integers with the existing experiment semantics. |
| `splits` | Optional object mapping split names to explicit ID lists, as an alternative to `mapping.split`. |

A selector is an explicit array of field names. `['payload', 'body']` in a Python representation, or `["payload", "body"]` in JSON, selects `record["payload"]["body"]`. Dots in a field name are literal. CSV selectors contain exactly one header name, such as `["ticket_id"]`. The importer does not guess IDs, convert numbers into strings, trim labels, or rename fields.

JSON accepts a record array or an object containing a `records` array. Set `records_path`, such as `["data", "items"]`, for a different envelope. JSONL contains one record object on every line; a final newline is allowed, and blank lines are rejected. CSV is UTF-8 with a header row, comma delimiter and standard CSV quoting. Duplicate or empty headers, malformed quoting and rows with the wrong number of cells are rejected. JSON duplicate object keys, nonfinite values and malformed records are also rejected.

Input IDs must be unique, nonempty strings. Every selected input value must already be a string, including structured records whose text fields sit inside nested objects. Unselected source fields remain in the private provenance copy and do not enter inference inputs. If a combined source maps a label or note field directly into an input field, import rejects that overlap; the check cannot determine whether unrelated free text contains an embedded answer. Review the selected input content.

## Instructions and prompt variants

Instruction and prompt files must contain nonempty UTF-8 text. Every effective prompt joins the rubric, then SOP, then the selected prompt variant with exactly two newline characters between supplied components. The importer preserves each component's text, including existing leading/trailing whitespace and newline bytes, and stores each original file separately. Omit `instructions` when each variant already contains the full task policy.

Task names, decision names, label strings and prompt IDs are supplied data. Changing them requires a new setup import and new experiment plan, rather than engine or report edits. Adapter compatibility and execution controls remain subject to [runner preflight](RUNNER.md).

## References, missing labels and abstention

Reference IDs must be unique and belong to the imported inputs. Every supplied label must exactly match a declared string label. A missing JSON field or `null`, or an empty CSV label cell, means the reference label is missing. Whitespace and unknown values are errors; they are not repaired. Notes may be absent or strings and remain outside inference documents.

The manifest declares one reference status:

| Status | Frozen reference artifacts |
| --- | --- |
| `complete` | `references/labels.json` contains every input ID and every decision field, using the existing labeled evaluator format. |
| `partial` | `references/partial-labels.json` preserves only supplied valid labels. The manifest's `labels` value is `null`; the file is a partial projection rather than a complete scoring input. |
| `unlabeled` | No accuracy reference file is created. Inputs can still be planned and classified. |

`references/coverage.json` always lists each input ID and its exact `missing_fields`. Missing reference labels do not become model errors or invented ground truth. A semantic abstention is an explicit allowed label chosen by your task policy, such as `needs_review`; invalid or absent model output remains a separate lifecycle/evaluation state under [FORMATS.md](FORMATS.md).

For the complete-reference scoring command in the example below, use `references/labels.json`. Partial and unlabeled scoring require an evaluator mode that explicitly accounts for missing reference coverage. They cannot be represented as fully labeled accuracy results. A corrected reference creates a fresh imported directory and a new evaluation; preserve the old directory and evaluation as historical evidence.

## Dataset splits and frozen files

Explicit `splits` and a source `mapping.split` are mutually exclusive. Split memberships must partition every imported input ID exactly once, without unknown IDs or omissions. The importer sorts split names and retains original source order within each split. With neither option, a single `all` split contains every record.

`splits.json` binds each declared name to its IDs and generated file paths. Arbitrary split names never become filesystem paths. Each split has a standalone `inputs.json` accepted by `plan`; a split with complete reference coverage also has a separate complete reference file. Choose the split input and its matching references together when building and evaluating a split experiment.

The frozen directory contains `task.json`, `inputs.json`, `experiment.json`, `splits.json`, split input files, separate references and notes, and `provenance` copies of the exact setup, source, rubric, SOP and prompt bytes. `setup-manifest.json` records their SHA-256 byte hashes, original selected paths, derived counts and reference coverage. These byte hashes differ from the core evaluator's canonical JSON hashes. Keep execution databases, plans, predictions and reports in a separate run directory so the frozen file set stays verifiable.

Validation detects edited or missing bytes, extra files, symlinked artifacts, inconsistent mappings and changes to derived documents even if their manifest hash was manually updated. It establishes consistency with the local frozen copies; it is not an authenticity signature or proof of process isolation. Source provenance copies can contain labels and notes, so inference processes must receive the allowlisted input/task/experiment documents through the [execution isolation contract](RUNNER.md), rather than access to the whole frozen directory.

## Complete offline operator example

This example imports two fictional support tickets from user-owned CSV files, then runs the synthetic adapter. Its fixed first-label answers test setup, execution and evaluation; they are not model-quality measurements. It creates eight requests and eight classification positions: one configuration, two prompt variants, two repeats and two records with batch size one.

Run the complete block from the repository root with Python 3.10 or later:

```sh
umask 077
tmp_root="${TMPDIR:-/tmp}"
workspace="$(mktemp -d "${tmp_root%/}/classification-task.XXXXXX")"
mkdir "$workspace/selected"

cat > "$workspace/selected/tickets.csv" <<'CSV'
ticket_id,message,account_context
ticket-a,Please send my receipt.,individual
ticket-b,I cannot sign in.,team
CSV

cat > "$workspace/selected/references.csv" <<'CSV'
ticket_id,queue,priority,review_note
ticket-a,billing,standard,Reviewed by the task owner
ticket-b,access,standard,Reviewed by the task owner
CSV

cat > "$workspace/selected/rubric.txt" <<'TEXT'
Queue: billing for receipt or payment questions; access for sign-in or password problems; otherwise other. Priority: urgent for a stated service outage; otherwise standard.
TEXT

cat > "$workspace/selected/sop.txt" <<'TEXT'
Use only the supplied message and account context. Return both declared decision fields.
TEXT

cat > "$workspace/selected/direct.txt" <<'TEXT'
Classify each record using the rubric.
TEXT

cat > "$workspace/selected/careful.txt" <<'TEXT'
Check the evidence for both decisions before choosing the allowed labels.
TEXT

cat > "$workspace/selected/setup.json" <<'JSON'
{
  "schema_version": 1,
  "task": {
    "name": "my-support-routing",
    "input_keys": ["message", "account_context"],
    "fields": [
      {"name": "queue", "labels": ["billing", "access", "other"]},
      {"name": "priority", "labels": ["standard", "urgent"]}
    ]
  },
  "source": {"path": "tickets.csv", "format": "csv"},
  "mapping": {
    "id": ["ticket_id"],
    "inputs": {"message": ["message"], "account_context": ["account_context"]}
  },
  "references": {
    "source": {"path": "references.csv", "format": "csv"},
    "mapping": {
      "id": ["ticket_id"],
      "labels": {"queue": ["queue"], "priority": ["priority"]},
      "notes": ["review_note"]
    }
  },
  "instructions": {"rubric": "rubric.txt", "sop": "sop.txt"},
  "prompts": [
    {"id": "direct", "path": "direct.txt"},
    {"id": "careful", "path": "careful.txt"}
  ],
  "configs": [
    {"id": "synthetic-check", "model": "synthetic-only",
     "settings": {"adapter": "synthetic", "response_mode": "first_label"}}
  ],
  "repeats": 2,
  "batch_size": 1,
  "splits": {"development": ["ticket-a"], "holdout": ["ticket-b"]}
}
JSON

python3 -m classification_bench init --spec "$workspace/selected/setup.json" --directory "$workspace/reviewed"
python3 -m classification_bench import --spec "$workspace/reviewed/setup.json" --directory "$workspace/frozen"
python3 -m classification_bench validate --directory "$workspace/frozen"

python3 - "$workspace" <<'PY'
import json
from pathlib import Path
import sys

workspace = Path(sys.argv[1]).resolve()
execution = workspace / "execution"
execution.mkdir(mode=0o700)
frozen = workspace / "frozen"
config = {
    "schema_version": 1,
    "task": str(frozen / "task.json"),
    "experiment": str(frozen / "experiment.json"),
    "inputs": str(frozen / "inputs.json"),
    "database": str(execution / "run.sqlite"),
    "artifacts": str(execution / "artifacts"),
    "scope": "synthetic:my-support-routing",
    "cap": 100,
    "currency": "SYN",
    "scale": 1,
    "max_concurrency": 1,
    "provider_limits": {"synthetic": 1},
    "authorization_file": None,
    "on_budget_exhausted": "pause"
}
(execution / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY

python3 -m classification_bench plan --task "$workspace/frozen/task.json" --experiment "$workspace/frozen/experiment.json" --inputs "$workspace/frozen/inputs.json" --out "$workspace/execution/plan.json"
python3 -m classification_bench preview --config "$workspace/execution/config.json"
python3 -m classification_bench run --config "$workspace/execution/config.json"
python3 -m classification_bench export --config "$workspace/execution/config.json" --out "$workspace/execution/predictions.json"
python3 -m classification_bench evaluate --task "$workspace/frozen/task.json" --plan "$workspace/execution/plan.json" --labels "$workspace/frozen/references/labels.json" --predictions "$workspace/execution/predictions.json" --out "$workspace/execution/evaluation.json"
python3 -m classification_bench report --config "$workspace/execution/config.json" --labels "$workspace/frozen/references/labels.json" --out "$workspace/execution/report.html"
printf 'Private workspace: %s\n' "$workspace"
python3 -m classification_bench validate --directory "$workspace/frozen"
```

Both prompts have two evaluated passes with denominator two and exactly one all-field match per pass. The first-label synthetic output routes both records to `billing` with `standard` priority; only `ticket-a` matches its reference. Open the private report locally. Live adapter setup, task compatibility, budget approval and credentials remain part of the separate [runner workflow](RUNNER.md).

The runnable import coverage is in [test_task_setup.py](../tests/test_task_setup.py): a recruitment CSV case and an unrelated nested JSONL support case pass through initialization, import, validation, planning, synthetic execution, export and offline evaluation without engine edits.
