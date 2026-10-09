# Retained parent halt stopping-rule analysis

Read-only derived analysis of four saved parent halt traces; new-mission trajectories are excluded. Reproduction uses `halt_analysis.py --rawroot <cross_state_reliability_001/artifacts>`. JSON records input SHA-256 and exact floating-point values. No controller, simulator, policy or provider is imported or called.

Both arms have identical values within each family:

| Family | Halt duration / steps | Penultimate mean m/s | Terminal mean m/s | Margin below 0.1 m/s |
|---|---:|---:|---:|---:|
| seen_reference_walk6 | 1.342 s / 671 | 0.10033663736499489 | 0.09996958151718828 | 0.000030418482811725434 (0.0304185%) |
| transition_turn45_walk6 | 1.316 s / 658 | 0.10020112993031954 | 0.09981605732160394 | 0.00018394267839606793 (0.183943%) |

StopSkill takes a 500-sample trailing mean at 2 ms per step and exits on its first value at or below 0.1 m/s. Minimum possible halt time is 1.000 s, although the timestamp span between the first and last of 500 samples is 0.998 s. Initial pre-halt sample is correctly excluded from the deque. All 171 earlier eligible seen windows and all 158 earlier transition windows exceeded the threshold.

Seen terminal timestamps: 13.280–14.278 s; penultimate: 13.278–14.276 s. Transition terminal: 15.534–16.532 s; penultimate: 15.532–16.530 s. Seen endpoint speed is 0.05603522601217542 m/s; transition 0.0639899117815049 m/s. Terminal windows still contain respectively 262/500 and 251/500 instantaneous samples above 0.1 m/s (maxima 0.2391826502753261 and 0.25413246215701346).

The small mean margin is expected from a first-crossing endpoint selected by this rule. These records contain zero additional halt steps after qualification. They do not establish sustained stationary hold or robustness to disturbance. The retained HALT_SUCCEEDED result remains the bounded original result; this analysis neither overrides its acceptance rule nor adds a robustness verdict.

Source locators (reviewed source 8d80b7a):

- `src/g1swarm/skills/basic.py:166–194`: StopSkill zero command, post-step deque and immediate first qualifying break; no controller reset in this method.
- `src/g1swarm/state/robot_state.py:93–97`: speed is planar `hypot(vx, vy)`.
- `src/g1swarm/mission/live_session.py:87–118`: monitor starts with pre-halt state and appends each step.
- `src/g1swarm/mission/live_session.py:178–224`: independent halt uses existing controller; endpoint acceptance checks add instantaneous speed, duration, displacement and finite/standing/no-fall conditions, but no post-qualification hold.
- `src/g1swarm/skills/basic.py:244–249`: WalkForward defaults `reset_memory=True` and invokes controller reset.
- `src/g1swarm/control/g1_locomotion.py:103–111`: controller reset calls policy `reset_memory` if available, clears action, restores target to default angles, and zeroes counter. It does not reset physics. Source semantics alone do not establish a causal reset effect; no reset intervention was performed.

Validation: all four first qualifying steps equal their final trace step; all recomputed terminal means match retained skill metrics within 1e-14. No acquisition. No outstanding computation blocker. Stop because the bounded saved-data question is answered.
