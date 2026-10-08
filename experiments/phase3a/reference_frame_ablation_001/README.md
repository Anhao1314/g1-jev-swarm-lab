# Phase3A residual-off walking reference ablation

This is a new experiment on `phase3a/transition-learning`. The original
`transition_learning_001` sources, artifacts, cases, reward, observation, PPO
configuration and outcomes are retained byte-for-byte. No PPO is trained here.

One categorical control factor changes:

* `actual_node_start`: correction uses actual node-start position and heading.
* `ideal_commanded_axis`: correction uses the already-defined planned path
  origin and commanded heading; origin advances by commanded walk distances,
  heading by commanded turn angles. Stand/Stop/measured motion never rebase it.

Full origin+heading selection is one reference-frame treatment, not an isolated
heading-only experiment. The old local frame still controls skill termination,
measurements, reward and all existing task envelopes. Control-frame diagnostics
are separate and never rescore a case. Original gains, clamping/deadband, base
policy, PD, reset/settle and skill code remain unchanged. Correction is walking
only; residual actions are zero throughout every skill.

The same26 already-seen cases are replayed once per treatment:16transitions,
8primitives,2mixed sequences. A separately recorded second pass verifies exact
repeatability; it is not pooled with primary evidence or treated as independent
samples. No fresh blind/generalization claim is made. All actual-mode records
must reproduce the previous deterministic treatment exactly.

The prospective hypothesis gate requires lower final absolute ideal lateral and
heading error on both sequences, no frozen physical/task PASS→FAIL losses, exact
primitive preservation and deterministic repeatability. This decision rule does
not replace task thresholds or authorize training in this session. Improved
global precision with local corridor regression is a retained negative result.

Reproduce with the previous pilot's pinned Python/MuJoCo/Torch environment and
official assets, from repository root, using a new output directory:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/run_phase3a_reference.py --output-dir artifacts/reference_frame_ablation_001
```

Campaign directories are exclusive. `freeze_phase3a_reference.py` creates the
history manifest once; reproductions verify the retained manifest rather than
regenerate it. Frozen history covers189 prior pilot files in addition to219
baseline source/asset pins. New source/protocol/case hashes accompany all runs.

Per-command traces include actual pose, measurement and control frames, signed
heading/lateral yaw contributions, raw/clipped yaw, residual/action and reset
count. Per-physics correction counters report saturation/oscillation. Per-node
evidence retains old local gates, ideal-path diagnostics, turn translation,
completion duration and stability. Any campaign exception retains a failure
receipt and completed rows. No outcome-dependent rerun is performed.
