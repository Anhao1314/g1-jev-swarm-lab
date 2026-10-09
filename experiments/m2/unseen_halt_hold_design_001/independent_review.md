# Independent candidate design review — 2026-10-09

Reviewer: separate read-only Codex subagent `m26a_independent_design_audit`. This is an independent agent review, not a human Owner acceptance or an external laboratory qualification. The root agent archived the review findings below; the reviewer did not modify this bundle.

**PASS_BOUNDED_PROSPECTIVE_DESIGN_REVIEW. NOT_READY_FOR_PHYSICS_ACQUISITION.** No unresolved design issue requiring a replacement candidate was found. This verdict is not a scientific qualification PASS.

Reviewed exact hashes:

| Artifact | SHA-256 |
| --- | --- |
| protocol.json | `1f0fd8aa4eeead99348dabccb747de0ebf5d45f854c4ff8840f6c81fb7e096f9` |
| design.md | `610301e9e31c662622fb9883b5fd7287b7783834035f38e020289733a418bb5e` |
| check_design.py | `f0b3eca51364758ecf50f3d7401e32ad2fbd960b4da414468d779814d7b29afe` |
| test_design.py | `6627e08970655cfece26e5443aad3b84f91895c902ebb6ec6aa660e308931e4f` |

The reviewer independently verified all 30 accepted-main Git source bindings, all 35 inventory checkout/Git hash pairs, and that eight inventory byte differences are CRLF/LF-only. Existing tracked historical files were unchanged. The corrected targeted suite passed 27/27 in 6.80 s in the reviewer process; that timing is a reviewer report, separate from the root process's retained raw 6.78 s receipt. No simulator, policy or provider call was made. An extra synthetic test with nonzero roll/pitch confirmed global XY translation and yaw rotation do not create qualifying physical novelty (only sub-microdegree floating-point residue).

The six fixed conditions, two predeclared primaries, force direction/timing comparisons, prefix pairing and dual-checkpoint distinctness form a testable bounded question. They do not establish IID, seed independence, complete hidden-state independence or project-wide novelty. Convergence, missing strict trigger, TIMEOUT/fall without Halt, technical censoring and aliasing are retained and cannot be filled in as PASS. Stop's first mean crossing and the subsequent Runtime qualification are distinct. Normal Stop is outside the failure-Halt denominator.

Review findings and dispositions:

1. Initial timing checker used an incorrect YAML key (`skills` rather than `skill_parameters`). Corrected before any acquisition. Root initial 24-pass/1-fail log and subsequent 27-pass log are both retained. This is a design-check technical failure, not a physical result.
2. Synthetic classifier needed to exclude normal Stop from requested-Halt denominators and veto support when seen/control physical outcomes fail. Corrected, with targeted fixtures. Valid distinct counterexamples remain preserved even when later cells are technically partial.
3. An independent assertion initially equated checkout hashes with Git hashes and failed. The inventory now explicitly keeps both domains; the eight mismatches were independently confirmed to be only newline conversion. The original assertion failure was an audit assumption failure, not historical evidence corruption. No standalone raw log was retained for that reviewer-only assertion; this limitation is explicit.

Remaining acquisition gates: Owner acceptance of design; six-cell experiment-only adapter and independent raw scorer; force/exception clearance, observer equivalence and continuity tests; complete executable/asset/dependency freeze; target-environment nonphysical preflight; one exact execution HEAD/Readiness SHA; and separately explicit Owner physics authorization. M2.4 INCONCLUSIVE, M2.5A's bounded conclusion and Research Ops selection remain unchanged.

Final independent seal check: **INDEPENDENT_CANDIDATE_SEAL_PASS**. Manifest SHA-256 `16c03d52623c705bae481ae512e9f9371f0d5bb246d7ec0eed3607e100f32ee5` and **8/8 exact LF core-file hashes** matched. `physics_authorization=false` and `UNMEASURED_NO_PHYSICS` remain explicit. The final seal check did not repeat tests or invoke physics. This is a candidate design seal, not execution readiness.
