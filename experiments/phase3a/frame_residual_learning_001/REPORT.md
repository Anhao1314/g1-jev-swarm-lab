# Same-frame PPO: more consistent position gains, angular tradeoffs remain

Date: 2026-10-07. Branch: `phase3a/transition-learning`.

**Verdict: CONSISTENT_POSITION_GAIN_WITH_ANGULAR_TRADEOFF_AND_RETAINED_STRICT_FAILURE.**
In this two-seed pilot, midpoint residual learning produces more consistent
same-frame position gains than actual-frame learning. Both midpoint actors
reduce fresh mean lateral/endpoint error and improve all three16m final global
metrics. They also reduce12m heading/endpoint error, but increase12m final lateral
error. Fresh mean global heading worsens in both seeds. The first8m strict
corridor failure remains. This supports a partial learning effect, not overall
Pareto superiority, seed-insensitive precision, strict recovery or adoption.

All learned effects below are paired with the actor's **own same-frame
residual-off control**. The prior deterministic midpoint improvement is not
credited to PPO. No reward/observation/budget/authority tuning occurred after
freeze or evaluation. Failed quality outcomes and every checkpoint are kept.

## Frozen experiment and genuine training

Acquisition commit `a4926973e01b65f98fc7c598d48ac982b47d6516`; source anchor
`1726d74111abe8084a0f509edafb8c16b1b3ad01`. Protocol SHA
`df0529a7f9f542463eadf99a1b01c36346344bec184009b13b44eef688781afb`;
case SHA `641dcdf36447976cfb29e64dd24bbe911beaca8284ef7299f82f9cb7ce38a909`;
history SHA `b124a1f66eed10b59ad8ed3e4e1ff7de34e382bc67e28a1a136c654dd34ddfc4`.
669 historical pins and219 foundation pins remain unchanged. Full methods and
the original policy/pilot hashes are in `methods.md` and the immutable manifests.

Original12 training cases,61-feature observation, stateful reward,64×64 network,
PPO512/64/five epochs, optimizer/defaults and8192-step budget per actor are
unchanged. Same seeds11/29 are paired by initial tensors across frames. Residual
bounds0.10/0.06/0.12, original2s window, PD, locomotion, gains/clamp, transition
definitions and all nominal/strict envelopes remain unchanged. Joint policy is
frozen. Only the actual-origin walking correction heading is alpha0 or alpha0.5.

| Formal actor | Decisions | Active decisions | Complete episodes | PPO loss receipts | Epoch counter | Actual Adam steps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Alpha0 seed11 | 8192 | 5706 | 317 | 16 | 80 | 640 |
| Alpha0 seed29 | 8192 | 5740 | 317 | 16 | 80 | 640 |
| Alpha0.5 seed11 | 8192 | 5702 | 316 | 16 | 80 | 640 |
| Alpha0.5 seed29 | 8192 | 5666 | 316 | 16 | 80 | 640 |

All1,266 completed formal training episodes pass their original task/physical
scores. Four interrupted tails remain unscored and retained. Two separate
seed7 smoke runs each complete512 decisions,19 episodes and40 Adam steps; none
enters primary evaluation. Formal training takes approximately128–129s per actor
on this host; wall time is not a changed budget. Episode exposure differs slightly
because closed-loop duration changes, despite equal decision budgets.

Both alpha0 runs reproduce original pilot final tensors exactly. The training
audit also checks legacy decision fields, optimizer receipts and intermediate
tensors. All formal initial/intermediate/final and smoke checkpoints are kept:
**24 ZIPs**, without evaluation selection. Reload reproduces exact tensor and
training-case physical replay. Initial tensor equality across same seeds makes
the reference contrast inspectable rather than an initialization contrast.

Fresh evaluation uses16 prospectively fixed, previously unexecuted parameter
tuples; all four final file/tensor receipts are locked before its first physics
call. Old26 cases are seen regressions, including12m/16m sequences and primitives.
Primary252 runs comprise96 fresh and156 seen. Separate36 identical repeats are
determinism checks and never pooled. This tests parameter interpolation in the
same simulator, not independent environments or statistical robustness.

## Reliability, nominal and strict

| Arm | Fresh nominal / physical | Fresh all-node strict | Seen nominal / physical | Seen all-node strict | Primitive identity |
| --- | --- | --- | --- | --- | --- |
| Alpha0 off | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 26/26 | Control |
| Alpha0 seed11 | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 26/26 | 8/8 exact |
| Alpha0 seed29 | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 26/26 | 8/8 exact |
| Alpha0.5 off | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 25/26 | Control |
| Alpha0.5 seed11 | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 25/26 | 8/8 exact |
| Alpha0.5 seed29 | 16/16 /16/16 | 16/16 | 26/26 /26/26 | 25/26 | 8/8 exact |

There are no falls, interruptions, new nominal failures or new strict failures.
Original nominal failure taxonomy is SUCCESS42 per arm. All-node strict is a
separate conjunction of original node booleans, not a rewritten task score.
The original midpoint sequence16m/node1 strict EXCESSIVE_DRIFT persists in both
learned actors. All32 learned-vs-own-frame primitive records are physically exact;
zero residual and zero policy calls protect primitives. Success already has a
ceiling, so42/42 does not establish a reliability gain.

| Continuous extrema over42 primary cases | Alpha0 off / s11 / s29 | Alpha0.5 off / s11 / s29 |
| --- | --- | --- |
| Peak tilt (degrees) | 7.183103 /7.224414 /7.285335 | 7.187348 /7.133352 /6.806604 |
| Minimum height (m) | 0.755067 /0.754864 /0.753287 | 0.754136 /0.755290 /0.755542 |

Midpoint improves these two extrema in both seeds, while actual-frame learning
worsens them. This is descriptive stability evidence on the declared cases,
not a new physical-success threshold or a robustness claim.
Walking correction has no recorded saturation or oscillation in any arm.

## Fresh global precision and seed agreement

Mean final absolute errors over the16 fresh cases per arm, with no missing values:

| Arm | Ideal lateral (m) | Ideal heading (degrees) | Endpoint norm (m) |
| --- | ---: | ---: | ---: |
| Alpha0 off | 0.085546 | 0.959439 | 0.187435 |
| Alpha0 seed11 | 0.067957 | 1.293892 | 0.167159 |
| Alpha0 seed29 | 0.093591 | 1.059591 | 0.221897 |
| Alpha0.5 off | 0.075238 | 0.717601 | 0.179461 |
| Alpha0.5 seed11 | 0.072137 | 0.860430 | 0.163752 |
| Alpha0.5 seed29 | 0.058895 | 0.830805 | 0.152942 |

Midpoint seed11/29 own-frame reductions: lateral4.12%/21.72%, endpoint8.75%/14.78%.
Its heading error **increases19.90%/15.78%**. Actual-frame seed11 improves mean
lateral/endpoint, while seed29 worsens both; both actual-frame seeds also worsen
mean heading. Thus midpoint makes position benefit more consistent across these
two seeds, while angular quality remains adverse and case-dependent.

| Fresh cases where both seeds improve their own baseline | Alpha0 | Alpha0.5 |
| --- | ---: | ---: |
| Final absolute lateral | 7/16 | 10/16 |
| Endpoint norm | 5/16 | 13/16 |
| Final absolute heading | 4/16 | 1/16 |

Angular sign agreement is14/16 at alpha0 and7/16 at midpoint, but alpha0 agrees
on worsening in10 cases. Agreement alone is not success. Midpoint has six cases
with both seeds worsening heading and nine with differing directions. No single
cross-seed total score or optimal checkpoint is selected to hide those effects.

## Seen12m/16m global outcomes

Absolute final diagnostics. These sequences are regression evidence, not fresh
held-out data. Every comparison is horizontal within its own three-column frame.

| Metric | Alpha0 off | Alpha0 s11 | Alpha0 s29 | Alpha0.5 off | Alpha0.5 s11 | Alpha0.5 s29 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 12m lateral (m) | 0.132712 | 0.060156 | 0.291685 | 0.001708 | 0.002859 | 0.027589 |
| 12m heading (degrees) | 2.246304 | 2.444990 | 4.005666 | 1.362891 | 0.112276 | 0.469841 |
| 12m endpoint (m) | 0.757700 | 0.716559 | 1.156545 | 0.718544 | 0.627378 | 0.442079 |
| 16m lateral (m) | 1.840337 | 1.842050 | 2.161778 | 1.111642 | 1.039803 | 0.952174 |
| 16m heading (degrees) | 6.348225 | 7.646487 | 7.061369 | 1.288572 | 0.564474 | 0.225337 |
| 16m endpoint (m) | 1.840972 | 1.842569 | 2.162714 | 1.209069 | 1.115638 | 1.048471 |

Midpoint16m improves all three metrics in both seeds: lateral6.46%/14.34%,
heading56.19%/82.51%, endpoint7.73%/13.28% versus midpoint off. Actual-frame16m
worsens all three metrics in both seeds. This is meaningful same-frame learning
evidence on a seen stress sequence, not the deterministic frame gain.

Midpoint12m improves heading/endpoint but worsens final lateral by0.001151m and
0.025881m. Since its off control is already near zero, relative lateral percentages
would exaggerate interpretation; both absolute regressions are retained. Route
precision remains incomplete: midpoint16m endpoint is still over1m, and sequence
improvement does not establish uniformly improved angular generalization.

## Four transition families and geometry

Fresh target-node means across four cases per family, versus each own baseline:

| Target metric | Alpha0 off / s11 / s29 | Alpha0.5 off / s11 / s29 |
| --- | --- | --- |
| stand→walk local heading (degrees) | 0.506918 /0.766027 /0.553961 | 1.615983 /1.063185 /1.158411 |
| stand→walk ideal heading (degrees) | 1.548113 /2.499865 /1.939179 | 0.528500 /0.991846 /0.896620 |
| stand→walk local lateral (m) | 0.033700 /0.006670 /0.030789 | 0.035428 /0.029507 /0.035770 |
| turn→walk local heading (degrees) | 1.236358 /0.753009 /0.823149 | 1.413639 /1.441401 /1.355349 |
| turn→walk local lateral (m) | 0.050252 /0.030173 /0.041745 | 0.042172 /0.043070 /0.028078 |
| walk→turn translation norm (m) | 0.312286 /0.295650 /0.423768 | 0.312286 /0.282467 /0.272213 |
| walk→turn target heading error (degrees) | 0.635447 /0.673014 /0.564813 | 0.635447 /0.689104 /0.640849 |
| walk→stop translation norm (m) | 0.153865 /0.131486 /0.188433 | 0.153865 /0.133346 /0.112907 |
| walk→stop local heading change, absolute (degrees) | 0.401310 /0.521117 /0.418499 | 0.401310 /0.727239 /0.572647 |

Midpoint reduces uncommanded Turn/Stop translation norms in both seeds; actual
seed29 worsens them. Those are real position effects beyond reward. However,
midpoint Turn heading slightly worsens in both seeds. turn→walk seed11 local
lateral/heading and window lateral geometry worsen, while seed29 improves them.
stand→walk local heading improves in both midpoint seeds **as ideal heading
worsens in both**, an explicit local/global objective tradeoff. Its seed29 local
lateral increases slightly. Nominal/strict success stays unchanged on fresh cases.

Midpoint target completion means off/s11/s29: stand→walk4.206/4.184/4.319s,
turn→walk4.2075/4.182/4.320s, walk→turn2.603/2.5765/2.596s,
walk→stop1.3345/1.294/1.2825s. Faster completion alone is not a quality gain.
Raw transition heading change includes intended rotation; Turn task heading
error is separately retained. Full target-window geometry, angular-speed RMS,
standing/recovery coverage and physical extrema are in `analysis.json` and raw
records, with all denominators and nulls preserved. Translation norms are derived
from retained start/end xy in `supplementary_geometry.json`, with no rescoring.

## Strict failure and authority attribution

| First16m 8m Walk | Alpha0.5 off | Alpha0.5 seed11 | Alpha0.5 seed29 |
| --- | ---: | ---: | ---: |
| Local lateral (m) | 0.372292 | 0.372792 | 0.363038 |
| Nominal0.56m corridor | PASS | PASS | PASS |
| Strict0.28m corridor | FAIL | FAIL | FAIL |

Seed11 slightly worsens this drift; seed29 improves it by0.009255m, insufficient
to recover strict. It is not a new nominal failure or an evaluator error, and
learning does not erase the historical strict regression.

Every first8m Walk starts from the same10s Stand state within the comparisons.
The selected midpoint line remains fixed. Its parallel-tracking requirement at
8m local progress is approximately0.374963m, above strict0.28m. Learning has
authority only before2s; the Walk completes near17s with zero applied residual
for the remaining roughly15s. Endpoint control-line error and boundary traces
must therefore be read as full-controller outcomes. Persistent later effects
can arise from earlier physical/recurrent state; they are not continued PPO
authority. The fixed frame/corridor geometry and limited temporal authority
strongly constrain strict recovery in this case, without proving impossibility
for every learned policy or budget.

The mechanism audit separates early from later effects: midpoint off/s11/s29
first8m world heading at2s is approximately +0.0046/+0.4922/−0.8377 degrees;
at completion it is −3.2649/−3.1275/−3.5918 degrees. Neither learned policy
recovers the strict corridor. The first8m lateral changes are only about+0.0005m
and−0.0093m; final16m lateral gains are0.0718m and0.1595m after later transitions.
Whole-sequence gain cannot be credited to strict first-Walk recovery. Moreover,
the fresh stand→walk mean active yaw residual points toward ideal in seed11 and
opposes it in seed29. The same local/global outcome tradeoff does not prove that
both actors countersteer or establish a reward-only causal explanation.

## Failure taxonomy, bottleneck and next decision

Original nominal/physical failure taxonomy is entirely SUCCESS. Research-quality
negative findings are kept separately: fresh angular degradation, seed-sensitive
turn→walk geometry,12m lateral regression, retained strict EXCESSIVE_DRIFT, and
large residual16m endpoint error. Training return is not promoted to a scientific
PASS: mean decision rewards are0.368761/0.360728 at alpha0 and0.366539/0.362011 at
midpoint, with slightly different case exposures. Actual observations, actions,
terminal episodes and optimization logs remain inspectable.

The most informative next hypothesis for **fresh angular quality** is reward
reference alignment. The frozen dense reward penalizes actual-start heading
error while midpoint correction deliberately follows a different heading; the
observed stand→walk local-heading gain/global-heading loss matches that conflict.
Ideal errors are already present in the frozen observation, and positive position
learning demonstrates usable policy capacity/authority. These facts make missing
observation or total base-policy failure weaker explanations for this particular
tradeoff. They do not causally identify reward as the unique bottleneck: no reward,
observation, network, authority or budget ablation was performed here.

For the **strict8m failure**, reference/corridor geometry together with2s authority
is a separate constraint. Reward alignment alone is not promised to repair it.
The base controller still permits uncommanded Stand/Turn/Stop motion, so it also
contributes to remaining route error; its weights/configuration were never varied.

Recommended next independent experiment: at fixed alpha0.5, change only the
**dense heading-reward reference**, comparing the retained actual-start heading
term with a term measured against the already selected midpoint heading. Keep
its coefficient, all other reward terms, terminal envelopes, observations,
network, bounds/window, optimizer and budget fixed. Pre-freeze new evaluation
evidence; retain the current fresh set as seen regression. This would test the
angular objective conflict, not patch a threshold or claim strict recovery.
It is a proposal only, not implemented or trained in this session.

The independent mechanism audit also proposes a residual-authority-window
ablation to address the strict node. That candidate targets a different failure.
This report prioritizes the dense heading-reward reference for the fresh angular
tradeoff, with2s authority held fixed, and does not combine the two changes or
promise strict recovery. The different next-factor recommendations reflect
uncertainty rather than a hidden causal resolution.

There is no basis to adopt a universal learned transition policy yet. Current
evidence supports useful, more consistent position learning at midpoint within
this two-seed pilot, with unresolved angular/strict quality and seed dependence.
Phase2.3 Language Runtime remains BLOCKED for its independent source-authority
safety issue. No Jev, Multi-Swarm, subsequent training or Runtime campaign starts.

## Tests, audits and preservation

Full suite **777 passed**,75 existing TorchScript deprecation warnings. The36
new tests include real old/new alpha0 one-rollout optimization equality,40 Adam
steps, checkpoint reload, same-frame zero actor,61-observation/reward/RNG identity,
no extra stateful reward calls,2s/primitive masking, worker/tail behavior and pure
split/protocol checks. Tests never simulate new held-out cases.

All392 exports retain raw/encoded SHA and size, including24 checkpoint ZIPs,
four8192-decision ledgers, all episode/optimizer receipts, partial tails, lock/
stage chronology,252 primary and36 repeated outcomes with command traces.
Large JSONL files are losslessly compressed; original artifacts remain.
Independent training and mechanism audits verify the chain and conclusions;
training audit passes562,680 checks, mechanism audit1,659, and root evidence
integrity792. The audits independently reconstruct training/checkpoint proof,
original scores, own-frame arithmetic, command masks/geometry and chronology.
Their final JSON files and root integrity audit are published alongside this
report. Prior Phase3A evidence and the retained Phase2.3 negative result are
unchanged. Passing integrity checks never changes the strict or angular findings.

See `methods.md`, `protocol.json`, `case_manifest.json`, `history_freeze.json`,
`analysis.json`, `training_statistics.json`, `supplementary_geometry.json`,
`evidence_manifest.json`, `independent_training_audit.json`,
`mechanism_learning_audit.json`, `integrity_audit.json`, `boundary_preservation.json`
and `tests.xml` for complete evidence.
