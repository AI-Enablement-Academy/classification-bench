# Run your own categorical task

This walkthrough creates a fictional support-routing task from scratch. It runs the synthetic adapter, which returns fixed test answers and makes no model calls. Use it to check that your task files, matrix, accounting, export and report work before planning any live run. The file contracts are in [FORMATS.md](FORMATS.md); the runner commands are in [RUNNER.md](RUNNER.md).

Run the whole block from the repository root with Python 3.10 or later. It creates a fresh private directory under your temporary directory and prints its path at the end. The paths in `config.json` are absolute, so later commands can read the run without depending on your current directory.

```sh
tmp_root="${TMPDIR:-/tmp}"
run_dir="$(mktemp -d "${tmp_root%/}/classification-bench-custom.XXXXXX")"

cat > "$run_dir/task.json" <<'JSON'
{
  "name": "fictional-support-routing",
  "input_keys": ["message"],
  "fields": [
    {"name": "queue", "labels": ["billing", "access", "other"]},
    {"name": "priority", "labels": ["standard", "urgent"]}
  ]
}
JSON

cat > "$run_dir/inputs.json" <<'JSON'
{
  "records": [
    {"id": "ticket-1", "input": {"message": "I need a copy of my receipt."}},
    {"id": "ticket-2", "input": {"message": "I cannot sign in after resetting my password."}},
    {"id": "ticket-3", "input": {"message": "The status page says service is down for everyone."}}
  ]
}
JSON

cat > "$run_dir/labels.json" <<'JSON'
{
  "records": [
    {"id": "ticket-1", "labels": {"queue": "billing", "priority": "standard"}},
    {"id": "ticket-2", "labels": {"queue": "access", "priority": "standard"}},
    {"id": "ticket-3", "labels": {"queue": "other", "priority": "urgent"}}
  ]
}
JSON

cat > "$run_dir/experiment.json" <<'JSON'
{
  "configs": [
    {"id": "first-label", "model": "synthetic-only", "settings": {"adapter": "synthetic", "response_mode": "first_label"}},
    {"id": "invalid-label", "model": "synthetic-only", "settings": {"adapter": "synthetic", "response_mode": "invalid"}}
  ],
  "prompts": [
    {"id": "short", "text": "Use billing for receipt or payment requests, access for sign-in or password problems, otherwise other. Use urgent only for a stated service outage affecting everyone, otherwise standard."},
    {"id": "evidence", "text": "Use only the supplied message. Queue: billing for receipt or payment requests; access for sign-in or password problems; otherwise other. Priority: urgent only for a stated service outage affecting everyone; otherwise standard. Check both fields."}
  ],
  "repeats": 2,
  "batch_size": 2
}
JSON

python3 - "$run_dir" <<'PY'
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1]).resolve()
config = {
    "schema_version": 1,
    "task": str(directory / "task.json"),
    "experiment": str(directory / "experiment.json"),
    "inputs": str(directory / "inputs.json"),
    "database": str(directory / "run.sqlite"),
    "artifacts": str(directory / "artifacts"),
    "scope": "synthetic:fictional-support-routing",
    "cap": 16,
    "currency": "SYN",
    "scale": 1,
    "max_concurrency": 2,
    "provider_limits": {"synthetic": 2},
    "authorization_file": None,
    "on_budget_exhausted": "pause",
}
(directory / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY

python3 -m classification_bench plan --task "$run_dir/task.json" --experiment "$run_dir/experiment.json" --inputs "$run_dir/inputs.json" --out "$run_dir/plan.json"
python3 -m classification_bench preflight --config "$run_dir/config.json" --out "$run_dir/preflight.json"
python3 -m classification_bench preview --config "$run_dir/config.json" --out "$run_dir/preview.json"
python3 -m classification_bench run --config "$run_dir/config.json" --out "$run_dir/run-result.json"
python3 -m classification_bench status --config "$run_dir/config.json" --out "$run_dir/status.json"
python3 -m classification_bench recover --config "$run_dir/config.json" --out "$run_dir/recovery.json"
python3 -m classification_bench export --config "$run_dir/config.json" --out "$run_dir/predictions.json"
python3 -m classification_bench evaluate --task "$run_dir/task.json" --plan "$run_dir/plan.json" --labels "$run_dir/labels.json" --predictions "$run_dir/predictions.json" --out "$run_dir/evaluation.json"
python3 -m classification_bench report --config "$run_dir/config.json" --labels "$run_dir/labels.json" --out "$run_dir/report.html"

printf 'Run directory: %s\n' "$run_dir"
```

The preview should list 16 requests: two configurations, two prompts, two repeats and two batches. The evaluation should contain 24 scheduled classification positions because each of the three records appears in every configuration, prompt and repeat. The `first-label` configuration always predicts `billing` and `standard`; `invalid-label` deliberately produces an unknown queue value. These results test the evaluator and its full denominator. They say nothing about model quality. Open `report.html` locally to inspect the case details and filters. Keep the report private if you replace the fictional records with real data.

`run` records the synthetic attempts once. A later `run` should dispatch no new requests; `recover` inspects saved evidence without dispatch. `plan` and `evaluate` are the separate file-based scoring path. `report` reads the saved run and opens `labels.json` only for scoring. Use new output names for later exports or reports because the CLI refuses to overwrite files. If you change the task, inputs, experiment, or config after running, create a new run directory; the saved run binds their original bytes.

The convenience scripts `scripts.offline_demo` and `scripts.prepare_run` accept only the bundled `candidate` and `product` fixtures. They do not create an arbitrary task. The generic CLI commands above accept task files that follow [FORMATS.md](FORMATS.md).

## Adapt the files for an authorized OpenRouter run

Use a new private directory and copy your reviewed `task.json`, `inputs.json` and `labels.json` into it. Set the live experiment's `configs` to a supported OpenRouter configuration instead of either synthetic configuration. Capture the selected model and exact provider endpoint with `python3 -m classification_bench catalog --model MODEL_SLUG --provider PROVIDER_TAG --out SNAPSHOT_PATH`. This command reads OpenRouter's public catalog; it does not make an inference call or require a key. Put the complete saved snapshot in `settings.endpoint_snapshot`, set the configuration's `model` to `snapshot.model_id`, and set `settings.adapter` to `openrouter`, `settings.provider` to `snapshot.provider_tag` and `settings.max_output_tokens` to your selected bound. Check controls and route limits against the [OpenRouter adapter contract](OPENROUTER.md) and [OpenRouter's endpoint catalog](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints).

Create a new `config.json` with absolute paths to the new files and empty database/artifact locations. Use `currency: "USD"`, `scale: 1000000`, a positive integer `cap` in microUSD, a new scope, and an absolute `authorization_file` path. Set that future grant path before preview; changing it later changes the run hash. Set `provider_limits` using the selected endpoint tag. Preview this exact configuration and review the request list, blocked reasons and conservative bounds before seeking approval. `plan` uses your task, experiment and inputs; `report` reads those files through the config and takes your labels. Never put `labels.json` in the run config or send it to the adapter. The [runner guide](RUNNER.md) explains budget behavior and recovery.

After explicit operator authorization for that exact run and cap, create the private file at the path already named by `authorization_file`. It must contain exactly these fields, with the hash, count, scope and cap copied from the new preview:

```json
{
  "schema_version": 1,
  "run_sha256": "COPY_FROM_PREVIEW",
  "plan_sha256": "COPY_FROM_PREVIEW",
  "request_count": 1,
  "scope": "COPY_FROM_CONFIG",
  "cap": 500000
}
```

The count and cap above are examples, not settings to reuse. The runner compares the whole authorization object with the exact config and plan before dispatch. A changed input, prompt, snapshot or config needs a new preview and authorization. The local file records an operator decision; it does not authenticate the payer. Credential setup and the authorized `run` command are in [RUNNER.md](RUNNER.md); the [smoke plan](LIVE_SMOKE_PLAN.md) shows a fixture-specific live example. This walkthrough performs no live catalog lookup or provider call.

The synthetic adapter reserves one SYN unit per active request and settles at zero. A positive SYN cap therefore bounds active reservations, not cumulative request count. Separate smoke/full databases currently have separate caps; no cross-run aggregate cap is enforced yet. These offline examples do not establish budget-exhaustion acceptance.
