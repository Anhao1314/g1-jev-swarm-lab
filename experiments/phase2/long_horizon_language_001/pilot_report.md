# Phase 2.3 Pilot Report (PILOT ONLY — not final metrics)

Verdict: **BLOCKED** — the frozen provider was unavailable from this session,
so the real compiler pilot (Stage A) and the language-runtime pilot (Stage C)
could not run. Everything that does not require the provider was completed:
deterministic pilot selection, the 18-mission oracle runtime pilot, guard-level
safety-control checks, the capability-unknown zero-step atomicity check, wall
time instrumentation, budget estimation, figure-field verification and
harness fixes found by the pilot.

## 0. Provenance

- Branch: `phase2.3/long-horizon-language`; starting HEAD `e2c5f80`.
- Protocol: `experiments/phase2/long_horizon_language_001/protocol.yaml`
  remains **draft / frozen: false**. No final protocol hash was produced.
- Frozen components were not modified (verified by diff): compiler, guard,
  prompt, Phase 2.1 grammar, Phase 2.0 runtime, grounder, skills,
  controller/policy, Phase 1 maps.
- Pilot artifacts (gitignored):
  `artifacts/long_horizon_language_001/pilot/` — `pilot_selection.json`,
  `canonical_missions.yaml`, `language_realizations.yaml`,
  `safety_controls.yaml`, `oracle_runtime_results.json`,
  `safety_controls.json`, `walltime_budget.json`.
- Committed pilot documents:
  `experiments/phase2/long_horizon_language_001/pilot_selection.json`,
  this report.

## 1. Provider availability (blocker)

- `LLM_COMPILER_BASE_URL`, `LLM_COMPILER_API_KEY`, `OPENAI_API_KEY`,
  `OPENAI_BASE_URL` are absent from the process, user and machine environment.
- The relay endpoint used by the earlier Phase 2.x sessions was located in the
  machine's own session history; a connection attempt was refused
  (`WinError 10061`), i.e. the relay process is not running.
- No candidate local LLM service is listening on the usual ports
  (11434 / 1234 / 8000 / 8080 / 5000 / 7860 / 30000 / 11435).
- Credential values were never printed or written to any evidence file.
- `--scripted` was deliberately **not** used as pilot evidence (protocol §6).

To resume: start the frozen relay and export `LLM_COMPILER_BASE_URL` plus one
of `LLM_COMPILER_API_KEY` / `OPENAI_API_KEY`, then run
`python scripts/run_long_horizon.py --out-dir artifacts/long_horizon_language_001/pilot compile`
followed by `... runtime`, then `... summarize`.

## 2. Pilot selection (deterministic, result-blind)

3 missions per horizon (18 total), covering walk-dominant / turn-dense / mixed
profiles; all mission IDs are `excluded_from_final = true`. Selection ranks
candidates purely from canonical IR shape (no run results). Full table:
`pilot_selection.json`.

| Horizon | Profile | Mission ID | Steps |
| --- | --- | --- | ---: |
| H1 | walk_dominant | `lh-h1-00-w4` | 1 |
| H1 | turn_dense | `lh-h1-01-r30` | 1 |
| H1 | mixed | `lh-h1-02-s1` | 1 |
| H3 | walk_dominant | `lh-h3-00-s5-w6-x` | 3 |
| H3 | turn_dense | `lh-h3-01-w8-l30-x` | 3 |
| H3 | mixed | `lh-h3-02-w8-r30-x` | 3 |
| H5 | walk_dominant | `lh-h5-08-w6-s2-w8-s5-x` | 5 |
| H5 | turn_dense | `lh-h5-01-s2-r90-w10-l45-x` | 5 |
| H5 | mixed | `lh-h5-00-s2-r45-w10-s5-x` | 5 |
| H8 | walk_dominant | `lh-h8-01-w12-r60-w4-l45-w6-s1-w8-x` | 8 |
| H8 | turn_dense | `lh-h8-03-s5-r45-w15-r30-s1-l90-w8-x` | 8 |
| H8 | mixed | `lh-h8-02-w6-r60-s1-w15-s5-l60-s5-x` | 8 |
| H12 | walk_dominant | `lh-h12-02-w12-l90-s1-w10-s1-l30-w6-s5-w4-s2-w20-x` | 12 |
| H12 | turn_dense | `lh-h12-00-w4-r60-s1-l60-w15-l90-w10-r45-w12-s5-r30-x` | 12 |
| H12 | mixed | `lh-h12-09-s2-l30-w4-s2-r90-s5-l60-w12-l60-w8-s2-x` | 12 |
| H16 | walk_dominant | `lh-h16-10-w4-s1-w20-l45-s2-w8-s5-l90-w10-s2-w6-s1-w10-s2-w6-x` | 16 |
| H16 | turn_dense | `lh-h16-14-s1-w4-r90-s5-r30-s2-l45-s5-l90-s5-r45-s1-r90-w20-r30-x` | 16 |
| H16 | mixed | `lh-h16-03-w8-s5-w6-r60-s5-w10-l90-s5-r45-w10-l45-s5-w6-s5-r45-x` | 16 |

Fallbacks (recorded in `pilot_selection.json`): H1 is single-step, so the three
profiles map to one primitive each (walk / turn / stand); H3 has no strictly
mixed mission in the current corpus, so the mixed slot used the deterministic
minimum-imbalance fallback. Neither fallback depends on results.

## 3. Compiler pilot (Stage A)

**NOT RUN — provider unavailable.** 0 of 54 language inputs compiled.
Nothing about compiler behaviour, exact IR, latency or tokens may be inferred
from this pilot; no partial sample was run to avoid bias.

Reference-only (NOT pilot data, clearly labeled as Phase 2.2b evidence):
selected architecture B achieved fresh-blind exact IR 0.9857 / coverage
0.9833 with 1,380.75 provider tokens per user mission and a provider-inclusive
reconstructed latency of median 1.56 s / P95 2.61 s.

## 4. Oracle runtime pilot (Stage B) — 18/18 SUCCESS

All 18 canonical pilot missions executed through the frozen Phase 2.0 runtime
in a single continuous run per mission (no in-mission simulator resets),
grounding GROUNDED 18/18, mission success 18/18, zero failures.

| Horizon | n | wall mean / max (s) | sim time mean / max (s) | steps mean |
| --- | ---: | ---: | ---: | ---: |
| H1 | 3 | 0.84 / 2.15 | 3.8 / 8.7 | ~1.9k |
| H3 | 3 | 1.49 / 1.57 | 19.7 / 20.0 | ~9.8k |
| H5 | 3 | 2.13 / 2.45 | 33.3 / 38.0 | ~16.6k |
| H8 | 3 | 4.18 / 4.57 | 65.9 / 71.4 | ~32.9k |
| H12 | 3 | 6.51 / 8.16 | 103.0 / 126.8 | ~51.5k |
| H16 | 3 | 7.43 / 9.56 | 124.3 / 157.1 | ~62.1k |

H12/H16 feasibility: confirmed. No runtime hard timeout was hit; the slowest
H16 mission completed in 9.56 s wall / 157.1 s simulation time. MuJoCo runs
roughly 15x faster than real time on this machine for these missions.

Transition instrumentation: every mission records `transition_count` and the
full ordered transition list (`previous_skill`, `next_skill`,
`position_delta_m`, `heading_delta_deg`, `controller_memory_reset`); counts
match `completed_nodes - 1` (0 for single-step H1). Controller-memory reset
semantics are unchanged (each inter-skill transition records a reset).

## 5. Language runtime pilot (Stage C)

**NOT RUN — depends on Stage A exact-IR samples.** No language runtime record
exists, therefore no paired comparison and no `RUNTIME_CONTRADICTION` could be
assessed. The oracle-only runs used the frozen runtime directly; no
contradiction of the "same IR -> same behaviour" invariant was observed
(there was no second path to compare).

## 6. Safety controls

| Control | Guard | Compiler | Runtime | Result |
| --- | --- | --- | --- | --- |
| long malformed ×3 | MALFORMED (REPEATED_CONNECTOR / EMPTY_CLAUSE / REPEATED_SEPARATOR) | 0 provider calls (by construction) | not executed | PASS (guard-side) |
| long ambiguous | PASS (structural only) | NOT RUN (provider) | not executed | BLOCKED |
| unsupported embedded | PASS (structural only) | NOT RUN (provider) | not executed | BLOCKED |
| capability-unknown embedded | PASS | NOT RUN (provider) | direct-IR check: REJECTED, `CAPABILITY_UNKNOWN`, **0 simulation steps** | runtime half PASS; compiler half BLOCKED |

Guard-side notes: the dangling-connector control is rejected by the
"connector followed by punctuation" rule (`EMPTY_CLAUSE`) rather than the
trailing-connector rule; the empty-clause control is rejected by
`REPEATED_SEPARATOR`. Both are fail-closed outcomes.

## 7. Wall-time instrumentation

- Compiler: fields added (`wall_time_s` per sample, plus latency/token
  aggregates) but no pilot measurement (provider unavailable).
- Oracle runtime: measured (section 4); per-mission wall and simulation time
  are recorded separately.
- Language runtime: not measured.

## 8. Provider / token budget

Pilot provider usage: **not measured** (0 calls). Reference-only projection for
306 compiler inputs (17/horizon × 3 conditions) using Phase 2.2b’s 1,380.75
tokens per mission: **≈ 422,500 provider tokens**. Compiler wall time cannot
be honestly projected from this pilot; Phase 2.2b reconstruction suggests
roughly 8–13 minutes total for 306 calls at median 1.56 s / P95 2.61 s.

## 9. Estimated final campaign budget

Assumptions: 6 horizons, 3 language conditions, final missions per horizon as
in each option; runtime wall ≈ pilot oracle measurements; language wall = 3×
oracle wall (worst case, all samples exact IR); simulation time ≈ measured.

| Option | Missions | Compiler inputs | Oracle runs | Language runs (max) | Oracle wall | Language wall (max) | Simulation time | Tokens (reference) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A: 17/horizon | 102 | 306 | 102 | 306 | ≈ 6.4 min | ≈ 19.2 min | ≈ 99 min | ≈ 422k |
| B: 15/horizon | 90 | 270 | 90 | 270 | ≈ 5.6 min | ≈ 16.9 min | ≈ 87 min | ≈ 373k |
| C: 10/horizon | 60 | 180 | 60 | 180 | ≈ 3.8 min | ≈ 11.3 min | ≈ 58 min | ≈ 249k |

Exact numbers: `artifacts/long_horizon_language_001/pilot/walltime_budget.json`.

## 10. Recommended final sample count (recommendation only — no freeze)

**Option A (17/horizon, 102 canonical missions).** Runtime cost is small and
scales linearly with mission count; the pilot shows H16 is comfortably within
the wall-time budget, so there is no cost-based reason to shrink the corpus.
The binding constraint is provider availability and token budget, not MuJoCo
time. If the relay remains unreliable, Option B (15/horizon) is the fallback;
this recommendation is based solely on runtime/provider cost and statistical
usefulness, never on pilot outcome (this pilot produced no language outcomes
at all). Final decision belongs to Session 3.

## 11. Corpus / harness bugs discovered and fixed

1. **Oracle evidence lacked transition detail.** `oracle_runtime_results.json`
   recorded only `transition_count`. Fixed in `run_oracle_stage` (now records
   the full transition list) and re-run; a test assertion was added.
2. **Scripted harness returned no mission for the capability-unknown control.**
   The offline stand-in mapped every control to its expected status, so the
   expected-SUCCESS control produced no IR and the grounding/runtime half could
   not be exercised. Fixed: the scripted compiler now returns the control’s
   intended IR for expected-SUCCESS controls (harness-only change).
3. **Wall-time fields were missing.** Per-sample `wall_time_s` added to
   compiler records, runtime records and control records, plus wall-time
   aggregates in `latency_tokens.json`.
4. No corpus ground-truth bug was found: the full 120-mission corpus validates
   and every L1 realization compiles to its canonical IR under the frozen
   grammar (Session 1 self-check still green). Pilot artifacts are marked
   `pilot_only` and `excluded_from_final`.

## 12. Protocol changes recommended for Session 3

- Add `compiler_pilot_completed_with_real_provider` and
  `language_runtime_pilot_completed` to the freeze checklist; the protocol must
  not be frozen while Stage A/C are NOT_RUN.
- Record in the protocol that pilot artifacts are permanently excluded and
  that the final corpus excludes the 18 pilot mission IDs.
- Keep H16 (feasibility confirmed) and keep the grounded parameter whitelist.
- Decide the final sample count (recommendation: 17/horizon) only after real
  compiler pilot data exists.

## 13. Figure feasibility

- Figure 1 (exact IR vs horizon) / Figure 2 (E2E success vs horizon) /
  Figure 4 (failure attribution): required fields exist in the compiler and
  runtime record schemas (`horizon`, `condition`, `exact_ir_match`,
  `mission_success`, `oracle`, `attribution`), but no compiler/language data
  exists in this pilot, so no series can be drawn yet.
- Figure 3 (oracle vs language runtime): the oracle series is available now
  (18 missions, wall/sim per horizon); the language series is pending.
- A temporary QA chart of oracle wall/simulation time per horizon was rendered
  to the system temp directory to confirm the plotting path; it is not
  committed.

## 14. Frozen baseline audit

`git diff` around the pilot confirms zero modifications to `src/g1swarm/llm/`,
the structural guard, prompts, the Phase 2.1 grammar, `mission/runtime.py`,
`mission/grounding.py`, skills, controller/policy or the Phase 1 maps. All
pilot changes are confined to the new `src/g1swarm/longhorizon/` harness,
`scripts/run_long_horizon.py`, and tests.

## 15. Tests

`python -m pytest -q`: **562 passed, 0 failed, 9 warnings** (556 pre-pilot +
6 new pilot tests).

## 16. Next session

Resume the provider-dependent pilot first (Stage A compile + Stage C runtime
with the frozen relay), then run **Session 3 — Protocol Freeze**. Do not freeze
the protocol while Stage A/C are NOT_RUN. The Codex developer-agent tool-call
interruption did not occur in this session; the blocker is the unavailable
local provider relay.
