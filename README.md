# classification-bench

A reusable benchmark core for categorical classification tasks: define the task, compare prompts and model configurations, and measure both agreement and repeatability.

**Current status: the generic matrix runner and private local report are implemented; the expanded release remains in progress.** The [report explorer](docs/REPORT_EXPLORER.md) includes declared model groups, composed filters, selected comparisons and a measured client-duration plot. Native [Clef/Clef-Flash smoke and full acceptance](docs/CLEF_LIVE_ACCEPTANCE_20261002.md) completed 42 valid responses; exact dollar charges remain unavailable and USD 0.454188 remains held. The [authorized OpenRouter product smoke](docs/LIVE_IDENTITY_SMOKE_RESULT.md) completed three valid requests for $0.000174 in rounded charges, with delayed model/provider metadata independently verified. Latest report visual and keyboard checks remain pending. Define categorical tasks, compare configurations and prompts, choose repeats and batches, preview exact work, and execute under a budget shared within each run. Both smoke and full runs support user-selected caps and budget exhaustion policies: pause for an explicit increase, or stop. [Managed smoke/full scopes](docs/AGGREGATE_BUDGET.md) now share atomic aggregate allocations. [Frozen smoke/full workflows](docs/WORKFLOW.md) now select inputs and repeats, schedule USD/REQ/SYN groups under shared concurrency, and compose phase-specific reports.

The expanded release is in progress: [task import](docs/TASK_SETUP.md), [subscription execution](docs/SUBSCRIPTION_RUNNER.md) and the [source-pinned parity matrix](docs/FEATURE_PARITY.md) now guide implementation. Optional-reference scoring, exact run/case comparison and [evidence-linked findings](docs/FINDINGS_ANALYSIS.md) are now offline verified. The shared [presentation](docs/PRESENTATION.md), [reference sensitivity](docs/REFERENCE_SENSITIVITY.md), complete class metrics and [private downloads](docs/REPORT_EXPORTS.md) are offline verified. [Repeat analysis](docs/REPEAT_ANALYSIS.md) adds per-field flips, excluded-case reasons, fixed repeat ranges and declared-origin evidence to report and presentation findings. [Generic operator reproduction](docs/GENERIC_OPERATOR_ACCEPTANCE_20261008.md) covers recruitment and warehouse tasks offline. [Subscription account-check renewal](docs/SUBSCRIPTION_ASSERTIONS.md), aggregate accounting and [OpenRouter discovery/reasoning controls](docs/OPENROUTER.md) have offline coverage. [Explicit model declarations](docs/MODEL_METADATA.md) keep family, purpose and sourced training lineage separate from execution route and measured findings. A [fresh-environment operator check](docs/WORKFLOW_ACCEPTANCE_20261008.md) passed both fictional examples. Claude Code/Codex live acceptance and rendered visual-quality acceptance remain pending.

Start with the [smoke/full operator workflow](docs/WORKFLOW.md), [individual runner](docs/RUNNER.md), [task and result formats](docs/FORMATS.md), and [implementation status and remaining verification gates](docs/IMPLEMENTATION_STATUS.md). Synthetic examples test the software, not model quality or nondeterminism.

For a new implementation task, start with the [handoff](docs/HANDOFF.md), [goal description](docs/NEXT_TASK_GOAL.md) and [benchmark lessons](docs/BENCHMARK_LESSONS.md).

## Why a separate project

The [Candidate Experience Feedback Benchmark](https://github.com/adambkovacs/candidate-experience-benchmark) tested four decisions about candidate-written reviews. Its results exposed reusable needs: strict output validation, visible missing answers, versioned references, exact request identities, cost accounting, and repeatability measurements. This repository separates those capabilities from one recruitment dataset.

Each task defines its own inputs, label vocabulary and rubric. Possible task packages include:

| Task | Inputs | Example decisions |
| --- | --- | --- |
| Candidate testimonials | Candidate-written feedback | Sentiment, follow-up, serious concern, testimonial potential |
| Interviewer feedback | Interview evidence and competency rubric | Evidence present, competency category, clarification needed |
| Ideal customer profile | Company description and explicit ICP criteria | Segment, criterion match, missing evidence |
| Candidate/job-description alignment | Candidate evidence and job requirements | Requirement supported, contradicted, or unknown |

Employment-related examples evaluate evidence against a declared rubric; a benchmark score does not establish suitability for autonomous hiring decisions. Task authors must define and review the reference criteria. No real candidate data is bundled.

## Run the offline example

Python 3.10 or later is sufficient. Runtime code uses the standard library and needs no API key.

```sh
python3 -m classification_bench plan   --task examples/task.json   --experiment examples/experiment.json   --inputs examples/inputs.json   --out /tmp/classification-plan.json

python3 -m classification_bench evaluate   --task examples/task.json   --plan /tmp/classification-plan.json   --labels examples/labels.json   --predictions examples/predictions.json   --out /tmp/classification-results.json

python3 -m unittest discover -s tests -v
```

Choose fresh output paths. Existing files are never overwritten.

The example has three fictional product descriptions, two categorical fields and three supplied replay passes. It intentionally contains one label change and one invalid prediction. The evaluator accounts for all nine planned positions and returns exact-match rates of 1, 2/3 and 2/3. This tests the analysis pipeline; no LLM was run.

## Supported now

- Custom named string inputs and any number of categorical output fields, each with a declared vocabulary.
- A configuration × prompt × repeat matrix, with fixed ordered batch membership.
- Content-derived request IDs that change with inputs, prompt bytes, model settings or repeat number.
- Strict predictions: extra fields, missing fields and unknown labels are invalid outcomes.
- Full-denominator exact agreement, per-label precision/recall/F1, confusion counts and macro-F1.
- Per-pass scores and their mean/range, plus per-field and whole-response flip rates between repeat pairs.
- Explicit IDs and denominators for comparable, changed and excluded repeat positions.
- Offline reference scoring, with SHA-256 bindings for task, plan, labels and predictions.
- A Python artifact-store API for raw bytes and immutable parser projections, with verified source bindings and concurrent publication.
- An offline SQLite [budget API](docs/BUDGET_API.md) for atomic reservations, unresolved holds and idempotent settlements.
- An offline [request coordinator](docs/COORDINATOR_API.md) with leased claims, stale-worker fencing and explicit crash reconciliation.
- An [atomic execution API](docs/EXECUTION_API.md) joining claims, reservations and dispatch intent, with terminal accounting in the same database transaction.
- A [verified execution wrapper](docs/VERIFIED_EXECUTION.md) that checks stored request/response bytes and immutable attempt receipts before recording response completion.

The [simulated runner](docs/SIMULATED_RUN.md) runs a declared single-configuration, single-prompt experiment across all records and repeats, with verified manifests, explicit recovery and label-free prediction export. Its macOS worker enforces file and network restrictions; unsupported hosts fail closed.

Reference labels are a separate file, opened only by offline `evaluate` and `report`. Plans contain the allowed output vocabulary, which is part of the task, but no answer key. The planner has a data-interface boundary; the simulated execution path separately uses the tested [macOS isolation boundary](docs/ISOLATION.md).

## Reading the metrics

Missing and invalid predictions earn no exact-match credit and remain in the scheduled denominator. Per-label recall treats them as missed true labels. Precision uses valid predicted labels; invalid outputs do not invent a predicted class. Macro-F1 averages over every declared label, including unsupported classes whose F1 is defined as zero. Inspect support counts alongside that metric.

Flip rates compare only positions with valid predictions in both passes and report excluded IDs. A rate of zero over no comparable positions is meaningless, so the output uses null. Three passes are a useful diagnostic, not a precise estimate of population variability. Repeated answers to three inputs are still three distinct inputs, not nine independent cases.

Changing prompts, models, providers, batch membership, sampling policy or reference versions creates a different comparison. Recovery attempts and cached replay do not count as fresh model repetitions.

## Matrix runner and report

```sh
python3 -m scripts.offline_demo --task candidate --directory /tmp/candidate-demo
python3 -m scripts.offline_demo --task product --directory /tmp/product-demo
```

Each command runs a full synthetic matrix and writes a private local HTML report. The report includes outcome denominators, field and exact agreement, class support, confusion counts, paired prompt effects, repeat ranges/flips, supporting cases and separately sourced timing/token/cost evidence. Operator-declared model groups, separate adapter categories and model/provider/route/prompt controls narrow the comparison view; select two conditions to compare their recorded values. The agreement-versus-client-duration plot discloses measured coverage, excludes synthetic timing and keeps fixed axes when filtered. Whole-experiment totals stay fixed. Sticky section navigation and reduced-motion support guide exploration. Filters include every planned condition by default. Reference labels are opened only after the runner produces its verified report snapshot.

The same runner accepts an [OpenRouter configuration](docs/OPENROUTER.md) after an explicit run-bound authorization. Caps are operator settings for both smoke and full runs. At exhaustion, `pause` preserves the queue for an audited cap increase; `stop` permanently stops new dispatches for that run. Neither releases unknown charges. The original `simulate` workflow remains available and uses its existing offline sandbox.

OpenRouter has partial live verification; the remaining acceptance checks are recorded in the [implementation status](docs/IMPLEMENTATION_STATUS.md). The HTTPS child enforces a tested macOS file boundary; other operating systems fail closed for live execution. Native [Liquid, Solar, Qwen and Cloudflare decision adapters](docs/NATIVE_DECISIONS.md) have offline coverage and require reviewed billing evidence before live admission. [OpenAI Decisions](docs/OPENAI_DECISIONS_STATUS.md) awaits a verified public API contract. Claude Code and Codex have registered subscription adapters, request-count budgets and offline matrix tests. Read-only account/isolation preflight has been checked on this host; model inference and real extra-usage-off verification remain pending. See [subscription execution](docs/SUBSCRIPTION_RUNNER.md). No public deployment or source-project migration is included.

The core accepts categorical fields. Multi-label sets, numerical scores, rankings, multimodal inputs and free-text rationale scoring need separate contracts; they are not silently treated as categorical tasks.

[Source project and reuse decisions](docs/PROVENANCE.md) · [Task and result formats](docs/FORMATS.md)
