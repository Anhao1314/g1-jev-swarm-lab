# G1 PPO Yaw-Residual Environment Contract

Status: T0 candidate, not an implemented physical environment. `NO_TRAINING_PERFORMED`.

## Control boundary

```text
mission command
  -> frozen Phase 1.3 heading+lateral correction
  -> deterministic (vx, vy, yaw_rate)
  -> bounded PPO delta_yaw_rate (walk only, 10 Hz)
  -> inherited total-yaw clamp
  -> frozen Unitree policy (50 Hz)
  -> frozen PD torque loop (500 Hz)
```

The chosen T0 action is deliberately one-dimensional. The candidate actor may only add `delta_yaw_rate`; it cannot write `vx`, `vy`, joint positions, joint targets, torques, PD gains, policy weights, hidden state, model state, or base pose.

The exact composition contract is:

```text
a_t in [-1, 1] (an out-of-range request is contract-invalid; it is not clipped)
delta_yaw_t = 0.12 * a_t rad/s
yaw_applied = clip(yaw_deterministic + delta_yaw_t, -0.6, +0.6)
vx_applied = vx_deterministic
vy_applied = vy_deterministic
```

The residual is active only in `walk_forward`. It is held for 0.1 s while the deterministic outer loop and frozen lower layers continue at their inherited rates. The candidate full-walk mask is a new T1 authority proposal, not a modification of Phase 1.3 or Phase 3A and not authorization to execute it.

The side-effect-free implementation in `src/g1swarm/residual_rl/contract.py` additionally fails closed if the deterministic command already violates the inherited yaw corridor. This guarantees that a zero or disabled residual does not silently alter the baseline through an extra clamp.

## Observation

The candidate observation is `Box(-1, 1, shape=(18,), dtype=float32)` with fixed physical scaling only. No normalization statistic may be fitted on validation or test data.

| Index | Feature | Scale/source |
| ---: | --- | --- |
| 0–1 | `sin`, `cos` of mission-frame heading error | wrapped angle |
| 2 | lateral error | `E_lateral=max(0.35 m, 0.07*target_distance)` |
| 3 | forward progress fraction | mission-frame projection / target |
| 4 | remaining distance fraction | mission-frame projection / target |
| 5 | task time remaining fraction | task-defined horizon, included if horizon is terminal |
| 6–7 | mission forward/lateral velocity | finite difference of projected position / 0.5 m/s |
| 8 | base yaw rate | / 0.6 rad/s |
| 9–11 | projected gravity | inherited orientation transform |
| 12 | base-height delta from reset | / 0.2 m |
| 13 | nominal forward command | / 0.5 m/s |
| 14 | deterministic yaw command | / 0.6 rad/s |
| 15 | previous normalized residual action | already in [-1,1] |
| 16 | previous total-yaw saturation flag | 0/1 |
| 17 | standing flag | 0/1 |

Every raw observation component, observation-clipping flag, scale, requested/applied action, deterministic/applied command, total-yaw saturation flag, and controller reset count must be recorded. Disturbance identity/magnitude, split label, future outcome, and low-level LSTM hidden state are excluded from the actor.

The low-level controller is recurrent while its hidden state is not exposed. Therefore this compact observation is a pragmatic high-level state, not a proof that the process is Markov. T1 must report that limitation; a recurrent residual or history stack is outside the first smoke.

## Reward

Reward is a training surrogate only. Scientific conclusions continue to use the existing physical/task/nominal/strict evaluators and paired route metrics.

Let

```text
Phi(s) = -[(e_lateral/E_lateral)^2
           + 0.5*(e_heading/15deg)^2
           + 0.25*(remaining_distance/target_distance)^2]
```

At a 0.1 s decision step:

```text
r = gamma*Phi(s_next) - Phi(s)
    - 0.02*a_t^2
    - 0.01*(a_t-a_previous)^2
    - 0.10*tilt_excess^2
    - 0.05*I(total_yaw_saturated)
```

Here `tilt_excess=clip(max(0, tilt_deg-15)/15, 0, 2)`. Candidate terminal events add `+5` when the target is reached inside the frozen task envelope, `-5` when the target is reached outside that envelope, `-20` for physical failure, and `-5` for a task-defined horizon failure. Every component is logged separately. The potential includes remaining distance so a policy cannot gain simply by delaying while holding low instantaneous path error. First target completion ends the task, but target attainment and envelope success remain separate fields. No return threshold is a success claim.

Reward-risk checks for later physical execution:

- route progress and errors use the frozen mission frame, not path length or a redefined local direction;
- action magnitude/change and saturation are visible diagnostics, not substitutes for oscillation and physical metrics;
- falls do not become cheap early exits;
- final and integrated lateral/heading errors are reported independently of reward;
- a simple retuned deterministic controller remains a required comparator before attributing value to learning.

## Reset and step lifecycle

`reset(seed, options)` must:

1. call the Gymnasium superclass reset;
2. select only from the authorized manifest;
3. reset the simulator to the declared initial state;
4. reset the frozen recurrent controller exactly once according to the inherited skill lifecycle;
5. freeze the mission frame;
6. clear residual, reward, saturation, and evidence state;
7. return observation plus case/seed/source/config hashes.

No unfavorable initial state is silently resampled. Root pose setters may only express a predeclared initial condition; they are never locomotion actions.

`step(action)` returns the Gymnasium five-tuple. Boundary meanings are:

| Outcome | API | Scientific handling |
| --- | --- | --- |
| target reached (inside or outside the frozen envelope), fall/physical failure, or observed task-defined horizon | `terminated=True` | valid MDP terminal; record target attainment and envelope success separately |
| external decision cap, wall-clock watchdog, or authorized interrupt | `truncated=True` | retain, label, and bootstrap correctly; not task success/failure |
| non-finite value, simulator/controller exception, hash drift, or zero-residual mismatch | raise/fail closed | invalid episode, retain partial evidence, stop run, do not score |

Gymnasium separates termination from truncation because they differ in value bootstrapping: <https://gymnasium.farama.org/main/tutorials/handling_time_limits/>. The future implementation must also pass the Stable-Baselines3 environment checker before any training: <https://stable-baselines3.readthedocs.io/en/master/common/env_checker.html>.

## Method basis and non-claim

Residual RL motivates adding a learned command to a retained controller, but the cited work is not evidence for G1 locomotion performance: <https://arxiv.org/abs/1812.03201>. PPO alternates rollout collection with multiple minibatch epochs on a clipped surrogate; it likewise offers no guarantee of superiority here: <https://arxiv.org/abs/1707.06347>. Current Stable-Baselines3 PPO exposes `n_steps`, `batch_size`, `n_epochs`, `clip_range`, and optional `target_kl`, which informs the bounded smoke configuration: <https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html>.

The machine-readable version is `configs/experiments/g1_ppo_residual_t0.yaml`.
