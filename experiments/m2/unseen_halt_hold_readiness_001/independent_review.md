# Independent engineering readiness review — 2026-10-09

Reviewer: separate read-only Codex subagent `m26a_final_audit`, not an implementation author or human Owner. The root agent archived these findings. This is neither third-party hardware certification nor authorization to run physics.

**PASS_BOUNDED_NONPHYSICAL_ENGINEERING_READINESS → READY_FOR_OWNER_ACQUISITION_AUTHORIZATION.** No unresolved engineering blocker found after the recorded corrections. Scientific outcome remains UNMEASURED_NO_PHYSICS; retain Draft and stop.

The reviewer independently checked:

- Committed code HEAD `d465c2ad664154a16326649c616e643156734dd7` and exact source manifest SHA `4e241c65ed13e64cd256c15fa755c3330ab57c82c5ff7485aa4ad031c1aad74c`.
- Readiness SHA `c052cb3b155a2182be0481f530b3c3dcbee4fa53c74c38313c8e8220923207eb`; all 21 receipt bindings, all 363 source files and all eight sealed design files matched.
- Seven new Python files matched the committed Git blobs; source domains remained distinct: 148 raw Git-equal, 124 LF→CRLF execution byte identities, 91 official unversioned assets. These do not replace the historical 78/85/91 receipt.
- The retained final test log contains 111 PASS in 6.79 s, SHA `155961103b5fa4f1bf7bd6101ad574b4f9d06b56bff81a03f68dcc430eaefe3d`. The reviewer reused this exact receipt rather than repeating tests.
- Target receipt binds the exact code HEAD, source and Readiness and reports 41 dependencies, 91 assets, two XML documents/28 resource links, and no simulator/policy imports, model loads, physics or inference.
- Actual Runtime/Skill signatures, string node status, first-crossing metrics, force pre/post offsets, controller reset path and continued zero-command torque helper are compatible with the unchanged sources.
- All changes are additive in the engineering namespace; design, historical science, thresholds, controller and Research Ops pointers are unchanged.

Concrete review findings fixed before code freeze, with offline regressions:

1. Caught Stop/observer exceptions now retain technical causes rather than ordinary physical Halt failure; raw-proved nonfinite physical failure remains separately preserved.
2. Readiness/source maps reject conflicting overlaps. Campaign success/partial receipts bind execution HEAD, source, protocol, Readiness, budget and wall timing.
3. Supervision/cell/campaign timing captures include prefix auditing; hard timeouts stop without retry and retain unknown in-flight evidence.
4. A fallen terminal row cannot retroactively create a successful first Stop mean crossing. Entry posture and finite flags are included.
5. Full raw fixtures cover missing Stop return, completed Hold negative followed by technical interruption, failed normal control before Stop and unavailable nonfinite novelty.
6. A missing hardkill witness does not erase available raw hashes/prefixes or turn censoring into a physical FAIL. Actual Halt requests and independently scorable denominators are separate.

The report accurately limits observer evidence to read-only source seams and fake execution. Real-dynamics equivalence is unproven until separately authorized acquisition passes frozen historical and paired pre-pulse comparisons. Hidden recurrent memory is not directly snapshotted; operational distinctness is not IID or broad generalization. TEST_ONLY flags do not provide production identity, concurrent atomicity or hardware safety. A terminated process does not prove physical Halt.

The exact final runnable engineering HEAD is supplied separately after the receipt commit, avoiding a self-hashed commit. Final publication must preserve these source/Readiness bytes and verify that HEAD before handoff. Remaining gates are independent/Owner acceptance and separately explicit physical authorization of that exact HEAD, Readiness SHA and six-cell one-attempt budget. No new physics, inference, providers or acquisition was used in this review.
