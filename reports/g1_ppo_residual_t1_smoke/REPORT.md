# T1 First Real PPO Smoke ¡ª retained technical block

**T1_BLOCKED_WITH_EXACT_EVIDENCE.** The independent Linux CPU environment and real G1 environment path work, and B0/B1 are exactly equivalent. The first PPO rollout completed128 real decisions, then an SB3 metadata namespace collision stopped the single authorized attempt **before any optimizer update**. No experimental retry or source repair was performed after that stop. This is not PPO efficacy evidence and not a completed smoke-training pipeline.

## Fixed identities and actual execution

- T0 parent: `e1ddd31978779365634989684579587668a56e7d`.
- Executed source: `0f41e0cd53aa52117da785f1d278d62650c9382f`; preparation-only parent `356b263320dbfb9f40ed85b0b652cfbdcf7d6a31` was never executed physically.
- Final freeze SHA256: `fdbfeea34fbe76e9bbdb52722dd957e6f56ca5c6f13b8904f30f5336ff5e71b9`.
- Source/assets:168 files; installed dependency bytes:21121 files;30 wheel dependencies. Official model closure30 files /25326088 bytes, identical to retained M2.5A official asset manifest. motion.pt SHA `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
- `G1-RL-Ubuntu`, Ubuntu24.04.5/WSL2, Python3.12.3, ext4 repo `/home/g1rl/g1-rl/repo`, venv `/home/g1rl/g1-rl/venvs/rl`.
- CPU Torch2.14.1+cpu, MuJoCo3.15.0, Gymnasium1.4.0, SB3 2.9.0;one environment;Torch intra/inter-op threads1. Full wheel URLs/hashes and transitive versions in sealed locks; no CUDA Toolkit, Linux GPU driver or ROS installation.
- Seen scenario content: historical `heading_lateral-4m-final-seed000` in `experiments/baselines/g1_closed_loop_correction_001/correction_comparison.json`; nominal4m/no disturbance/speed.5/horizon24. Seed7 is this prospective smoke seed, not a historical seed7 reproduction or unseen benchmark.

| Stage | Native steps | Actual result |
|---|---:|---|
| B0 frozen WalkForwardSkill + Phase1.3 |4350|physical/nominal/strict PASS|
| B1 exact zero residual Gym wrapper |4350|every native row + evaluator identical to B0, tolerance0|
| SB3 check_env |550|PASS, fully budgeted real steps|
| PPO rollout |6400|128 interactions, then technical exception|
| Total |15650|all reservations/completions continuous;no fall/nonfinite/bound breach|

Checkpoint0 SHA256: `8842a04b49397d2f96535f76c5a6d4d623a634f74dd8fb00af512f8941d5feb9`. This is an **untrained initial actor**, optimizer state empty. No checkpoint128/256. Optimizer updates0;training loss/KL **NOT_AVAILABLE**. One train episode reached original task success during collection; this says nothing about learning or superiority.

Supervisor native exit1;elapsed6.479393397s, no watchdog interruption. Measured worker physical interval3.782094181s. Exact failed-training interval was not separately saved;supervisor6.479s is a strict upper bound,below600s. 15650<60000native budget;total<1800s. No outcome was replaced by a favorable rerun.

## First actual blocker and shortest next repair

`G1YawResidualEnv.observation()` emits `info["episode"]` as an integer. SB3 reserves this key for Monitor's episode-summary dictionary. SB3 `_update_info_buffer` appends the integer, and `dump_logs` evaluates `len(integer)` before the first `train()` call, yielding `TypeError: object of type 'int' has no len()`.

Nonphysical regression reproduces that exact failure using info ingestion only; it does not call learn,env.step or optimizer.step. A future rename of the adapter's public info key to `case_episode` avoids the reserved-buffer collision in that ingestion check. **This repair is proposed, not applied to the executed/frozen adapter, and does not prove a completed training run.** The shortest next step is that one namespace fix,focused nonphysical checks,a new source freeze and a separately authorized single smoke attempt. No new environment platform or controller/reward tuning is required.

## Verification and retained failures

The earlier25-test run is retained;the later complete26-test suite (sealed `research-ops/g1-t1-ppo-smoke-1791714133032755428.log`,26 passed in2.04s) PASS (including action bounds,zero command/reset surface,nonphysical checkpoint roundtrip and Linux child/descendant termination); final checkpoint-only test1 PASS is a narrow recheck after serialization exclusion,not an additional unique test. Clean-process preflight verifies correct HEAD/freeze/source/assets/installed dependency bytes;wrong readiness/HEAD/source hash/dependency rejected without Torch/MuJoCo imports.19 post-run raw integrity checks PASS;independent Sentinel re-counted native/actions/evaluations and inspected checkpoint metadata/tensors.

The initial wheel resolver failure (setuptools68.1.2 vs Torch>=77.0.3),new-clone ownership copy failure before any asset copy,and preparation-only freeze remain retained separately. Setuptools was corrected to77.0.3 before physics. The earlier shell status-wrapper warning is retained as a preparation issue;actual pytest native success is separately recorded. Historical GPG/APT failures remain in their original evidence directories;APT full update0/39.839s was reused,never rerun. All new raw records and exact failure traceback are sealed, not overwritten.

Research Ops context38/38 was read;selection pointer unchanged. Command telemetry includes26-test suite2.8499s,singlecampaign6.5057s,nonphysical fault regression2.1833s,raw audit0.4028s. These are measured commands,not end-to-end efficiency gains. An initial Git closeout flagged CRLF line endings as trailing whitespace;the frozen bytes are preserved,with subsequent Git whitespace review explicitly accepting CR-at-EOL while retaining ordinary whitespace checks. Reasoning/implementation durations and token usage are NOT_MEASURED;no savings claim.

## Evidence and read-only reproduction

`RAW_MANIFEST.json` binds every archived byte;`raw-evidence.tar.gz` contains reservations/completions,decision/reward/observation logs,raw stdout/stderr,all preparation failures,freeze/dependency locks,killproof,test/preflight/audit receipts and checkpoint0. No official model binary is committed. `restore_and_audit.py` verifies archive hash and every restored file then invokes `audit_partial.py` without physics,Torch or policy imports. See `REPRODUCE.md` for commands. The prospective success auditor is not used to relabel this partial campaign.

## Boundaries

The T0 contract,Phase1.3 source/evaluators,all historical thresholds/results and Research Ops selection remain unchanged. Windows T0 and PR26 worktrees are protected;FlowCredit-Student is not modified or restarted. Existing global WSL shared swap can change through normal resource behavior previously accepted by Owner.

No additional physics after the exception,no experimental retry,no optimizer update,no GPU computation,hardware,Jev,ROS,unseen/M2.6A,reward/PPO profile search or production authorization. Import PASS and real control equivalence are not training success. Stop at the retained technical blocker with independent Draft PR;no merge or next-stage execution.
