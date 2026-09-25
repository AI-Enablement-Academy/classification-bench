# Offline budget ledger API

`classification_bench.budget.BudgetLedger` is an offline SQLite primitive. It does not call providers, authenticate authorizations, verify price quotations or enforce subscription quotas. No live runner uses it yet. The existing case study keeps its original ledger and spending limits.

Every scope needs an explicit positive cap, currency, integer scale and authorization source. Amounts are integer subunits: a scale of 1,000,000 means one million units per currency unit. No default cap or permission is inferred. Separate scopes are separate authorizations; do not split one authorization into several scopes to multiply its cap.

| Method | Effect |
| --- | --- |
| `create_scope(scope, cap, currency, scale, authorization_source)` | Create explicit terms; identical repeated creation is allowed, conflicting terms fail. |
| `reserve(scope, attempt_id, amount, bound_source=...)` | Atomically admit one attempt within the shared cap. Duplicate attempt IDs fail. A zero reservation needs `no_fee_evidence` instead of a bound source. |
| `mark_unknown(scope, attempt_id, reason)` | Move an active reservation to an unresolved hold without releasing capacity. |
| `settle(scope, attempt_id, settlement_id, charge)` | Replace an active reservation or hold with the full observed charge. A zero charge needs `zero_charge_evidence`. |
| `balances(scope)` | Read disjoint known charges, active reservations, unknown holds, remaining capacity and freeze state. |
| `verify(scope)` | Replay audit deltas and compare them with the current attempts and balances. |

Settlement with the same attempt, settlement identity, amount and evidence is idempotent. Conflicting callbacks fail. An observed charge above the reservation is retained in full and freezes new reservations, even if the cap has not yet been exceeded. The ledger never clips a charge or treats missing usage as zero.

The implementation uses short SQLite `BEGIN IMMEDIATE` transactions and FULL synchronization. Tests exercise concurrent processes, restart, unknown holds, duplicate settlement and above-bound charges. No transaction spans a model call because this module has no model-call integration. Request claims, dispatch permits, cancellation, automatic retries, not-sent recovery and cap amendments remain future coordinator work.

New databases are created exclusively with mode 0600. Existing database files and SQLite journal/WAL/shared-memory files must be regular, owned by the current user and inaccessible to group/other users. Unsafe files are rejected without chmod or overwrite. This implementation targets the project's POSIX single-host environment; it is not a multi-host service. Keep the database in private local storage, outside Git and public exports.

Pricing and authorization evidence are caller-supplied strings. A future admission layer must bind verified source artifacts and check provider capabilities before a reservation can authorize dispatch. The ledger is necessary accounting machinery, not proof that external spending is safely integrated.
