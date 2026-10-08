# Frozen same-frame residual comparison

Source anchor: `1726d74111abe8084a0f509edafb8c16b1b3ad01`.
Acquisition freeze: `a4926973e01b65f98fc7c598d48ac982b47d6516`.

Protocol SHA: `df0529a7f9f542463eadf99a1b01c36346344bec184009b13b44eef688781afb`.
Case manifest SHA: `641dcdf36447976cfb29e64dd24bbe911beaca8284ef7299f82f9cb7ce38a909`.
History manifest SHA: `b124a1f66eed10b59ad8ed3e4e1ff7de34e382bc67e28a1a136c654dd34ddfc4`.
Original pilot protocol SHA: `d27a92c59f6496a796208dd4b5d8b91ea2a2b98f793a3fc28bba9e3a229663df`.
Official motion.pt SHA: `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.

669 historical source/evidence pins and the inherited 219 foundation pins are
checked before and after acquisition. Historical files, local envelopes and
previous negative results remain unchanged. Source hashes bind all new study
modules and the runner to their exact acquisition Git bytes.

## Factor and controls

Both frames use actual node-start origin. Alpha0 uses actual node-start heading;
alpha0.5 uses the already fixed wrapped midpoint toward commanded heading. The
frame rotates both heading and lateral axes; correction gains1.5/1.0,
clamp0.6/deadband0.01 remain original. The selected correction frame never
replaces the actual-start frame used by skill termination, observations, reward
or nominal/strict scoring.

Six evaluation arms instantiate four treatment classes: two residual-off
controls and four learned actors (each frame, seeds11 and29). Every learned
actor is paired only with its own frame's residual-off control. Initial actor
tensors are paired by seed across frames; subsequent state/case exposure may
differ because closed-loop episode duration changes. Fixed decision budgets,
not forced exposure or outcomes, define the comparison.

All original training settings are copied literally: 61 features; original
stateful dense and terminal reward; 64×64 MLP; PPO512-step rollout, batch64,
five epochs, learning rate0.0003, gamma0.99, GAE0.95, clip0.2, entropy0; CPU one
thread; 8192 decisions per actor; unchanged defaults such as target_kl=None.
Residual bounds remain vx/vy/yaw0.10/0.06/0.12, sampled every0.1s and applied only
within the first2s of the original four eligible transition families. No joint
policy weights are optimized. Outside-window/primitive residual is zero.

The original runner, controller, monitor, skills and rewards are inherited.
The new environment changes only its runner factory. Diagnostic logging never
calls stateful reward again, alters episode RNG, or resets base policy memory.
Configured policies, actual decision calls and optimization versus inference
are recorded distinctly. All training decisions include their original61
observations, requested actions, returned rewards and actual command samples.

## Prospective data separation

Training reuses the exact original12 cases, equally for both frames and seeds.
The16 fresh transition tuples were fixed without simulating candidate outcomes:

| Family | Fresh parameters |
| --- | --- |
| walk→turn | walk1.25/+37.5°, walk2.5/−37.5°, walk1.25/+67.5°, walk2.5/−67.5° |
| turn→walk | +37.5°/walk1.25, −37.5°/walk2.5, +67.5°/walk1.25, −67.5°/walk2.5 |
| walk→stop | walk1.25/yaw0°, walk2.5/yaw0°, walk1.25/yaw+7.5°, walk2.5/yaw−7.5° |
| stand→walk | stand1.5/walk1.25/yaw0°, stand2.5/walk2.5/yaw0°, stand4.5/walk1.25/yaw+7.5°, stand6.5/walk2.5/yaw−7.5° |

Distances are metres and stand durations seconds. Original helper functions
retain all skill defaults/envelope rules. Split validation checks full recipes,
overlap ignoring initial yaw, and adjacent primary task tuples in old sequences.
Renaming a case or changing its nominal simulation seed does not create a fresh
task. The new set tests parameter interpolation in the same nominal simulator;
it supplies no new-environment or stochastic robustness claim.

Old16 transitions, eight primitives and two12m/16m sequences remain26 seen
regression cases. They are never combined with fresh16 to claim held-out42.
First new held-out physics executes only after all four8192-step final file/
tensor receipts are immutable in `final_checkpoint_lock.json`. Checkpoint saved
times, lock time, evaluation recorded times and append-only stage ledger make
that order inspectable. Unit tests, smoke and checkpoint reload use old cases.

## Retention and analysis

Smoke seed7 is separate512-step validation per frame. Each formal actor retains
initial,2048,4096,6144 and fixed-final8192 checkpoints. Smoke retains initial and
final. The main evaluation never uses intermediate scores or picks a best
checkpoint. Failed optimization checkpoints and failures are retained; no
semantic retry, seed extension, reward rewrite or extra budget is allowed.
Budget-interrupted episode tails are saved and excluded from completed episodes.

Primary evaluation is252 episodes:96 fresh (16×6 arms) and156 seen (26×6).
Separate36 repeats cover the first held-out case of each family and both seen
sequences across all six arms. Repeats check determinism and are not independent
samples. Final model reload also reproduces a training-only physical replay.

`analysis.py` was frozen before acquisition. It requires exact primary/split/
arm membership and reports original nominal/physical/strict booleans separately,
missing-node coverage, target-skill geometry, original transition diagnostics,
own-frame paired deltas and two-seed sign agreement. Continuous and strict
regressions remain visible even when nominal success is unchanged. No weighted
score, new task threshold, optimal alpha, significance claim or reward-only
learning verdict is introduced. Two seeds provide descriptive pilot consistency.

The next experiment, if any, is a new research decision after evidence review.
Current source-authority safety findings and Phase2.3 Language Runtime BLOCKED
status remain intact. This experiment ends at audited report and Git push.
