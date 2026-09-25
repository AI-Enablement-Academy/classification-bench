# Offline coordinator API

`classification_bench.coordinator.Coordinator` stores one logical request and its first attempt in a private, local SQLite database. It does not call a provider. Its `record_dispatch_intent` method records a durable boundary before a caller could send a request; the return value is an audit receipt, not live dispatch authorization. Standalone coordinator calls do not reserve money. For coupled claims and reservations, use the separate [atomic execution API](EXECUTION_API.md). Neither API calls a provider.

Create it with `Coordinator(path)`. New database files have mode `0600`. Existing database and SQLite sidecar files must be private regular files owned by the current user. Keep the database in private local storage outside Git. The module uses short `BEGIN IMMEDIATE` transactions and full SQLite synchronization on one host.

| Method | Contract |
| --- | --- |
| `enqueue(request_id, manifest_digest, request_artifact_digest)` | Add a request in `ready` state. Both digests are lowercase SHA-256 hex. An identical call returns the existing row; conflicting identity evidence fails. The manifest must be a full execution manifest supplied by the caller, not a v0.1 planning digest. |
| `claim(worker_id, lease_seconds)` | Atomically claim one `ready` request or an expired `claimed` request. Returns a row with a fresh token and incremented generation, or `None`. Recovery keeps the same attempt ID. |
| `record_dispatch_intent(request_id, token)` | Atomically accepts one current, unexpired claim and appends `dispatch_started`. A second call, expired token or previous holder fails. From this point, no lease expiry can requeue the request. |
| `complete(request_id, token, outcome, evidence_id, response_digest=...)` | Record `response_saved`, `not_sent` or `outcome_unknown` after intent. A saved response needs its byte digest. Identical repeated completion is a no-op; conflicting evidence fails. |
| `reconcile(request_id, reconciliation_id, outcome, response_digest=...)` | Resolve `outcome_unknown` with explicit `response_saved` or `not_sent` evidence. The original unknown event remains. This never requeues the request. |
| `get(request_id)`, `events(request_id)` | Read the current row and ordered immutable event history. |

The caller must publish and verify a request artifact before enqueueing its digest. The coordinator currently validates digest shape but does not read an artifact store. Likewise, a `response_saved` completion accepts a digest supplied by the caller; the caller must first publish and verify the response bytes through the artifact API. The coordinator cannot prove that a `not_sent` assertion is true. A timeout alone is not `not_sent` evidence.

Only an expired claim with no recorded dispatch intent can be reclaimed automatically. A crash after `record_dispatch_intent` leaves `dispatch_intent`, even if the external call never happened. An operator or future adapter must inspect process and provider evidence, then record an outcome. `outcome_unknown` and all completed states remain outside the claim queue. There is no retry API, next-attempt allocation, cancellation protocol, provider reconciliation, authorization check, reservation, settlement, or live execution path here.

Requests enrolled through the atomic execution API are excluded from standalone claiming, and their public mutation methods are guarded against bypassing coupled accounting. See [execution evidence contracts](EVIDENCE_CONTRACTS.md) for the remaining acceptance gates and [offline budget ledger API](BUDGET_API.md) for separate money accounting. A live runner needs one atomic admission boundary joining claim, verified capability and authorization evidence, and a budget reservation before any provider call.
