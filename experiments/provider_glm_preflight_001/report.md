# Independent GLM provider integration: blocked before live preflight

Configuration verdict: **BLOCKED_PENDING_RESOURCE_PACKAGE_ROUTE_AND_LIVE_PREFLIGHT**.
`READY_FOR_CROSS_MODEL_PILOT = false`. Phase 2.4.2 scored Pilot is paused.

An independent OpenAI-compatible Chat Completions adapter is added without editing
the existing DeepSeek backend, compiler, Guard, prompts, experimental settings,
historical evidence or frozen package manifests. The provider factory requires
explicit `deepseek-flash` or `glm-5.3-flash` selection and explicit configuration;
there is no automatic fallback or credential discovery across providers.

## Credential and billing investigation

The existing local Claude configuration uses
`https://open.bigmodel.cn/api/anthropic`; its Haiku model is `glm-5.3-flash`,
and its credential lives in local Claude settings. No credential value or hash
was printed or copied into this integration. The user confirmed that this
credential belongs to a different account from the account holding the 300M
token package. It was therefore excluded. The user also supplied a credential
in the conversation; this integration did not use, copy, hash or persist it.
This statement concerns our changes, not retention of the conversation by the
chat application.

The resource-package account is not signed in on this device. The existing
browser account's package information cannot establish the target account's
entitlement. No local credential or provider setting was changed.

Official [OpenAI compatibility documentation](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)
specifies standard Base URL `https://open.bigmodel.cn/api/paas/v4` and Chat
Completions. This is the documented target endpoint, **not a live verified
endpoint for the supplied credential**. We did not attempt `/responses` or
switch to Coding Plan.

The official [fee FAQ](https://docs.bigmodel.cn/cn/faq/fee-issues) says applicable
model resource packages are deducted before cash; earliest expiry takes priority
among applicable packages. That rule requires an active, applicable package with
remaining balance. The [Coding Plan FAQ](https://docs.bigmodel.cn/cn/coding-plan/faq)
describes a distinct route whose quota is not a validator for standard API
resource-package deductions.

The official Chat response has no documented resource-package ID or deduction
channel. No general financial/package API was found in the
[official OpenAPI specification](https://docs.bigmodel.cn/openapi/openapi.json).
Consequently successful authentication, a matching model name, and token usage
would not prove that this particular 300M token package was charged. We cannot
reliably establish package coverage, validity, remaining balance or actual
deduction using the available local account evidence. We stopped before live
preflight in accordance with the user's billing boundary.

To unblock: inspect the target account's package details showing coverage of
`glm-5.3-flash`, validity and available balance; then verify resource-package
deduction for an authorized non-scored call in that account's billing details.
No new Key needs to be sent in chat. Credential binding should use a dedicated
process environment or an authorized local credential store, independently of
Claude's other-account credential and DeepSeek.

## Documented capability, not measured capability

The official [model guide](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash)
lists model `glm-5.3-flash`, 1M context and 131072 maximum output tokens.
Thinking is mandatory; documented `reasoning_effort` values are `low`, `high`,
and `max`, with default `max`. Our adapter explicitly requests enabled thinking
and leaves effort unset, so this documented default remains a live-unverified
assumption. The integration profile records a 4096-token request budget,
temperature 0, 60-second timeout and at most two transport retries. These are
new GLM settings, not a modification of historical DeepSeek settings.

The model guide advertises JSON structured output; official examples use
`response_format={"type":"json_object"}`. We have not established a server-side
strict `json_schema` guarantee. The generic API's model scope for
`response_format` and `reasoning_content` is less current than the model guide.
Live compatibility therefore remains unverified; the existing typed host
certificate validator is still required.

The adapter separates `reasoning_content` from final `content`; reasoning is
never treated as a certificate. It preserves explicit incomplete/truncated
status, rejects missing/mismatched model identity and malformed response shape,
normalizes prompt/completion/total usage, and retains only whitelisted optional
usage details. Optional reasoning token fields cannot be assumed present. Errors
are typed and do not include provider error bodies, headers or credential values.
Semantic response failures are not retried.

## Preflight status and scientific boundary

All live checks are **NOT RUN**: reachability, authentication, returned model,
normal text, JSON, reasoning behavior, actual usage and typed-certificate smoke.
Provider calls, attempts, tokens consumed by this integration and scored samples
are all zero. There is no live/documentation discrepancy result because there
was no live test.

Offline transport tests and a fictional ordinary-source certificate fixture test
verify host integration only. They are not evidence of provider availability,
semantic reliability, cross-model independence or the target package's billing
route. No historical unsafe OOD source is used in the smoke fixture.

D011 remains candidate, the language Runtime gate remains BLOCKED, and there is
no scored Pilot, Runtime call or held-out campaign. Cross-model dependent-failure
analysis must wait for an explicitly configured, billing-verified experiment;
merely adding a second provider does not establish independent failures.

Verification results are recorded in `offline_validation.json`. New artifacts
have scoped byte-preserving Git attributes. Original V1/V2 archive bytes and
historical provider provenance remain unchanged.

The combined offline test run passed **130 tests**: 91 new adapter/selector tests,
34 old provider/packaging regressions and five old backend configuration/scripted
tests. Seven local HTTP server tests were intentionally excluded; neither real
GLM nor real DeepSeek was contacted. Independent code review found no remaining
material implementation blocker. The unresolved blocker is account/package
verification and the subsequent real non-scored preflight.
