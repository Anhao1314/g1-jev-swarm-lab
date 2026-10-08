"""Integration check: nominal runs are deterministic and marked as such."""

from __future__ import annotations

from g1swarm.characterization.runner import CharacterizationRunner

PROTOCOL = "configs/experiments/g1_skill_characterization_001.yaml"
KEY_METRICS = ("forward_displacement_m", "lateral_drift_m", "completion_sim_time_s")


def test_nominal_walk_repetitions_are_identical(locomotion_robot: dict, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("G1SWARM_ARTIFACTS_DIR", str(tmp_path))
    runner = CharacterizationRunner(PROTOCOL, campaign="pilot")
    first = runner.run_nominal_walk(0.5, seed=0, repetition=0)
    second = runner.run_nominal_walk(0.5, seed=1, repetition=1)
    for key in KEY_METRICS:
        assert first["metrics"][key] == second["metrics"][key], key
    grouped = runner._group([first, second], KEY_METRICS)
    assert grouped["deterministic_repetition"] is True
    assert grouped["success_rate"] == 1.0
