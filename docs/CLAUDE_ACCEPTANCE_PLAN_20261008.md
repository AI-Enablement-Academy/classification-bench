# Claude acceptance candidate: 8 October 2026

## Credit authorization update, 8 October 2026

The user has explicitly approved consumption of existing Claude and Codex
credits. This supersedes the disabled-credit prerequisite and proposed account
change below: enabled or unknown credit state is no longer itself a blocker
once the approval applies through an honest, run-bound version 2 assertion and
exact dispatch grant. Preserve this packet's false guard and account
observations; do not rewrite them as disabled or reuse the packet as a grant.
See [the assertion contract](SUBSCRIPTION_ASSERTIONS.md).

Live execution remains pending on one unanswered question: whether exactly one
Claude invocation and one Codex invocation, with no retry or top-up, are
acceptable despite no verified hard USD cap. The project USD 10 ceiling remains
unchanged. No account change, top-up or live run follows from this note. The
[combined CLI credit smoke plan](CLI_CREDIT_SMOKE_PLAN_20261008.md) records the
scope, monetary limit and remaining authorization question.

The proposed smoke is **one Claude Code invocation for fictional case `toy-a`, using `claude-haiku-4-5-20251001`**. It is blocked: the matched Claude organization/billing context has usage credits enabled. The private candidate preserves `extra_usage_disabled: false`; the real adapter rejects it. No executable workflow, authorization, ledger, preflight or inference was created.

This packet was prepared against commit `8ed870ebf6a5c2024db8f6de70117bd1c8887db4`, using the [active goal](NEXT_TASK_GOAL.md), [subscription readiness audit](SUBSCRIPTION_READINESS_20261008.md), [adapter](../classification_bench/subscription_adapters.py), and [generic workflow contract](WORKFLOW_DESIGN.md). Apply existing explicit authority when it covers the final scope. The project USD 10 allowance does not establish a subscription request authorization or authorize an account-setting change.

## Exact account action for review

In the Claude organization/billing context already matched to the native CLI, open [Settings → Usage](https://claude.ai/settings/usage), locate **Usage credits**, turn the existing enabled setting **off**, and verify its resulting disabled state. This is an account policy change requiring explicit authorization before the operator acts. It is separate from authorizing a model request.

The setting serves both Claude conversations and Claude Code. Once disabled, use is limited to the plan's included allowance; work reaching that allowance cannot continue through usage credits. This effect extends beyond this benchmark. The proposed action changes only that enabled/disabled setting; it includes no purchase, redemption, refund, balance transfer, auto-reload change, spending-limit change or subscription upgrade. [Claude: manage usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans)

The retained [policy observation](../private-data/live-workflow-plan-20261008/claude-policy-readiness.json), at `2026-10-08T03:20:34.874194+00:00`, records `organization_matches_cli: true`, `usage_credits_enabled: true`, and `extra_usage_disabled: false`. Its SHA-256 is `ebd7dda8992bd203298d40fdefbc15ed778355d7ffee5628a88c2c548256c1a8`. The match establishes the organization/billing context through the operator's full hash comparison; **member/email identity remains unverified**. This preparation inspected the record, not the account UI.

## Proposed smoke scope

| Control | Exact candidate |
| --- | --- |
| Provider/runtime | `claude_subscription` / `claude_code` |
| Model | `claude-haiku-4-5-20251001` |
| Effort | `not_applicable`; the adapter omits `--effort` |
| Native executable | `/Users/adamkovacs/.local/share/claude/versions/2.1.293` |
| Version output | `2.1.293 (Claude Code)` |
| Binary SHA-256 | `4e21122a227857da1178aca3299700c1fd7f2b77c93f12e73c2c76db796a105e` |
| Authentication source | Existing official Claude.ai first-party Max login; no API-key route or credential copy |
| Task | `fictional-product-fit`; fields `segment` (`teams`, `solo`) and `urgency` (`now`, `later`) |
| Input | `toy-a`: description “A shared planning board”; audience “Small creative studio” |
| Condition | Existing product `baseline` prompt; one repeat; batch size one |
| Selected phase | `smoke`; exactly one planned request and one case |
| Smoke cap | `REQ: 1`; exhaustion behavior `pause` |
| Concurrency | Total one; `claude_subscription: 1` |
| Local bounds | 180-second timeout; 65,536 captured output bytes |
| Current account guard | `extra_usage_disabled: false`; enabled-credit observation retained honestly |

The [official model page](https://platform.claude.com/docs/en/models/haiku-4-5/overview) lists this dated Haiku 4.5 ID as active legacy, with effort unsupported. It publishes API prices of USD 1 input / USD 5 output per million tokens; those prices do not measure this subscription invocation's cost. The [Claude Code guide](https://support.claude.com/en/articles/11940350-claude-code-model-configuration) lists the same exact ID and supports selecting it with `--model`. This is a low-cost, currently documented candidate compatible with our adapter, not a claim that it is the newest or cheapest available route. Account entitlement and actual serving availability remain unverified until an authorized live response.

Current official [model configuration documentation](https://code.claude.com/docs/en/model-config) also lists Haiku 5.5 and requires CLI 2.1.293 or later for it. At this packet's preparation commit `8ed870e`, the adapter required `not_applicable` for every Haiku ID. The later [capability correction](SUBSCRIPTION_RUNNER.md) supports Haiku 5.5 effort with documented CLI-version checks before live execution and preserves historical reads. This retained packet still selects Haiku 4.5; its private candidate files and hashes are unchanged.

One `REQ` bounds admitted CLI invocations. It does not bound opaque internal model requests, repair attempts, tokens, or dollars. The local timeout and byte limit are not provider billing or output-token caps. Actual subscription cost remains unknown. No subscription request capacity is converted to, or charged against, USD arithmetic. See [subscription accounting](SUBSCRIPTION_RUNNER.md).

The existing workflow format requires positive caps for both `smoke` and `full`. The candidate therefore declares a proposed parent `REQ: 2`, with `REQ: 1` in each phase. **Only smoke is proposed for acceptance. Full has no dispatch approval**, and this blocked packet creates no allocation in either phase. Both select the same one fictional case solely to satisfy the current format; no full-run request is included in the proposed action.

## Private review artifacts and remaining fields

The mode-0700 [candidate directory](../private-data/claude-acceptance-plan-20261008/) contains mode-0600 JSON files:

- [Review candidate](../private-data/claude-acceptance-plan-20261008/review-candidate.json): exact account action, smoke scope, prerequisites and source links. SHA-256 `df4e664dea2b8c675ace751d433a4f073ac0c422fba7434ee0f39d677ba23656`.
- [Task](../private-data/claude-acceptance-plan-20261008/task.json), [input](../private-data/claude-acceptance-plan-20261008/inputs.json), and [experiment candidate](../private-data/claude-acceptance-plan-20261008/experiment-candidate.json): copied fictional task/input and the existing baseline prompt, with the exact proposed native controls and false guard. Reference labels are absent.
- [Workflow specification candidate](../private-data/claude-acceptance-plan-20261008/workflow-spec-candidate.json): valid specification structure, blocked by its adapter guard. SHA-256 `eeeddd7e8a3981a7454a501cb3176fc60d17fcf9bb4e80a5ef1348a2fa063549`.
- [Logical plan candidate](../private-data/claude-acceptance-plan-20261008/logical-plan-candidate.json) and [verification](../private-data/claude-acceptance-plan-20261008/verification.json): deterministic one-request membership, file/source hashes, private permissions and the expected rejection `paid extra usage must be disabled before subscription execution`.

After an authorized account change, retain these candidate files as historical evidence and create new source files. The final experiment must replace `extra_usage_disabled` with `true` only after a genuine disabled-state observation, replace `extra_usage_verified_at` with its fresh UTC `Z` timestamp, and replace `extra_usage_source` with that observation's honest account-bound provenance. Reconfirm the applicable billing-context match and retain the member/email limitation. Assertions must satisfy the adapter's freshness check; a timestamp or source string alone is not independent verification. See [account assertions](SUBSCRIPTION_ASSERTIONS.md).

The final specification also needs an honest `authorization_source` tied to applicable explicit authority. Its new hashes and request identity must be frozen after those edits; the current false-guard identities cannot serve as final execution identity. A fresh complete runtime preflight must check the native binary/version/help, official authentication, isolation and actual account assertion. Then bind the selected `smoke` phase, exact workflow hash and `REQ: 1` to an authorization covered by existing permission, or request only the missing authority. Never dispatch the dormant full phase or automatically retry an ambiguous invocation.

For the later verified source set, the ordinary offline preparation commands are:

```sh
python3 -m classification_bench workflow-prepare \
  --spec private-data/claude-acceptance-plan-20261008/ready-source/workflow-spec.json \
  --directory private-data/claude-acceptance-plan-20261008/prepared-after-verification
python3 -m classification_bench preview \
  --workflow private-data/claude-acceptance-plan-20261008/prepared-after-verification/workflow.json \
  --phase smoke
```

Those future paths do not exist in this packet. The preparation commands send no inference; real preflight and dispatch remain subsequent gated steps. Only an authorized live smoke can prove the selected model route and task output.

## Verification boundary

Offline checks validated the task, experiment, input and workflow-specification structure, counted exactly one logical request, checked the current native binary hash and private file modes, and confirmed that the actual subscription constructor rejects the false guard. They performed no preflight, credential read/copy, provider request or account change. No executable workflow, ledger or authorization was produced. This document is a concrete review packet, not a successful live acceptance result.
