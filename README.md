# G1 Jev Swarm Lab

**Research testbed for long-horizon Unitree G1 tasks with decision models, multi-swarm orchestration, and reinforcement-learning skills.**

> This repository is an experimental research testbed. No performance claim is considered valid without reproducible experimental evidence.

## Research question

Can a layered embodied-agent runtime improve the reliability and efficiency of long-horizon Unitree G1 task execution by separating:

- **reasoning** — mission understanding, decomposition, replanning, and multi-swarm coordination;
- **decision** — bounded high-level action/skill selection and escalation;
- **control** — learned or deterministic embodied skills executed by the robot.

The project will specifically investigate **Jev as a high-level decision model** inside this stack, rather than assuming it is beneficial.

## Target architecture

```text
Natural-language mission
        ↓
Mission compiler / task graph
        ↓
Multi-swarm reasoning
        ↓
Jev decision layer
        ↓
Skill router
        ↓
RL / deterministic skill library
        ↓
Unitree G1 in simulation
        ↓
World + robot feedback
        └──────────────→ runtime
```

Safety-critical low-level control is never delegated to a language or decision model.

## Initial research scope

The first research track is a simulated long-horizon G1 mission with staged navigation, interaction, disturbance, recovery, and return-to-base behavior.

Primary comparisons will isolate the contribution of:

1. single-agent vs multi-swarm reasoning;
2. with vs without Jev decision routing;
3. fixed scripted skills vs learned RL skills where appropriate.

All compared systems must use the same task definitions, seeds, skill interfaces, evaluation protocol, and disturbance schedule unless an experiment explicitly studies one of those variables.

## Current status

**Phase 0 — repository and research protocol initialization.**

No G1 training result, Jev benefit, swarm benefit, sim-to-real result, or performance improvement is claimed yet.

## Repository map

```text
configs/        experiment, robot, task, and skill configuration
docs/           research charter, architecture, hypotheses, protocol
src/g1swarm/    runtime implementation
experiments/    experiment definitions and reports
scripts/        reproducible entry points
tests/          unit and integration tests
checkpoints/    local model outputs (not committed)
artifacts/      local experiment outputs (not committed)
```

## Evidence rule

A result is considered reportable only when it can be traced to:

```text
experiment
→ config
→ code revision
→ seed
→ trajectory / decision log
→ metrics
→ artifact
→ report
```

Failed and negative runs are retained when they are relevant to the conclusion.

## Environment policy

The previously validated MuJoCo/PyTorch environment is treated as an external baseline and is not modified by this repository during Phase 0. G1-specific dependencies will be introduced only after compatibility and reproducibility are reviewed.

## Research documents

- [Research goal](docs/research-goal.md)
- [Architecture](docs/architecture.md)
- [Hypotheses](docs/hypotheses.md)
- [Experiment protocol](docs/experiment-protocol.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
