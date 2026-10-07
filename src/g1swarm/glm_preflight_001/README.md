# Offline GLM transport, not a live preflight

Package/debit attribution remains **BLOCKED**. This adapter and its stubbed
tests establish local protocol behavior only. No live call, entitlement check,
billing verification, scored campaign, held-out evaluation or Runtime ran.

`GLMChatConfig` requires a caller-supplied Chat base URL and GLM-specific key.
It reads no environment or Claude/Codex credential files, hides the key from
repr and is immutable. Model is `glm-5.3-flash`. Defaults are temperature 0,
max_tokens 4096, timeout 60 seconds, two transport retries, 0.5-second backoff
and the existing retry status set. Future scientific budgets require an explicit
new profile; this transport does not silently tune them. Thinking is enabled;
reasoning_effort is omitted to retain provider default. JSON-object response
format is optional and must be explicitly selected.

`GLMChatCompletionsBackend` implements the existing LLMBackend interface, posts
to `/chat/completions` and preserves only final content. It rejects wrong/missing
model, unsupported finish reasons, multiple choices, tool calls, malformed
wire JSON and credential echoes. It prohibits all HTTP redirects and keeps
ordinary verified TLS. Stop/length map to completed/incomplete, with that mapping
declared in response metadata. Reasoning presence and character length are
recorded without reasoning text. Missing token totals remain unknown; totals
and cached/reasoning details must be internally consistent when present.

`create_backend('glm-5.3-flash', glm_config=...)` selects only the new adapter.
`create_backend('deepseek-flash', deepseek_config=...)` returns the unchanged
frozen backend. Selection never falls back or borrows another provider's key.

The certificate integration test is an invented, stubbed fixture, not a live
smoke test or historical OOD result. Existing source files, prompts, resolvers,
evidence and root Git attributes remain unchanged. Scoped `.gitattributes`
inside the two new directories use `** -text` for byte-exact checkout.
