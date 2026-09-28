# Authorized smoke evidence

The operator approved three fictional inputs, one baseline prompt, one repeat, batch size one, `openai/gpt-4.1-nano` via `openai`, with a combined USD 0.50 cap and pause at exhaustion. Credential use from the parent codebuild environment file and creation of a private repository-local `.env` were explicitly authorized afterward. The key is ignored by Git, has mode 0600 and is absent from tracked files.

## First attempt

The original run at `/private/tmp/classification-proposed-smoke/config.json` admitted the `fictional-a` request, then saved an empty-response `URLError` diagnostic. Its request ID is `562d4881e9d057643644ba8ba4eafc8bcac3a17c37f146fbad220c6ff4a74f71`; diagnostic SHA-256 is `00b020a185470d05f845019ffd8204b019e970b4255adb106211af6fdf50647a`. No provider response or charge is available. Recovery found no attributable response. The unknown hold remains **104,963 microUSD**. The original two later records remain never-sent in that archive.

Later credential-free probes found that the child could not import OpenSSL libraries or resolve the hostname. This explains a reproducible transport defect but does not prove the earlier attempt was unbilled. Its evidence and hold remain unchanged. Never retry it or resume the original run.

## Correction and continuation boundary

The transport profile adds exact OpenSSL library and certificate paths, metadata access to `/var`, and outbound access to the mDNSResponder socket. The revised preflight proves default CA loading, DNS and a public HTTPS request before paid admission, while retaining reference/symlink denials and a scrubbed environment. Diagnostic profiles with broader rules were used only in credential-free resolution tests, never for inference.

Changing the runtime source changes the enrolled execution identity. The continuation therefore has its own immutable run definition at `/private/tmp/classification-approved-smoke-suffix/config.json`, containing **only fictional-b and fictional-c**, the same prompt and model settings, and no additional repeat. Its private authorization derives from the existing approval for those two unsent positions. A lineage record links it to the original attempt.

The suffix cap is **395,037 microUSD**. Together with the original 104,963-microUSD hold, the maximum authorized accounting remains **500,000 microUSD ($0.50)**. Its two request bounds sum to 209,926 microUSD. These are separately archived runs with explicit operator accounting; this does not claim that separate SQLite files enforce one shared transaction. The original ordered run is blocked by its unknown attempt and must remain retired.

Continuation result: pending final transport review and verification. No additional inference has been dispatched at this checkpoint. A completed suffix must not be presented as a complete three-record model-quality benchmark; the unknown original position stays visible.
