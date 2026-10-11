# T2a candidate protocol — Owner confirmation pending

Parent: PR #28 exact HEAD 7e86481a972146614863bd4b6c4fd4b9d8347241. This is a prospective design and nonphysical readiness delivery, not an executed comparison. The current message explicitly calls the authorization a draft. No new physics or policy prediction is permitted until Owner separately confirms this exact study. A CLI flag is only an accidental-launch guard; it is not real Owner authorization or production identity proof.

## Frozen membership and execution

Order B0 → C0 → C256, one attempt each. One historical seen nominal4m/no-disturbance scene,seed7,actual-start frame,speed0.5m/s,horizon24s. B0 is original WalkForwardSkill with Phase1.3 heading_lateral controller; C0/C256 use the same frozen Gym wrapper and deterministic=True actor prediction with T1b checkpoint0/256. Same model,controller,PD,timestep0.002s,policydecimation10,deterministic gains1.5/1.0,residualperiod0.1s,Walk-only yaw residual±0.12,totalyaw±0.6,18features,originalphysical/nominal/strict evaluator. No profile/reward/scenario search or training.

Each group starts with a separately constructed simulator and low-level controller,then one declared episode/skill reset. Constructors' initialization resets are separately counted. Freeze actual-start frame at reset; reset the official policy memory once for the episode. Residual actors are stateless MLPs: load a fresh CPU actor per checkpoint group,do not reuse state from another group,predict deterministically,no exploration noise. No Stand warmup,hidden teleport,friction or external force. End at original first4m completion or24s horizon. Close each group; no dispatch after a stop condition.

Maximum12000 native steps per group,36000 total,600s total wall,oneCPU environment,oneTorch intra/inter-op thread. Supervisor reuses previously verified Linux process-group termination at595s,including source preflight;cleanup margin below600s. Native reservation flushed before every physics step and measured completion after it. No automatic retry. Existing shared Ledger remains unchanged and is instantiated with limit36000;per-group originalWalk/Gym horizon enforces12000.

## Strictly fixed actors

C0 SHA256 1b169cf6fdc2f703f4c38814b10b983820a289b60222ee55c801566e2606dec2.
C256 SHA256 cc383df4f9508d9db97f12043f483e4b8e7ae5ee7bf0d1de015197384ef486d2.
Read existing ext4 checkpoint files from T1b;verify bytes before any actor load. No reinstall/download. PPO learn/train/optimizer.step are blocked in evaluation. Historical checkpoint optimizer counters0/8 are provenance,not new optimization;new optimizer calls must remain0. Actor weights must remain byte/tensor identical before and after the one inference run. Frozen official motion.pt andMJCF hash verification required. No M2.6A/held-out data.

## Measurements and matched comparison

Raw native qpos/qvel,torques,deterministic/applied commands,policycounter,controller/simulator resetcounts,fallflags andtimestamps retain the existing logger schema. Actor records include predecision18-vector,deterministic action,and checkpoint identity. Record original physical,nominal,strict metrics plus forward/lateral/heading,endpoint distanceerror,lateral/heading RMS and maxima,completiontime andresidual yaw. Do not use reward/return as scientific success. The Gym wrapper still computes its frozen reward for logging;no optimizer consumes it.

Before comparing behavior,verify all three initial qpos/frame/control identities andreset counts. Compare full raw trajectories and native-time common prefixes. A shorter trajectory is never extrapolated to the longer endpoint. Retain endpoint metrics at each group's own original terminal. Weight differences,deterministic action differences,command differences andphysical trajectory differences are distinct findings;one does not automatically prove the next.

## Candidate interpretation rules (requires Owner review)

No new continuous-gain threshold is invented. Primary classification uses existing gate vector physical_success/task_success/strict_success against BOTH B0 andC0:

- Missing outcome/source/technical integrity: INCONCLUSIVE;retain partial physical observations separately.
- C256 loses any original gate passed by either reference: REGRESSION.
- C256 weakly improves every gate and strictly improves at least one against each reference: IMPROVED_SEEN_CASE.
- All three gate vectors identical: NO_MEANINGFUL_GAIN,meaning no demonstrated incremental gate-level gain,not proof of identical trajectories or unimportant continuous differences.
- Other reference conflict: INCONCLUSIVE.

Continuous changes are printed alongside this classification,including small improvements or mixed costs. Because B0 historically already passed this seen task,continuous margin improvement alone will not be relabeled a gate-level scientific gain. If Owner prefers a different primary objective,it must be prospectively reviewed before any acquisition,never after results. No generalization claim from this single case/seed.

## Stop and evidence preservation

Immediately stop on fall/inherited safety failure,invalid/bounded action,nonfinite value,hash/source drift,exception,wall/native-budget violation ormissing evidence. No later group after a stop. An observed physical failure is retained alongside incomplete coverage;technical interruption cannot erase an established fall. C256 physical failure with both earlier reference outcomes known can support gate-level REGRESSION;missing earlier/later outcome remainsINCONCLUSIVE. Normal nominal/strict task-envelope failure without a physical safety event is retained as a scored outcome;do not tune or retry it.

Exclusive new evidence directory,once.claim,rawstdout/stderr,native/actor/metrics,checkpoint/source/config/Readiness hashes. A Source/Readiness proposal is prepared before Owner confirmation;the later actual approval message must be archived as its own authorization receipt and independently checked against the proposal. CLI flags are not a substitute. Sentinel reviews source/design before execution and raw receipts afterward. New Draft PR only,no merge. Current scientific status remains T1b PIPELINE_PASS/LEARNING_GAIN_NOT_PROVEN;T2a has NO_RESULT and0physics/policy/optimizer calls.
