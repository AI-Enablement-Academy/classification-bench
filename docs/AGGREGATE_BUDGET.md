# Aggregate allocations in one private ledger

The [budget ledger](../classification_bench/budget.py) can now reserve a parent cap for multiple managed child scopes in one authoritative SQLite database. Each child receives an explicit allocation for its whole cap. Child admission and settlement check the parent within the existing transaction boundary; a committed above-bound charge stops sibling admission.

The runner's version-2 configuration connects separate smoke and full runs to this ledger. Automatic phase selection, mixed-unit scheduling, shared provider concurrency and combined report composition remain separate requirements. The [execution audit](EXECUTION_GAP_AUDIT_20261008.md) records the remaining requirements and live prerequisites. Creating ledger terms does not authenticate spending authority, verify provider prices or authorize inference.

## Operator commands and managed runs

An aggregate specification has exactly these fields. This is a synthetic example; replace the absolute database path with a private local destination.

```json
{
  "schema_version": 1,
  "database": "/private/selected/authority.sqlite",
  "scope": "example:aggregate",
  "cap": 10,
  "currency": "SYN",
  "scale": 1,
  "authorization_source": "fictional offline allocation example"
}
```

Use `python3 -m classification_bench.cli aggregate-create --spec aggregate.json` to create the authority and `aggregate-status --spec aggregate.json` to inspect it. Both accept `--out` for exclusive private JSON output. Keep the original specification bytes unchanged: their SHA-256 is bound to the initial authority, including after a cap increase. USD uses integer microdollars at scale `1000000`; REQ and SYN use scale `1`.

Status remains available while a runner holds its execution lock. Balance verification uses a SQLite transaction and may briefly wait for another ledger transaction. It uses the existing ledger constructor, rather than promising a read-only database connection. Create and increase commands retain the exclusive runner lock.

For each existing runner configuration, set `schema_version` to `2` and add an `aggregate` object containing exactly `parent_scope`, `allocation_id` and `phase`. Phase is `smoke` or `full`. Use the parent's database, a unique child `scope` and allocation ID, and the child's explicit `cap`. All other [runner fields](RUNNER.md) remain required. Allocation happens on initialization; the whole child cap stays encumbered even after its requests settle.

Managed phases preserve the logical request IDs inside provider capsules and exported predictions. SQLite execution identities additionally bind the frozen run hash, so overlapping smoke and full inputs remain separate attempts. Operations expose both `request_id` and `storage_request_id`. A phase's stop control does not stop another phase; a parent safety block or money freeze prevents sibling admission. An old singleton run cannot be attached to a managed database implicitly.

An inherited execution block reports `blocked_safety` with `review_safety_block` and the original reason/evidence. An above-bound parent settlement reports `blocked_budget_freeze` with `review_budget_freeze` and its separate `aggregate_freeze` record. Both are visible before a sibling has any allocation. Neither condition spends the sibling's pause/stop policy or creates its allocation. Increasing a cap does not resolve either condition.

To increase the parent, use `aggregate-increase --spec aggregate.json --authorization amendment.json`. The amendment has exactly `schema_version: 1`, `aggregate_spec_sha256`, `scope`, `amendment_id`, `expected_cap`, `new_cap` and `authorization_source`. Its hash identifies the original specification bytes; `expected_cap` identifies the current cap. An identical amendment is idempotent. A conflicting or stale amendment fails. This command rejects frozen or safety-blocked parents. A child increase uses the existing `budget-increase --config ... --authorization ...` command, which now amends its allocation atomically within unused parent capacity.

These commands manage explicit local accounting terms. They do not change provider billing settings, release unknown holds, authorize inference or clear a stopped run. Existing live authorization and preflight requirements still apply.

## Create and allocate

The API uses integer subunits, as in the [existing budget contract](BUDGET_API.md). Parent and children share a currency and scale; optional explicit child terms must match. Separate USD and REQ parents can coexist, but their amounts are never converted or added into one money total.

```python
from classification_bench.budget import BudgetLedger

# Fictional offline accounting example. No provider is called.
ledger = BudgetLedger("/private/selected/authority.sqlite")
ledger.create_aggregate("example", 10, "SYN", 1, "explicit fixture authority")
ledger.allocate_child("example", "example:smoke", "smoke-allocation", 4,
                      "a" * 64, "explicit fixture smoke authority", phase="smoke")
ledger.allocate_child("example", "example:full", "full-allocation", 6,
                      "b" * 64, "explicit fixture full authority", phase="full")
view = ledger.verify_aggregate("example")
assert view["allocated_cap"] == 10
assert view["unallocated"] == 0
```

Select an existing private parent directory for the database. New database files use `0600`; unsafe existing files and sidecars are rejected. The example's sources and hashes are fictional, rather than declarations about this project's live budget.

| Method | Contract |
| --- | --- |
| `create_aggregate(scope, cap, currency, scale, authorization_source)` | Create explicit parent terms. Identical creation is idempotent, including after a later cap increase; original terms remain the creation contract. An existing ordinary scope cannot be converted implicitly. |
| `allocate_child(parent_scope, child_scope, allocation_id, cap, run_sha256, authorization_source, *, phase=None, currency=None, scale=None)` | Atomically create a new child and allocate its whole cap. The run hash must be a lowercase SHA-256 digest. Phase is explicitly `smoke`, `full` or unavailable; names never determine it. Allocation ID, child scope and run identity cannot be reused for a different child. |
| `allocation_for(child_scope)` | Return detached frozen binding/current allocation metadata, or `None` for an unmanaged scope. An execution integration must compare the bound run hash with its actual frozen run before admission. |
| `increase_allocation(child_scope, amendment_id, expected_cap, new_cap, authorization_source)` | Increase allocation and child cap in one commit after checking unused parent capacity. Identical amendments are idempotent; stale/conflicting amendments fail. |
| `increase_cap(parent_scope, ...)` | Apply the existing explicit, conditional cap amendment to the parent. Direct increases of a managed child are rejected; use `increase_allocation`. |
| `aggregate_balances(parent_scope)` / `verify_aggregate(parent_scope)` | Show separate allocation and usage categories. Verification replays parent/child balance audits and checks allocation amendments against child cap history. |

All operations use short `BEGIN IMMEDIATE` transactions and FULL synchronization. A failed allocation or amendment publishes no partial child/cap state. Allocations remain retained after use or failed later initialization; no refund or release API exists. Existing unmanaged scope behavior is unchanged.

## Read balances without counting twice

An allocated cap is capacity promised to a child. It is separate from a charge, an active attempt reservation or an unknown-charge hold.

| Aggregate field | Meaning |
| --- | --- |
| `allocated_cap` | Sum of retained current child caps. |
| `known_charges` | Sum of child settled amounts, in this parent's accounting unit. For REQ these are consumed invocations, not dollars. |
| `active_reservations`, `unknown_holds` | Sum of child active or unresolved attempt amounts. Unknown exposure is retained. |
| `accounted_exposure` | Sum of `max(child allocated cap, child known + active + held)`. Actual usage is not added again to the cap that already covers it. |
| `unallocated` | Parent cap minus allocated child caps. Use does not refund this capacity. |
| `scope_remaining` | Parent cap minus accounted exposure, including negative values after observed overruns. |
| `remaining`, `frozen` | Effective admission capacity/state. A parent money freeze or explicit parent execution safety block makes remaining capacity at most zero. |
| `scope_frozen`, `freeze`, `admission_block` | Intrinsic monetary freeze and its first immutable child/attempt/settlement evidence, or a separate explicit execution block. These causes remain distinct. |
| `children` | Every child balance and its allocation/run/phase binding, in stable child-scope order. |

Managed child balances also expose `scope_frozen`, `scope_remaining`, `aggregate_frozen` and `aggregate_admission_block`. Their ordinary `frozen` and `remaining` fields report effective admission, so a scheduler cannot keep retrying a child whose parent has stopped it. Intrinsic capacity remains visible in `scope_remaining`.

For parent cap 10 and child caps 4 and 6, the allocation total remains 10 even after both children settle zero charges. If the first child reserves 2 and returns charge 3, the full charge is saved and the parent freezes, although 3 is below the child cap of 4. If it returns 12, accounted exposure becomes `max(4, 12) + max(6, 0) = 18`, with remaining exposure capacity `-8`; the ledger clips neither charge nor exposure.

## Stop sibling admission atomically

Managed reservations check parent allocation coverage and freeze state in the same transaction as child reservation. This includes existing [ExecutionLedger](../classification_bench/execution.py) calls, whose reservation and dispatch intent share that commit. An aggregate parent cannot reserve attempts directly; provider work belongs to a managed child.

A child settlement above its attempt reservation records the whole amount, freezes child and parent, and stores the first parent cause in one commit. Late settlement of an unknown hold uses the same rule. Existing admitted work may complete and preserve its evidence. Identical settlement remains idempotent; cap increases and restart cannot clear a freeze.

When the execution layer has an `execution_admission_blocks` table, an explicit block on the parent also stops managed child admission, new allocations and allocation increases. The block's reason/evidence is retained separately from monetary overrun evidence. Child-only blocks retain their existing scope; the integration must explicitly propagate a shared-account or experiment-wide safety finding to the parent when appropriate. This layer does not infer account relationships from model or scope names.

Ordinary reserve/settlement APIs continue to reject attempts owned by ExecutionLedger. Use its atomic API for those attempts, rather than bypassing request state or settlement ownership.

## Preserve one authority

Creating the first aggregate binds the database to an immutable database ID, canonical path and OS file identity. Opening a copied database elsewhere, or replacing the file inode with a copied snapshot at the same path, fails before BudgetLedger schema changes. Original-path restart on the same file remains supported. Parent-directory aliases resolving to that file do not create a second authority.

Moving or replacing the authoritative database inode fails closed; the implementation does not automatically adopt the copy. An owner can still overwrite the current file's bytes with an old snapshot while preserving its inode; identity checks cannot detect that operation. Such rollback can erase recorded charges and dispatch state, violates the immutable-ledger contract and is outside supported receipt recovery. A rollback-resistant restore would require a separate durable fence and a reviewed recovery contract. Guarantees are local to the declared authoritative database, not multiple hosts, independent authority files or owner-controlled rewrites.

The parent cap bounds admitted allocations under the declared enforceable provider bounds. It cannot prevent an unobserved provider overcharge. A request cap bounds admitted CLI invocations, not opaque internal calls, provider token quota or unknown subscription dollars. Preserve these limitations before execution; a ledger row is not evidence that paid extra usage is disabled.

## Verification

The [aggregate tests](../tests/test_aggregate_budget.py) cover exact allocation/usage arithmetic, retained unknown holds, separate units, copied authority rejection, immutable binding/audit history, conditional cap changes, real-process allocation/amendment races, committed overruns blocking a sibling process, explicit parent safety blocks, atomic rollback and inherited ExecutionLedger admission/settlement. [Legacy budget](../tests/test_budget.py) and [execution](../tests/test_execution.py) tests check existing behavior alongside the new layer.

The combined aggregate, legacy budget/execution, admission-guard, verified-recovery and request-accounting suite passed 79 tests in 4.041 seconds, no skips. These results include 23 new aggregate cases; they do not accept a subsequent scheduler integration or live workflow.

```sh
python3 -m unittest tests.test_aggregate_budget tests.test_budget tests.test_execution -v
```

No test performs provider inference or reads credentials. The operator workflow and exact live acceptance still need integration and independent verification before this ledger layer can close the aggregate-budget goal.
