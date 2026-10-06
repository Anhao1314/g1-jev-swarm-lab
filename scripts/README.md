# Scripts

Reproducible entry points for Phase 1. Run them from the repository root with
the project virtual environment active (see the README quick start).

| Script | Purpose |
| --- | --- |
| `fetch_g1_models.ps1` | Fetch the pinned official Unitree G1 MJCF/asset repositories into `third_party/` (never committed). |
| `run_compat_spike.py` | Load -> reset -> step >= 1000 steps -> read state for the official G1 models; writes `artifacts/compat-spike/`. |
| `run_baseline_001.py` | Stand -> WalkForward 2.0 m -> Stop over the configured seeds; writes `artifacts/baseline-001/` and the committed summary. |
| `run_skill_pilot.py` | Pilot runs for individual skills (turn); writes `artifacts/skill-pilot/`. |
| `run_characterization.py` | Phase 1.1 skill characterization campaigns (`--campaign pilot|final`); writes per-run evidence plus the committed summary and competence map. |
| `view_g1_skills.py` | Interactive MuJoCo viewer: reset -> stand -> walk 2 m -> stop -> turn +/-45 deg -> walk 5 m, real time, observation only. |
| `enter.ps1` | Activate `.venv` and keep pip cache and temp files inside the repository. |

All evidence-producing scripts are headless by default. A viewer is optional
and never required (`G1Simulation.open_viewer()`).
