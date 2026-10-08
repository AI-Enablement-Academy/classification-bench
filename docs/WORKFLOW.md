# Prepare and verify a frozen workflow

One workflow specification freezes smoke and full membership, repeat conditions,
concurrency limits and separate accounting caps. Preparation writes ordinary
version-2 runner configurations for each accounting unit. See the
[design contract](WORKFLOW_DESIGN.md), [runner contract](RUNNER.md) and
[aggregate budget contract](AGGREGATE_BUDGET.md) for execution and recovery rules.

Use task, experiment and input documents from the existing
[task setup workflow](TASK_SETUP.md). The workflow specification accepts exactly
these fields:

```json
{
  "schema_version": 1,
  "name": "Fictional intake triage",
  "task": "task.json",
  "experiment": "experiment.json",
  "inputs": "inputs.json",
  "budgets": {"SYN": 40},
  "phases": {
    "smoke": {
      "selection": {"first": 2},
      "repeats": 1,
      "caps": {"SYN": 10},
      "on_budget_exhausted": "pause"
    },
    "full": {
      "selection": {"all": true},
      "caps": {"SYN": 30},
      "on_budget_exhausted": "stop"
    }
  },
  "max_concurrency": 3,
  "provider_limits": {"synthetic": 2},
  "authorization_source": "fictional offline allocation terms"
}
```

Source paths resolve relative to this specification. All three documents use
the existing JSON contracts; JSONL and CSV records enter through task setup
before workflow preparation. Reference paths, labels and adjudication notes are
excluded from the workflow specification. An input string containing a path or
instruction remains input data and cannot cause preparation to open that path.

Selection is exactly one of `{"all": true}`, `{"first": N}` or
`{"ids": ["case-b", "case-a"]}`. A first count must be positive and no larger
than the input count. Explicit IDs must be nonempty, unique and present in the
supplied inputs; their order sets batching order. All and first preserve source
order. Repeats default to the source experiment and may be overridden with a
positive integer for either phase. Each phase retains every configuration,
prompt and batch size from the experiment.

Accounting units come from registered runtime code. USD uses integer
microdollars at scale `1000000`; REQ and SYN use scale `1`. Every used unit must
have one positive aggregate cap and one positive child cap in each phase. The
sum of smoke and full child caps must fit the aggregate cap for that unit.
The workflow keeps each unit separate. A request allocation does not establish
a dollar cost or verify subscription quota.

Synthetic and unsupported configurations belong to SYN. Unsupported adapter
names remain planned work with an unsupported outcome. Invalid controls for a
registered adapter fail preparation with the configuration ID and validation
reason. Every enabled adapter provider needs a positive provider limit; unused
provider limits may be retained for an operator's common configuration.

## Operator commands

From the repository, this sequence prepares and runs the unrelated fictional
product example. Choose a new output directory on each preparation. The
candidate example uses `examples/candidate/workflow.json` and its own output
directory. Both examples are synthetic and perform no inference.

```sh
mkdir -p -m 700 private-data
python3 -m classification_bench workflow-prepare --spec examples/product/workflow.json --directory private-data/product-workflow
python3 -m classification_bench preview --workflow private-data/product-workflow/workflow.json
python3 -m classification_bench preflight --workflow private-data/product-workflow/workflow.json --phase smoke
python3 -m classification_bench run --workflow private-data/product-workflow/workflow.json --phase smoke
python3 -m classification_bench run --workflow private-data/product-workflow/workflow.json --phase full
python3 -m classification_bench status --workflow private-data/product-workflow/workflow.json
python3 -m classification_bench export --workflow private-data/product-workflow/workflow.json --phase full --out private-data/product-workflow/full-predictions.json
python3 -m classification_bench report --workflow private-data/product-workflow/workflow.json --labels examples/product/labels.json --out private-data/product-workflow/report.html
```

`run`, `preflight`, `recover` and `export` require an explicit phase. `preview`,
`status` and `report` show both phases by default. The combined report preserves
each phase's deep analysis, explorer, filters, presentation and downloads. Its
whole-workflow output counts include every scheduled repetition; phase accuracy
is never pooled across different memberships. Local links retain phase and
report selection. Use `report --phase full` for an ordinary standalone report.
Scenarios, cohort declarations and repeat-origin annotations require a selected
phase. References are validated against the frozen full input source before
projection to the selected phase and never enter execution capsules.

For live work, `preview` includes an **authorization template**, not permission
to dispatch. After the operator approves the exact workflow identity, phase,
request count and cap vector, save that record separately and pass
`run --workflow ... --phase smoke --authorization approved-smoke.json`.
The runner retains that record and derives ordinary child authorizations; it
never manufactures approval during preparation. Full requires its own matching
record. Runtime credential, billing-guard and isolation checks still apply.

Budget exhaustion uses the phase's declared `pause` or `stop` policy. Pause
retains evidence and waits for an explicit amendment; it never buys credits or
raises caps automatically. Stop is terminal for that run. The frozen manifest
exposes each aggregate specification and child config for the existing
[`aggregate-increase` and `budget-increase` commands](AGGREGATE_BUDGET.md).
Amend the parent first when additional allocation capacity is needed. Safety
blocks and above-bound charge freezes require review and cannot be cleared by
a cap increase. Recovery reads existing evidence without replaying ambiguous
requests. Interrupted setup exposes uninitialized groups without authorizing or
allocating them during status/recovery.

## Python interface

```python
from pathlib import Path
from classification_bench.workflow import prepare, load

destination = Path("/private/selected/new-workflow")
manifest = prepare("workflow-spec.json", destination)
verified = load(destination / "workflow.json")
assert verified == manifest

smoke = verified["phases"]["smoke"]
config_paths = [run["config_path"] for run in smoke["runs"]]
```

Choose a new destination under an existing private location. Preparation
validates the specification, selected records and adapter request controls
before creating the destination. Every directory uses private permissions;
every output file uses exclusive creation with private permissions. The
manifest is written last. An I/O failure can leave an incomplete directory;
loading rejects it, and the caller chooses a fresh destination.

The resulting directory contains:

| Path | Contents |
| --- | --- |
| `workflow.json` | Workflow identity, immutable file hashes, source provenance, limits, aggregate specifications and both phase plans. |
| `sources/` | Exact original specification, task, experiment and input bytes. |
| `phases/smoke/`, `phases/full/` | Selected inputs, phase experiment and canonical whole-phase plan. |
| `runs/` | Ordinary version-2 configurations and experiments grouped by runtime accounting unit. |
| `aggregates/` | One ordinary aggregate specification per unit. |

The manifest declares `execution.sqlite` as the common future ledger and
`artifacts/` as the future evidence store. Preparation creates neither one.
It also creates no provider authorization. Live run configurations declare
future authorization locations under `authorizations/`; SYN configurations
have `authorization_file: null`. Provider discovery, credential checks,
preflight and inference occur through their separately authorized execution
paths.

Both `prepare` and `load` return the manifest with absolute paths. Useful fields
include:

| Field | Meaning |
| --- | --- |
| `workflow_sha256` | SHA-256 of canonical manifest content, excluding only this field. |
| `sources.inputs.path` | Frozen full input source, used by offline reference validation and phase projection. |
| `aggregates[unit].spec_path` | Frozen aggregate specification path. |
| `phases[phase].plan_path` | Independently frozen whole-phase plan. |
| `phases[phase].request_count`, `position_count` | Planned requests and prediction positions for this phase. |
| `phases[phase].runs` | Ordered unit groups with config, run and plan hashes, accounting unit, scope, request count and child cap. |

## Verification boundaries

Loading validates private owned files, contained normalized paths, source
hashes, every derived document and every manifest binding. It rebuilds the
expected preparation from frozen source bytes and current registered adapter
controls. A changed derived plan with updated file hashes still fails if it
disagrees with those sources. A changed runtime accounting unit fails rather
than silently moving work to another scope. Loading performs no repairs.

Original source files may be removed after preparation. The frozen copies
remain the source of verification. Internal paths and ordinary run identities
bind the selected destination, so moving a prepared directory requires a new
preparation and a new workflow identity. Do not move an initialized ledger;
the [aggregate authority contract](AGGREGATE_BUDGET.md#preserve-one-authority)
rejects copied or replaced databases.

Hashes detect drift against the stored manifest; they are not a signature or a
defense against an owner rewriting all frozen sources and bindings. Live
authorization must independently bind the exact workflow identity, phase,
request count and cap vector. Preparation does not prove runtime isolation,
live prices, account authentication or disabled paid extra usage.

The [preparation tests](../tests/test_workflow_prepare.py) exercise deterministic
freezing, membership and order, repeat overrides, exact unit allocations,
mixed runtime groups, whole-phase denominators, unchanged logical request IDs,
source disappearance, invalid controls, hash and binding tampering, contained
paths and private permissions. Guards prove reference-like strings are not
opened and credential, preflight and dispatch methods are not called.

```sh
python3 -m unittest tests.test_workflow_prepare -v
python3 -m unittest discover -s tests -v
```
