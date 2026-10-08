# Lab Notebook — Phase 2.2b: Compiler Hardening and the Selection of the Smallest Sufficient Architecture

Status: closed. Selected architecture: `B guarded_direct_llm_v1`.
Machine evidence root: `experiments/phase2/simplex_compiler_001/`.
Figures: `docs/lab-notebook/visual-summary-phase2.2b.md`.

## 1. Why Phase 2.2 ended PARTIAL

Phase 2.2 built a constrained LLM mission compiler and pushed open-language
coverage from 0.5106 (frozen Lark) to 1.0 on the 153-sample blind set, with
zero blind unsafe acceptances. Then the required 189-sample controlled
regression found something the blind set had not: two malformed connector
inputs (`cl-h-016`, `cl-h-017`) that the compiler silently repaired into valid
missions. The engine could be accurate and still fail open. That distinction —
capability versus assurance — is what Phase 2.2b was created to study.

## 2. Question and hypotheses

The question was deliberately narrow: what is the smallest architecture that
removes that fail-open behaviour without giving back the language capability
Phase 2.2 gained? Four candidates were frozen before the fresh blind run:

- A `direct_llm_v1` — the Phase 2.2 compiler unchanged (control).
- B `guarded_direct_llm_v1` — a deterministic structural monitor in front of
  the same compiler. The monitor rejects only surface-structural defects that
  a normalizer, a helpful model, or a grader could silently "repair".
- C `canonical_bridge` — guard, then a language model that may only propose
  controlled-language text, then the frozen Phase 2.1 grammar as the only
  authority that can mint Mission IR.
- D `simplex_canonical` — guard, then try the frozen grammar first (no model
  call on success), and escalate to the canonicalizer only when the grammar
  refuses.

The design intent came from runtime-assurance and neuro-symbolic practice:
never let a generative component be the last word on a safety-relevant
decision, keep deterministic monitors cheap, and keep capability and risk
verdicts out of the language layer entirely.

## 3. What was frozen, and what was not allowed to move

Protocol, both prompts, the guard rule set and the scoring rules were frozen
before the fresh blind campaign. No prompt tuning, guard edits, thresholds or
scoring changed afterwards. The two failure classes that later mattered were
defined in advance: silent repair (MALFORMED source becoming a mission) and
unsafe acceptance (a should-reject input reaching an executable mission).

## 4. What actually happened

- A reproduced the Phase 2.2 problem at scale: 37 of 74 malformed inputs
  became missions on fresh blind (silent repair rate 0.500), and both known
  holes were accepted in controlled regression. High exact IR (0.9857) did not
  matter: the architecture was eliminated by the hard safety gate.
- B closed the fail-open completely. The guard rejected 50 fresh-blind inputs
  with zero false positives on valid inputs, kept exact IR and coverage at
  A's level (0.9857 / 0.9833), reached 1.0 / 0 unsafe on controlled
  regression, and was perfectly repeatable (1.0 across status, error code,
  route, semantic IR).
- C and D eliminated fail-open as well, but paid for it in capability. C fell
  to 0.9571 exact / 0.9500 coverage and missed the controlled 1.0 gate
  (0.9635); D reached 0.9714 / 0.9667. Both lost valid inputs inside the
  canonicalization stage, and C additionally hit one genuine provider failure.
- The efficiency story pointed the other way: D used 113 provider calls and
  184,791 tokens versus B's 129 calls and 247,155 tokens. The temptation was
  to read the cheaper architecture as the better one; the frozen semantic
  gates made that reading inadmissible.

## 5. The result we did not expect to need

The more "interesting" neuro-symbolic stack — canonicalizer plus grammar
round-trip — did not win. It bought safety that the guard alone already
bought, and it paid with coverage and complexity. The experiment's own
conclusion is that the smallest sufficient architecture was the guard plus the
direct compiler. That is a negative result for architectural sophistication
and a positive result for the minimality principle: prefer the simplest
architecture that satisfies all frozen gates.

## 6. Failure modes are not equal

The failure taxonomy (Figure 4) made the severity layering explicit: fail-open
execution (A only) cannot be counted in the same breath as a fail-closed
refusal or a refusal-class mismatch. B's residual failures are refusals and
classification noise; C/D's residuals are lost coverage. The experiment also
kept language safety and capability safety separate: `forward 25 m` compiles
to Mission IR for every treatment, passes static validation, and is rejected
downstream by the grounder as `CAPABILITY_UNKNOWN` with zero executed steps.
The compiler never pretends to own capability or risk.

## 7. Unresolved questions carried forward

- The shared direct-LLM path still loses one valid fresh input
  (`blind2-valid-stand-02`, classified UNSUPPORTED in A and B). Guarding does
  not fix model-side capability limits.
- Refusal-class classification is not perfect (3/2/3/3 mismatches on fresh
  blind; `cl-h-011` on controlled regression). These stay fail-closed but
  would matter for diagnosis quality.
- B's latency evidence is reconstructed, not measured online; future
  campaigns should capture online latency for the selected architecture.
- The `lark_calls` diagnostics counter undercounts canonicalized routes. It
  does not affect B, but it should be fixed before C/D-style routes are used
  again for observability.
- Whether the guard rule set generalizes beyond the frozen corpora is a
  Phase 2.3 question; this experiment only demonstrates it on frozen evidence.

See `experiments/phase2/simplex_compiler_001/report.md` for the full numbers
and `docs/research-decisions.md` (D010) for the formal decision record.
