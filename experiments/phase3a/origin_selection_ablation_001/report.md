# Phase3A origin selection — heading gain does not preserve the local corridor

Date: 2026-10-07. Branch: `phase3a/transition-learning`.

**Verdict: HYBRID_GLOBAL_GAIN_WITH_LOCAL_TASK_REGRESSION.** Actual origin plus
ideal heading improves12m/16m global lateral and heading errors. It removes the
full-ideal treatment's second4m local failure but retains the first8m failure.
The unchanged hybrid training gate is **FAIL**; no PPO was trained. Original
envelopes, labels, scores, cases, reward/observation/network and training budget
remain unchanged. This experiment stops after publication.

## Three arms and isolated factor

| Arm | Walking correction origin | Walking correction heading |
| --- | --- | --- |
| Historical anchor | Actual node-start | Actual node-start |
| Hybrid | Actual node-start | Ideal commanded |
| Retained full-ideal | Planned | Ideal commanded |

Hybrid/full isolates origin selection conditional on ideal heading. Hybrid/
historical supplies a heading contrast conditional on actual origin. This
three-arm triangle does not identify a full2×2 interaction or additive percentage
shares. Changes in downstream states are closed-loop effects of the rule.
Actual origin stays fixed at node start, not at each physics step.

Only the new selected frame enters the frozen walking correction. Locomotion,
PD, gains1.5/1.0, clamp0.6/deadband0.01, skill bodies/termination/resets/settle,
local actual-start measurements and success envelopes are retained. Both ideal
arms use exactly the same commanded heading recipe. Residual is off. The
previous training_hypothesis_gate is copied verbatim; only candidate identity
maps to hybrid. No new improvement or task threshold is introduced.

Historical source anchor `642dcc1`; acquisition freeze `9f5726d`.
Protocol SHA `f2b8fcaa50294efa0669bbd4724b8b9fe65349d1d0301ac4c91e7707703c0c9c`.
History manifest SHA `3f34ae8c76591eb2a99fc4022fc6f87427ce382fcf7f40a8672fe7db515d218e`.
Inherited reference protocol SHA `b1da0596037f8cea1d8879e2ebb1d911771a342354e0122ad0355a4c78c0b04f`.
Case SHA `c84cf2484d9cd6138d19828e09ad9fb7cb57467330c96e08ad8cbed853b0f55e`.
Official motion.pt SHA `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
314 historical files and219 baseline source/asset pins are preserved.

Same26 previously examined cases perarm. Primary78 records and a separate
predeclared78-run repeatability pass remain distinct. Repeats are determinism
checks, not independent samples. No fresh blind/generalization claim is made;
legacy evaluation_set strings retain their original identifiers only.

## Reliability and unchanged gates

| Primary outcome | Actual/actual | Hybrid | Full-ideal |
| --- | --- | --- | --- |
| Transition task / physical | 16/16 /16/16 | 16/16 /16/16 | 16/16 /16/16 |
| Primitive task / physical | 8/8 /8/8 | 8/8 /8/8 | 8/8 /8/8 |
| Sequence task / physical | 2/2 /2/2 | 1/2 /2/2 | 1/2 /2/2 |
| Overall task / physical | 26/26 /26/26 | 25/26 /26/26 | 25/26 /26/26 |

Both historical arms reproduce all104 retained-arm physical records across
the two passes. All78 repeats match; primitive physical records match in all
three arms. No falls or saturation occur. Peak tilt is7.1831/7.9052/7.1858°;
minimum height0.75862/0.74824/0.75593m. Hybrid physical reliability remains valid,
but these continuous stability extrema are not improvements over the anchor.
Maximum correction yaw0.13803/0.22233/0.49817rad/s; summed walking oscillations
0/0/4. No new physical-instability threshold is invented from these diagnostics.

## Sequence global precision

Final absolute errors; all signed values are retained. Results repeat exactly.

| Sequence / metric | Actual/actual | Hybrid | Full-ideal |
| --- | ---: | ---: | ---: |
| 12m ideal lateral (m) | 0.132712 | 0.058107 | 0.024781 |
| 12m ideal heading (°) | 2.246304 | 1.042817 | 1.399892 |
| 12m endpoint norm (m) | 0.757700 | 0.730519 | 0.539048 |
| 16m ideal lateral (m) | 1.840337 | 0.694057 | 0.052999 |
| 16m ideal heading (°) | 6.348225 | 0.255096 | 0.648108 |
| 16m endpoint norm (m) | 1.840972 | 0.991713 | 0.144075 |

Hybrid versus anchor reductions:12m lateral56.2%, heading53.6%, endpoint3.6%;
16m lateral62.3%, heading96.0%, endpoint46.1%. Simulation times12m
33.774/33.774/33.798s,16m53.772/54.032/53.990s. The improvement does not rely on
shortened cases or changed skill targets; endpoint is the retained diagnostic.

The heading contrast establishes that ideal heading alone, at actual origin,
accounts for a substantial angular improvement in these deterministic cases.
Planned origin supplies further position/lateral improvement conditional on
ideal heading, but final absolute heading gets worse than hybrid on both
sequences. Thus angular improvement is not equivalent to complete route precision,
and heading/origin are not universally beneficial or linearly separable.

## Local Walk failures and transition geometry

| 16m Walk node | Target | Actual lateral | Hybrid lateral | Full-ideal lateral | Frozen limit |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | 8m | -0.001682m | +0.743292m | +0.925791m | 0.56m |
| 3 | 4m | -0.023275m | +0.053852m | -0.458098m | 0.35m |
| 5 | 4m | -0.022144m | -0.039024m | +0.335481m | 0.35m |

Hybrid removes origin recentering's second-node failure, but not the first
EXCESSIVE_DRIFT. This is a real local contract regression under the original
measurement frame, not an evaluator error. All skills finish and stay upright.
Control-frame near-zero lateral error never replaces a failed local envelope.

Binary transition reliability is preserved, while geometry changes:

| Four-case target means | Actual/actual | Hybrid | Full-ideal |
| --- | ---: | ---: | ---: |
| turn→walk local lateral (m) | 0.007785 | 0.026875 | 0.033411 |
| turn→walk local heading (°) | 0.398817 | 0.573134 | 1.029283 |
| turn→walk ideal heading (°) | 0.652580 | 0.396549 | 1.068314 |
| stand→walk local lateral (m) | 0.018168 | 0.098502 | 0.168639 |
| stand→walk local heading (°) | 0.964576 | 4.005183 | 4.886806 |
| stand→walk ideal heading (°) | 2.122411 | 1.074550 | 1.903666 |

walk→turn/walk→stop retain coincident first-walk frames and unchanged physical
results. Nonwalking nominal commands, Turn/Stop semantics and original resets
are unchanged. Their downstream geometry can respond to changed prior walking
state; this does not establish improved in-place turning across all sequences.

## Why actual origin is insufficient

Both arms enter the first16m Walk from the identical10s Stand output:
position(0.112009,-0.185944)m and heading−5.367025°. At that first shared state,
ideal-heading contribution is+0.140508rad/s in both ideal arms. Full-ideal adds
the+0.185944rad/s origin-derived lateral term; hybrid adds zero. This is an
isolated first-state input contrast, not a fixed contribution to later outcomes.

Hybrid's desired control line passes through the actual start but points along
ideal heading. Exact tracking at8m actual-frame forward progress would require:

`local_lateral = forward * tan(ideal_heading - actual_start_heading)`

which is approximately0.7516m, exceeding0.56m. Observed0.7433m agrees with this
geometry; the small difference is residual parallel-line tracking error.
Preserving a frame's origin does not preserve its orientation-dependent corridor.
The remaining conflict is **ideal heading versus the old actual-heading local
contract**, even when origin recentering is removed.

This argument is scoped to that first node at the declared progress/heading.
It is not proof that every whole-route controller or partial alignment is
infeasible. No task metric is reoriented, no tolerance is relaxed and no outcome
is relabeled to erase the conflict. Reward/capacity explanations are not needed
to establish this residual-off geometry problem.

## Decision and next single factor

Global-gain, physical, primitive and repeatability checks pass. The retained
hybrid task regression fails the unchanged conjunction. **Reference semantics
are not clean enough for the next PPO comparison.** No PPO, reward, observation,
network, residual bound/window or budget change occurs here.

If research continues, the highest-information candidate is one reference-only
factor: **heading alignment blend at fixed actual origin**. Compare a prospectively
fixed, nonadaptive midpointα=0.5 with retainedα=0(anchor) andα=1(hybrid), using
wrapped heading interpolation. Keep gains, cases, measurements and all gates
unchanged; do not pickα from the observed16m failure or tune it to recover PASS.
This tests partial alignment rather than adding a new constraint controller.
It offers no promised PASS and is not implemented in this session. Any later
generalization claim requires separately frozen evidence, as these cases are seen.

## Tests, audit and retained evidence

Full suite **709 passed**,40 TorchScript deprecation warnings;23 new tests
verify independent hybrid geometry, same ideal heading across origin arms,
historical replay/primitive equivalence, actual measurement/envelopes, original
controller/skill lifecycle, zero residual and unchanged case membership.

Independent mechanism audit1,474/1,474 integrity checks pass, including10,070
walking command samples among15,670 total traces, historical/primitive/repeated
identities and the unchanged old gates. Results audit independently verifies
feedback, sources, frame recipes, counters and candidate-gate failure. Passing
integrity never changes the negative training conclusion.

All156 outcomes, command traces, per-physics correction counters, manifests,
completion, primary summaries, anchor comparisons and conditional-origin
comparison are retained.162 exported files preserve raw/encoded SHA and size;
large JSONL logs are losslessly gzipped. Original raw artifacts remain. Old
Phase3A sources and evidence are untouched; Phase2.3 language Runtime is still
BLOCKED. No Jev/Multi-Swarm or next experiment starts.

See `decision.json`, `evidence_manifest.json`, `mechanism_audit.json`,
`independent_results_audit.json`, and `README.md` for methods and complete evidence.
