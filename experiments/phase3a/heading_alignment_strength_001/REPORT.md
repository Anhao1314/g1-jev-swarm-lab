# Phase3A fixed heading alignment — nominal recovery with a strict corridor cost

Date: 2026-10-07. Branch: `phase3a/transition-learning`.

**Verdict: MIDPOINT_GLOBAL_GAIN_WITH_RESTORED_TASK_RELIABILITY**, under the
unchanged **nominal** task gate. The predeclared alpha=0.5 improves final global
lateral and heading errors on both sequences and restores 26/26 nominal task
successes. It retains a strict-envelope regression on the first16m Walk, so
this is not recovery of every historical envelope. No PPO was trained, no alpha
was searched, and alpha=1's negative result remains intact.

## Fixed factor and preserved evidence

All three arms use actual node-start origin, fixed for each Walk:

| Alpha | Walking correction heading |
| --- | --- |
| 0 | Historical actual node-start heading |
| 0.5 | Wrapped midpoint of actual and ideal commanded heading |
| 1 | Retained ideal commanded heading |

`theta_ref = wrap(theta_actual + alpha * wrap(theta_commanded - theta_actual))`,
where `wrap(x)=atan2(sin(x),cos(x))`. The midpoint takes the short wrapped arc;
signed antipodal ties follow that declared numerical convention. Endpoint
recipes are exactly the old implementations, preserving physical and command
identity. The selected frame rotates lateral and heading axes together. This
changes reference orientation, not gains or a yaw-command multiplier.

Locomotion, official motion.pt, PD, gains1.5/1.0, clamp0.6/deadband0.01, original
skills/termination/resets/settling and every nominal/strict envelope remain
unchanged. Local metrics still use the actual-start measurement frame. Original
Walk termination still reaches its distance target; tolerance is not used for
an earlier stop. Residual is off. Original reward, observation, network, bounds,
window and training budget are preserved and no training is invoked.

Source anchor `1eb802e2ab8d0dcb0cb2a2e601fd3a955f2fbb8f`;
acquisition freeze `1ee3667`.
Protocol SHA `f07a434f79cf2df9fca8ff0bf3c33775845eec0a95ab01b00c4188609077dabc`.
History manifest SHA `d22139534411139d51e0411babfe16eef43c395612890696c7e6f5b061510f0f`.
Inherited reference protocol SHA `b1da0596037f8cea1d8879e2ebb1d911771a342354e0122ad0355a4c78c0b04f`.
Case SHA `c84cf2484d9cd6138d19828e09ad9fb7cb57467330c96e08ad8cbed853b0f55e`.
Official motion.pt SHA `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
492 historical source/evidence files and inherited219 baseline pins verify.

Same26 previously seen mechanism cases per arm:16 transitions,8 primitives,
2 sequences. Primary78 runs and separate78 repeats are never pooled. Repeated
nominal dynamics are deterministic checks, not independent samples. Legacy
evaluation-set names do not supply new blind/generalization evidence.

## Reliability and retained failures

| Primary outcome | Alpha0 | Alpha0.5 | Alpha1 |
| --- | --- | --- | --- |
| Transition nominal task / physical | 16/16 /16/16 | 16/16 /16/16 | 16/16 /16/16 |
| Primitive nominal task / physical | 8/8 /8/8 | 8/8 /8/8 | 8/8 /8/8 |
| Sequence nominal task / physical | 2/2 /2/2 | 2/2 /2/2 | 1/2 /2/2 |
| Overall nominal task / physical | 26/26 /26/26 | 26/26 /26/26 | 25/26 /26/26 |
| Nominal failure taxonomy | SUCCESS26 | SUCCESS26 | SUCCESS25; EXCESSIVE_DRIFT1 |
| Strict node failures | 0 | 1 | 2 |

Alpha1 retains the exact old first8m nominal EXCESSIVE_DRIFT. Its strict failures
are that node and eval-sw-04's Walk. Midpoint has no nominal/physical regression,
but its first8m strict envelope fails while alpha0's passes. The hard training
gate was already defined using original `task_success` (nominal); strict remains
a separate retained diagnostic. Neither status is changed to obtain PASS.

All104 endpoint runs reproduce historical alpha0/1 physical records; all78
repeats match. All eight primitive physical outcomes are identical in all arms.
No falls, correction saturation or correction oscillations occur. Peak tilt
7.183103/7.187348/7.905225 degrees and minimum height
0.758619/0.754136/0.748237m for alpha0/0.5/1 show that continuous physical extrema
are not all improvements. Maximum correction yaw is
0.138029/0.180180/0.222333rad/s. Preserved physical success is not proof of stronger
stability or generalization.

## Final sequence precision

Absolute final errors, not maximum path deviation. Signed results and all node
diagnostics remain in per-sample evidence.

| Sequence / metric | Alpha0 | Alpha0.5 | Alpha1 |
| --- | ---: | ---: | ---: |
| 12m ideal lateral (m) | 0.132712 | 0.001708 | 0.058107 |
| 12m ideal heading (degrees) | 2.246304 | 1.362891 | 1.042817 |
| 12m endpoint norm (m) | 0.757700 | 0.718544 | 0.730519 |
| 16m ideal lateral (m) | 1.840337 | 1.111642 | 0.694057 |
| 16m ideal heading (degrees) | 6.348225 | 1.288572 | 0.255096 |
| 16m endpoint norm (m) | 1.840972 | 1.209069 | 0.991713 |

Midpoint reductions versus alpha0:12m lateral98.71%, heading39.33%, endpoint5.17%;
16m lateral39.60%, heading79.70%, endpoint34.32%. Final signed midpoint lateral/
heading are +0.001708m/−1.362891 degrees at12m and −1.111642m/−1.288572 degrees
at16m. Global gains repeat exactly and satisfy the prior conjunction without a
new improvement threshold. Endpoint also improves but is not newly made a gate.

Completion times for alpha0/0.5/1:12m33.774/33.772/33.774s;
16m53.772/53.806/54.032s. No cases or targets were shortened. Near-zero final12m
lateral error does not mean a near-zero entire route: midpoint's maximum absolute
lateral among recorded node endpoints is0.364008m, versus alpha0's0.434700m and
alpha1's0.345903m. These are node-endpoint diagnostics, not per-physics path
maxima. In16m, midpoint remains over1m from the ideal lateral axis and loses some
global gain relative to alpha1. There is no optimal-alpha claim or universal
global precision solution.

## First8m corridor and the mechanism

| 16m Walk / metric | Alpha0 | Alpha0.5 | Alpha1 |
| --- | ---: | ---: | ---: |
| First8m local lateral, signed (m) | -0.001682 | +0.372292 | +0.743292 |
| First8m local heading, signed (degrees) | -0.228014 | +2.102093 | +4.372686 |
| First8m nominal / strict success | PASS / PASS | PASS / FAIL | FAIL / FAIL |
| Next4m local lateral (m) | -0.023275 | +0.113928 | +0.053852 |
| Last4m local lateral (m) | -0.022144 | +0.051312 | -0.039024 |

The unchanged first8m nominal lateral limit is0.56m and strict limit0.28m; the
two later4m nominal limits are0.35m. All three arms enter first8m from the exact
same10s Stand state: position(0.112009,−0.185944)m, yaw−5.367025 degrees.
Midpoint reference is−2.683512 degrees, halfway toward commanded zero. Its
first-state heading feedback is+0.070254rad/s; alpha0/1 are0/+0.140508. Lateral
feedback starts at zero because every origin is the actual node start.

For parallel tracking at forward8m in the original local frame, the geometric
lateral requirement is `8 * tan(alpha * 5.367025 degrees)`: approximately0,
0.375 and0.752m. Observed−0.001682/+0.372292/+0.743292m follows that mechanism.
The predeclared midpoint relieves the orientation conflict enough for the
nominal corridor, but not the strict corridor. This is a real reference/contract
tradeoff, not label ambiguity, evaluator error, reward hacking or PPO capacity.
The geometric construction is evidence at this shared first node, not a theorem
about all closed-loop transitions.

## Transition geometry and continuous costs

Target-node means across the same four cases per family:

| Metric | Alpha0 | Alpha0.5 | Alpha1 |
| --- | ---: | ---: | ---: |
| turn→walk local absolute lateral (m) | 0.007785 | 0.015551 | 0.026875 |
| turn→walk local absolute heading (degrees) | 0.398817 | 0.440432 | 0.573134 |
| turn→walk ideal absolute heading (degrees) | 0.652580 | 0.381421 | 0.396549 |
| stand→walk local absolute lateral (m) | 0.018168 | 0.056755 | 0.098502 |
| stand→walk local absolute heading (degrees) | 0.964576 | 2.443895 | 4.005183 |
| stand→walk ideal absolute heading (degrees) | 2.122411 | 1.330853 | 1.074550 |
| turn→walk transition lateral change, absolute mean (m) | 0.030808 | 0.031387 | 0.031392 |
| stand→walk transition lateral change, absolute mean (m) | 0.048374 | 0.033896 | 0.028312 |
| turn→walk completion duration, mean (s) | 5.000000 | 5.000500 | 5.000000 |
| stand→walk completion duration, mean (s) | 5.011500 | 5.015500 | 5.021000 |

Local alignment gets worse as the correction partly follows the commanded
axis, while ideal heading improves. Binary nominal reliability is preserved;
geometry is not unchanged or uniformly better. Transition window duration stays
2s for those two families. Sustained recovery means turn→walk
0.5515/0.5530/0.5520s and stand→walk0.6665/0.6680/0.6725s show no recovery-speed
improvement. Raw transition heading change includes intended rotation and is
not a heading error. Original summary/comparison retain denominators and null
recovery coverage; missing values are never zero-filled.

walk→turn and walk→stop records remain physically exact across all arms because
their first Walk's actual and commanded headings initially coincide. Nonwalking
commands and skill semantics stay unchanged. Later sequence Turn/Stop geometry
can change through prior Walk state; no general turning-stability claim follows.

## Gate, next single factor and stop boundary

The inherited nominal task, physical, primitive, global-gain and repeatability
criteria all pass for the midpoint. **An intermediate heading reference exists
on these fixed cases that improves global precision without nominal task
regression.** Strict reliability has not been restored; this qualification must
travel with any readiness claim. The strict negative result is already present
in the original scoring and is not used to rewrite the frozen nominal gate.

The evidence supports a subsequent independent PPO comparison. Its only factor
should be heading-reference strength: alpha0 versus alpha0.5 at actual origin,
with reward, observation, network, residual bounds/window and training budget
held fixed. Include both residual-off controls and compare each learned actor
against its own same-frame control, so deterministic reference gains cannot be
credited to learning. Freeze training/evaluation separation before training;
new blind evidence is required for generalization. Retain nominal and strict
outcomes separately. The historical local reward may pull against partial ideal
alignment; that is a future hypothesis, not authorization to change reward now.

This study does not scan alpha0.4/0.6 or claim the midpoint is optimal. It does
not start PPO, Jev, Multi-Swarm, or another campaign. The Phase2.3 source-authority
failure and language Runtime BLOCKED gate remain unchanged.

## Tests and evidence

Full suite **741 passed**,50 existing TorchScript deprecation warnings. The32
new tests verify wrapped branch crossing/ties, endpoint equality, immutable
actual origin, rejection of unlisted alpha, independent feedback arithmetic,
all primitives, actual local measurement/envelopes and old controller/skills.

All156 per-sample outcomes, command traces, correction counters, manifests,
completion, primary summary and paired comparison are retained.161 exports
preserve raw/encoded SHA and byte size; large JSONL files are losslessly gzipped.
Raw artifacts remain in place. `decision.json` applies the original gate without
rescoring. Independent mechanism audit passes 1,473/1,473 checks and reconstructs
10,062 logged walking command samples among 15,662 trace rows. Independent
results audit passes 87,828 checks, including 104 fully annotated historical
endpoint records and 104 trace byte identities, and verifies the source/evidence
chain, both historical anchors and repeated behavior; see their JSON records
and the 412-check `integrity_audit.json` for checks. A passing integrity audit does not erase
the strict regression or alpha1 nominal failure.

Methods: `README.md`, `protocol.json`, `history_freeze.json`.
Results: `decision.json`, `evidence_manifest.json`, `evidence/summary.json`,
`evidence/comparison.json`, `evidence/results.jsonl.gz`.
Audits: `mechanism_audit.json`, `independent_results_audit.json`,
`integrity_audit.json`; tests: `tests.xml`.
