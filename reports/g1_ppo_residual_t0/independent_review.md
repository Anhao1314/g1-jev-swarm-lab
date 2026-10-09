# Independent T0 Review — Sentinel

## Verdict

- T0 design: **`PASS`**
- T1 execution readiness: **`BLOCKED_PENDING_OWNER_AND_RUNTIME_READINESS`**
- PPO efficacy: **`INCONCLUSIVE / NOT_PROVEN`**
- Overall: **`PASS_T0_DESIGN__T1_BLOCKED_PENDING_OWNER_AND_RUNTIME_READINESS`**
- Draft PR: suitable as a design-only artifact. This is not authorization to merge or enter T1.

## Review scope

Sentinel performed a strictly read-only review of the candidate reports, YAML contract, pure contract code, tests, validation receipts, current diff, original controller/evaluator sources, and frozen-state records. Sentinel did not run tests, MuJoCo, policy inference, training, GPU work, installation, or network calls.

## Findings

### 1. Residual-control contract — PASS

- The original controller accepts `(vx, vy, yaw_rate)` while retaining the pretrained 12-DoF policy and PD loop: `src/g1swarm/control/g1_locomotion.py:125-192`.
- Phase 1.3 already changes only yaw at that boundary: `src/g1swarm/control/path_correction.py:104-137`.
- The candidate permits only one normalized yaw residual, preserves `vx/vy`, and retains the ±0.6 rad/s total corridor: `CONTRACT.md:17-31` and YAML `25-36`.
- Out-of-range actions and deterministic yaw outside the corridor fail closed rather than being silently clipped: `src/g1swarm/residual_rl/contract.py:75-86`.
- The near-boundary zero-residual counterexample is covered by `tests/test_residual_rl_contract.py:50-63`.
- Target attainment and frozen-envelope task success are separate concepts: `CONTRACT.md:80,104-110` and `contract.py:123-149`.

Real B0/B1 step-for-step physical equivalence remains correctly deferred as a mandatory pre-optimizer T1 gate.

### 2. Reward and termination design — PASS WITH RETAINED RISK

- `tilt_excess` has an exact degree-based formula, onset, scale, and clipping range: `CONTRACT.md:70-80` and YAML `70-98`.
- Reaching the target outside the frozen envelope terminates without being mislabeled task success: `CONTRACT.md:80,108` and YAML `89-110`.
- Reward remains subordinate to frozen physical, nominal, strict, and task evaluators: `CONTRACT.md:58-60,82-88`.
- Falls retain a materially larger penalty, while integrated/final route errors remain independent metrics.

Residual risk is scientific rather than a T0 defect: the reward weights are unvalidated, and PPO may improve return without improving every paired route metric. Frozen evaluators and the deterministic-retune comparator prevent training return from becoming the scientific verdict.

### 3. Data isolation and M2.6A protection — PASS

`PROTOCOL.md:20-28` and YAML `120-147` separate historical seen/regression evidence, one-case seen smoke, future formal training, independently authored validation, and sealed one-shot unseen testing.

M2.6A cases, manifests, state, results, and unseen status are forbidden inputs. Split identity is based on full scenario content/hash rather than names. Validation/unseen data cannot drive normalization, reward tuning, thresholds, early stopping, or checkpoint choice.

### 4. Frozen-baseline protection — PASS

- HEAD remained at requested anchor `4e2a51bf143cafea5eb90e89a88e1f04c156c9c8` during review; `origin/main` matched and the older local `main` was not substituted.
- All reviewed changes are new T0 files. No existing controller, evaluator, frozen protocol, historical result, or M2.6A artifact changed.
- Sentinel independently recomputed all six source hashes listed in `CAPABILITY_MAP.md:49-56`; each matched.
- Phase 3A.5 remains `PAUSED`; the retained residual-authority verdict remains `INCONCLUSIVE`.

### 5. Reproducibility and controls — PASS FOR T0; BLOCKED FOR EXECUTION

The candidate specifies B0 frozen Phase 1.3, B1 exact zero-residual wrapper, C yaw-only PPO residual, D same-budget deterministic retune, paired metrics, staged ablations, fixed CPU/one-thread/one-seed 256-decision smoke, two 128-step rollouts, checkpoints at 0/128/256, fixed-final selection, a 600-second watchdog, explicit immediate stops, and partial-evidence retention: `PROTOCOL.md:9-18,30-115` and YAML `149-184`.

The smoke can establish only pipeline and bounded safety-smoke behavior. It cannot support efficacy, generalization, robustness, or superiority claims.

### 6. Non-physical validation and execution boundary — PASS

The retained receipt reports 23 tests passed, contract compilation passed, diff check passed, runtime import allowlist passed, no policy/MJCF asset in the worktree, and zero physics steps, policy loads, optimizer updates, checkpoint writes, and GPU calls: `validation.json:5-47` and `validation/final.log:1-19`.

Sentinel verified that final Research Ops raw-log hash `8bf1e9363ce40ea91c1183e08908b1c720b0e81ba21d59a1a1c4b24a84eed5e3` matches the retained raw receipt. Sentinel did not independently rerun tests.

## T1 blockers

1. Separate Owner authorization for policy loading, MuJoCo stepping, and optimizer updates.
2. Restore and hash-verify pinned `motion.pt` and G1 MJCF assets.
3. Create an isolated, locked dependency environment.
4. Implement the Gymnasium environment without changing frozen controllers/evaluators.
5. Freeze smoke case and all source/config/split identities.
6. Verify wrapper ordering, mission-frame velocity semantics, controller reset count, Gymnasium API behavior, and watchdog enforcement.
7. Pass exact B0/B1 command and physical equivalence before optimizer construction.
8. Keep validation, unseen, and M2.6A unavailable to the smoke.
9. Stop and retain partial evidence on any authority, finite-value, safety, checkpoint-reload, provenance, or equivalence violation.

## Remaining non-blocking risks

- Low-level recurrent hidden state is unobserved; Markov completeness is not established.
- Yaw-only authority may be insufficient for lateral slip, strong pushes, recovery, or long-horizon drift.
- Full-walk residual authority is a new proposal, not inherited evidence.
- Reward coefficients and terminal bonuses remain candidate choices until authorized physical evaluation.
- One seed and one historical seen case cannot measure learned benefit.
- Formal train, validation, and unseen manifests remain intentionally unauthored.
- Checkpoint timing relative to PPO rollout updates and process-level watchdog behavior must be pinned during implementation.

## Draft PR disposition

**Approved for a Draft PR as a T0 design-only artifact.**

This approval covers the research specification, pure contract skeleton, non-physical checks, and bounded T1 proposal. It does not approve training, physics acquisition, policy loading, GPU execution, result adoption, merge, or any claim that PPO outperforms the deterministic controller.

`NO_TRAINING_PERFORMED`
