# Evidence-Native Adaptive Embodied Runtime

This repository is a **Unitree G1 MuJoCo research testbed**. Its current single-agent path executes structured missions, evaluates measured skill outcomes, changes Task Graph flow on a strict failure, and records the decision alongside robot motion. Evidence, including unsuccessful experiments, determines which capabilities the runtime may use. The system is **not production-ready** or certified for robot safety.

## What runs today

```text
Reviewed Oracle Mission IR → validation and evidence-grounded Task Graph
    → deterministic G1 skill dispatch → MuJoCo state and skill result
    → strict outcome evaluation → CONTINUE or STOP_DEPENDENTS
    → optional, separately authorized post-failure StopSkill
    → event ledger, source-bound replay, Research Console
```

| Capability | Verified scope | Boundary |
| --- | --- | --- |
| G1 skills and walking correction | Official pretrained locomotion policy with deterministic Stand, Walk, Turn and Stop skills; Phase 1.3 heading/lateral correction passed its frozen nominal and two disturbance points. | Simulation and tested envelopes only; no new policy training or general reliability claim. |
| Structured mission execution | Phase 2.0 validated 20/20 frozen Oracle Mission IR missions and rejected 15 negative missions before simulation. | Oracle IR is reviewed structured input, not unrestricted language. |
| M2.0 feedback loop | A real strict failure in a 6 m experimental open-loop Walk changed execution from static dispatch of three skills to one failed Walk and two blocked dependents; the normal three-skill mission was retained. | The failed case uses an explicit **HIGH-risk, TEST_ONLY override**. `STOP_DEPENDENTS` blocks the graph, not robot motion. |
| M2.1 physical handling | An **opt-in, separate physical-halt path** ran StopSkill after the M2.0 block in one frozen MuJoCo failure state. It is explicitly enabled by the experimental Runtime configuration (`walk_strict_gate` and `physical_halt_contract`), not by redispatching a blocked task node. Speed fell from 0.451 to 0.056 m/s in 1.342 s with 0.185 m additional displacement; the original strict failure stayed failed. The normal mission remained 3/3 and requested no extra halt. | One previously seen failure state and one safe control at seed 0. Configuration opt-in is **not authenticated Human Principal Authority or production authorization**. The last-1 s mean speed only narrowly met its 0.10 m/s limit. This is **not** a hardware emergency stop or production safety capability. |

The M2.0 [execution report](experiments/m2/closed_loop_mission_001/report.md) and M2.1 [physical-halt report](experiments/m2/post_failure_halt_integration_001/report.md) link to their frozen protocols, raw traces, receipts and audits. Historical results and negative outcomes remain in their original experiment directories.

## Current gates

- **Jev:** The Phase 3B.1 node-entry offline risk role was `JEV_RISK_ROLE_NOT_SUPPORTED` (7 false-safe decisions among 11 strict violations). Phase 3B.1b early-risk instrumentation was `INCONCLUSIVE`. Jev has **no online selection, intervention or actuation authority**.
- **Language Runtime / D011:** `BLOCKED`. Language/compiler experiments and Source Authority development results do not authorize natural-language dispatch into this runtime. The separate Source Authority research branch is not part of this baseline.
- **Recovery and swarm:** The frozen residual recovery vocabulary was `RECOVERY_VOCABULARY_NOT_READY`. There is no verified Jev-selected recovery, Multi-Swarm runtime or new PPO training in the M2 path.
- **Safety:** Task refusal, a physical halt request, successful termination and failed termination are distinct states. A successful simulation stop does not establish physical robot safety across situations.

See the [research decisions](docs/research-decisions.md), [negative results](docs/lab-notebook/negative-results.md) and [integrity incidents](docs/lab-notebook/integrity-incidents.md) for the broader record. The [lab notebook](docs/lab-notebook/README.md) and [visual research summary](docs/lab-notebook/visual-summary.md) retain `main`'s historical research context; the experiment artifacts are authoritative for measured claims.

## Inspect the retained MuJoCo demonstration

The Research Console replays committed source-bound G1 states and decisions. It does **not** step the simulator or rerun an experiment. From the repository root on Windows:

```powershell
py -3.11 console/server.py --data experiments/research_console/m2_post_failure_halt_001 --port 8765
```

Open `http://127.0.0.1:8765/`. Compare the failed mission's task block, independent halt request, measured deceleration and final `HALT_SUCCEEDED` with the normal mission that continues through Walk, Turn and task Stop. The [Console guide](console/README.md) describes evidence inspection and older mechanism replays. Serving requires the committed evidence inventory to verify; it does not call Jev or a provider.

For read-only checks of the integration, use the project's Python 3.11 environment:

```powershell
python scripts/research_ops.py context
python -m pytest tests/test_m2_physical_halt_runtime.py tests/test_mission_runtime.py console/tests -q -k "not live_session_runs_a_stop_mission and not live_session_runs_a_grounded_walk"
python -m pytest tests/test_research_ops.py -q
node --test console/web/data.test.js
```

Research Ops `context` verifies pinned evidence and reports the reviewed-selection status. A `STALE` selection is a gate requiring explicit review, not a reason to silently choose the newest result. The selected tests exclude two live-session tests that step MuJoCo; run those only as a separate, explicit physics check. The commands above do not run physics, training or model evaluation. Some full historical integrity tests also require the ignored official G1 assets in `third_party/`; a fresh checkout without those assets cannot pass them. The [Research Ops guide](.agents/skills/g1-research-ops/SKILL.md) describes its claim and closeout workflow.

## Reproduce the development environment

The original G1 physics studies use native Windows, Python 3.11, pinned Unitree assets and the repository-local virtual environment. Check the frozen protocol and asset hashes before any new experiment; the demonstration above is a replay of retained evidence.

```powershell
py -3.11 -m venv .venv
.\scripts\enter.ps1
pip install -e ".[dev]"
pip install torch --index-url https://download.pytorch.org/whl/cu130
.\scripts\fetch_g1_models.ps1
```

The official pretrained `motion.pt` and G1 model assets are fetched into ignored `third_party/`; they are not committed. Use [Phase 1 compatibility notes](experiments/baselines/g1_compat_spike/README.md) and the frozen experiment protocols before attempting a physics reproduction. The repository's historical readme-style research notebook is retained, but its earlier future-architecture sketches are not a status claim for R1.

## Repository map

| Path | Role |
| --- | --- |
| `src/g1swarm/mission/` | Mission IR, grounding, Task Graph, deterministic feedback executor and live session |
| `src/g1swarm/skills/`, `control/`, `simulation/` | G1 skills, official-policy controller port and MuJoCo adapter |
| `experiments/` | Frozen protocols, raw evidence, receipts, audits, reports and Console replay artifacts |
| `console/` | Read-only integrity-checked evidence server and synchronized robot/trajectory UI |
| `scripts/research_ops.py`, `ops/` | Research context, workflow telemetry and reviewed selection |
| `docs/lab-notebook/` | Historical research narrative, negative results and integrity record |

The evidence rule is **protocol → source and asset hashes → execution → raw state/events → measured outcome → audit → claim**. Keep failed runs and provider/infrastructure failures distinct. Do not overwrite frozen evidence to improve a verdict.

Apache-2.0; see [LICENSE](LICENSE).
