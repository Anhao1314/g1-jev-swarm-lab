# Phase3A reference ablation — global gain with local task regression

Date: 2026-10-07. Branch: `phase3a/transition-learning`.

**Verdict: GLOBAL_PRECISION_GAIN_WITH_LOCAL_TASK_REGRESSION.** Changing only the
walking correction reference strongly improves the12m/16m sequence global
precision. It also changes16m sequence task success from PASS to EXCESSIVE_DRIFT
under the unchanged actual-start envelope. The prospective training gate is
**FAIL**. No PPO training, reward/observation/budget change, historical evidence
edit, rescoring or Jev/Multi-Swarm experiment occurred.

## Intervention and frozen evidence

Historical anchor: `1088c725ed12842df9f54116ac1921be71f2a633`.
New acquisition freeze: `0338a19`. Protocol SHA:
`b1da0596037f8cea1d8879e2ebb1d911771a342354e0122ad0355a4c78c0b04f`.
Inherited case manifest SHA:
`c84cf2484d9cd6138d19828e09ad9fb7cb57467330c96e08ad8cbed853b0f55e`.
Official policy SHA:
`cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
189 historical pilot files and219 baseline source/asset pins are preserved.

Actual treatment uses actual node-start position and heading. Ideal treatment
uses the existing planned origin and commanded heading: only requested walking
distance advances the origin and only requested Turn angle advances heading.
Measured Stand/Turn/Stop motion does not redefine this intended path. Full
origin+heading is one categorical reference treatment; this experiment cannot
separately attribute its effect to heading or origin.

Only the frame passed into frozen walking PathCorrectionPolicy changes. Gains
1.5/1.0, yaw clamp0.6, deadband0.01, PD, official recurrent locomotion, physics,
skill bodies, resets, Turn settle and completion semantics remain identical.
Residual is off. The old actual frame remains the input to local metrics,
observations/reward and task envelopes. New control-frame diagnostics never
replace those measurements or decide task success.

Same26 prior evaluation cases:16transitions,8primitives,2sequences. Primary is
one pass per treatment (52records). A second predeclared pass (52records) is a
separate determinism check and never pooled. These cases are already seen:
this is a paired mechanism study, not fresh blind generalization. Legacy
evaluation_set strings are retained as identifiers, not an unseen-data claim.

## Reliability and preservation

| Primary set | Actual task / physical | Ideal task / physical |
| --- | --- | --- |
| Transitions16 | 16/16 /16/16 | 16/16 /16/16 |
| Primitives8 | 8/8 /8/8 | 8/8 /8/8 |
| Sequences2 | 2/2 /2/2 | 1/2 /2/2 |
| Overall26 | 26/26 /26/26 | 25/26 /26/26 |

All52 actual historical replay comparisons and52 annotated repeatability
comparisons match exactly, excluding only wall/provenance metadata. All eight
primitive physical records per repeat match across treatments. No falls or
saturation occur. Primary peak tilt7.1831→7.1858° and minimum height
0.75862→0.75593m remain physically valid. Maximum correction yaw rises
0.13803→0.49817rad/s, still below0.6. Summed walking oscillation count is0→4;
this is a diagnostic change, not a new physical failure or retroactive gate.

## Sequence global precision

The table uses final absolute error; signed values remain in all original
per-sample results. Repeated results are identical.

| Sequence / metric | Actual | Ideal | Reduction |
| --- | ---: | ---: | ---: |
| 12m ideal lateral (m) | 0.132712 | 0.024781 | 81.3% |
| 12m ideal heading (°) | 2.246304 | 1.399892 | 37.7% |
| 12m endpoint norm (m) | 0.757700 | 0.539048 | 28.9% |
| 16m ideal lateral (m) | 1.840337 | 0.052999 | 97.1% |
| 16m ideal heading (°) | 6.348225 | 0.648108 | 89.8% |
| 16m endpoint norm (m) | 1.840972 | 0.144075 | 92.2% |

12m simulation time33.774→33.798s;16m53.772→53.990s. Gains are not explained by
a shortened sequence, different primitive, new target, faster task or hidden
failure exclusion. Endpoint norm is an additional report-only derivation from
the existing commanded endpoint, not a new task envelope.

Reference semantics therefore causally account for much of the observed global
error in these fixed deterministic sequences. This is not proof that the
initial Stand yaw alone explains every effect: origin alignment, Turn/Stop
translation, feedback and changed downstream entering states also contribute.

## Retained local failures and transition geometry

Ideal16m has two EXCESSIVE_DRIFT Walk nodes:

| Node index | Target | Actual local lateral | Ideal local lateral | Frozen limit |
| --- | --- | ---: | ---: | ---: |
| 1 | Walk8m | -0.001682m | +0.925791m | 0.56m |
| 3 | Walk4m | -0.023275m | -0.458098m | 0.35m |

These are valid old-envelope failures, not evaluator mistakes. Both arms finish
all skills and remain physical successes. Global correction can move outside
the corridor attached to the actual start direction. Ideal control-frame lateral
errors at these endpoints are near zero, but using them as the old gate would
silently change task semantics; that was not done.

Primitive and binary transition reliability are preserved, but transition
geometry is not uniformly improved:

| Four-case target means | Actual | Ideal |
| --- | ---: | ---: |
| turn→walk local lateral (m) | 0.007785 | 0.033411 |
| turn→walk local heading (°) | 0.398817 | 1.029283 |
| turn→walk ideal heading (°) | 0.652580 | 1.068314 |
| stand→walk local lateral (m) | 0.018168 | 0.168639 |
| stand→walk local heading (°) | 0.964576 | 4.886806 |
| stand→walk ideal heading (°) | 2.122411 | 1.903666 |

walk→turn and walk→stop cases have coincident first-Walk frames and retain their
physical outcomes. Nonwalking nominal commands and skill semantics stay
unchanged; their later trajectories in sequences can differ because preceding
walking states differ. This ablation does not establish a general improvement
in in-place Turn translation or every transition's global heading.

## Mechanism: reference versus local task contract

The16m initial10s Stand is identical in both treatments: position
`(0.112009,-0.185944)`m, yaw−5.367025°. Actual correction retains this start axis;
ideal correction brings the route toward the commanded axis. The first8m Walk's
local/global relationship is directly reconstructable:

`Y_end = Y_start + forward*sin(start_yaw) + local_lateral*cos(start_yaw)`.

At about8m forward progress, placing this first endpoint on idealY=0 requires
approximately0.9383m local lateral movement, beyond the frozen0.56m limit.
At that progress, the best idealY magnitude permitted by this corridor is about
0.3767m. The observed ideal endpoint is close to the ideal line and its local
corridor fails exactly as this geometry predicts. This is a specific first-node
reference/contract conflict, not proof that every alternative whole-route
controller is infeasible.

The second failure also includes measured turn translation and differing planned
versus actual origin. No “walking tolerance causes early stop” mechanism is
invented: the original skill's stop-distance behavior is preserved. This full
axis intervention cannot distinguish origin-only from heading-only causality.

## Training decision and single next factor

The prospective rule required both sequence lateral/heading gains **and** zero
physical/task regressions, primitive preservation and deterministic replication.
Global gain, physical, primitive and replication checks pass; the16m task
regression fails the conjunction. **Do not enter PPO training yet.** PPO cannot
be credited with solving this contract conflict merely by improving a differently
referenced reward, and reward/observation/budget were not changed here.

Next candidate factor only: **correction origin selection, with ideal heading
fixed**. Add an actual-origin/ideal-heading hybrid to compare with the retained
planned-origin/ideal-heading arm; keep actual/actual as the old gate anchor.
This decomposes the reference effect without adding a constraint controller or
tuning a projection against the observed16m failure. It does not promise PASS;
the first-node heading/corridor conflict may remain. No full2×2 interaction
claim, gain retuning, old-envelope revision or new PPO run is proposed here.

This next experiment is not implemented. Only after a declared residual-off
treatment meets the unchanged reliability constraints should a separate training
experiment revisit actual-frame versus ideal-frame residuals with the old reward,
observation, network, bounds, window and budget held fixed. Current cases remain
seen diagnostics; future generalization requires separate frozen evidence.

## Tests, audit and evidence completeness

Full suite **686 passed**,30 TorchScript deprecation warnings;21 new tests cover
frame selection/formula, actual replay, primitives, local gate preservation,
skill lifecycle, zero residual, unchanged case membership and invalid modes.
No source or protocol change followed acquisition freeze.

Independent checks: mechanism audit862/862 and results audit51,203 pass. They
reconstruct trace pose/reference/feedback math, signed yaw contributions,
clamping/deadband, per-physics counters, historical/primitive/repeat identities,
old envelopes,189 history and219 baseline pins. Passing evidence integrity does
not convert the failed training hypothesis into PASS.

All104 per-sample records and traces, manifest, completion, paired comparison
and primary summary are retained.109 exported files have raw and encoded SHA/
size receipts; large JSONL logs are losslessly gzipped. Original artifact trees
remain. Old Phase3A evidence is unchanged; Phase2.3 Runtime remains BLOCKED.

See `decision.json`, `evidence_manifest.json`, `mechanism_audit.json`,
`independent_results_audit.json` and `README.md`. This session stops after
publication; no next deterministic experiment, PPO, Jev or Multi-Swarm starts.
