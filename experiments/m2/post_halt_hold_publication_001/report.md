# M2.5A Accepted-Main Publication and Integrity Report

**Accepted scientific verdict:**
`PASS_BOUNDED_POST_HALT_HOLD_IN_TWO_SEEN_SEED0_STATES_WITH_NORMAL_STOP_CONTROL`.
This independently submitted publication record is based on actual merge
commits, immutable reviewed sources and saved physical evidence. It does not
change the Research Ops scientific selection, authorize another acquisition
or authorize a new Mission. M2.4 remains **`INCONCLUSIVE`**.

## Publication sequence and immutable identities

| Item | Reviewed HEAD | Actual Merge Commit | Merge parents |
| --- | --- | --- | --- |
| [PR #14](https://github.com/Anhao1314/g1-jev-swarm-lab/pull/14), design/readiness | `d7fcb76b1acabd166f9c279d75e4a6a53783e979` | `e5140db37d94ce24efedfe967064d7a69604c298` | prior main `51b2f39`, frozen `d7fcb76` |
| [PR #17](https://github.com/Anhao1314/g1-jev-swarm-lab/pull/17), original evidence | `d0a04f46ac05f57abb85470905f021b139d485cd` | `3f0d6bad5d831563acf27af0283638d82de887ba` | `e5140db`, frozen evidence `d0a04f4` |

The owner explicitly authorized this publication chain, with independent
verification and **Merge Commits only**. PR #14 was reviewed and merged first.
PR #17 was then retargeted from the design branch to main; its HEAD remained
unchanged, its diff contained exactly the 27 evidence additions, and GitHub
confirmed mergeability before merging. No rebase, squash or frozen-history
rewrite occurred. This separate [Accepted-Main Decision](../../../ops/decisions/m25a-main-publication.json)
is reviewed and published through its own PR.

The accepted design tree is `2744be2cd8a0d70f9500f24264388c5f9933f9da`;
accepted evidence tree is `e52737beb624262af2a0cf0239d9c5eb62075dad`.
Both equal the independently computed merge trees. All 24 design and 27
evidence files equal their reviewed HEAD Git blobs. All **2,582 prior-main
paths preserve their mode and Git blob**, including ROS-R0/R1 publication,
historical M2.4 artifacts/results, controllers, thresholds and `ops/state.json`.
No prior-main file changed or was deleted. The [main acceptance receipt](main_acceptance.json)
seals all 51 integrated-file hashes and merge identities.

## Complete external review archive

The full language Codex [SCIENTIFIC_AUDIT.md](external_audit/SCIENTIFIC_AUDIT.md)
is preserved byte-for-byte, SHA-256
`5d37530806bb5d396c37a7354966692a31ff45b84c6c575c23479eb27ee8dddc`.
The complete [43-file hash verification](external_audit/raw_hash_verification.json)
is preserved byte-for-byte, SHA-256
`e3e0be959cdb6f51b7b2aa9bd8acfa313c202779f364831ce1332444042baed4`.
Both exactly match the [external review's GitHub reference](https://github.com/Anhao1314/g1-jev-swarm-lab/pull/17#issuecomment-6077040100).
Every one of its 43 hashes, lengths and true match flags was independently
checked against the accepted ZIP and original raw manifest; no discrepancy
was found. The external reviewer reports establishing its result before
reading/comparing the main report; that result and comparison are retained.

The [support archive](external_audit/language_codex_audit.zip) retains 28
unchanged supporting files: the full report, hash list, source/line-ending
audits, independent recomputation/restoration/continuity scripts, pre-comparison
result, comparison inputs/results, all three 1,000-window CSVs and the original
output hash seal. [archive_manifest.json](external_audit/archive_manifest.json)
binds every member. The duplicated `original.zip` and 43-file `restored/`
directory are represented by their byte-identical, already published raw ZIP
and manifest rather than repeated storage. Their bytes were checked, and the
manifest records exact reconstruction locators. Thus the full supplied audit
evidence can be reconstructed without acquisition. Original fixed machine
locators/scripts are intentionally not rewritten or presented as universally
portable software.

Full GitHub review bodies are separately archived in
[PR #14 review history](external_audit/github_pr14_reviews.json) and
[PR #17 review history](external_audit/github_pr17_reviews.json), with explicit
attribution and the reviewers' own limits. A review summary is not substituted
for the full external scientific report or 43-entry hash list.

## Three distinct source identities

The [source provenance receipt](source_provenance.json) records all 254 paths:

| Category | Paths | Exact meaning |
| --- | ---: | --- |
| Git raw-byte matches | 78 | Frozen execution SHA equals original Git blob SHA; accepted main preserves that blob. |
| LF → CRLF execution-byte matches | 85 | Git stores LF bytes; the explicitly verified Windows checkout conversion produces the frozen execution SHA. Git raw bytes and execution bytes differ. |
| Unversioned official assets | 91 | Ignored official model/policy asset bytes match the frozen local receipt; these are not Git blobs. |

**It is false to describe all 254 paths as Git raw-byte matches.** No source
manifest, line ending, asset or threshold was changed to obtain a match. The
frozen Windows execution identity remains the readiness/protocol identity,
while Git publication and archived acquisition bytes have separate hashes.
A fresh Linux or differently configured checkout is not automatically a
byte-equivalent execution environment. The recorded no-physics preflight
verified the original 41 installed dependency versions and 91 assets before
the already completed campaign; this publication only reuses that bound
receipt and performs source/hash inspection. Present local hashes and
historical machine metadata do not independently authenticate past execution.

## Qualified observation and retained negative evidence

The unchanged frozen design specified three seed-0 cells, one attempt each,
1,000 uninterrupted 0.002 s Hold steps per eligible cell and unchanged limits.
The complete campaign used 24,396 native steps. Whole-command elapsed was
32.5378347 s, a conservative upper bound for each sequential cell as well as
the campaign. Exact per-cell timing was not independently saved and is not
represented as measured. Retained target/audit/restoration checks bind the
97-test readiness and 11-test restoration receipts; no tests or physics were
rerun just to obtain this publication. The complete original ZIP has 43 files,
64,962,438 raw bytes and SHA-256
`780164d135b87975be8034fa6bc9db6ef8534f0041e9e41ef03a4494dfca876a`.

| Cell | Maximum 1 s rolling speed | Final speed | XY path | Instantaneous samples >0.1 m/s |
| --- | ---: | ---: | ---: | ---: |
| Seen failure/Halt | 0.099604884 m/s | 0.086390810 m/s | 0.135574498 m | 198 |
| Turn45 failure/Halt | 0.099437391 m/s | 0.090219608 m/s | 0.136287493 m | 209 |
| Unmatched normal Stop control | 0.078349090 m/s | 0.077928123 m/s | 0.141010946 m | 248 |

All 3,000 seeded rolling means, terminal speeds, XY path and sampled
finite/standing/no-fall checks passed the prospective frozen contract. The
first Stop qualification steps are 671 / 658 / 500; the original failed
parents remain failed. Recorded simulator/controller/policy object identity,
terminal-to-Hold state/counter continuity, exact zero commands and no additional
Hold reset/dispatch were verified. Hidden recurrent-memory bytes were not
captured, so interface witnesses are not hidden-memory byte proof.

Instantaneous peaks reach 0.144113 / 0.145732 / 0.142378 m/s. The frozen gate
uses rolling means plus terminal speed, not every-step instantaneous speed.
The two failure-state maximum rolling-window margins are only 0.000395116 /
0.000562609 m/s. Motion and small margins remain published negative/cautionary
evidence; this is not immobility or robustness to perturbation. Normal Stop
is not a matched causal control. Two previously seen deterministic seed-0
states and a two-second window do not support general reliability, longer
waiting, hardware/production safety, recovery of the failed Mission or new
Mission authorization.

## Final gate and stop

Independent release review verified the frozen HEAD/readiness, all three
source categories, original ZIP/member hashes, companion manifest, full
external review bytes and bounded interpretation. No integrity or scientific
publication blocker remains. The separate publication PR adds only new
decision/archive/verification records and must retain all already accepted
source files. After its Merge Commit, the final read-only gate verifies actual
parents/tree, archive/hash bindings and unchanged prior-main paths; the PR
discussion records that actual final SHA without recursively rewriting this
historical acceptance receipt.

Research Ops still selects M2.3b. Its historical design-only wording is not a
current publication index; separate accepted-main decisions record M2.4 and
M2.5A publication without rewriting that pointer. No new MuJoCo sampling,
retry, policy/provider call, training, Jev, ROS-R2, Multi-Swarm, Language
Runtime/D011 or hardware operation occurred in this release. Publication
completion is the stopping condition; **M2.6 is not authorized**.
