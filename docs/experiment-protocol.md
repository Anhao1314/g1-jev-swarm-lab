# Experiment Protocol v0.1

## Purpose

Define the minimum evidence required before the repository makes a performance claim.

## Comparison matrix

The first architecture-level study should support a controlled 2 × 2 comparison:

| Group | Reasoning | Decision |
| --- | --- | --- |
| A | Single agent | Baseline decision |
| B | Single agent | Jev |
| C | Multi-swarm | Baseline decision |
| D | Multi-swarm | Jev |

The low-level skill library, mission set, simulator configuration, seeds, and disturbance schedules are held constant unless explicitly varied.

Additional baselines may be added later, including FSM/rule control or hierarchical RL.

## Run identity

Every experimental run should eventually record:

- experiment ID;
- git commit SHA;
- configuration hash;
- task ID;
- random seed;
- simulator and package versions;
- reasoning strategy;
- decision strategy;
- skill versions/checkpoints;
- disturbance schedule;
- start/end timestamp;
- success/failure status.

## Primary metrics

Mission-level metrics take priority over training reward.

Candidate primary metrics:

- full task success rate;
- subtask success rate;
- recovery success rate;
- time/steps to recovery;
- invalid high-level action rate;
- number of replans;
- swarm-call rate;
- decision latency;
- end-to-end completion time.

## Secondary metrics

Depending on the experiment:

- policy return;
- falls;
- collision count;
- path efficiency;
- energy proxy;
- token/API cost;
- calibration error;
- false escalation / missed escalation;
- skill-selection confusion matrix.

## Seeds and repetitions

Smoke tests may use a single seed.

Any comparative result intended for a report must use multiple seeds or repeated mission instances. The final number of runs will be selected after variance is measured in a pilot study rather than chosen for convenience.

## Failure injection

Failure scenarios must be deterministic or seeded where possible.

Each disturbance should have:

- trigger condition;
- magnitude;
- duration;
- expected observable consequence;
- recovery success criterion.

## Train / validation / test separation

Thresholds, prompts, rules, and decision gating parameters must not be tuned on the final evaluation set.

Final test scenarios should be frozen before the decisive comparison.

## Evidence retention

For reportable runs retain, where applicable:

```text
config
manifest
metrics
event / decision log
trajectory reference
checkpoint reference
failure events
summary
```

Do not keep only successful runs.

## Claim rule

A claim may enter the README only after:

1. the protocol for that experiment is frozen;
2. the compared runs complete;
3. artifacts are retained;
4. calculations can be reproduced;
5. known limitations are written next to the conclusion.

## Phase-0 restriction

Phase 0 performs no training and makes no comparative performance claim.
