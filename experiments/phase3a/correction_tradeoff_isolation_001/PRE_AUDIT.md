# Phase3A.4b independent mechanism pre-audit

This document is a read-only pre-acquisition review. It examines retained
historical records and command traces; it does not run a policy or simulator,
rescore historical outcomes, alter an envelope, or select an optimal alpha.
The new protocol and acquisition manifest are the authority for new membership,
execution order, source hashes and final results.

## Preflight finding

No fundamental implementation or evaluator error was found in the frozen
`sequence-mixed-16m` alpha0, alpha0.5 and alpha1 records. The first8m strict
failure is a real displacement relative to the historical actual-start local
corridor. Existing evidence does not demonstrate loss of upright physical
stability. The most precise hypothesis is a correction-axis / local-corridor
contract conflict.

The local frame is recreated from the actual node-start pose. The walking
correction uses the same origin but a wrapped interpolated heading. The
unchanged Walk skill terminates when progress along the actual-start forward
axis reaches the full target distance; its tolerance is not an earlier stop
condition. Scoring retains this same actual-start frame. Ideal route diagnostics
use the distinct commanded heading and planned origin.

## Independently reconstructed historical evidence

The source is the unique primary record for each alpha and case in
`experiments/phase3a/heading_alignment_strength_001/evidence/results.jsonl.gz`,
with each corresponding `primary--<reference_mode>--sequence-mixed-16m`
command trace. These are previously seen mechanism/regression data.

All three arms enter the first Walk from the exact same Stand end state:
position `(0.11200944697231176, -0.18594415169729253)` m and yaw
`-5.367024720986278` degrees. Let `delta` be correction heading minus actual
start heading, `x_local/y_local` the independently projected actual displacement,
and `y_control` its projection onto the correction frame. Then

`y_local = x_local * tan(delta) + y_control / cos(delta)`.

| Alpha | Delta, deg | Local lateral, m | Geometric component, m | Tracking remainder, m |
| --- | ---: | ---: | ---: | ---: |
| 0 | 0 | -0.001682466450 | 0 | -0.001682466450 |
| 0.5 | 2.683512360493 | +0.372292344021 | +0.374977001629 | -0.002684657608 |
| 1 | 5.367024720986 | +0.743291996918 | +0.751656240018 | -0.008364243100 |

The identity residual is at most `1.1102230246251565e-16` m. In alpha0.5 the
actual control-frame lateral error is only `-0.0026817135831306294` m. Its
positive local displacement follows the rotated correction axis while the
frozen strict envelope still constrains the old local axis. First8m limits are
nominal `0.56` m and strict `0.28` m. Alpha0.5 remains nominal PASS / strict
FAIL, and alpha1 remains nominal FAIL / strict FAIL.

This decomposition is an exact coordinate identity, not by itself an
independent causal confirmation. The testable mechanism is that real trajectories
closely track each selected correction axis, giving a small measured tracking
remainder relative to the geometric term. New predeclared intermediate doses
test that prediction. Full-sequence global errors are separate measured outcomes;
the identity does not predict all later Turn/Walk/Stop dynamics.

Independent reconstruction from world positions, quaternions, correction
headings, gains `1.5/1.0`, deadband `0.01` and clamp `0.6` reproduces all
`1,037` logged walking command samples in the three retained sequence arms.
The maximum arithmetic difference is `2.9976021664879227e-15`. This found no
feedback-sign, projection, wrapping or annotation artifact in those samples.

| First8m physical diagnostic | Alpha0 | Alpha0.5 | Alpha1 |
| --- | ---: | ---: | ---: |
| Max tilt, deg | 4.636871606 | 4.586776413 | 4.477100058 |
| Minimum height, m | 0.762259246 | 0.762256711 | 0.762241033 |
| Transition standing fraction | 1 | 1 | 1 |
| Falls | 0 | 0 | 0 |
| Correction saturation count | 0 | 0 | 0 |

These diagnostics do not support calling the strict failure a physical
instability. They also do not establish a universal stability guarantee.

## Minimal new experiment review

The proposed small campaign has sixteen executions: the same frozen16m sequence
at a predeclared coarse alpha grid `0, 0.25, 0.5, 0.75, 1`, each executed twice,
plus `primitive-walk-8` null-control arms at alpha `0, 0.5, 1`, also twice.
These are ten sequence and six primitive executions. No additional mission family,
finer alpha search, training, reward, controller or envelope change is needed.

Historical anchors and shared Stand state must be checked before expanding to
the two new doses. The first8m prefix within each full sequence supplies the
cleanest mechanism isolation, because all arms share an identical pretreatment
state. It does not require restarting from an injected state or changing the
mission. Later nodes inherit treatment-induced pose changes and therefore
cannot be treated as independent common-start interventions.

The primitive null control starts with actual and commanded headings equal.
Reference interpolation should initially be a no-op; identical full primitive
execution is stronger evidence against an adapter artifact. A nonidentity must
be retained and investigated before further expansion.

The old heading selector permits only alpha0/0.5/1. New doses require a new,
separate selector with predeclared membership. The old selector, its protocol,
all historical source/evidence and scientific configuration must remain
byte-identical. Endpoint recipes should preserve alpha0 and alpha1 exactly.

## Interpretation and stopping rules

- Strict scoring is endpoint local lateral displacement, not continuous maximum
  corridor excursion. Any continuous trajectory maxima are new diagnostics,
  explicitly separate from unchanged scientific outcomes.
- Repeated identical MuJoCo executions establish deterministic reproducibility.
  They are not independent stochastic seeds or statistical generalization:
  the simulator stores its seed but does not randomize the reset state or
  physics in this harness.
- The coarse grid must not become a search for a better passing alpha. An
  intermediate dose might improve global errors and satisfy strict constraints;
  that would qualify any claim of an unavoidable trade-off rather than license
  tuning or retrospective treatment selection.
- Prefer the statement "local corridor / global correction trade-off" unless
  new tilt, height, fall or tracking evidence supports a separate physical
  stability claim. Small tracking remainder and smooth geometry alone do not
  prove robustness outside this fixed case.
- Stop expansion upon baseline/history drift, failed historical-anchor identity,
  mismatched shared Stand state, null-control nonidentity, or independently
  unreconstructable frame/feedback/scoring arithmetic. Retain negative artifacts.
- Console is only a read-only observer of its already frozen visual replay.
  Neither its displayed diagnostics nor replay media are the evaluator for
  this new campaign. This study adds no UI or live training observer.

## Source pointers

- `src/g1swarm/heading_alignment/experiment.py:47` — immutable-origin wrapped
  heading interpolation and exact endpoint recipes.
- `src/g1swarm/segmentation/mission.py:38` — world-to-frame projections.
- `src/g1swarm/skills/basic.py:252` — actual-start Walk axis and full-distance
  stopping condition through line279.
- `src/g1swarm/transition_learning/env.py:230` — actual local scoring and
  separate ideal diagnostics through line270.
- `src/g1swarm/transition_learning/env.py:289` — node-start local frame and
  planned route updates through line311.
- `src/g1swarm/control/path_correction.py:112` — heading/lateral feedback,
  deadband and command clamp.
- `src/g1swarm/boundary/envelope.py:128` — unchanged strict limits;
  endpoint evaluation at line65 and physical predicate at line137.
- `src/g1swarm/simulation/g1_simulation.py:125` — deterministic reset with seed
  storage and no initial-state randomization.

No historical files, policy parameters or machine results were modified by
this pre-audit.

## New implementation pre-acquisition review

The separate new `tradeoff_isolation` module was inspected before any new
acquisition. It delegates the original runner, skill bodies and correction
arithmetic, preserves exact alpha0/alpha1 recipes, and reuses the unchanged
Console's offline state-copy observer. Rendering and UI are absent from physics.
The historical record comparison removes explicit experiment/publication
metadata and wall clocks while retaining states, parameters, reference modes,
control diagnostics and outcomes; complete historical traces are compared
without this normalization.

Read-only `verify_experiment()` passed all `1,519` pre-existing file pins,
including Console's `34` retained visual assets and `13` source files. Protocol
SHA is `fa90b79f6c60e00e5cf18c3b21125ae947d40f15ff4d82eaafd12c2a613d570f`.
All six unique historical record/trace anchors exist with the correct case,
alpha and source label. Sequence alpha0/alpha0.5 use decoded rows26/52 of the
frame experiment and alpha1 uses row78 of the heading experiment; primitive
anchors use rows19/45 and row71 respectively.

As a read-only compatibility check, the new `audit_one_run` analyzed the
already retained Console alpha0 and alpha0.5 poses with their original source
records/traces. It passed `13,695` and `13,724` checks respectively, with no
failures and no policy or simulator calls.

One orchestration issue was identified before acquisition: full collection
analysis requires all sixteen runs and cannot serve as the interim single-run
stop gate. The campaign must instead call `audit_one_run`, then enforce paired
repeatability, common first-Walk start and primitive null-control equality
before authorizing the new doses. This is a pre-acquisition harness correction,
not a scientific outcome adjustment. Completion of that correction is a
condition of proceeding; no underlying scientific fault was found by this
source review.
