# M2.6A — Unseen-State Halt/Hold Qualification: candidate design

**Design verdict: READY_FOR_INDEPENDENT_DESIGN_REVIEW. Acquisition verdict: NOT_READY_FOR_PHYSICS_ACQUISITION. Scientific result: UNMEASURED.**

This is a prospective design, not a qualification result or permission to run. The accepted baseline is `main@4e2a51bf143cafea5eb90e89a88e1f04c156c9c8`. M2.4 remains **INCONCLUSIVE**. M2.5A remains **PASS_BOUNDED_POST_HALT_HOLD_IN_TWO_SEEN_SEED0_STATES_WITH_NORMAL_STOP_CONTROL**. No historical result, controller, policy, reference, task threshold or Research Ops selection pointer changes.

## Question and evidence basis

Does the unchanged strict-failure → configured physical Halt → continuous 2 s zero-command Hold chain qualify in two predefined, physically distinguishable disturbance conditions that have not been measured under this protocol?

M2.4 showed incomplete failure-trigger coverage: the historical world +Y 60 N, 0.2 s push during the first Walk improved its endpoint enough to pass the strict gate. It therefore exercised **NO_HALT_TRIGGER**, not an unsuccessful Halt. The retained pre-push traces match the unpushed control for 500 native post-step rows. The first difference follows the force interval beginning at 1.0 s. The observed cancellation of pre-existing negative drift motivates testing the opposite direction; it does not establish linear causal additivity. A fixed later onset at 4.0 s distinguishes the initial transient from a period of established negative heading projection. At 4 s the unpushed lateral position was approximately −0.067600 m. Neither onset nor severity is selected by new outcomes.

M2.5A's two seen failure entries passed only a bounded Hold. Their maximum 1 s rolling means were 0.099604883988 and 0.099437390849 m/s, leaving margins of about 0.000395116 and 0.000562609 m/s. Instantaneous speed reached about 0.144113 and 0.145732 m/s; cumulative Hold paths were about 0.135574 and 0.136287 m. These are moving, marginally qualified states, not stationary or production-safe states. The historical first Halt window crossings (671 and 658 Stop steps) and the later maximum Hold margins are different measurements.

[`evidence_basis.json`](evidence_basis.json) binds these facts to retained metrics. [`source_binding.json`](source_binding.json) binds 30 accepted-main source/report files by **Git blob SHA-256**. [`history_inventory.json`](history_inventory.json) inventories 35 tracked metadata files and nine explicit push specifications, forming three unique profiles. It found no exact −Y/1 s, −Y/4 s or +Y/4 s condition under the same parent protocol within that inventory. This is a scoped metadata inventory, not a project-wide raw-state novelty proof or proof that no unarchived experiment exists.

## Fixed matrix and hypothesis

All six cells run once, sequentially, in this order. Challenges use the existing open-loop Walk6 → Turn45 → Stop Oracle Mission. The normal control uses the existing Walk4 → Turn45 → Stop Mission. Seed 0 is bookkeeping; different labels or repeated initializations do not create independent samples.

| Order | Cell | World-frame pelvis pulse in first Walk | Role |
| --- | --- | --- | --- |
| 1 | `seen_no_push_anchor` | None | Seen failure/Halt/Hold reproduction and integrity anchor |
| 2 | `unseen_minus_y_early` | (0, −60, 0) N, 1.0–1.2 s | Required primary new condition |
| 3 | `unseen_minus_y_late` | (0, −60, 0) N, 4.0–4.2 s | Required primary new condition |
| 4 | `unseen_plus_y_late_partner` | (0, +60, 0) N, 4.0–4.2 s | Fixed direction/timing partner, secondary coverage |
| 5 | `seen_plus_y_early_control` | (0, +60, 0) N, 1.0–1.2 s | Seen no-trigger control |
| 6 | `normal_stop_control` | None | Ordinary Stop/Hold measurement control, separate denominator |

The prospective hypothesis is bounded: **both required primary conditions** reach an actual strict-failure Halt request, satisfy the unchanged Halt and Hold contracts, and provide operationally distinct physical states at request and Hold entry. The secondary partner cannot replace a missing or aliased primary. It may reveal a timing interaction or remain a no-trigger condition; neither is assumed. No successful-sample selection, additional seed, force, timing or state may be added after outcomes.

## State construction and actual independence

Each cell starts one fresh unchanged session. Existing disturbance machinery applies only the scheduled world-frame pelvis force. There is no teleport, qpos/qvel injection, reference search or reset after initialization. Within each cell, the parent, Halt and Hold use the same simulator, controller and policy objects continuously. No new mission or task node is dispatched during Hold.

Construction novelty alone is insufficient. Offline comparisons use the raw state at **Halt request/Stop entry** and **first qualifying terminal state before Hold** against all three saved M2.5A references, applicable same-campaign controls, and the other primary. Global XY translation, absolute yaw, time, seed, object IDs and controller-counter/action differences alone do not qualify as new physical-state coverage.

A primary must differ from **every reference and the other primary at both checkpoints**, by at least one of these predeclared resolutions:

| Feature | Minimum difference |
| --- | --- |
| Joint-position RMS | 0.02 rad |
| Joint-velocity RMS | 0.1 rad/s |
| Yaw-aligned base linear-velocity L2 | 0.02 m/s |
| Body gravity-direction angle | 1 degree |
| Base height | 0.01 m |
| Raw freejoint rotational-speed norm | 0.1 rad/s |

The helper removes global XY/yaw using the recorded quaternion and world linear velocity. It does not assert an unverified frame for raw angular qvel; only its norm is used. These are transparent **prospective coverage resolutions**, not changes to any physical success threshold, validated distances between latent policy states, or an IID/generalization criterion. Report every continuous pairwise delta. Missing/nonfinite fields make novelty unavailable. Policy recurrent bytes are not directly archived: same objects/no reset witnesses do not prove hidden-state equality or independence.

The controller may converge to an already seen state before Hold. Such aliasing is a meaningful coverage limitation. Execute the fixed Hold when physically eligible regardless of novelty; retain its score, mark insufficient distinctness, and do not replace the cell.

## Three independent evaluation layers

1. **Failure-trigger coverage.** Preserve original Walk, nominal/physical and strict endpoint outcomes. The current runtime requests Halt only after Walk skill success, physical success and strict endpoint failure cause `STOP_DEPENDENTS`. Strict PASS follows the unchanged remaining parent graph; do not manufacture a failure Halt or append a challenge Hold. A Walk TIMEOUT/fall currently does not route through this strict gate: retain `PARENT_SKILL_OR_PHYSICAL_FAILURE_NO_HALT_NO_HOLD`, including remaining motion, and do not silently fix triggering. Ending the simulator episode does not prove physical termination. A missing Halt on an actual strict-trigger branch is integrity failure.
2. **Halt qualification.** Apply the existing explicitly configured experimental physical-termination path. StopSkill returns at the **first full 500-post-step speed mean ≤0.1 m/s**; unchanged Runtime acceptance checks that same state and may still classify `HALT_FAILED`. Retain the original ≤4 s, final instantaneous/mean ≤0.1 m/s, net planar displacement ≤0.5 m, finite/standing/no-fall and StopSUCCESS requirements. Do not extend Stop, redispatch it or wait for a better crossing. Failed Halt is a physical negative and is not Hold-eligible.
3. **Hold qualification.** After `HALT_SUCCEEDED`, verify force clearance and exact terminal/pre-first-step continuity. Continue the same torque helper with zero velocity command for exactly 1,000 native steps/2 s, without reset, Stop redispatch or task dispatch. Seed the rolling window from exactly the final 500 qualifying Stop **post-step** speeds; evaluate all 1,000 ensuing means ≤0.1 m/s. Final instantaneous speed must be ≤0.1 m/s, sampled XY path ≤0.2 m, with finite/standing/no-fall throughout. These are verbatim M2.5A criteria. Instantaneous intermediate peaks, net displacement and posture margins remain descriptive. A speed/path breach stays in the fixed window; fall, nonfinite, non-standing or simulation fault terminates the cell with raw partial evidence and the appropriate physical/technical classification.

Report planned cells, valid cells, actual Halt requests, Halt successes, continuity/force-clear Hold eligibility, complete Hold windows and normal-control windows separately. No trigger is N/A, not Halt failure or success. A zero denominator is N/A, never 0% or PASS. Normal Stop must never enter the failure-Halt denominator.

## Pairing, continuity and independent evidence

Compare all pre-pulse rows, not just endpoints: the early ± pair must match the no-push anchor for the first 500 native post-step rows; the late ± pair for the first 2,000. Bind time, qpos, qvel, ctrl, applied force, controller action/target/counter. Match the seen no-push parent/Halt/Hold, +Y early parent, and normal control against their frozen historical physical/control records, excluding only identifiers/source metadata. A reproducibility mismatch is retained and stops the campaign; it is not evidence of a new successful state.

The future adapter must journal actual pre-step force/body/timing, activation, clearance at Walk exit and before Halt/Hold. A full pulse is 100 native intervals: early indices 500–599 and late 2000–2099, with corresponding post-step rows 501–600 and 2001–2100. Natural termination before pulse completion is truncated exposure, not a fabricated full dose. Clear applied forces on every exit, including exceptions, before any eligible Halt/Hold. Preserve abrupt physical failure and missing coverage separately.

Archive full native pre/post qpos/qvel, ctrl/force, commands, controller action/target/counter, reset/dispatch/object witnesses, RobotState/skill/strict outcomes, first-crossing window, all Hold rows, wall/native-step journals, warnings, logs and partial records. Bind source commit, executable bytes, dependencies, model/policy assets, protocol, raw members and reports. An independent read-only auditor must restore the archive in a clean directory and recompute force exposure, prefixes, all three layers, novelty deltas, budgets and continuity from raw records. It must preserve NaN/nonfinite and technical interruption rather than drop bad rows. No new-mission trajectory is Halt/Hold evidence.

The old 78 Git-byte matches, 85 frozen CRLF execution conversions and 91 official assets remain distinct historical provenance domains. This design's accepted-main Git bindings are not a target-environment readiness manifest. The inventory preserves checkout hashes and adds separate baseline Git hashes; eight of its 35 files differ only in byte domain. Future execution requires its own full source/dependency/asset closure and byte freeze.

## Budget, stopping and interpretation

Maximum **6 cells ×1 attempt ×30,000 native steps**, total **180,000 steps**; **120 wall seconds per cell**, **720 seconds total**. Native timestep remains 0.002 s. Budgets include parent execution, Turn/settle, Halt and Hold. Conservative bounds are 50.5 simulated seconds/25,250 steps for an untriggered complete challenge graph, 42 s/21,000 steps for Walk timeout bound plus Halt/Hold, and 40.5 s/20,250 steps for the normal parent plus Hold. External process/campaign guards and raw journals are mandatory. No unbounded subscriber/viewer is an acquisition dependency.

Valid scientific failure continues to the next fixed cell. Source, reset, routing, force, budget or integrity violations stop the whole campaign with partial evidence. Technical interruption or missing required evidence also stops it; remaining cells are `NOT_RUN`, not failures. A valid counterexample already observed remains a counterexample even if later cells are technically censored. No retry, replacement or optional success-driven expansion.

`BOUNDED_PRIMARY_PAIR_SUPPORTED` requires complete valid classification of all six cells, control reproduction, both primary chains passing with demonstrated distinctness at both checkpoints and from each other, and passing Halt/Hold for every secondary condition that actually requests Halt. A secondary strict PASS/no-trigger limits only its Halt/Hold coverage. A valid distinct requested-Halt failure or eligible-Hold failure is a `BOUNDED_UNSEEN_COUNTEREXAMPLE`. Condition-new but state-aliased physical failure is retained as a condition-level negative, not an unseen-state counterexample. Unsupported routing, missing primary triggers, aliasing or technical censoring yield `INCONCLUSIVE_COVERAGE_OR_TECHNICAL`. Report scientific signal and completion independently.

This is a prospective small deterministic mechanism test, not broad robustness, unseen-seed generalization, stationary safety, production authorization or hardware qualification. TEST_ONLY trusted serial configuration has no concurrent atomicity or Human Principal Authority guarantee. Jev, Language Runtime/D011 and other scientific blockers remain unchanged.

## Reproduction and next gate

From the repository root, with the existing repository-local Python environment (or the same pinned test dependencies), run:

```text
python experiments/m2/unseen_halt_hold_design_001/check_design.py
python -m pytest experiments/m2/unseen_halt_hold_design_001/test_design.py -q
```

These are nonphysical source/synthetic contract checks, not MuJoCo runs or a production scorer. The checker deliberately rejects simulator/policy runtime imports. The initial design-test failure and corrected 27/27 receipt are retained in `logs/` and bound by `verification.json`. Independent review, candidate hashes and Research Ops boundaries accompany this design.

**Recommendation:** proceed to independent design review, then a separately scoped experiment-only adapter/readiness phase if approved. The old M2.5A acquisition adapter hardcodes three seen cells and historical-prefix checks and cannot be invoked unchanged. Required remaining gates are reviewed design, frozen raw-data scorer/adapter, noninterfering observer and force/exception tests, complete target source/model/dependency preflight, immutable execution HEAD/readiness SHA, and separate Owner physics authorization. None is replaced by this Draft PR or its synthetic checks. Stop here; no acquisition is authorized.
