# Execution evidence contracts

Status: design for the next implementation stage, 2026-09-25. The current planner and evaluator do not yet implement these records. This contract follows the source project's [system specification](https://github.com/adambkovacs/candidate-experience-benchmark/blob/main/docs/HARNESS_SPEC.md). It is independent of the pending framework comparison.

## Identity and storage

A logical request identifies one configuration, prompt condition, repeat, phase and ordered batch. A new attempt is not a new repeat. An import is replay and cannot establish model repeatability.

The v0.1 planner binds task, configuration, prompt and membership by canonical JSON SHA-256. Before live execution, a versioned execution manifest must additionally bind rendered message roles and bytes, adapter and parser build hashes, resolved controls, retry and cache policy, seed policy, and schedule. Do not silently reinterpret a v0.1 plan as a complete execution manifest. Reference hashes belong only to an offline evaluation manifest, never to the worker request.

Raw artifacts use SHA-256 of their actual bytes, length, media type and a relative content-addressed location. Save request bodies and response/event bytes, excluding credentials and unrelated account data. Document any transport redaction. Canonical JSON hashes and byte hashes are different fields. A parsed projection never replaces original response bytes.

Publish an artifact durably before committing an event that refers to it. Use a temporary file on the same filesystem, flush and fsync, then publish without replacing an existing destination and sync the directory. Verify an existing object with the same digest before reuse. A crash may leave an orphan artifact; it must not leave a committed response event pointing to absent bytes. Default storage is private. Public reports are a separate allowlisted export.

## Attempt events

Each event has schema version, event ID, experiment and execution-manifest digest, request ID, attempt ID, sequence number, event type, UTC timestamp and producer build. Attempt ordinals are unique within the request. Repeat identity comes from the plan and never from the number of attempts.

| Event | Required evidence |
| --- | --- |
| admitted | Exact capability snapshot, inspected smoke receipt, authorization scope, reservation or subscription-quota decision |
| claimed | Worker identity, lease generation and request-artifact digest |
| dispatch_started | Durable evidence recorded immediately before calling the provider; later crashes are conservatively ambiguous |
| response_saved | Original response artifact, observable provider request/model IDs, finish status and usage evidence |
| not_sent | Evidence that no transport dispatch occurred; a timeout alone cannot establish this |
| outcome_unknown | Possible dispatch with no definitive response; retain money hold and do not automatically resend |
| cancelled | Local stop status, separate provider cancellation confirmation, remaining outcome and billing uncertainty |
| reconciled | Source evidence resolving the earlier ambiguity; append the finding without deleting the original event |

A request cannot be claimed twice concurrently. A lease expiry is not evidence that inference stopped. Recovery must query the actual process or provider handle where possible; otherwise keep the attempt ambiguous. A replacement attempt requires the declared retry policy and a new reservation. Runtime reconciliation does not use reference labels.

Parsing is a separate immutable record binding response digest and parser build. States are valid, invalid or unavailable, with structured reasons. An unavailable response is not an invented semantic label. A valid but wrong prediction is not retried. Selecting an attempt for evaluation uses a frozen policy independent of references; all attempts remain visible.

## Provider capability snapshot

Each capability is supported, unsupported or unknown, with source and observation time. Capture role placement, schema enforcement, reasoning controls, seed control, model revision, provider routing, cache control, hidden retries, tools, cancellation, idempotency, usage, costs and timing telemetry. Requested controls and observed controls are separate. An accepted argument is not proof that the provider applied it.

Native choice, NLI and other specialist calls retain their interface and call topology. A multi-call record has explicit child request IDs; its aggregate usage is the sum of disjoint children. Chat batching and provider batch jobs are distinct request types. Their latency cannot be presented as individual-record latency.

## Money and usage

Store nonnegative integer monetary subunits with currency and scale, or exact decimal strings. Never use binary floating point for admission. No budget is implicit: each experiment names its authorization scope, cap and source. Imported historical costs do not authorize new spending.

Keep disjoint totals for observed settled charges, unresolved charge holds and active reservations. Their sum plus a proposed reservation must fit the cap in the same transaction that creates the reservation. A known provider-side price ceiling and a defensible bound on every chargeable component are required for hard-cap execution. Unknown tokenizer or reasoning billing cannot be replaced with an optimistic token estimate.

Each attempt settles once by a unique settlement identity. An identical repeated callback is a no-op; a conflicting callback is rejected and escalated for explicit reconciliation. Missing cost does not settle to zero. An ambiguous attempt transfers its reserve to a hold without releasing capacity. A charge above reserve is recorded in full, leaves an over-cap state if necessary, and stops further dispatch. Charges are never clipped to make the ledger balance.

Record input, output, cached and reasoning token counts as separately sourced nullable values. Mark overlap rules before computing totals; do not add reasoning tokens twice when included in output tokens. Preserve raw provider usage. Prices are either observed charges, estimates with their price snapshot and formula, or unknown. Subscription fees are not allocated as zero per request.

## Timing

Use monotonic elapsed time within one worker for durations and UTC timestamps for chronology. Distinguish queue delay, client request duration, time to first token, provider generation duration and pure inference duration. Only populate the latter when the provider actually exposes that quantity. Unknown timing stays null with a reason.

Do not sum concurrent request durations and call it elapsed run time. Report the wall-clock run span separately. Dividing a batch duration by its record count gives an amortized share, not measured per-record latency. Local hardware results remain identified by exact runtime and available hardware details; they do not estimate hosted speed.

## Offline acceptance gates before credentials

The next implementation must prove these cases with a simulated provider and fresh temporary storage:

1. Two workers racing for one request yield one claim and one dispatch permit.
2. Concurrent reservations cannot exceed a shared cap; separate authorization scopes remain separate.
3. A crash before dispatch can be recovered without pretending a call occurred; a crash after dispatch-start retains uncertainty and does not resend.
4. A response artifact survives a crash before the terminal database event; recovery verifies its hash before recording it.
5. Repeated settlement is idempotent; conflicting settlement fails; a later charge resolves a hold without counting it twice.
6. Invalid and missing outputs remain in the full denominator and cannot trigger content repair.
7. A worker receives only allowlisted inputs and cannot access sentinel references through the enforced execution boundary. Merely omitting the labels path is not an OS-isolation test.
8. Restart preserves every raw attempt, unknown charge and repeat identity. A replay produces no model call and is never reported as a new repeat.

These are required tests, not claims that a simulator or provider adapter already passes them. Framework adoption must preserve these boundaries, and a framework's own resume command is not sufficient evidence.
