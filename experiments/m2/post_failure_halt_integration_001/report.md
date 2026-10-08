# M2.1 — Post-Failure Physical Halt

## Verdict

**Bounded MuJoCo physical-halt slice: PASS.** On the frozen, explicitly HIGH-risk
open-loop 6 m mission, the strict feedback gate still marks the first Walk and
mission failed and blocks the Turn and task Stop nodes. A separately authorized,
opt-in StopSkill then produces a measured controlled termination. This is a
physical handling result after task failure, not a reversal of the failure or
a claim of real-hardware emergency-stop safety.

## Frozen execution and result

The separate feasibility acquisition used the retained M2.0 failure mission,
seed 0, original controller, policy, StopSkill, strict envelope and Task Graph.
Its prephysics amendment retained the original freeze and pinned robot YAML,
scene and included G1 XML, the TorchScript policy, and failure capture. The
integrated acquisition then froze exactly two opt-in runs before physics: the
same failure mission and the normal 4 m → turn 45° → stop control. The existing
M2.1 StopSkill parameters and acceptance limits were reused; no threshold or
historical evidence was changed.

| State | Frozen failure run |
| --- | --- |
| Task decision | `STOP_DEPENDENTS` after first Walk strict failure |
| Task Graph | `s1=FAILED`; `s2/s3=BLOCKED`; only `s1` dispatched |
| Physical request | Separate `EXPLICIT_INDEPENDENT_PHYSICAL_HALT`, after the block |
| Physical result | `HALT_SUCCEEDED`; original mission remains `FAILED: TASK_ENVELOPE_VIOLATION` |

At the task block, measured planar speed was **0.451221 m/s**. During the
StopSkill request it fell to **0.056035 m/s** in **1.342 s** of simulation. The
last 1 s mean was **0.099970 m/s**, just below the frozen **0.100 m/s** limit;
post-block planar displacement was **0.185365 m** and path length **0.222617
m**. All **672** recorded halt states were finite, standing and not fallen;
minimum base height was **0.7620 m** and maximum tilt **3.98°**. The integrated
halt trace and scientific values exactly match the independent feasibility run
apart from host wall time and provenance.

The first Walk's scientific metrics and 6,468 simulation steps match M2.0
exactly, excluding host wall time. Its strict decision and end state are
unchanged. All 259 shared pre-failure 20 Hz pose frames have identical
`qpos/qvel/ctrl`; the historical M2.0 endpoint frame is absent from the new
combined pose file because its recorder continues into Stop, while the Task
Graph end state equals the new halt trace's initial state. Native ledger order
is `feedback_decision` → `node_failure` → `physical_halt_requested` →
`physical_halt_succeeded`; there is no task-graph Stop dispatch.

The normal task remains `SUCCESS` with its original Walk, Turn and task Stop.
All three node scientific metrics and all 241 pose frames match M2.0, and no
independent physical halt is requested. The retained static M2.0 failure
control still dispatches all three nodes after the unsafe Walk; the feedback
gate blocks them, and M2.1 adds the physical termination path after that
block.

## Integrity and limits

[Independent audit](audit.json) verified all 24 frozen integration source and
asset hashes, both result/pose receipts, Task Graph and ledger events, the
halt arithmetic, and the safe-path parity. The separate feasibility trace
also passed its frozen StopSkill gate. The strict failure before halt is not
relabeled, and the blocked task Stop is not used as the emergency action.

This is one deliberately selected, previously seen development failure and
one safe control at seed 0. The failing Walk uses an explicit HIGH-risk
experimental override. The 1 s mean speed is only about **0.000030 m/s** below
its limit, so the result supports this exact bounded MuJoCo execution, not
robust stopping across states or a real-hardware safety guarantee. A future
StopSkill timeout, fall, non-finite state or excess displacement must remain
`HALT_FAILED` even when the Task Graph is already blocked.

Research Ops v0.1 context reported `STALE` because its reviewed selection
pointer still names the earlier Phase 3B.0a baseline. The task was explicitly
routed as a mechanism experiment without changing Research Ops. Its recorded
experiment stage contains two successful shell executions totaling **8.5825
s**. Reasoning, implementation and token timing were not measured and are not
estimated.
