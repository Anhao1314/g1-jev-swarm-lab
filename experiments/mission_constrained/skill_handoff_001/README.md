# Skill Handoff Research — one prospective speed-schedule test

**DESIGN_AND_OFFLINE_COMPONENT_FREEZE_NOT_ACQUISITION_READY**

This package selects and freezes a minimal, worthwhile physical question. It has
no physical entry point, no Owner grant, and no complete execution Readiness.
The source commit is a **design/component identity**, not `C_exec`.

## Scientific decision

Test whether one terminal-distance speed schedule improves the complete original
Walk-to-Turn handoff. Preserve the original world waypoint and all local gates.
Do not continue alpha search or PPO training. Do not insert Stop after the target
and count only the smaller subsequent Turn displacement as improvement.

The sealed Stand5 fixed-alpha0.25 prefix exits Walk at 0.493424m/s, with 0.346687m
world waypoint error. At the end of the subsequent Turn the error is 0.604084m.
The previous two-arm experiment remains **NO_JOINT_SUPPORT**; no historical label
or outcome changes here.

Independent historical support for the input range exists in
`experiments/baselines/g1_skill_characterization_001/report.md`: the 0.25m/s
approach command had about 0.261m/s actual velocity and 0.100m subsequent Stop
distance, versus 0.484m/s and 0.188m at the 0.5m/s command. These are different
protocols/skills and cannot become outcome cells for the proposed Turn study.
They support a plausible input choice, not this new profile's physical success.

## Frozen candidate

Same seen seed-0 state, alpha0.25, original `Stand5 → Walk8 → Turn−90` **prefix**:

- Constant: original 0.5m/s.
- Terminal schedule: original first 7m, then linear decrease by remaining
  original-entry distance to 0.25m/s at 8m. No alternate profiles or retries.

The first 1m lead length is a prospective mechanism choice larger than the
approximately 0.38m observed Turn footprint, not a measured braking distance or
optimized cutoff. Ideal kinematics adds `4*ln(2)-2 ≈ 0.773s`; real time and gait
response are unknown. Keep original 8m termination and frame, policy, PD, alpha,
controller reset semantics, Turn angle/rate and 0.5s settle. No task node splitting,
new reanchoring, simulator state injection, or compensation waypoint.

The adapter calls existing fixed-alpha correction with changed forward command,
using the **original skill frame** for remaining distance. It neither alters
the reference angle nor replaces the low-level policy. The original correction
sample records the scheduled vx. Old nominal-command tracking diagnostics are
not the new treatment's effectiveness score; retain original and scheduled
commands separately. Future collector must verify this complete path.

## What would count as evidence

Full details and units are frozen in `protocol.json`.

1. Confirm **measured** mean speed over the final 0.5s of Walk decreases by at
   least 0.1m/s; report instantaneous speed too. A changed command is insufficient.
2. Require complete original strict/physical pass, no worse Walk waypoint norm,
   Turn-end waypoint norm improvement of at least 1cm, no worse absolute Turn-end
   X/Y/heading or instantaneous exit speed, and no more than 2s extra prefix time.
3. Report full Walk and Turn motion, signed components, attitude, reset/counter and
   native-state evidence. Include all movement during deceleration. Original node
   limits remain unchanged. New mechanism thresholds are prospective practical
   screens, not significance claims or rewritten historical gates.
4. Missing native measurements or technical interruption prevent support; preserve
   already observed physical/strict failure simultaneously. Native mean-speed
   calculation rejects even one missing 0.002s sample inside its fixed window.

The 1cm criterion follows the preceding study's practical comparison scale;
0.1m/s demands a substantial measured change relative to the 0.25m/s command
reduction. The 2s time allowance is a declared cost ceiling, not a prediction.
These choices must not move after acquisition.

Two arms falsify this specific scheduling package. They do **not** isolate scalar
speed as the unique mediator: time, phase, posture and joint state change too.
They do not prove superiority to constant slow walking, completion of the remaining
Mission, cross-state generalization, or hardware safety. A uniform-slow comparison
is required before making an adaptive-over-fixed-rule claim.

## Implemented and checked, without physics

- `handoff.py`: bounded rule, original-frame correction adapter, complete-window
  speed measurement, and explicit multi-axis outcome classification.
- `test_handoff.py`: **20/20** final tests. Includes unchanged production
  `_Controller` statements extracted by AST, using a recording fake base, verifying
  the vx path, yaw preservation, Turn bypass, reset behavior and observer error
  propagation. It proves a local call contract, not full backend equivalence.
- `offline_review.py`: hashes three sealed raw inputs and eleven retained source
  references, then evaluates the rule on 171 historical command states. Before
  7m the rule leaves observed forward commands unchanged. It generates no
  counterfactual trajectory or new physical outcome.
- Native speed-window evidence is **not available** in retained 20Hz poses. Both
  future arms must record it; no interpolation fills that historical gap.
- Independent review found sparse-window acceptance in the first implementation.
  `review-gap-before-fix.json` retains the two-point acceptance (0.375m/s).
  The max-gap correction and missing-sample tests close it. Initial 19/19 and
  final 20/20 receipts are both retained; initial PASS did not establish coverage.
- A rejected Research Ops stage name prevented one wrapper invocation; it is
  retained in `tool-failure.txt`. No scientific operation was attempted.

Run nonphysical checks from the repository root:

```text
python -B experiments/mission_constrained/skill_handoff_001/test_handoff.py
python -B experiments/mission_constrained/skill_handoff_001/offline_review.py --raw-root <sealed-stand5-directory> --output <new-json-file>
```

The output file must not exist. No asset restore, model import, environment install,
physics, inference or training is needed. Historical bytes are referenced, not copied.

## Why this is not Acquisition Ready

The previous Stand5 runner binds a full seven-node selected/fixed experiment,
including seven-node completeness and its original source/Readiness. It cannot be
used unchanged as a three-node speed-treatment entry. This package deliberately
does not duplicate that collector or claim an AST test validates its lifecycle.

Before an Owner physical request, the following are required:

- minimally bind this component and prefix to the retained serial acquisition
  machinery; preserve all original controller/evaluator source bytes;
- implement independent raw scoring and replay/pairing checks, including native
  velocity coverage and pre-intervention state/policy identity;
- test partial failure retention and full-lifecycle cutoff/cleanup through the real
  guarded entry using a nonphysical backend;
- freeze **new** full `C_exec`, Source/Readiness, assets, dependency/environment
  identity and exact field comparisons. Historical Stand5 Readiness is not reusable
  as this new experiment's permission or identity.

Future proposed authorization: **two prefix executions, one per arm**, at most
32,000 native attempts each / 64,000 total; 120s each / 240s total wall time with
235s outer cutoff including cleanup. The 31,750-step nominal worst-case ceiling
includes Stand5 + Walk48 + Turn10 + settle0.5 at 0.002s. These are proposed caps,
not authority. Physical, technical, integrity or budget failures stop the campaign;
no retries, new profiles or hidden resets. Ending a process is not a physical-safe
stop claim. The unexecuted rest of the Mission remains untested.

## Closeout

Independent review supports this narrow design and, after the native-gap fix,
its offline components. Stop at this design/component freeze. No physical result
is claimed; all previous M2.4, M2.5A, T2a and Stand5 decisions remain unchanged.
Research Ops selection pointer is unchanged. Measured check times and unavailable
phases/token costs are recorded without inferring efficiency benefits.
