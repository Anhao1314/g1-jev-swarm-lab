"""Phase 2.3 pilot harness tests (selection, wall time, control runtime)."""

from __future__ import annotations

import json

from g1swarm.longhorizon import corpus as lh
from g1swarm.longhorizon import runner

RUNTIME_PROTOCOL = "configs/experiments/oracle_mission_runtime_001.yaml"


def test_pilot_selection_is_deterministic_and_covers_profiles() -> None:
    corpus = lh.build_corpus(per_horizon=20, seed=2300)
    first = lh.select_pilot_missions(corpus["canonical_missions"])
    second = lh.select_pilot_missions(corpus["canonical_missions"])
    assert first == second
    assert len(first) == 18
    for horizon in lh.HORIZONS:
        entries = [entry for entry in first if entry["horizon"] == horizon]
        assert [entry["profile"] for entry in entries] == list(lh.PILOT_PROFILES)
        assert len({entry["mission_id"] for entry in entries}) == 3
    assert all(entry["fallback_reason"] for entry in first if entry["horizon"] == "H1")


def test_write_pilot_files_round_trip(tmp_path) -> None:
    corpus = lh.build_corpus(per_horizon=20, seed=2300)
    selection = lh.select_pilot_missions(corpus["canonical_missions"])
    outputs = runner.write_pilot_files(
        corpus,
        selection,
        corpus_dir=tmp_path,
        selection_path=tmp_path / "pilot_selection.json",
    )
    assert set(outputs) == {
        "canonical_missions",
        "language_realizations",
        "safety_controls",
        "pilot_selection",
    }
    payload = json.loads((tmp_path / "pilot_selection.json").read_text(encoding="utf-8"))
    assert payload["excluded_from_final"] is True
    assert len(payload["missions"]) == 18
    import yaml

    missions = yaml.safe_load((tmp_path / "canonical_missions.yaml").read_text(encoding="utf-8"))
    samples = yaml.safe_load((tmp_path / "language_realizations.yaml").read_text(encoding="utf-8"))
    assert len(missions["missions"]) == 18
    assert len(samples["samples"]) == 54


def test_compiler_stage_records_wall_time() -> None:
    corpus = lh.build_corpus(per_horizon=1, seed=2300)
    compiler = runner.ScriptedOracleCompiler(runner.scripted_answers_from_corpus(corpus))
    stage = runner.run_compiler_stage(
        corpus, compiler, provenance={"compiler_architecture": "scripted_oracle"}
    )
    assert all(isinstance(record.get("wall_time_s"), float) for record in stage["records"])
    summary = runner.benchmark.latency_token_summary(stage["records"])
    assert summary["H1"]["wall_time_mean_s"] is not None


def test_control_record_carries_compiled_mission() -> None:
    corpus = lh.build_corpus(per_horizon=1, seed=2300)
    compiler = runner.ScriptedOracleCompiler(runner.scripted_answers_from_corpus(corpus))
    stage = runner.run_compiler_stage(
        corpus, compiler, provenance={"compiler_architecture": "scripted_oracle"}
    )
    unknown = [row for row in stage["safety_controls"] if row["kind"] == "capability_unknown_embedded"][0]
    assert unknown["compiled_mission"] is not None
    malformed = [row for row in stage["safety_controls"] if row["kind"] == "long_malformed"]
    assert all(row["compiled_mission"] is None for row in malformed)


def test_control_runtime_capability_unknown_atomicity() -> None:
    corpus = lh.build_corpus(per_horizon=1, seed=2300)
    control = [
        item for item in corpus["safety_controls"] if item["kind"] == "capability_unknown_embedded"
    ][0]
    stage = runner.run_control_runtime_stage(
        {
            "safety_controls": [
                {
                    "control_id": control["control_id"],
                    "kind": control["kind"],
                    "expected_grounding": control["expected_grounding"],
                    "compiled_mission": control["intended_mission"],
                }
            ]
        },
        runtime_protocol_path=RUNTIME_PROTOCOL,
    )
    assert stage["record_count"] == 1
    record = stage["records"][0]
    assert record["grounding_status"] == "CAPABILITY_UNKNOWN"
    assert record["grounding_match"] is True
    assert record["zero_step"] is True
    assert record["mission_success"] is False


def test_build_walltime_budget_projection() -> None:
    oracle_stage = {
        "results": {
            "m1": {"horizon": "H1", "total_wall_time_s": 2.0, "total_simulation_time_s": 8.0},
            "m2": {"horizon": "H1", "total_wall_time_s": 4.0, "total_simulation_time_s": 8.0},
            "m3": {"horizon": "H3", "total_wall_time_s": 6.0, "total_simulation_time_s": 20.0},
        }
    }
    budget = runner.build_walltime_budget(
        oracle_stage=oracle_stage, final_missions_per_horizon=17
    )
    assert budget["pilot_oracle"]["H1"]["pilot_runs"] == 2
    assert budget["pilot_oracle"]["H1"]["pilot_wall_mean_s"] == 3.0
    assert budget["projected_final"]["oracle_runs"] == 34
    assert budget["projected_final"]["language_runtime_runs_max"] == 102
    assert budget["projected_final"]["oracle_wall_total_s"] == 3.0 * 17 + 6.0 * 17
    assert budget["pilot_compiler"]["status"] == "not_measured_provider_unavailable"
