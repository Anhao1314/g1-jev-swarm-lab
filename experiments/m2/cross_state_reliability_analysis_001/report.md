# M2.4 Cross-State Reliability Acquisition

Scientific verdict: **INCONCLUSIVE**. Acquisition completed; integrity PASS. This is a new research result, not accepted main or generalized reliability.

## Frozen provenance and execution

Baseline `02f2bca8ffff485e2fd9c71ce3f86d349497a7bb`; readiness SHA256 `14219b6edc85d8346a97d5e50895d924c1157c6abffab37bd926dbfe4b138f08`. Target preflight matched 241 source files, 91 official assets, 41 dependency versions and frozen authorization before any physics. The seven frozen cells ran exactly once, seed 0, unchanged controller, policy, evaluator, thresholds and protocol. Total 64,787 native steps / 270,000 permitted; root acquisition wall 60.204s / 840s. Each cell stayed within 120s and its native cap. No acquisition retries, state replacements, integrity aborts or extra simulator resets.

The exact copied protocol retains its historical `cross_state_reliability_design_001` identifier; the new acquisition and this separately derived analysis have distinct directories. Prior scientific verdicts and raw artifacts are unchanged. Research Ops selected evidence remains M2.3b; this result does not silently update its pointer.

## Seven-cell results

| State / arm | Native steps | Parent / Halt / assessment | New task or refusal outcome |
|---|---:|---|---|
| Seen / authorized | 13,128 | strict FAIL; Halt PASS; eligible | strict + physical PASS, 3/3 nodes; accepted-grant replay refused |
| Seen / refusal | 7,140 | strict FAIL; Halt PASS; eligible | six refusals, zero incremental dispatch / physics |
| Turn45 transition / authorized | 14,253 | strict FAIL; Halt PASS; eligible | strict + physical PASS, 3/3 nodes; accepted-grant replay refused |
| Turn45 transition / refusal | 8,267 | strict FAIL; Halt PASS; eligible | six refusals, zero incremental dispatch / physics |
| Fixed +Y 60N push / authorized | 8,004 | parent strict PASS; NO_HALT_TRIGGER | no issuance / assessment / new dispatch; missing failure-chain coverage |
| Fixed +Y 60N push / refusal | 8,004 | parent strict PASS; NO_HALT_TRIGGER | refusal contract not reached, not an authorization PASS |
| Normal control | 5,991 | ordinary strict + physical PASS | 3/3 nodes; no Halt or lifecycle |

The deliberate stale-state construction is one native step per eligible refusal arm, included in totals and separate from the rejected calls. Each rejection itself has zero physics, node, executor and reset increments. Initial session setup resets are retained; there is no reset between failure, Halt and the new mission. Original failed parent tasks remain failed and their evidence is preserved.

## Physical stages and cross-state differences

| Metric | Seen | Turn45 transition |
|---|---:|---:|
| Failed Walk endpoint lateral drift (m) | -0.548649 | -0.805182 |
| Failed Walk heading error (deg) | -9.479121 | -11.707249 |
| Halt duration (s) | 1.342 | 1.316 |
| Halt additional displacement (m) | 0.185365 | 0.189892 |
| Halt last-1s mean speed (m/s) | 0.09996958 | 0.09981606 |
| New mission final Stop instantaneous speed (m/s) | 0.00640728 | 0.00719530 |
| New mission final Stop last-1s mean speed (m/s) | 0.06764572 | 0.06881227 |

Both Halt means pass the unchanged 0.1m/s criterion but margins are only 0.00003042 and 0.00018394m/s. A threshold crossing with a small margin is not proof of robust stopping. Transition is not merely a world-coordinate transform: compared with Seen, joint-position maximum difference is 0.00468168, joint-velocity 0.3334539 and control 1.2830926; body-frame velocity and action differences also remain after removing yaw. This supplies one new bounded failure condition, not independent seeds or a broad physical envelope.

The fixed push was applied for exactly 100 native steps at 1.0–1.2s and cleared. Parent endpoint drift was +0.203459m against the unchanged 0.21m limit (margin 0.006541m), heading -4.396770deg; all parent nodes succeeded. Ordinary success is retained, but the planned additional failure-chain condition was not constructed. No outcome-driven replacement or stronger push was tried. There are no observed negative qualifying failure-chain cells; lack of the second new failure condition prevents the intended cross-state PASS. It does not establish FAIL of the mechanism either.

## Audit, transport and reproduction

Independent saved-data audit: 94/94 checks, integrity PASS, verdict INCONCLUSIVE. `audit.json` contains per-stage checks, margins, authorization reasons, state differences, reset/budget and immutable-plan checks. `raw_evidence_manifest.json` seals 178 original files (594,669,353 bytes), including native states, robot trace, poses, commands, forces, parent/child ledgers, events, worker logs and outcomes.

Original files remain untouched locally. Git transports their exact bytes in eight lossless `.tar.gz` archives under `../cross_state_reliability_archives_001`, with member and archive SHA256 inventories. `archive_evidence.py` verifies every original member hash and length without physics. To verify from a checkout, run the repo Python on this script without flags. To restore original paths into a fresh outside-repo directory, use `--restore-to ABSOLUTE_EMPTY_DIRECTORY`; it refuses existing targets and escaping paths. Run `audit.py --verify` from the acquisition worktree with restored raw paths for a read-only comparison to the retained independent audit. No acquisition command is part of reproduction of the audit.

The first recorded repeat audit command refused to overwrite existing audit output; that tooling exit-1 receipt is retained. It is not a physics failure or a rerun. A separate verification mode compares retained derived results without rewriting them. Historical source/readiness bytes and the baseline tracked file tree remain unchanged.

## Research Ops and boundary

Research Ops v0.1 routed the experiment and recorded actual preflight, acquisition, lossless-transport verification, audit and closeout commands. Retained telemetry is in `telemetry/`. Acquisition wall is measured; unmeasured reasoning/implementation intervals and model token counts are not invented. Worker output is in raw worker logs (root acquisition stdout is intentionally empty because workers redirect output). No Research Ops code or selected scientific pointer changed.

Only trusted serial TEST_ONLY complete-plan authorization is exercised. No concurrent atomicity, production human identity, hardware safety or arbitrary-state restart claim. Zero Jev/provider calls, PPO training, new recovery search, Language Runtime/D011 or Multi-Swarm. No automatic merge or follow-on acquisition.

Stopping reason: all seven frozen acquisitions and independent evidence audit are complete. Missing push failure-chain coverage and small stopping margins are explicit limitations; further sampling or protocol change requires a new reviewed authorization.
