# M2.3b — Real MuJoCo Trusted Handoff Qualification

**Verdict: `PASS_BOUNDED_REAL_MUJOCO_TRUSTED_HANDOFF`.** Two frozen, once-only
seed-0 runs connect the accepted M2.3 immutable handoff to the existing M2.2
same-session lifecycle in real MuJoCo. Correct TEST_ONLY authorization runs a
distinct new Mission; invalid authorization dispatches no additional physics.
The original mission remains FAILED. M2.3's historical
`PASS_OFFLINE_TRUSTED_SERIAL_HANDOFF` is unchanged.

## Baseline and frozen budget

PR #6 was merged with merge commit `a114ec9`; its tree equals reviewed M2.3
`1ede004`. Work occurs in a new isolated `m2.3b/real-trusted-handoff` branch.
Protocol, runner, offline checks and independent preflight were committed at
`e8c13333111fe7f07b68d7012175fb9ccba9db8f` before any new physics. The source
manifest freezes 158 code/config/policy/model/comparator files, including all
relevant official model assets and the selective v0 source pin `a2325d3`.

Only `trusted_authorized` then `halt_only_invalid`, seed 0, were declared.
Hard budgets were 14,000 / 8,000 steps, 120s per arm and one attempt per arm.
No additional state, seed, amplitude, controller or recovery search. Existing
M2.2 failure, halt and Walk4 → Turn45 → Stop Mission/IDs/parameters were reused
in new study-specific ledger directories. Policy, controller, reference,
physics timestep, evaluator and thresholds remain byte-identical. Historical
normal control is retained context, not a new physics arm.

## Actual execution

| Arm | Parent / halt | New Mission | Physics steps | Additional dispatch after refusal |
| --- | --- | --- | ---: | ---: |
| trusted_authorized | FAILED / HALT_SUCCEEDED | SUCCESS, 3/3; strict Walk and physical PASS | 13,128 | 0 for replay |
| halt_only_invalid | FAILED / HALT_SUCCEEDED | NOT_EXECUTED, ESCALATE | 7,139 | 0 for all five controls |

Both runs use the same live session/simulator/controller throughout. Each has
two expected startup `G1Simulation.reset` and `mj_resetData` calls, no keyframe
reset and **zero reset after initialization**. Normal skill controller-memory
resets retain their existing semantics; they are not simulator resets.
No external session factory was invoked, and no blocked parent node revived.

The correct grant was registered by the TEST_ONLY fixture issuer with explicit
host continuation permission. Preparation binds full canonical plan, source,
request, actual owner, interpretation epoch and fresh halted raw state. At the
actual `MissionExecutor.run` entry, only the expected observer executor-call
counter increment differs from the pre-dispatch snapshot; time, qpos/qvel/ctrl,
controller action/target/counter, owner IDs, reset/physics/node counters agree.

Issuer-retained canonical plan, actual executor input, persisted Mission
manifest and all physical node parameters/dependencies agree exactly. The v0
complete-plan SHA and M2.2 `Mission.to_dict()` SHA remain distinct encodings;
each is checked in its own domain. New Mission canonical SHA is
`c3d15a25c9d9877da0139eadd0994f6e475302215ffd61e64fb3de460c3dc79b`.

Observed new Walk4 endpoint: forward 4.000738m, distance error 0.000738m,
lateral drift −0.020910m, heading error 0.068285°. Final Stop speed is
0.006407m/s; last 500 steps (1s) mean is 0.067646m/s. The existing 0.10m/s
criteria, finite/standing/no-fall requirements and strict scoring were retained.
Runtime does not serialize Stop's window mean into its node result; the new
study derives that value read-only from the saved per-step trace, without
editing Runtime or changing Stop behavior.

## Retained negative controls

| Request | Actual refusal |
| --- | --- |
| Missing grant | UNTRUSTED_HANDOFF |
| Copied registered grant object | UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF |
| Changed comparison plan, Walk4 → Walk6 | PLAN_CHANGED |
| Replayed original grant after registered plan mismatch | UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF |
| Registered display-only principal without continuation permission | PRINCIPAL_CONTINUATION_PERMISSION_MISSING |
| Accepted arm's consumed-grant replay | UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF |

All six refusals have exactly equal before/after raw execution snapshots,
zero additional executor/node/physics/reset calls, and unchanged parent files.
The five invalid-arm requests occur at the same real halted state. Deliberate
separate fixture issuances were predeclared controls, not outcome-driven retry
or renewal. An unregistered copied object is refused; the registered plan-
mismatch attempt consumes its original grant and its restored-plan replay
remains refused. No invalid arm is later converted into a positive run.

## Integrity, independent audit and observer equivalence

Parent result, graph and every parent ledger byte remain unchanged after new
Mission execution/refusal. The parent's s1 remains FAILED and s2/s3 BLOCKED.
The same-session pose samples and every recorded physics-step state match
the corresponding historical M2.2 arms exactly, including the entire positive
run and negative halt-only run. This verifies the call-through observer did
not change execution within this specific deterministic state/controller.

Independent `audit.py` recomputes 64 checks from raw receipts, source bytes,
canonical inputs, persistent ledgers, raw state/counters and complete traces:
**64 PASS, 0 FAIL**. It verifies all 158 source members, seven original source
Git blobs and pre-physics commit bindings. No reviewer physics was executed.
Original workspace untracked entries and Source Authority workspace retain
their Git status; this is not a byte audit of unrelated untracked contents.
The original history snapshot and all historical experiments/results remain.
Only declared Console observer files and the reviewed current Ops index change.

The parent halt last-second mean remains 0.0999695815m/s, narrowly below
0.10m/s. This margin is disclosed, not rounded into generalized stopping safety.
There was no acquisition failure, outcome-driven retry or replacement. Setup
used only already retained ignored official assets and the existing verified
encoder; no new package/provider configuration was required.

## Console and checks

The new read-only Console at `http://127.0.0.1:8774/` shows continuous native
capture, failure/independent halt, source-bound handoff and refusal decisions,
separate original/new task outcomes and complete plan/continuity evidence.
Positive/negative videos contain 528/287 frames; rendering uses `mj_forward`
and **0 `mj_step`**, without acquisition replay. Numeric outcomes are read from
experiment evidence; video does not rescore them.

Same-time decisions now select exact `source_locator`, preventing Inspector
from displaying another earlier evaluation. A targeted Runtime card CSS fix
keeps all original/new/lifecycle badges visible in comparison at narrow widths.
Both changes are observers only. Initial receipts and the CSS amendment remain
separate. Fresh browser QA binds final code/data hashes, decoded playback/end
frames, distinct same-time PLAN_CHANGED/permission refusals, full-plan identity,
raw links and the final visible comparison. UI automation transient errors are
retained separately; they caused no acquisition or scientific-data changes.

Offline acquisition tests 13/13, Console/compatibility tests 55/55 and frontend
tests 13/13 pass. Existing M2.3's broader 164 applicable offline receipts are
retained context, not newly rerun or counted as new physical evidence. Research
Ops uses an explicit independently reviewed selection after new namespace
detection; no mtime-based promotion or historical verdict rewrite.

## Limits, reproduction and stopping reason

This qualifies one previously seen seed-0 MuJoCo state and a trusted, serial,
in-process TEST_ONLY entry. Simulated principal names do not authenticate
humans. The source consumption lock does not establish concurrent atomic robot
dispatch, durable replay defense, continuous revocation or production authority.
The underlying executor remains callable by trusted Python. ESCALATE does not
claim ongoing physical safety. Original route failure is not repaired or erased.
No hardware safety, general recovery or cross-state reliability follows.
Jev, Language Runtime/D011, PPO/reward changes and Multi-Swarm remain blocked.

Use repository dependencies and this checkout's src on PYTHONPATH. The saved
audit is reproducible without physics:

```powershell
python experiments/m2/trusted_handoff_qualification_001/audit.py
python experiments/m2/trusted_handoff_qualification_001/history_audit.py check
python scripts/research_ops.py context
python console/server.py --port 8774 --data experiments/research_console/m23b_trusted_handoff_001
```

The acquisition CLI refuses existing output directories; do not re-execute it
to reproduce the audit or visualization. A future scientific repeat needs a
separate authorization/freeze, retaining this once-only experiment. The required
physical witness, refusals, provenance, independent audit and observable Console
evidence are complete. Stop after tests and the independent review PR; no main
merge or next experiment is authorized by this closeout.
