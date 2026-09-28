# Authorized smoke evidence

The operator approved three fictional inputs, one baseline prompt, one repeat, batch size one, `openai/gpt-4.1-nano` via `openai`, with a combined USD 0.50 cap and pause at exhaustion. Credential use from the parent codebuild environment file and creation of a private repository-local `.env` were explicitly authorized afterward. The key is ignored by Git, has mode 0600 and is absent from tracked files.

## First attempt

The original run at `/private/tmp/classification-proposed-smoke/config.json` admitted the `fictional-a` request, then saved an empty-response `URLError` diagnostic. Its request ID is `562d4881e9d057643644ba8ba4eafc8bcac3a17c37f146fbad220c6ff4a74f71`; diagnostic SHA-256 is `00b020a185470d05f845019ffd8204b019e970b4255adb106211af6fdf50647a`. No provider response or charge is available. Recovery found no attributable response. The unknown hold remains **104,963 microUSD**. The original two later records remain never-sent in that archive.

Later credential-free probes found that the child could not import OpenSSL libraries or resolve the hostname. This explains a reproducible transport defect but does not prove the earlier attempt was unbilled. Its evidence and hold remain unchanged. Never retry it or resume the original run.

## Correction and continuation boundary

The transport profile adds exact OpenSSL library and certificate paths, metadata access to `/var`, and outbound access to the mDNSResponder socket. The revised preflight proves default CA loading, DNS and a public HTTPS request before paid admission, while retaining reference/symlink denials and a scrubbed environment. Diagnostic profiles with broader rules were used only in credential-free resolution tests, never for inference.

Changing the runtime source changes the enrolled execution identity. The continuation therefore has its own immutable run definition at `/private/tmp/classification-approved-smoke-suffix/config.json`, containing **only fictional-b and fictional-c**, the same prompt and model settings, and no additional repeat. Its private authorization derives from the existing approval for those two unsent positions. A lineage record links it to the original attempt.

The suffix cap is **395,037 microUSD**. Together with the original 104,963-microUSD hold, the maximum authorized accounting remains **500,000 microUSD ($0.50)**. Its two request bounds sum to 209,926 microUSD. These are separately archived runs with explicit operator accounting; this does not claim that separate SQLite files enforce one shared transaction. The original ordered run is blocked by its unknown attempt and must remain retired.

## Saved continuation results

Both unsent positions returned HTTP 200 with model `openai/gpt-4.1-nano` and provider display name `OpenAI`. Their original immutable parser observations are invalid because the initial parser compared that display name with the routing slug `openai`. A narrowly scoped parser correction accepts this exact alias and still rejects other provider mismatches. No model request was repeated.

| Position | Raw response SHA-256 | Input / output tokens | Client duration | Reported usage.cost | Rounded ledger charge |
| --- | --- | --- | --- | --- | --- |
| fictional-b | `a797cff7a06ded77225e772f14676abeae542f9395d22d4ad4afef93de9df48f` | 339 / 85 | 3.190 s | $0.0000679 | 68 microUSD |
| fictional-c | `9eaaa7ef29752701afbbdd821ad7e668859e707aee8ddff6aa9eb600f22b9926` | 341 / 90 | 1.721 s | $0.0000701 | 71 microUSD |

Provider-reported charges sum to $0.000138; rounding each request upward for the ledger gives **$0.000139**. Both responses reported zero reasoning and cached-input tokens. Client duration is not pure inference time. Each immediate generation-metadata lookup returned 404; hosting-provider metadata, provider generation duration and pure inference time remain unavailable. The chat responses' `OpenAI` value is observed evidence, separately displayed from the requested routing tag.

The corrected offline parser still rejects both responses for genuine output errors: fictional-b contains malformed JSON (delimiter error at character 256), and fictional-c assigns `serious_concern_reported` to sentiment, outside that field's vocabulary. Neither receives exact-match credit. These are retained model outcomes, not reasons for automatic retries or repaired answers.

A versioned offline correction, its reproducible script, raw-response hashes, parser-source hash, selected predictions, evaluation and private HTML are under `/private/tmp/classification-smoke-evaluation/`. `report-parser-correction.html` visibly identifies the two-position suffix and the excluded original unknown attempt. The script verifies saved raw bytes and verifies that the original snapshot is unchanged. `report-original-parser.html` in the suffix archive preserves the historical view. No labels were supplied to inference.

Restarting the completed suffix using its enrolled `4bbc357` build returned completed with identical operation records. Recovery also left the operations unchanged and required no requests. Changed parser builds remain barred from silently resuming enrolled work.

Across the authorized scope: **three dispatch attempts, two responses, one unknown attempt, zero valid selected outputs after strict offline re-evaluation**. Accounted exposure is **105,102 microUSD ($0.105102)**: 139 observed ledger charges plus the unchanged 104,963 hold. There are no remaining authorized model requests, no new repeats, and no additional paid smoke has been launched.

The smoke proves authentication, serving, raw capture, usage/charge settlement, strict failure preservation and saved-report generation on the corrected transport. It does not prove successful valid classification output, generation-metadata attribution, complete live verification or a release-complete result. Browser inspection and a second human operator's reproduction remain pending. Further inference requires a new explicit request scope, even though money remains under the original cap.


## Durable private archive and verification

A byte-verified copy of both run archives, the offline evaluation, and the enrolled `4bbc357` code is retained under repository-local `private-data/smoke-20260928/`, ignored by Git. `SHA256.json` covers 140 copied files, including the correction script (SHA-256 `c699d2e2d15b5564254bb984ab57dfdab75489fdcff692ef076e8bd7acacf026`). No credential is present in those archived bytes. The archive records the original absolute paths needed to reproduce frozen run bindings; do not silently rewrite archived configs to new paths or dispatch additional work from them.

The final full suite passed **148 tests with no skips** on the root macOS environment. Independent reviews approved both the transport correction and the narrow parser alias. A separate real credential-free preflight verified TLS, DNS and public HTTPS while preserving reference/symlink/environment restrictions. Browser visual verification and the human operator handoff have not been claimed.
