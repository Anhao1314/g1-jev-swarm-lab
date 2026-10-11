# T2a Frozen PPO Policy Comparison — nonphysical preparation

**READY_FOR_OWNER_CONFIRMATION / NO_RESULT.** The current request explicitly describes a new authorization draft. No evaluation has run: 0 physics steps,0 policy loads/predictions,0 optimizer updates. There are no three-group measured trajectories and no scientific result to select yet. Existing T1b PIPELINE_PASS / LEARNING_GAIN_NOT_PROVEN and T1 BLOCKED remain unchanged.

The independent candidate branch is based on PR #28 exact `7e86481a972146614863bd4b6c4fd4b9d8347241`. It adds a small evaluation adapter,pure comparison helpers,protocol and tests without changing shared controller/skills/Gym environment/reward/PPO/scientific thresholds. No environment installation or asset download.

## Candidate execution identity

- Code HEAD: `0a8f16f3d9fbc7734c08f580933d2a21ad6d555c`.
- Readiness proposal SHA256: `cf0d476290a9e7bb5740f8503fc30fd29a3b1d309bf954fb666517f11564aadc`.
- Source Manifest SHA256: `0dd748cf6a951878c90d45d106eecf8633551a1bff24106da55b8f2f87186394`.
- Protocol/config SHA256: `1181c673cf34c0886bedd68351ce6ee2baef25999097b7150a590bfba7d2e77c`.
- Authoritative status: `acquisition_authorized=false`.

`FREEZE_RECEIPT.json` and `SOURCE_MANIFEST.json` are direct review entries;full Readiness and metadata are in the preparation archive. Original model/asset/dependency identities are reused and verified;C0/C256 bytes match the T1b hashes. Only checkpoint ZIP metadata was inspected,without loading a policy or predicting an action.

## Proposed matched comparison

Order B0,C0,C256,one attempt each. Same historical 4m,no disturbance,seed7,speed0.5m/s,horizon24s,actual-start frame. B0 uses original WalkForwardSkill/Phase1.3;C0 andC256 use fresh checkpoint actors with deterministic inference. Constructors and episode resets are separately counted. All initial qpos,simulator resets and first native controller counter/reset values must match. No Stand warmup or state injection.

Budgets:36000 cumulative native steps,12000 per group,600s total wall;outer process-group supervisor stops at595s with cleanup margin. Zero new optimization:learn/train/optimizer.step blocked,actor parameters checked before/after. No retries or later dispatch after safety/integrity/technical failure. Existing raw logger and controller/evaluator are unchanged.

Record native states,command/torque traces,actor inputs/actions,residuals,original physical/nominal/strict scores,target attainment/termination reason,endpoint errors,lateral/heading RMS/maxima and common-time trajectory deltas. Never extrapolate a shorter run. Heading derivation directly uses the original normalized MissionFrame metric. A fall remains visible even if the campaign is partial;technical failure cannot erase it.

## Interpretation requiring Owner approval

The existing contract has no minimum continuous-gain threshold. This proposal therefore uses original gate-level outcomes for the four requested labels,with continuous differences printed separately. C256 losing a reference gate is REGRESSION;strictly dominating both reference gate vectors is IMPROVED_SEEN_CASE;identical vectors are NO_MEANINGFUL_GAIN;missing/invalid/conflicting coverage is INCONCLUSIVE.

NO_MEANINGFUL_GAIN means no incremental **gate-level** gain was demonstrated,not that trajectories are identical. If B0 repeats its historical all-PASS outcome,smaller lateral/heading margins alone cannot become gate-level improvement. This is a conservative candidate choice for Owner review;it must not be changed after acquisition. No outcome,statistical significance or generalization is inferred now.

## Nonphysical evidence and limits

13 targeted pure/fake tests PASS:gate classification,common-clock alignment,unconfirmed-entry rejection,checkpoint/protocol pins,deterministic fake actor and forbidden optimization calls,invalid actions,and exact normalized heading equivalence. Earlier preparation tests/proposals are retained. Source/model/installed dependency/checkpoint preflight passed without importing Torch/MuJoCo. Sentinel independently reviewed exact source delta,candidate identities,design and receipts. Unchanged historical audits/killproof were reused,not rerun.

The CLI operator flag is only an accidental-launch guard in this trusted research workflow. It does not prove Human Principal Authority or authorize physics. No approval receipt exists. Before any real acquisition,Owner must send a separate explicit confirmation of this exact protocol/readiness/three-group budget. Main must archive that message and use the outer supervised entry;direct worker execution is outside the approved workflow. This is not a production authority or concurrency guarantee.

The preparation archive contains only new code-identity/test/proposal receipts;it does not contain invented physical trajectories or duplicate checkpoint/model binaries. Use `verify_preparation.py` for standard-library archive/hash verification,not execution. A later approved task must collect and independently audit the real three-group data. Draft PR only,no merge;stop awaiting Owner confirmation.
