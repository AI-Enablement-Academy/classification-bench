# One-config offline simulation

The `simulate` command exercises the execution path with a local fake responder.
It makes no model or network request and needs no credentials. It accepts one
configuration and one prompt, with any positive repeat count and any number of
input records. Existing plan batching still applies.
The experiment's sole config must use `"model": "synthetic-only"` with no
settings (or an empty settings object). The fake worker rejects controls it
does not implement.

Create a private JSON config with these exact fields and absolute paths:

```json
{
  "schema_version": 1,
  "task": "/private/tmp/example/task.json",
  "experiment": "/private/tmp/example/experiment.json",
  "inputs": "/private/tmp/example/inputs.json",
  "database": "/private/tmp/example/state.sqlite",
  "artifacts": "/private/tmp/example/artifacts",
  "scope": "synthetic:example",
  "cap": 2,
  "reserve_amount": 1,
  "response_mode": "first_label"
}
```

`response_mode` can be `first_label`, `invalid`, or `missing`. The last two
exercise the evaluator's full-denominator behavior. The scope is restricted to
the `synthetic:` prefix, uses synthetic monetary units, and records an explicit
synthetic zero charge after each response. It grants no real budget authority.

```sh
python3 -m classification_bench simulate --config /private/tmp/example/run.json
python3 -m classification_bench simulate-export --config /private/tmp/example/run.json --out /private/tmp/example/predictions.json
python3 -m classification_bench evaluate --task /private/tmp/example/task.json --plan /private/tmp/example/plan.json --labels /private/tmp/example/labels.json --predictions /private/tmp/example/predictions.json
```

The first command is the execution path. Produce the plan with the existing
`plan` command for the separate evaluation step. `simulate-export` reads and
verifies saved response artifacts; it never opens labels. The evaluator alone
opens the labels file. Choose a fresh export path because the CLI never
overwrites an existing file.

The simulator rebuilds the v0.1 plan, renders exact UTF-8 system and user
message bytes, and validates a closed v1 execution manifest for each request.
The manifest binds the plan and full run-config digests, rendered messages,
request-byte hash, fake adapter/parser build hash, resolved controls, repeat
and batch order, retry `none`, cache `off`, seed `none`, and the synthetic
scope. A single immutable binding in the private SQLite database rejects any
changed config or referenced input files on restart. The worker receives only
the rendered request capsule through the [macOS isolation boundary](ISOLATION.md).
The config has no label or reference field; unknown fields are rejected.

The [verified execution wrapper](VERIFIED_EXECUTION.md) stores the manifest and
request bytes before enrollment, checks them before atomic admission, then
saves and verifies the fake response and its request-bound receipt before
terminal accounting. A rerun can reclaim an expired pre-intent claim. Once a
dispatch intent exists, it never automatically runs the fake responder again.
If the process stops after a receipt is published, run:

```sh
python3 -m classification_bench simulate-recover --config /private/tmp/example/run.json
```

Recovery scans the private artifact store for one attributable receipt,
verifies its bytes, and completes the saved response without calling the fake
worker. The default scan bound is at least 10,000 objects and grows with the
declared request count (four possible artifacts per request, plus margin).
If the private store contains additional published objects, pass an explicit
`--max-objects` value at least as large as that planned bound; exceeding the
chosen bound fails without accepting a partial scan. If no receipt exists,
recovery reports the request as unresolved; the
dispatch intent and reservation remain. A timeout or missing receipt does not
prove `not_sent`. An operator must use the underlying execution API with
independent evidence to mark an outcome or settle an unknown charge. A saved
response after an `outcome_unknown` event reconciles the response but leaves
its money hold for explicit settlement.

The fake responder is deterministic and deliberately small. It does not
verify provider capability, authorization, prices, usage, source attribution,
or external delivery. The isolated child has no network access, so this is
not a generic provider adapter. The [execution contracts](EVIDENCE_CONTRACTS.md)
remain the gate for credentials and live requests.
