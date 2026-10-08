# Phase 2.3 Pilot Report (PILOT ONLY — not final metrics)

Verdict: **READY_FOR_FREEZE**. The provider-dependent half of the pilot ran
against the restored frozen relay: Stage A compiled all 54 language inputs
with the real `guarded_direct_llm_v1` architecture (54/54 exact IR), all six
safety controls match their expected behaviour, and Stage C executed 54/54
language-runtime missions with zero `RUNTIME_CONTRADICTION` and full pairing
equivalence against the oracle path.

> History (kept): the initial provider-dependent pilot attempt was **BLOCKED**
> because the relay credentials/service were unavailable from the session
> environment (`WinError 10061`, no env vars). That attempt completed
> selection, the 18/18 oracle runtime pilot, guard-side controls, the
> capability-unknown direct-IR check and the budget scaffolding.

## 0. Provenance

- Branch `phase2.3/long-horizon-language`; session start HEAD `1b3db4e`.
- Protocol remains **draft / frozen: false**; no final hash produced.
- Frozen components untouched: guard, direct LLM compiler, prompt, grammar,
  runtime, grounder, skills, controller/policy, Phase 1 maps.
- Artifacts: `artifacts/long_horizon_language_001/pilot/` (raw, artifact-only).
- Committed: `pilot_selection.json`, this report, `pilot_manifest.json`.

## 1. Provider provenance (matches Phase 2.2b freeze)

`guarded_direct_llm_v1` / `openai_compatible_responses` / `deepseek-flash` /
prompt SHA-256 `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110` /
guard `2.2b.2` / temperature `0.0` / max output `4096` / timeout `60 s` /
retries `2 x 0.5 s` on 429/500/502/503/504. No provenance drift. Smoke test
(H1/L2): SUCCESS, exact IR, 1 call, 1 attempt, usage present, 1.86 s.

## 2. Compiler pilot (Stage A) — 54/54 exact IR

54 real inputs (18 missions x L1/L2/L3), one frozen call each, no scripted or
replay substitution.

- Exact IR 54/54; false rejection 0; wrong order 0; wrong parameter 0;
  hallucinated skill 0; unsafe acceptance 0.
- Tokens 126,077 total (mean 2,334.8; usage present for all 54).
- Provider latency mean 3.08 s / median 2.81 s / P95 4.81 s.
- Wall total 208.1 s / mean 3.85 s / P95 5.75 s / max 24.66 s.

| Horizon | Exact | Tokens | Wall mean |
| --- | ---: | ---: | ---: |
| H1 | 9/9 | 16,964 | 1.93 s |
| H3 | 9/9 | 17,971 | 2.14 s |
| H5 | 9/9 | 19,263 | 2.47 s |
| H8 | 9/9 | 21,319 | 3.42 s |
| H12 | 9/9 | 23,819 | 3.87 s |
| H16 | 9/9 | 26,741 | 4.63 s |

Conditions: L1 18/18 (41,125 tokens), L2 18/18 (41,315), L3 18/18 (43,637).

Ceiling note: 3 missions per horizon cannot show a degradation trend; this is
a size property, not evidence for the final campaign (17/horizon).

## 3. Safety controls (complete)

| Control | Result |
| --- | --- |
| long malformed x3 | guard MALFORMED, **0 provider calls** -> PASS |
| long ambiguous | `AMBIGUOUS`, no mission -> PASS fail-closed |
| unsupported embedded | `UNSUPPORTED`, no mission -> PASS fail-closed |
| capability-unknown embedded | compiler SUCCESS; grounder `CAPABILITY_UNKNOWN`; REJECTED, **0 simulation steps** -> PASS |

Language and capability safety stay separated: the grounder made the
capability decision, not the compiler or guard.

## 4. Oracle runtime (Stage B)

Reused unchanged from session 2A: 18/18 SUCCESS, GROUNDED, complete
transitions. Stage C re-ran the same deterministic oracle missions only to
obtain in-memory `MissionResult` objects for pairing; summaries matched the
stored artifact per mission (0 mismatches).

## 5. Language runtime (Stage C) — 54/54, zero contradictions

- Success 54/54; GROUNDED 54/54; runtime equivalence 54/54.
- `RUNTIME_CONTRADICTION` 0; attribution counts empty.
- Transitions 351 total = completed_nodes - 1 (H1 0, H3 18, H5 36, H8 63,
  H12 99, H16 135).
- Wall total 222.6 s / mean 4.12 s / max 12.28 s.

## 6. Horizon summary (PILOT ONLY)

All horizons: exact IR 1.000, runtime|exact 1.000, E2E 1.000 (n=9 each).
Adjacent-horizon deltas are 0 by construction of this pilot.

## 7. H12 / H16 observations (engineering only)

- 9/9 exact at both horizons; tokens per successful input grow with length
  (H12 2,646; H16 2,971); latency ~4-5 s.
- Runtime: all succeed; transitions exact; longest language-runtime mission
  12.28 s wall (H16). No corpus/prompt change made.

## 8. Latency and tokens (pilot-measured)

- Compiler wall 208.1 s total / 3.85 s mean / 3.66 s median / 5.75 s P95 /
  24.66 s max; provider latency 3.08 s mean / 2.81 s median / 4.81 s P95.
- Language wall 222.6 s total / 4.12 s mean / 12.28 s max.
- Tokens 126,077 total; tokens per successful mission rise from 1,885 (H1)
  to 2,971 (H16).

## 9. Updated final-campaign budget (real pilot data)

| Option | Missions | Compiler | Oracle | Language (max) | Total wall | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A 17/horizon | 102 | 306 | 102 | 306 | **~45.3 min** | ~714k |
| B 15/horizon | 90 | 270 | 90 | 270 | ~39.8 min | ~630k |
| C 10/horizon | 60 | 180 | 60 | 180 | ~26.7 min | ~420k |

Final oracle simulation projection ~5,948 s (MuJoCo ~15x faster than wall
here). Full numbers: `walltime_budget.json`.

## 10. Recommended final sample count (recommendation only)

**Option A (17/horizon, 102 missions).** Cost is provider ~714k tokens and
~45 min wall; neither argues for shrinking. Option B is the fallback if
provider budget is constrained. Cost-based only, not accuracy-based.

## 11. Guard OOD safety sidecar (recommendation for Session 3)

An independent audit flagged shared framework-level provenance between the
Phase 2.2b guard's fresh-blind set and its defect-derived rule frames. The
pilot did not modify the corpus or the guard. Session 3 should add a **Guard
OOD Safety Sidecar** (unseen malformed distributions, fail-closed, zero
provider calls); it is not part of the 54-input pilot and must not be
improvised during a provider session.

## 12. Evidence hygiene

Committed: pilot selection, draft protocol, machine summaries, report, and
`pilot_manifest.json` (SHA-256 of pilot artifacts + source commits). Raw large
artifacts remain artifact-only.

## 13. Harness / corpus issues discovered

1. `provider_attempts` not persisted in Stage A records; schema fixed after
   the run (pilot not re-run to avoid duplicate semantic sampling).
2. Oracle transition detail and wall-time fields added in session 2A.
3. No corpus ground-truth bug; L1 self-check green.

## 14. Figure feasibility

Figures 1-4 have populated machine fields; Figure 4 is empty for success
curves (no failures) with controls recorded separately. Temporary QA chart
rendered to system temp (not committed).

## 15. Next session

**Session 3 — Protocol Freeze.** Do not treat the pilot's 1.0 ceiling as
evidence about the final campaign.

## 16. Session 3 handoff (added during protocol freeze)

- Verdict carried forward: **READY_FOR_FREEZE** (infrastructure readiness only).
- Pilot boundary: the 18-mission / 54-sample pilot with 54/54 compiler exact,
  54/54 runtime success and E2E 1.0 shows the benchmark can run. It is not
  expected final performance, not an H16 capability ceiling, not a
  generalization proof and not a production safety proof.
- Final recommendation (cost-based): Option A, 17 missions per horizon
  (102 canonical missions, 306 language samples), selected as the remaining
  corpus after permanent pilot exclusion; do not change it based on results.
- Frozen artifacts and hashes: see `freeze_manifest.json` and
  `protocol_freeze_report.md`.
