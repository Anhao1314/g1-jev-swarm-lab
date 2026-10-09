# Codebase Capability Map

Status: source/evidence audit only. `NO_TRAINING_PERFORMED`.

## Baseline identity

- Worktree: `D:\webcodex\mujoco-g1\rl-training`
- Branch: `research/g1-ppo-residual-t0`
- T0 start: `4e2a51bf143cafea5eb90e89a88e1f04c156c9c8`
- `origin/main`: exact match to the requested start.
- Local `main`: `c2fd2762d4a32c85a8031abe88e54ad7b955157e`, an older ancestor 149 commits behind the requested start. It was not used.
- The target worktree did not exist at task start; it was created from the exact requested commit. The unrelated source checkout and its untracked research files were not modified.

## Reusable capabilities

| Capability | Source evidence | Actual contract | Reuse decision |
| --- | --- | --- | --- |
| Official 12-DoF locomotion | `src/g1swarm/control/g1_locomotion.py:29-57,60-111,125-192`; `configs/robot/g1_locomotion_12dof.yaml:1-38` | High-level command is `(vx, vy, yaw_rate)`; 47 low-level observations; 12 targets; PD torques; 500 Hz physics and 50 Hz policy refresh; recurrent memory has an explicit reset | Freeze completely. PPO must not emit joint targets/torques or alter policy/PD/action scale. |
| Simulation/state adapter | `src/g1swarm/simulation/g1_simulation.py:42-184,209-225`; `src/g1swarm/state/robot_state.py:37-97` | Deterministic reset surface, actuator-shape and finite checks, compact serializable base state, fall/standing flags | Reuse in a future authorized environment; no T0 instantiation. |
| Stand/Walk/Turn/Stop | `src/g1swarm/skills/basic.py:63-92,95-388`; `src/g1swarm/skills/contract.py:21-150` | All motion reaches the robot through the same command-to-torque seam; Walk uses `[speed,0,0]`; Turn uses yaw-rate; lifecycle/reset behavior differs by skill; outcomes are structured | Preserve skill bodies, preconditions, success statuses, settle behavior, and controller-memory lifecycle. |
| Mission frame | `src/g1swarm/segmentation/mission.py:24-56` | Frozen origin/heading with forward, lateral, and wrapped-heading projections | Reuse for observations, reward components, and scientific metrics. Never redefine direction during an episode. |
| Phase 1.3 deterministic controller | `src/g1swarm/control/path_correction.py:1-22,41-72,97-177,180-229`; `configs/experiments/g1_closed_loop_correction_001.yaml:45-101` | Converts heading/lateral error to yaw-rate; copies nominal command and changes only index 2; total yaw clamp ±0.6 rad/s; deadband 0.01; tracking of saturation and oscillation; reset delegates to the frozen controller | Primary strong baseline and the additive residual seam. Zero residual must be exactly equivalent. |
| Existing evaluation gates | `src/g1swarm/boundary/envelope.py:27-89,120-171`; `src/g1swarm/metrics/schema.py:74-171` | Physical success and nominal/strict task envelopes are separate; required/non-finite metrics fail closed | Reuse as evaluation, never as reward-defined replacements. |
| Historical PPO plumbing | `src/g1swarm/transition_learning/env.py:1-103,179-227,333-443`; `src/g1swarm/transition_learning/training.py:71-126,153-315,339-440,479-567` | Real Gymnasium worker; 61 observations; 3-D bounded command residual; 10 Hz; first 2 s of selected transitions; provenance, checkpoints, partial-tail retention, fixed-final evaluation | Reuse evidence/provenance patterns only. Do not edit the frozen experiment or reuse its held-out cases as unseen. |

## Historical evidence and limits

These are retained historical results, not T0 reruns.

- Phase 1.3 reported 30/30 physical successes and 24/30 task successes across the bounded campaign. Corrected walking passed through 20 m within the search budget, with no measured saturation or oscillation. This does not establish a true failure boundary, real-world robustness, arbitrary terrain generalization, or recovery: `experiments/baselines/g1_closed_loop_correction_001/report.md` and `docs/lab-notebook/phase1-embodied-execution.md:292-378`.
- Decision D006 explicitly selected outer-loop correction before replacing/retraining `motion.pt`: `docs/lab-notebook/research-decisions.md:72-82`.
- The historical Phase 3A PPO study completed a real training/checkpoint/evaluation loop but concluded `PIPELINE_VALID_NO_CONSISTENT_LEARNED_GAIN`: `experiments/phase3a/transition_learning_001/REPORT.md`.
- Its training/evaluation cases, reward, learned checkpoints, and observed outcomes are now seen evidence. They cannot be relabeled as fresh validation or unseen test data.
- Later residual-authority work remained `INCONCLUSIVE`; no strict + physical + same-reference global witness was established and Phase 3A.5 remained paused: `experiments/phase3a/residual_authority_feasibility_001/REPORT.md` and `ops/decisions/phase3a4g-selection.json`.

## Engineering gaps before T1

1. The worktree has no `.venv`, official `motion.pt`, or G1 `scene.xml`. T1 is not runnable and T0 did not download or install them.
2. `pyproject.toml` does not declare Gymnasium or Stable-Baselines3; Torch is intentionally external. A later authorized T1 needs an isolated, exact dependency/runtime receipt without modifying the frozen `D:\work\mujoco-lab`.
3. The existing PPO environment is transition-only and first-2-seconds-only. It cannot establish continuous disturbance adaptation, route tracking, or long-task gains.
4. Existing code reads the controller's private `_counter` for gait phase. The new design excludes that private state from the minimum observation rather than coupling a new environment to it.
5. Existing `TransitionEnv` uses simulator seed 0 while Gym seeding selects cases. A new claim cannot call a case-selection seed an unseen physics seed.
6. Existing Gym code always returns `truncated=False`. The new contract must distinguish task terminal states, external truncation, and invalid/non-scored infrastructure transitions.
7. The low-level LSTM hidden state remains unobserved. The T0 high-level observation is not claimed to be a proven Markov state.
8. A future scenario generator and train/validation/unseen manifests remain to be independently frozen. M2.6A unseen state is out of scope.

## Source identities sampled in T0

| Path | SHA-256 of T0 worktree bytes |
| --- | --- |
| `src/g1swarm/control/g1_locomotion.py` | `0871c4bd5cfb8270d5e8c2f06636f53f0cac3c63c625bef63356d1295f9c9c78` |
| `src/g1swarm/control/path_correction.py` | `b18768012605c76a18f2a81cc7aefb864a04fb75098771f13fd7ac5320011dd3` |
| `src/g1swarm/simulation/g1_simulation.py` | `d19c3d529f699d3c219a53b867e32e6eeadfd55703ba32ea5794fc902c16fb4c` |
| `src/g1swarm/skills/basic.py` | `240e0be476fe10893c34d8f7882125023db8104f7d8bcdc9d796cee6ac0abee5` |
| `src/g1swarm/transition_learning/env.py` | `5542043862860e61974204fa0cd5c75a39142d1faaa5e215b5c756a7a6fd2abc` |
| `configs/experiments/g1_closed_loop_correction_001.yaml` | `a9a3028bec1fb5f4dea80d96353c0d3305de8cea9c201ba183434e4fe56e6345` |

The Phase 1.3 report uses the repository's normalized LF identity for its frozen protocol. The Windows checkout byte hash above is not evidence of scientific drift.

## Atlas audit boundary

Atlas performed targeted read-only source/evidence inspection. It did not modify files, run tests, construct MuJoCo, load the policy, or train. Main Codex separately ran the non-physical T0 contract checks recorded in `validation.json`.
