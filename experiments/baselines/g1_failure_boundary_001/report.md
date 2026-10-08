# Phase 1.2 - Failure Boundary & Skill Risk Mapping

Experiment: `g1_failure_boundary_001`. Robot/controller: unchanged Phase 1 official
12-DOF G1 + pretrained Unitree policy. Frozen protocol:
`configs/experiments/g1_failure_boundary_001.yaml` (SHA-256
`9145d03a75350a61c2cd4c5b8447747923c06593e5089404d7d069684db00b4a`), committed in
`ea3bfb8` **before** the final campaign. Final campaign: 91 runs at commit `ea3bfb8`.

## 1. Verdict

**PASS.** All five one-factor boundary searches ran under the frozen protocol;
failure boundaries were measured for lateral push, friction and initial yaw, and
two searches honestly report `boundary_not_reached` inside their frozen ladders
(distance ladder started outside the safe region; joint perturbation never left
the reliable zone). No controller or policy change was made.

## 2. Frozen protocol

- Path/hash/freeze commit: see above; every run manifest records the same hash.
- Task envelopes (warehouse-corridor proxies, **experiment task constraints, not
  Unitree G1 standards**): nominal `|distance error| <= max(0.30 m, 10%)`,
  `|lateral| <= max(0.35 m, 7%)`, `|heading| <= 15 deg`, timeout `max(15 s, 6 s/m)`;
  strict: `max(0.15 m, 5%)`, `max(0.20 m, 3.5%)`, `8 deg`, `max(12 s, 5 s/m)`.
- Zones: reliable `task_success_rate >= 0.90`, transition `0.30 < rate < 0.90`,
  failure `rate <= 0.30`; risk rules in `risk_map.json` (LOW/MEDIUM/HIGH/UNKNOWN).
- One-factor-at-a-time; per-run evidence in `artifacts/g1_failure_boundary_001/final/`.

## 3. Physical vs task success (headline)

**91/91 runs were physical successes; only 54/91 were task successes.** No fall,
non-finite state or invalid control occurred in the entire final campaign. Every
failure below is a *task-envelope* failure with the robot still upright:

| Case | Physical | Task | Measured |
| --- | --- | --- | --- |
| Walk 10 m | success | failure | drift -1.440 m, heading -15.09 deg, `EXCESSIVE_DRIFT` |
| Push 60 N (final, 5 seeds) | 5/5 success | 2/5 success | mean drift +0.373 m (limit 0.35 m) |
| Push 100 N | success | failure | drift +0.80 m |
| Friction 0.15 | 3/3 success | 0/3 success | drift -2.041 m, heading -49.90 deg (slides, does not fall) |
| Initial yaw 20 deg | success | failure | world-frame drift +0.590 m |

## 4. Failure boundaries

| Experiment | Reliable region | Transition region | Failure region | Boundary estimate | Reached? |
| --- | --- | --- | --- | --- | --- |
| A_distance (reset -> walk) | none inside the frozen ladder | - | 5.0 m, 7.5 m (both task failures) | not defined; Phase 1.1 brackets 2 m pass / 5 m fail | no (`boundary_not_reached`; the 5 m "safe start" was already outside the nominal envelope under this condition) |
| B_push lateral +Y, 0.2 s | 20 N (final LOW), 30 N (exploration) | 60 N (40%), 65 N (40%) | 70 N (0%), 80/100 N (exploration, task failures) | 60 N from the 2-seed search; final 5-seed evidence shows the transition begins at 60 N | yes for the task boundary; the **fall** boundary was not reached (all physical successes up to 100 N) |
| C_friction (sliding) | 0.175 - 0.5 | - | 0.15 | 0.175 | yes |
| D_joint (initial joint sigma) | 0.02 - 0.30 rad (all ladder points) | - | none | none | no (`boundary_not_reached`; sampled offsets are clipped to joint limits) |
| E_yaw (world-frame 2 m goal) | 5 deg (LOW), 10 deg (task pass, strict violation -> MEDIUM) | - | 15 deg, 20 deg | 10 deg | yes |

## 5. Risk map

`experiments/baselines/g1_failure_boundary_001/risk_map.json` (schema 1.2.0) is a
generic, queryable capability-evidence table: `condition` (distance, push force,
friction, joint sigma, initial yaw) + `value` + `risk` + `evidence`
(n_runs, deterministic flag, physical/task success rates, strict-violation rate,
failure counts, run ids). Rules are frozen and unit-tested:
UNKNOWN (insufficient evidence) / HIGH (task <= 0.30 or physical < 0.90) /
MEDIUM (transition region or strict-envelope violation) / LOW (reliable with
sufficient evidence and no strict violations). Labels come from the deterministic
evaluator, not from any model. Deterministic conditions are marked and counted as
one independent sample.

## 6. Capability boundary map

`experiments/baselines/g1_failure_boundary_001/capability_boundary_map.json`
(schema 1.2.0): `source_commit`, `phase1_1_competence_source`, robot/controller
provenance (including the policy SHA-256), per-parameter reliable/transition/failure
regions, boundary estimates with brackets and stop reasons, known failure modes,
a risk table and evidence references. `turn`, `stop` and `stand` are explicitly
`not_explored_in_phase_1_2` and reference the Phase 1.1 competence map instead of
inventing boundaries.

## 7. Real failure modes

Final campaign taxonomy: `EXCESSIVE_DRIFT` 34, `HEADING_ERROR` 3, `SUCCESS` 54.
No `FALL`, `TIMEOUT`, `DISTANCE_ERROR`, `FAILED_TO_STOP`, `UNSTABLE`,
`NON_FINITE_STATE`, `INVALID_CONTROL`, `SLIP` or
`TASK_ENVELOPE_VIOLATION`-only runs occurred. The dominant failure mode is lateral
drift growth; at very low friction the drift is joined by large heading error
(-49.9 deg at friction 0.15). Failure taxonomy version was raised to 1.2.0 with
`SLIP` and `TASK_ENVELOPE_VIOLATION` added for future use.

## 8. Negative findings

- **The distance ladder's safe start was wrong**: 5 m was assumed safe from Phase
  1.1 (where drift was report-only), but under the frozen nominal envelope it
  already violates the drift limit (0.407 m > 0.35 m). The search honestly reports
  `boundary_not_reached` instead of a bracket; the distance boundary must be
  re-searched from 2 m in a Phase 1.2b.
- **The push fall boundary was not reached**: even 100 N (task failure) left the
  robot upright; the search stops at the first non-reliable point by design, so no
  statement about falls at >=100 N can be made from this campaign.
- **Joint perturbation never degraded the task** within 0.02-0.30 rad (clipped to
  joint limits); that condition is UNKNOWN beyond the ladder, not "safe".
- **Two-seed exploration can misplace the boundary**: 60 N looked reliable with 2
  seeds but the 5-seed final sample gave 40% task success. Fewer than 5
  non-deterministic runs are labelled UNKNOWN by rule.
- Deterministic conditions (distance, friction, yaw) repeat identical trajectories;
  their standard deviations are not independent statistical evidence.
- Strict-envelope violation makes several otherwise reliable points MEDIUM
  (e.g. friction 0.175, yaw 10-12.5 deg): "task success" and "no measurable
  degradation" are different statements.

## 9. Tests

```
81 passed, 0 failed
```
54 existing Phase 1/1.1 tests plus 27 new tests: boundary-search determinism and
bracket logic, physical-vs-task success, task-envelope evaluator (including
protocol/module consistency), risk-label mapping and UNKNOWN behaviour,
capability/risk map serialization and validation, joint-limit respect, invalid
perturbation rejection, and final-aggregation-equals-raw-evidence.

## 10. Security scan

The Codex Security plugin is not available in this session; the fallback was a
local diff scan for secrets/dangerous shell/path handling plus the MCP secret
scanning tool over the new protocol/script content. Result: no secrets, no shell
string building, no arbitrary path deletion, no download-and-execute path.
Recorded in the final task report.

## 11. Git

- Branch `phase1.2/failure-boundary` (from viewer HEAD `771bd9d`).
- Commits: harness + frozen protocol `ea3bfb8`; results/report commit follows.
- Phase 1.1 branch, `competence_map.json` and all Phase 1.1 artifacts are untouched.
- Working tree: clean after the result commit. Push: not possible from this
  machine (no credentials); command reported to the user.

## 12. Next gate

Based on the measured data the recommended next step is **C (limited Phase 1.2b)**
before any Phase 2 work: re-run the distance search from 2 m, extend the push
ladder past 100 N to find the fall boundary, and probe joint sigma beyond 0.30 rad.
Phase 1.3 (closed-loop locomotion correction) becomes worthwhile if the mission
profile needs >2-3 m straight corridors, since the open-loop drift is the dominant
failure mode. Phase 2 conversational mission baselines should not start until the
risk map covers at least the corridor distances they intend to use. Not started
here.
