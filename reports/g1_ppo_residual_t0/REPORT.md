# G1-RL Training Lab — T0 Research and Design Report

Date: 2026-10-10 (Asia/Shanghai)

## Verdict

**`T0_DESIGN_COMPLETE__T1_BLOCKED_PENDING_OWNER_AND_RUNTIME_READINESS`**

The repository supports a narrow residual-RL seam at the existing high-level `(vx, vy, yaw_rate)` command boundary. The selected candidate freezes the official 12-DoF locomotion policy and Phase 1.3 heading+lateral controller, then permits PPO to add only a bounded scalar `delta_yaw_rate` during Walk. This is substantially narrower than retraining joint torques and narrower than the historical three-axis Phase 3A residual.

No claim is made that PPO will beat the deterministic controller. Existing evidence makes that uncertainty material: Phase 1.3 is already strong, the historical Phase 3A PPO pipeline produced no consistent learned gain, and later residual-authority studies remained `INCONCLUSIVE` with Phase 3A.5 paused.

**`NO_TRAINING_PERFORMED`**: T0 executed zero physics steps, zero policy loads, zero optimizer updates, zero checkpoint writes, and zero GPU calls.

## Baseline and scope result

- The requested worktree did not exist. It was created at the exact requested path and branch from `4e2a51bf143cafea5eb90e89a88e1f04c156c9c8`.
- `origin/main` exactly matched that commit. Local `main` was older (`c2fd2762...`, 149 commits behind), so it was not used.
- The original checkout had unrelated untracked research assets. They were left untouched.
- Research Ops returned `CURRENT`; its retained state still marks Phase 3A.5 paused and acquisition unauthorized. This user task authorized T0 design/static preparation only, not acquisition.
- No M2.6A file/state/result was used for tuning or case design. No frozen protocol, historical artifact, threshold, label, or scientific verdict was modified.

## Delivered design

- `CAPABILITY_MAP.md`: source-backed reusable components, historical evidence boundaries, and engineering gaps.
- `CONTRACT.md`: 18-feature observation, 1-D action, bounded command composition, candidate reward, reset, termination/truncation, and invalid-transition semantics.
- `PROTOCOL.md`: immutable comparators, split isolation, metrics, ablations, T1 budget, checkpoints, and stop rules.
- `configs/experiments/g1_ppo_residual_t0.yaml`: machine-readable T0/T1 candidate contract.
- `src/g1swarm/residual_rl/contract.py`: side-effect-free command/boundary skeleton only.
- `tests/test_residual_rl_contract.py`: non-physical checks for zero equivalence, bounds, fail-closed input handling, API boundary semantics, and data-isolation declarations.
- `independent_review.md`: Sentinel review of the completed candidate.
- `validation.json` plus retained initial/final logs: exact non-physical receipts, including the first failed collection attempt.

## Technical selection

The primary action is `Box(-1,1,shape=(1,))`, mapped to `delta_yaw_rate` ±0.12 rad/s after Phase 1.3 correction and before the frozen Unitree controller. The pure composition contract preserves the `vx` and `vy` components exactly for float64 Phase 1.3 commands; real B0/B1 command and physical equivalence remains a mandatory T1 gate. Total yaw remains within ±0.6 rad/s. Action frequency is 10 Hz; the lower 50 Hz/500 Hz stack stays unchanged.

The compact observation uses route errors/progress, mission-frame velocity, yaw rate, projected gravity, height delta, deterministic command, previous residual/saturation, remaining task time, and standing state. It deliberately omits raw joints and disturbance labels. Because the low-level LSTM hidden state is unavailable, Markov completeness is not claimed.

Reward uses route-error/remaining-distance potential shaping plus small action, slew, tilt, and saturation costs. Existing physical/task/nominal/strict gates remain the evaluators. Reward/return cannot redefine success.

## Data and evaluation decision

All prior Phase 1/1.3/3A evidence is now `historical_seen_regression`. T1 smoke may use one seen case only to validate the pipeline. Formal train, validation, and unseen manifests are deliberately not authored from current outcomes. The unseen set must be independently frozen after environment/reward freeze and remain sealed through checkpoint lock. M2.6A remains outside this research line.

The primary paired comparison is the frozen Phase 1.3 baseline versus the candidate PPO residual. A zero-residual wrapper is a mandatory engineering equivalence gate, and a same-budget deterministic retune is a later required comparator before any learning-specific attribution.

## T1 candidate and blockers

T1 smoke is capped at 256 high-level decisions, one CPU environment/seed, two 128-step PPO rollouts, checkpoints at 0/128/256, fixed-final selection, and a 600-second watchdog. It can prove only pipeline/safety-smoke behavior; performance remains `NOT_PROVEN`.

T1 is blocked until all of the following occur under separate Owner authorization:

1. restore and hash-verify the missing official `motion.pt` and G1 MJCF assets;
2. create an isolated locked dependency environment for this worktree (it currently has no `.venv`, and Gymnasium/SB3 are not declared in `pyproject.toml`);
3. implement the Gymnasium environment without changing frozen controllers/evaluators;
4. freeze the smoke case and source/config/split identities;
5. pass static/API checks and exact B0/B1 zero-residual equivalence before optimizer creation.

## Stopping reason

The T0 research questions, design contract, bounded T1 proposal, non-physical checks, and independent review are complete. Any further action would enter T1 setup, policy loading, MuJoCo acquisition, or training and therefore requires a new explicit Owner authorization.
