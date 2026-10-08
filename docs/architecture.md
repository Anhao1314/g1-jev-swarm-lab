# Architecture v0.1

> Historical target architecture. This document describes research directions,
> not the R1 implementation. The [project README](../README.md) records the
> current Oracle Mission IR → deterministic Task Graph → G1 skill → measured
> feedback path. Jev, Multi-Swarm, natural-language dispatch, and hardware
> emergency stopping have not been accepted into that runtime.

## Principle

Different time scales and responsibilities must remain separated.

```text
Natural-language mission
        ↓
Mission compiler
        ↓
Task graph / mission state
        ↓
Reasoning layer
(single agent or multi-swarm)
        ↓
Decision layer
(rule baseline or Jev)
        ↓
Skill router
        ↓
Skill policy
(RL / imitation / deterministic)
        ↓
Robot control interface
        ↓
Unitree G1 simulation
        ↓
Observation + event stream
        └──────────────────────→ runtime
```

## Responsibility boundaries

### Mission compiler
Converts user intent into a structured mission representation. It does not issue joint commands.

### Reasoning layer
Handles decomposition, semantic planning, recovery planning, and task-level replanning. Experiments may replace this layer with a single agent or multi-swarm implementation.

### Decision layer
Chooses among a bounded set of legal high-level actions such as:

- continue;
- select skill;
- replan;
- recover;
- request more perception;
- ask for higher-level reasoning;
- stop / abort.

Jev belongs here in the experimental architecture.

### Skill router
Maps a legal decision to a verified skill implementation and enforces preconditions.

### Skill layer
Executes embodied behavior. A skill may be:

- a reinforcement-learning policy;
- an imitation policy;
- a deterministic controller;
- an official robot high-level primitive.

The experiment must record which implementation was used.

### Safety boundary
Safety-critical limits are deterministic and cannot be bypassed by a language model, swarm, or decision model.

Examples include:

- invalid joint targets;
- configured velocity / torque limits;
- fall-risk emergency stop;
- collision stop;
- unavailable skill;
- decision outside the allowed action set.

## Runtime state

The runtime should eventually expose a compact, typed state rather than streaming raw simulator data directly into reasoning models.

Candidate state groups:

- mission phase;
- active subgoal;
- active skill;
- skill progress;
- robot stability;
- environment events;
- recent failures;
- retry count;
- decision history;
- uncertainty / missing information.

The concrete schema is intentionally not frozen in Phase 0.

## Jev integration boundary

The first Jev integration must be replaceable by a deterministic baseline through the same interface.

Conceptually:

```text
DecisionInput
  state
  legal_actions
  decision_question

DecisionOutput
  selected_action
  scores / probabilities if available
  metadata
```

No Jev-specific output should leak into the skill implementation.

## Experimental modularity

The following components must be swappable independently:

- reasoning strategy;
- decision strategy;
- skill implementation;
- task definition;
- disturbance schedule;
- evaluation policy.

This is required for meaningful ablation studies.
