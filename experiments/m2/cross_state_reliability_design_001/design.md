# M2.4 — Cross-State Adaptive Runtime Reliability: design only

Question: does the accepted Failure → Halt → Assess → TEST_ONLY immutable authorized new Mission chain retain its bounded behavior in physically different, reproducibly reached failure states? Prior PASS is one previously seen seed-0 state. This phase supplies no new reliability result and authorizes zero physics.

## Baseline and interpretation

PR #7 was merged by merge commit 884edde1dd19931a8cc3d33c0640a42874f2e6bf, parents a114ec90a4f577420e6f183fe0c41cadedba03fd and 1b390d70a3825508ef4d451884244924e24df9ac. Merge tree equals reviewed PR HEAD. Independent main acceptance and a new publication decision preserve the old working-branch decision unchanged. M2.4 remains a separate pending design, not a promoted result.

The parent halt last-second mean0.0999695815m/s has a very small margin under0.10. Termination and eligibility may therefore be sensitive to gait/history. A graph block is not a halt; ABSTAIN/ESCALATE is not a physical stop. Current Runtime requests the opt-in StopSkill only after a physically successful Walk receives strict STOP_DEPENDENTS. A skill-level failure or fall can end the mission without this halt trigger. We measure that limitation; we do not extend Runtime to hide it.

## Scope and feasibility

Only bounded initial task history or a previously exercised finite push changes state acquisition. Fixed official motion.pt, controller/PD/gains, physics timestep, default model/friction, skill parameters, strict evaluator, halt contract, lifecycle and trusted handoff are retained. There is no residual/reward/observation/threshold tuning. New Mission remains the same reviewed Walk4 → Turn45 → Stop plan and complete canonical authority binding.

Independent state means a separate reachable physical condition and task history, not a fresh seed, different XY/yaw coordinates, or another copy of identical trajectories. No captured qpos is teleported into a simulator. Within each run, the parent, halt, assessment and continuation use one real session with exactly the inherited startup initialization; no later reset. Paired arms replay the same construction, and their predecision raw traces must match exactly. Those paired copies are not independent samples. Joint position/velocity, body-frame motion and controller memory determine whether new conditions actually yield distinct failure/halts beyond a rigid world transform. Save differences descriptively; do not select a numerical cutoff after outcomes or replace a duplicate state.

The old M2.3b acquire.py asserts equality to historical baseline and HALT_SUCCEEDED. It cannot simply be run on new states. A future experiment-only acquisition adapter must preserve every parent/trigger/halt failure, conditional eligibility and all negative cells. That adapter, its observer equivalence, actual complete source/asset manifest and hard watchdog must be independently reviewed before any later acquisition authorization. No adapter or controller is implemented now.

## Separately scored stages

1. Parent trigger: retain strict PASS/FAIL, physical/skill status, failed node and graph block. If no strict trigger occurs, record NO_HALT_TRIGGER and missing failure-state coverage; never fabricate a failure or force Stop.
2. Halt: record REQUESTED, HALT_SUCCEEDED or HALT_FAILED using all unchanged checks. Report pre/post speed, full speed trace, last1s mean, duration, displacement/path length, height/tilt/finiteness/fall and every limit margin. No trigger is not HALT_FAILED.
3. Assessment: retain all exact reasons, current raw state and parent/graph provenance. Halt success is necessary but not sufficient. HALT_FAILED, absent trigger, missing evidence or ineligible live state means ESCALATE / NOT_ISSUED; no claim that refusal physically stopped the robot.
4. Authorization: correct registered identity, exact issuer-owned full plan, context, session and explicit host permission; negative requests must yield zero incremental executor/node/physics/reset calls and unchanged raw state/parent evidence. The deliberate stale-state construction step is recorded separately from zero-dispatch refusal.
The normal control does not instantiate lifecycle or request authorization; a normal SUCCESS is not ESCALATE. An intended failure condition that never triggers halt is retained as missing failure-state coverage, not an authorization PASS.

5. New task: score strict Walk, all required node results, nominal/physical, final task Stop instantaneous and mean speed. An allowed dispatch that later fails is a reliability failure, not an authorization failure. Original task remains FAILED and its artifacts are immutable. If the new task itself receives a strict Walk failure, the unchanged opt-in Runtime may issue its inherited physical halt; record child failure/halt separately, never fabricate new-task success or add a manual recovery.

## Stop and conclusion

Run only the approved frozen matrix once, no result-driven retries, severity scan, parameter substitution or extra seeds. Halt failure or task failure is a scientific result and does not justify repair/tuning. Close an unsafe/ineligible arm without further mission dispatch; closing MuJoCo is not hardware safety. Integrity/reset/source/plan/provenance violation or observer interference stops the entire acquisition, saving partial evidence. Ordinary negative science retains remaining predeclared conditions to characterize the bounded contrast. Hard budgets, wall watchdog and stage progress are mandatory; a stall stops partial, never restarts a completed run.

A future all-stage success supports only the tested bounded conditions, not a stable probability or production safety. Any halt/eligibility/new-task failure refutes blanket qualification for the frozen set. Authorization leakage invalidates the integration claim and stops acquisition. Missing triggers, duplicated conditions, unavailable evidence or technical censoring produce INCONCLUSIVE/PARTIAL coverage. No positive is required; no new condition is added to obtain PASS.

Stop now after independent design review, budget/contract checks, Research Ops telemetry and Git delivery. Next acquisition requires explicit approval of this design plus the reviewed frozen implementation/manifest. Jev, PPO, Multi-Swarm and Language Runtime/D011 stay disabled.
