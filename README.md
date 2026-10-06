# G1 Jev Swarm Lab

**Research testbed for long-horizon Unitree G1 tasks with decision models, multi-swarm orchestration, and reinforcement-learning skills.**

> This repository is an experimental research testbed. No performance claim is considered valid without reproducible experimental evidence.

## Research question

Can a layered embodied-agent runtime improve the reliability and efficiency of long-horizon Unitree G1 task execution by separating:

- **reasoning** — mission understanding, decomposition, replanning, and multi-swarm coordination;
- **decision** — bounded high-level action/skill selection and escalation;
- **control** — learned or deterministic embodied skills executed by the robot.

The project will specifically investigate **Jev as a high-level decision model** inside this stack, rather than assuming it is beneficial.

## Current status

**Phase 1 — G1 simulation baseline.** The measured facts on this machine (Windows 11, Python 3.11.9, `mujoco==3.15.0`, `torch==2.14.1+cu130`, RTX 5060 Ti 16 GB):

- Official Unitree G1 MJCF models load and run headless natively under MuJoCo for 1000 steps each with no NaN/Inf and no MuJoCo warnings: the full-body 29-DOF model (`unitree_mujoco` @ `1eb6642`) and the 12-DOF leg model used by Unitree's own MuJoCo deployment (`unitree_rl_gym` @ `276801e`).
- Walking is produced by Unitree's official pretrained TorchScript policy through a headless port of the official MuJoCo deployment pipeline (12 actions, 47 observations, 50 Hz policy, 500 Hz physics). No teleporting or root-pose editing is used by any skill.
- Baseline-001 (`Stand -> WalkForward 2.0 m -> Stop`): 5/5 runs ended inside the pre-frozen `[1.8, 2.2] m` window with 0 falls; mean final displacement 2.169 m, mean lateral drift -0.365 m, mean heading error -8.41 deg. The controller is deterministic, so the five seeds are identical runs.
- Phase 1 target skill status: `Stand` PASS, `Stop` PASS, `WalkForward` PASS, `Turn` PASS (45 deg pilot, 5/5, error 0.18 deg).
- No locomotion training was performed. No Jev, multi-swarm, LLM, perception or manipulation component is active in this phase.

Reports: [compatibility spike](experiments/baselines/g1_compat_spike/README.md) · [Baseline-001](experiments/baselines/g1_baseline_001/README.md) · [turn pilot](experiments/baselines/g1_turn_pilot/README.md).

## Target architecture

```text
Natural-language mission
        ↓
Mission compiler / task graph
        ↓
Multi-swarm reasoning
        ↓
Jev decision layer
        ↓
Skill router
        ↓
RL / deterministic skill library
        ↓
Unitree G1 in simulation
        ↓
World + robot feedback
        └──────────────→ runtime
```

Safety-critical low-level control is never delegated to a language or decision model.

## Phase 1 modules

| Module | Responsibility |
| --- | --- |
| `src/g1swarm/simulation/` | `G1Simulation` adapter (`reset`, `step`, `get_robot_state`); MuJoCo `mjModel`/`mjData` stay private, viewer is optional |
| `src/g1swarm/state/` | `RobotState` protocol shared by skills, router, evaluation and future decision layers |
| `src/g1swarm/skills/` | `Skill`, `SkillContext`, `SkillResult`, `SkillStatus`, `SkillRouter`; concrete stand / stop / walk_forward / turn skills |
| `src/g1swarm/control/` | Headless port of the official Unitree G1 MuJoCo locomotion controller (PD + observation pipeline) |
| `src/g1swarm/evidence/` | Run manifests with provenance and per-run evidence bundles |
| `src/g1swarm/evaluation/` | Baseline summary aggregation |
| `configs/` | Robot and experiment configs with pinned model/controller revisions |
| `scripts/` | Model fetch, compatibility spike, Baseline-001, skill pilot |

## Reproduction

```powershell
git clone https://github.com/Anhao1314/g1-jev-swarm-lab.git
cd g1-jev-swarm-lab
py -3.11 -m venv .venv
.\scripts\enter.ps1          # activates .venv; keeps pip cache and temp files inside the repo
pip install -e ".[dev]"
pip install torch --index-url https://download.pytorch.org/whl/cu130
.\scripts\fetch_g1_models.ps1   # pinned official G1 assets into third_party/ (never committed)
python -m pytest -q
python .\scripts\run_compat_spike.py
python .\scripts\run_baseline_001.py
python .\scripts\run_skill_pilot.py
```

If Windows PowerShell 5.1 blocks the activation script, allow local scripts for the current user once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Evidence rule

A result is considered reportable only when it can be traced to:

```text
experiment
→ config
→ code revision
→ seed
→ trajectory / decision log
→ metrics
→ artifact
→ report
```

Failed and negative runs are retained when they are relevant to the conclusion. Per-run evidence (`manifest.json`, `metrics.json`, `events.jsonl`) is written under `artifacts/` and is not committed; committed digests live under `experiments/`.

## Known limitations

- The official controller is deterministic, so the five Baseline-001 seeds are identical; seed-level variation needs domain randomization, which this phase does not add.
- Forward-only control: ~0.29 m lateral drift and ~6.5 deg heading error accumulate during a 4.5 s walk. There is no lateral or heading correction.
- The stop criterion is the trailing 1.0 s mean speed (< 0.10 m/s). Instantaneous base speed oscillates between ~0.004 and ~0.143 m/s while the robot balances, so instantaneous thresholds were rejected (documented in the Baseline-001 report).
- The full-body 29-DOF model has no controller in this phase; it is compatibility evidence only and falls under zero torque.
- Physics runs on the CPU path (~20x real time). No GPU physics (MJX/Warp) is used.
- Simulation only. No sim-to-real claim is made.

## Repository map

```text
configs/        experiment, robot, task, and skill configuration
docs/           research charter, architecture, hypotheses, protocol
src/g1swarm/    runtime implementation
experiments/    experiment definitions and reports (committed digests)
scripts/        reproducible entry points
tests/          unit and integration tests
checkpoints/    local model outputs (not committed)
artifacts/      local experiment outputs (not committed)
third_party/    fetched official G1 assets (not committed)
```

## Environment policy

The previously validated MuJoCo/PyTorch environment at `D:\work\mujoco-lab` is treated as an external frozen baseline and is not modified by this repository. Phase 1 uses its own isolated virtual environment with `mujoco==3.15.0` and CUDA 13.0 PyTorch wheels only: no CUDA downgrade, no NVIDIA driver change, and no MJX, JAX, Isaac Lab or ROS dependency.

## Research documents

- [Research goal](docs/research-goal.md)
- [Architecture](docs/architecture.md)
- [Hypotheses](docs/hypotheses.md)
- [Experiment protocol](docs/experiment-protocol.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
