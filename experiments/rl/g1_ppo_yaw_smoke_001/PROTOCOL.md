# T1 first real yaw-residual PPO smoke (prospective freeze)

This campaign implements T0 e1ddd31978779365634989684579587668a56e7d. It is a pipeline experiment, not an efficacy or safety qualification. Owner authorization is the task message for this one campaign. M2.6A, PR26, original Windows sources, historical data, thresholds and Research Ops selection remain untouched.

## Fixed scenario and gates

Historical seen Phase1.3 nominal 4m WalkForward, speed0.5m/s, horizon24s, no initial injection, no external force, seed7. Actual-start mission frame; heading_lateral k_heading1.5/k_lateral1.0/deadband0.01/yawlimit0.6. No Stand warmup. Standard simulator constructor initialization followed by one declared episode reset; official controller constructor initialization followed by one episode/skill memory reset. No mid-episode resets. Policy is official motion.pt SHA cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d; unchanged MJCF/PD/controller/evaluator.

B0 uses the original WalkForwardSkill and Phase1.3 CorrectingController; B1 uses the new Gym wrapper with exact zero residual. Both run until the same 4m native-step endpoint or24s horizon, at most12000 native steps each. Compare every native command, PD torque, updated target, qpos/qvel, policy counter, reset count, terminal simulation time and frozen evaluator result with tolerance0. Any mismatch stops all later execution; no retry.

After B0/B1 exact PASS, SB3 check_env runs once with the same physics/seed7 and a recorded action-space seed7. Its mandatory reset(seed=0) is an API probe only: requested Gym RNG seed0 is recorded, simulator seed is always7, there is no randomized physical initial condition. These real checker steps count toward the global native budget. No hidden uncounted environment probe is permitted.

Only then one PPO.learn(256), CPU, Torch threads1/inter-op1, seed7, one environment. T0 parameters n_steps128/batch64/epochs2/lr3e-4/gamma.99/GAE.95/clip.2/targetKL.03/MLP[32,32] and unchanged 18-feature/reward contract. A tanh-squashed Gaussian with its Jacobian log probability is used so PPO proposes bounded actions instead of silently clipping out-of-range Gaussian requests. No action/window/amplitude/reward search. Checkpoints0/128/256 are fixed; save128/256 after their optimizer updates; final only, no best selection. Reload comparison is nonphysical.

## Budget and external completion

Global maximum60000 native steps /1800 physical wall seconds includes B0/B1/check_env/training. Before each mj_step, flush a reservation, then flush the completed measured row. A killed reserved tail is unknown, never fabricated as a completed step. Per-episode maximum12000 native steps. Training256 decisions each at most50 native steps, shortened only by original Walk target/horizon. Final external decision cap is truncated (SB3 TimeLimit bootstrap), not task success. Native physical failure is immediately logged and aborts the campaign before another policy/physics step; no reset/resampling or optimizer update is allowed after that failure. Invalid values/exceptions also abort and preserve partial records.

An independent Linux supervisor owns a new session/process group and polls every0.05s. It terminates the group at global1795s or training595s, followed by SIGKILL after0.25s; the margin is below Owner1800/600 limits. Nonphysical child+descendant timeout injection must PASS before physics. Output directory creation is exclusive, with a once.claim; the authorized acquisition is never rerun.

## Frozen identity and evidence

Supervisor and Worker both require the independently recorded freeze SHA256 as an explicit argument; a modified manifest is rejected before runtime imports. Before runtime imports, verify exact execution Git HEAD, clean tracked source, all src/config/runner hashes,30 required official asset hashes, complete installed dependency file hashes and versions, venv and actual import origin, scenario and budget. Source-root overrides are refused. No GPU, ROS, driver/toolkit installation or external policy call. Linux ext4 paths are independently provisioned.

Record raw native reservations/completions, reset initial states,18 raw/scaled/clipped features, actions, deterministic/applied commands, saturation, every reward component, terminal metrics, optimizer-step count separate from epoch count, losses/KL, wall times and checkpoint hashes. Seal all raw files/checkpoints in a hash-bound archive; independent auditor recomputes counts and boundaries from raw data. All preparation failures remain in their original directories and are cited, not overwritten. No hidden-state Markov or generalization claim; one seen scenario and short partial episodes cannot establish superiority to Phase1.3.
