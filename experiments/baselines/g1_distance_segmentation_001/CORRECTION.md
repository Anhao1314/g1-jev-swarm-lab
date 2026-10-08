# CORRECTION — Phase 1.2b segmentation evaluation

Date: 2026-10-06. Branch: `phase1.2b/audit` (from `beb95a3`).
Audit: `experiments/baselines/g1_distance_segmentation_001/audit/audit_report.md`.

## Original conclusion (as published in `report.md`)

> All 12 segmented missions were physical successes; every task failure is
> `EXCESSIVE_DRIFT`. Segmentation adds 2.5-5.2 s of stopping time and increases
> drift at every distance, and segmentation did not improve anything.

## Problem found

The segmentation mission metrics dict used `final_lateral_drift_m` /
`final_heading_error_deg` / `final_forward_progress_m`, while the shared
walk-envelope evaluator reads `lateral_drift_m` / `heading_error_deg` /
`forward_displacement_m`. The missing keys defaulted to `+infinity`, so **every
segmentation mission was marked FAIL regardless of its physical trajectory**.
The 4 m `direct_long` run (drift -0.2814 m, heading -6.72 deg, both inside the
nominal envelope) was therefore incorrectly reported as a task failure.
Boundary runs already used the canonical keys and were unaffected.

## Corrected conclusion

With the evaluator input fixed and the 12 missions re-run against the identical
frozen protocol:

- **4 m**: `direct_long` is a nominal **task success** (drift -0.281 m); all three segmented treatments are **task failures** (drift -0.393 to -0.445 m). Segmentation *creates* the failure at this distance.
- **6 m**: all treatments fail; segmented drift (-0.71 to -0.96 m) is worse than direct (-0.549 m).
- **8 m**: all treatments fail; segmented drift (-1.10 to -1.67 m) is worse than direct (-0.947 m); `segmented_reset` heading error reaches -20.96 deg.
- The refined distance boundary is unchanged: last reliable 4.53125 m, first failure 4.625 m.

The qualitative finding that the segmentation strategy does **not** improve
long-distance task reliability - and actively worsens drift - is unchanged, and
now rests on correct evaluations. The previous statement that all 12 missions
failed was wrong: the single long walk succeeds at 4 m, and segmentation turns
that success into a failure.

## Affected files

- `experiments/baselines/g1_distance_segmentation_001/summary.json` (regenerated)
- `experiments/baselines/g1_distance_segmentation_001/segmentation_comparison.json` (regenerated)
- `experiments/baselines/g1_distance_segmentation_001/risk_map_v1_2b.json` (regenerated)
- `experiments/baselines/g1_distance_segmentation_001/execution_strategy_map.json` (regenerated)
- `experiments/baselines/g1_distance_segmentation_001/report.md` (corrected)
- `artifacts/g1_distance_segmentation_001/final/**` (12 mission bundles re-run; originals preserved in `final-preaudit/`)
- `src/g1swarm/segmentation/runner.py` (canonical keys; comparison builder alias-safe)

## Unaffected content

- Refined distance boundary 4.53125-4.625 m and its evidence.
- Phase 1 / 1.1 / 1.2 results, maps, competence data and taxonomy.
- The controller, policy weights, gains, action scale and the frozen task envelope.
- The LSTM-memory audit and the `segmented_reset` vs `segmented_continuous` ordering (reset remains a confound and is still worse).

## Stage B

Stage A verdict is **FAIL**, therefore Phase 1.3 (closed-loop correction) was
**not started**, per the Stage A gate.
