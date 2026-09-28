# Separate-task handoff

Verified on 2026-09-28. The local checkout is `/Users/adamkovacs/Documents/codebuild/classification-bench`, on `main`, with remote `https://github.com/AI-Enablement-Academy/classification-bench.git`. GitHub visibility is private. Before these documentation updates, local HEAD and `origin/main` both pointed to `78c253e`, with no working-tree changes. The directory is already a Git checkout; do not create a nested clone.

Use [the goal description](NEXT_TASK_GOAL.md) as the new task's starting instruction. This handoff contains enough context to begin without the source conversation. Read [benchmark lessons](BENCHMARK_LESSONS.md) before designing an adapter or report.

## Ownership

The separate task owns implementation and documentation in this repository. The original case-study task continues its model runs and publication in `/Users/adamkovacs/Documents/codebuild/recruitment-feedback-demo`, whose GitHub name is now `adambkovacs/candidate-experience-benchmark`. Do not edit its frozen inputs, runner code, active outputs or ledgers. Historical folder names are intentional and do not identify another project to clone.

No agent from the original task is assigned to implement this private repository after handoff. If another task is already writing here, coordinate file ownership or use an isolated worktree before editing. Do not duplicate active case-study requests.

## Verified implementation checkpoint

The implementation at `78c253e` includes:

- Generic categorical task and experiment contracts, deterministic matrix planning, strict offline scoring, confusion metrics and repeat comparisons.
- An immutable artifact store, parser bindings and verified request/response attribution receipts.
- SQLite budget reservations, settlements and retained unknown-cost holds; leased claims and stale-worker fencing; atomic dispatch admission and completion.
- A macOS offline worker boundary with restricted file access, denied network access, scrubbed environment and bounded execution.
- A one-command simulated runner, explicit recovery after interrupted publication and label-free prediction export.
- A hash-verified replay of one existing 60-record case-study result, plus an offline Inspect/promptfoo comparison.

The checkpoint had 78 passing offline tests, including real macOS isolation and process-crash recovery tests. Run them again in the new task. The simulation uses fake transport and accounting. It does not enforce real provider spending, authenticate a model, or prove a live adapter. Live provider integrations and a local report UI are still missing.

## Start here

1. Read `AGENTS.md` and [README](../README.md), then [roadmap](ROADMAP.md), [architecture](ARCHITECTURE.md) and [formats](FORMATS.md).
2. Inspect [simulated execution](SIMULATED_RUN.md), [verified execution](VERIFIED_EXECUTION.md), [atomic execution](EXECUTION_API.md), [budget API](BUDGET_API.md), [isolation](ISOLATION.md) and [evidence contracts](EVIDENCE_CONTRACTS.md).
3. Run `python3 -m unittest discover -s tests -v`. On macOS, OS isolation tests must run with the permissions they need; distinguish environment restrictions from product failures.
4. Make a bounded first-adapter plan with explicit capability, identity, credential, isolation, budget and recovery boundaries. Implement and test it offline before proposing an authorized live smoke.
5. Connect the verified exported evidence to offline evaluation and a local report. Preserve the existing simulated workflow and historical compatibility while extending it.

See [framework comparison](FRAMEWORK_COMPARISON.md) before starting another framework survey. See [source import verification](CASE_IMPORT_VERIFICATION.md) and [provenance](PROVENANCE.md) before reusing source-project artifacts.

## Authorization and completion

Keep this repository private. No new live spending budget, provider credential transfer, public deployment or real dataset publication is granted by the handoff. The original case-study caps are separate. Prepare a concrete smoke configuration, input provenance, expected request count and maximum budget before requesting live authorization. A missing live approval should stop only that gate, not independent implementation, tests or report work.

The product should run without repeated agent supervision. A collection of adapters that still needs a person to issue per-phase commands, move files and hand-edit result reports does not meet the goal. Track the remaining work in the roadmap and report verified boundaries plainly.
