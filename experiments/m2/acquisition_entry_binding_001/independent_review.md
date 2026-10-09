# Independent scoped engineering review

Reviewer: separate Codex sub-agent `entry_binding_review`. Read-only source and saved-receipt review; it did not modify files, rerun tests, run physics, invoke a policy/provider or expand historical auditing.

**Verdict: `PASS_ACQUISITION_ENTRY_BINDING_NONPHYSICAL_ENGINEERING_REVIEW`.**

Bound to qualification HEAD `7976d33d8cc96eb5326256de43720a08d7ddf499` and operational code HEAD `7edf79fa78d95f2020ed11b597ac014d44646db3`.

Source SHA `b91578f63bdeb1d87aeb0e3b8f7e02f49c6a1d7c9c8143a7235ad8a89382cac3` and Readiness SHA `8dd88843f4abd9b283076b4e42c73c317b0863336e861f41fd3bbbc663e282b0` were independently matched. All 531 source files and 11 Readiness members were read and hashed: zero mismatches; zero missing PR22 source members. Six new Python execution files are pinned to the code HEAD. The code-to-qualification diff contains only metadata/receipts. Six-cell membership/order, budgets, 2-second/1000-native-step Hold match the original P1 freeze.

## Entry and preserved behavior

The new supervisor entry and direct worker execute the new full identity gate and real authorization rejection before loading the frozen adapter. The adapter preflight and backend guard repeat those checks before possible live imports. Rebinding only the new instance's `HERE`/`READINESS` routes all supervisor child commands to the new entry. The original P1 `exception_observer`, `assess_hold`, `run_cell`, native/wall budgets, no-retry, prior/future directory checks and prefix audit remain the original implementation. The new audit replaces only its source-binding seam; raw numerical scoring and historical/normal-control functions remain unchanged function objects.

## Saved evidence checked independently

- Seven new task receipt SHA/byte values match `offline_test_receipt.json`.
- Corrected entry XML: 39 tests, zero failures/errors. Relevant P1 XML: 12 tests, zero failures/errors. Corresponding logs agree.
- Initial XML/log retains 38 PASS / 1 FAIL. The failure was the new AST-unparse quote assertion, repaired with a structural AST assertion; it did not change P1 code.
- Raw clean-process log SHA: `3a139cc62330316d6a649133613a0305ea88bd3db5afb6c3efcebc3a64d3a7b8`.
- Correct preflight exits 0 and reports the exact qualification HEAD/Readiness, 531 sources, 91 assets, 41 dependencies, 2 XML documents and NO_PHYSICS.
- Remaining 10 cases exit 1 for the expected HEAD/Readiness/Owner-authority rejection. Both acquire and directly invoked worker reject missing flags, asserted flags without Owner authority and wrong HEAD before adapter loading. `FORBIDDEN_LIVE_IMPORT` hits: zero in every case.

## Boundaries and final delivery check

No actual code blocker was found for this nonphysical engineering scope. This freeze deliberately denies all physical operations; positive dispatch ordering uses offline doubles only. Real physics, Owner positive authorization and a live backend positive path remain **NOT_PROVEN** and unauthorized. There is no production identity, concurrent atomicity, hostile-process/TOCTOU or hardware safety guarantee.

The reviewer stopped after this scoped source and retained-evidence review. The subsequent delivery commit adds evidence/documentation only. Its exact final HEAD requires a single new clean-process preflight receipt, externally referenced in the PR; the unchanged 11-case matrix need not be rerun merely for metadata additions. No scientific result or selection pointer is promoted.
