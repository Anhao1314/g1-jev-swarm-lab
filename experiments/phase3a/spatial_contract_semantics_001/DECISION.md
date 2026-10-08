# Phase 3A.4c — Spatial Contract Semantics

Verdict: **DECIDED_FOUR_INDEPENDENT_SPATIAL_CONTRACTS**.

Use fixed mission-world route error as a **constrained optimization objective**;
retain the historical actual-start local endpoint envelopes as **independent
eligibility constraints**; treat controller-reference tracking as a **subordinate
diagnostic**; retain physical execution as a **mandatory independent constraint**.
No score can cancel another ledger's failure. This is a semantics decision,
not an implemented evaluator, controller or PPO reward change.

## Decision and claim boundary

| Contract | Optimize / constrain / measure | Frame and time authority |
| --- | --- | --- |
| Global route | Optimize ordered route/endpoint accuracy; retain XY vector, norm, along/cross and heading | Frozen mission initial world pose plus commanded node chain; per-phase and final targets |
| Fixed local | Constrain original skill completion and nominal/strict endpoint envelopes independently | Actual origin/heading latched once at the original node boundary; fixed within that node |
| Reference tracking | Measure selected-axis tracking, applied commands and residual; optional subordinate objective | Explicit deterministic reference origin/heading/selector, never actor-selected scoring geometry |
| Physical execution | Constrain finite/valid/upright execution and preserve completion/status | Original full-step execution checks and summaries, independent of geographic frames |

The current task gate remains **nominal**; strict retains its independent
predicate and mandatory disclosed outcomes. A future experiment must freeze its
claim and profile before acquisition. A nominal-bounded global improvement can
coexist with strict FAIL and must say so. A **strict-corridor-preserving** claim
requires the unchanged strict endpoint contract as well. Neither claim certifies
continuous or environmental corridor containment. A candidate outside the
required profile remains an improvement outside eligibility, never aggregate
PASS obtained by reward weighting or a favorable profile switch.

The machine-readable companion is `contract.json` (`SC-3A.4c-001`). It defines
authority and claim rules; it is explicitly **not runtime configuration** and
introduces no global PASS threshold, tracking tolerance or reward weights.

## What the existing local corridor actually means

The same `MissionFrame` type is used in several contexts; its class-level
mission-frame description is not the authority for this runner. In
`transition_learning/env.py`, `self.frame` is built from actual state at **each
node start**. Walk termination and the retained envelope both use that frame.
Reference selection changes the controller error axes without changing it.

The historical Walk acceptance region is a **terminal** distance/lateral/heading/
time envelope. For 8m it retains:

| Profile | Absolute forward error | Absolute lateral | Absolute local heading | Completion time |
| --- | ---: | ---: | ---: | ---: |
| Nominal | 0.8m | 0.56m | 15° | 48s |
| Strict | 0.4m | 0.28m | 8° | 40s |

These numbers are copied from existing source/results, not selected here.
Original successful skill completion and physical predicate still apply.
Walk envelopes must not be applied to Turn, Stand or Stop; their original
skill parameters/status remain authoritative.

This local constraint is fixed **within a node**, but its anchor can differ
between treatments after genuine upstream motion. It is not a common world
wall or obstacle corridor. Keep node latch event, actual origin/yaw and the
upstream Stand/Turn/Stop displacement and global error. Do not permit actors
to insert a new alignment stage, split nodes, or reset the scoring anchor.
A legitimate upstream improvement changes later local state; it does not
redefine the mission-world target or establish clearance.

Endpoint PASS cannot prove that the entire path was inside the same lateral
band. A synthetic path `(0,0) → (4,1) → (8,0)` passes the lateral endpoint
condition and leaves both bands en route. Even all 20Hz samples inside a band
cannot exclude an excursion between samples. An outside sample can refute
containment; an inside sampled maximum is only a lower bound on the true
maximum. The retained 500Hz state digest is not a recoverable 500Hz trajectory.

Any future environmental or all-path corridor claim needs a separately
declared geometry/footprint, boundary time, coverage and evaluator version.
That missing capability is recorded here; it does not justify retroactive
rescoring or new acquisition for this semantics question.

## Ordered world route is exogenous to behavior

Let the mission anchor be `(q₀, θ₀)` from the frozen initial pose. A commanded
Walk advances `q` by `D(cos θ, sin θ)`; a relative Turn advances `θ` by its
commanded angle. Stand and Stop leave the commanded target unchanged.
Actual translations during Stand, Turn and Stop therefore remain world error.
Each node has its own designated commanded phase/segment, never the nearest
arbitrary segment selected after observing the trajectory.

Keep per-node terminal world error `p_end − q_end`, its norm and signed
along/cross components, plus wrapped terminal heading error. Keep ordered
node completion and the final vector/norm. Walk line cross-track does not
replace along-route progress. Turn relative-angle error is separate from
world terminal heading error; raw transition yaw contains intended rotation.
No time-parameterized ideal Turn motion is invented by this decision.

Final lateral can improve while X error worsens, or earlier route errors cancel.
The retained α=0.5 versus α=0 example changes final error from
`(+0.048330, −1.840337)m` to `(+0.475501, −1.111642)m`.
Its norm improves, but its X component worsens. Retain both facts. No scalar
weighting or alpha preference is chosen here.

## Two distinct incompatibilities in the real retained case

Source: Phase 3A.4b `primary--alpha0.5--sequence-mixed-16m`, decoded result
**line 2**, JSON pointer **`/nodes/1`**. The 10s Stand ends at
`(+0.112009447, −0.185944152)m`, yaw **−5.367024721°**. The local frame locks
there. The correction heading is **−2.683512360°** (rotation +2.683512360°).

At the original Walk endpoint:

- Actual-start `(x_L,y_L) = (8.000293915, +0.372292344)m`.
- Reference lateral `y_R = −0.002681714m`.
- Original nominal **PASS**, strict **FAIL: EXCESSIVE_DRIFT**, physical **PASS**.

**First: zero reference tracking and strict local acceptance conflict.**
For the same origin and `δ = wrap(θ_R − θ_L)`:

`y_R = −x_L sin δ + y_L cos δ`

`y_L = x_L tan δ + y_R / cos δ` when `cos δ ≠ 0`.

Zero reference lateral at the measured progress predicts
`y_L = +0.374977002m`. To satisfy the fixed strict lateral bound at that same
progress, reference lateral must lie in
**`[−0.654258747, −0.094872849]m`**. The observed −0.002681714m lies outside.
Intentional reference deviation is therefore necessary for a compliant
endpoint at this progress; its existence is not automatically controller error.
For general origins use the full SE(2) translation and rotation rather than
silently assuming coincident anchors. Near perpendicular axes use the linear
transform directly, not the divided tangent expression.

If a separately declared tracking band were `|y_R| ≤ ε`, its intersection
with `|y_L| ≤ b` at a fixed `x_L` exists exactly when
`|x_L sin δ| ≤ b |cos δ| + ε`. This is a geometry relation, **not a new
tracking threshold or an alpha-selection rule**; no ε is chosen here.

**Second: exact global first-waypoint attainment and the local box conflict.**
The commanded first waypoint `(8,0)m` projects into the locked actual-start
frame as **`(7.836016953, +0.922934724)m`**. Its lateral coordinate lies
outside both original bands. Exact first-waypoint accuracy is consequently
incompatible with either band at this already acquired start state.

Minimizing position error over the original endpoint acceptance rectangles
gives these **relaxed geometric lower bounds**:

| Profile | Closest local-box point to the ideal waypoint | World position error lower bound |
| --- | --- | ---: |
| Nominal | `(7.836016953, +0.56)m` | 0.362934724m |
| Strict | `(7.836016953, +0.28)m` | 0.642934724m |

These bounds ignore heading/time, the frozen Walk stop-at-8m lifecycle,
intermediate path and dynamics. In particular the box minimizer has forward
7.836m and is **not** a demonstrated endpoint of the current Walk, which
terminates only on actual-start progress reaching 8m. A relaxation lower bound
is not a reachable trajectory, optimum policy or future mission-level bound.
Do not insist that every objective reach zero when the hard constraints
exclude zero. Global accuracy remains an objective over the admissible set.

This does not establish that all global improvement conflicts with strict:
the retained α=0.25 case improves final world precision and passes strict.
It is a counterexample to universal impossibility, not an operational choice.
Nor does static geometry prove that the frozen base policy, bounded residual
and 2s activation window can recover strict compliance. Keep three levels
separate: endpoint feasibility, all-path geometry, dynamic authority.

## Physical proxy stays independent

The original simulator checks finite qpos/qvel and valid finite control at
each step. Original fall/standing criteria, full-step tilt/height summaries,
skill status, transition diagnostics and completion remain independently
auditable. The current frozen config defines fall below 0.45m or above 65°
tilt; standing requires height at least 0.55m and tilt at most 30° without a
fall. These are simulator proxies, not contact or collision certificates.

A historical node `physical_success` can retain physical survival under
TIMEOUT while task completion fails; the original sequence field also
requires all prescribed nodes to have executed. Keep those source semantics
and separately show status/completeness. A corridor violation is not a fall,
and upright execution is not mission success. Good geometry or return cannot
compensate a physical violation or missing execution.

## Candidate decisions and counterexamples

| Candidate | Decision | Decisive evidence / limitation |
| --- | --- | --- |
| Move task acceptance into reference frame | Reject | Real α=0.5 tracks reference near zero and still violates locked strict; rotation would erase negative evidence |
| Optimize/report only final world endpoint | Reject as sole contract | Synthetic waypoint cancellation, skipped nodes and endpoint-return paths hide route/constraint violations |
| Retain local endpoint success as the entire objective | Reject as sole contract | Real α=0 passes locally while inheriting mission-world yaw/error; local anchor resets do not resolve global drift |
| Treat physical survival as task success | Reject | All 16 retained executions are physical PASS, including nominal/strict failures |
| Four independent contracts with constrained global objective | **Accept** | Explains all retained outcomes without relabeling and exposes incompatible zero targets rather than concealing them |

`analysis.json` retains **12** explicitly typed counterexamples: one real
score-substitution case; endpoint-return, temporal aliasing, final cancellation,
along-track masking, origin reset, upstream yaw laundering and intended Turn
rotation; logical fall masking, TIMEOUT survival and waypoint skip; and the
derived nonzero-tracking requirement. Synthetic geometry/logical examples are
not new robot rollouts or scientific gold samples.

## What a future learned residual must know

**Optimize:** fixed world-route/endpoint errors, with ordered phase identity and
component tradeoffs retained. **Constrain:** unchanged physical execution,
original skill lifecycle/completion and the predeclared nominal/strict local
profile. **Measure:** controller reference errors, commands/residual, transition
geometry, both local profiles and physical summaries independently.

Reference origin/heading/selector, mission targets and node latch rules are
outside residual authority. Reference-relative tracking and effort may be
auxiliary objectives only when subordinate to the required spatial constraints.
No finite reward bonus may turn a constraint violation into an eligible PASS.
The numerical reward, observation sufficiency, implementation of constrained
learning and dynamic attainability remain later questions, not this decision.
Each learned treatment must still compare with its own same-reference
residual-off baseline; deterministic reference gain is not PPO gain.

## Evidence, validation and stopping

- Offline protocol frozen before calculation: `protocol.json`, SHA
  `be66b8b88f84be9f8c05f8e6d1a3d83096611a4baf5d3a2aac768c3e06584afb`.
- Study base commit: `2bc3e440d900af3c6f4f5f6786e5b0515e3da150`;
  protocol publication: `2a434ec9cc5a638778fd68769e163e05048c5dac`.
- Reused acquisition commit: `191b78ab2f6d1637cba39dec8148af8e9bfc56b4`;
  Phase 3A.4b publication: `c244ae75bd390255f4b99345c2415016288a81b6`.
- Original protocol SHA: `fa90b79f6c60e00e5cf18c3b21125ae947d40f15ff4d82eaafd12c2a613d570f`;
  case SHA: `0799556722dc6a9c90841acf29e425f88e3c3c690eb5f1f3b4768d061ba961c9`;
  base policy SHA: `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
- `source_manifest.json` binds 72 retained input files. `validation.json`
  verifies all 55 encoded/decoded exports and all 16 source rows; 721 numeric
  checks and 578 predicate checks pass, maximum roundoff 5.274e−15.
  These are offline arithmetic/integrity checks, not new simulations or
  a full-regression/unit-test count. Original labels are verified and copied.
- Reproduce offline only into a new output directory:
  `.venv\Scripts\python.exe experiments/phase3a/spatial_contract_semantics_001/analyze.py --output NEW_DIRECTORY`.
  The script imports only the standard library and refuses to replace receipts.
  Its exact bytes/execution-base identity are bound in `validation.json`.

Remaining blockers for **this decision**: none. Continuous/environmental
containment coverage, dynamic attainability and learned reward implementation
remain explicitly unproven; they are not reasons to expand this semantics task.
The prior initial primitive observer metadata gap remains recorded in the
unchanged Phase 3A.4b integrity receipt; endpoint reasoning does not depend on it.

**Stopping reason:** retained acquisition, exact source arithmetic, geometric
counterexamples and independent source/adversarial review distinguish the
candidate contracts reliably. New physics would not change the definition or
repair missing historical temporal coverage. Budget consumed: **0 new physics,
0 training, 0 provider calls**. No alpha selected, no historical score/threshold/
artifact changed, no Console change. **Stop; Phase 3A.5 remains paused.**
