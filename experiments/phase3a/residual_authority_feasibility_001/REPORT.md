# Phase 3A.4d — Residual Authority Feasibility Gate

Scientific verdict: **INCONCLUSIVE**. Evidence integrity: **PASS**.

No constructive strict-preserving global-improvement witness was found in the
six predeclared deterministic profiles. Their early steering effects are real,
but the original correction subsequently brings the robot back toward its
selected reference; insufficient endpoint offset remains to satisfy strict.
This is not a proof that the entire continuous residual authority is infeasible.
There is no validated full-space reachability certificate. Stop at this gate;
**Phase 3A.5 remains paused**.

## Frozen question, claim and authority

One seen mechanism case: original `sequence-mixed-16m`, fixed **α=0.5**,
actual node-start origin and frozen midpoint reference selector. It contains
Stand10s, Walk8m, Turn−90°, Walk4m, Turn+90°, Walk4m, Stop. No alpha selection,
task alteration, alignment stage, new controller gains or evaluator change.

The primary claim was frozen as **strict endpoint eligibility across every
original node**, with complete original physical execution and skill SUCCESS.
Nominal and physical outcomes are independent reports. The paired global
condition requires final commanded-world endpoint norm to decrease, with
absolute final commanded-axis lateral and wrapped heading errors not worsening
relative to **its own α=0.5 residual-off baseline**. Full XY and every node's
world geometry remain disclosed. This is a terminal-accuracy claim, not
all-prefix/all-component Pareto dominance or continuous corridor safety.

The retained authority is unchanged:

- Normalized action in `[-1,1]^3` adds body-command residual
  `(Δvx, Δvy, Δyaw-rate)` bounded by `(0.1m/s, 0.06m/s, 0.12rad/s)`.
- Action is selected every 50 physics steps (0.1s) and held between decisions;
  base policy period is 0.02s, physics timestep 0.002s.
- Original eligible transition pairs, node-boundary resets and **first 2s**
  activation mask apply. Total applied yaw retains the ±0.6rad/s clip.
- Deterministic probes return nonzero action only for the original first Walk
  (node1, Stand→Walk). All later eligible windows use zero action. First Walk
  is a necessary gate: later actions cannot repair its already acquired FAIL.

The original learned-path injection branch is reused with `optimizing=False`.
Its legacy `treatment="learned"` / `learned_policy_configured` fields identify
the injection route and configured callback, **not a trained actor**. The
per-run audit labels the actor `DETERMINISTIC_BOUNDED_PROBE_NOT_TRAINED`.
Original dense reward is evaluated by that callback path and ignored, not
removed or tuned. There are no optimizer calls or new checkpoints.

## Prospective execution and controls

Protocol, case, source pins, acquisition/audit code and targeted tests were
committed before the first physics call at
`923e0bb0033d31901a4bfec94ce130f393a4530c`.

Order was frozen: residual-off replay, zero callback, six fixed probes, then
one confirmation. A qualifying first witness would have been repeated and
optional remaining probes skipped. With no witness, the **combined inward**
profile was repeated as declared before acquisition; no result-based choice
of a favorable treatment or additional scan occurred.

| Profile | First-Walk normalized action / schedule |
| --- | --- |
| off | Original residual-off route |
| zero | Original injection route, action `(0,0,0)` |
| lateral inward | `(0,−1,0)` for 0–2s |
| yaw inward | `(0,0,−1)` for 0–2s |
| combined inward | `(0,−1,−1)` for 0–2s |
| forward/inward corner | `(1,−1,−1)` for 0–2s |
| late combined inward | `(0,0,0)` first 1s, `(0,−1,−1)` second 1s |
| yaw-return/lateral inward | `(0,−1,−1)` first 1s, `(0,−1,+1)` second 1s |

Schedules are original decision ticks 0–19; onset/switch1s is tick10.
The original elapsed-time active mask remains the ultimate authority.

Residual-off matches the historical Phase 3A.4b scientific record and complete
command, torque, observation/action and physics streams exactly. Zero injection
matches off science, commands, torques, base observation/action and all physics
states exactly. Residual-observation active flags and original reward callback
counts differ intentionally; they do not establish a physics difference.

All probes have identical pretreatment Stand, first-Walk actual state and
first-Walk reference. Later actual-start anchors can change through genuine
upstream motion; the selector rule and latch boundary remain unchanged.

## Actual results

All **9/9** executions are complete, original skill SUCCESS, physical PASS and
nominal PASS. All **9/9** retain first-Walk strict FAIL (`EXCESSIVE_DRIFT`);
every other node remains strict PASS. Primary profiles only below, with zero
identical to off. No repeat is counted as an independent statistical sample.

| Profile | Walk8 local lateral, m | Final endpoint norm, m | Final absolute heading, ° | Endpoint delta, mm | Paired global condition |
| --- | ---: | ---: | ---: | ---: | --- |
| off / zero | 0.372292344 | 1.209069098 | 1.288572409 | 0 | Baseline |
| lateral inward | 0.371605554 | 1.192228406 | 1.030006506 | −16.841 | PASS |
| yaw inward | 0.370930196 | 1.194035588 | 1.038372374 | −15.034 | PASS |
| combined inward | 0.369652203 | 1.206914955 | 1.087747868 | −2.154 | PASS |
| forward/inward corner | 0.362656910 | 1.196980401 | 0.937640249 | −12.089 | FAIL |
| late combined inward | 0.371083669 | 1.203356430 | 1.255834419 | −5.713 | PASS |
| yaw-return/lateral inward | 0.370435630 | 1.213418084 | 1.368857909 | +4.349 | FAIL |

Strict8m lateral remains **0.28m**. Baseline gap is **92.292mm**. The largest
observed local reduction is **9.635mm**, closing **10.44%** of that gap and
leaving **82.657mm**. This describes the measured range, not selection of an
optimal controller. That profile worsens final absolute global lateral by
**39.155mm**, so it fails the predeclared global condition despite norm and
heading improvements. The yaw-return profile worsens endpoint, lateral and
heading; its negative result is retained.

Four of six primary profiles pass the paired global condition. **Zero of six**
pass strict or the joint gate. Global gain never compensates strict failure.
The repeated combined result matches record, trace, decisions, poses, physics,
command/reward/observation streams, final runtime tensors and RNG exactly.

## Dynamic mechanism and measured authority gap

The residual has genuine steering authority during its window:

| Profile | Reference lateral at 2s, m | Reference lateral at Walk end, m | Fixed local lateral at Walk end, m |
| --- | ---: | ---: | ---: |
| off | −0.127093789 | −0.002681714 | +0.372292344 |
| combined inward | −0.242003432 | −0.005315672 | +0.369652203 |
| forward/inward corner | −0.253031655 | −0.012311160 | +0.362656910 |

The retained 2s state is the nearest original 10Hz pre-command trace state,
within 6.68e−13s of the window boundary, not an extra simulation step.
Combined's local lateral differs from off by **−115.123mm** there; only
**−2.640mm** remains at the original 8m endpoint. Its Walk lasts **17.148s**.
Residual is exactly zero after 2s; the original reference correction continues
for approximately 15s. Across six profiles, early local differences are about
39.7–119.2mm; endpoint differences are only 0.687–9.635mm.

At each actual measured endpoint progress, strict requires reference lateral
around **≤−0.0949m** (the exact interval is the frozen SE(2) geometry).
Observed selected-frame endpoint lateral is only **−0.0034 to −0.0123m**.
The required persistent deviation was not constructed. These data support
strong attenuation of the tested early perturbations by subsequent fixed
reference tracking. They do not establish a certified invariant or an optimal
reachable offset under every possible action sequence.

Command integrals such as `(0,−0.12m,−0.24rad)` are **command exposure**,
not physical displacement/yaw bounds. Neural policy lag, body orientation,
recurrent/buffer state and closed-loop dynamics remain in the real response.
Finite saturated/late/shaped profiles do not exhaust the continuous 60 scalar
first-Walk action decisions, let alone other original transition windows.

## Route and physical effects remain independent

Combined improves final endpoint by 2.154mm, absolute lateral by 4.212mm and
absolute heading by 0.200825°. It nevertheless worsens first-Walk commanded
waypoint norm by **2.510mm**, and the subsequent first-Turn norm by
**24.213mm**; the later last Walk/Stop bring final norm below baseline.
Its final XY error changes from `(+0.475501,−1.111642)m` to
`(+0.479836,−1.107430)m`: X worsens. Full per-node world vectors and Stand/
Turn/Stop translations remain in `evidence/summary.json`; no all-prefix or
all-component improvement is claimed.

Measurement naming is explicit: new `world_metrics` along/cross diagnostics
use each node's **commanded terminal heading**. The original runner's retained
`ideal_path_lateral_error_m` uses its planned heading before the Turn update.
They differ for Turn nodes and are not interchangeable columns. Original
fields and scores are untouched; use the fixed world XY vector/norm for
cross-node attribution. The preregistered final gate uses commanded heading0°
in both conventions, so this diagnostic naming distinction cannot affect it.

No fall, invalid-control, non-finite or physical-success regression occurred.
Diagnostics are not identical: combined whole-sequence tilt increases from
7.115372° to **7.516844°**, and minimum height decreases from 0.754136m to
**0.747055m**. Physical PASS remains the original simulator proxy, not
collision/contact/hardware safety. Strict is still an endpoint gate; neither
20Hz poses nor this experiment certify continuous corridor containment.

The raw nominal failure taxonomy remains `SUCCESS` because nominal passes.
The **claim-level** failure is the independently retained strict envelope's
`EXCESSIVE_DRIFT`; no original result label is overwritten to conflate them.

## Verdict and stopping rule

- **FEASIBLE was not demonstrated:** no repeated strict + physical + global
  joint witness exists.
- **NOT_FEASIBLE was not demonstrated:** no full-admissible-space reachability
  certificate exists, and the required hard constraints are not statically
  proved mutually impossible.
- **INCONCLUSIVE:** the tested profile class fails the constructive gate,
  with a measured temporal/persistence limitation. The full current authority's
  existential capability remains unproved. Phase 3A.5 is not authorized.

The dominant observed issue is **persistence of terminal offset under the
original 2s window followed by fixed reference feedback**, not absent actuator
effect. It is not evidence that more PPO budget would solve the strict problem,
nor proof that changing bounds/window would work. Any subsequent authority
analysis or change needs its own authorized protocol; none is performed here.

## Provenance, validation and retained evidence

- Experiment `residual_authority_feasibility_001`, case `sequence-mixed-16m`;
  seed0 deterministic reproduction, no independent-seed generalization claim.
- Acquisition code commit `923e0bb0033d31901a4bfec94ce130f393a4530c`.
- Protocol SHA `573127438f96b1d446a21381371568640fc7ca2f1b62fe609c6639972c536eae`.
- Spatial contract SHA `19a5b637502036714bebaf381776799d8022fc6843ab8d0dfd1371d8fcc222fc`.
- Official policy SHA `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.
- CPU, one Torch thread, original MuJoCo3.15.0/PyTorch2.14.1+cu130 environment.
- All **193 source pins**, inherited baseline/model/history freeze and all
  **61 lossless exports** verified; original source/evidence/Console untouched.
- **242,067 full physics-step authority checks**, **9,696 retained poses**,
  **3,520 original diagnostic reward calls**, **0 optimizer updates**,
  **0 checkpoint writes**, **0 provider calls**.
- Independent per-run arithmetic/contract checks: **135,135 numeric** and
  **41,383 predicate** checks, all PASS; maximum roundoff 1.9874e−11 under
  the predeclared 1e−10 audit resolution. These are not scientific thresholds
  or a unit-test count.
- **138 targeted offline tests PASS**, no physics tests or full regression
  rerun. Tests and source checks preceded acquisition. No completed episode
  was retried, discarded or rerun after source changes.
- Initial/final policy `state_dict` digests can differ because runtime buffers
  evolve. Off/zero and combined/repeat tensor **replay parity** is exact;
  the official policy file and configuration remain frozen.

Raw acquisitions remain at `artifacts/residual_authority_feasibility_001`.
`evidence_manifest.json` binds raw and encoded/decoded export hashes.
`evidence/runs/<run_id>/result.json` identifies each original score and states;
`trace.jsonl.gz` and `decisions.jsonl.gz` bind applied commands, original callback
rewards and state samples. `poses.npz` contains **acquisition state samples**,
not a video or derived historical replay. Full-step digests are execution
identities, not reconstructible trajectories. `control_gate.json`,
`repeat_gate.json`, per-run `independent_audit.json` and `completion.json`
retain the actual gate outcomes and provenance.

Nonblocking environment notice: Torch emits its existing `torch.jit.load`
deprecation warning. The frozen loader/environment was not changed.

Remaining blocker for a positive feasibility claim: a strict/global joint
witness or a validated full-authority exclusion certificate. There is no
blocking evidence-integrity issue. **Stopping reason:** the bounded design is
complete, its negative outcomes are reproducible and the frozen verdict is
INCONCLUSIVE. No further probes, alpha selection, training, reward changes,
authority extension or Console work follow this session.
