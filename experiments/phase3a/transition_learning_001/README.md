# Phase 3A — transition-learning pilot

This independent embodied-learning experiment retains Phase 1.3 locomotion and
does not open the Phase 2.3 language Runtime gate. It uses real MuJoCo stepping
and SB3 PPO, not a simulated reward table or language/compiler execution.

Three treatments are frozen before acquisition: original open-loop controller,
Phase 1.3 walk-only heading+lateral correction, and the same correction plus a
learned transition residual. The residual changes only the high-level velocity
and yaw command: bounds `[0.10 m/s, 0.06 m/s, 0.12 rad/s]`, decisions at10Hz,
first2s of walk→turn, turn→walk, walk→stop or stand→walk. Original skill bodies,
reset/settle behavior, official recurrent `motion.pt`, PD configuration and task
envelopes remain unchanged. Primitive and out-of-window residual is exactly0.

Original skills execute in a continuous physical state. A worker pauses at
command decisions to exchange Gym actions; synchronous evaluation uses the same
runner. The 61-dimensional observation includes task/transition identity, local
errors, proprioception, gait phase and intended-path diagnostics. It does not
expose or retrain the base policy's recurrent state. Reward is a new surrogate;
task success still uses the frozen original gates and walk envelopes.

Train12 and held-out16 cases split actual parameter combinations; different
nominal simulation seeds alone would not be different initial physics. Eight
primitive checks and mixed12m/16m sequences are separate evaluation sets. Local
walk frames retain the historical envelope meaning. Ideal commanded path error
is also reported, so post-turn bias is not hidden by a new local frame.

The fixed2s observation window is not a physical transition duration. Next-skill
completion duration, tilt/height/angular metrics and a separately declared
sustained command-tracking recovery diagnostic are reported. Null recovery
means not observed inside that window, not zero recovery time or a task failure.

## Reproduce on the pinned local stack

Fetch the official assets with the existing repository asset script if absent.
Install the project and official CUDA13.0 PyTorch wheel as described in the root
project, then the additions in `requirements.txt`. `constraints-local.txt` pins
the currently verified Torch/NumPy/MuJoCo versions; do not replace Torch with a
different wheel while reproducing this experiment. PPO itself uses CPU1thread.
Both the baseline/case manifests and their protocol pins are checked before and
after every campaign. Protocol and source/checkpoint hashes accompany outputs.

Run from the repository root with the local virtual environment:

```powershell
.venv\Scripts\python.exe -m pip install -r experiments/phase3a/transition_learning_001/requirements.txt -c experiments/phase3a/transition_learning_001/constraints-local.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/run_phase3a.py --output-root artifacts/transition_learning_001 baseline
.venv\Scripts\python.exe scripts/run_phase3a.py --output-root artifacts/transition_learning_001 smoke
.venv\Scripts\python.exe scripts/run_phase3a.py --output-root artifacts/transition_learning_001 train --seed 11
.venv\Scripts\python.exe scripts/run_phase3a.py --output-root artifacts/transition_learning_001 train --seed 29
.venv\Scripts\python.exe scripts/run_phase3a.py --output-root artifacts/transition_learning_001 evaluate --checkpoint artifacts/transition_learning_001/train-seed11/final.zip artifacts/transition_learning_001/train-seed29/final.zip
```

Use a new output-root for replication: campaigns refuse to overwrite existing
directories. Do not rerun `freeze_phase3a.py` over the retained manifests; it is
the one-time manifest creation helper, not a reproduction prerequisite.

The independent512-step smoke verifies optimizer updates, checkpoint tensor
identity and deterministic physical replay before expansion. Two fixed8192-step
pilot seeds retain initial/intermediate/final checkpoints; held-out evaluation
uses the declared final checkpoint only. Training observations/actions/rewards,
terminal episodes and budget-interrupted tails are retained. Failure receipts
are preserved rather than silently rerun. Training reward improvement is not
task improvement, and this small pilot is not a broad capability claim.

## Design references

[Residual RL (Johannink et al., 2018)](https://arxiv.org/abs/1812.03201) motivates
adding a learned signal to an existing controller; its robot/task results do
not establish this G1 pilot's effectiveness. The stack follows the
[SB3 PPO API](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
and [Gymnasium environment API](https://gymnasium.farama.org/introduction/create_custom_env/).
Installed package versions are pinned separately from the moving documentation.
