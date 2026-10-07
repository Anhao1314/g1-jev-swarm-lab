# Phase 3B.0 — Decision Problem & Oracle Construction

**Verdict: NOT_READY_FOR_JEV_SHADOW as a scientific mode-selection evaluation.** The existing evidence supports a bounded vocabulary and a deterministic, fail-closed offline oracle. It does not yet establish an admissible recovery choice on a distinct state: the only complete fixed-14 s four-mode comparison is one 16 m first-Walk state, and its answer is `ABSTAIN`. Seen off-sufficient cases exercise `CONTINUE` and interface plumbing, but cannot establish recovery selection quality. No Jev call, new physics, training, residual search or robot-control integration occurred.

## Why a decision problem is plausible, and what is not yet proven

The inherited fixed-14 s experiment presents a real task-level conflict. On one exact 16 m state, the combined residual crosses the first-Walk strict 0.28 m gate while increasing final world endpoint error relative to its own residual-off comparator. Lateral-only and yaw-only reduce local error but do not pass strict. A selector therefore has a meaningful *type* of decision—continue, choose a bounded recovery, or decline authorization under joint constraints—rather than a scalar residual tuning task. However, no observed state currently demonstrates a recovery mode that satisfies strict, physical and same-reference global criteria together. The evidence establishes the conflict and abstention requirement, not Jev's ability to resolve it.

| First-Walk action, same 16 m predecision state | Local lateral m | Strict | Nominal/physical | Final X/Y error m | Endpoint norm m | Paired global |
| --- | ---: | --- | --- | --- | ---: | --- |
| off `(0,0,0)` | 0.372292 | FAIL | PASS/PASS | +0.475501 / −1.111642 | 1.209069 | comparator |
| lateral `(0,-1,0)` | 0.322906 | FAIL | PASS/PASS | +0.553673 / −1.078376 | 1.212208 | FAIL |
| yaw `(0,0,-1)` | 0.318341 | FAIL | PASS/PASS | +0.582537 / −1.083744 | 1.230386 | FAIL |
| combined `(0,-1,-1)` | 0.268425 | PASS | PASS/PASS | +0.687954 / −1.061285 | 1.264756 | FAIL |

These are retained deterministic within-case outcomes from [Phase 3A.4g](../../phase3a/residual_yaw_component_001/REPORT.md) and its [source analysis](../../phase3a/residual_yaw_component_001/component_analysis.json). Four actions on the same predecision snapshot count as **one** benchmark state. Treatment differences, including the final X interaction, are descriptive for this case; they are not a transferable dynamics law.

## Frozen bounded contract and predecision state

The machine-readable [contract](contract.json), [oracle](oracle.py) and [benchmark](benchmark.json) define five modes: `CONTINUE` (zero residual), first-Walk 14 s `LATERAL_RECOVERY`, `YAW_RECOVERY`, `COMBINED_RECOVERY`, and `ABSTAIN`. The three recovery modes inherit alpha 0.5, actual-start origin, original residual bounds, policy/controller/reference and evaluator. Their fixed action vectors are `(0,-1,0)`, `(0,0,-1)` and `(0,-1,-1)`. `ABSTAIN` withholds a recovery choice; it does **not** claim a tested physical stop maneuver. This vocabulary is a replay of observed treatments, not evidence that every mode is useful or safe elsewhere.

The input contains a stable state ID, exact experiment context, and only quantities available before the decision: current skill/transition; local lateral and heading error; current route X/Y and heading error; reference heading; instantaneous strict margin; remaining planned distance; and previous recovery. Exact context includes case/seed, alpha, origin, reference, controller, evaluator, base policy, residual bounds and recovery contract. Future strict result, final endpoint, later drift and treatment outcome are excluded. Outcome cells reside in a separate host-side catalog and are bound to exact state and context fingerprints. The state schema is deliberately small; no new perception channel or observation/reward change is proposed.

At an actual-start first-Walk entry, local lateral error can be zero by construction even when the *future* Walk strict gate fails. Consequently the current state may not discriminate later local risk by itself. Case/route context and pre-Walk state help locate an episode, but this tiny benchmark cannot establish generalizable prospective risk prediction; oracle outcome lookup must never be mistaken for a deployable policy.

## Deterministic oracle and benchmark coverage

The oracle is independent of Jev. It prefers `CONTINUE` if the observed off path meets nominal, physical and all-node strict gates. Otherwise a recovery is eligible only with complete same-state treatment evidence, nominal/physical/all-strict success, strictly lower final endpoint norm than own off, and no worse absolute final commanded-axis lateral or heading. It selects exactly one eligible recovery only after all three recovery cells and off are present. Missing evidence, context/state mismatch, multiple admissible modes or no admissible mode produce distinct `ABSTAIN` reasons. A recovery choice is limited to the recorded first-Walk entry and fixed 14 s contract. No “least bad” fallback is allowed.

The first benchmark reuses already-seen Phase 1/3 evidence. It is a diagnostic set, not fresh held-out. The 16 m four-cell row is the complete `ABSTAIN / NO_ADMISSIBLE_RECOVERY` counterexample. Retained off-sufficient episodes provide `CONTINUE` guardrails, while unobserved recovery cells stay explicit unknowns. The [benchmark](benchmark.json) records exact source paths/hashes, state derivation, observed and missing cells, and oracle labels; its targeted check verifies the fixed counterexample and source binding. Its seed-0 provenance is the pinned historical runner source, because the old result rows do not carry seed as a top-level field. Phase 1 heading/lateral correction under a different controller remains contextual evidence only and cannot fill a Phase 3B recovery cell.

This set covers off-sufficient and no-admissible situations. It does **not** cover a unique admissible recovery, a tested recovery that helps one state and harms another matched state, a disambiguated global-risk threshold, or enough independent examples for confidence calibration. A 12 m off trajectory's nonzero global endpoint error is not a global FAIL: the inherited global recovery rule is paired improvement against its own off, with no new absolute endpoint threshold.

## Jev v0 evaluation boundary

The separate [offline-shadow protocol draft](JEV_V0_PROTOCOL.md) defines exact oracle agreement; known unsafe versus unsupported selection; unnecessary intervention; abstention by reason; confidence calibration only with adequate independent examples; and latency/availability with failures retained in denominators. It explicitly withholds the host-side outcome catalog from the model and prohibits actuation. Current rows may exercise parsing and negative/continue behavior in an offline harness, but they cannot support a scientific GO for Jev shadow mode selection or calibrated confidence. A future decision requires independently reviewed, context-matched states with at least one admissible recovery and the missing outcome cells filled under a frozen acquisition plan. This stage does not initiate that acquisition.

## Integrity, telemetry and stop

Research Ops v0.1 context was loaded first. It initially reported a stale selection pointer, then returned **CURRENT** with 10/10 anchors after the authorized reviewed update to accepted Phase 3A.4g evidence. The historical scientific verdict remains **INCONCLUSIVE** and Phase 3A.5 remains paused. Work was routed as `mechanism`; Ops itself was not changed. Independent read-only review found no blocking source, observability or label mismatch. The final targeted suite passed **39/39** checks (oracle branches, exact trace/result recomputation and Research Ops pointer), and scoped closeout review returned `PASS_SCOPED_DIFF` with no outside tracked changes.

Research Ops telemetry for this task records two context wrapper events (0.4495 s total; the initial stale status is retained as one failed command), one deterministic fixture-generation command (0.1156 s), two targeted test commands (6.027 s total), and one scoped audit command (0.2468 s). These are command durations, not total task time. Agent reasoning and most writing/implementation time were not measured; model tokens are unavailable. No experiment or browser stage was run. Git delivery status is reported in the final handoff.

The stop condition is met once the offline contract, first benchmark, provenance audit and targeted tests establish this negative readiness verdict. Additional residual profiles, new physics, a Jev call or a larger matrix would be a separate decision and are not part of Phase 3B.0.
