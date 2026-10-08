# Renewing a subscription account assertion

[SubscriptionAssertionLedger](../classification_bench/subscription_assertions.py) stores dated account assertions outside the frozen experiment. A fresh operator check can therefore renew the guard without rewriting the configuration, plan, request identity, provider capsule or historical evidence.

The ledger verifies local bindings, timestamps and evidence hashes. It does not inspect an account, authenticate the operator or establish that a provider has disabled paid extra usage. Its records say `operator_assertion`. Actual account state still requires the operator's account check under [subscription operation](SUBSCRIPTION_RUNNER.md).

## Original assertion and revisions

A guard belongs to one `(scope, run_sha256, config_id)`, with the original configuration hash and `codex` or `claude_code` adapter bound separately. The scope must already exist with `REQ` units at scale `1`; its run must match the existing singleton benchmark binding or the exact scope in the managed-run binding.

Revision `0` copies the original assertion's `extra_usage_disabled`, `verified_at` and `source`. An expired original assertion remains recordable as history so an ordinary paused run can be renewed. Recording that history does not permit dispatch. A false disabled assertion, malformed timestamp or future initial check is rejected.

Each renewal appends a revision linked to its predecessor. Its account check must be newer than the preceding check, no later than the current UTC time and at most 24 hours old. Both the selected revision and its evidence remain immutable. Missing or altered evidence causes verification to fail.

A cap amendment changes capacity only. It does not refresh an account assertion, release an unknown hold, clear a safety block or resume a stopped run. Renewal likewise leaves all budget balances, unknown outcomes, settlements and scope blocks unchanged. A scope blocked for observed paid extra usage, quota exhaustion or an isolation failure still requires investigation after a new account check.

## Renewal authorization

The authorization uses these exact fields:

| Field | Required value |
| --- | --- |
| `schema_version` | Integer `1` |
| `renewal_id` | A new, nonempty trimmed identifier for this renewal |
| `run_sha256`, `scope`, `config_id` | The unchanged exact run and configuration guard key |
| `configuration_sha256`, `adapter` | The original configuration hash and subscription adapter |
| `expected_revision` | The current nonnegative integer revision |
| `extra_usage_disabled` | Boolean `true`, following an actual operator account check |
| `verified_at` | That check's UTC timestamp, for example `2026-10-08T08:00:00Z`; the example is not account evidence |
| `source` | A nonempty description identifying the actual account check, without control characters |
| `account_check_sha256` | Lowercase SHA-256 of the exact separately supplied evidence bytes |

The account-check file is operator supplied. It can contain a dated observation or another bounded account-settings record, with the appropriate media type. The ledger preserves the supplied bytes in the private content-addressed artifact store; it does not infer their meaning from a filename or treat their hash as remote verification. Evidence must be nonempty and at most 1,000,000 bytes. Keep credentials out of it.

The stored revision includes the evidence's hash, size, media type and artifact reference, the authorization's canonical JSON hash, predecessor identity, expiration time and recording time. It never adds this account evidence to a provider capsule. Retrying the identical renewal ID, authorization, evidence and media type returns the original revision. That retry does not extend its expiration. A conflicting ID reuse or stale expected revision fails; concurrent renewals cannot silently replace one another.

## Integration API

| Method | Behavior |
| --- | --- |
| `SubscriptionAssertionLedger(execution, artifact_root)` | Adds immutable revision and guard-admission audit tables to the existing execution database. |
| `bind_initial(scope, run_sha256, config_id, configuration_sha256, adapter, assertion)` | Records the original assertion once. `assertion` uses exact keys `extra_usage_disabled`, `verified_at`, `source`. Identical repeats return revision `0`; changed original terms fail. |
| `renew(authorization, account_check_bytes, *, media_type="application/json")` | Appends one fresh, run-bound revision with its private evidence. |
| `current(scope, run_sha256, config_id)` | Returns the latest verified immutable record. Reading a record does not establish that it is still fresh. |
| `SubscriptionAssertionLedger.read_current(database, artifact_root, key)` | Opens existing SQLite state with `mode=ro`, verifies the same bindings/history/private evidence and returns the latest record. An absent database, assertion table or key returns `None`; unsafe or inconsistent state fails. It creates no database, tables, scopes or bindings. |
| `history(key)` | Verifies and returns the complete revision chain and retained evidence. |
| `require_fresh_in(conn, key, expected_revision=None, *, request_id=None, admission_token=None)` | Checks freshness and the persistent safety block inside the caller's active admission transaction. It can also bind the exact storage request and claim token to the selected assertion in that transaction. |

The admission hook must run before capacity reservation and dispatch intent. It opens no independent transaction and performs no reservation or dispatch. A rollback of the caller's admission transaction also rolls back its guard audit. The supplied request must be enrolled and currently claimed under the same scope and exact token. Managed runs use their authoritative storage request ID, rather than the logical request ID inside the provider capsule.

The benchmark runner selects the effective assertion immediately before preflight, passes it into the execution attestation, requires the same revision during admission and rechecks its age before dispatch. The immutable adapter configuration stays unchanged. Direct users of the lower-level ledger must supply the admission hook; creating the ledger alone does not enforce dispatch protection on a caller that omits it.

Append an authorized check with `python3 -m classification_bench.cli account-check-renew --config run.json --authorization renewal.json --evidence account-check.json`. Optional `--out` writes a new mode-0600 JSON file. The command verifies the exact run, configuration, revision and evidence hash; it performs no dispatch. A subsequent `preflight` reads the verified revision without creating a database or admission state, and `run` uses it without changing the frozen experiment. The [workflow regression](../tests/test_subscription_renewal_workflow.py) covers an expired run, renewal, completion and restart without duplicate dispatch.

If a guard expires after durable dispatch intent but before the local CLI worker launches, the current generic exception path conservatively retains an unknown-outcome hold. Renewal does not replay that intent. This is a documented residual limitation: distinguishing a proven prelaunch refusal needs an explicit worker outcome, while ambiguous launches must continue retaining their holds.

Read-only preflight can use `read_current` without initializing execution state. Its SQLite read transaction keeps the returned revision chain consistent if a renewal commits concurrently. A missing guard returns control to the original frozen assertion; a malformed database, changed binding or missing/private-permission failure in existing evidence must not be treated as an absent guard.

Expired checks leave unadmitted work available for a later authorized renewal. Already admitted responses may still complete, settle or recover under the existing [execution contract](EXECUTION_API.md). A renewal cannot establish that an ambiguous attempt was never sent and does not authorize its replay.

## Offline evidence

[The focused tests](../tests/test_subscription_assertions.py) cover renewal from expired history, unchanged run identity and budgets, false/future/expired checks, stale and conflicting renewals, concurrent writers, private evidence, immutable revisions, transaction rollback, exact claim tokens, singleton and managed bindings, retained safety blocks and unknown holds, and recovery of historical outcomes.

These tests use fictional account-check evidence and local ledgers. They perform no account changes, credential reads or provider inference. They do not establish current billing state or live route acceptance.
