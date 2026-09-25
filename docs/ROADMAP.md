# Delivery plan

## Completed: offline foundation

Task contracts, matrix planning, request IDs, strict categorical evaluation, full-denominator metrics, repeat stability, synthetic fixtures and tests. No real model requests or new benchmark data.

## Current: evidence contracts and execution coordinator

1. Completed: [bounded offline comparison](FRAMEWORK_COMPARISON.md) of pinned Inspect and promptfoo versions. Keep the project coordinator as the planned execution/accounting owner; both tools remain candidates for narrower integrations. Transitive license review and real adapter gates remain open.
2. Partially complete: immutable raw artifacts and parser bindings implement part of the [evidence contracts](EVIDENCE_CONTRACTS.md). The [offline budget ledger](BUDGET_API.md) implements atomic reservations, unknown holds, idempotent settlement and audit replay. Complete attempt lifecycle, provider capability/usage binding and dispatch integration next. Keep request duration, provider generation time and pure inference time distinct.
3. Completed: [replay one existing candidate-experience run](CASE_IMPORT_VERIFICATION.md) by explicit source hashes. The generic evaluator matches 60 valid outputs and all saved per-field scores. Source data remains external; this is not execution provenance or a new repeat.
4. Partially complete: the [offline coordinator](COORDINATOR_API.md) now provides atomic leased claims, stale-worker fencing, durable dispatch intent and explicit reconciliation without automatic replay of uncertain attempts. Ledger tests cover restart, duplicate settlement and uncertain-charge holds. The reviewed [atomic execution API](EXECUTION_API.md) now joins claims, budget reservations and dispatch intent in one transaction, and joins terminal outcomes with settlement or retained unknown-cost holds. Its 42-test suite covers concurrent admission, rollback, legacy API fencing and idempotent callbacks. The [verified execution wrapper](VERIFIED_EXECUTION.md) now verifies stored request/manifest bytes before admission and saved response/attribution receipts before completion, with 53 passing offline tests and independent review. A crash before receipt indexing still requires manual orphan discovery, and provider attribution remains caller-supplied. Next prove unattended recovery across that crash window, complete execution-manifest validation, and enforced label isolation before attaching credentials. The case study continues on its existing adapters.

## Then: live adapters and the first real repeat study

Add OpenRouter, supported subscription CLI adapters and native specialists incrementally. Carry exact routing and model controls, separate provider retries, and a shared authorized budget. An adapter must pass smoke inspection and identity checks before a full run.

The case-study user has requested repeats for P0, P1 and P2. Keep each requested configuration/condition in an explicit coverage matrix, including blocked or unsupported entries. Use three fresh passes per condition, or two additional passes only when the historical first pass is demonstrably comparable. Estimate costs and admit execution against the existing case-study caps before launching. Prioritizing a wave must not silently remove remaining configurations from scope. This repository has no separate live spending authorization.

## Then: reusable task packs and reports

Import the candidate-experience task first. Add ICP and other tasks with their own independently reviewed labels. Interview feedback and candidate/JD evidence alignment require clear definitions of evidence, uncertainty and decision scope. Share scoring infrastructure, not unexamined judgment policy.

Build report views for confusion patterns, class balance, paired prompt differences, repeat flips, cost/quality tradeoffs and reference-version sensitivity. Keep case-level evidence accessible. Do not rank tasks with incompatible label distributions on one aggregate leaderboard.

## Excluded from the first release

Hosted multi-user service, real-time hiring decisions, distributed compute, automatic reference relabeling, LLM judges as a default substitute for references, and a full migration of historical benchmark evidence.
