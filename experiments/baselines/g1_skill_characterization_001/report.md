# Phase 1.1 - G1 Skill Competence Characterization

Experiment: `g1_skill_characterization_001`. Robot: official 12-DOF G1 description
(`unitree_rl_gym` @ `276801e46c5d433564f24658bac64f254b7d2d4b`), controller: the official
pretrained TorchScript policy through the ported official MuJoCo deployment pipeline.
Campaign commit: `6c6af0475c1191800c313dbae2989ed127903596`. Protocol SHA-256:
`007b316f2334021c02865858988e758adb6f5d0b99bf6c9d09618c7dc80a45fb`.

This phase is characterization, not optimization: no controller parameter, threshold or
policy weight was tuned, and the known lateral drift / heading bias were measured rather
than corrected.

## 1. Verdict

**PASS.** The frozen protocol ran end to end: 237/237 final runs completed with a
classified outcome, all 18 perturbation conditions succeeded, and the resulting
competence map is machine-readable and traceable to a single committed revision.

## 2. Frozen protocol

`experiments/baselines/g1_skill_characterization_001/protocol.yaml` (byte-identical copy
of `configs/experiments/g1_skill_characterization_001.yaml`, hash above) was committed in
`4a9bc81` **before** the final campaign and was not modified afterwards.

| Scope | Definition |
| --- | --- |
| Nominal WalkForward | 0.5 / 1.0 / 2.0 / 3.0 / 5.0 m, 3 repetitions, speed command 0.5 m/s |
| Nominal Turn | -90 / -60 / -45 / -30 / +30 / +45 / +60 / +90 deg, 3 repetitions, yaw-rate command 0.5 rad/s |
| Nominal Stand | 5 / 10 / 20 s, 3 repetitions |
| Stop characterization | command 0.25 / 0.5 / 0.75 m/s, 3 repetitions, 3 s warm-up, 4 s measurement window |
| Robustness | tasks WalkForward(2 m), Turn(+45 deg), WalkForward(2 m)->Stop x conditions nominal / yaw / xy_offset / joint / friction / push x seeds 0-9 |
| Walk tolerance | `max(0.2 m, 10% of target)` (Phase 1's 0.2 m at 2 m, extended with a floor) |
| Turn tolerance | 15 deg (frozen in the Phase 1 turn pilot) |
| Stop criterion | trailing 1.0 s mean speed < 0.10 m/s (frozen in Baseline-001) |
| Fall / finite | adapter's Phase 1 fall logic; non-finite state is a classified failure |
| Perturbation envelope | yaw +/-10 deg; XY offset +/-0.05 m; joint position sigma 0.02 rad, velocity sigma 0.05 rad/s; friction slide U(0.4, 1.2); push 6-10% body weight (19.98-30.78 N) for 0.2 s along +Y, triggered 0.4-2.0 s into the task |

Lateral drift and heading error for WalkForward are **report-only** metrics: no defensible
pass/fail threshold exists yet, so none was invented. Every run wrote
`manifest.json` / `metrics.json` / `events.jsonl` under
`artifacts/g1_skill_characterization_001/final/<run_id>/`.

## 3. Nominal competence

All nominal experiments were run 3 times each; every repetition produced identical
trajectories (section 4).

### WalkForward (deterministic, 3/3 identical per target)

| Target | Distance error | Lateral drift | Heading error | Completion | Mean speed |
| --- | --- | --- | --- | --- | --- |
| 0.5 m | 0.0009 m | -0.159 m | -4.37 deg | 1.34 s | 0.374 m/s |
| 1.0 m | 0.0000 m | -0.189 m | -4.08 deg | 2.39 s | 0.419 m/s |
| 2.0 m | 0.0002 m | -0.290 m | -6.47 deg | 4.50 s | 0.445 m/s |
| 3.0 m | 0.0004 m | -0.386 m | -7.28 deg | 6.61 s | 0.454 m/s |
| 5.0 m | 0.0007 m | -0.707 m | -10.73 deg | 10.84 s | 0.461 m/s |

Distance tracking is exact to ~1 mm because the skill hands over when the measured
displacement crosses the target; the tracking error of the underlying velocity command is
visible instead in the drift and heading columns.

### Turn (deterministic, 3/3 identical per angle)

| Target | Actual | Absolute error | Translation drift | Completion |
| --- | --- | --- | --- | --- |
| -90 deg | -91.24 deg | 1.24 deg | 0.227 m | 3.78 s |
| -60 deg | -60.85 deg | 0.85 deg | 0.188 m | 2.68 s |
| -45 deg | -45.95 deg | 0.95 deg | 0.169 m | 2.13 s |
| -30 deg | -30.49 deg | 0.49 deg | 0.141 m | 1.57 s |
| +30 deg | 30.08 deg | 0.08 deg | 0.122 m | 1.71 s |
| +45 deg | 45.40 deg | 0.40 deg | 0.156 m | 2.27 s |
| +60 deg | 59.93 deg | 0.07 deg | 0.169 m | 2.84 s |
| +90 deg | 90.23 deg | 0.23 deg | 0.177 m | 3.96 s |

### Stand (deterministic, 3/3 identical per duration)

| Duration | Height mean | Height min | Max abs roll | Max abs pitch | Position drift |
| --- | --- | --- | --- | --- | --- |
| 5 s | 0.778 m | 0.773 m | 4.04 deg | 3.31 deg | 0.092 m |
| 10 s | 0.778 m | 0.773 m | 4.04 deg | 3.31 deg | 0.217 m |
| 20 s | 0.778 m | 0.773 m | 4.04 deg | 3.31 deg | 0.447 m |

Attitude stability does not degrade with duration, but the base keeps creeping at
roughly 2.2 cm/s; standing is not position-stationary.

### Stop (deterministic, 3/3 identical per command)

| Approach speed | Velocity before stop | Time to threshold | Distance after command | Residual mean 1 s | Residual max 1 s | Residual mean 2 s |
| --- | --- | --- | --- | --- | --- | --- |
| 0.25 m/s | 0.261 m/s | 1.080 s | 0.100 m | 0.111 m/s | 0.253 m/s | 0.088 m/s |
| 0.50 m/s | 0.484 m/s | 1.308 s | 0.188 m | 0.190 m/s | 0.478 m/s | 0.128 m/s |
| 0.75 m/s | 0.716 m/s | 1.528 s | 0.292 m | 0.296 m/s | 0.703 m/s | 0.180 m/s |

The Phase 1 criterion (trailing 1.0 s mean < 0.10 m/s) was sustained in every run, and
stopping time/distance scale with the approach speed.

## 4. Determinism

- Nominal WalkForward/Turn/Stand/Stop: 3/3 repetitions identical for every condition
  (`deterministic_repetition = true`). These are single deterministic trajectories, not
  statistical samples; their standard deviations are not robustness evidence.
- Robustness `nominal` and `xy_offset` conditions: all 10 seeds identical (1/10 unique
  metric vectors) - an XY offset does not change relative trajectory metrics.
- Robustness `yaw`, `joint`, `friction`, `push`: 10/10 unique metric vectors per task
  (tables in section 5), so the seeds now produce genuinely different physical
  trajectories (Phase 1's five identical seeds are resolved).

## 5. Robustness

Success rate was 1.0 in every group (10 seeds per cell). Values are group means.

| Task | Condition | Displacement / turned | Lateral drift / translation | Heading error | Deterministic |
| --- | --- | --- | --- | --- | --- |
| WalkForward 2 m | nominal | 2.001 m | -0.094 m | -4.49 deg | yes |
| WalkForward 2 m | yaw | 2.000 m | -0.093 m | -4.46 deg | no |
| WalkForward 2 m | xy_offset | 2.001 m | -0.094 m | -4.49 deg | yes |
| WalkForward 2 m | joint | 2.000 m | -0.093 m | -4.41 deg | no |
| WalkForward 2 m | friction | 2.000 m | -0.079 m | -3.95 deg | no |
| WalkForward 2 m | push (+Y) | 2.000 m | +0.076 m | -1.96 deg | no |
| Turn +45 deg | nominal | 45.43 deg | 0.065 m | 0.43 deg | yes |
| Turn +45 deg | yaw | 45.44 deg | 0.065 m | 0.44 deg | no |
| Turn +45 deg | xy_offset | 45.43 deg | 0.065 m | 0.43 deg | yes |
| Turn +45 deg | joint | 45.31 deg | 0.081 m | 0.31 deg | no |
| Turn +45 deg | friction | 45.35 deg | 0.066 m | 0.35 deg | no |
| Turn +45 deg | push | 45.30 deg | 0.098 m | 0.30 deg | no |
| Walk 2 m -> Stop | nominal | 2.152 m | -0.105 m | -5.27 deg | yes |
| Walk 2 m -> Stop | yaw | 2.152 m | -0.104 m | -5.23 deg | no |
| Walk 2 m -> Stop | xy_offset | 2.152 m | -0.105 m | -5.27 deg | yes |
| Walk 2 m -> Stop | joint | 2.148 m | -0.104 m | -5.19 deg | no |
| Walk 2 m -> Stop | friction | 2.151 m | -0.088 m | -4.74 deg | no |
| Walk 2 m -> Stop | push | 2.144 m | +0.069 m | -2.68 deg | no |

Sampled perturbation values (recorded per run): friction slide 0.469-1.154 (10 unique),
push force 19.98-30.78 N (10 unique), maximum joint offset 0.026-0.067 rad, yaw +/-10 deg,
XY +/-0.05 m. Perturbations changed trajectories measurably but never crossed a failure
boundary within this envelope.

## 6. Failure taxonomy

The taxonomy implemented in `src/g1swarm/characterization/failures.py`:
`SUCCESS`, `FALL`, `TIMEOUT`, `DISTANCE_ERROR`, `HEADING_ERROR`, `EXCESSIVE_DRIFT`,
`FAILED_TO_STOP`, `UNSTABLE`, `NON_FINITE_STATE`, `INVALID_CONTROL`, `SKILL_UNAVAILABLE`,
`PRECONDITION_FAILED`, `INTERRUPTED`, `UNKNOWN_FAILURE`. Every record carries
`failure_type` and `failure_reason`.

Final campaign: 237/237 `SUCCESS` (no FALL, TIMEOUT, DISTANCE_ERROR or failure to stop).

Observed failure (pilot, and a real implementation bug):

| Item | Evidence |
| --- | --- |
| Symptom | `a2-turn--45deg-rep0-seed000`: target -45 deg, actual +45.40 deg, absolute heading error 90.40 deg -> `HEADING_ERROR` |
| Root cause | `TurnSkill` commanded a fixed `+0.5 rad/s` yaw rate and only compared `abs(turned)` against `abs(target)`; the sign of the target was ignored |
| Why it is a code bug, not controller performance | the official policy supports yaw commands in `[-1, 1] rad/s`; +45 deg runs already tracked within 0.4 deg, and after the one-line sign fix -45 deg tracks within 0.95 deg |
| Fix | command yaw rate = `sign(target) * abs(yaw_rate)`; metric `yaw_rate_command_radps` recorded |
| Before / after | before: 45.40 deg in the wrong direction (error 90.40 deg). After: -45.95 deg (error 0.95 deg), pilot re-run 34/34 SUCCESS |
| Preserved evidence | `artifacts/g1_skill_characterization_001/pilot-before-turn-fix/` (before) and `.../pilot/` (after), plus the final campaign |

A reporting bug was also found and fixed before the reported final run: the first final
pass completed all 237 runs but the summary crashed converting the string task key
`walk_forward_2m` to float; nominal aggregation now filters numeric-task records, with a
regression test (`6c6af04`). No run result changed.

## 7. Competence map

`experiments/baselines/g1_skill_characterization_001/competence_map.json`, schema version
`1.1.0`. It contains `robot` and `controller` provenance (revisions + policy SHA-256),
`source_commit`, and for each of `walk_forward`, `turn`, `stop`, `stand`:
`preconditions`, `success_criteria`, `nominal`, `conditions` (robustness groups),
`known_failure_modes` and `evidence` (experiment id, campaign, artifact path, run count).
It is generated from the frozen protocol and the final summary only, validated by
`validate_competence_map`, and contains no decision-model-specific fields: it is generic
robot-capability evidence intended to be readable by a future Skill Router, Jev or
multi-swarm layer.

## 8. Important findings

1. **Lateral drift is distance-dependent, not a fixed bias.** -0.159 m at 0.5 m,
   -0.290 m at 2 m, -0.707 m at 5 m: approximately proportional to walk duration
   (roughly -0.065 m/s of sideways creep while the command asks for straight walking).
2. **Heading bias grows with distance** (-4.4 deg at 0.5 m to -10.7 deg at 5 m), i.e. a
   roughly -2 deg/s yaw drift under the forward command rather than a constant offset.
3. **Stop is repeatable and speed-proportional**: 1.08-1.53 s and 0.10-0.29 m to satisfy
   the frozen trailing-window criterion, with residual 1 s mean speeds above the
   threshold (0.111-0.296 m/s) and residual 2 s means of 0.088-0.180 m/s - the criterion
   passes only via its trailing-window definition.
4. **Friction sensitivity is mild within U(0.4, 1.2)**: heading bias moves from -4.49 deg
   to -3.95 deg and lateral drift from -0.094 m to -0.079 m compared with nominal.
5. **A 6-10% body-weight lateral push is absorbed without a fall** (10/10), changing the
   lateral drift sign (+0.076 m) and reducing the apparent heading bias (-1.96 deg).
   There is no recovery skill; the policy simply tolerates the push.
6. **Seeds now matter**: all four sampled perturbation conditions produce 10/10 unique
   trajectories, while nominal and xy_offset remain deterministic.
7. **Standing creeps**: attitude is stable over 20 s but the base drifts 0.45 m, so
   "Stand" should not be treated as position hold.
8. **The pre-task stand phase changes locomotion metrics**: robustness runs (which start
   the task right after reset) show about -4.5 deg heading error and -0.09 m drift at
   2 m, while the nominal command-tracking runs (2 s stand phase first) show -6.5 deg and
   -0.29 m. Both families are internally consistent; the difference is documented rather
   than normalized away.

## 9. Tests

`python -m pytest -q`: **54 passed, 0 failed** (3 benign `torch.jit.load` deprecation
warnings). The Phase 1 suite (21 tests) is unchanged and still passes; 33 new tests cover
perturbation seed reproducibility, failure classification, precondition rejection,
competence map serialization, summary aggregation and deterministic marking.

## 10. Negative findings

- The frozen perturbation envelope is **below the failure boundary**: 0 failures across
  180 robustness runs, so the competence map describes a no-failure envelope, not the
  policy's limits. Stronger perturbations are needed to find failures.
- Only one of the four perturbation types (push) visibly changed the mean trajectory;
  yaw and XY offsets are largely absorbed; joint noise and friction changed trajectories
  at the millimetre/0.1 deg level (statistically visible only because runs are exact).
- WalkForward drift/heading thresholds do not exist yet; the competence map deliberately
  leaves them as continuous metrics.
- The stop criterion passes with residual 1 s mean speeds up to 0.296 m/s; the map
  reports the criterion and the residual curves rather than a single "stop works" claim.
- No failure recovery behavior exists; robustness here means tolerance, not recovery.
- The 29-DOF full-body model still has no controller (Phase 1 compatibility evidence
  only), and no manipulation/other skill families were characterized.

## 11. Git

| Item | Value |
| --- | --- |
| Branch | `phase1.1/skill-characterization` (from frozen Phase 1 `217fc71`) |
| HEAD | see the final summary in the task report (implementation `4a9bc81`, aggregation fix `6c6af04`, report commit follows) |
| Working tree | clean after the report commit |
| Phase 1 branch | untouched; Phase 1 artifacts not overwritten |
| Push | not possible from this machine (no credentials); command in the task report |

## 12. Next recommendation

Based on the measured results: **Phase 1.2 should (a) widen the perturbation envelope**
(larger pushes, lower friction, bigger joint offsets, sustained pushes) to locate the
actual failure boundary, and **(b) decide whether to add forward-heading/lateral
correction**, since drift and heading error are systematic and distance-dependent rather
than random. Only after the failure boundary and correction decision are known does a
Phase 2 conversational mission baseline have a trustworthy competence profile to route
against. No next phase is started here.
