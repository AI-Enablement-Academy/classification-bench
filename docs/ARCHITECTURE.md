# Architecture

Status: v0.1 offline core implemented; live execution is proposed. Repository visibility is private under AI-Enablement-Academy.

## Product boundary

One project owns generic classification experiments. Domain-specific task packs provide input fields, rubric, allowed labels, dataset split and separately versioned references. The candidate-experience benchmark remains a separate case study and immutable evidence archive. Do not move or rewrite its active execution protocol during extraction.

The first release has two commands: plan and evaluate. A future execution command will consume a frozen plan and emit immutable attempt records. Scoring remains offline. A task pack must be reusable without editing provider code or forking the report UI.

## Data flow

Task + experiment + allowed inputs -> deterministic request plan -> adapter execution -> raw attempts -> strict parser -> offline scoring with versioned references -> report.

The current implementation begins at planning and resumes at saved predictions. The separate artifact API can store and verify externally supplied response bytes and parser bindings, but the evaluator is not yet wired to it. Neither component establishes real execution, billing enforcement or process isolation. Those are explicit next-stage contracts.

Request identities bind the full task, model/configuration, prompt text, repeat number, batch index and ordered input membership. The evaluator reconstructs the matrix and verifies the supplied plan. Output scores bind their source documents by canonical JSON SHA-256; these are semantic document hashes, not original-byte archive hashes.

## Experiments and repeats

Treat prompt condition, model configuration, repeat and attempt as distinct dimensions. Retry is an attempt of a logical request; repeat is a new independently executed request. Preserve both. An imported response is replay, not a repeat.

For a real repeat study, freeze membership, prompt bytes, model route, sampling settings, parser, context size and batch boundaries. Record seed policy, visible model revision and client version. Rotate condition order across repeated passes where practical. Separate fixed-seed reproducibility from varied-seed sampling sensitivity. Provider-side nondeterminism and hidden serving changes remain limitations even at temperature zero.

The reporting unit is an input record, grouped by scenario family where relevant. Repeats do not multiply independent sample size. Label stability, output validity and correctness are separate metrics. A consistently wrong answer is stable, and an invalid output is not a categorical flip.

See the [execution evidence contracts](EVIDENCE_CONTRACTS.md) for the next-stage records and acceptance gates. The artifact and parser-binding subset is implemented; execution and accounting gates remain specified.

## Live execution to extract next

Use a coordinator with SQLite on one host and immutable response artifacts. It should claim work in short transactions, reserve money before dispatch, and settle each attempt once. An uncertain started request retains its reservation and needs reconciliation; restarting must not blindly resend it. No database transaction spans inference.

Adapters receive only input capsules, task instructions, output vocabulary and execution controls. References and evaluation metadata stay in a separate process/store. Supported subscription CLIs, OpenRouter, LM Studio and native specialist interfaces require distinct adapters and capability evidence. Native Choice/NLI methods retain their original semantics; they are not forced into chat text.

Extract existing request builders, parsers and accounting contracts with attribution and regression fixtures. Do not copy secrets, account caches, local paths or all historical result folders. Live adapters must prove their isolation boundary; a clean working directory alone is not sufficient.

## Build versus adopt

Retain a thin project-owned task, identity, evidence and accounting layer. Evaluate Inspect AI and promptfoo offline before choosing scheduling or viewer components. Compare the same saved responses, invalid outputs, interrupted requests, duplicate settlements and missing metadata. Adoption must reduce code and operator work without changing experiment policy.

Inspect already supports evaluation sets, epochs, concurrency and resume; its retry and cleanup options need deliberate configuration. Promptfoo provides a declarative prompt/provider/test configuration. These capabilities are candidates for reuse, not grounds to claim they already satisfy our reference-isolation or shared-budget requirements. [Inspect eval sets](https://inspect.aisi.org.uk/eval-sets.html), [promptfoo configuration](https://www.promptfoo.dev/docs/configuration/reference/), checked 2026-09-25.

Do not rebuild a model gateway, authentication platform or cluster scheduler. The offline core intentionally depends only on Python's standard library while integration choices remain open.

## Publication and privacy

Private is the default for this repository and imported datasets. Publishing a report is an explicit allowlisted export. A source response may contain confidential hiring or customer information even when its aggregate score is safe to publish. No deployment workflow or public artifact upload is enabled in v0.1.
