# Scripts

Reproducible entry points for Phase 1/2. Run them from the repository root with
the project virtual environment active (see the README quick start).

| Script | Purpose |
| --- | --- |
| `fetch_g1_models.ps1` | Fetch the pinned official Unitree G1 MJCF/asset repositories into `third_party/` (never committed). |
| `run_compat_spike.py` | Load -> reset -> step >= 1000 steps -> read state for the official G1 models; writes `artifacts/compat-spike/`. |
| `run_baseline_001.py` | Stand -> WalkForward 2.0 m -> Stop over the configured seeds; writes `artifacts/baseline-001/` and the committed summary. |
| `run_skill_pilot.py` | Pilot runs for individual skills (turn); writes `artifacts/skill-pilot/`. |
| `run_characterization.py` | Phase 1.1 skill characterization campaigns (`--campaign pilot|final`); writes per-run evidence plus the committed summary and competence map. |
| `run_oracle_missions.py` | Phase 2.0 structured Mission IR benchmark (`--pilot --repeat 2` or frozen `--final`); writes raw mission evidence under `artifacts/` and the committed summary/transition map under `experiments/phase2/oracle_mission_runtime_001/`. |
| `build_language_corpus.py` | Rebuild/check the deterministic Phase 2.1 controlled-language corpus from its hand-authored source and bounded generator; `--check` verifies the frozen YAML. |
| `build_llm_datasets.py` | Rebuild/check the frozen Phase 2.2 development and blind datasets from the hand-authored sources; `--check` verifies byte-identical output and runs the prompt-leak guard. |
| `run_llm_compiler.py` | Phase 2.2 LLM mission compiler benchmark (`--development`, frozen `--blind`, `--repeatability`, `--e2e`); reads `LLM_COMPILER_BASE_URL` plus an API key env variable, records every raw model response under `artifacts/`, and writes the rule-vs-LLM comparison under `experiments/phase2/llm_compiler_001/`. |
| `run_language_benchmark.py` | Phase 2.1 controlled-language compiler benchmark (`--pilot` or frozen `--final`); writes compiler results/summary and Oracle execution equivalence under `experiments/phase2/controlled_language_001/`. |
| `view_g1_skills.py` | Interactive MuJoCo viewer: reset -> stand -> walk 2 m -> stop -> turn +/-45 deg -> walk 5 m, real time, observation only. |
| `view_mission.py` | Interactive MuJoCo viewer for Phase 2.0 missions: validate -> capability-ground -> task graph -> deterministic executor, real time, with a live HUD. Observation only (`--list`, `--plan-only`, `--no-viewer` available). |
| `enter.ps1` | Activate `.venv` and keep pip cache and temp files inside the repository. |

All evidence-producing scripts are headless by default. A viewer is optional
and never required (`G1Simulation.open_viewer()`).
