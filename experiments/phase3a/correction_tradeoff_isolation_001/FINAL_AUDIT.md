# Phase3A.4b independent final evidence audit

Verdict: **SUPPORTED_GEOMETRIC_LOCAL_CONTRACT_CONFLICT**.

The complete prospective campaign supports a real correction-axis / historical
local-corridor conflict on the fixed16m case. It does not establish that the
first Walk8m strict failure is caused by physical instability. No evidence
integrity, frame-sign, command reconstruction or evaluator artifact was found.
No additional alpha, mission, model run, training, or scientific gate change is
recommended or performed within this audit.

## Acquisition and provenance

All sixteen predeclared executions completed before this independent audit read
the new results: ten sequence executions at alpha0/0.25/0.5/0.75/1, each twice,
and six primitive-walk-8 null controls at alpha0/0.5/1, each twice.

- Acquisition commit: `191b78ab2f6d1637cba39dec8148af8e9bfc56b4`.
- Protocol SHA: `fa90b79f6c60e00e5cf18c3b21125ae947d40f15ff4d82eaafd12c2a613d570f`.
- Case manifest SHA: `0799556722dc6a9c90841acf29e425f88e3c3c690eb5f1f3b4768d061ba961c9`.
- History manifest SHA: `cabd4333090ceb548aca70ae148b560f880794283aa81cb8f7525ba12c5c500e`.
- Official motion.pt SHA: `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
- CPU, one Torch thread, simulator seed0, MuJoCo3.15.0, timestep0.002s.

The raw primary and repeat results are the sixteen decoded rows in
`evidence/results.jsonl.gz`. Source locators use each row's immutable `run_id`,
with the first Walk at `/nodes/1`. Corresponding traces and20Hz state archives
are under `evidence/traces/` and `evidence/poses/`. `evidence_manifest.json`
binds all55 exported artifacts to encoded and decoded raw SHA values. These
are new acquisition artifacts; they do not replace the old Console video or
any historical experiment result.

## Dose response on the same sequence

Signed errors, primary executions only:

| Alpha | First8m local lateral, m | Rotation component, m | Tracking remainder, m | Final global lateral, m | Final ideal heading, deg | Endpoint norm, m | Nominal / strict / physical |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | -0.001682466 | 0 | -0.001682466 | -1.840337303 | -6.348225198 | 1.840971814 | PASS / PASS / PASS |
| 0.25 | +0.185506446 | +0.187381957 | -0.001875511 | -1.425958392 | -3.127175496 | 1.452194162 | PASS / PASS / PASS |
| 0.5 | +0.372292344 | +0.374977002 | -0.002684658 | -1.111641569 | -1.288572409 | 1.209069098 | PASS / FAIL / PASS |
| 0.75 | +0.557925852 | +0.562990317 | -0.005064465 | -0.853557332 | -0.362058931 | 1.047960075 | PASS / FAIL / PASS |
| 1 | +0.743291997 | +0.751656240 | -0.008364243 | -0.694056668 | -0.255096178 | 0.991713496 | FAIL / FAIL / PASS |

Every repeat reproduces its primary exactly. Alpha1's original nominal failure
is retained; improved final global precision does not erase it. Alpha0.75's
first8m nominal lateral margin is only0.002074m, which does not demonstrate
robust nominal reliability under untested disturbances.

The actual node-start yaw after the unchanged10s Stand is exactly
`-5.367024720986278` degrees in every sequence execution. Stronger alignment
rotates the same-origin correction axis toward commanded zero by
`0 / 1.341756 / 2.683512 / 4.025269 / 5.367025` degrees.

The old Walk terminates at measured actual-start forward progress of8m.
Independent world projections give

`y_local = x_local * tan(delta) + y_control / cos(delta)`.

The local displacement is real in world coordinates, and the old endpoint
strict limit remains0.28m. For alpha0.5, following the rotated reference implies
about+0.375m local offset; actual selected-frame tracking contributes only
-0.002685m. The same mechanism predicts the intermediate doses: their measured
tracking remainder is about1.00% and0.90% of the geometric component. Across
all positive alphas it is0.72–1.11% of that component. This is measured tracking
behavior, rather than treating the exact coordinate identity as causal proof.

The new fixed intermediate interventions, identical pretreatment states,
historical anchors and primitive null controls collectively strengthen the
reference mechanism explanation. They do not identify an optimal alpha.
Alpha0.25 improves global errors and passes strict on this case; therefore
an assertion that *any* global correction necessarily causes strict failure
would be false. The supported conflict concerns the tested alignment strength
and the fixed actual-start corridor, especially alpha0.5 and stronger doses.

## What happened physically

| Alpha | First8m max tilt, deg | First8m minimum height, m | Whole-sequence max tilt, deg | Whole-sequence minimum height, m |
| --- | ---: | ---: | ---: | ---: |
| 0 | 4.636872 | 0.762259 | 6.463656 | 0.758619 |
| 0.25 | 4.600706 | 0.762258 | 6.689050 | 0.758830 |
| 0.5 | 4.586776 | 0.762257 | 7.115372 | 0.754136 |
| 0.75 | 4.519824 | 0.762255 | 7.177925 | 0.749383 |
| 1 | 4.477100 | 0.762241 | 7.905225 | 0.748237 |

All sixteen executions are physically successful with no falls. First8m
transition standing fraction is1 in each dose. First8m correction saturation
and significant command sign-oscillation counts are zero. Its duration increases
modestly from17.080s to17.176s across the grid, without shortening a mission.

The first8m tilt/height measurements do not implicate physical instability as
the cause of strict lateral failure. Whole-sequence tilt and height do change,
and stronger alignment is not physically identical or uniformly better. These
bounded changes do not establish robustness outside this deterministic case.
Strict is an endpoint actual-start corridor score, not a fall detector and
not a continuous maximum-excursion score. Sampled20Hz path peaks remain
diagnostics separate from unchanged formal outcomes.

## Why final global heading and position improve

At a Walk, independently reconstructed endpoint heading satisfies

`e_end = wrap((1-alpha) * e_start + e_control)`.

Here `e_control` is the actual measured error relative to the selected axis;
it is not assumed zero. Relative Turn errors and Stand/Stop yaw changes are
retained as additional measured contributions. Across the three Walk nodes,
the original first-Walk inherited heading component is multiplied by
`(1-alpha)^3`.

| Alpha | First-Walk inherited yaw contribution at final, deg | Other measured heading contributions, deg | Actual final heading error, deg |
| --- | ---: | ---: | ---: |
| 0 | -5.367024721 | -0.981200477 | -6.348225198 |
| 0.25 | -2.264213554 | -0.862961942 | -3.127175496 |
| 0.5 | -0.670878090 | -0.617694319 | -1.288572409 |
| 0.75 | -0.083859761 | -0.278199169 | -0.362058931 |
| 1 | 0 | -0.255096178 | -0.255096178 |

This is an exact attribution of observed motion, not a guarantee that measured
control/Turn/Stop residuals will stay fixed under another treatment or case.

The independent world-position budget retains every node displacement and
subtracts the ideal commanded Walk displacement. For alpha0.5 minus alpha0,
final world error-vector change is `(+0.427170454, +0.728695734)` m. Its Y
contributions are:

| Node | Change in actual world-Y displacement, m |
| --- | ---: |
| Stand | 0 |
| Walk8m | +0.372373943 |
| Turn-90 | +0.010883448 |
| Walk4m | -0.024914178 |
| Turn+90 | +0.001660897 |
| Walk4m | +0.355614072 |
| Stop | +0.013077552 |

The first and last Walk explain most of the lateral improvement; downstream
Turn/Stop translations remain in the budget. The larger positive X endpoint
error is also retained, rather than hidden by reporting only lateral error.
Alpha0.5 reduces absolute final lateral39.596%, heading79.702% and endpoint
norm34.324% versus alpha0, while preserving its strict failure.

## Independent integrity and arithmetic checks

The independent audit used direct JSON/gzip/NumPy reads and world-coordinate
arithmetic after campaign completion. It did not call a policy, simulator,
optimizer or evaluator, run additional tests, or edit completed evidence.

- Exact predeclared16-run membership, with8 primary and8 repeat records.
- All55 exports match encoded SHA, byte size and decompressed raw SHA.
- All8 full scientific record, command-trace and retained-pose repeats match
  exactly, including their stream hashes, final policy tensors and RNG receipts.
- All10 sequence first-Walk start states match exactly.
- All6 primitive executions have identical poses, applied commands, final
  states, final tensors and observer/RNG receipts; nominal/strict/physical PASS.
- All records share the same provenance. Protocol/case/history SHA values and
  all captured producer source hashes match current immutable acquisition bytes.
- Reward calls, optimizer updates and checkpoint writes are zero in every run.
- Independently reconstructed all4,482 retained walking command samples:
  maximum command/lateral/heading arithmetic discrepancy is zero for the stored
  values. This covers10Hz traces, not every500Hz command call.
- Maximum endpoint rotation error: `1.3877787807814457e-16` m.
- Maximum telescoping world error-vector budget error:
  `5.551115123125783e-16` m.
- Maximum per-node heading recurrence error:
  `1.429412144204889e-15` rad; whole-sequence heading-budget error:
  `1.1102230246251565e-16` rad.

These errors are floating-point audit differences, not new task thresholds.
The pre-acquisition audit verified all1,519 prior file pins and frozen Console
assets; the separate campaign completion retains before/after integrity checks
and historical anchor checks. No old negative result is replaced.

## Research conclusion and stopping boundary

The dominant mechanism is the intentional reference/corridor semantics:
correction heading and lateral axes rotate together while the old actual-start
local measurement and termination stay fixed. The robot tracks the selected
axis closely; the resulting world displacement can improve ideal-route
precision and depart from the old strict corridor simultaneously.

This is not an accidental isolated outcome, but the evidence is deterministic
reproducibility and fixed-case dose response, not independent-seed statistics,
blind generalization, a universal local-stability trade-off, or a selected safe
alpha. No hidden scoring modification, PPO reward change, gain change, UI
intervention or model retry is required to explain the result.

Research Console remains the frozen read-only visual explanation surface.
This audit creates only this new document. It does not modify Console or its
existing media, start an additional replay, recommend an alpha for training,
or change any historical readiness gate. Phase3A.5 remains paused; stop here.
