# Subscription readiness audit: 8 October 2026

## Credit authorization update, 8 October 2026

The user has explicitly approved consumption of existing Claude and Codex
credits. This supersedes the disabled-credit prerequisite in the readiness
audit below: enabled or unknown credit state is no longer itself a blocker
once the approval applies through an honest, run-bound version 2 assertion and
exact dispatch grant. Preserve the historical false guards and account
observations; do not rewrite them as disabled. See [the assertion contract](SUBSCRIPTION_ASSERTIONS.md).

Live execution remains pending on one unanswered question: whether exactly one
Claude invocation and one Codex invocation, with no retry or top-up, are
acceptable despite no verified hard USD cap. The project USD 10 ceiling remains
unchanged. No account change, top-up or live run follows from this note. The
[combined CLI credit smoke plan](CLI_CREDIT_SMOKE_PLAN_20261008.md) records the
scope, monetary limit and remaining authorization question. Fresh account
evidence, runtime prerequisites and model serving still need their own checks.

**Live Claude Code and Codex acceptance remains blocked by account billing evidence.** The installed native CLIs expose the required noninteractive controls and report subscription authentication. Neither result proves that paid usage credits are disabled, that the account observed in a browser is the CLI account, or that a requested model is available.

This audit used read-only version, help and login-status commands, source inspection, official documentation and offline tests. It sent no model request, changed no account setting, redeemed no credits, and opened or copied no credential file. Authentication output was reduced to the minimum fields below; account identifiers and raw status output are not reproduced here. The native CLI checks were made at approximately `2026-10-08T03:08:08Z`.

## Installed native executables

| Route | Exact native executable | Exact version output | Observed authentication | Required help controls |
| --- | --- | --- | --- | --- |
| Codex | `/opt/homebrew/Caskroom/codex/0.156.1/bin/codex` | `codex-cli 0.156.1` | ChatGPT | Present |
| Claude Code | `/Users/adamkovacs/.local/share/claude/versions/2.1.293` | `2.1.293 (Claude Code)` | Logged in; `claude.ai`; `firstParty`; `max` subscription type | Present, including `--effort` |

`/opt/homebrew/bin/codex` and `/Users/adamkovacs/.local/bin/claude` resolve to those respective native executables. An experiment must freeze its chosen native path, version, explicit model ID and effort. The [adapter](../classification_bench/subscription_adapters.py) rejects script wrappers and rechecks the executable hash before dispatch.

| Primary executable evidence | Codex | Claude Code |
| --- | --- | --- |
| Binary SHA-256 | `0196e89fe5a7598f816ee54232c3d7c26d75e502ab5cfe2c9240e81d90f7255a` | `4e21122a227857da1178aca3299700c1fd7f2b77c93f12e73c2c76db796a105e` |
| Invocation help SHA-256 | `0e82cfde0122715250e93dc65866caa956b2ac5b9d0b20ec4ad4f9e81486509e` (`exec --help`) | `550db4f88ae1d97bf7244ca96dc89554aabd3978241ceb69f79001e816c35f09` (`--help`) |

Two other Codex binaries were found. The desktop application's native executable at `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex` reports `codex-cli 0.160.0`; its `exec --help` includes the required flags. The desktop entry at `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` is a script wrapper and is not an admissible executable. The custom native executable at `/Users/adamkovacs/.local/share/codex-skill-budget/bin/codex` reports `codex-cli 0.153.4`. Neither alternative received a complete current authentication or runtime preflight in this audit. Their existence does not upgrade the frozen primary configuration.

Version/help/login-status exposes no verified serving model ID. The adapter requires an explicit model and effort; a valid configuration is a request for those controls, not evidence of availability. Live response identity and successful task output still require a separately authorized smoke.

## Controls and isolation boundary

The [worker commands and profile](../classification_bench/subscription_adapters.py) use Claude print mode, stream JSON and an output schema; safe mode, empty tools and MCP configuration, disabled hooks/memory, no session persistence and no Chrome integration restrict local context. Codex uses `exec`, JSON events, an output schema, ephemeral state, ignored user configuration/rules and forced ChatGPT authentication. The current help output supports the required flags. See the official [Claude CLI reference](https://code.claude.com/docs/en/cli-reference), [Codex noninteractive guide](https://learn.chatgpt.com/docs/non-interactive-mode) and [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

The worker additionally uses a deny-default macOS sandbox profile and a scrubbed environment. Its offline OS probe verifies permitted capsule reads and denied reference/symlink reads. It allows the exact existing authentication files, including writes needed for official token refresh; Claude can require the login keychain and security helper. This is not isolation of individual keychain records. TCP 443 and DNS remain available without a domain allowlist. Official built-in instructions, administrator requirements and remote account policy remain disclosed context.

The current native checks establish flag and authentication support, not a fresh complete runtime attestation for a concrete model/configuration. The OS-probe regression passed in the offline tests below. Earlier read-only preflight evidence used synthetic account assertions; it cannot establish actual disabled paid usage. A new live configuration must obtain an honest account assertion before its real preflight. The [runtime contract](ADAPTER_RUNTIME.md) and [runner contract](SUBSCRIPTION_RUNNER.md) retain these limits.

## Account evidence and exact blockers

The retained private [readiness record](../private-data/subscription-account-check-20261008/readiness.json) was observed at `2026-10-08T01:39:42Z`; its SHA-256 is `16a47330259d59784dfed4d281feb1e8c3bc12d1b6f4e36d8fc2e399fb1515ff`. It records a read-only authenticated browser check and explicitly says the browser account was not independently matched to the CLI account. It is historical observation, not a current CLI-bound billing attestation.

A separate operator [Claude policy check](../private-data/live-workflow-plan-20261008/claude-policy-readiness.json), recorded at `2026-10-08T03:20:34.874194+00:00`, matches the browser organization to the native Claude auth-status organization through a full SHA-256 comparison. It confirms usage credits remain enabled. This establishes the recorded organization/billing-context match, **not an email or member identity match**; it supplies no disabled-usage assertion. The mode-0600 record retains the match boolean and minimum policy fields, with no identifiers, identity hashes or balances. Its file SHA-256 is `ebd7dda8992bd203298d40fdefbc15ed778355d7ffee5628a88c2c548256c1a8`. The operator made no account changes or inference calls; this audit inspected the retained record, not the account UI.

| Route | Retained account observation | Remaining prerequisite |
| --- | --- | --- |
| Claude Code | Current operator check matches the CLI organization/billing context; usage-credit switch remains enabled; `extra_usage_disabled` is `false`. Member/email identity remains unverified. | A fresh observation that paid usage credits are disabled in the applicable billing context. The known enabled observation cannot support a `true` guard. |
| Codex | Auto-reload off; existing credit balance present; `extra_usage_disabled` is unknown | Actual CLI-account match and evidence that this invocation cannot fall back to paid credits. Auto-reload off supplies no such evidence. |

OpenAI documents that included plan usage is consumed first and that Codex can then draw from the existing credit balance. Auto-reload controls further credit purchases; it does not disable consumption of credits already held. [OpenAI: using credits for flexible usage](https://help.openai.com/en/articles/12642688)

No supported per-invocation credit-exclusion control was verified in the installed Codex help, the inspected local configuration schema or the current official configuration reference. `forced_login_method="chatgpt"` restricts authentication; it is not a billing policy. A request cap, timeout, disabled tools, expected small answer, apparent remaining quota or waiting for a reset cannot prove avoidance of credit fallback. This audit therefore cannot demonstrate a safe live Codex invocation on the observed account without further provider-backed billing evidence or an explicitly authorized account policy change. It does not establish that no such provider control can exist. [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

Claude documents that usage credits serve Claude and Claude Code after included limits and can be disabled in Settings → Usage. That gives an operator a documented account control, but changing it is outside this read-only audit and affects account policy. The known enabled state still blocks acceptance. Claude's client-side cost estimate or `--max-budget-usd` is not evidence that account credits are disabled. [Claude: manage usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans), [CLI budget flag](https://code.claude.com/docs/en/cli-reference)

The code records account assertions as `operator_assertion`; a source description, timestamp or hash does not independently verify the account setting. Observed Claude overage blocks later admission, but a post-response observation cannot prevent an initial charge. Codex billing and overage observability remains unavailable. `REQ` accounting bounds admitted CLI invocations and preserves ambiguous holds; it does not bound provider credits or opaque internal model calls. See [subscription accounting](SUBSCRIPTION_RUNNER.md).

## Safe next step

1. For Codex, match the authenticated CLI account to the account being checked, using a bounded read-only account-status procedure and private identity hashes or minimum fields. Preserve dated evidence without account identifiers in this document or in provider capsules. For Claude, retain the recorded organization/billing-context match and its explicit member/email limitation rather than broadening that claim.
2. For Claude, obtain a fresh observation of disabled usage credits in that matched billing context. If disabling them is required, get explicit authorization for that account-setting change first. For Codex, seek a provider-supported control or confirmation that excludes paid-credit fallback for the selected account/invocation. Do not equate disabled auto-reload, an empty displayed balance or an unaffiliated app's credit setting with an enforced Codex policy.
3. Only after actual prerequisites hold, freeze the exact native executable/version/model/effort and genuine account assertion in a one-case smoke plan. Run read-only preflight, bind the exact workflow/phase/request cap authorization, and obtain explicit approval for the provider calls before dispatch. A smoke verifies only its selected route and condition; it does not authorize a full run.

No new guard should be declared `true` from the current evidence. Existing [renewal](SUBSCRIPTION_ASSERTIONS.md) can append a fresh run-bound assertion without changing frozen identities, and the [workflow scheduler](WORKFLOW.md) can coordinate separate USD/REQ/SYN scopes with shared concurrency. Those implemented features do not replace account prerequisites or live authorization.

## Offline verification and review

The following command passed **72 tests in 4.402 seconds** on 8 October:

```sh
python3 -m unittest tests.test_subscription_adapters tests.test_subscription_runtime tests.test_subscription_assertions tests.test_subscription_renewal_workflow tests.test_workflow_scheduler -v
```

The tests cover native control construction, parsers, real local OS reference/symlink/environment isolation, request accounting, immutable assertion renewal and mixed-unit scheduling. Account fixtures are synthetic; fake workers send no provider inference. They establish neither account billing state nor live model acceptance.

**Code verdict: APPROVE; no new confirmed BLOCKING defect in this bounded audit.** Billing readiness remains an external prerequisite, not a successful live acceptance result. **RESIDUAL:** if an assertion expires after durable dispatch intent but before CLI launch, the generic exception path retains an unknown-outcome hold; this preserves conservative accounting but leaves proven prelaunch refusal indistinguishable from an ambiguous launch. Renewal never replays that intent. This existing limitation is described in [subscription assertions](SUBSCRIPTION_ASSERTIONS.md).
