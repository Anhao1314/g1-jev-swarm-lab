# Negative Results and Failed Hypotheses

Negative results are retained because they changed the architecture and prevented later experiments from resting on false assumptions.

## 1. PD-only standing was not sufficient

**Observation:** a direct PD standing approach fell after approximately 1.29 s.

**Why it mattered:** the project could not treat a visually upright initialization as a stable control policy.

**Response:** switch to the official Unitree locomotion policy rather than tuning a fake baseline into existence.

---

## 2. Repeated seeds were not independent evidence

**Observation:** Phase 1's five seeds produced identical trajectories.

**Failed assumption:** “five seeds” automatically means five independent robustness samples.

**Response:** Phase 1.1 added seeded physical perturbations and explicitly marked deterministic repetitions.

---

## 3. The first perturbation envelope was too easy

**Observation:** Phase 1.1 completed 237/237 runs successfully.

**Failed assumption:** a wide-looking collection of perturbations necessarily identifies capability limits.

**Response:** Phase 1.2 actively searched task failure boundaries.

---

## 4. Physical success did not imply task success

**Observation:** Phase 1.2 achieved 91/91 physical successes but only 54/91 task successes.

**Example:** friction 0.15 produced severe slip/drift without a fall.

**Architectural consequence:** risk and mission logic must distinguish physical health from task completion.

---

## 5. Segmentation did not improve long-distance walking

**Hypothesis:** split a long high-risk walk into several short low-risk walks.

**Corrected result:**

- direct 4 m: PASS;
- segmented 4 m: FAIL;
- 6 m / 8 m segmentation also worse than direct execution.

**Mechanisms observed:**

- Stop/restart overhead;
- accumulated state error;
- recurrent-policy memory reset made the reset treatment worse.

**Conclusion:** low-risk skill primitives do not compose into a low-risk sequence automatically.

---

## 6. LSTM memory reset was a real confound

**Observation:** segmented-reset was consistently worse than segmented-continuous.

At 8 m, reset heading error reached roughly -20.96° vs ~-13.21° for continuous memory.

**Consequence:** controller memory must be considered part of mission transition state.

---

## 7. A real evaluator bug invalidated part of Phase 1.2b's first report

**Bug:** segmentation emitted `final_lateral_drift_m`; evaluator expected `lateral_drift_m`.

Missing values became `+inf`.

**False conclusion produced:** direct 4 m was incorrectly labelled a task failure.

**Response:** full audit, raw-evidence preservation, alias-safe canonicalization, regression tests, rerun.

**Corrected conclusion:** segmentation was still harmful, but for real measured drift rather than a fabricated infinity.

---

## 8. HIGH-risk mission coverage was missing from the Phase 2.0 formal corpus

**Observation:** the negative benchmark covered validation failures and capability UNKNOWN, but no stable HIGH-only formal mission.

**Response:** retain this as a coverage limitation instead of inventing a HIGH example.

---

## 9. Phase 2.1 is not open-language understanding

**Observation:** controlled grammar achieved 100% on the frozen corpus.

**Interpretation boundary:** this does not imply unrestricted Chinese understanding.

Known limitations include:

- bounded synonym set;
- bounded number converter;
- controlled composition;
- finite unsupported-keyword vocabulary.

**Consequence:** Phase 2.2 must use a blind open-language set, not only replay the controlled corpus.

---

## General lesson

The project should prefer:

```text
honest UNKNOWN
honest FAIL
honest negative result
```

over expanding a claim until every cell in a table looks complete.

Several of the strongest architectural decisions in this project came from results that initially looked like failures.
