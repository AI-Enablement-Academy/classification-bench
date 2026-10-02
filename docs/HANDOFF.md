# Implementation handoff

Current working increment: 2026-10-02 in `/Users/adamkovacs/Documents/codebuild/classification-bench`. The private repository is `AI-Enablement-Academy/classification-bench`. The generic runner and report are implemented. Native Liquid, Solar, Qwen and Cloudflare Clef/Clef-Flash categorical adapters and a report explorer are the current extension; see [native operation](NATIVE_DECISIONS.md), [Clef operation](CLEF_DECISIONS.md) and [report explorer](REPORT_EXPLORER.md). [OpenAI Decisions](OPENAI_DECISIONS_STATUS.md) is pending a public contract.

The active release goal is [NEXT_TASK_GOAL.md](NEXT_TASK_GOAL.md). The updated OpenRouter identity path has [three-request live evidence](LIVE_IDENTITY_SMOKE_RESULT.md). Direct visual/keyboard verification of the changed report remains pending. Earlier user readability acceptance applies to the earlier report. On 2026-10-02 the user authorized this project's smoke tests and runs up to USD 10 total. The prepared Clef/Flash smoke and full scopes receive separate run-bound allocations totaling USD 2.50, with pause and retained unknown-cost holds. The active candidate-experience benchmark remains separate.

Use [implementation status](IMPLEMENTATION_STATUS.md) for final verification counts and limits, and [operator workflow](RUNNER.md) for commands. The latest model-group and client-duration plot update passes 203 offline tests and independent review. [Report inspection](REPORT_UX_CHECK.md) names the exact final saved-evidence reports and the unexecuted mixed fixture; earlier HTML does not accept this interface.

The [2026-09-30 independent recheck](OPERATOR_RECHECK_20260930.md) reproduced all three fictional workflows. The [release audit](RELEASE_ACCEPTANCE_AUDIT.md) records the remaining visual gate and the applicability limits of saved live evidence. [Clef live acceptance](CLEF_LIVE_ACCEPTANCE_20261002.md) completed all 42 prepared requests, with no added dispatch on completed restart/recovery and USD 0.454188 retained unknown-cost holds. The other [native smoke proposals](NATIVE_SMOKE_PLAN.md) retain access/billing prerequisites. The [Cloudflare account setup check](CLOUDFLARE_ACCOUNT_SETUP.md) has actual-account previews, a verified account-restricted token in the private local `.env`, and working subscription reads. No Workers Paid subscription was listed and the completed scopes had no quota failures. The main setup environment is `/Users/adamkovacs/Documents/codebuild/.env`, as explicitly authorized by the user. No subscription or payment change occurred.

## Ownership

The separate task owns implementation and documentation in this repository. The original case-study task continues its model runs and publication in `/Users/adamkovacs/Documents/codebuild/recruitment-feedback-demo`, whose GitHub name is now `adambkovacs/candidate-experience-benchmark`. Do not edit its frozen inputs, runner code, active outputs or ledgers. Historical folder names are intentional and do not identify another project to clone.

No agent from the original task is assigned to implement this private repository after handoff. If another task is already writing here, coordinate file ownership or use an isolated worktree before editing. Do not duplicate active case-study requests.

## Original offline checkpoint (superseded)

The implementation at `78c253e` includes:

- Generic categorical task and experiment contracts, deterministic matrix planning, strict offline scoring, confusion metrics and repeat comparisons.
- An immutable artifact store, parser bindings and verified request/response attribution receipts.
- SQLite budget reservations, settlements and retained unknown-cost holds; leased claims and stale-worker fencing; atomic dispatch admission and completion.
- A macOS offline worker boundary with restricted file access, denied network access, scrubbed environment and bounded execution.
- A one-command simulated runner, explicit recovery after interrupted publication and label-free prediction export.
- A hash-verified replay of one existing 60-record case-study result, plus an offline Inspect/promptfoo comparison.

The checkpoint had 78 passing offline tests, including real macOS isolation and process-crash recovery tests. Run them again in the new task. The simulation uses fake transport and accounting. It does not enforce real provider spending, authenticate a model, or prove a live adapter. Live provider integrations and a local report UI were missing at that checkpoint; both are now implemented, with verification limits described above.

## Continue here

1. Read `AGENTS.md`, [README](../README.md), [benchmark lessons](BENCHMARK_LESSONS.md), and the [release acceptance audit](RELEASE_ACCEPTANCE_AUDIT.md).
2. Use [RUNNER.md](RUNNER.md), the [custom task walkthrough](CUSTOM_TASK_WALKTHROUGH.md), and [FORMATS.md](FORMATS.md) for generic task configuration and operation. The [adapter runtime contract](ADAPTER_RUNTIME.md) covers future providers without scheduler changes.
3. Run `python3 -m unittest discover -s tests -v` before code changes. Use the latest result in [implementation status](IMPLEMENTATION_STATUS.md), including its host-specific isolation caveats.
4. Follow [OPERATOR_CHECK.md](OPERATOR_CHECK.md) for independent reproduction and report inspection. Do not claim these checks passed without observations.
5. Preserve the inference authorization boundary. Existing completed attempts are evidence, not permission to dispatch again. Do not repeat the original implementation or expand the live experiment to fill a release gate.

See [framework comparison](FRAMEWORK_COMPARISON.md) before starting another framework survey. See [source import verification](CASE_IMPORT_VERIFICATION.md) and [provenance](PROVENANCE.md) before reusing source-project artifacts.

## Authorization and completion

Keep this repository private. The user's dated USD 10 inference approval and Cloudflare credential setup authorization are recorded in [the current goal](NEXT_TASK_GOAL.md); they do not authorize a subscription upgrade, public deployment or real dataset publication. The original case-study caps are separate. Prepare concrete configurations, input provenance, request counts and budget allocations before additional dispatch. Preserve prior exposure within the aggregate cap. A missing prerequisite should stop only that gate, not independent implementation, tests or report work.

The product should run without repeated agent supervision. A collection of adapters that still needs a person to issue per-phase commands, move files and hand-edit result reports does not meet the goal. Track the remaining work in the roadmap and report verified boundaries plainly.
