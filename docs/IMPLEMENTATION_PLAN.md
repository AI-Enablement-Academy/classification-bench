# First runner implementation plan

This increment follows [the approved task goal](NEXT_TASK_GOAL.md) and [the operational lessons](BENCHMARK_LESSONS.md). The existing 78-test baseline passed on 2026-09-28, including the macOS isolation tests outside the enclosing development sandbox. GitHub reported `PRIVATE` for `AI-Enablement-Academy/classification-bench`.

1. Preserve the offline planner, evaluator, immutable artifact store, SQLite coordinator and money ledger. Add a matrix runner using their existing admission and receipt boundaries.
2. Add one pinned OpenRouter chat adapter with strict controls, fresh endpoint checks, conservative integer reservations, bounded raw capture and no automatic retry. Separate requested route from observed model/provider evidence.
3. Enforce the reference-file boundary in a scrubbed macOS child. Permit the HTTPS transport required by the trusted fixed endpoint; do not describe TCP-port permission as domain isolation.
4. Run independent configurations concurrently, preserve declaration order within each configuration and apply shared provider limits. Resume only work without dispatch intent. Recovery verifies saved evidence without model calls.
5. Generate a private self-contained local report from verified exports plus separately opened references. Keep missing and invalid outputs in every denominator. Include prompt effects, repeat variation, cases, costs and nullable timing/token measurements.
6. Reproduce the workflow with fictional candidate feedback and a fictional product task. Test ordinary failures, interruptions, concurrent invocations, unknown charges and malformed responses. Review confirmed findings using [the repository rubric](../AGENTS.md).
7. Commit and push tested files to the existing private repository. Leave inference authorization and live verification pending. The [smoke plan](LIVE_SMOKE_PLAN.md) defines the subsequent gate.

No source-project inputs, active outputs, credentials, ledgers or publication files are migrated. The candidate fixture reuses only the documented categorical task vocabulary from [the historical offline import](CASE_IMPORT_VERIFICATION.md); its examples and references are fictional software fixtures.
