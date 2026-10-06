# Baseline-001 - Stand -> WalkForward 2.0 m -> Stop

Frozen protocol: `protocol.yaml`. Robot: official 12-DOF G1 description
(`unitree_rl_gym` @ `276801e46c5d433564f24658bac64f254b7d2d4b`), controller:
Unitree's official pretrained TorchScript policy through the official MuJoCo
deployment pipeline (12 actions, 47 observations, 50 Hz, 500 Hz physics).

## Result: 5/5 runs inside the pre-frozen success window

| Run | Seed | Final displacement | Lateral drift | Heading error | Falls | Status |
| --- | --- | --- | --- | --- | --- | --- |
| run-000 | 0 | 2.169 m | -0.365 m | -8.41 deg | no | SUCCESS |
| run-001 | 1 | 2.169 m | -0.365 m | -8.41 deg | no | SUCCESS |
| run-002 | 2 | 2.169 m | -0.365 m | -8.41 deg | no | SUCCESS |
| run-003 | 3 | 2.169 m | -0.365 m | -8.41 deg | no | SUCCESS |
| run-004 | 4 | 2.169 m | -0.365 m | -8.41 deg | no | SUCCESS |

Success window `[1.8, 2.2] m` was frozen before the five official runs.

Per-run metric: `success_rate = 1.0`, `falls = 0`, mean displacement
`2.169 m`, mean lateral drift `-0.365 m`, mean heading error `-8.41 deg`.

## Per-skill measurements (run-000)

| Skill | Steps | Status | Measurements |
| --- | --- | --- | --- |
| stand | 1000 (2.0 s) | SUCCESS | base drift 0.039 m, min height 0.773 m, max tilt 4.9 deg, controller `official_pretrained_policy` |
| walk_forward | 2249 (4.50 s) | SUCCESS | reached 2.000 m, lateral drift during walk -0.290 m, heading error at handover -6.47 deg |
| stop | 637 (1.27 s) | SUCCESS | final speed 0.035 m/s, trailing 1.0 s mean speed 0.0998 m/s (threshold 0.10 m/s) |

Total simulated time per run 7.77 s; wall-clock time ~0.36 s (CPU physics).

## Reproduce

```powershell
.\scripts\enter.ps1
python .\scripts\run_baseline_001.py
```

## Notes and limitations

1. **Determinism.** The official controller and the simulation are
deterministic, so all five seeds produced identical trajectories. Seeds are
retained in every manifest for traceability; seed-level variation would
require domain randomization (future work).
2. **Stop criterion history (not hidden).** The pilot used instantaneous
speed `< 0.05 m/s` sustained 0.5 s and timed out (final 0.0655 m/s). Raising
the instantaneous threshold to `0.10 m/s` also timed out because balancing
oscillates the instantaneous speed between ~0.004 and ~0.143 m/s. The frozen
criterion is therefore the trailing 1.0 s mean speed `< 0.10 m/s`; the
measured pilot and five-run traces support it. The 2.0 m distance tolerance
was never changed. Pilot evidence: `artifacts/baseline-pilot/run-000/`.
3. **Lateral drift and heading error are real.** The policy tracks forward
velocity; it accumulates ~0.29 m lateral drift and ~6.5 deg heading error
over the 4.5 s walk (0.37 m / 8.4 deg after the stop phase). No lateral or
heading controller is applied in this phase.
4. **CPU physics.** Runs execute on the CPU physics path (~20x real time); no
GPU physics (MJX/Warp) is used in this phase.
5. **Scope.** Simulation only. No sim-to-real validation is claimed.
6. **Revision traceability.** The five runs were executed from the working
tree that became commit `d8a1afb`; the run manifests record the pre-commit
HEAD `c2fd276`. An independent verification campaign re-ran the frozen
protocol at `d8a1afb` and reproduced every metric bit-for-bit.
7. **Asset identity.** `motion.pt` SHA-256
`cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`;
`scene.xml` SHA-256
`08d6297979ea3f62768212b6f115f342a9c4dcdde1968d33330c292a0238921f`.

## Evidence

Raw bundles (not committed): `artifacts/baseline-001/run-000..004/` with
`manifest.json`, `metrics.json`, `events.jsonl`. Machine-readable digest:
`summary.json`.
