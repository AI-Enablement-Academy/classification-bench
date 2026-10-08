# Minimal live workflow plan, 2026-10-08

The read-only inventory at `2026-10-08T03:11:55.974865Z` reconciled the saved live
ledgers as **313 microUSD in known charges,
zero active reservations and 559,151 microUSD in unresolved holds**. Their
combined recorded exposure is **559,464 microUSD ($0.559464)**. Retaining the
reviewed historical allocations leaves **$6.50 of allocation headroom** under
this project's documented USD 10 ceiling. This plan proposes a separate,
one-request OpenRouter workflow smoke. Claude Code and Codex remain pending
their paid-fallback checks and exact model selection.

This preserves that inventory and the subsequent offline proposal; later live
acceptance has separate evidence. This is not a live authorization. No inference,
credential copying, account changes, budget amendments or hold releases were
performed during this inventory and preparation. The only new remote reads were OpenRouter's public endpoint and model
identity catalogs, with no credential. Preparation and preview created no
execution database, evidence store or authorization file.

## Evidence and accounting

The [private inventory](../private-data/live-workflow-plan-20261008/inventory.json)
records all 27 benchmark SQLite files: seven USD ledgers and 20 SYN ledgers.
Each database was opened with SQLite `mode=ro` and `query_only=ON`, in a read
transaction. SQLite integrity checks, attempt totals, replayed audit deltas and
cap chains passed. Database and existing sidecar hashes remained unchanged.
No USD scope has a cap increase, and the seven authorization records match their
ledger run hashes, scopes and caps. Distinct run hashes and attempt IDs prevent
the two different `openrouter:smoke` scopes from being conflated.

| Saved live evidence | Frozen scope cap, microUSD | Known charges | Active reservations | Unknown holds | Completed dispatch evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| [Original OpenRouter archive](../private-data/smoke-20260928/original-run/config.json) | 500,000 | 0 | 0 | 104,963 | One ambiguous attempt; two later original positions never sent |
| [Never-sent suffix archive](../private-data/smoke-20260928/never-sent-suffix/config.json) | 395,037 | 139 | 0 | 0 | Two completed responses |
| [Identity OpenRouter original](../private-data/identity-proposal-20260928/config.json) | 500,000 | 174 | 0 | 0 | Three completed responses |
| [Clef smoke original](../private-data/clef-account-preparation-20261002/clef-smoke/config.json) | 250,000 | 0 | 0 | 47,187 | Three completed responses; charges unresolved |
| [Clef full original](../private-data/clef-account-preparation-20261002/clef-full/config.json) | 1,000,000 | 0 | 0 | 283,122 | Eighteen completed responses; charges unresolved |
| [Clef Flash smoke original](../private-data/clef-account-preparation-20261002/clef-flash-smoke/config.json) | 250,000 | 0 | 0 | 17,697 | Three completed responses; charges unresolved |
| [Clef Flash full original](../private-data/clef-account-preparation-20261002/clef-flash-full/config.json) | 1,000,000 | 0 | 0 | 106,182 | Eighteen completed responses; charges unresolved |
| Total observed balances | See allocation reconciliation below | **313** | **0** | **559,151** | 48 attempts, including one ambiguous dispatch |

Zero recorded Clef charges do not establish zero actual charges. Its 42 completed
responses retain their original unknown-charge reservations. The earlier
OpenRouter hold is a separate unknown-dispatch outcome. None was settled,
released or retried during this inventory. Sources:
[historical OpenRouter result](LIVE_SMOKE_RESULT.md),
[identity smoke result](LIVE_IDENTITY_SMOKE_RESULT.md),
[Clef acceptance](CLEF_LIVE_ACCEPTANCE_20261002.md) and the
[budget balance contract](BUDGET_API.md).

The identity and four Clef databases remain at the original paths declared by
their configurations. The earliest OpenRouter configurations point to
`/private/tmp/classification-proposed-smoke/run.sqlite` and
`/private/tmp/classification-approved-smoke-suffix/run.sqlite`; both originals
are absent. Their repository copies are preserved evidence, not new spending
authorities. All 140 files in the original
[archive hash manifest](../private-data/smoke-20260928/SHA256.json) still match.
Their audit balances are verified against that preserved snapshot; subsequent
state in absent originals cannot be checked. Do not rewrite archive paths,
resume the retired original or dispatch from copied grants.

The seven live databases use legacy singleton run bindings. None has a SQL
aggregate parent linking it to the USD 10 ceiling. The dated
[Clef allocation record](../private-data/native-acceptance-20261002/aggregate-allocation.json)
records the user approval and four caps totaling 2,500,000 microUSD; all four
bindings, caps and request counts match the existing original ledgers. That
record is documentary accounting, not a shared transaction across databases.

| Calculation against the documented 10,000,000-microUSD ceiling | microUSD | Meaning |
| --- | ---: | --- |
| Known charges + active reservations + unknown holds | 559,464 | Verified saved ledger exposure |
| Ceiling less that exposure | 9,440,536 | Exposure-only arithmetic; it excludes retained allocations |
| Original OpenRouter plus its suffix, counted once | 500,000 | One combined approval; the suffix's 395,037 is the remainder after the original 104,963 hold |
| Identity smoke retained frozen cap | 500,000 | Execution used this cap; its approval allowed up to $1 if needed, but no increase occurred |
| Four Clef retained caps | 2,500,000 | Documented separate scope allocations |
| Total retained allocation assumption | 3,500,000 | Charges and holds are already inside these caps |
| Ceiling less retained allocations | **6,500,000** | Conservative capacity available for a new allocation within existing project authority |
| Proposed new OpenRouter aggregate cap | 300,000 | Includes both required workflow phase caps; not allocated yet |
| Historical allocations plus proposed aggregate | 3,800,000 | Leaves 6,200,000 microUSD if this proposal is bound to existing authority |

Adding all seven SQL caps would double-count the original OpenRouter approval
and its suffix. Adding exposure to the retained caps would also count the same
charges and holds twice. The 3,500,000-microUSD figure deliberately retains the
reviewed frozen allocations; this plan releases none. New work needs a matching
request authorization and explicit recognition of its new allocation within
the same project ceiling. Its future SQL parent can enforce the new workflow's
300,000-microUSD cap; it will not retroactively bind the legacy databases.
No ledger, allowance or funds from the reference project were included.
See the [active goal](NEXT_TASK_GOAL.md) and
[aggregate authority contract](AGGREGATE_BUDGET.md).

## Prepared OpenRouter proposal

The [frozen workflow](../private-data/live-workflow-plan-20261008/openrouter-proposal/workflow.json)
and [smoke preview](../private-data/live-workflow-plan-20261008/openrouter-smoke-preview.json)
are reviewable offline artifacts with private permissions. The scope uses only
`toy-a` from the [fictional product inputs](../examples/product/inputs.json), the
[product task](../examples/product/task.json) and its existing baseline prompt.
The input is a shared planning board for a small creative studio. Its two
categorical fields are `segment` and `urgency`. Reference labels remain outside
the frozen source files and inference capsules.

| Control | Exact proposal |
| --- | --- |
| Phase | `smoke` only |
| Route | OpenRouter `openai/gpt-4.1-nano` through exact endpoint `openai` |
| Frozen canonical model | `openai/gpt-4.1-nano-2025-04-14` |
| Requests and positions | One request, one fictional case, one baseline prompt, one repeat, batch size one |
| Controls | Temperature `0`, maximum output `512` tokens, no reasoning selection |
| Concurrency | Total `1`; `openai: 1` |
| Conservative per-request bound | `104963` microUSD ($0.104963) |
| Smoke child cap and exhaustion | `150000` microUSD ($0.15), `pause` |
| New workflow parent proposal | `300000` microUSD ($0.30); smoke/full child caps each `150000` |
| Authentication source | Existing ignored project `.env` `OPENROUTER_API_KEY`; no new credential copied or read by this preparation |
| Workflow SHA-256 | `896e8d5b4b1a42f4ace2d4fa3db012f85192b4be4082fe1ff078778193fe7b6d` |
| Smoke run SHA-256 | `5a232091fb70a8f31ce0fa75e7466a21edb58c46ccfbff26e53ea0973de57b21` |
| Plan SHA-256 | `64f3a168972b4e6944f7440a8ff445ba4441d22cbdcd56fb662470ab872793bb` |

The [fresh public snapshot](../private-data/live-workflow-plan-20261008/openrouter-endpoint-20261008.json)
was read at `2026-10-08T03:13:52.652405Z`. Offline adapter validation and preview
passed. Its full prompt ceiling is 1,047,576 tokens, with input rate
$0.0000001/token and output rate $0.0000004/token. The reservation is rounded
up from `1,047,576 × 0.0000001 + 512 × 0.0000004`; expected short-prompt cost does
not replace this bound. The snapshot retains model identity, endpoint evidence,
pricing and supported controls. Current availability and price compatibility
must still pass admission-time checks. See the
[OpenRouter adapter contract](OPENROUTER.md).

The root operator's
[account-policy observation](../private-data/live-workflow-plan-20261008/openrouter-policy-readiness.json)
at `2026-10-08T03:12:17.234991Z` matched the existing project key to the default
workspace without saving credential values or account identifiers. Web
override prevention was off; response healing and its override prevention were
off. The frozen `account_policy_assertion` truthfully cites that observation and
sets the two supported policy fields to true. It remains an operator assertion
and expires 24 hours after that check; expiration requires new frozen policy
and a newly reviewed workflow identity. Provider honoring the request controls
remains a condition of the bound.

Requests disable fallback, inference retry, response repair and web/response
healing plugins, and request cache bypass. Applicable empty-tools/tool-choice
controls are supplied by the adapter. Provider prompt caching is separately
observable. A timeout or unavailable charge retains its reservation; invalid
output remains in the denominator. Generation metadata lookup is a separate
read-only operation, not a repeat. No automatic retry, top-up, payment change or
subscription change is permitted.

The workflow format requires a positive full cap as well as a smoke cap. The
frozen full phase has one planned request but **has no approval and is not part
of this smoke**. Its preparation authorizes nothing. A future full invocation
would require a separate phase record and renewed verification of prerequisites.
This tiny smoke checks the current generic workflow integration; it establishes
no model-quality ranking or repeat stability.

## Remaining authorization and commands

The saved preview contains the exact authorization template: schema version
`1`, the workflow hash above, phase `smoke`, request count `1` and
`caps: {"USD": 150000}`. No executable authorization record was created.
The execution record must bind this exact one-request smoke and the proposed
300,000-microUSD parent allocation within the reconciled project ceiling. The
root operator can record the existing explicit project USD 10 authority where
it covers this scope; preparing a new allocation does not automatically require
asking for that same permission again. Request approval only for authority that
is actually missing. This worker-created proposal is not itself authority.
The parent's full capacity remains unapproved for dispatch. Existing historical
grants do not cover these new workflow request identities.

These commands inspect the prepared proposal without inference:

```sh
python3 -m classification_bench preview --workflow private-data/live-workflow-plan-20261008/openrouter-proposal/workflow.json --phase smoke
python3 -m classification_bench status --workflow private-data/live-workflow-plan-20261008/openrouter-proposal/workflow.json
```

The root operator subsequently prepared a new schema-2 workflow and bound the
existing project authorization to it. The original proposal remains unexecuted;
its hashes and the accepted workflow's hashes differ. Do not reuse the accepted
workflow's authorization with this proposal. The exact execution and recovery
records are in [the live acceptance](WORKFLOW_LIVE_ACCEPTANCE_20261008.md).

For offline scoring of this one-case source, use the private
`openrouter-reference-labels.json` projection containing only `toy-a`, kept
outside all inference capsules. The original three-case reference file is not
an exact match for this one-case frozen source. The separate projection record
binds both files by hash. Successful preflight is a prerequisite, not a grant;
existing explicit authorization still determines which prepared scope can run.

## Claude Code and Codex prerequisites

Each later route would use the same one-case task and baseline prompt, with one
fresh CLI invocation at batch size one and repeat one. Each reserves **one REQ**;
a two-route smoke therefore needs an explicitly approved cap of **two REQ** and
provider limits `claude_subscription: 1`, `chatgpt_subscription: 1`. Total
concurrency can remain one for this minimal live acceptance. REQ is invocation
capacity, not a dollar/token cap or a bound on hidden CLI calls, retries or
repair. No conversion into microUSD is proposed.

| Required field or gate | Claude Code | Codex |
| --- | --- | --- |
| Exact native executable | `/Users/adamkovacs/.local/share/claude/versions/2.1.293` | `/opt/homebrew/Caskroom/codex/0.156.1/bin/codex` |
| Exact version output | `2.1.293 (Claude Code)` | `codex-cli 0.156.1` |
| Authentication observed | Existing first-party Claude.ai Max | Existing first-party ChatGPT |
| Exact model ID | Still required; version/help/auth checks did not establish available IDs | Still required; version/help/auth checks did not establish available IDs |
| Explicit effort | `low` if the selected model supports it; `not_applicable` for a selected Haiku model | `low` if the selected model supports it |
| Actual paid-fallback check | Blocked: observed Usage credits enabled | Unverified: auto-reload off does not disable fallback to existing credits |
| Browser/CLI identity match | Still required for the selected account | Still required for the selected account |
| Fresh assertion | Cannot truthfully set `extra_usage_disabled: true` yet | Cannot truthfully set `extra_usage_disabled: true` yet |
| Model serving/entitlement | Pending separately authorized smoke | Pending separately authorized smoke |

Sources: [current CLI readiness](SUBSCRIPTION_READINESS_20261008.md),
[saved account observations](../private-data/subscription-account-check-20261008/readiness.json),
[subscription runtime contract](SUBSCRIPTION_RUNNER.md) and
[assertion renewal contract](SUBSCRIPTION_ASSERTIONS.md).

After the actual operator check establishes disabled paid fallback, each route
still needs exact `model`, `settings.executable`, `settings.cli_version`,
`settings.effort`, `settings.extra_usage_disabled: true`, the real UTC
`settings.extra_usage_verified_at` and an honest `settings.extra_usage_source`.
Use the verified native binary hash from the readiness document and rerun the
reference/symlink/environment and context-control preflight. Authentication
does not prove model entitlement. No model ID, billing assertion, private
configuration or executable CLI authorization was invented here. Neither route
may enable credits, change payment settings or fall back to an API key to pass
this gate. Once truthful fields exist, prepare a new workflow and obtain its
exact hash-bound phase authorization through the same generic operator flow.

## Verification boundary

Reconciliation, fresh unauthenticated catalog capture, strict offline adapter
validation, deterministic workflow preparation/load and preview passed. The
prepared workflow's files have private modes, and its future database, artifact
store and authorization directory do not exist. Historical evidence remained
unchanged. No claim is made about current provider serving, new billing,
subscription model availability or rendered report acceptance.
