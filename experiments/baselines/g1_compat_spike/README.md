# G1 Compatibility Spike (Phase 1)

**Question.** Can credible official Unitree G1 models load and run under MuJoCo
on native Windows 11 (Python 3.11, `mujoco==3.15.0`)?

**Answer: YES for both official models** - `load -> reset -> step -> read
qpos/qvel` completed headless for 1000 steps per model with no NaN/Inf and no
MuJoCo warnings.

## Models

| Run | Model | Source (pinned) | qpos | qvel | Actuators | Steps | Sim time | Wall | RTF | Fall | End state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `g1_full_29dof-run-000` | full-body G1, 29 torque motors | `unitreerobotics/unitree_mujoco` @ `1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d`, `scene_29dof.xml` | 36 | 35 | 29 | 1000 | 2.000 s | 0.072 s | 27.6x | yes, step 497 | not standing |
| `g1_locomotion_12dof-run-000` | G1 legs, 12 torque motors | `unitreerobotics/unitree_rl_gym` @ `276801e46c5d433564f24658bac64f254b7d2d4b`, `resources/robots/g1_description/scene.xml` | 19 | 18 | 12 | 1000 | 2.000 s | 0.101 s | 19.8x | no | standing |

Real-time factor (RTF) is simulated time divided by wall-clock time; both runs
were faster than real time on the CPU physics path.

## Findings

1. The full-body 29-DOF MJCF loads and steps natively, but this phase ships no
official controller for that model path. With zero torque it falls at step 497
(~1.0 s simulated time, max tilt 180 degrees). Model compatibility is therefore
reported separately from controller availability.
2. The 12-DOF leg model used by Unitree's own MuJoCo deployment example stays
standing for the full 1000-step window when driven by the official pretrained
policy with a zero velocity command (max tilt 4.9 degrees, min base height
0.773 m).
3. Neither run produced MuJoCo warnings or non-finite state.
4. No viewer was used; every check is headless.

## Provenance

- Full-body model: `https://github.com/unitreerobotics/unitree_mujoco` @ `1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d`
- Locomotion model + MuJoCo deployment + pretrained policy: `https://github.com/unitreerobotics/unitree_rl_gym` @ `276801e46c5d433564f24658bac64f254b7d2d4b`
- Local assets are fetched by `scripts/fetch_g1_models.ps1` into `third_party/`
(never committed; large meshes and policy binaries).
- SHA-256 of `resources/robots/g1_description/scene.xml` (12-DOF model):
  `08d6297979ea3f62768212b6f115f342a9c4dcdde1968d33330c292a0238921f`
- SHA-256 of `unitree_robots/g1/scene_29dof.xml` (29-DOF model):
  `958ed3f4a404d3d49ffce318bc8ac18cc3941fa17d214d655533620fb581856a`

## Evidence

Raw evidence (not committed): `artifacts/compat-spike/<run_id>/` with
`manifest.json`, `metrics.json` and `events.jsonl`. The manifest records OS,
Python, MuJoCo and Torch versions, GPU, git commit, seed and the pinned model
revisions. Machine-readable digest: `summary.json`.

## Limitations

- The 29-DOF run proves model loading and stepping only. It is not a control
result, and the fall is expected without a controller.
- The 12-DOF run uses a zero velocity command (stand), not walking; walking is
covered by Baseline-001.
