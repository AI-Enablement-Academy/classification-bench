# Reusable classification and decision benchmark

Continue the private classification benchmark repository:
https://github.com/AI-Enablement-Academy/classification-bench
Local path: /Users/adamkovacs/Documents/codebuild/classification-bench

Use this working benchmark as the functional reference:
https://github.com/adambkovacs/candidate-experience-benchmark
Local checkout: /Users/adamkovacs/Documents/codebuild/recruitment-feedback-demo

Build a reusable, local-first classification and decision benchmark tool that people can run on their own use cases, inputs, decision definitions and reference labels, using their own OpenRouter API token or authenticated Claude Code/Codex account.

Required execution scope is OpenRouter, Claude Code, Codex and the native adapters already implemented in classification-bench. Match the reference project's task workflow, evaluation, exploration and presentation functionality across these routes. Recruitment feedback must be a configurable example of the generic tool.

Preserve the existing implementation and evidence. Do not restart the project, repeat completed inference unnecessarily, or migrate the active reference benchmark into unfinished infrastructure.

1. Establish the baseline and parity requirements.

Read AGENTS.md, README.md, docs/HANDOFF.md, docs/NEXT_TASK_GOAL.md, docs/BENCHMARK_LESSONS.md and the current execution, budget, isolation and acceptance contracts. This goal supersedes older project guidance where they conflict, including older implementation-agent model defaults.

Inspect the latest reference repository without changing its active checkout, datasets, runs or budgets. Pin the reviewed commit and create a feature-parity matrix linking demonstrated source behavior to generic implementation, tests and acceptance evidence. Distinguish working features from design proposals such as HARNESS_SPEC.md.

Retrieve relevant shared Ruflo decisions and ReasoningBank patterns before substantial work. Save verified reusable decisions and patterns with project-qualified identifiers and verify shared persistence. Preserve existing session memories and never store credentials.

2. Make task setup reusable.

Provide a documented initialization, import and validation workflow for user-owned text or structured records, stable IDs, named input fields, categorical decision fields, allowed labels, task rubrics, instructions/SOPs, prompt variants, references and dataset splits.

Support JSON/JSONL and a documented CSV import path. Freeze the actual files, mappings and instructions used by each experiment. Support arbitrary task names, field names, label vocabularies, record counts and prompt names without changing engine or report code.

Keep reference labels and adjudication notes outside inference capsules. Define abstention, missing labels and invalid outputs explicitly. Unlabeled inputs may be classified and compared, but must not receive invented accuracy scores. Reference corrections create new evaluation versions without overwriting original evidence.

3. Implement the required execution routes.

OpenRouter:
- Accept the user's token through an ignored private environment file or environment variable.
- Support explicit model IDs and catalog discovery without a hand-maintained model allowlist.
- Validate endpoint availability, protocol, controls, limits and pricing.
- Support any model compatible with the declared task and adapter contract; explain incompatible combinations during preflight.
- Expose supported reasoning/effort and generation controls as experimental settings.
- Freeze provider selection and fallback policy. Never silently substitute models, routes, settings or response formats.

Claude Code and Codex:
- Implement real adapters using supported noninteractive CLI interfaces and the user's existing account authentication.
- Verify installed versions, authentication mode and supported controls.
- Record requested and observable model identity, effort, CLI version and usage limitations.
- Use fresh sessions for independent work.
- Enforce and test configurable isolation from references, unrelated repository context, tools, hooks, MCP, skills and memory. Disclose unavoidable CLI-supplied context.
- Fail preflight when required reference protection cannot be enforced.
- Verify paid extra usage is disabled where applicable. Never silently switch to a paid API, enable overage or redeem credits.
- Handle quota exhaustion, cancellation and ambiguous interruptions safely.

Claude Code and Codex adapters are required release features, not placeholders.

Preserve the existing Liquid, Solar, Qwen and Clef/Clef-Flash adapters and their native choice/probability semantics. Keep model family, declared purpose, verified training lineage, output interface and execution route separate. Show unknown metadata honestly.

Keep OpenAI's native decision API pending until a public contract and access are verified. Codex execution does not establish native decision API support.

Inventory additional local and specialist execution methods from the reference repository in a separate extension backlog. They are outside this release unless the user expands the execution scope. Feature parity does not require rerunning the reference project's entire historical model roster.

4. Provide one deterministic operator workflow.

Use the same experiment format and commands for validation, model preflight, preview, smoke, full run, status, safe resume/recovery, offline evaluation, export and report generation across adapters.

Routine operation must not require an LLM agent or a custom controller for each model.

Support configurable prompt variants, reasoning settings, batch shapes and independently dispatched repeats. Freeze input membership, prompt bytes, model configuration, parser and evaluation versions.

Keep attempts, retries, fresh repeats, imported evidence, continuations and replay distinct. Unsupported conditions must remain visible. Use deterministic code for scheduling, hashing, accounting and scoring.

5. Make budgets and recovery user-controlled.

Expose separate smoke and full-run caps, an aggregate experiment cap, concurrency limits and budget-exhaustion behavior.

Support:
- Pause: preserve pending work and explain how to authorize a versioned cap increase and resume.
- Stop: prevent further dispatch for that run.

Do not implement automatic top-ups or indefinite unattended approval waits.

Reserve shared capacity atomically before dispatch, reconcile charges once, preserve unknown-charge exposure and audit amendments. Distinguish actual provider charges, estimates, allocations, unresolved holds and subscription usage. Unknown per-request subscription cost is not zero cost.

Monetary guarantees require enforceable bounds. Where unavailable, explain that limitation before execution and offer applicable request, token or quota limits.

Save raw responses and execution receipts before parsing. Preserve invalid, refused, failed, uncertain and never-sent outcomes in the full planned denominator. Recovery must not automatically resend possibly dispatched work.

6. Reach report and presentation parity.

Build a polished, private, comparison-first report with task and methodology context, scoped findings, clear sections, synchronized filters, search, numeric sorting and selected A/B comparisons.

Provide filters for model group, model, provider, execution route, output interface, reasoning setting, prompt, repeat and lifecycle status where applicable. Include general LLM, fine-tuned LLM, decision-model and unspecified reporting groups without inventing architecture or training claims.

Default views must account for the whole planned experiment. Filters must disclose their scope and preserve whole-experiment totals.

Provide:
- Exact run and case inspection, predicted/reference values and failure or missing states.
- Cross-run A/B differences and reproducible run/case selections in local report URLs.
- Links from charts, findings and comparisons to exact supporting evidence.
- All-field and per-field agreement, output validity, class support, precision, recall, F1 and confusion.
- Paired prompt gains/losses, repeat ranges, label flips and difficult/disagreement case cohorts.
- Separate historical and declared fresh cohorts, with distinct-configuration denominators and unusable counts.
- Two-run agreement/deferral analysis using a declared all-fields-equal rule: accepted-correct, accepted-error and deferred counts, all eligible pair results, case drilldown and cost/source disclosure.
- Explicitly hypothetical reference-sensitivity exploration that never mutates saved references.
- Downloadable allowlisted data with source hashes.
- An accessible presentation mode.

Do not cherry-pick favorable pairs, pool incompatible tasks, treat repeated observations of the same cases as independent samples, or turn descriptive findings into deployment guarantees.

Present quality, cost, token and timing comparisons only when measurements support them. Separate client duration, provider timing, pure inference time and run elapsed time. Show missing coverage and exclude synthetic measurements from real-provider comparisons. Probability output alone does not prove calibration.

Use the reference project's current report as the primary functional reference. Use Recruitly and Cloudflare's benchmark sites as additional visual references. Apply relevant design and writing skills, restrained motion, useful click/scroll exploration, keyboard navigation, visible focus, responsive layouts and reduced-motion support.

7. Preserve privacy and existing authorization boundaries.

Keep classification-bench private. Credentials belong in an ignored private project environment file, never source, reports or commits.

The authorized shared credential lookup location is /Users/adamkovacs/Documents/codebuild/.env. Use only relevant credentials within existing authorization. Separate private raw evidence from deliberately sanitized exports. Public deployment or dataset publication is not implied.

Prepare code, offline tests and exact smoke plans before live execution. Each plan must specify provider, model, task/input provenance, request count, cost bound, cap, exhaustion policy and authentication source.

This goal does not expand existing inference or subscription authority. Dispatch when existing explicit authorization covers the prepared scope; otherwise request the missing authorization without re-requesting permission already granted.

Reconcile new authorized spending against this project's existing aggregate USD 10 allowance and ledger, including previous charges, allocations and unresolved holds. Do not assume USD 10 remains unspent or import the reference project's budgets. Account upgrades, payment changes and additional spending require explicit authorization.

8. Use subagents aggressively, with intelligent model selection.

Delegate substantial independent work across implementation, adapter integration, tests, UI/UX, documentation and adversarial review. Give each agent a bounded deliverable, explicit file ownership, relevant context and concrete acceptance criteria. Avoid competing edits and duplicate investigations.

Use GPT-6.1 Sol with xhigh reasoning for the majority of substantial implementation tasks. It is also suitable for integration, difficult debugging and detailed review. Do not escalate merely because a task is large.

Use lower-cost models and lower reasoning effort for bounded inventories, straightforward edits, source collection and routine verification. Prefer deterministic scripts for counting, hashing, reconciliation and running existing commands.

Use a stronger model only for a specific unresolved architecture, experimental-validity, security or financial-correctness problem that the normal implementation model cannot resolve. Explain the escalation and keep it bounded.

Choose the model and reasoning effort explicitly when spawning each agent. If the requested combination is unavailable, report the limitation and select the closest suitable available option.

Keep coordination and integration with the primary agent. Use independent reviewers for significant changes, especially authentication, budgets, recovery, evidence integrity and experimental validity. Follow the BLOCKING/RESIDUAL review rubric. Resolve confirmed BLOCKING findings and record RESIDUAL findings.

9. Verify and deliver.

Run python3 -m unittest discover -s tests -v after code changes, plus relevant CLI, adapter-contract, isolation, budget, recovery, import and report interaction checks.

Commit and push verified increments with exact-file staging. Confirm the remote remains private.

The goal is complete only when:
- The source-pinned parity matrix accounts for every applicable capability, with no requested feature silently deferred.
- An independent operator can install the tool and complete the workflow on a recruitment example and an unrelated user-defined classification/decision task without changing engine or report code.
- OpenRouter, Claude Code and Codex execute through the same generic workflow, with offline contract/failure tests and bounded authorized live acceptance for each route.
- Other native providers have separate, honest acceptance status.
- Budget exhaustion, concurrent admission, quota failure, interruptions and safe recovery are demonstrated without duplicate ambiguous dispatch or lost outcomes.
- Reports and presentation views cover complete, partial, failed, missing-data and unlabeled cases.
- Exact final artifacts pass rendered visual, keyboard, responsive and interaction checks in a permitted browser or through documented operator observations.
- Documentation, reproducible examples, evidence links and the private remote match the verified implementation.

Respect tool-policy denials. If a verification surface is unavailable, keep that acceptance gate pending while continuing independent work; do not treat static tests as rendered acceptance.

Finish with a requirement-by-requirement audit distinguishing implemented, offline-verified, live-verified and pending capabilities. Do not declare completion while a required gate remains unverified.
