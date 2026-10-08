# Turn Pilot - Stand -> Turn 45 deg -> Stop

Same robot and controller as Baseline-001. Purpose: give the fourth Phase 1
target skill its own measured status instead of an assumed one.

## Result: 5/5 runs successful

| Run | Seed | Turned | Heading error | Falls | Status |
| --- | --- | --- | --- | --- | --- |
| g1_turn_pilot-run-000 | 0 | 45.18 deg | 0.18 deg | no | SUCCESS |
| g1_turn_pilot-run-001 | 1 | 45.18 deg | 0.18 deg | no | SUCCESS |
| g1_turn_pilot-run-002 | 2 | 45.18 deg | 0.18 deg | no | SUCCESS |
| g1_turn_pilot-run-003 | 3 | 45.18 deg | 0.18 deg | no | SUCCESS |
| g1_turn_pilot-run-004 | 4 | 45.18 deg | 0.18 deg | no | SUCCESS |

Tolerance: +/-15 deg (frozen in `configs/experiments/g1_turn_pilot.yaml`).
The controller is deterministic, so the runs are identical; seeds are retained
for traceability.

The trailing stop step uses the same calibrated criterion as Baseline-001
(trailing 1.0 s mean speed < 0.10 m/s). An earlier pilot run used the stricter
default (0.05 m/s) and reported `stop = TIMEOUT` at a trailing mean of
0.0621 m/s; the turn result itself was unaffected. The criterion was aligned
with Baseline-001 before the five runs recorded here.

## Reproduce

```powershell
.\scripts\enter.ps1
python .\scripts\run_skill_pilot.py
```

## Evidence

Raw bundles (not committed): `artifacts/skill-pilot/g1_turn_pilot-run-000..004/`.
Machine-readable digest: `summary.json`.
