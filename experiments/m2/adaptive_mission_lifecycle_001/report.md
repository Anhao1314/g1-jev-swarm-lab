# M2.2 — Adaptive Mission Lifecycle

## Verdict

**PASS_BOUNDED_SAME_SESSION_LIFECYCLE.** The frozen seed-0 development case
demonstrates Failure → Halt → Assess → Authorized New Mission on one live
MuJoCo session. The parent mission remains `FAILED: TASK_ENVELOPE_VIOLATION`,
with `s1=FAILED` and `s2/s3=BLOCKED`. A separately identified, grounded Oracle
Walk4 → Turn45 → Stop task completes only after current-state eligibility and
a matching, single-use `TEST_ONLY` experiment grant. The matched halt-only
control has the same eligible physical state but no grant, and executes no
new task. This is conditional restart feasibility, not repair of the failed
route, autonomous recovery, authenticated Human Principal Authority, or
production/hardware safety.

## Frozen design and measured results

[Protocol](protocol.json), [source manifest](source_manifest.json), the
implementation and acquisition runner were committed as
`4d43f098f21dba29efa79035c2ae98cc74a212e9` before the three formal runs.
The chosen new task reuses the previously grounded safe 4 m/45°/Stop template,
with distinct mission and node IDs. Its actual post-halt start was not assumed
equivalent to the original safe initial state. No profile, controller, policy,
reference, evaluator, threshold, skill semantics or physics timestep changed.

| Frozen run | Parent / halt | New task | Physics steps |
| --- | --- | --- | ---: |
| `adaptive_authorized` | FAILED / HALT_SUCCEEDED | SUCCESS, 3/3 nodes | 13,128 |
| `halt_only_no_authorization` | FAILED / HALT_SUCCEEDED | ESCALATE: AUTHORIZATION_MISSING; zero new nodes/steps | 7,139 |
| `normal_control` | SUCCESS, original 3/3 nodes; no halt | No continuation requested | 5,991 |

Both failure runs reproduce the retained M2.1 halt: 1.342 s, final instantaneous
speed 0.056035 m/s, last-1 s mean 0.099970 m/s, and extra planar displacement
0.185365 m. That mean remains only narrowly below the unchanged 0.100 m/s
criterion; this study adds no stopping-reliability claim.

The new mission starts at the exact actual halt endpoint, t=14.278 s, and
completes after 11.978 s and 5,989 new physics steps. Its Walk strict gate
passes: distance error 0.000738 m, lateral drift −0.020910 m and heading error
0.068285°. The correction reports zero saturation and zero oscillation.
The final task Stop measures 0.006407 m/s instantaneous speed and 0.067646 m/s
mean over its last 500 steps (1 s at the unchanged 0.002 s timestep). All
new-task recorded steps are finite, standing and not fallen; minimum base
height is 0.758842 m and maximum tilt 6.070499°.

## Feedback and authorization evidence

The gate requires the retained parent failure and all eight named M2.1 halt
checks, a fresh actual simulator read, finite/standing/no-fall state, speed
≤0.10 m/s, exact halt endpoint continuity, valid capability grounding without
an experimental override, distinct mission/node IDs, and an unused evidence
destination. It binds a grant to the complete canonical new Mission IR,
parent result/graph/receipt, actual lifecycle/session owner, and fresh
assessment including read-only raw `qpos/qvel/ctrl/time` and available
controller action/target/counter. No policy execution occurs in assessment
or authorization.

Missing, forged and mismatched grants are rejected at the eligible live halt
state. Every denial has identical before/after full execution snapshots,
including time, steps, raw state, identities and reset counts. The used grant
is denied after the one permitted continuation (`ASSESSMENT_REJECTED`,
including the already-dispatched/freshness conditions); it executes zero
additional steps. Focused fixtures cover actual failed-halt receipts,
truncated acceptance checks, nonfinite/fallen/moving/closed or stale state,
zero-time joint/control changes, different live owners sharing a serialized
session ID, altered mission binding, existing evidence destinations and
parent mutations.

[Recorded pre-halt control](recorded_prehalt_control.json) applies the frozen
necessary state conditions to the retained real t=12.936 s record. Although
finite and standing, it is moving at 0.451221 m/s and its halt has not yet
completed; it is ineligible with `NOT_HALTED_SPEED/HALT_NOT_SUCCEEDED`. This
is explicitly a descriptive recorded-state replay, not an additional live
physics run or full live lifecycle assertion.

`ESCALATE` means deterministic refusal of new task dispatch. It does not
introduce an ongoing stabilization controller or claim a physical emergency
stop. The grant is a trusted in-process experimental allowlist capability,
not a security boundary against arbitrary Python process code and not a
production human-principal authorization system.

## Independent audit and controls

[Audit](audit.json) passes all raw outcome checks. Both failing parent runs
retain exact scientific results versus M2.1 and all 287 historical
`time/qpos/qvel/ctrl` frames. The safe control retains all 241 frames and its
original scientific results. Comparison excludes host wall times/run
provenance and normalizes only the absolute worktree prefix of grounding
evidence references; their retained suffix and verified source content match.
No source or original artifact was rewritten for comparison.

Original parent result bytes, all original mission-ledger bytes and the
parent Task Graph are unchanged after lifecycle decisions and new execution.
All runs retain the same simulator and controller objects. They preserve
the historical two constructor/startup reset calls and record **zero later
simulator resets**. Time and step traces are monotonic. Existing per-skill
controller-memory reset semantics remain explicit and are not simulator
resets. The blocked parent nodes never appear as new task dispatches.

All 49 working-checkout source hashes and every raw artifact receipt pass.
Twenty-seven historical source/map files differ from their Git blob only by
Windows checkout CRLF/LF conversion; normalized content is identical. The
manifest therefore requires byte-identical checkout conventions, not an
arbitrary LF checkout. Three official Unitree assets remain external/untracked
but are pinned by their actual bytes, including the unchanged policy hash.

## Execution discipline, verification and limits

[Execution deviation](execution_deviation_001.json) retains an unplanned
prefreeze run of two unchanged legacy initial-state physical unit tests
(Stop and grounded Walk). A stale test exclusion selector caused this run.
They did not exercise a failure→halt→new-mission treatment and are excluded
from the formal three-run matrix and all restart claims. Exact command
timestamps were not captured; the retained cache time is only an end-time
proxy. The deviation is not relabeled as planned validation. Corrected
nonphysics prefreeze checks passed 41 tests with two actual physics tests
explicitly deselected.

Research Ops entered `CURRENT` with 20 reviewed anchors, and the task was
routed as mechanism work with independent claim audit. Its measured initial
test command took 0.524 s and formal acquisition 6.845 s. Subsequent Console,
targeted verification and closeout receipts are recorded separately; no
unmeasured reasoning/token cost is inferred from these command timings.

This is one previously seen development failure, one paired halt-only
control and one safe control at seed 0. It establishes no fresh held-out,
cross-state, independent-seed, hardware or production generalization.
Jev remains ineligible for online use and Language Runtime / D011 remains
BLOCKED. No Jev call, language dispatch, PPO training, reward change,
recovery search or Multi-Swarm was introduced. Further acquisition is not
required for this bounded implementation verdict.

## Final implementation verification and Console

The combined no-physics Runtime/lifecycle/Console/Research Ops target recorded
126 passing tests and one failure: the legacy retained-closeout adapter
correctly refused the stale R1 selection after new Console evidence was added.
An explicit M2.2 selection was then reviewed against this independent audit,
preserving all 20 old anchors and adding eight named evidence anchors. Its
context is `CURRENT` with 28/28 anchors; the affected Research Ops target then
passed all 22 tests. Two existing live-session physics tests were explicitly
excluded from the formal verification command. The initial failed metadata
check is retained, not rewritten as an initial all-pass result.

Console frontend checks passed 12 tests. The new replay namespace is
`experiments/research_console/m2_adaptive_lifecycle_001`; its three videos
restore original captured states with `mj_forward` and no physics stepping.
Fresh browser QA observed the original FAILED/new SUCCESS separately at the
exact final time, eligible-but-unauthorized refusal with no new execution,
and the unchanged normal control. Inspector seed 0, official policy hash,
source commit and separate parent/new raw evidence links were verified.
The timeline range now retains the exact final time rather than rounding it
down and hiding the completion event. See that namespace's `browser_qa.json`,
`http_qa.json`, `tests_receipt.json` and render manifests.

[Validation receipt](validation.json) records the commands, initial failure,
targeted resolution, and measured Research Ops intervals. These command
intervals do not measure complete reasoning/implementation effort or token
usage. The read-only Console can be started with:

```powershell
python console/server.py --data experiments/research_console/m2_adaptive_lifecycle_001 --port 8773
```
