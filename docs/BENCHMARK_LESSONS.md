# Lessons from the candidate-experience benchmark

These requirements come from operating the [source case study](https://github.com/adambkovacs/candidate-experience-benchmark), including its prompt and repeat experiments through 2026-09-28. Its runs are still progressing. Counts and balances in that repository are dated evidence, not permanent defaults for this tool.

## Execution must be routine

The case study accumulated model-specific launch scripts, manual smoke receipts, suffix continuations and hand-built publication snapshots. They preserved evidence but required too much agent time. Build one declarative matrix, durable queue, status command, adapter contract and report pipeline. Do not reproduce a new Python controller for each model, effort, prompt or interrupted suffix. An operator should be able to see exactly what is complete, running, failed, unknown, blocked and never sent.

Agent slots are not provider concurrency. Use code to run independent requests under provider limits and shared budgets; use agents for bounded implementation and review. Keep condition order and batch membership explicit. Queueing should follow a concrete limit, not an arbitrary one-worker default. Stop affected work when it reaches a real boundary without stalling unrelated admitted work.

The full requested roster must remain visible. A completed subset is not permission to remove expensive, awkward, native or blocked configurations. Separate the case study's completion from repeat-study completion and tool-development completion. A documented blocker explains unfinished work; it is not a completed run or an accepted scope exclusion.

Sources: [current goals](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/CURRENT_GOALS.md), [roster accounting](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/MVP_ROSTER_ACCOUNTING.md), [tool specification](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/HARNESS_SPEC.md).

## Preserve attempts and uncertainty

A connection failure can occur after a provider accepts work. An HTTP 429 can have unknown billing. A crash can leave a durable dispatch intent without a response. Preserve the raw outcome and hold the reservation; do not infer that a missing file means nothing was sent. Resume only provably never-sent work. Record any separately admitted continuation and its changed timing. Invalid outputs remain invalid; they must not be retried until a better score appears.

Save bounded raw bytes before decoding or parsing, including partial/error bodies. Bind response evidence to the request, parser version, runtime, route, attempt and budget settlement. Redact credentials if a service reflects them; record that redaction happened. Separate terminal completion from complete validity. A 60-position pass can contain failures, while an interrupted pass has both attempted and never-sent positions.

Tests must use isolated fixtures rather than assuming a live experiment directory is empty. In the case study, an order-gate test became stale once the formerly pending phase completed. Test resumed runs, concurrent claims, partial writes, unknown charges, wrong returned models, price drift and a crash after receipt publication as ordinary operating cases.

Sources: [Mistral continuation](https://github.com/adambkovacs/candidate-experience-benchmark/tree/main/results/repeatability-v1/openrouter-paid-mistral-small32-24b-venice-not-applicable/later-phases-v1), [Qwen rate-limit result](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/results/qwen36-on-p2-final19-v4/SUMMARY.md), [local verified execution contract](VERIFIED_EXECUTION.md).

## Keep model routes and interfaces distinct

A model name alone does not identify a configuration. Record exact provider, model ID and returned identity, quantization where known, runtime version, visible controls, context length, batch shape and hardware for local inference. Disable fallback and response repair when the experiment requires an exact route. Verify catalog capability and pricing before admission, then inspect returned identity and usage. Catalog availability does not prove serving capacity.

Use hosted routes for models intended to run hosted. Download local artifacts only when the exact native method or model is unavailable through a suitable hosted interface. Hugging Face discovery/download is different from hosted inference. Never silently replace a native specialist with a hosted chat model that shares its backbone.

Jev's native Choice questions, SemIf's direct/serial/shared modes, Laya, AnyJev and NLI methods need explicit adapter semantics. A generated-JSON control is a separate method. Native methods may not support chat-style system prompts or thinking effort. Report unsupported conditions clearly; do not fabricate equivalence. Laya's native context limits rejected the full inputs, while expanded-context variants did run. Those variants require a visible qualification because changing context settings changes the tested configuration.

Use supported subscription CLI authentication for GPT/Claude experiments where authorized. Isolate tools, repository instructions, hooks, MCP access, memory and unrelated context; a clean working directory alone does not prove isolation. Keep quota/account receipts private and include only necessary hashes and observable runtime evidence in exports. Do not enable paid overage or redeem reset credits implicitly.

Sources: [specialist registry](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/results/specialist-run-registry.json), [repeat coverage](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/REPEAT_COVERAGE_MATRIX.md), [Claude roster controls](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/CLAUDE_REPEAT_ROSTER.md).

## Budgets must cover concurrent work

Reserve before dispatch, settle observed charges once, and retain bounds for unresolved charges. Independent workers must share an atomic cap; per-process counters are insufficient. Child allocations encumber the master budget until reconciled. Release only verified unused amounts. Never report allocated or conservatively held money as an invoice charge.

Historical cost is a planning estimate. Provider reasoning and output length can vary; a cheap smoke does not guarantee a cheap development pass. Publish the distinction between observed provider cost, token-price estimate, unknown subscription cost and unresolved reserve. Subscription access is not evidence that individual requests cost zero. Do not transfer a case-study approval to a different project or task.

Source: [hosted wave budget inventory](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/HOSTED_REPEAT_NEXT_WAVE.md), [local budget contract](BUDGET_API.md).

## Repeats and reference review answer different questions

Keep P0 (existing prompt), P1 (classifier instructions) and P2 (classifier instructions plus SOP/decision process) as distinct prompt conditions. The tool should accept other named variants without code changes. Run three separately dispatched passes per condition where authorized. Count a historical pass only after auditing its request and failure policy; otherwise plan a new matched series. Smoke calls, retries and imported responses are not repeats.

Freeze prompt bytes, input membership, batch boundaries, model route, controls, parser and seed policy. Record CLI changes and hidden serving limitations rather than asserting equivalence. Compare prompt effects within each pass, then show their range across passes. Equal aggregate scores can conceal different per-record classifications. Repeated results on the same 60 inputs do not create 180 independent cases.

Reference labels belong only in offline evaluation. Review disputed references against a task-specific rubric and version corrections without rewriting prior scores. Model consensus can identify cases to examine; it cannot establish truth. Preserve AI-reviewed versus independently human-adjudicated reference status. A stable wrong answer, a changed valid label and an invalid response are different outcomes.

Sources: [repeat protocol](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/REPEATABILITY_PLAN.md), [repeat findings](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/REPEAT_CHECKPOINT_2026-09-28.md), [local scoring formats](FORMATS.md).

## Explain the results, including missing measurements

Show a metric's numerator, denominator and meaning where it appears. Valid output means the answer passed the schema, not that it matched the reference. Display per-field and all-field agreement, class support, confusion patterns, invalid/refused/failed counts, paired prompt deltas, repeat flips and changed cases. Avoid one aggregate leaderboard across incompatible tasks or execution conditions.

A sequential 60-request run's wall-clock duration is not inference latency. Keep model load, queueing, network time, client request duration, provider generation time, pure inference time and whole-run elapsed time distinct. Batch duration divided by ten is an amortized share, not a measurement of ten independent request latencies. Preserve absent token fields and inference measurements as null. Local timing depends on hardware, runtime and contention and should not be compared casually with hosted timing.

Default filters must not hide the models the experiment was designed to compare. The source site's hosted-only default obscured completed Laya and SemIf runs. Include visible specialist access and indicate exact execution route. Explain prompt variants in plain language, rather than assuming readers understand P0/P1/P2. Present a short findings narrative with charts for paired effects, repeat spread, class errors and cost/quality tradeoffs, with links to the underlying records.

Separate the public results view from private operational status, quota receipts, credentials and raw confidential content. Export only allowlisted fields. Build published reports from closed, hash-verified evidence; do not stage or publish files that active workers are still appending.

Sources: [public case study](https://adambkovacs.github.io/candidate-experience-benchmark/), [current publication goals](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/CURRENT_GOALS.md), [local evidence contracts](EVIDENCE_CONTRACTS.md).

## Reuse what earns its place

Keep the current coordinator and evidence boundaries while adding the missing execution and reporting pieces. The offline comparison of Inspect and promptfoo is already complete. Adopt a component when it reduces maintained code and operating effort without weakening the experiment contract. Avoid another framework survey, a full rewrite, a gateway, an authentication platform or a cluster scheduler as prerequisites for a usable first release.

Source: [completed framework comparison](FRAMEWORK_COMPARISON.md).
