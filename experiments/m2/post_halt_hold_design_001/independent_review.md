# Independent design-only review

Two read-only subagent audits examined the current main StopSkill/controller/Halt sources, M2.4 published first-crossing analysis and selected sealed raw archives, then reviewed this candidate protocol and offline checker. Neither reviewer edited files or ran physics, policy or provider acquisition.

**Verdict: PASS for a bounded design-only Draft PR. Physics remains BLOCKED.** The reviewers confirmed that the selected Seen and Turn45 parents are strict-failure/`HALT_SUCCEEDED` states with zero postqualification hold evidence, and that the normal control is an ordinary successful Stop, not a matched failure state. The fixed 2 s / 1,000-step seeded rolling-window criterion distinguishes persistence from the historical first crossing. The original `INCONCLUSIVE` verdict is preserved.

Review issues and resolution:

| Finding | Disposition |
| --- | --- |
| A reset between the qualifying terminal step and first hold snapshot might escape a `post_entry` witness, especially for hidden recurrent memory. | Reset-call witness now spans the qualifying Stop step through hold completion. Same controller/policy object and no reset calls are required; hidden LSTM byte equality remains unproven. |
| Parent strict PASS/no Halt trigger and strict FAIL/no Halt request were merged into one no-hold reason. | Split into distinct frozen result codes; neither can be counted as hold success. |
| The new 0.20 m path bound was described as if exactly implied by sampled speed. | Explicitly label it a separately frozen prospective criterion, motivated by 0.1 m/s × 2 s; discrete path and speed integration can differ. |
| The offline verifier relied on Python `assert`, which can vanish under `-O`. | Replace with explicit `ValueError` guard; mutation tests exercise fail-closed behavior. |
| Archive hashes alone did not machine-check the selected historical outcomes and pre-hold step premise. | Verify sealed raw `parent_result.json`, `witness.json` and refusal-arm `stale_state_step.json`; enforce strict-failure/Halt and normal-Stop membership and derive 7,139 / 8,266 / 5,991 pre-hold steps. |

The offline check now verifies 16 pinned source/config/evidence files, three complete selected archives, eight selected sealed raw members and the published 178-file raw manifest. Three targeted tests pass. These checks establish provenance and protocol consistency only. They do not show that G1 remains physically stopped for two seconds, that future observer instrumentation is non-interfering, or that the hidden policy state can be directly compared. The experiment-specific adapter, execution freeze, target preflight and a separately authorized physical run remain outside this PR.
