# Phase 1.3 - Closed-loop Locomotion Correction

Protocol: `configs/experiments/g1_closed_loop_correction_001.yaml`, SHA-256
`ca99d60b1f8576682c1fa02a3c7e7b92018b6376a9a418dbd59324cb090f3661`, frozen in
commit `91fb6f8` before the final campaign. Baseline provenance: audit-corrected
Phase 1.2b at `a519b62` (open-loop last reliable 4.53125 m, first failure
4.625 m). No policy weight, gain, action scale, model or task envelope changed.

## 1. Verdict

**PASS.** A simple, explainable outer-loop heading (+lateral) feedback layer at
the policy-command level reduces lateral drift by 87-100% and heading error by
93-98% under the frozen nominal envelope, converts the 6/8/10 m task failures
into passes, and expands the tested reliable distance from 4 m to >=20 m
(the 20 m extension budget was exhausted; corrected boundary not reached).

## 2. Frozen protocol

- path/hash/freeze commit: see above; every final-run manifest records both the
  protocol hash and `git_commit = 91fb6f8`.
- Task envelope: Phase 1.2 nominal warehouse corridor proxy, unchanged.
- Mission frame: frozen at mission start; all errors projected onto it.
- Gains frozen from the pilot (below); improvement gate frozen before final.

## 3. Treatments

| Treatment | Layer | Formula |
| --- | --- | --- |
| open_loop | none - raw controller, bit-identical to the historical path | `yaw = 0` |
| heading_only | policy command | `yaw = -k_heading * e_heading` |
| heading_lateral | policy command | `yaw = -k_heading * e_heading - k_lateral * e_lateral` |

Only the `(vx, vy, yaw-rate)` command is modified; `vx/vy` are untouched and no
joint-level value is ever written. Yaw command clamped to +/-0.6 rad/s (policy
verified range +/-1.0 rad/s), deadband 0.01 rad/s.

## 4. Pilot (gains frozen before final)

- Open-loop control: 4 m -0.2814 m / -6.720 deg PASS and 8 m -0.9471 m /
  -13.310 deg FAIL - reproduced the audit-corrected baseline exactly.
- Heading sweep `{0.5, 1.0, 1.5}` x {4 m, 8 m}: all three turned 8 m FAIL into
  PASS with zero saturation/oscillation; `k_heading = 1.5` gave the smallest
  residual (8 m: -0.047 m / -0.81 deg).
- Lateral sweep `{0.5, 1.0, 2.0}` with `k_heading = 1.5`: `k_lateral = 1.0`
  gave near-zero drift (-0.002 m at 8 m) with the smallest balanced RMS.
- Viewer sanity checks (8 m): open-loop visibly drifted (FAIL); heading-only
  walked straight (PASS, -0.047/-0.81); heading+lateral tracked the centreline
  (-0.002/-0.43) with no serpentine oscillation or abrupt speed changes.

## 5. Nominal comparison (4/6/8/10 m)

| Distance | Treatment | Task | Drift | Heading | Drift Δ | Heading Δ | Sim time | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 m | open_loop | PASS | -0.2814 m | -6.720 deg | - | - | 8.71 s | baseline |
| 4 m | heading_only | PASS | -0.0360 m | -0.276 deg | -87% | -96% | 8.70 s | improved metrics |
| 4 m | heading_lateral | PASS | -0.0193 m | +0.257 deg | -93% | -96% | 8.70 s | improved metrics |
| 6 m | open_loop | **FAIL** | -0.5486 m | -9.479 deg | - | - | 12.94 s | baseline |
| 6 m | heading_only | PASS | -0.0312 m | -0.300 deg | -94% | -97% | 12.89 s | **FAIL -> PASS** |
| 6 m | heading_lateral | PASS | +0.0006 m | +0.210 deg | -100% | -98% | 12.90 s | **FAIL -> PASS** |
| 8 m | open_loop | **FAIL** | -0.9471 m | -13.310 deg | - | - | 17.20 s | baseline |
| 8 m | heading_only | PASS | -0.0474 m | -0.812 deg | -95% | -94% | 17.09 s | **FAIL -> PASS** |
| 8 m | heading_lateral | PASS | -0.0024 m | -0.434 deg | -100% | -97% | 17.10 s | **FAIL -> PASS** |
| 10 m | open_loop | **FAIL** | -1.4404 m | -15.092 deg | - | - | 21.51 s | baseline |
| 10 m | heading_only | PASS | -0.0769 m | -1.001 deg | -95% | -93% | 21.27 s | **FAIL -> PASS** |
| 10 m | heading_lateral | PASS | -0.0187 m | -0.576 deg | -99% | -96% | 21.28 s | **FAIL -> PASS** |

## 6. Reliable distance

| Treatment | Last reliable (tested) | First failure | Boundary |
| --- | --- | --- | --- |
| open_loop | 4.0 m on the final grid (4.53125 m in the finer Phase 1.2b bracket) | 6.0 m on the final grid (4.625 m in Phase 1.2b) | ~4.6 m |
| heading_only | **>=20 m** | none within budget | `boundary_not_reached_within_budget` |
| heading_lateral | **>=20 m** | none within budget | `boundary_not_reached_within_budget` |

Tested extension grid: 12 / 15 / 20 m (frozen budget), all passing for both
corrected treatments. Reliable-distance expansion on the tested grid: **+16 m**.

## 7. Error reduction and correction behaviour

Drift reduction 87-100%, heading reduction 93-98% (largest reductions at 6-10 m,
where the open-loop error is largest). Absolute differences are in the table
above; percentages are suppressed when the baseline is near zero.

Correction behaviour (all corrected runs): RMS 0.019-0.023 rad/s (about 3-4% of
the 0.6 rad/s clamp), max |yaw| well below the clamp, **saturation count 0
(0.0%)**, **control oscillation count 0**, completion time within 0.1-1.2% of
open loop (no time regression). Heading-only RMS is slightly lower than
heading+lateral; heading+lateral trades a little more yaw activity for near-zero
lateral drift.

## 8. Physical vs Task success

30/30 runs were physical successes; 24/30 were task successes. All six task
failures are open-loop `EXCESSIVE_DRIFT` (6/8/10 m nominal). No falls, no
non-finite state, no timeouts, no control oscillation. Corrected runs never
traded physical stability for task success - they improved both axes.

## 9. Disturbance spot-check (frozen Phase 1.2 representative conditions)

| Condition | Treatment | Task | Drift | Heading |
| --- | --- | --- | --- | --- |
| friction 0.175 | open_loop | **FAIL** | -4.426 m | -71.38 deg |
| friction 0.175 | heading_only | PASS | -0.052 m | -1.37 deg |
| friction 0.175 | heading_lateral | PASS | -0.009 m | -0.42 deg |
| push 60 N | open_loop | PASS | -0.005 m | -7.65 deg |
| push 60 N | heading_only | PASS | +0.277 m | -0.76 deg |
| push 60 N | heading_lateral | PASS | -0.003 m | -0.47 deg |

The correction is not only effective in the nominal world: under near-boundary
low friction (where open loop diverges to -4.4 m / -71 deg) both corrected
modes remain inside the envelope. The 60 N push spot-check passes for all
treatments; the corrected runs recover heading faster, while heading-only shows
a small lateral excursion (+0.277 m, still inside the nominal envelope).

## 10. Canonical metrics schema (audit hardening)

`src/g1swarm/metrics/schema.py` defines the canonical required fields
(`forward_displacement_m`, `distance_error_m`, `lateral_drift_m`,
`heading_error_deg`, `simulation_time_s`, `physical_success`, `task_success`,
`failure_type`, `failure_reason`). Historical aliases (`final_*`, `absolute_*`,
`completion_*`, `segment_*`) are canonicalized before evaluation, canonical keys
win, and a missing or non-finite required metric raises `MissingMetricError` -
the Phase 1.2b silent `+inf` fallback is impossible by construction. Every
Phase 1.3 run validates through `RunMetrics.validate()` before evidence is
written.

## 11. Viewer

Three manual 8 m checks were actually executed (see pilot section): open-loop
drift visible, both corrected modes straight with no serpentine oscillation and
no abrupt speed changes. Viewer output matched the headless evidence exactly.

## 12. Risk and capability maps

- `risk_map_v1_3.json` (schema 1.3.0): per distance and execution mode, with the
  frozen deterministic risk rules and evidence references.
- `capability_map_v1_3.json` (schema 1.3.0): attributes the improvement to
  `closed_loop_execution_strategy` (explicitly **not** a new locomotion policy;
  `motion.pt` SHA unchanged) and records the reliable-distance expansion.
- Historical maps (`risk_map.json`, `risk_map_v1_2b.json`, capability maps) were
  not modified.

## 13. Tests

```
115 passed, 0 failed
```
(97 previous + 18 new: canonical schema required-fields/alias/missing-raises,
heading and lateral error signs, zero-error correction, correction direction,
clamp and saturation logging, open-loop output unchanged, correction only at the
command layer, config validation/serialization, mission-frame behaviour,
aggregation consistency and historical-map integrity.)

## 14. Security

Codex Security `security-diff-scan` is **not available** in this session
(plugin not configured). Fallback: static diff review of the Phase 1.3 change
set (no secrets, no shell string building, no recursive deletion, no
download-and-execute, no policy/model file writes) -> `static review clean`,
reported as such, not as an official Security PASS.

## 15. Negative findings

- The corrected boundary was **not reached**: 20 m is a lower bound, not the
  limit. A larger bound would need a new budgeted study (Route B candidate).
- Heading-only develops a small lateral excursion under the 60 N push
  (+0.277 m); heading+lateral is tighter (-0.003 m).
- The 60 N push spot-check does not discriminate much because the open loop also
  passed it; the low-friction point is the discriminating disturbance.
- Correction RMS is small (~0.02 rad/s) because the policy needs very little
  yaw authority; a policy with a weaker heading response could saturate.
- All findings are conditional on the frozen warehouse envelope and the specific
  disturbance points; no claim is made outside them.
- Phase 1.2b's segmentation negative finding stands: low-risk segments do not
  compose; feedback correction, not segmentation, is what mitigates accumulated
  sequence error.

## 16. Git

Branch `phase1.3/closed-loop-correction` from `a519b62`.
Commits: `eea2378` (schema + correction module + tests + pilot harness),
`91fb6f8` (frozen protocol with pilot-selected gains), final results commit
follows. Push unavailable from this machine (no credentials):
`git push -u origin phase1.3/closed-loop-correction`.

## 17. Next gate

**Route A - Phase 2 Conversational Mission Baseline.** Evidence: under the
frozen envelope the correction converts every tested open-loop task failure
(6/8/10 m) into a pass with 93-100% error reduction, zero saturation, zero
oscillation, no time or physical regression, and it holds at the near-boundary
low-friction operating point; the reliable distance is at least 20 m, which is
adequate for the mission distances in the Phase 2 scope. If a precise corrected
boundary is later required, a small Phase 1.3b boundary extension (25/30 m) is
the cheaper follow-up, but it is not a prerequisite for Phase 2.
