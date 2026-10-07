# Phase 3A.4f — Residual action composition at fixed 14 s authority

**Scientific verdict: INCONCLUSIVE for the strict + physical + same-reference global joint witness.** The sole new lateral-only `(0,-1,0)` primary completes the seen 16 m case with nominal and physical PASS, but its first-Walk strict gate and paired global gate both FAIL. The frozen conditional confirmation rule therefore stops acquisition after one run. This is a negative result for this action at this duration, not a full-space infeasibility proof or permission to tune another profile.

## Frozen intervention and controls

The question was whether removing sustained yaw from the already tested 14 s combined action would preserve its local strict gain while eliminating its final global X penalty. Protocol, 279 source pins, case, action schedule, conditional run budget, isolated controller and independent audit were committed as `c950b2f35435e2894026e59057eced21546f0f97` before the first new physics step. Alpha remains 0.5; the same seen `sequence-mixed-16m` case, seed 0, actual-start origin, reference selector, first-Walk 14 s applied authority, residual bounds, base policy, PD/gains, evaluator, thresholds, original observation and reward callback path are retained. The 61-feature observation's active flag and transition monitor retain their original 2 s meaning; the applied-authority trace flag remains 14 s. The only changed actuator proposal is combined `(0,-1,-1)` to lateral-only `(0,-1,0)` on node 1 Walk; all other nodes get zero probe action. No reward or observation was modified.

Historical residual-off and 2 s lateral-only from `residual_authority_feasibility_001`, and 14 s combined plus its zero control and exact repeat from `residual_authority_window_001`, are read-only comparison evidence. The inherited zero-14, combined-2 and combined-14 repeat gates were checked PASS. New pre-treatment Stand, first-Walk start state and walking reference match residual-off exactly. The local controller and offline auditor are byte-identical to the 14 s experiment. The new treatment was not selected by scanning actions or windows.

## Primary result

| Treatment | Walk8m local lateral | Strict 0.28 m | Nominal / physical | Final world endpoint norm | Paired global vs own off |
| --- | ---: | --- | --- | ---: | --- |
| Residual-off | 0.372292 m | FAIL | PASS / PASS | 1.209069 m | baseline |
| Historical lateral-only, 2 s | 0.371606 m | FAIL | PASS / PASS | 1.192228 m | PASS |
| Historical combined, 14 s | 0.268425 m | PASS | PASS / PASS | 1.264756 m | FAIL |
| **New lateral-only, 14 s** | **0.322906 m** | **FAIL by 42.906 mm** | **PASS / PASS** | **1.212208 m** | **FAIL, +3.139 mm** |

The 14 s lateral-only action removes **134.281 mm** of the combined treatment's excess final X error and reduces its endpoint norm by **52.548 mm**, but it also loses **54.481 mm** of combined's local lateral improvement. Versus residual-off, final world XY error is `( +0.553673, -1.078376 ) m` instead of `( +0.475501, -1.111642 ) m`: X worsens by **78.172 mm**, while absolute commanded-axis lateral improves **33.266 mm**. Absolute heading error improves by **0.870 deg** (`-0.418894 deg` versus `-1.288572 deg`). The inherited paired global condition nevertheless fails because endpoint norm is not strictly lower than off. Node 0 is exact; nodes 1–6 endpoint norm changes versus off are `+47.441, +6.125, +58.815, +52.266, -4.187, +3.139 mm`. All seven original skills finish SUCCESS, but only the first Walk fails strict.

## Steering, correction and physical behavior

At the equal-time 2 s boundary, the new 14 s arm matches historical 2 s lateral-only: **-73.438 mm** local lateral effect versus off. The new arm continues to approximately **-122.261, -140.216, -148.690 and -148.383 mm** at 4, 6, 10 and 14 s. Historical combined-14 reaches **-270.641 mm** at 14 s. At the 14 s cutoff the first zero-residual sample has fixed-reference lateral **-0.159398 m**, versus off **-0.010223 m**. The new Walk lasts **17.090 s**, leaving **3.090 s** after authority ends. Its formal endpoint still has **-49.386 mm** local effect versus off, about one third of its 14 s effect; fixed-reference lateral has decayed to **-0.052006 m**. These formal endpoint values are not equal-time trace samples. Historical 2 s lateral-only retained just **-0.687 mm** at its endpoint.

The longer lateral action thus persists beyond the old 2 s cutoff, but is weaker than combined steering and is partially erased by continuing reference correction after 14 s. First-Walk correction statistics show zero saturation and zero oscillations; no 10 Hz total-yaw clipping sample was found. Max tilt is **6.7698 deg**, minimum height **0.75894 m**, with no fall, invalid control or nonfinite state. The normalized lateral action spends its declared window at its fixed bound by design. These are simulator stability observations, not hardware or continuous-corridor safety claims. Strict is scored at the formal Walk endpoint.

## Integrity, telemetry and stopping boundary

The sole new run has **26,887 physics steps**, each covered by a full-step authority check with zero violations, **440 original reward callbacks**, zero optimizer updates and zero checkpoint writes. Its separate offline auditor passed **15,250 numeric** and **5,431 predicate** checks. Raw result, trace, decision ledger, state archive, full-step receipts and negative score are retained with encoded/decoded hashes. The controller was restored. Independent post-acquisition review recomputed the source/score and evidence integrity; the exact outcome is in `integrity_review.json`. Nineteen targeted offline tests passed before physics and again against the committed acquisition source. No full regression was run because shared controller, evaluator, observation and reward sources did not change.

Research Ops v0.1 routed this work as `mechanism` and recorded task `authority-composition-001`. Its `context` correctly returned STALE because the selected pointer still names the older experiment after 3A.4e; the six underlying anchors passed, and no pointer or Ops code was changed. The measured new physics command took **7.801 s**. Stage intervals may overlap and cannot be summed as wall time; token usage is unavailable. Browser QA was outside this scientific task.

**Stopping reason:** the one frozen action has a complete, audited negative result; it fails both the local strict and paired global conditions. The predeclared confirmation is reserved for a constructive primary and was skipped. No additional action, amplitude, window, training, reward alignment, Jev, Multi-Swarm or new reference search follows.
