# Adapter runtime contract

The matrix scheduler calls trusted runtime implementations registered by `settings.adapter` in [adapter_runtime.py](../classification_bench/adapter_runtime.py). Registration happens in application code; run configuration cannot import a Python module or execute a plugin path. A task's input fields and categorical vocabulary are independent of its runtime.

| Runtime method | Responsibility |
| --- | --- |
| `create_adapter(config)` | Validate the configuration's controls and create its request renderer/parser |
| `credential(supplied)` | Resolve the runtime's supported authentication mechanism; a runtime may need no secret |
| `source_digests(adapter)` | Bind adapter, runtime and transport builds in the execution manifest |
| `preflight(adapter, prepared, worker)` | Check serving capabilities, price bounds and required isolation before admission |
| `dispatch(adapter, prepared, credential, worker)` | Perform one admitted attempt; do not retry implicitly |
| `parse(adapter, result, ...)` | Interpret saved raw output against the expected request/model and ordered IDs |
| `supplement(adapter, parsed, credential, worker, artifact_root, config)` | Optionally fetch attribution/usage evidence, publish its raw bytes before parsing, and return explicit identity/cost outcomes |
| `recovery_identity_status()` | Describe the identity evidence available from local recovery without new inference |
| `zero_charge_evidence(observation)` | Cite explicit evidence when an observed charge is zero |

The scheduler retains ownership of ordering, shared reservations, dispatch intent, raw primary-response publication, task vocabulary validation, immutable observation records, terminal settlement and recovery. It does not select an OpenRouter endpoint, read an OpenRouter-specific environment variable, or issue a generation-metadata request itself. Those choices belong to `OpenRouterRuntime`.

The [runtime tests](../tests/test_adapter_runtime.py) register another request/response protocol and exercise the same scheduler. They also exercise explicit USD admission with a no-network fake runtime that needs no OpenRouter credential. These tests establish the extension boundary. The native Liquid, Solar and Qwen implementations use that boundary; see [native decision operation](NATIVE_DECISIONS.md) for their billing and verification limits. Claude Code and Codex now have registered subscription runtimes with offline matrix integration tests; their live acceptance remains pending. See [subscription accounting](SUBSCRIPTION_RUNNER.md).

Live runtimes default to `accounting_currency = "USD"`. Subscription runtimes declare `"REQ"`, with scale one and one reserved unit per fresh CLI invocation. This counts invocations, not opaque internal model calls or dollars. Parsed provider cost remains unknown. The scheduler settles consumed invocation capacity separately and preserves holds for ambiguous dispatch. Different accounting units currently require separate scopes. No run configuration can change a registered runtime's accounting unit.

## Historical evidence and changed code

Read-only export/report verifies the saved manifest and request against their enrolled hashes, immutable run/plan/control/schedule bindings and receipt evidence. It reports the stored route and source digests, so a runtime code edit does not relabel historical results. The original completed candidate and product demo archives remain readable after the runtime refactor.

New dispatch still compares the entire current rendered manifest and request with enrolled bytes. A changed adapter/runtime/transport build therefore cannot silently resume an old pending request. Use the original verified build to continue an existing experiment, or define a separately reviewed experiment with changed runtime identity. Historical recovery that requires parsing remains tied to the original parser contract; read compatibility is not permission to reinterpret old raw output under arbitrary new semantics.
