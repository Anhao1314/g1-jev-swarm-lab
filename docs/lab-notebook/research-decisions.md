# Major Research Decisions

This file records decisions that shaped later experiments.

## D001 — Use Unitree G1 as the primary embodied platform

**Context:** the research goal required a humanoid platform suitable for learned locomotion, future manipulation, long-horizon tasks, and eventual real-robot transfer.

**Choice:** Unitree G1.

**Reasoning:** official G1 MuJoCo assets and locomotion policies provide a credible embodied baseline while leaving higher-level task intelligence open for research.

**Consequence:** Phase 1 focused first on validating the body/control layer rather than writing task intelligence against a toy Gym environment.

---

## D002 — Separate reasoning, decision, and control

**Choice:**

```text
Reasoning
→ Decision
→ Skill execution
→ low-level control
```

**Reasoning:** if LLMs, Jev, multi-swarm logic, and joint control all make decisions simultaneously, ablation becomes meaningless.

**Consequence:** the project can later compare deterministic decision logic vs Jev while preserving the same Runtime and robot skills.

---

## D003 — Jev is a future bounded decision layer, not a motor controller

**Choice:** reserve Jev for typed high-level decisions such as skill selection, escalation, replan, or stop.

**Rejected direction:** Jev → joint targets / torque.

**Reasoning:** the timing, safety, and experimental responsibility boundaries are incompatible with direct motor control.

**Revisit condition:** only if future evidence supports a different formally bounded use case.

---

## D004 — Do not enter language until the Oracle Runtime works

**Reasoning:** otherwise a failed mission could be blamed on language parsing, capability selection, Task Graph logic, or locomotion with no clean attribution.

**Result:** Phase 2.0 first proved the structured Mission Runtime independently.

---

## D005 — Do not use segmentation as automatic risk mitigation

**Evidence:** Phase 1.2b.

Repeated 2 m segments worsened long-distance drift and could convert a successful 4 m direct walk into a failed mission.

**Rule introduced:** a planner must not infer:

```text
LOW-risk skill
+ LOW-risk skill
= LOW-risk sequence
```

Sequence state and transition risk matter.

---

## D006 — Add outer-loop correction before replacing the RL policy

**Context:** open-loop G1 locomotion remained physically stable but accumulated heading/lateral error.

**Alternative:** retrain PPO or replace `motion.pt`.

**Choice:** first test a simple external heading/lateral feedback loop.

**Evidence:** Phase 1.3 expanded measured reliable distance from ~4.6 m to ≥20 m without changing policy weights.

**Consequence:** task-level control improved without destroying the provenance of the official locomotion policy.

---

## D007 — Establish a deterministic grammar baseline before evaluating LLM language control

**Choice:** Lark controlled-language compiler.

**Reasoning:** an LLM cannot be fairly evaluated if the alternative is an improvised regex parser with unknown quality.

**Evidence:** Phase 2.1 reached exact performance on its intentionally bounded frozen corpus.

**Consequence:** Phase 2.2 can measure the actual trade-off:

```text
extra language coverage
vs
semantic error
vs
unsafe acceptance
vs
latency
vs
cost
```

rather than merely showing that an LLM can produce JSON.

---

## D008 — GitHub evidence is canonical; notebook interpretation is secondary

**Rule:** measured claims come from frozen protocols and experiment artifacts.

The lab notebook explains why experiments were performed and how decisions were made, but it does not override machine evidence.

If the notebook and raw evidence disagree, the evidence must be audited and the notebook corrected.


---

## D009 — Do not promote the LLM compiler after Phase 2.2

**Context:** DeepSeek-v4.1flash improved blind open-language coverage from 0.5106 to 1.0 and valid exact IR from 0.53 to 1.0.

**Blocking evidence:** two malformed connector inputs in the frozen controlled regression were accepted as valid Missions.

**Choice:** keep Phase 2.2 verdict PARTIAL and enter Phase 2.2b Compiler Hardening.

**Rejected direction:** move directly to long-horizon language tasks based on the strong blind benchmark.

**Reasoning:** the language compiler is upstream of robot execution. A narrow but reproducible fail-open case is sufficient to block promotion even when aggregate accuracy is excellent.

**Revisit condition:** all required language safety gates return to zero on frozen regression and new held-out hardening tests without sacrificing the demonstrated coverage gain.
