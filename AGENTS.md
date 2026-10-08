# Agent Execution Contract

**Reason broadly, act narrowly, verify proportionally, stop decisively.**

## Research Ops entry

Before broad repository/history searches, load `.agents/skills/g1-research-ops/SKILL.md`
and run `.venv/Scripts/python.exe scripts/research_ops.py context` from this repo.
It derives current Git state and validates selected decision anchors. STALE means
inspect the named evidence and review pointers, never infer permission or verdict.
Route actual scope with `plan`: implementation, mechanism, scientific claim.
Safety/generalization/held-out/baseline adoption/formal scientific claims require
the claim tier and independent audit; ordinary UI/docs do not default to it.
For retained visual evidence use `g1-visual-evidence`; keep workflows in Skills
and current source locators in `ops/state.json`, not copied history in prompts.

## Scope and autonomy

- Solve one explicit question per task. Start by stating the question, task class, authorized change boundary, evidence needed, and stopping condition; keep this brief.
- Inspect branch, working tree, applicable protocol, retained evidence, and latest experiment decision before acting. Continue completed work rather than restarting it; preserve unrelated changes and untracked assets.
- Reason broadly about causes and alternatives; implement only what is necessary for the current question. Make routine, reversible choices autonomously within the authorized scope.
- A blocker prevents a valid answer or required deliverable. Record nonblocking findings with their impact and evidence locator; do not fix them opportunistically.
- If a foundational integrity or implementation issue invalidates the experiment, stop expansion, preserve partial evidence, and diagnose the cause. Repair only within authorized scope.
- Do not add frameworks, runners, daemons, dependencies, or architectural abstractions unless necessary for the requested deliverable. A possible next experiment is not authorization to run it.

## Task classes and validation

| Class | Scope | Proportionate validation |
| --- | --- | --- |
| **Surgical** | Bounded documentation, analysis, or implementation change | Inspect the diff and affected contracts; run focused checks only where behavior or claims require them. Documentation alone does not require physics or full regression. |
| **Experimental** | One hypothesis with a controlled intervention | Freeze the protocol and run budget before acquisition; validate the measurement path and minimum required controls. Preserve all outcomes and limitations. |
| **Release** | Integration, publication, or a declared release gate | Run the applicable release checks and provenance audit. Broader regression is justified by affected shared contracts or an explicit gate, not by habit. |

- Choose the class from actual scope, not as a way to bypass required checks. Git commit/push alone does not turn a Surgical task into a full Release campaign.
- Prefer targeted validation. Reuse prior passing evidence only when its code, configuration, environment, and covered behavior still apply; identify reused evidence and checks not rerun.
- Broaden or repeat checks only for a relevant change, failure, unresolved risk, or mandatory protocol/release requirement. Do not weaken a required check to save time.

## Expensive work and process discipline

- Before simulation, training, provider campaigns, or large regression, identify the unresolved decision it can change, why retained evidence is insufficient, the bounded cases/seeds/budget, and completion/abort criteria.
- Use the smallest reliable design consistent with the protocol. Stop optional expansion once evidence supports a verdict; finish mandatory frozen runs/checks or report the campaign incomplete. Do not scan extra parameters to obtain PASS.
- Give long-running commands a progress signal and an expected duration or inactivity limit. If progress stalls, inspect logs, process state, and output growth before another bounded wait; do not poll indefinitely or launch duplicate work.
- Persistent viewers/servers are not completion dependencies. Record their status and ownership; leave or stop task-owned processes as appropriate without disturbing unrelated processes. Slow UI/rendering must not block scientific execution or task closure.

## Scientific integrity

- Follow [experiment protocol](docs/experiment-protocol.md), the active experiment's frozen protocol, and its latest retained decision. Repository summaries are contextual; verify claims and gates against the relevant evidence. This contract does not override explicit user boundaries or authorize thawing an experiment.
- Keep historical evidence immutable. Store new experiments, corrections, and derived analyses in separately identified artifacts; bind them to their source rather than replacing history.
- Never change thresholds, labels/gold results, success envelopes, or historical artifacts to obtain PASS. Any authorized future change requires a separately declared experiment and preserves the original result.
- Retain failures, negative findings, failed checkpoints, and incomplete runs. Keep infrastructure/transport failures distinct from semantic or physical failures; retries follow the frozen policy, never an unfavorable result.
- Bind reportable evidence to experiment/treatment/case, seed, protocol/config hashes, source commit, policy/checkpoint identity, environment, raw traces, and source metrics as applicable. Keep secrets out of logs, evidence, and Git; follow existing large-artifact storage rules.
- Separate training, held-out evaluation, and previously seen mechanism/regression cases. Deterministic repeats establish reproducibility, not independent-seed generalization. Keep physical/task and nominal/strict outcomes distinct.
- Console and telemetry are observers, not evaluators or experiment controls. Label acquisition capture, state playback, and derived visualization replay accurately; visuals do not replace machine scoring. Observer changes require relevant execution-equivalence evidence before scientific use.
- Use the repo-local environment; preserve the external frozen `D:\work\mujoco-lab` baseline and existing pinned scientific configuration.

## Close every task

Report **Verdict / Evidence / Remaining blockers / Stopping reason**, briefly. Include relevant validation results, limitations, nonblocking findings, and Git status; distinguish completed work from proposals.

Once the authorized deliverable and required evidence are complete, stop. Do not add polish, sampling, broad regression, or the next research phase without a concrete unmet requirement.

Current retained state is generated/validated by `research_ops.py context` from
the source pointers in `ops/state.json`. Phase 3A.5 remains paused. Only an explicit
subsequent task may reopen a scientific boundary; Research Ops does not authorize it.
