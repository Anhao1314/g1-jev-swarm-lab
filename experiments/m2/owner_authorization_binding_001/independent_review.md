# Independent bounded engineering review

Separate read-only Codex reviewer: `owner_binding_review`. No file changes, test reruns, physics, model/policy calls, or broad historical re-audit by the reviewer.

**Final verdict: `PASS_OWNER_AUTHORIZATION_BINDING_NONPHYSICAL_ENGINEERING_REVIEW`.** Bound to qualification HEAD `62745c562b7375258042ea41208bc27f07af4606`, operational Python HEAD `99da89671c1c16e1a745bf52df95ed39c3c92819`.

The reviewer inspected PR25's frozen entry contract, all new executable paths, the three authority kinds, consumption ordering, direct Worker rejection, Source/Readiness binding, saved unit results and actual separate-process qualification. Real Owner allowlist remains empty; real acquire/worker have no positive dispatch path. Owner record comparison is a **canonical JSON SHA** against externally reviewed frozen anchors, not raw-file equality, production authentication or online proof of a claimed GitHub identity.

## Findings and retained fixes

The first code review found Backend expiry not rechecked; duplicate campaign close masking final result-write failure; failure receipt potentially written into an old output; and child timeout not limited by remaining campaign budget. Each was repaired with targeted fault injection. A genuine process test additionally failed before the first child spawn because the P1 subprocess proxy lacked `STDOUT`. Its frozen candidate, Readiness and complete raw failure remain in `blocked_candidate_001`; no result was relabelled.

The next process candidate correctly refused the first actual Worker: frozen Windows CPython uses a venv redirector, so a direct-parent assumption did not match the actual process chain. `blocked_candidate_002` retains that failure and its identities. The fix queries live parent/image metadata and allows only direct parenthood or exactly one frozen launcher, verifying actual launcher/runtime paths and binary hashes. Backend repeats it, and consumed markers bind the actual runtime PID. It is not an ancestor-search bypass.

Source/checker comparison confirmed those fixes preserve the original P1 source, error taxonomy, scientific contract and parent branch. The reviewer read the saved 51/51 test result and final two affected checks; the earlier 45 PASS / 1 FAIL assertion mismatch remains recorded.

## Final saved-evidence verification

- All 579 Source entries and 20 Readiness members were read and hashed: zero mismatches. Seven operational Python files match their pinned Git blobs.
- Source SHA `5bd0db97166b62866ac5b9af671043fed6bd8b8f902ed09f82fa8acc6d36d22a`; Readiness SHA `690eca5e4aea89d29014b6cb4207f4da7c56af39871cdebe34a49884151bb67b` independently matched.
- Parent PR25 Readiness `8dd88843…63e282b0` is unchanged; relative diff contains only additions in the new namespace.
- QA raw-log SHA `a68d106d931577912b8da6c5e4996615c2747109638a4f60936f0907d482c452` independently matched. Nine actual CLI cases have the expected exit/rejection results and zero import-tripwire hits.
- Six independent runtime Workers used the same Supervisor and distinct runtime PIDs. Each parent is the issued launch-handle PID. Supervisor receipts, substitute results and actual worker logs agree with the acceptance record (universal-newline LF representation of raw CRLF logs is explicitly accounted for).
- Six issued/used/backend/completed marker sets are complete; campaign is persistently closed with six completed cells/no retry. Replay, worker self-authorization/copy, tampered record, wrong HEAD and wrong Readiness are rejected.
- Both blocked-candidate archive indexes match every archived byte; the obsolete Readiness identities are retained and explicitly rejected.

## Boundaries and stopping condition

No remaining blocker was found for the narrowly scoped **TEST_ONLY nonphysical authorization flow**. Real Owner approval, real physical/model/policy execution, production identity, concurrent atomicity, hostile local-ledger defense, PID reuse and hardware safety remain unproved/disabled.

The reviewer additionally identified that the unchanged P1 watchdog kills the launch handle, which does not prove termination of its redirected runtime. `contract.json` explicitly records runtime timeout termination **NOT_PROVEN** and an actual-acquisition blocker. This task does not expand into a new process-group termination mechanism or modify frozen P1. Binding the frozen budget and finishing a successful nonphysical process flow are not proof of a runtime hard-wall guarantee.

The final delivery may add only this review, reports and raw evidence. One fresh final-HEAD preflight is required; unchanged process tests can be reused. This review does not grant physical authorization, merge approval or scientific promotion. Stop after independent Draft PR delivery.
