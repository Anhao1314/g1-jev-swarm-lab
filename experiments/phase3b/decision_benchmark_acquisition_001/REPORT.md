# Phase 3B.0a — frozen decision-benchmark acquisition

**Verdict: `RECOVERY_VOCABULARY_NOT_READY`; Jev offline shadow remains `NOT_READY_FOR_JEV_SHADOW`.** The preregistered benchmark has one `CONTINUE` state and two `ABSTAIN` states, but no state with a unique admissible recovery. The frozen stop rule therefore ended acquisition without a confirmation run, additional state, or recovery adjustment. This is a development result for a small, correlated 16m route family; it does not show that no suitable state exists elsewhere.

## Frozen acquisition and reachability

The [protocol](protocol.json), [case membership](cases.json), and [source manifest](source_manifest.json) were committed before physics (`ba2e8496`). The same 16m Stand→Walk8m route was used at its historical 10s Stand decision, with a 5s Stand transition, and with a single +Y 60N, 0.2s push at 9.5s during the 10s Stand. Phase 1's 60N/0.2s perturbation and the existing Stand-transition machinery supported this bounded construction; no old outcome was used to predict its label. All three predecision states were reached. The push was applied from 9.502s to 9.702s and was inactive before Walk entry. Each state received the same four frozen modes: off, lateral, yaw, and combined; α=0.5, actual-start origin, 14s authority, bounds, policy, controller, reference rule, evaluator, seed, and Oracle remained fixed.

The original nominal four-cell control matched retained Phase 3A records, traces, complete physics streams, predecision physical state/reference, and initial/final policy-state hashes arm by arm. The first acquisition stopped after those four cells because a new audit incorrectly required a stateful TorchScript tensor digest to be stationary through the episode. The stopped evidence and `AUDIT_FAILED` statuses remain in [attempt01 evidence](evidence/primary_completion.json) and commit `b7146643`. A versioned [amendment](amendment_attempt02.json), committed as `f0c1079`, corrected only this audit assumption and a decision-time versus episode-start digest comparison. The second attempt SHA-verified and re-audited the four retained controls, then executed the eight preregistered novel cells in a separate [evidence export](evidence_attempt02/primary_completion.json). The 180s cap applied separately to the resumed attempt; the original maximum of 16 complete executions was respected (12 primary executions total, no confirmation). There was no infrastructure retry or replacement of a scientific negative.

## Same-state outcome matrix

Each entry shows **all-node strict / physical / final world endpoint norm in metres**. Nominal passed in all 12 cells. A recovery requires all gates plus a strictly lower endpoint norm than its own off comparator and no worse absolute commanded-axis lateral or heading error. `CONTINUE` takes priority when off passes.

| Predecision state | CONTINUE | LATERAL | YAW | COMBINED | Frozen Oracle |
| --- | --- | --- | --- | --- | --- |
| Historical 10s Stand | FAIL / PASS / 1.20907 | FAIL / PASS / 1.21221 | FAIL / PASS / 1.23039 | PASS / PASS / 1.26476 | `ABSTAIN` |
| 5s Stand | PASS / PASS / 0.87580 | PASS / PASS / 0.92766 | PASS / PASS / 0.94693 | PASS / PASS / 0.99381 | `CONTINUE` |
| 10s Stand +Y push | FAIL / PASS / 1.08870 | FAIL / PASS / 1.07850 | FAIL / PASS / 1.11543 | FAIL / PASS / 1.11279 | `ABSTAIN` |

The historical combined arm satisfies strict and physical, but its endpoint norm is worse than off (1.26476 versus 1.20907m). At 5s Stand, off already satisfies strict and physical and has the smallest endpoint norm; recovery would be unnecessary. In the pushed state, lateral improves endpoint norm and commanded-axis lateral/heading against off, yet fails strict, so the Oracle cannot authorize it. All negative cells are retained in the [SHA-bound benchmark](benchmark.json); none was inferred from a different predecision state.

## Observable decision structure and limits

Across all four arms of each state, full predecision qpos/qvel/ctrl, selected reference, policy digest, and serialized decision snapshot matched exactly. The frozen state schema distinguishes these situations through route position and heading before action: relative to historical 10s Stand, 5s Stand changes route Y by +0.12175m and route heading by +2.74048°, while the push changes route Y by +0.19576m and route heading by −0.65889°. The actual-start local lateral error is 0 and instantaneous strict margin is 0.28m in all three; those fields alone cannot distinguish the states. These are observable differences, not evidence that the schema captures every relevant dynamic variable. In particular, the frozen schema omits velocity although the physical-state audit includes it.

There is a real off-versus-abstain distinction, but no observed positive recovery choice. The benchmark therefore lacks the selection structure required for Jev shadow evaluation. The Oracle is fail-closed and remains independent of any Jev output. No Jev API, PPO, reward change, Runtime, Multi-Swarm, profile scan, or additional physics state was used.

## Evidence integrity, telemetry, and stop

The [attempt02 manifest](evidence_manifest_attempt02.json) binds 94/94 exported files; the first-attempt manifest binds 38/38. Independent review rehashed exports, reproduced all 12 outcome values and three Oracle labels, confirmed same-state predecision snapshots and the push ending before Walk, and found no missing or censored matrix cell. The [benchmark builder](build_benchmark.py) independently rechecks file hashes, exact source locators, all four outcomes per state, and frozen Oracle labels. Targeted acquisition, Oracle, benchmark, and Research Ops tests: **54 passed**.

Research Ops v0.1 routed this as a mechanism experiment. Recorded stage telemetry: context 0.38s; prereg reasoning lower-bound 77s; implementation lower-bound 442s; experiment commands 30.70s stopped first attempt plus 60.23s resumed attempt; final targeted test command 5.45s; evidence rebuild audit command 1.73s. Intervals may overlap and do not measure total human/agent elapsed time or model tokens. The second attempt's 60.23s includes SHA verification, eight new physics cells, export, and scoring; 12 cells in the final matrix are **four inherited plus eight newly executed**, not 12 new simulations in that attempt.

The preregistered acquisition is complete and has no unique recovery state. The stipulated response is to stop and retain this negative result, not search another severity, state, window, or action in this phase.
