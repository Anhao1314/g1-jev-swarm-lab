# Phase 2.2 Prompt History

Prompt artifact: `prompts/llm_mission_compiler_v1.txt`

The blind set was not used for prompt development. The prompt was frozen in
commit `3fc5ebc` before the blind campaign; no prompt change followed the blind
result.

| Version | Change reason | Development result |
| --- | --- | --- |
| v1 draft | Initial schema, skill vocabulary, error taxonomy and seven examples | Valid IR remainder was correct, but one prompt-injection phrase reached `SUCCESS` and two malformed/unit cases had the wrong status/code mapping |
| v1 revised | Clarified `MALFORMED` versus `UNSUPPORTED`, added explicit invalid-unit, contradictory-command and injection examples | Development hard gates reached zero, but one non-vocabulary `fly`/shell-style request was still mapped to the wrong status and one provider call returned an empty response |
| v1 frozen | Distinguished capability requests (for example add/use `fly`) from meta/OS/rule override attempts; regenerated prompt hash | 87/87 expected statuses, valid IR 1.0, all hard gates 0, no API error |

Frozen SHA-256:
`913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110`.

Development evidence:
`artifacts/llm_compiler_001/development/summary.json`.

The blind campaign used exactly this frozen prompt and is reported separately
in `experiments/phase2/llm_compiler_001/report.md`.
