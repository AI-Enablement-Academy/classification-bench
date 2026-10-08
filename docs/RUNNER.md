# Running a benchmark locally

The matrix runner reuses the [atomic ledger](EXECUTION_API.md) and [verified artifact store](VERIFIED_EXECUTION.md). One orchestrator runs independent configurations concurrently. A private per-database process lock prevents a second orchestrator from multiplying the provider concurrency limit. Configuration declaration order, then prompt, repeat and batch order, is preserved within each configuration.

CLI JSON files written with `--out` and HTML reports are created exclusively with owner-only permissions (`0600`). Existing paths, including symlinks, are rejected. This covers plans containing input text, evaluation results and prediction exports, even when their parent directory is shared. Standard output remains available; when redirecting it, the shell controls the destination permissions. Existing files from earlier versions are not modified automatically.

## Use your own task

Follow the [custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md) to define your own task, inputs, separate references, prompts, model configurations, repeat count and batch size. It includes a complete offline command sequence and the additional configuration and authorization required for OpenRouter.

`scripts.offline_demo` and `scripts.prepare_run` are convenience helpers for the two bundled fixtures. They are not the generic task interface. The `classification_bench` commands accept your own configuration files directly.

## Reproduce without a provider

Python 3.10+ and the standard library are sufficient for synthetic execution and reporting. Run from the repository root; choose fresh output directories:

```sh
python3 -m scripts.offline_demo --task candidate --directory /tmp/candidate-demo
python3 -m scripts.offline_demo --task product --directory /tmp/product-demo
```

Each command creates a private run directory, previews and executes 24 synthetic requests across two configurations, two prompts, three repeats and two batches per pass, then writes `report.html`. Each experiment has 36 planned classification positions. The first-label and deliberately invalid outputs test the software; they are not measurements of model quality. No credentials, source-project records or model calls are involved.

For the generated run, the individual commands are:

```sh
python3 -m classification_bench preview --config /tmp/candidate-demo/config.json
python3 -m classification_bench run --config /tmp/candidate-demo/config.json
python3 -m classification_bench status --config /tmp/candidate-demo/config.json
python3 -m classification_bench recover --config /tmp/candidate-demo/config.json
python3 -m classification_bench export --config /tmp/candidate-demo/config.json --out /tmp/candidate-predictions.json
python3 -m classification_bench report --config /tmp/candidate-demo/config.json --labels examples/candidate/labels.json --out /tmp/candidate-report.html
```

Open the local HTML file in your browser. It contains private inputs and references, inline charts and filters, and no external scripts or network resources. Reports and exports never overwrite an existing output file. The report includes every planned position; incomplete and invalid outputs receive no agreement credit. Lifecycle state, parsed outcome and classification disagreement are separate measures. Requested routes and observed provider identity are shown separately. The report also distinguishes the requested model, completion model, frozen canonical model and generation metadata model; unavailable identities stay unavailable. Canonical metadata does not replace the completion identity used for price estimates. Unavailable timing, tokens and costs stay unavailable. Reasoning and cache counts come from the saved provider usage details when present; reasoning tokens are already included in completion tokens and are not added twice. A separate token-price estimate uses the frozen requested-route prices and standard input rates, without assuming cache savings. Its formula and snapshot hash are shown per request. Identity conflicts, unsupported charges or insufficient usage make that estimate unavailable; it never changes settlement.

The report starts with an unfiltered configuration/prompt comparison, including full-denominator agreement, repeat ranges and measurement coverage. Pass filters show a match count, no-results message and Reset filters. Contents links navigate to conditions and passes; selecting a hidden target clears the filters. Full request identity and telemetry evidence is expandable while measurement summaries stay visible.

Reference labels are passed only to `report` or `evaluate`. Changing a reference file produces a new report with a new reference hash; it does not rewrite historical evidence. Public deployment and public export of confidential inputs are not part of this workflow.

## Configuration

The generated JSON is the complete schema. Paths must be absolute. Required fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `task`, `experiment`, `inputs` | Separate task definition, matrix and permitted inputs |
| `database`, `artifacts` | Private SQLite state and immutable raw evidence locations |
| `scope`, `cap`, `currency`, `scale` | Explicit authorization scope and integer budget units |
| `max_concurrency` | Maximum independent configuration workers |
| `provider_limits` | Object mapping each adapter provider to its concurrent-request limit |
| `authorization_file` | Exact run-bound authorization JSON for live work; `null` for synthetic work |
| `on_budget_exhausted` | `pause` or `stop` |

Live USD amounts use scale `1000000`; for example cap `500000` means $0.50. Synthetic amounts use `SYN` and scale `1`. A smoke and a full experiment use the same configurable controls, with separate run directories, scopes and authorizations. There is no standing or inherited spending budget.

`preview` includes each request ID, input IDs, prompt, repeat, batch, route and conservative reservation. It shows blocked requests, including unsupported adapters and a cap smaller than a single-request bound. Unsupported native methods remain visible and are never silently substituted. The sum of reservations is a conservative worst-case planning bound, not an expected invoice. Requests are admitted only while settled charges plus active reservations plus unresolved holds plus the new reservation fit the current cap.

## At the budget limit

The scheduler first lets active work settle when it could free capacity. It does not ask for more money merely because another admitted request temporarily holds a reservation.

- `pause` records `paused_budget`, preserves the remaining queue, exits and reports the required operator action. It does not leave an unattended process waiting for keyboard input. An explicitly approved cap increase permits a subsequent `run` command to continue only never-dispatched work.
- `stop` records `stopped_budget` and forbids further dispatch for that run. Already dispatched requests finish or retain uncertainty. A new experiment requires a separate reviewed configuration and authorization; do not rerun completed work without intending new requests.

Neither policy cancels provider billing or treats an unknown charge as zero. An above-bound provider charge freezes admission even after a cap increase; it requires investigation. Configurable automatic top-ups and automatic retry are intentionally absent.

## Approve a larger cap

Do not edit the original run config or initial authorization. After reviewing `status`, the operator supplies a new authorization file with these exact fields:

```json
{
  "schema_version": 1,
  "run_sha256": "COPY_FROM_PREVIEW",
  "scope": "COPY_FROM_CONFIG",
  "amendment_id": "operator-approved-increase-001",
  "expected_cap": 500000,
  "new_cap": 750000,
  "authorization_source": "Explicit operator approval for this new total cap"
}
```

The numbers illustrate raising a total cap from $0.50 to $0.75, not adding $0.75. Apply only after that increase is authorized:

```sh
python3 -m classification_bench budget-increase --config /private/run/config.json --authorization /private/run/increase-001.json
python3 -m classification_bench run --config /private/run/config.json
```

The amendment is tied to the immutable run hash and current cap, applied atomically, and retained in immutable audit history. Repeating the identical amendment is idempotent; conflicting or stale increases fail. A cap increase does not release unknown-cost holds or resume a stopped run. Local authorization files are explicit operator assertions, not a remote identity or payment authorization service.

## Failure and recovery

Only requests with no durable dispatch intent may be sent after restart. A pre-intent claim left by a dead orchestrator is safely released under the exclusive process lock. Ambiguous requests are never replayed automatically. They block later work in their ordered configuration; other independently admitted configurations can continue within the shared cap.

Raw bounded response bytes and transport metadata precede parsing and terminal completion. `recover` verifies saved receipts and can reconstruct a parsed result after interrupted publication without sending another inference request. Missing attributable receipts keep the request uncertain and its reservation encumbered. Provider HTTP errors, invalid outputs and refusals are final observations for that attempt, not reasons to retry until the answer improves. Imported predictions and recovery do not create repeats.

The live adapter uses a tested macOS file boundary with scrubbed environment. Its OS profile permits TCP443 and DNS; the trusted adapter pins HTTPS destinations and rejects redirects. This is not a domain-based OS network restriction. Other platforms fail closed for live dispatch. See [OpenRouter controls](OPENROUTER.md) and the [pending smoke gate](LIVE_SMOKE_PLAN.md).

The report usage mapping follows the [OpenRouter chat response schema](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion) and [cache-token documentation](https://openrouter.ai/docs/guides/best-practices/prompt-caching). Provider generation time, client duration and pure inference time remain separate measures.

Runtime extensions and historical read compatibility follow the [adapter runtime contract](ADAPTER_RUNTIME.md). Saved reports use stored execution routes and build hashes; new dispatch fails closed when those builds change.


## Local credential setup

Use the repository-local `.env` for `OPENROUTER_API_KEY`; `.gitignore` excludes it. Keep its permissions at `0600`. The tracked `.env.example` contains no credential. The CLI reads the process environment, so load your trusted local file before an authorized run:

```sh
set -a
. ./.env
set +a
python3 -m classification_bench run --config /path/to/approved/config.json
```

Do not enable shell tracing while loading credentials. Never put a key in command arguments, run configuration, reports or commits. Loading `.env` does not grant spending authorization; the separate run-bound grant and selected budget still apply.

## Native decision models

Use [native decision operation](NATIVE_DECISIONS.md) for Liquid d1, Upstage Solar Decide and Alibaba Qwen decision-model-preview, and [Clef operation](CLEF_DECISIONS.md) for Cloudflare Clef and Clef-Flash. Each provider has its own credential variable and reviewed billing snapshot, while sharing the same preview, authorization, budget, recovery and report commands. These adapters are offline-tested; live provider acceptance remains pending. OpenAI Decisions remains [pending its public API contract](OPENAI_DECISIONS_STATUS.md).
