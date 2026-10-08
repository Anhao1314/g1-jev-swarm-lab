# Phase 1.2b - Distance Boundary Refinement & Segmentation Study (corrected)

> **Correction notice.** The first version of this report stated that all 12
> segmentation missions failed the nominal envelope. A Stage A audit found an
> evaluator-input bug (mission metrics used `final_*` keys, the shared envelope
> evaluator reads canonical keys, so the missing values defaulted to `+inf`).
> The affected missions were re-run with the fixed evaluator. See
> `audit/audit_report.md` and `CORRECTION.md`. The distance boundary was
> unaffected and reproduced identically.

Protocol: `configs/experiments/g1_distance_segmentation_001.yaml`, SHA-256
`cfb936c6ed947db5dedaa086b782dd34f01266aa96fbf2fbc2c4f3e0170e83da`, frozen in
commit `28fd970` before the final campaign. Phase 1.2 nominal warehouse envelope
reused unchanged; mission frame fixed at mission start.

## 1. Verdict

**PASS** (both research questions answered; RQ2's answer is negative).

## 2. Refined distance boundary (unaffected by the correction)

- last reliable **4.53125 m**, first failure **4.625 m**, bracket 4.53-4.63 m
- dominant failure mode `EXCESSIVE_DRIFT`, physical success in every boundary run
- provenance: Phase 1.2 bracket [2 m pass, 5 m fail] referenced, not copied

## 3. Segmentation comparison (corrected, mission frame)

| Distance | Treatment | Task | Drift | Heading | Stops | LSTM resets | Sim time | Verdict |
|---|---|---|---|---|---|---|---|---|
| 4 m | direct_long | **PASS** | -0.281 m | -6.72 deg | 0 | 1 | 8.71 s | baseline |
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

All 12 missions are physical successes. Key corrected finding: at 4 m the single
long walk succeeds while every segmented variant fails; at 6 m and 8 m every
treatment fails and segmentation still increases drift and stopping time.

## 4. Controller-memory semantics (audit)

Walk/Stand/Turn call `controller.reset()` (→ `policy.reset_memory()`); `StopSkill`
does not. Standard lifecycle therefore has
`policy_memory_continuous_across_skill_calls = false`. Phase 1.2b adds an explicit
`reset_memory` parameter (default `True`, preserving Phase 1/1.1/1.2 behaviour) and
runs both `segmented_reset` and `segmented_continuous`. The reset variant is
consistently worse, so recurrent-state reset is a material confound and must not
be attributed to planning.

## 5. Mechanism interpretation (evidence only)

Adding Stop/restart between 2 m segments increases drift at every distance
(+0.16 m at 4 m, +0.22 m at 6 m, +0.25 m at 8 m versus direct execution), and the
LSTM-reset variant increases it further. At 4 m that turns a task success into a
task failure. No evidence supports high-level segmentation improving reliability
under the frozen envelope.

## 6. Negative findings

- Segmentation degrades the 4 m case from PASS to FAIL and worsens drift at 6/8 m.
- `segmented_state_aware` (remaining-distance recomputation) gives no benefit and
  adds stop overhead.
- 8 m `segmented_reset` heading error reaches -20.96 deg: the reset effect is a
  confound, not a planning benefit.
- Stop-phase drift is included in the segmented measurements (design choice);
  direct runs are walk-only, which is a caveat for drift comparison.
- Viewer segmentation spot-check was not performed; terminal evidence is
  authoritative.
- The original Phase 1.2b report contained an evaluator-input bug; corrected here.

## 7. Artifacts

`protocol.yaml`, `summary.json`, `distance_boundary.json`,
`segmentation_comparison.json`, `risk_map_v1_2b.json`,
`execution_strategy_map.json`, `report.md`, `CORRECTION.md`,
`audit/{audit_report.md, audit_summary.json, case_comparison.json}`. Raw runs in
`artifacts/g1_distance_segmentation_001/<campaign>/`; pre-audit originals in
`artifacts/g1_distance_segmentation_001/final-preaudit/`.

## 8. Tests

```
97 passed, 0 failed
```
(91 previous + 6 Stage A regression tests: 4 m threshold case, original `+inf`
bug shape, nominal-vs-strict semantics, failure-type source, boundary/mission
evaluator equivalence, raw-to-comparison mapping.)

## 9. Git

Audit branch `phase1.2b/audit` from `beb95a3`; fix + audit artifacts committed
here. Stage B is not started (Stage A verdict FAIL). Push unavailable from this
machine (no credentials): `git push -u origin phase1.2b/audit`.

## 10. Next gate

Stage A verdict is **FAIL**, therefore Phase 1.3 is **not started**. If the
corrected conclusion is accepted, the decision record recommends **Route B
(Phase 1.3 closed-loop correction)** because the dominant failure mode remains
open-loop lateral drift and segmentation demonstrably does not mitigate it.
