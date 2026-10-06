# Research Goal v0.1

## Problem

Long-horizon embodied tasks are not difficult only because motor control is hard. They also require task decomposition, skill selection, state tracking, recovery, replanning, and deciding when expensive reasoning is actually necessary.

This project studies those layers on a simulated Unitree G1.

## Core goal

Build and experimentally evaluate a layered runtime that can translate a natural-language mission into a long-horizon G1 task while separating:

1. **Mission reasoning** — understanding goals, decomposing tasks, replanning, and coordinating specialist agents or swarms.
2. **Decision** — selecting a bounded next action, skill, recovery path, or escalation route.
3. **Embodied control** — executing locomotion, balance, manipulation, or recovery skills through learned or deterministic policies.

Jev is treated as an experimental decision component, not as a presumed improvement.

## Target mission family

The initial mission family is a warehouse-style autonomous task containing multiple dependent stages, for example:

```text
receive mission
→ navigate to target area
→ locate target
→ approach
→ interact / transport
→ encounter disturbance or route change
→ recover / replan
→ complete delivery
→ return to base
```

A task is considered long-horizon because later stages depend on world state produced by earlier stages, not merely because the episode lasts a long time.

## Research questions

### RQ1 — Decision layer
Can a bounded decision model improve high-level skill selection or escalation compared with scripted rules or a generative planner?

### RQ2 — Multi-swarm reasoning
Does multi-swarm reasoning improve long-horizon task completion and recovery compared with a single reasoning agent when the low-level skill library is held constant?

### RQ3 — Jev × swarm interaction
Can Jev reduce unnecessary swarm reasoning calls while maintaining or improving task success and recovery?

### RQ4 — Skill composition
Can independently trained or deterministic embodied skills be composed reliably into longer missions without retraining an end-to-end policy for every task?

### RQ5 — Robustness
How do the systems behave under route blockage, observation ambiguity, external disturbance, skill failure, and missing-action conditions?

## Non-goals for the first stage

- end-to-end language-to-joint control;
- training a foundation robot model from scratch;
- claiming sim-to-real transfer before hardware validation;
- optimizing leaderboard reward without a mission-level hypothesis;
- adding components whose contribution cannot be isolated experimentally.

## Success criterion

The project succeeds as research only if it produces reproducible evidence that isolates which architectural components help, hurt, or do nothing.

A polished demo without controlled comparisons is not sufficient.
