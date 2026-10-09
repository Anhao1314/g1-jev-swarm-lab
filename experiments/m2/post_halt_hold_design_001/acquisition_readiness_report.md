# M2.5A Post-Halt Hold — acquisition readiness, no physics

**Engineering verdict: `READY_FOR_OWNER_ACQUISITION_AUTHORIZATION`. Scientific result: unmeasured.** This report supersedes the design-time readiness statements in `design.md`, `readiness.md`, `independent_review.md`, and `verification.json` from the original PR #14 candidate. Those candidate files remain byte-for-byte frozen as a historical design record; their statements that an adapter did not yet exist describe the earlier gate, not this engineering gate. `protocol.json` remains unchanged, including `physics_authorized=false`. The published M2.4 conclusion stays `INCONCLUSIVE`; no Research Ops scientific pointer was changed.

## Frozen scope and execution seam

The three cells remain Seen failure/Halt, Turn45 failure/Halt, and ordinary successful Stop control, in that order, one attempt each. Each *eligible* parent is followed in the same `LiveMissionSession` by exactly 1,000 native 0.002 s steps of the existing Stop torque helper with velocity command `(0,0,0)`. No new task node, session, reset, state substitution or post-Halt mission is allowed. The parent replay is compared, before Hold, with the hash-sealed M2.4 native predecision trace and scientific parent-result fields. A changed parent is an integrity/reproducibility result, never silently replaced by a different physical state.

The original terminal 500 Stop post-step speeds seed all 1,000 rolling means. The independent auditor also replays the full Stop speed history to establish that this was the *first* qualifying 500-step window. The fixed Hold checks are all rolling means ≤0.1 m/s, final instantaneous speed ≤0.1 m/s, XY path ≤0.20 m, and finite, standing, no-fall state at every step. The 0.20 m bound is new and prospective; it does not change the historical Halt displacement limit. No criterion was adjusted after observing a new physical result, because none was collected.

The adapter records parent result and Task Graph, original native-step journal, separate Hold-step journal, Stop crossing and entry snapshots, source/asset/readiness identities, counters, object identities, and write-once outcome/partial receipts. It refuses missing eligibility; keeps physical Halt failure, technical interruption, missing coverage and integrity/budget stop distinct; and stops the campaign on technical interruption without retry. A blocked worker is killed by an external per-cell wall watchdog, with a partial receipt. The limits remain 10,000 / 12,000 / 8,000 native steps by cell, 30,000 total, 120 s per cell, 360 s total.

## Frozen provenance and target gate

| Receipt | Result |
| --- | --- |
| Baseline main | `0eff13a5cb523690cde31a742cc985e9ee0eaf03` |
| Original M2.4 readiness SHA256 | `14219b6edc85d8346a97d5e50895d924c1157c6abffab37bd926dbfe4b138f08` |
| M2.5A execution source manifest SHA256 | `ef770b1139b5c1a4ee46ea963198392662f7052228d5db7d491cedecf3d0ccb3` |
| Exact owner-facing readiness manifest SHA256 | `6e51d067cd32717f33e1d253d41d9a8430ceaecd2cabb324cda95ae468947802` |
| Source/dependencies/assets | 241 inherited M2.4 source files, 254 total execution-source files, 41 pinned dependency versions, 91 hash-matched official model assets, 28 XML resource links |
| Target preflight | `TARGET_PREFLIGHT_PASS_NO_PHYSICS`; simulator and policy runtime not imported; zero physics steps and policy inferences |
| Adapter preflight | Exact readiness SHA accepted; package and mission script import origins verified inside this checkout, not a stale editable installation |

The 91 official assets were restored only after checking the published source receipt, then rehashed in this isolated worktree. They remain ignored by Git; the new `asset_restore_m25a.json` records the recovery and its zero-physics scope. `source_manifest.json`, `target_preflight_receipt.json`, `offline_test_receipt.json`, and `readiness_manifest.json` are write-once additions in this experiment namespace. The readiness manifest binds the source manifest and receipts, states `physics_authorized=false`, and requires a separate owner acquisition authorization. The acquisition command additionally requires explicit `--authorize-physics` and the exact readiness SHA; this is an experimental invocation gate, not production identity or hardware safety authority.

## Offline validation and independent review

The frozen M2.5A fake-backend, source-integrity and audit tests passed **43/43**. Applicable pre-existing M2.4 readiness and M2 physical-halt/lifecycle tests passed **54/54** with the target checkout on `PYTHONPATH`; the combined Research Ops test command passed **97/97**. Two live-session physics tests were explicitly excluded. The tests exercise no-Halt, failed Halt, failed normal control, exact 1,000-step zero command, first crossing, missing evidence, reset/dispatch rejection, source drift, controller continuity, seeded scoring, physical failure, technical interruption, watchdog and budget stops, one-attempt campaign behavior, and raw-data tampering. Fake observer on/off runs produced the same deterministic command sequence and terminal state. This is an offline seam check, not a measured MuJoCo observer-equivalence result.

Independent read-only engineering review identified and had corrected campaign continuation after technical interruption, a missing between-cell wall-budget receipt, postinitialization reset and Stop-return gaps, inadequate first-crossing/parent-label checks, raw posture/finite and controller-field trust, and a stale editable package import origin. It found no remaining code blocker after those corrections. The independent auditor now derives physical flags from raw qpos/qvel/ctrl/force/controller arrays and pinned posture limits; a nonfinite physical-stop classification requires raw qpos or qvel evidence. It verifies native and Hold rows against each other and the sealed historical parent. The signed-off review is recorded separately in `independent_engineering_review.md`.

## Reproduction without physics

From this checkout, use the pinned Python interpreter listed in the inherited M2.4 dependency receipt. `readiness.py` with no options rechecks the target source, assets, dependencies and XML links. `acquire.py preflight --readiness-sha256 6e51d067cd32717f33e1d253d41d9a8430ceaecd2cabb324cda95ae468947802` rechecks the exact execution gate without importing MuJoCo or the policy. The portable LF-normalized `offline_test_transcript.txt` has SHA256 `fed7086377813dfbabc7d245fd859567454e52b3f79f51621d8494a3059a1b32`, matching `offline_test_receipt.json`; that receipt also retains the original Research Ops Windows log hash. To repeat the 97-test no-physics selection from the repository root on Windows:

```powershell
$env:PYTHONPATH = "$(Get-Location)\src;$(Get-Location)"
$py = 'D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe'
& $py -m pytest experiments/m2/post_halt_hold_design_001/test_offline_check.py experiments/m2/post_halt_hold_design_001/test_readiness.py experiments/m2/post_halt_hold_design_001/test_acquire.py experiments/m2/post_halt_hold_design_001/test_audit.py tests/test_m24_acquisition_readiness.py tests/test_m2_physical_halt_runtime.py tests/test_m2_mission_lifecycle.py -q -k 'not test_live_session_runs_a_stop_mission and not test_live_session_runs_a_grounded_walk'
```

After a future authorized acquisition, `audit.py <saved-campaign-dir> --readiness-sha256 <same-sha>` can recompute the saved result read-only. No campaign directory exists in this readiness PR.

## Remaining scientific boundary and stop

There is **no new physical Hold outcome**. Real MuJoCo observer noninterference, hidden recurrent policy memory byte identity, cross-state reliability and hardware/production stopping remain unproven. The frozen adapter will retain a changed historical parent as integrity/reproducibility failure, and will not force Hold or retry to obtain a pass. This stage stops at owner review of the immutable readiness SHA and protocol. It does not grant acquisition permission, alter M2.4 results, or advance to another research phase.
