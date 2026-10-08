# Phase 3A pilot — real transition learning, no consistent learned gain

Date: 2026-10-07. Branch: `phase3a/transition-learning`.

**Verdict: PIPELINE_VALID_NO_CONSISTENT_LEARNED_GAIN.** A real, reproducible
MuJoCo→PPO→checkpoint→held-out replay loop completed. The learned treatment
preserved the tested primitive abilities and physical/task reliability, but did
not consistently reduce transition or long-sequence error across the two seeds.
This negative learning result is retained; no post-evaluation tuning occurred.
Phase 2.3 language Runtime remains BLOCKED. Jev/Multi-Swarm were not introduced.

## Frozen foundation and treatments

The branch starts at the Session4 audit `624c802`. Acquisition pipeline/protocol
was committed as `3b655ba`; subsequent `4f2ce5f` only corrected Git whitespace
handling for exact CRLF evidence. Scientific source hashes did not change.

| Pin | Value |
| --- | --- |
| Official motion.pt | `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d` |
| Phase1.3 protocol | `ca99d60b1f8576682c1fa02a3c7e7b92018b6376a9a418dbd59324cb090f3661` |
| Phase3A pilot protocol | `d27a92c59f6496a796208dd4b5d8b91ea2a2b98f793a3fc28bba9e3a229663df` |
| Case manifest | `c84cf2484d9cd6138d19828e09ad9fb7cb57467330c96e08ad8cbed853b0f55e` |
| Baseline freeze manifest | `5c2d13fdf83512ecba7f3ba8126fc45a542f725ae115098d3c587a0c4c96ec04` |

219 pinned files bind existing sources, robot/control/experiment configuration,
historical baseline evidence and official XML/mesh/policy assets. Original
50Hz recurrent locomotion, 500Hz physics, PD gains, action scaling, skill
contracts, reset/settle behavior and success envelopes were preserved.

Treatments: A `frozen_baseline` bypasses command correction; B
`deterministic_correction` uses frozen Phase1.3 heading+lateral correction on
walking only (1.5/1.0 gains, ±0.6 yaw,0.01 deadband); C adds PPO residual to B.
C can change vx/vy/yaw by at most0.10/0.06/0.12, at10Hz, during the first2s of
the four requested transitions. Primitive, other transition and outside-window
residual is exactly zero. Joint policy weights are never optimized.

The original SkillRouter and skill bodies execute continuously in MuJoCo; a
worker only pauses at residual decisions. Stand/Walk/Turn reset the official
recurrent policy as before; Stop does not. Turn retains its0.5s settle. The61
observations include proprioception, task identity, local/reference errors,
phase and previous action. The PPO actor is a64×64 MLP on CPU1thread.

## Split and genuine training evidence

Train12 cases cover all four transitions. Held-out16 use different distance,
angle and stand-duration combinations: train walks1/2m, turns30/60°, stands1–3s;
eval walks1.5/3m, turns45/75°, stands4–7s. Nominal simulator seeds do not
randomize physics, so no “unseen seed” evaluation claim is made. Eight primitive
cases and two mixed sequences with nominal walking totals12/16m are separate.
No evaluation-based checkpoint selection, reward rewrite or additional budget.

| Campaign | PPO decisions | Completed episodes | Rollout/loss receipts | SB3 epoch counter | Actual Adam steps |
| --- | ---: | ---: | ---: | ---: | ---: |
| Independent smoke seed7 | 512 | 19 | 1 | 5 | 40 |
| Pilot seed11 | 8192 | 317 | 16 | 80 | 640 |
| Pilot seed29 | 8192 | 317 | 16 | 80 | 640 |

Initial/intermediate/final tensor hashes differ as expected from optimization;
checkpoint file hashes, reload tensor equality and optimizer state steps were
independently checked. Smoke additionally reproduced the entire deterministic
physical episode after save/load. Each8192-step run took approximately230s.
All634 completed pilot episodes satisfied their training task/physical gates.
Each fixed-budget unfinished tail is retained as BUDGET_INTERRUPTED_NOT_SCORED.

Not all PPO decisions actuate a residual: seed11 had5706 active of8192, seed29
5740. The remaining decisions still record rewards/observations but commands are
masked to zero residual after2s. Twelve of the16 held-out target skills complete
after that window; only the four stop targets complete entirely inside it.

There are12 retained checkpoint ZIPs: two smoke and five per pilot seed
(initial,2048,4096,6144,fixed final). Per-step observations, requested actions,
actual command samples, rewards, terminal episodes, optimization diagnostics
and evaluation traces are retained. Training and held-out artifacts are separate.

## Frozen baseline replay and held-out outcomes

The four4m/8m raw/corrected baseline replays match historical forward/lateral/
heading/time doubles exactly. Original negative controls are retained.

| Treatment | Held-out transitions task/physical | Primitive task/physical | Sequence task/physical | Overall task/physical |
| --- | --- | --- | --- | --- |
| A raw baseline | 16/16 /16/16 | 7/8 /8/8 | 0/2 /2/2 | 23/26 /26/26 |
| B deterministic | 16/16 /16/16 | 8/8 /8/8 | 2/2 /2/2 | 26/26 /26/26 |
| C seed11 | 16/16 /16/16 | 8/8 /8/8 | 2/2 /2/2 | 26/26 /26/26 |
| C seed29 | 16/16 /16/16 | 8/8 /8/8 | 2/2 /2/2 | 26/26 /26/26 |

104 total evaluation records have complete membership. No falls occurred;
observed peak tilt was7.2853° and minimum height0.75219m. No primitive regression:
all16 learned-vs-B primitive physical records and824 command/state trace rows
are exactly equal, excluding wall-clock/provenance metadata. This is tested
gating protection, not evidence that PPO retrained primitive competence.

Both baseline transition arms were already16/16, so binary success had a ceiling.
Learned26/26 alone is not a gain over B. The following means use the **target
skill** of each four-case transition family, not the unchanged prefix:

| Transition / target metric | B | C11 | C29 | Interpretation |
| --- | ---: | ---: | ---: | --- |
| walk→turn absolute turn heading error (°) | 0.4944 | 0.6696 | 0.4307 | One seed improves, one worsens |
| walk→turn translation's local lateral component (m) | 0.05900 | 0.04674 | 0.06420 | Seed-dependent; not whole translation norm |
| walk→turn whole translation norm (m) | 0.40754 | 0.38432 | 0.52512 | Seed29 worsens28.9%; heading gain does not imply in-place precision |
| turn→walk absolute local heading error (°) | 0.3988 | 0.1146 | 0.5362 | Seed11 improves71%; seed29 worsens34% |
| turn→walk absolute lateral drift (m) | 0.00779 | 0.00884 | 0.00711 | Opposite tradeoff |
| walk→stop target completion (s) | 1.2640 | 1.2035 | 1.3725 | Seed11 faster4.8%; seed29 slower8.6% |
| walk→stop absolute lateral movement (m) | 0.02303 | 0.02184 | 0.02296 | Both smaller; about1.18mm/0.06mm, weak isolated benefit |
| stand→walk absolute lateral drift (m) | 0.01817 | 0.02257 | 0.02125 | Both worse24.2%/16.9% |
| stand→walk absolute local heading error (°) | 0.9646 | 0.9744 | 1.2144 | Both worse |

Continuous results contain some real measured, seed-specific improvements.
They do not establish a consistent residual benefit or select seed11 as “best”.
Neither model improves the full set of error/stability/time outcomes. Full
denominators and paired case deltas, including null recovery observations, are
in `summary.json` / `comparison.json` and raw per-sample receipts.

## Long-sequence precision and dominant mechanism

Local task envelopes are retained. They are **not** a global-route accuracy gate.
The ideal-path diagnostics below retain commanded turn headings and path origin,
so a new actual node frame does not wash out accumulated error:

| Nominal sequence | Treatment | Final ideal lateral error (m) | Final ideal heading error (°) |
| --- | --- | ---: | ---: |
| 12m | B | -0.1327 | -2.2463 |
| 12m | C11 | -0.0602 | -2.4450 |
| 12m | C29 | -0.2917 | -4.0057 |
| 16m | B | -1.8403 | -6.3482 |
| 16m | C11 | -1.8420 | -7.6465 |
| 16m | C29 | -2.1618 | -7.0614 |

No new ideal-path PASS/FAIL threshold is invented. All these sequences pass the
old local gates, yet neither learned seed improves16m global precision. Seed11's
12m lateral improvement accompanies worse heading; seed29 worsens both.

The16m sequence starts with10s Stand. Its identical output in all treatments
already has -0.18594m lateral movement and -5.36703° yaw before any residual can
act. The following walk correction locks its **actual** start heading, retaining
that offset; after2s the residual loses authority. This directly observed
reference/transition-semantics limitation is the strongest mechanism evidence.
It is not a newly discovered fall or a change to Phase1.3 straight-walk evidence.

Dominant attribution for the unmet global-error objective: **transition/reference
semantics**, with reward alignment and limited residual authority as contributors.
The reward penalizes local walk/turn errors and does not score the ideal route.
Its successful optimization cannot imply global-route improvement. Observation
aliasing from hidden recurrent state and insufficient policy/budget remain
possible explanations for seed variability, but this pilot does not isolate them.
No causal capacity, observation-only or reward-only diagnosis is claimed.

## Failure taxonomy, reward exploitation and negative findings

Hard frozen task failures: raw8m primitive and both raw sequences are
EXCESSIVE_DRIFT with physical success. B/C have no hard task or physical failure
on this limited held-out set. The research negative is mixed precision effects,
stand→walk drift regression and lack of consistent long-sequence improvement.

Completed-episode training return means, first50 vs last50, are10.309→10.776 for
seed11 and9.785→9.811 for seed29. Case composition differs, so these are descriptive,
not paired learning-gain estimates. Reward improvement is not held-out progress.
Slowing to exploit geometric reward was a declared concern; both models' walk
targets actually complete faster on average, so that specific exploit is not
supported. Seed29 stopping takes0.1085s longer, without timeout or task violation.
No observed reward-hacking proof is claimed; objective mismatch remains real.

There is also a concrete turning geometry tradeoff: seed29's mean active forward
residual during walk→turn is+0.07523m/s, and its full turn translation grows from
0.40754 to0.52512m while heading error slightly improves. The original turn gate
constrains heading and physical safety, not translation; the reward also lacks
a turn translation term. All-PASS therefore does not establish preserved in-place
turning geometry. This is retained as an objective/authority blind spot without
inventing a new failure label or asserting intentional reward exploitation.

The2s window and recovery diagnostic are distinguished: window duration is fixed,
target completion is measured, and sustained tracking recovery can be null.
The latter is a new diagnostic with declared0.15m/s,0.15rad/s,0.2s sustained criteria
and original standing state; it never replaces a historical task-success gate.

## Next experiment — one factor only, not implemented

Investigate **walking correction reference frame** in a new treatment: actual
node-start axis versus the already declared ideal commanded axis. Preserve A/B,
old reports, gains, policy, envelope and this pilot's negative outcome unchanged.
Keep residual bounds/window, observation, reward, network and budget fixed to
isolate the frame effect; include residual-off frame ablation to distinguish its
deterministic contribution from learning. First verify primitive equivalence and
per-step intended-axis behavior, then repeat training in a new experiment identity
with separately frozen evaluation data. Do not treat current held-out cases as
fresh blind evidence after this audit.

This proposal is not implemented here. Increasing budget or changing reward and
frame together would not answer the strongest current mechanism question.
Phase3A pilot stops here; no Jev, Multi-Swarm or language Runtime follows.

## Verification and evidence access

Full suite: **665 passed**,20 existing TorchScript deprecation warnings. Earlier
662-pass receipt predates final guard tests and is retained. Real integration
tests cover frozen-direct replay, all four zero-residual pairs, bounded/nonzero
actuation, primitive gating, finite Gym APIs, lifecycle and real drift failure.
Offline tests cover splits, metric pairing, checkpoint identity/tampering,
budget, manifest pins, refusals to overwrite, missing data and provenance.

Independent baseline audit689/689 and primitive audit70/70 pass. Training audit
checks actual Adam state, all decisions/rewards, checkpoints and source/case pins.
All219 baseline files and Phase2.3 evidence remain unchanged. No old output path
was reused. Exact-byte new manifests match their Git blobs. The inherited
Phase2.3 publication issue is not silently repaired by this independent branch.

`evidence_manifest.json` maps158 exported files to their original raw SHA/size.
Large JSONL files are losslessly gzipped, with encoded and decoded hashes;
all12 checkpoints are retained. Original local artifact trees also remain.
For methods/commands see `README.md`; for metrics `summary.json`, `comparison.json`,
`baseline_audit.json`, `primitive_regression_audit.json`,
`training_integrity_audit.json` and `failure_attribution.json`.
