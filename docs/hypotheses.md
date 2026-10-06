# Hypotheses v0.1

These are hypotheses, not claims.

## H1 — Jev decision utility

With the same reasoning layer and skill library, a Jev-based bounded decision layer can improve at least one of:

- high-level decision correctness;
- decision latency;
- invalid action rate;
- mission success;
- recovery success;
- reasoning cost.

without causing an unacceptable regression in safety or task completion.

### Null hypothesis
Jev provides no meaningful improvement over a deterministic or generative baseline under the tested conditions.

---

## H2 — Multi-swarm utility

With the same decision layer and skill library, multi-swarm reasoning improves long-horizon task completion or failure recovery compared with a single reasoning agent.

### Null hypothesis
Multi-swarm reasoning adds latency/cost without meaningful improvement.

---

## H3 — Jev as a reasoning gate

Jev can identify states that do not require expensive multi-swarm reasoning and route them directly to safe bounded actions.

Expected effect:

- lower swarm-call rate;
- lower high-level latency and/or cost;
- similar or better task success.

### Failure condition
Reduced swarm use accompanied by a material loss in mission success or safety is not considered an improvement.

---

## H4 — Confidence-aware escalation

If Jev exposes usable confidence or probability information, calibrated escalation thresholds can reduce incorrect autonomous decisions relative to unconditional execution.

The threshold must be selected using validation data and then frozen before final evaluation.

---

## H5 — Skill composition

A common skill library can support multiple long-horizon missions without retraining a monolithic end-to-end policy for every mission.

---

## H6 — Robust recovery

The layered runtime can recover from at least some injected failures more effectively than a fixed task script.

Candidate disturbances:

- blocked route;
- target relocation;
- external push;
- reduced ground friction;
- failed skill;
- ambiguous target;
- no valid skill available.

## Falsification policy

Negative results are valid results.

A component is not retained merely because it is architecturally appealing. If experiments show no measurable value, the project records that result and simplifies the system.
