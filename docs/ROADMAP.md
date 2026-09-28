# Delivery plan

The separate implementation task starts from [HANDOFF.md](HANDOFF.md) and [NEXT_TASK_GOAL.md](NEXT_TASK_GOAL.md). Operational requirements from the case study are recorded in [BENCHMARK_LESSONS.md](BENCHMARK_LESSONS.md).

## Completed: offline foundation

Task contracts, matrix planning, request IDs, strict categorical evaluation, full-denominator metrics, repeat stability, synthetic fixtures and tests. No real model requests or new benchmark data.

## Historical checkpoint: evidence contracts and execution coordinator

1. Completed: [bounded offline comparison](FRAMEWORK_COMPARISON.md) of pinned Inspect and promptfoo versions. Keep the project coordinator as the planned execution/accounting owner; both tools remain candidates for narrower integrations. Transitive license review and real adapter gates remain open.
2. Partially complete: immutable raw artifacts and parser bindings implement part of the [evidence contracts](EVIDENCE_CONTRACTS.md). The [offline budget ledger](BUDGET_API.md) implements atomic reservations, unknown holds, idempotent settlement and audit replay. Complete attempt lifecycle, provider capability/usage binding and dispatch integration next. Keep request duration, provider generation time and pure inference time distinct.
3. Completed: [replay one existing candidate-experience run](CASE_IMPORT_VERIFICATION.md) by explicit source hashes. The generic evaluator matches 60 valid outputs and all saved per-field scores. Source data remains external; this is not execution provenance or a new repeat.
4. Partially complete: the [offline coordinator](COORDINATOR_API.md) now provides atomic leased claims, stale-worker fencing, durable dispatch intent and explicit reconciliation without automatic replay of uncertain attempts. Ledger tests cover restart, duplicate settlement and uncertain-charge holds. The reviewed [atomic execution API](EXECUTION_API.md) now joins claims, budget reservations and dispatch intent in one transaction, and joins terminal outcomes with settlement or retained unknown-cost holds. Its 42-test suite covers concurrent admission, rollback, legacy API fencing and idempotent callbacks. The [verified execution wrapper](VERIFIED_EXECUTION.md) now verifies stored request/manifest bytes before admission and saved response/attribution receipts before completion, with independently reviewed artifact checks. Explicit bounded orphan discovery now covers a crash after receipt publication but before indexing; a real subprocess-crash test restarts without a returned receipt ref and recovers once. Provider attribution remains caller-supplied, and incomplete or conflicting evidence never authorizes a resend. A tested [macOS offline worker boundary](ISOLATION.md) now enforces capsule-only reads outside runtime allowances, network denial, a scrubbed environment and bounded execution. Real OS tests verified these properties using synthetic files. The reviewed [simulated execution command](SIMULATED_RUN.md) now connects strict manifest validation, budget admission, isolated request execution, explicit receipt recovery and verified label-free export. All 78 offline tests pass, including real macOS isolation and recovery beyond 10,000 stored objects. This remains a fake transport with synthetic accounting; provider capability, identity, usage, pricing and authorization checks remain gates before credentials. The case study continues on its existing adapters.

## Implemented: first matrix runner and private report

The [matrix workflow](RUNNER.md) and [OpenRouter adapter](OPENROUTER.md) are implemented with offline tests. It includes pinned endpoint checks, a macOS file-isolated HTTPS worker, concurrent configurations, provider limits, explicit no-retry behavior, raw/transport recovery, visible unsupported configurations, and a local report from a locked verified snapshot. Fictional candidate feedback and product fixtures run without credentials.

Smoke and full-run budgets are explicit user settings. `pause` preserves remaining work pending an audited cap increase; `stop` permanently stops new requests in that run. Unknown charges stay encumbered and above-bound charges freeze admission.

See [implementation status](IMPLEMENTATION_STATUS.md) for the verification boundary. No live adapter or release-complete claim is made yet.

## Pending: authorized live smoke and operator handoff

The operator approved the [three-request smoke](LIVE_SMOKE_PLAN.md) with a $0.50 cap and pause at exhaustion. The [smoke evidence](LIVE_SMOKE_RESULT.md) records one unknown attempt and two HTTP 200 responses, with strict output failures and missing generation metadata. No approved positions remain. Verify serving identity, actual usage/billing, report output and idempotent restart. Have a second operator reproduce the documented workflow. Browser rendering has not been visually inspected because the browser tool blocked the local file URL.

The active candidate-experience study retains its existing inputs, workers, outputs, publication and budgets in its own repository. Its approvals do not authorize work here. Subscription CLI, native Choice/NLI adapters, real task datasets and broader benchmark runs each need explicit scope and task-specific rubrics. The runner lists unsupported methods instead of substituting a hosted chat model.

## Excluded from the first release

Hosted multi-user service, real-time hiring decisions, distributed compute, automatic reference relabeling, LLM judges as a default substitute for references, and a full migration of historical benchmark evidence.
