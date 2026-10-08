# Independent accepted-main review

**PASS_INDEPENDENT_MAIN_ACCEPTANCE.** Merge `884edde1dd19931a8cc3d33c0640a42874f2e6bf` has the expected parents `a114ec90a4f577420e6f183fe0c41cadedba03fd` and `1b390d70a3825508ef4d451884244924e24df9ac`. Its tree exactly equals reviewed PR HEAD; local `origin/main` points to the merge. This accepts the unchanged bounded M2.3b research baseline on main. The scientific verdict remains `PASS_BOUNDED_REAL_MUJOCO_TRUSTED_HANDOFF`.

Fresh byte checks verified all 36 Research Ops anchors and all 40 files bound by the retained independent audit. The existing 64-check numerical audit is reused, not rerun. All 67 locally present frozen source-manifest entries match; the 91 missing entries are ignored official assets in this isolated checkout. Asset absence limits future execution, not retained-result acceptance. No assets were copied or downloaded and no physics ran.

The retained 103 passing tests are applicable to this unchanged merge tree: 13 acquisition, 55 Console/compatibility, 13 frontend and 22 Ops. Receipt hashes and counts were freshly checked; no tests were rerun. The reused repository environment reports the same Python 3.11.9, MuJoCo 3.15.0, NumPy 2.4.6 and Torch 2.14.1+cu130 as the retained acquisition receipt. This does not assert fresh rendering, new physics execution or installed official assets.

The historical `ops/decisions/m23b-selection.json` remains byte-identical and retains `working_branch_only=true` and `PR_PENDING_NOT_ACCEPTED_MAIN`. A separately recorded main-publication decision may cite this review; the old decision is not rewritten.

No independent-state generalization, production authority, concurrent atomicity, durable replay protection, hardware safety or autonomous recovery follows. The parent remains FAILED; halt mean 0.0999695815 m/s narrowly meets 0.10. Trusted principal and host permission remain serial TEST_ONLY fixtures; the underlying executor remains callable. Jev and Language Runtime/D011 stay BLOCKED, and Phase 3A.5 stays PAUSED.

**Evidence:** exact check outcomes, identities, receipt hashes, environment versions and missing-asset list are in `independent_main_acceptance.json`. **Remaining blockers:** none for this scoped acceptance. Complete official asset verification is required before future physics. **Stopping reason:** accepted-main adoption is supported by unchanged retained evidence; this review performed zero physics/provider calls and authorizes no acquisition.
