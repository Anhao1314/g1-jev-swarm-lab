# M2.3 — Trusted Mission Handoff Integration, first stage

**Implementation verdict: `PASS_OFFLINE_TRUSTED_SERIAL_HANDOFF`.** Independent
review agrees within the frozen offline TEST_ONLY scope. Source Handoff v0 can
enter the unchanged M2.2 lifecycle through a small, explicit trusted adapter.
The verified execution plan comes solely from issuer-retained canonical bytes.
This does not issue a new physical, concurrency or production authority claim.

## What changed

`src/g1swarm/trusted_handoff_v0/` selectively imports the reviewed TEST_ONLY
principal/handoff contracts and narrow request/value primitives from source
commit `a2325d3`. Its manifest identifies exact source blobs/bytes and import,
interpretation-pin and documentation adaptations. The Source Authority branch
was not merged; provider/certificate/release-stack and Compiler status paths
were not transplanted.

`src/g1swarm/mission/trusted_handoff.py` prepares and dispatches the bridge.
Preparation registers complete canonical bytes, an actual lifecycle/session
owner, source/request, the existing parent/raw-state assessment, copied host
permission policy and code epoch. Principal confirmation is required but does
not itself confer execution permission. Dispatch consumes the external grant,
then independently checks permission and fresh lifecycle state, parses only
returned issuer bytes, and uses the existing local authorizer and lifecycle.

Existing Runtime, lifecycle, skills, policy, simulator, evaluator, thresholds,
Console and Research Ops implementation are unchanged. The accepted scientific
selection remains M2.2 `PASS_BOUNDED_SAME_SESSION_LIFECYCLE`; its 28/28 anchors
are CURRENT. M2.3 is a supplementary interface result, not a pointer rewrite.
The exact cross-branch contract is in [CONTRACT.md](CONTRACT.md), and the
predeclared matrix/stopping rule in [PROTOCOL.md](PROTOCOL.md).

## Offline outcomes and affected checks

| Check | Result | Evidence meaning |
| --- | --- | --- |
| Integrated bridge matrix | 45/45 PASS | Fake-session wiring, canonical execution and refusals |
| Adapted v0 boundary | 56/56 PASS | Registered identity, complete plan, request, clock, seals and one-use consumption |
| Existing Runtime/halt/lifecycle | 41/41 PASS | Unchanged affected non-physics contracts |
| Research Ops | 22/22 PASS after asset restoration | Context/inventory/provenance workflow |
| Accepted baseline byte audit | 2,269/2,269 unchanged | Every preexisting tracked working file and original Git tree preserved |
| Independent review | PASS, no scoped blocker | Implementation, source provenance, negative evidence and interpretation |

There are **164 unique applicable passing checks**, not 164 physical samples.
Two explicitly named live-session physics tests were deselected. No physics,
providers, Jev, training, robot actuation, new recovery or model calls occurred.
The positive fixtures complete the new three-node Mission only in a fake
session. They prove dispatch input/session identity and parent evidence
preservation; they are not additional MuJoCo successes.

The integrated matrix retains three fixture completion events, 72 refusal
events (including replay attempts), and five preparation refusals. These are
correlated checks, not independent samples. Actual status, refusal code and
consumption status are preserved in `bridge_final.xml` and derived
`offline_decisions.json`. Plan amount/identity/skill/dependency/order/schema
and override mutation, forged/copied/replayed/revoked grants, wrong source or
request, stale/foreign/copied principal proof, insufficient permission, another
same-named lifecycle owner, changed execution/parent state, code epoch and
evidence destination collisions all refuse without new task calls/steps or
overwriting the parent files. Registered attempted grants cannot later succeed.

The strongest boundary control mutates raw qvel **after** successful v0
consumption: fresh M2.2 assessment detects `EXECUTION_STATE_CHANGED`, refuses
dispatch, preserves parent bytes and rejects a replay. Another control changes
the caller's mutable Mission after consumption: the executor still receives
the exact issuer-owned complete canonical bytes. Both digest domains are
checked independently; the canonical and lifecycle hashes intentionally differ.

Existing M2.2 tests additionally cover old mission/node ID reuse, controller
action changes and failed/incomplete halts. Existing v0 tests retain its
one-consumption lock behavior. Neither establishes concurrent atomic robot
dispatch for this integrated entry.

## Retained technical failures

The first affected run had 60 PASS / 3 FAIL / 2 deselected. All three failures
were Research Ops Console inventory checks refusing missing ignored
`third_party/.../motion.pt` in the new worktree. Only that already retained
asset was copied from the original workspace and verified against both frozen
Console inventories. The 22 Ops checks then passed; the already passing 41
Runtime/lifecycle checks were not repeated. Initial XML/log are retained.

The first derived-summary parser expected JSON for a plain preparation-refusal
property. `derivation_attempt_001.json` retains that error; only the parser and
derived summary were corrected, with no test or acquisition rerun. No refusal,
label, threshold, raw receipt or negative scientific result was replaced.

## Reproduction and boundaries

Use the repository dependencies with this worktree's `src` on PYTHONPATH:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests/test_m23_handoff_v0.py tests/test_m23_trusted_handoff.py -q
python -m pytest tests/test_mission_runtime.py tests/test_m2_physical_halt_runtime.py tests/test_m2_mission_lifecycle.py -q -k 'not test_live_session_runs_a_stop_mission and not test_live_session_runs_a_grounded_walk'
python scripts/research_ops.py context
python reports/m23_trusted_handoff_001/verify_integrity.py check
```

Research Ops inventory tests require the existing ignored pinned policy file;
the normal dependency/asset setup remains unchanged. Integrity checks reference
the retained original/source worktrees as a local isolation audit and need
those checkouts available. Source/implementation/receipt hashes in
`verification.json` provide the independent portable provenance record.

The original research workspace still has the same 23 unrelated untracked
entries; it was not edited. That isolation check compares Git status, not the
bytes of unrelated ignored/untracked assets. The source workspace also remains
unchanged. All 2,269 accepted tracked working bytes were individually checked.

Simulated principal names are not authenticated humans. Host permissions are
TEST_ONLY experiment configuration. The underlying executor remains directly
callable by trusted Python. In-process consumption is not durable replay
defense or atomic dispatch across threads/processes. Continuous revocation,
post-dispatch cancellation, generalized restart, hardware safety and production
authorization remain unqualified. ABSTAIN/ESCALATE does not claim physical halt.
Jev remains ineligible for online use; Language Runtime/D011 remain BLOCKED.

## Decision and stopping reason

No new physical acquisition is needed to decide this first-stage interface
compatibility question: all physical execution code and criteria remain
byte-identical, and the new authority/plan boundary is exercised offline.
Retained M2.2 physics supports only its previously seen bounded state. A future
real handoff qualification would require a separate frozen protocol and gate.

Work stops at this bounded implementation verdict and independent PR. Remote
main still contains R1; M2.2 PR #5 is accepted/Ready but unmerged. This separate
integration PR targets `m2.2/adaptive-mission-lifecycle` so its diff contains
only M2.3, and explicitly depends on PR #5. No automatic merge or scientific
pointer advance. Research Ops stage receipts/limits are in `telemetry.json`;
unmeasured periods are not reported as zero or invented token savings.
