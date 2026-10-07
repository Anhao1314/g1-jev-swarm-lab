# GLM live preflight: READY_FOR_CROSS_MODEL_PILOT

**READY_FOR_CROSS_MODEL_PILOT = true.** This is provider integration readiness,
not a Source Authority efficacy result or authorization to start scored work.
Phase 2.4.2 scored Pilot remains paused. Runtime and held-out were not started.

On 2026-10-07 at 18:31:02–18:31:41 Asia/Shanghai, the existing independent GLM
adapter made three non-scored requests to:

`https://open.bigmodel.cn/api/paas/v4/chat/completions`

All returned exactly `glm-5.3-flash`, final assistant content, `stop`, and complete
usage. Authentication and reachability passed. No transport retries or semantic
reruns occurred. The provider remained explicitly selected as `glm-5.3-flash`;
DeepSeek, its resolver, compiler prompt and historical evidence were unchanged.

| Live check | Result | Latency | Input / output / total tokens | Reasoning tokens |
|---|---|---:|---:|---:|
| Ordinary text marker | PASS | 3.131 s | 33 / 79 / 112 | 72 |
| JSON object with exact expected fields | PASS | 26.364 s | 96 / 1193 / 1289 | 1176 |
| Typed certificate through existing host parser | PASS | 9.627 s | 701 / 484 / 1185 | 441 |

Total: **3 calls, 3 attempts, 2586 reported tokens**, comprising 830 input and
1756 output tokens. All attempts had complete usage; there is no unreported
failed-attempt usage in this run. Cached input counts were zero. Actual response
details included independent reasoning token counts, totaling 1689; this field
was not established by the prior general documentation schema.

Reasoning content was present on all three responses (343, 5340 and 1531
characters). The adapter returned only final content to the certificate parser.
No raw reasoning text was saved. Enabled thinking was requested; reasoning effort
was omitted, so a particular default effort level was not independently verified.
The JSON check's substantial reasoning and 26-second latency are retained; these
three small requests do not establish representative performance or availability.

The certificate used the completely fictional source:

> 请先站立三秒，然后停止。

It produced `AUTHORIZED_UNIQUE`, seven `U` checks, plan
`[["stand",3],["stop"]]` and no issues. The existing candidate-blind issuer and
typed host parser accepted the complete certificate. No historical unsafe OOD
sample, compiler candidate, scored corpus or Mission execution was involved.
JSON object mode was explicitly enabled for the JSON/certificate stages. A
server-side strict JSON Schema guarantee remains unestablished; host validation
remains required.

The fixed settings were temperature 0, max_tokens 4096, enabled thinking, effort
omitted, non-streaming, timeout 60 seconds, two maximum transport retries, and
0.5-second initial backoff. All three completed within that budget; provider
maximum context/output limits were not experimentally measured.

Transport-error handling is verified by deterministic injected timeout, network,
HTTP, TLS and malformed-response tests. No deliberate live failure request was
made. The GLM test directory passed **117 offline tests**, including 26 new
runner tests for stopping on failure, rejecting zero/missing usage, URL pinning,
credential echo, one certificate call, and unknown retry accounting. Independent
review found no remaining material implementation blocker.

The user confirmed account ownership of the 300M token package and explicitly
removed independent deduction verification from the scientific provenance gate.
Actual package deduction is recorded as unverified; no billing verification
claim is inferred from API success. This policy change supersedes the initial
billing blocker without rewriting the earlier BLOCKED/profile/offline receipts.

The supplied credential was passed only in the caller process's memory. It was
not installed in persistent environment variables, written to a credential file,
put into a tool argument, or copied into the repository, public receipts, logs
or evidence. No credential fingerprint/hash was computed. The process exited
after saving only audited non-secret results. Future calls require explicit
credential injection; no wrong-account Claude credential or DeepSeek credential
is borrowed, and no cross-model fallback exists.

Current state is indexed by `current_live_receipt.json` and `live_profile.json`.
The unchanged original `inspect_readiness.py` describes the historical offline
receipt; `inspect_live_readiness.py --provider glm-5.3-flash` checks the current
live receipt without reading credentials or contacting a provider.

D011 remains candidate and the language Runtime gate remains BLOCKED. No further
model requests, scored Pilot, Runtime, benchmark repair or held-out campaign are
started by this integration.
