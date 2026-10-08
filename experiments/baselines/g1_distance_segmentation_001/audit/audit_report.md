# Stage A — Phase 1.2b Experimental Integrity Audit

Scope: three raw-evidence cases (`direct_long 4.0 m`, boundary `4.53125 m`,
boundary `4.625 m`), the shared evaluator, the protocol and the aggregation
chain. The audit is read-only with respect to raw evidence; originals are
preserved under `artifacts/g1_distance_segmentation_001/final-preaudit/`.

## Method

`scripts/audit_phase12b.py` loads each case's `metrics.json`, extracts the
physical measurements, recomputes the nominal/strict envelope evaluations with
the frozen envelope constants and compares the result with the recorded verdict.
Machine-readable evidence: `audit_summary.json`, `case_comparison.json`.

## Case comparison (actual vs threshold)

| Case | Metric | Actual | Nominal limit | Strict limit | Nominal pass? | Recorded | Recomputed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| direct_long 4.0 m | lateral drift | -0.281424 m | 0.350 m | 0.200 m | yes | FAIL (`EXCESSIVE_DRIFT`) | **PASS** |
| direct_long 4.0 m | heading error | -6.7197 deg | 15.0 deg | 8.0 deg | yes | violation | **no violation** |
| direct_long 4.0 m | distance error | 0.0000648 m | 0.400 m | 0.200 m | yes | - | - |
| direct_long 4.0 m | time | 8.706 s | 24.0 s | 20.0 s | yes | - | - |
| boundary 4.53125 m | lateral drift | -0.329134 m | 0.350 m | 0.200 m | yes | PASS | PASS (agrees) |
| boundary 4.53125 m | heading error | -7.5269 deg | 15.0 deg | 8.0 deg | yes | - | - |
| boundary 4.625 m | lateral drift | -0.355361 m | 0.350 m | 0.200 m | **no** | FAIL (`EXCESSIVE_DRIFT`) | FAIL (agrees) |
| boundary 4.625 m | heading error | -8.3627 deg | 15.0 deg | 8.0 deg | yes | - | - |

## Root cause

The segmentation mission metrics dict stored `final_lateral_drift_m`,
`final_heading_error_deg` and `final_forward_progress_m`, while the shared
`WalkEnvelope.evaluate` reads `lateral_drift_m`, `heading_error_deg` and
`forward_displacement_m`. Missing keys fall back to `+inf`, so every
segmentation mission recorded `Infinity` drift/heading and was marked
`EXCESSIVE_DRIFT` + `HEADING_ERROR` regardless of the physical measurement.
The raw evidence confirms this: the recorded nominal envelope in
`direct_long-4m-final-seed000/metrics.json` shows
`"lateral_drift_m": "Infinity"` while `final_lateral_drift_m = -0.281424`.

## Evaluator checklist (A5)

1. `task_success` uses the **nominal** envelope; `strict` is reported separately (confirmed in `envelope.evaluate_walk_task`).
2. Risk rules are deterministic and documented; the 1.2b strategy risk uses its own frozen mapping (task/physical + improvement verdict) and the boundary risk uses the success-rate zones.
3. `failure_type` is derived from the **nominal** violation list (ordered DISTANCE_ERROR → EXCESSIVE_DRIFT → HEADING_ERROR → TIMEOUT) — correct in principle, but the ∞ fallback corrupted the input for missions.
4. Boundary and segmentation call the **same evaluator**, but the missions fed it a **different key shape** → inputs were not equivalent. This is the defect.
5. No divergent default parameters were found (same frozen envelope constants for both paths).
6. Mission frame: boundary runs use the walk skill's own start frame (mission start = walk start); segmentation missions use the fixed mission frame. For `direct_long` these coincide; segmented treatments correctly accumulate heading relative to mission start.
7. No absolute/relative threshold mixing: limits are `max(floor, relative x target)`.
8. Stop-after drift vs walk-end drift: boundary runs are walk-only; segmented missions measure the pose after the final Stop. This is a design difference (not the bug) and is reported as a caveat for drift comparisons.
9. No float-rounding borderline: the failing measurement (0.3554 m vs 0.35 m) and the passing one (0.2814 m) are clearly separated.
10. Summary/report mapping: the comparison table read the correct `final_*` values, so displayed numbers were right while the evaluator verdict was wrong — a classic input-mapping bug.

## Protocol consistency (A6)

All three cases share protocol hash
`cfb936c6ed947db5dedaa086b782dd34f01266aa96fbf2fbc2c4f3e0170e83da`, the same
controller/policy SHA, the same frozen envelope and the same robot config.
The boundary runs carry canonical keys; the segmentation missions did not.
No protocol was silently changed.

## Verdict

**AUDIT = FAIL** (per the Stage A rules: raw evidence did not support the
published Phase 1.2b conclusion that all 12 segmentation missions failed).

## Remediation performed

1. `segmentation/runner.py` now writes canonical keys (`forward_displacement_m`, `lateral_drift_m`, `heading_error_deg`) alongside the `final_*` aliases, so both paths feed the evaluator identically.
2. Regression tests added (`tests/test_audit_regressions.py`, 6 tests) covering the 4 m threshold case, the original ∞ bug shape, nominal-vs-strict semantics, failure-type source, boundary/mission evaluator equivalence and raw→comparison mapping.
3. The 12 affected segmentation missions were re-run with the fixed evaluator; the boundary evidence was re-run too and reproduced identically (4.53125 m / 4.625 m).
4. Corrected results and `CORRECTION.md` written; original raw evidence preserved in `artifacts/g1_distance_segmentation_001/final-preaudit/`.

## Impact

- **Unaffected**: the refined distance boundary, all Phase 1 / 1.1 / 1.2 results.
- **Corrected**: the Phase 1.2b segmentation conclusion. At 4 m the single long walk is a nominal **task success** while all segmented variants are task failures; at 6/8 m every treatment fails and segmentation still worsens drift. The qualitative conclusion (segmentation does not improve, and worsens drift) stands, but the previous "all 12 missions failed" statement was wrong.

Per the Stage A gate, **Stage B (Phase 1.3) is not started**.
