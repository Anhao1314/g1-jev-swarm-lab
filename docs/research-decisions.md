# Research Decisions

This file is the consolidated decision log. It starts with the Phase 2.2b
synthesis; earlier phases recorded their decision recommendations inside their
experiment reports. Entry IDs follow the Phase 2.2b synthesis plan.

## D010 — Phase 2.2b compiler architecture selection

Date: 2026-10-07. Phase: 2.2b (`simplex_compiler_001`). Status: **decided**.

Problem: Phase 2.2's direct LLM compiler reached high blind accuracy but failed
open on two controlled malformed connector inputs. Which compiler architecture
should be frozen as the Phase 2.3 language front end?

Alternatives considered (frozen before the fresh blind campaign):

- A `direct_llm_v1` — direct LLM compiler (control).
- B `guarded_direct_llm_v1` — deterministic structural guard, then the direct
  LLM compiler.
- C `canonical_bridge` — guard, canonicalizer, then the frozen Phase 2.1 Lark
  grammar as the only Mission IR authority.
- D `simplex_canonical` — guard, frozen Lark fast path without a provider
  call, canonicalizer escalation only when Lark refuses.

Evidence (machine-readable, frozen; full detail in
`experiments/phase2/simplex_compiler_001/report.md`):

- Fresh blind: A unsafe 37 / silent repair 0.500; B/C/D zero on all safety
  gates. Exact IR and coverage: A/B 0.9857 / 0.9833, C 0.9571 / 0.9500,
  D 0.9714 / 0.9667 (frozen gates: >= 0.98).
- Controlled regression: A exact 1.0 but unsafe 2; B and D exact 1.0 /
  unsafe 0; C exact 0.9635 (fails the frozen 1.0 gate, robust to its two
  replay-missing samples).
- E2E: B/C/D 7/7 valid missions runtime-equivalent, 6/6 language rejections at
  zero steps, capability boundary intact; A accepted one malformed input.
- Repeatability: B/C/D 1.0 across status, error code, route, semantic IR.
- Efficiency: B 129/179 calls, 247,155 tokens; D cheapest (113/179, 184,791)
  but fails the fresh semantic gates.

Decision: **SELECT `B guarded_direct_llm_v1`** — the smallest architecture
that passes every frozen mandatory gate.

Rejected alternatives:

- A — hard-gate fail-open (37 fresh unsafe acceptances). Aggregate accuracy
  does not override safety.
- C — fails fresh exact/coverage gates (0.9571 / 0.9500) and the controlled
  exact gate (0.9635); eliminates fail-open but loses valid coverage.
- D — fails fresh exact/coverage gates (0.9714 / 0.9667); efficiency gains do
  not substitute for frozen semantic gates.

Revisit conditions: guard false positive > 0 or any fail-open acceptance; a
new frozen corpus where B falls below the fresh semantic gates; controlled
exact < 1.0 or unsafe > 0; any prompt or guard change that invalidates the
frozen hashes/versions; or evidence that the canonical bridge can match B's
accuracy with equal or lower complexity.

Artifacts: `experiments/phase2/simplex_compiler_001/architecture_selection.md`,
`experiments/phase2/simplex_compiler_001/report.md`,
`docs/lab-notebook/phase2.2b.md`,
`docs/lab-notebook/visual-summary-phase2.2b.md`.
