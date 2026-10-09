# M2.5A design and reproducibility review

**Gate: DESIGN_REVIEW_READY / PHYSICS_BLOCKED.** This branch freezes one candidate three-cell, two-second study for independent review. It does not authorize or contain a runnable MuJoCo acquisition. M2.4 stays `INCONCLUSIVE` with its original audit PASS; the Research Ops scientific selection stays M2.3b. The latest main used here is `0eff13a5cb523690cde31a742cc985e9ee0eaf03`.

The [protocol](protocol.json) declares entry states, zero-command continuation, exact rolling score, negative cases, state/command/reset witnesses, hard budgets and stop conditions. [Source binding](source_binding.json) pins 16 relevant current code/config/evidence files and archives by SHA256. The [offline verifier](offline_check.py) reads only those files, validates the 178-entry original raw seal, checks eight selected archived members (three `parent_result.json`, three `witness.json`, two `stale_state_step.json`) against the seal, confirms the two published first-crossing records have zero hold steps, and checks the candidate budget/authority invariants. Its targeted tests reject accidental physics authorization, window/command/reset changes, budget change and source-hash tampering. No simulator, policy or provider is imported or called.

The historical record supports choosing Seen and Turn45 as two **observed** strict-failure/Halt-success states and normal Stop as a recording control. It does **not** predict whether either failure state will pass the new hold criterion. The 2 s length and 0.20 m hold path gate are prospective choices; neither is a previous measured result. The control has a different route history and cannot identify a causal failure-vs-normal effect. One deterministic seed and three states cannot estimate reliability rates, disturbance robustness or hardware safety.

Before any real acquisition, an independent reviewer must accept or amend this candidate while it is still unexecuted. A new experiment-specific continuation adapter, source/asset/dependency closure, write-once raw journal, watchdog, reset/command/dispatch witness and target-environment preflight must be frozen and audited. Offline fake-session tests must exercise eligible and missing-trigger/Halt-failure/control-failure paths, zero-command 1,000-step continuity, budget and observer equivalence. **A separate explicit user authorization is required after that review.** If any prerequisite fails, physics remains blocked. No result-driven cell substitution or retries are allowed after acquisition begins.

The standalone offline check is:

```powershell
& .venv\Scripts\python.exe experiments\m2\post_halt_hold_design_001\offline_check.py
& .venv\Scripts\python.exe -m pytest experiments\m2\post_halt_hold_design_001\test_offline_check.py -q
```

These commands read existing archives and run no physics. They do not substitute for the later target-environment preflight or independent scientific postrun audit.
