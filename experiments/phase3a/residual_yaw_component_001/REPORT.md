# Phase 3A.4g — Fixed 14 s residual component control

**Scientific verdict: INCONCLUSIVE for the strict + physical + same-reference global joint witness.** The sole new yaw-only `(0,0,-1)` primary is nominal and physical PASS, but first-Walk strict and paired global both FAIL. The predeclared confirmation was therefore skipped. The fixed 14 s 2×2 comparison is complete for this seen 16 m case; no further action, window or amplitude is tested.

## Frozen question and execution

This experiment supplies the missing yaw-only actuator control alongside retained residual-off, 14 s lateral-only `(0,-1,0)` and 14 s combined `(0,-1,-1)`. Protocol, case, 284 source pins, run budget and acquisition code were committed at `660409c8cbd3fcd183c6e778572729bd8f47a125` **before new physics**. Alpha=0.5, seed 0, actual-start origin, reference selector, applied first-Walk authority=14 s, residual bounds, base policy, PD/gains, original 61-feature observation/reward callback path, evaluator and thresholds are fixed. The observation active feature and transition monitor retain their original 2 s semantics. Only the first-Walk proposed action changes; other nodes receive zero probe action. The local controller and independent auditor are byte-identical to the preceding 14 s lateral experiment.

Historical off is represented by the 14 s zero control, which exactly reproduces residual-off scientific execution and physics; its callback flags/reward observations are explicitly exempt from that equivalence. Retained combined and lateral evidence are read-only. The new pre-treatment Stand, first-Walk start state and walking reference match off exactly. The frozen plan allowed one yaw primary and one exact confirmation **only if** primary met all-node strict, complete physical/SUCCESS and the inherited paired-global condition. The primary did not qualify, so the run count is one.

## Fixed 14 s component table

| Action on first Walk | Walk8m local lateral | Strict 0.28 m | Nominal / physical | Final X error | Final Y error | Endpoint norm | Final heading error | Paired global |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| off `(0,0,0)` | 0.372292 m | FAIL | PASS / PASS | +0.475501 m | −1.111642 m | 1.209069 m | −1.288572° | baseline |
| lateral `(0,-1,0)` | 0.322906 m | FAIL | PASS / PASS | +0.553673 m | −1.078376 m | 1.212208 m | −0.418894° | FAIL |
| **yaw `(0,0,-1)`** | **0.318341 m** | **FAIL by 38.341 mm** | **PASS / PASS** | **+0.582537 m** | **−1.083744 m** | **1.230386 m** | **−0.457466°** | **FAIL** |
| combined `(0,-1,-1)` | 0.268425 m | PASS | PASS / PASS | +0.687954 m | −1.061285 m | 1.264756 m | +0.243257° | FAIL |

Yaw-only reduces local lateral by **53.951 mm** versus off, similar in size to lateral-only's **49.386 mm** reduction. Neither alone crosses the 0.28 m strict limit; combined reduces it by **103.867 mm** and crosses by 11.575 mm. Yaw-only increases final X error **107.036 mm**, improves signed Y error **27.897 mm** toward zero, and worsens endpoint norm **21.317 mm** versus off. Absolute commanded-axis lateral and heading both improve, but the original paired-global condition requires a strictly lower endpoint norm too. All seven skills finish SUCCESS; only first-Walk strict fails for yaw-only. Every post-Stand commanded-world prefix endpoint norm is worse than off in this arm.

## Component differences and interaction

The predeclared descriptive interaction is `I = combined − lateral − yaw + off`, applied to signed first-Walk local lateral, final world X/Y error and wrapped final heading error. The independent calculations and source hashes are in `component_analysis.json`.

| Outcome | Lateral − off | Yaw − off | Combined − off | Interaction I |
| --- | ---: | ---: | ---: | ---: |
| Local lateral | −49.386 mm | −53.951 mm | −103.867 mm | **−0.530 mm** |
| Final X error | +78.172 mm | +107.036 mm | +212.453 mm | **+27.245 mm** |
| Final Y error | +33.266 mm | +27.897 mm | +50.356 mm | **−10.806 mm** |
| Signed heading error | +0.869679° | +0.831106° | +1.531829° | **−0.168956°** |

At this formal endpoint, local lateral effects are close to the sum of isolated effects; the combined strict crossing does not require a large local interaction. In contrast, the combined final X penalty exceeds the sum of isolated X shifts by **27.245 mm**, with an accompanying signed Y and heading interaction. Thus the route-level global tradeoff is not captured by simply adding the two single-component endpoint shifts. These are finite differences from one deterministic case with feedback and downstream route propagation, not a general causal-additivity law or a fitted dynamics model. Endpoint norm interaction is **+31.230 mm descriptively**, but the Euclidean norm itself is nonlinear and cannot establish actuator interaction on its own. Binary strict/physical results are not decomposed additively.

## Authority persistence, correction and stability

At equal first-Walk elapsed time, yaw-only local effect versus off is **−39.707 mm at 2 s**, **−86.467 mm at 4 s**, **−107.914 mm at 6 s**, and **−120.862 mm at the 14 s cutoff**. The first sample at cutoff has zero residual; the Walk finishes after **17.116 s**, leaving **3.116 s** of continuing reference correction. At its own formal Walk endpoint, yaw-only retains **−53.951 mm** versus off. Lateral and combined retain **−49.386 mm** and **−103.867 mm** respectively at their own endpoints. Formal endpoints are not equal-time samples. These traces show substantial steering during authority and partial post-cutoff washout.

Yaw-only has no falls, invalid controls or nonfinite states; max tilt is **7.188°**, minimum height **0.752683 m**. All Walk correction statistics report zero saturation and zero oscillation, and no 10 Hz total-yaw clipping sample was observed. The yaw residual itself spends its declared window at the fixed normalized bound. These simulator observations do not certify hardware safety or continuous corridor containment; strict is an endpoint envelope.

## Evidence integrity, Research Ops and stop

The new run retained **26,915 physics steps**, each with a full-step authority check and zero violations, **441 original reward callbacks**, zero optimizer updates and zero checkpoint writes. Its offline auditor passed **15,284 numeric** and **5,442 predicate** checks. Independent post-acquisition review passed all 17 integrity checks: 284 pins, seven files equal to the pre-physics commit, 12 raw/export/decoded evidence files, historical controls, anchors, score recomputation and conditional stop. A separate interpretation review verified all 20 component-analysis source hashes and independently recomputed all four-cell arithmetic within 1e-12. Nineteen targeted offline tests passed against committed inputs. The complete raw result, trace, decision ledger, state archive and receipts are retained, including the failed gates. Shared scientific controller/evaluator sources did not change, so no full regression was run.

Research Ops v0.1 routed task `authority-yaw-component-001` as `mechanism` and retained stage telemetry. Initial context returned STALE because its selected pointer still names the older experiment; six source anchors passed, and neither the pointer nor Ops code was changed. Measured reasoning and implementation intervals are 91 s and 170 s. Audit intervals total 458 s but overlap implementation and include pre-review waiting and correction of an offline no-write path error. None of these stage intervals can be summed as wall time. The measured physics command took **7.846 s**. Token usage is unavailable; browser QA is outside this scientific task.

**Stopping reason:** all four predeclared fixed-14s component cells are available, the only new yaw treatment has a complete audited negative joint result, and its conditional confirmation was correctly skipped. No profile scan, training, reward alignment, Jev, Multi-Swarm or window search follows.
