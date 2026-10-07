# G1 Jev Swarm Lab


**Phase 2.2b - compiler hardening (PASS).** Four compiler architectures
were evaluated against frozen safety, semantic and regression gates. Selected:
`guarded_direct_llm_v1` (deterministic structural guard + frozen direct LLM
compiler) - zero unsafe acceptance and zero silent repair on the 179-sample
fresh-blind set (versus 37/37 for the unguarded baseline), exact Mission IR
0.9857 and open-language coverage 0.9833 (frozen gates 0.98), controlled
regression 1.0 exact IR with 0 unsafe acceptance, and both Phase 2.2 fail-open
holes now rejected before any provider call. The canonicalization bridge and
simplex architectures were safe but missed the frozen fresh semantic gates.
Artifacts: `experiments/phase2/simplex_compiler_001/`. This is a constrained
benchmark, not a claim of unrestricted natural-language understanding.


**Phase 2.2 - LLM mission compiler benchmark (PARTIAL).** Phase 2.2 evaluates
a constrained LLM mission compiler against the frozen deterministic grammar
baseline. On the 153-sample blind set, the LLM reached 1.0 exact Mission IR
match on clear valid inputs and 1.0 open-language coverage versus 0.5106 for
Lark, with zero blind unsafe acceptance, hallucinated skills or invalid inputs
reaching the runtime. The required 189-sample controlled regression found two
malformed connector inputs accepted as missions, so the overall verdict is
PARTIAL and the next gate is compiler hardening. Artifacts:
`experiments/phase2/llm_compiler_001/`. This is a constrained benchmark, not
a claim of unrestricted natural-language understanding.




**Phase 2.1 - controlled-language compiler (complete).** Controlled Chinese
commands can be deterministically compiled into Mission IR under the frozen
Phase 2.1 grammar. The 189-sample frozen corpus reached 189/189 status and
canonical IR matches, all four language safety gates were zero, and 11/11
representative language missions were runtime-equivalent to their Oracle IR
counterparts. This is a bounded grammar-based baseline, not general language
understanding. Artifacts: `experiments/phase2/controlled_language_001/`.




**Phase 2.0 - Oracle mission runtime (complete).** Structured Mission IR
(no natural language, LLM, Jev or swarm component) is now validated,
capability-grounded against the frozen Phase 1.3 evidence, compiled into a
deterministic task graph and executed through the existing G1 skills. The
frozen 20-mission corpus (H1/H3/H5/H8) completed **20/20**, and the 15 negative
missions were rejected with **0 simulation steps**. Walk nodes use the
evidence-selected `heading_lateral` mode; in-place turn/stand/stop nodes stay
`open_loop` because the Phase 1.3 correction is a walking path-correction.
Artifacts: `experiments/phase2/oracle_mission_runtime_001/`; interactive
viewer: `python scripts/view_mission.py --mission <id>`.




**Phase 1.3 - closed-loop locomotion correction (complete).** Under the frozen
Phase 1.2 warehouse envelope, an outer heading/lateral feedback loop at the
policy-command layer (`motion.pt` unchanged; open-loop runs bit-identical to
the historical baseline):

- Open loop: 4 m PASS (-0.281 m drift / -6.72 deg), 6/8/10 m FAIL
(`EXCESSIVE_DRIFT`), reliable boundary ~4.6 m.
- `heading_only` (k=1.5) and `heading_lateral` (k=1.5/1.0) convert 6/8/10 m
to PASS with drift reduced 87-100% and heading error 93-98%, zero saturation,
zero control oscillation and no completion-time regression.
- Corrected reliable distance is at least 20 m (frozen 12/15/20 m extension
budget exhausted -> `boundary_not_reached_within_budget`); +16 m on the tested
grid versus open loop.
- Disturbance spot-check: at friction 0.175 the open loop diverges
(-4.43 m / -71.4 deg) while both corrected modes stay inside the envelope; the
60 N push spot-check passes for all three treatments.
- All 30 final runs were physical successes; 24/30 task successes (the six
failures are open-loop 6/8/10 m).
- Artifacts: `correction_comparison.json`, `boundary_comparison.json`,
`risk_map_v1_3.json`, `capability_map_v1_3.json`, `report.md` under
`experiments/baselines/g1_closed_loop_correction_001/`.

All Phase 1.3 statements are conditional on the frozen nominal envelope and
the two frozen disturbance points; no broader safety or reliability claim is
made.
**Research testbed for long-horizon Unitree G1 tasks with decision models, multi-swarm orchestration, and reinforcement-learning skills.**

> This repository is an experimental research testbed. No performance claim is considered valid without reproducible experimental evidence.

## Research question

Can a layered embodied-agent runtime improve the reliability and efficiency of long-horizon Unitree G1 task execution by separating:

- **reasoning** — mission understanding, decomposition, replanning, and multi-swarm coordination;
- **decision** — bounded high-level action/skill selection and escalation;
- **control** — learned or deterministic embodied skills executed by the robot.

The project will specifically investigate **Jev as a high-level decision model** inside this stack, rather than assuming it is beneficial.

## Current status

**Phase 1.2 - failure boundary & skill risk mapping (complete).** Frozen protocol
`configs/experiments/g1_failure_boundary_001.yaml` (hash `9145d03a...`) ran 91
final runs at commit `ea3bfb8`: **91/91 physical successes, 54/91 task
successes** - all failures are task-envelope violations with the robot still
upright.

- Lateral push (0.2 s, +Y): 20 N is LOW risk and 30 N remained reliable in
2-seed exploration; the task boundary appears at 60 N (40% task success in the
5-seed final sample) and 70 N failed for every run. No falls were observed up
to 100 N, so the fall boundary is not covered by this campaign.
- Friction: reliable down to 0.175; 0.15 fails (drift -2.04 m, heading -49.9 deg)
without falling.
- Initial yaw with a fixed world-frame 2 m goal: 5 deg LOW, 10 deg task pass but
strict-envelope degradation (MEDIUM), 15-20 deg fail.
- Long-distance walk: under the frozen nominal envelope the walk is already
degraded at 5 m, so the frozen ladder's safe start was wrong and the search
reports `boundary_not_reached`; Phase 1.1 evidence brackets the distance
boundary between 2 m (pass) and 5 m (drift limit exceeded).
- Joint perturbation 0.02-0.30 rad never degraded the task (offsets clipped to
joint limits): UNKNOWN beyond that ladder, not "safe".
- Deliverables: `capability_boundary_map.json`, `risk_map.json` (schema 1.2.0)
and `report.md` under `experiments/baselines/g1_failure_boundary_001/`.

All statements above are conditional on the frozen experiment envelopes; they
are not general safety or reliability claims.

**Phase 1.1 - G1 skill competence characterization (complete).** The frozen protocol
(`experiments/baselines/g1_skill_characterization_001/protocol.yaml`, SHA-256
`007b316f2334021c02865858988e758adb6f5d0b99bf6c9d09618c7dc80a45fb`) was executed
at commit `6c6af04`: 237/237 runs succeeded, 0 failures.

- Nominal WalkForward reaches its target within ~1 mm at 0.5-5 m, but lateral
drift grows with distance (-0.159 m at 0.5 m to -0.707 m at 5 m) and heading error
grows from -4.4 deg to -10.7 deg. Nominal runs are deterministic (3/3 identical).
- Nominal Turn (30-90 deg, both directions) lands within 0.07-1.24 deg of the
target with 0.12-0.23 m translation drift (frozen 15 deg tolerance).
- Stand holds height (mean 0.778 m, min 0.773 m) with roll/pitch <= 4.0/3.3 deg
over 5/10/20 s; the base creeps ~2.2 cm/s (0.09 m at 5 s to 0.45 m at 20 s).
- Stop from 0.25/0.50/0.75 m/s needs 1.08/1.31/1.53 s and 0.10/0.19/0.29 m.
- All 18 perturbation conditions (nominal/yaw/xy_offset/joint/friction/push x
walk/turn/walk+stop, 10 seeds each) succeeded: the frozen envelope produced no
failure. Perturbed conditions give 10/10 unique trajectories across seeds.
- A real implementation bug was found by the pilot and fixed: TurnSkill ignored
the sign of the target angle (-45 deg was executed as +45 deg). Before/after
evidence is preserved in the characterization report.
- Competence map: `experiments/baselines/g1_skill_characterization_001/competence_map.json`
(schema 1.1.0) - machine-readable capability evidence for future routing layers.

**Phase 1 (frozen baseline).**

**Phase 1 — G1 simulation baseline.** The measured facts on this machine (Windows 11, Python 3.11.9, `mujoco==3.15.0`, `torch==2.14.1+cu130`, RTX 5060 Ti 16 GB):

- Official Unitree G1 MJCF models load and run headless natively under MuJoCo for 1000 steps each with no NaN/Inf and no MuJoCo warnings: the full-body 29-DOF model (`unitree_mujoco` @ `1eb6642`) and the 12-DOF leg model used by Unitree's own MuJoCo deployment (`unitree_rl_gym` @ `276801e`).
- Walking is produced by Unitree's official pretrained TorchScript policy through a headless port of the official MuJoCo deployment pipeline (12 actions, 47 observations, 50 Hz policy, 500 Hz physics). No teleporting or root-pose editing is used by any skill.
- Baseline-001 (`Stand -> WalkForward 2.0 m -> Stop`): 5/5 runs ended inside the pre-frozen `[1.8, 2.2] m` window with 0 falls; mean final displacement 2.169 m, mean lateral drift -0.365 m, mean heading error -8.41 deg. The controller is deterministic, so the five seeds are identical runs.
- Phase 1 target skill status: `Stand` PASS, `Stop` PASS, `WalkForward` PASS, `Turn` PASS (45 deg pilot, 5/5, error 0.18 deg).
- No locomotion training was performed. No Jev, multi-swarm, LLM, perception or manipulation component is active in this phase.

Reports: [compatibility spike](experiments/baselines/g1_compat_spike/README.md) · [Baseline-001](experiments/baselines/g1_baseline_001/README.md) · [skill characterization](experiments/baselines/g1_skill_characterization_001/report.md) · [turn pilot](experiments/baselines/g1_turn_pilot/README.md).

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
| `src/g1swarm/mission/` | Typed Mission IR, static validator, capability/risk grounding, task graph, deterministic executor and per-mission evidence |
| `src/g1swarm/language/` | Frozen Lark grammar, deterministic controlled-Chinese compiler, typed `CompilerResult`, normalization/units, corpus and compiler benchmark |
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
python .\scripts\run_oracle_missions.py --pilot --repeat 2
python .\scripts\run_language_benchmark.py --pilot
python .\scripts\run_language_benchmark.py --final
python .\scripts\view_mission.py --mission h5-stand-walk4-turn45-walk4-stop
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
