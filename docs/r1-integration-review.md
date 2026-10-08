# Research Integration Baseline R1 — review record

R1 integrates the retained embodied research line into a review branch. It does
not change a scientific threshold, label, raw result, historical verdict, or
the separate Source Authority branch. It is a bounded MuJoCo research baseline,
not a production or hardware safety release.

## Integration identity and boundaries

- The merge commit `6903d277281c408a0f2757af5875aee6c24b4bd9` has parents
  `815622c956508b687c70a327d8dd1f6c5da474f5` (latest reviewed `main`)
  and `d1918ec9c3532cc8b71f8380a76959c82e8c2e36` (embodied research).
- All 14 `main`-only lab-notebook files retain their Git blobs. The research
  branch's `experiments/` tree is unchanged by the merge. README was the sole
  content conflict and was rewritten to describe the implemented system.
- The independent `phase2.4/source-authority` branch is not an ancestor of R1.
  Jev has no online authority; Language Runtime / D011 remains blocked.
- Research Ops selection was reviewed separately from the merge: the 10 earlier
  Phase 3A/Console anchors remain, 10 M2/R1 anchors were added, and `context`
  reports `CURRENT` with 20/20 matching anchors. The selection describes only
  the accepted bounded M2.0/M2.1 slice.

## Verification without new experiment execution

- M2.1 integration source manifest: 24/24 exact byte hashes matched after
  provisioning three ignored official Unitree assets in this clean worktree.
  The retained Console M2 manifest verified 9 derived and 11 source files.
- No-physics Python target: 98 passed, 2 live-session tests deselected. The
  two tests were excluded specifically because they execute MuJoCo physics.
  Frontend data tests: 10 passed. Research Ops targeted tests: 22 passed.
- Research Ops `check console`: `PASS_RETAINED_INTEGRITY`; 61 scientific
  exports verified. It correctly marks the old browser receipt as requiring
  fresh QA because the Console changed after that receipt.
- Fresh read-only browser QA of the R1 worktree Console: failure replay showed
  `STOP_DEPENDENTS` and independent physical-halt request at 12.94 s, then
  `HALT_SUCCEEDED` at 14.28 s with 0.056 m/s displayed at the final captured
  frame. The safe control showed three `CONTINUE` decisions, 3/3 task nodes,
  and `Halt NOT_REQUESTED`. The Console imported retained evidence; no robot
  command, provider call, training, or new physics execution occurred.

## Reproduction limits and remaining review

- The official Unitree model and `motion.pt` are deliberately excluded from
  Git. A fresh checkout must provision the pinned assets before full integrity
  checks; their hashes are in the frozen source manifests.
- R1 adds exact LF checkout attributes for source files pinned by the M2
  manifest. The older Console integrity test now checks historical Git blob
  preservation and permits only LF/CRLF checkout variants of its historical
  byte receipt. It does not relax the M2 manifest's exact-byte checks.
- The existing Research Ops Console receipt still reports
  `REQUIRES_FRESH_BROWSER_QA`; the fresh manual QA above is recorded here, not
  retroactively written into that old receipt.
- M2.1 demonstrates one seed-0 HIGH-risk MuJoCo failure and one safe control.
  Its last-one-second speed mean had a narrow margin below 0.10 m/s. No
  cross-state reliability, hardware emergency stop, Jev online use, or natural
  language authority is established. Final merge into `main` awaits review.
