# Phase 1.2b - Distance Boundary Refinement & Segmentation Study

Protocol: `configs/experiments/g1_distance_segmentation_001.yaml`, SHA-256
`cfb936c6ed947db5dedaa086b782dd34f01266aa96fbf2fbc2c4f3e0170e83da`, frozen in
commit `28fd970` before the final campaign. Task envelope reused from Phase 1.2
(nominal warehouse corridor proxy) unchanged.

## 1. Verdict

**PASS** (the research questions are answered; the answer to RQ2 is negative).

## 2. Refined distance boundary

- last reliable **4.53125 m**, first failure **4.625 m**, bracket 4.53-4.63 m
  (target resolution 0.25 m, achieved 0.09 m), deterministic repeats
- dominant failure mode `EXCESSIVE_DRIFT`; physical success in every boundary run
- provenance: Phase 1.2 bracket [2 m pass, 5 m fail] referenced, not copied

## 3. Segmentation comparison (mission frame fixed at start)

| Distance | Treatment | Task | Drift | Heading | Stops | LSTM resets | Sim time | Verdict |
|---|---|---|---|---|---|---|---|---|
| 4 m | direct_long | FAIL | -0.281 m | -6.72 deg | 0 | 1 | 8.71 s | baseline |
| 4 m | segmented_continuous | FAIL | -0.439 m | -8.09 deg | 2 | 0 | 11.74 s | no improvement |
| 4 m | segmented_reset | FAIL | -0.445 m | -10.72 deg | 2 | 2 | 11.57 s | no improvement |
| 4 m | segmented_state_aware | FAIL | -0.393 m | -9.42 deg | 2 | 0 | 11.28 s | no improvement |
| 6 m | direct_long | FAIL | -0.549 m | -9.48 deg | 0 | 1 | 12.94 s | baseline |
| 6 m | segmented_continuous | FAIL | -0.764 m | -9.01 deg | 3 | 0 | 17.50 s | no improvement |
| 6 m | segmented_reset | FAIL | -0.964 m | -15.81 deg | 3 | 3 | 17.34 s | no improvement |
| 6 m | segmented_state_aware | FAIL | -0.713 m | -10.29 deg | 3 | 0 | 16.79 s | no improvement |
| 8 m | direct_long | FAIL | -0.947 m | -13.31 deg | 0 | 1 | 17.20 s | baseline |
| 8 m | segmented_continuous | FAIL | -1.193 m | -13.21 deg | 4 | 0 | 23.15 s | no improvement |
| 8 m | segmented_reset | FAIL | -1.668 m | -20.96 deg | 4 | 4 | 23.11 s | no improvement |
| 8 m | segmented_state_aware | FAIL | -1.102 m | -11.18 deg | 4 | 0 | 22.31 s | no improvement |

All 12 missions were physical successes; every task failure is `EXCESSIVE_DRIFT`
(and heading error for `segmented_reset`). Segmentation adds 2.5-5.2 s of stopping
time and increases drift at every distance.

## 4. Controller-memory semantics (audit)

`WalkForwardSkill`, `StandSkill` and `TurnSkill` call `controller.reset()`, which
calls `policy.reset_memory()`; `StopSkill` does not. Therefore
`policy_memory_continuous_across_skill_calls = false` in the standard lifecycle:
each segmented Walk invocation clears the LSTM state. Phase 1.2b adds an explicit
`reset_memory` parameter (default `True`, so Phase 1/1.1/1.2 behaviour is
unchanged) and runs two segmented treatments to separate the confounds:
`segmented_reset` (standard) vs `segmented_continuous` (`reset_memory=False`).
`segmented_reset` is consistently worse than `segmented_continuous`, so the
LSTM reset contributes materially - it must not be attributed to planning.

## 5. Mechanism interpretation (evidence only)

Segmentation with `Stop` between 2 m segments made drift worse than a single long
walk at every distance (+0.16 m at 4 m, +0.22 m at 6 m, +0.25 m at 8 m), and the
LSTM-reset variant worsened it further (+0.50-0.72 m). The stop/restart cycle
itself perturbs the gait; no evidence supports high-level segmentation improving
task reliability under the frozen envelope.

## 6. Negative findings

- The refined boundary is ~4.53-4.63 m, much closer to 5 m than the pilot's
  assumption; distances 4/6/8 m all fail the nominal envelope.
- `segmented_state_aware` (remaining-distance recomputation) reduces neither
  drift nor heading relative to direct execution; the extra stop time is pure
  overhead.
- 8 m `segmented_reset` heading error doubles (-20.96 deg) - the reset effect is a
  confound, not a planning benefit.
- Viewer segmentation spot-check was not performed in this pass (time budget);
  the terminal evidence above is the authoritative result.

## 7. Artifacts

`experiments/baselines/g1_distance_segmentation_001/`: `protocol.yaml`,
`summary.json`, `distance_boundary.json`, `segmentation_comparison.json`,
`risk_map_v1_2b.json`, `execution_strategy_map.json`, `report.md`. Raw runs in
`artifacts/g1_distance_segmentation_001/<campaign>/` (manifest/metrics/events per
run, `mission_start`/`segment_start`/`skill_start`/`skill_end`/`stop_start`/
`stop_end`/`state_checkpoint`/`memory_reset`/`mission_end` events).

## 8. Tests

```
91 passed, 0 failed
```
(81 existing + 10 new: mission-frame metrics, schedules, final partial segment,
state-aware remainder, memory-reset flag, boundary last-reliable/first-failure,
comparison verdicts, risk v1.2b + execution strategy serialization, Phase 1.2 maps
untouched, raw-to-summary consistency.)

## 9. Git

Branch `phase1.2b/distance-segmentation` (base `55b71b5`); harness + frozen
protocol `28fd970`; results commit follows. Phase 1.2 branch and maps untouched.
Push not possible from this machine (no credentials):
`git push -u origin phase1.2b/distance-segmentation`.

## 10. Next gate

**Route B - Phase 1.3 Closed-loop Locomotion Correction.** Evidence: segmentation
did not improve task outcome at any tested distance and made drift worse; the
dominant failure mode remains open-loop lateral drift (task failures start at
~4.6 m under the frozen envelope); no mechanism-isolation study is needed because
no segmentation benefit was observed.
