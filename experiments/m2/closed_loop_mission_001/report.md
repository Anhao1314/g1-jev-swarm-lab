# M2.0 closed-loop mission execution: frozen two-mission slice

## Scope and predeclaration

The `protocol.json`, acquisition code, and source hashes were frozen in commit
`d16e9d49c4938ffde10a652daf24a572b6414b7a` before the first physics run.
Both missions are structured Oracle Mission IR 2.0.0. Each ran once with the
Phase 2 static dispatcher and once with the opt-in strict-walk feedback gate,
seed 0, original policy/controller/skill bodies, and original Phase 2 grounding.
The only comparison switch was `MissionExecutor.walk_strict_gate`. The four-run
limit was honored; no case was substituted. The explicit open-loop 6 m override
is a documented experimental mode with HIGH grounding risk, selected because
the retained Phase 1.3 boundary reported first failure at 6 m and last reliable
distance at 4 m. It is not an automatic runtime choice.

## Real execution

| Mission | Dispatch | Mission | Invoked skills | MuJoCo steps | First walk |
| --- | --- | --- | ---: | ---: | --- |
| walk 4 m → turn 45° → stop | static | SUCCESS | 3 | 5,991 | lateral −0.0193 m; heading +0.257° |
| walk 4 m → turn 45° → stop | feedback | SUCCESS | 3 | 5,991 | same first walk; strict CONTINUE |
| open-loop walk 6 m → turn 45° → stop | static | SUCCESS | 3 | 8,056 | lateral −0.5486 m; heading −9.479° |
| open-loop walk 6 m → turn 45° → stop | feedback | FAILED: TASK_ENVELOPE_VIOLATION | 1 | 6,468 | same first walk; STOP_DEPENDENTS |

The failing first walk reached its 6 m target within 0.000373 m. Its skill status
and physical-success flag were SUCCESS/true, which let static dispatch execute
the turn and stop. The independent frozen strict envelope instead found lateral
drift 0.54865 m > 0.21 m and heading error 9.479° > 8°; the feedback executor
marked s1 FAILED and s2/s3 BLOCKED. This is an actual feedback-driven task-flow
change, not a changed walking command. Both modes' first-walk scientific metrics,
start/end states, and common 20 Hz pose samples match exactly. The safe mission
retains all three executions and identical pose trajectories under both modes.

`STOP_DEPENDENTS` is a refusal to dispatch later skills, not a physical
emergency stop. The robot's measured speed at the failure boundary was
0.4512 m/s; this study makes no safe-stop claim. There is no recovery,
replanning, language input, Jev, new policy training, or threshold change.

## Evidence and integrity

Each of the four write-once run directories under `artifacts/` retains the
MissionResult, native MissionRecorder event ledger and Task Graph, exact
20 Hz MuJoCo `qpos/qvel/ctrl/time_s` replay states, and a receipt. `audit.json`
pins their hashes and confirms source integrity, paired first-skill parity,
safe-path retention, strict failure routing, and blocked descendants. The
acquisition command ran through Research Ops task `m2-closed-loop-mission` as one
experiment event (7.092 s).
The first offline audit attempt failed because the terminating feedback run
appended an exact endpoint frame between the continuing static run's 20 Hz
frames. The check was narrowed to shared sample times; the original attempt
remains in Research Ops telemetry. The corrected read-only audit passed
(two events, 0.492 s total; one failed command). No physics was repeated.

This is a bounded demonstration of mission-flow feedback on two deliberately
selected, already-seen development tasks. It does not establish general
adaptive capability, reliable physical stopping, or a new recovery policy.

## Console and verification

The read-only M2 Console serves four source-bound native G1 state-playback clips
at `http://127.0.0.1:8770/` while the local viewer is running. The browser QA
visited the failure feedback endpoint and observed the robot replay, route,
`Strict FAIL / Physical PASS`, measured drift 0.549 m versus 0.210 m limit,
heading 9.48° versus 8.00° limit, and timestamped `STOP_DEPENDENTS`. Node-end
results and decisions are hidden before their recorded times. The catalog
labels the failed mode as a HIGH-risk experimental override. The renderer uses
captured `qpos/qvel/ctrl` and `mj_forward` only, after physics acquisition.

Validation passed: 43 targeted Mission Runtime/Console server tests, nine
Console data tests, and all 59 Console tests; the source-bound Console catalog
verified four runs. The old Console snapshot test initially failed because it
compared the old commit's Runtime and test files to the intentionally updated
working tree. Its check now compares those two historical files to their pinned
historical Git blobs, still checks every other frozen file against the current
tree, and verifies the current Runtime against the pre-execution M2 source
manifest. Historical files and scientific artifacts were not rewritten.
Research Ops measured the four-run experiment (7.092 s), targeted Python tests
(16.162 s), full Console tests (35.593 s), and two audit commands (0.492 s,
including one retained read-only audit-check failure). Reasoning,
implementation, and token durations were not measured and are not estimated.
