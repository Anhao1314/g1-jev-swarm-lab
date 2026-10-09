# T0 Experiment and Data-Isolation Protocol

## Research question and stopping condition

Question: can a bounded command-layer yaw residual improve disturbance adaptation, path tracking, or long-task execution over the already strong Phase 1.3 deterministic controller without damaging its physical/task behavior?

The null outcome is valid: the best learned residual may be zero, seed-dependent, worse than a deterministic retune, or unable to overcome the documented authority/reference limitations. T0 stops after source-backed design, side-effect-free contract checks, independent review, and delivery. It does not acquire a new physical transition.

## Immutable comparators

| ID | Treatment | Role |
| --- | --- | --- |
| B0 | Frozen Phase 1.3 `heading_lateral`, gains 1.5/1.0, total yaw ±0.6 | Primary strong scientific baseline |
| B1 | New wrapper with residual identically zero | Engineering equivalence control; must match B0 step-for-step before learning |
| C | B0 plus PPO yaw residual ±0.12, walk-only | Candidate treatment |
| D | Deterministic retune with the same data/authority budget | Later comparator required before claiming learning-specific value |

Historical Phase 3A three-axis residual results provide seen negative/context evidence only. They are not a new comparator run and are never an unseen set.

## Isolation model

1. **Historical seen/regression.** All Phase 1, Phase 1.3, and Phase 3A cases/results. They may test interfaces and reproduce known behavior, but cannot support fresh generalization.
2. **T1 smoke-train.** One predeclared historical seen case. It exists only to check environment, optimizer, checkpoint, reload, and evidence plumbing. No efficacy conclusion is allowed.
3. **Formal train.** Not authored in T0. Before any formal acquisition, freeze the generator, parameter cells, disturbance schedule, simulator/policy identities, and train seeds in a new manifest.
4. **Validation.** Independently authored after environment/reward freeze. It may guide a separately declared development revision, but any inspected set then becomes seen development data. The T1 smoke does not access it.
5. **Unseen test.** Sealed by an independent manifest and accessed once only after fixed checkpoint lock and Owner authorization. No normalization fitting, early stopping, reward tuning, threshold setting, or checkpoint selection may read it.

M2.6A cases, manifests, states, results, and unseen status are explicitly forbidden inputs. Split membership is by full scenario content/hash, not just case name, so renaming a duplicate cannot bypass isolation.

## Metrics

Primary paired metrics for a future formal experiment:

- frozen physical success and task success;
- nominal and strict envelope outcomes, reported separately;
- final and integrated absolute lateral error;
- final and integrated absolute heading error;
- recovery success and time under a predeclared disturbance;
- long-route final XY vector/norm and heading, without hiding component regressions.

Secondary diagnostics:

- completion simulation time and path ratio;
- residual RMS, total variation, observation clipping, and total-yaw saturation;
- peak tilt, minimum height, falls, non-finite/invalid count;
- controller reset count and base-policy identity;
- training return/loss/KL only as optimization diagnostics.

Training return never serves as the scientific primary outcome.

## Staged ablation plan

- Gate 0: B0 versus B1 exact zero-residual equivalence. Any mismatch blocks all training.
- Gate 1: B0/B1 versus C yaw-only residual on paired authorized cases. This is the minimum scientific comparison.
- Gate 2: compare C to deterministic retune D under the same authority/data budget. This tests whether learning adds value beyond another hand-designed yaw rule.
- Later-only: add `delta_vy`, joint observations, history stacking, recurrent residual, or broader skill masks one factor at a time under separate protocols. None belongs to T1 smoke.

## T1 smoke candidate — pending Owner approval

Purpose: pipeline and numerical-contract validation, not performance.

| Item | Frozen candidate |
| --- | --- |
| Device | CPU, one Torch thread |
| Environment count | 1 |
| Seed | 7 |
| Total high-level decisions | 256 at 10 Hz |
| PPO rollout | `n_steps=128`, `batch_size=64`, `n_epochs=2` |
| PPO core | learning rate 3e-4, gamma 0.99, GAE 0.95, clip 0.2, target KL 0.03 |
| Network | MLP `[32,32]` |
| Checkpoints | initial, decision 128, fixed final 256 |
| Selection | fixed final only; no validation/best-checkpoint selection |
| Watchdog | 600 wall-clock seconds |

This smaller budget is intentionally below the historical 512-decision smoke and far below the 8,192-decision pilots: one or two PPO updates are enough to prove that gradients/checkpoints/evidence exist, while any efficacy inference would be invalid. Stable-Baselines3 documents that rollout size is `n_steps*n_envs` and that `target_kl` may bound unexpectedly large updates: <https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html>.

T1 can report only:

- `PIPELINE_PASS` or `PIPELINE_FAIL`;
- `SAFETY_SMOKE_PASS` or `SAFETY_SMOKE_FAIL` for the bounded seen case;
- performance `NOT_PROVEN` in either case.

## Preconditions and immediate stops

Before T1:

- obtain separate Owner authorization for policy loading, MuJoCo stepping, and optimizer updates;
- restore/verify pinned policy and MJCF assets without changing frozen evidence;
- create an isolated locked environment for this worktree;
- freeze the smoke case and all source/config/split hashes;
- verify command ordering, velocity frame, reset count, environment API, and B0/B1 exact equivalence.

Stop immediately and retain partial evidence on:

- any B0/B1 command or physical mismatch;
- normalized action outside [-1,1], residual magnitude >0.12 rad/s, total yaw >0.6 rad/s, or authority outside Walk;
- fall or inherited safety violation during the smoke;
- non-finite observation/action/reward/loss/gradient/state;
- simulator/controller error, source/hash drift, or missing evidence write;
- checkpoint reload tensor/action mismatch;
- any validation, unseen, or M2.6A access;
- wall-clock watchdog expiry or external interruption.

No retry is permitted merely because an outcome is unfavorable. Infrastructure-invalid and policy/physical failures remain separate.

## Evidence package required from a future T1

- exact Git/config/policy/model/dependency/split identities;
- initial and fixed checkpoints with tensor and file hashes;
- optimizer update count, loss/KL/gradient diagnostics;
- every observation/action/deterministic/applied command and reward component;
- termination/truncation/invalid reason and partial-tail receipt;
- B0/B1 equivalence receipt;
- resource/device/thread settings and wall-clock watchdog outcome;
- explicit `NOT_PROVEN` performance label.

No T1 action in this document is authorized by T0 completion.
