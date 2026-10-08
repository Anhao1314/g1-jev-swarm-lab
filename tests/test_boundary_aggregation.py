"""Integration: final aggregation must equal the raw evidence."""

from __future__ import annotations

import yaml

from g1swarm.boundary.runner import BoundaryRunner

PROTOCOL = {
    "experiment_id": "g1_failure_boundary_001",
    "protocol_version": "test",
    "robot_config": "configs/robot/g1_locomotion_12dof.yaml",
    "provenance": {
        "model_source": "https://example.invalid/model",
        "model_commit": "abc",
        "controller_source": "https://example.invalid/controller",
        "controller_commit": "def",
        "policy_sha256": "cafe",
        "dof": 12,
        "actuators": 12,
    },
    "thresholds": {
        "walk": {
            "target_distance_m": 2.0,
            "tolerance_min_m": 0.2,
            "speed_mps": 0.5,
            "timeout_min_s": 15.0,
            "timeout_s_per_m": 6.0,
        },
        "envelopes": {"nominal": {}, "strict": {}},
        "push": {
            "direction": [0.0, 1.0, 0.0],
            "duration_s": 0.2,
            "trigger_s_range": [0.8, 1.2],
        },
        "joint": {"velocity_std_radps": 0.05},
        "zones": {"reliable_min_rate": 0.9, "failure_max_rate": 0.3},
        "risk": {"min_runs_for_label": 3, "min_runs_for_low": 5},
    },
    "sampling": {
        "exploration_seeds_deterministic": 1,
        "exploration_seeds_stochastic": 2,
        "final_runs_per_point": {
            "reliable": 2,
            "transition": 2,
            "failure": 2,
            "deterministic": 2,
        },
        "final_seeds": [0, 1],
    },
    "experiments": {
        "A_distance": {
            "parameter": "target_distance_m",
            "unit": "m",
            "direction": "increase",
            "deterministic": True,
            "safe_start": 2.0,
            "candidates": [3.0],
            "max_evaluations": 4,
            "refinement_rounds": 1,
            "resolution": 0.5,
            "task": {"target_distance_m": 2.0},
        }
    },
    "pilot_points": {"A_distance": 2.0},
}


def test_final_observation_matches_raw_runs(
    tmp_path, monkeypatch, locomotion_robot: dict
) -> None:
    monkeypatch.setenv("G1SWARM_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    protocol_path = tmp_path / "protocol.yaml"
    protocol_path.write_text(yaml.safe_dump(PROTOCOL), encoding="utf-8")
    runner = BoundaryRunner(protocol_path, campaign="final")
    payload = runner.run_experiment("A_distance")
    final = payload["final"][0]
    run_ids = set(final["run_ids"])
    raw = [record for record in runner.records if record["run_id"] in run_ids]
    assert final["n_runs"] == len(raw)
    assert final["task_successes"] == sum(
        1 for record in raw if record["metrics"]["task_success"]
    )
    assert final["physical_successes"] == sum(
        1 for record in raw if record["metrics"]["physical_success"]
    )
    assert final["n_runs"] == 2
    assert payload["search"]["trace"][0]["decision"] == "safe_start"
    summary = runner.summarize()
    assert summary["runs_total"] == len(runner.records)
    assert summary["task_successes"] == sum(
        1 for record in runner.records if record["metrics"]["task_success"]
    )
