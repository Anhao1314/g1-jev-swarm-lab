# Skill Handoff acquisition entry

This is a prospective engineering adapter for the immutable design at
`19d4f6e11d8c24606559296309acf06651374ae6`, not a new scientific result or
permission to acquire. The original `skill_handoff_001/protocol.json` and
historical Stand5 artifacts remain unchanged.

## Scope and execution

Only `constant` then `terminal_schedule`, one attempt each, seen Stand5 seed 0,
fixed alpha 0.25, original Stand5 / Walk8 / Turn-90 plus original settle.
Original policy, controller, skill bodies, observation, envelopes and original
world waypoint stay frozen. No extra Stop, reset, state injection or later
Mission nodes are introduced. This prefix is not a completed full Mission.

The retained `AcquisitionRunner`, `WindowController` and fixed-alpha correction
are reused. `ScheduledCorrection` changes the nominal vx at the existing Walk
callback only. The legacy authority check reconstructs its expected command
from `last_nominal_command`: that diagnostic is updated to the declared scheduled
nominal. Original nominal is retained separately in schedule and trace. The
original assertion is not disabled. Source-extracted nonphysical tests exercise
the actual WindowController and its retained full-step assertion.

## Bounds and termination

Original loop ceilings give `2500 + 24000 + 5000 + 250 = 31750` native steps:
5 s Stand, 48 s Walk, 10 s Turn and 0.5 s settle at 0.002 s. Thus the 32000/arm
and 64000/campaign limits are compatible **as ceilings**, not a guarantee that
slower walking completes. Walk still times out at its original 48 s. Extra
initialization stepping is rejected. Every native attempt is counted before
dispatch, with completion and unknown completion kept separately.

An outer Windows Job bounds source verification, nested worker initialization,
execution, raw audit and cleanup under one start time: 235 s cutoff, 240 s total.
Workers have at most 120 s each, with cleanup reserve deducted rather than added.
Kill-on-close and explicit termination cover exited roots with surviving
descendants. Cleanup failure is not success. Windows process termination is not
a claim of robot physical stopping or hardware safety. Linux execution is not
qualified by this implementation.

## Measurements and qualification

Each native before/after record includes time, node, full qpos/qvel/ctrl,
actual command, controller counter/action/target/reset count. Read-only node
boundaries and original post-reset hooks retain physical and policy digests.
Every Walk callback retains original/scheduled commands and original-frame
progress. First nonbaseline-command entry has a full preceding native-stream
digest, full state, original frame and policy digest; treatment must match the
constant arm before that command is applied.

Independent `audit_raw.py` recomputes physical/strict outcomes using raw states
and the original pure envelope, checks commands and timing, and calculates the
final 0.5 s speed window at native resolution. Physical failure, strict failure,
technical interruption, missing coverage and integrity failure remain separate.
Native exceptions and post-step recording errors cannot erase observed falls.

Before the second arm, the new constant prefix must match historical alpha 0.25
scientific fields, all retained command samples and available pose samples at
zero tolerance. Matching NaN reference sentinels are missing-field markers, not
numerical data. Historical poses cannot prove every-native equivalence; the new
pair provides that denser comparison before intervention. Actual physical replay,
observer wall-time overhead, slowdown response and scientific benefit remain
unmeasured until separately authorized acquisition. No retry or tolerance change
is allowed after a mismatch.

## Freeze and reproduce without physics

Use the existing Windows Python environment, restored hash-matched 91 assets,
and sealed historical Stand5 acquisition directory. Do not load the policy for
these operations. Commit the new package first; freeze against that exact HEAD.

```powershell
$py = 'D:\work\g1-jev-swarm-lab\.venv\Scripts\python.exe'
$pkg = 'experiments/mission_constrained/skill_handoff_acquisition_001'
& $py -B -m pytest "$pkg/test_backend.py" "$pkg/test_entry.py" "$pkg/test_lifecycle.py" "$pkg/test_raw.py" -q
& $py -B "$pkg/run.py" freeze --history <sealed-history> --output <new-freeze-directory>
& $py -B "$pkg/run.py" preflight --readiness <readiness.json> --sha256 <exact-sha256>
& $py -B "$pkg/verify_frozen.py" --readiness <readiness.json> --sha256 <exact-sha256> --output <new-test-directory>
```

`verify_frozen` uses production guards and Jobs with a test-only injected backend
in its child process. It never loads the physical backend and does not expose a
production bypass flag. Its positive synthetic receipt is not a physics result.
The separate future `acquire` operation requires an explicit trusted-operator
assertion following Owner approval of this exact execution identity. This is
serial experimental access, not authenticated production Human Principal
Authority. Readiness has `physics_authorized: false`.

Evidence is external and append-only so recording acceptance does not invalidate
the frozen execution HEAD. Preserve earlier failed test attempts. Reports must
identify the exact source/readiness hashes, raw test receipts, independent review
and remaining limitations. No push or merge is part of this task.
