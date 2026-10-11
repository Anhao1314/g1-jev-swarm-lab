# T1b First PPO Optimization Smoke

**PIPELINE_PASS / LEARNING_GAIN_NOT_PROVEN.** One new, authorized CPU campaign completed 256 real interactions and 8 optimizer updates. Checkpoint-128/256 contain changed parameters and Adam state; both reload exactly. This proves the bounded training pipeline works, not that PPO improves locomotion or generalizes.

## Source and intervention

The exact parent is PR #27 at `a076523eec7244c9d72cb48644e5e31a58e5145d`. Its failed T1 campaign, archived data and frozen commits remain intact. The only runtime change is the public Gymnasium info key `episode` → `case_episode`. Native physical rows and raw reset events still use `episode`.

Controller, reward, observation vector, action bounds, actor distribution, PPO settings, model, evaluator, thresholds and scenario are unchanged. Runner, auditor, watchdog, installed environment and assets were reused. No installation or download occurred.

- Execution HEAD: `dfe8e13ba91483b8fe972b1fd323cad20d1bce6f`.
- Readiness SHA256: `e80459cecd4e3a4a8279b30108514eeb00c690b6c4618a4c122a7ccbb6c4882d`.
- Source Manifest SHA256: `8a137510643eb0ba9328f25704cd16b6daf620b551ea28fde10db2c4626b5d13`.
- T0 configuration SHA256: `4eed6162aa272594a98456c65198c9de0f4a0233bc110d860547f72f77984b03`.
- Exclusive execution directory: `/home/g1rl/g1-rl/evidence/t1b-ppo-optimization-20261011/acquisition-once`.

The existing WSL ext4 source and venv use CPU Torch 2.14.1+cpu, MuJoCo 3.15.0, Gymnasium 1.4.0 and SB3 2.9.0. The freeze binds 171 source/asset files, 21,121 installed dependency files and 30 dependency versions. The 30-file official asset closure is unchanged; motion.pt SHA256 remains `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.

The scene is the same historical nominal 4m walk: no disturbance, speed 0.5m/s, horizon 24s, actual-start frame, seed 7. One CPU environment and one Torch intra/inter-op thread. Residual authority remains Walk-only yaw ±0.12rad/s, total yaw ±0.6rad/s. Historical scene content is seen evidence; this is not an unseen/M2.6A benchmark.

## Actual execution

| Stage | Native steps | Result |
|---|---:|---|
| B0 original Walk + Phase 1.3 | 4350 | Physical, nominal and strict PASS |
| B1 zero-residual wrapper | 4350 | Every native state/command/torque/reset/evaluator matches B0 exactly |
| SB3 environment checker | 550 | PASS; all steps budgeted |
| PPO training | 12799 | 256 decisions, 8 Adam updates, 4 epochs |
| Total | 22049 | Continuous reservations/completions; no fall, nonfinite value or bound violation |

Training wall time: **2.542756320s**. Worker physical-scope interval: **4.914633749s**. External supervisor interval, including setup and checks: **11.746982311s**. These remain below 600s training, 1800s overall and 60,000 native steps. Supervisor native exit code 0; no interruption. There was one acquisition claim and no retry.

| Decisions | Cumulative Adam updates | Cumulative epochs | Last minibatch loss | Mean value loss | Approx KL |
|---:|---:|---:|---:|---:|---:|
| 128 | 4 | 2 | 0.608843684 | 1.43983549 | 1.312932e-05 |
| 256 | 8 | 4 | 0.815577745 | 1.40936959 | 1.67861581e-05 |

The 8 Adam updates are 2 rollouts × 2 epochs × 2 minibatches, distinct from SB3's cumulative epoch counter of 4. All 13 parameter tensors change from 0→128→256. Adam has 13 parameter states with step values 4/8, finite and nonzero moments. Every optimizer step is logged; loss and KL are pipeline diagnostics, not scientific success thresholds.

| Checkpoint | Byte SHA256 |
|---:|---|
| 0 | `1b169cf6fdc2f703f4c38814b10b983820a289b60222ee55c801566e2606dec2` |
| 128 | `6f8d4eaedaf0b69520c8113b85b09125f3bedae9b15005a72f081a9b1a8e2e2c` |
| 256 | `cc383df4f9508d9db97f12043f483e4b8e7ae5ee7bf0d1de015197384ef486d2` |

Checkpoint-0 is untrained. The 128/256 snapshots are saved after their updates. Both trained snapshots reload with exact tensor equality. The frozen runner also checked final deterministic action equality at a fixed zero observation. The additional read-only audit performed no physics, official policy call, residual prediction or optimizer update. The final checkpoint is fixed; none was selected for favorable performance.

Training task terminals occur at decisions 87 and 174. The third episode is externally truncated at 256, not scored as task success/failure. SB3's subsequent automatic reset produces an initial observation but **zero extra native steps**. Initial states match and low-level memory resets occur once per declared episode. In-training successes do not constitute independent policy qualification: the actor samples actions and changes during the campaign, and no post-training paired performance evaluation was run.

## Verification and retained limits

Four targeted nonphysical tests pass: actual adapter metadata, Monitor episode summaries, external-cap behavior, and retention of the original collision regression. Unchanged prior tests and Linux descendant-kill proof were referenced instead of rerun. The clean-process identity check verified the new HEAD/Readiness, import root, source/asset bytes and full dependency bytes before physics. Sentinel approved the exact source delta before the single run.

The unchanged raw auditor passes 18/18 checks. Checkpoint audits pass. Sentinel independently recomputed counts, actions, reset/boundary behavior and parameter/Adam changes, then read the reload receipts. The only runtime stderr is the existing `torch.jit.load` FutureWarning, preserved without policy replacement. Original T1 TypeError, preparation failures, source identities and initial checkpoint remain in unchanged PR #27 history; this success does not replace them.

The compact observation does not establish a Markov state because the frozen lower-level controller is recurrent. One historical case and seed, 256 decisions, no unseen qualification, perturbation campaign or post-training efficacy comparison: **LEARNING_GAIN_NOT_PROVEN**. Scientific thresholds, historical results and Research Ops selection remain unchanged. No GPU training, ROS, hardware, Jev, M2.6A, reward/profile search, extra training or merge.

## Evidence and read-only reproduction

`RAW_MANIFEST.json` binds only new T1b raw bytes. It does not duplicate the T1 archive, assets or wheels. The full Readiness is in the archive; `FREEZE_RECEIPT.json` and `SOURCE_MANIFEST.json` provide direct review identities. The archive contains native/decision logs, all three checkpoints, stdout/stderr, freeze/preflight receipts, targeted tests, read-only audits and independent review.

`restore_and_audit.py` verifies archive/member hashes in a new directory and invokes the unchanged standard-library auditor without physics, policy or Torch imports. See `REPRODUCE.md`. The preserved read-only checkpoint inspection script and its receipt support further review. The execution entry must not be rerun using this spent authorization.

Research Ops records measured test, experiment, audit and closeout commands. Unmeasured reasoning, implementation and token costs remain unavailable; these timings are not evidence of efficiency gains. Stop after independent Draft PR publication.
