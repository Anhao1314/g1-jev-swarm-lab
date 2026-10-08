"""Oracle mission benchmark aggregation tests (synthetic runs, no MuJoCo)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
import yaml

from g1swarm.mission import MISSION_SCHEMA_VERSION, MissionResult
from g1swarm.mission.benchmark import (
    CorpusError,
    MissionRun,
    build_benchmark_summary,
    build_transition_map,
    load_corpus,
    mission_document,
    validate_benchmark_summary,
)
from g1swarm.paths import resolve_repo_path

CORPUS_PATH = "configs/missions/oracle_phase2_001.yaml"
CAMPAIGN = "pytest"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _corpus() -> dict[str, Any]:
    return {
        "schema_version": MISSION_SCHEMA_VERSION,
        "corpus_id": "synthetic_corpus",
        "missions": [
            {
                "mission_id": "m1",
                "horizon": "H1",
                "steps": [{"id": "s1", "skill": "stop", "parameters": {}}],
                "expected": {"validation": "VALID"},
            }
        ],
        "negatives": [
            {
                "mission_id": "n1",
                "expected": {"failure_type": "VALIDATION_FAILURE"},
                "steps": [{"id": "s1", "skill": "grab_object", "parameters": {}}],
            }
        ],
    }


def _write_corpus(tmp_path, data: dict[str, Any], name: str = "corpus.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _entry(mission_id: str, horizon: str = "H1") -> dict[str, Any]:
    return {
        "mission_id": mission_id,
        "horizon": horizon,
        "steps": [{"id": "s1", "skill": "stop", "parameters": {}}],
        "expected": {},
    }


def _result(
    mission_id: str,
    *,
    horizon: int = 1,
    state: str = "SUCCESS",
    mission_success: bool = True,
    failure_type: str | None = None,
    failure_reason: str | None = None,
    completed_nodes: int = 1,
    failed_node: str | None = None,
    simulation_time_s: float = 1.0,
    wall_time_s: float = 0.1,
    skill_invocations: int = 1,
    physical_success: bool = True,
    path_length_m: float = 1.0,
    transition_count: int = 0,
    controller_memory_resets: int = 1,
    simulation_steps: int = 10,
    nodes: tuple[dict[str, Any], ...] = (),
    transitions: tuple[dict[str, Any], ...] = (),
    grounding: dict[str, Any] | None = None,
) -> MissionResult:
    return MissionResult(
        mission_id=mission_id,
        mission_schema_version=MISSION_SCHEMA_VERSION,
        horizon=horizon,
        state=state,
        mission_success=mission_success,
        failure_type=failure_type,
        failure_reason=failure_reason,
        completed_nodes=completed_nodes,
        failed_node=failed_node,
        total_simulation_time_s=simulation_time_s,
        total_wall_time_s=wall_time_s,
        skill_invocations=skill_invocations,
        physical_success=physical_success,
        path_length_m=path_length_m,
        transition_count=transition_count,
        controller_memory_resets=controller_memory_resets,
        simulation_steps_executed=simulation_steps,
        nodes=nodes,
        transitions=transitions,
        grounding={} if grounding is None else grounding,
    )


def _node(node_id: str, *, task_success: bool) -> dict[str, Any]:
    return {"node_id": node_id, "metrics": {"task_success": task_success}}


def _link(
    next_node_id: str,
    *,
    previous_skill: str = "walk_forward",
    next_skill: str = "stop",
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    heading: float = 0.0,
) -> dict[str, Any]:
    return {
        "previous_skill": previous_skill,
        "next_skill": next_skill,
        "previous_node_id": "s1",
        "next_node_id": next_node_id,
        "position_delta_m": list(position),
        "heading_delta_deg": heading,
    }


def _valid_run(
    mission_id: str,
    horizon: str,
    *,
    success: bool = True,
    failure_type: str | None = None,
    completed_nodes: int = 3,
    simulation_time_s: float = 1.5,
    wall_time_s: float = 0.5,
    skill_invocations: int = 3,
    transition_count: int = 2,
    simulation_steps: int = 30,
    grounding: dict[str, Any] | None = None,
) -> MissionRun:
    return MissionRun(
        entry=_entry(mission_id, horizon),
        negative=False,
        result=_result(
            mission_id,
            horizon=int(horizon.lstrip("H")),
            state="SUCCESS" if success else "FAILED",
            mission_success=success,
            failure_type=None if success else (failure_type or "SKILL_FAILURE"),
            failure_reason=None if success else "synthetic failure",
            completed_nodes=completed_nodes,
            failed_node=None if success else "s3",
            simulation_time_s=simulation_time_s,
            wall_time_s=wall_time_s,
            skill_invocations=skill_invocations,
            transition_count=transition_count,
            simulation_steps=simulation_steps,
            grounding=grounding,
        ),
    )


def _negative_run(
    mission_id: str,
    *,
    expected_failure_type: str | None,
    failure_type: str | None,
    simulation_steps: int = 0,
) -> MissionRun:
    expected = {} if expected_failure_type is None else {"failure_type": expected_failure_type}
    return MissionRun(
        entry={
            "mission_id": mission_id,
            "steps": [{"id": "s1", "skill": "grab_object", "parameters": {}}],
            "expected": expected,
        },
        negative=True,
        result=_result(
            mission_id,
            horizon=0,
            state="REJECTED",
            mission_success=False,
            failure_type=failure_type,
            failure_reason="synthetic rejection",
            completed_nodes=0,
            simulation_time_s=0.0,
            wall_time_s=0.05,
            skill_invocations=0,
            path_length_m=0.0,
            transition_count=0,
            controller_memory_resets=0,
            simulation_steps=simulation_steps,
        ),
    )


def _protocol() -> dict[str, Any]:
    return {
        "experiment_id": "oracle_mission_runtime_001",
        "_protocol_sha256": "protocol-hash",
        "horizons": {"H1": 1, "H3": 3, "H5": 5, "H8": 8},
    }


def _summary(runs: list[MissionRun]) -> dict[str, Any]:
    return build_benchmark_summary(
        protocol=_protocol(),
        corpus={"corpus_id": "synthetic_summary_corpus"},
        corpus_path=resolve_repo_path(CORPUS_PATH),
        runs=runs,
        source_commit="deadbeef",
        campaign=CAMPAIGN,
    )


# ---------------------------------------------------------------------------
# load_corpus / validate_corpus
# ---------------------------------------------------------------------------
def test_load_corpus_accepts_the_frozen_phase2_corpus() -> None:
    corpus = load_corpus(resolve_repo_path(CORPUS_PATH))
    assert corpus["schema_version"] == MISSION_SCHEMA_VERSION
    assert corpus["corpus_id"] == "oracle_phase2_001"
    assert len(corpus["missions"]) == 20
    assert len(corpus["negatives"]) == 15
    assert {entry["horizon"] for entry in corpus["missions"]} == {"H1", "H3", "H5", "H8"}
    ids = [entry["mission_id"] for entry in corpus["missions"] + corpus["negatives"]]
    assert len(ids) == len(set(ids))
    assert all(entry["steps"] for entry in corpus["missions"])


def test_load_corpus_accepts_json_documents(tmp_path) -> None:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_corpus()), encoding="utf-8")
    assert load_corpus(path)["corpus_id"] == "synthetic_corpus"


def test_load_corpus_requires_every_top_level_field(tmp_path) -> None:
    data = _corpus()
    del data["negatives"]
    with pytest.raises(CorpusError, match="missing fields: negatives"):
        load_corpus(_write_corpus(tmp_path, data))


def test_load_corpus_rejects_non_list_sections(tmp_path) -> None:
    data = _corpus()
    data["missions"] = {"mission_id": "m1"}
    with pytest.raises(CorpusError, match="missions must be a list"):
        load_corpus(_write_corpus(tmp_path, data))


def test_load_corpus_rejects_documents_that_are_not_mappings(tmp_path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("null\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="corpus must be a mapping"):
        load_corpus(path)


@pytest.mark.parametrize(
    "broken", ["missing-id", "empty-id", "steps", "expected", "not-a-mapping"]
)
def test_load_corpus_rejects_malformed_entries(tmp_path, broken: str) -> None:
    data = _corpus()
    entry = data["negatives"][0]
    if broken == "missing-id":
        entry.pop("mission_id")
        match = "without a mission_id"
    elif broken == "empty-id":
        entry["mission_id"] = ""
        match = "without a mission_id"
    elif broken == "steps":
        entry["steps"] = "not-a-list"
        match = "steps must be a list"
    elif broken == "not-a-mapping":
        data["negatives"][0] = "oops"
        match = "negatives entry must be a mapping"
    else:
        entry.pop("expected")
        match = "expected outcome missing"
    with pytest.raises(CorpusError, match=match):
        load_corpus(_write_corpus(tmp_path, data))


def test_load_corpus_rejects_duplicate_ids_within_a_section(tmp_path) -> None:
    data = _corpus()
    data["missions"].append(dict(data["missions"][0]))
    with pytest.raises(CorpusError, match="duplicate mission_id"):
        load_corpus(_write_corpus(tmp_path, data))


def test_load_corpus_rejects_duplicate_ids_across_sections(tmp_path) -> None:
    data = _corpus()
    data["negatives"][0]["mission_id"] = data["missions"][0]["mission_id"]
    with pytest.raises(CorpusError, match="duplicate mission_id"):
        load_corpus(_write_corpus(tmp_path, data))


# ---------------------------------------------------------------------------
# mission_document
# ---------------------------------------------------------------------------
def test_mission_document_falls_back_to_the_corpus_schema_version() -> None:
    entry = {"mission_id": "m1", "steps": [{"id": "s1", "skill": "stop"}]}
    document = mission_document(entry, MISSION_SCHEMA_VERSION)
    assert document["schema_version"] == MISSION_SCHEMA_VERSION
    assert document["mission_id"] == "m1"
    assert document["steps"] == entry["steps"]


def test_mission_document_preserves_an_entry_schema_override() -> None:
    corpus = load_corpus(resolve_repo_path(CORPUS_PATH))
    overridden = next(
        entry for entry in corpus["negatives"] if entry["mission_id"] == "n-schema-version"
    )
    document = mission_document(overridden, corpus["schema_version"])
    assert document["schema_version"] == "1.0.0"
    assert document["mission_id"] == "n-schema-version"
    assert mission_document({"mission_id": "m", "steps": [], "schema_version": "9.9.9"}, "2.0.0")[
        "schema_version"
    ] == "9.9.9"


# ---------------------------------------------------------------------------
# build_transition_map
# ---------------------------------------------------------------------------
def test_build_transition_map_aggregates_success_and_failure_counts() -> None:
    def run(mission_id: str, *, next_task_success: bool) -> MissionRun:
        return MissionRun(
            entry=_entry(mission_id),
            negative=False,
            result=_result(
                mission_id,
                nodes=(_node("s1", task_success=True), _node("s2", task_success=next_task_success)),
                transitions=(_link("s2", position=(0.10, -0.02, 0.0), heading=0.5),),
                transition_count=1,
            ),
        )

    payload = build_transition_map(
        [
            run("m1", next_task_success=True),
            run("m2", next_task_success=False),
            run("m1", next_task_success=True),
        ]
    )
    assert payload["schema_version"] == "2.0.0"
    assert payload["generated_at"]
    entry = payload["transitions"]["walk_forward->stop"]
    assert entry["previous_skill"] == "walk_forward" and entry["next_skill"] == "stop"
    assert entry["executions"] == 3
    assert entry["next_node_successes"] == 2
    assert entry["next_node_failures"] == 1
    assert entry["representative_position_delta_m"] == [0.1, -0.02, 0.0]
    assert entry["representative_heading_delta_deg"] == 0.5
    assert entry["deterministic"] is True
    assert entry["evidence_refs"] == ["m1", "m2"]


def test_build_transition_map_flags_divergent_executions() -> None:
    def run(mission_id: str, position, heading: float) -> MissionRun:
        return MissionRun(
            entry=_entry(mission_id),
            negative=False,
            result=_result(
                mission_id,
                nodes=(_node("s1", task_success=True), _node("s2", task_success=True)),
                transitions=(_link("s2", position=position, heading=heading),),
                transition_count=1,
            ),
        )

    payload = build_transition_map(
        [run("m3", (1.0, 2.0, 3.0), 10.0), run("m3", (3.0, 4.0, 5.0), 20.0)]
    )
    entry = payload["transitions"]["walk_forward->stop"]
    assert entry["executions"] == 2
    assert entry["next_node_successes"] == 2 and entry["next_node_failures"] == 0
    assert entry["deterministic"] is False
    assert entry["representative_position_delta_m"] == [2.0, 3.0, 4.0]
    assert entry["representative_heading_delta_deg"] == 15.0


def test_build_transition_map_does_not_claim_determinism_across_templates() -> None:
    def run(mission_id: str, position, heading: float) -> MissionRun:
        return MissionRun(
            entry=_entry(mission_id),
            negative=False,
            result=_result(
                mission_id,
                nodes=(_node("s1", task_success=True), _node("s2", task_success=True)),
                transitions=(_link("s2", position=position, heading=heading),),
                transition_count=1,
            ),
        )

    payload = build_transition_map(
        [run("m3", (1.0, 2.0, 3.0), 10.0), run("m4", (3.0, 4.0, 5.0), 20.0)]
    )
    entry = payload["transitions"]["walk_forward->stop"]
    assert entry["deterministic"] is None
    assert "different mission template" in entry["determinism_note"]


def test_build_transition_map_keys_use_the_skill_pair() -> None:
    run = MissionRun(
        entry=_entry("m5"),
        negative=False,
        result=_result(
            "m5",
            nodes=(
                _node("s1", task_success=True),
                _node("s2", task_success=True),
                _node("s3", task_success=True),
            ),
            transitions=(
                _link(
                    "s2",
                    previous_skill="walk_forward",
                    next_skill="turn",
                    position=(0.5, 0.0, 0.0),
                    heading=45.0,
                ),
                _link("s3", previous_skill="turn", next_skill="stop"),
            ),
            transition_count=2,
        ),
    )
    transitions = build_transition_map([run])["transitions"]
    assert set(transitions) == {"walk_forward->turn", "turn->stop"}
    assert transitions["walk_forward->turn"]["deterministic"] is None
    assert transitions["walk_forward->turn"]["determinism_note"]
    assert transitions["turn->stop"]["evidence_refs"] == ["m5"]


# ---------------------------------------------------------------------------
# build_benchmark_summary
# ---------------------------------------------------------------------------
def test_build_benchmark_summary_groups_valid_missions_by_horizon() -> None:
    runs = [
        _valid_run("v-h1-a", "H1", success=True),
        _valid_run("v-h1-b", "H1", success=False, failure_type="SKILL_FAILURE"),
        _valid_run("v-h3-a", "H3", success=False, failure_type="MISSION_TIMEOUT"),
        _valid_run(
            "v-h5-a",
            "H5",
            success=True,
            grounding={"results": [{"execution_mode": "heading_lateral"}]},
        ),
        _valid_run("v-h8-a", "H8", success=True),
    ]
    summary = _summary(runs)
    assert summary["experiment_id"] == "oracle_mission_runtime_001"
    assert summary["campaign"] == CAMPAIGN
    assert summary["corpus_id"] == "synthetic_summary_corpus"
    assert summary["protocol_sha256"] == "protocol-hash"
    assert summary["source_commit"] == "deadbeef"
    assert summary["generated_at"]
    assert summary["corpus_sha256"] == hashlib.sha256(
        resolve_repo_path(CORPUS_PATH).read_bytes()
    ).hexdigest()
    assert summary["valid"] == {"missions": 5, "successes": 3, "failures": 2, "success_rate": 0.6}
    assert summary["failure_taxonomy"] == {"SKILL_FAILURE": 1, "MISSION_TIMEOUT": 1}
    assert summary["mission_successes"] == 3
    assert summary["physical_successes"] == 5
    assert summary["horizons"]["H1"] == {
        "missions": 2,
        "successes": 1,
        "failures": 1,
        "success_rate": 0.5,
        "mean_completed_nodes": 3.0,
        "mean_simulation_time_s": 1.5,
    }
    assert summary["horizons"]["H3"]["successes"] == 0
    assert summary["horizons"]["H3"]["failures"] == 1
    assert summary["horizons"]["H5"]["success_rate"] == 1.0
    assert summary["horizons"]["H8"]["missions"] == 1
    assert summary["mission_success_by_horizon"] == {"H1": 0.5, "H3": 0.0, "H5": 1.0, "H8": 1.0}
    assert [payload["mission_id"] for payload in summary["missions"]] == [
        "v-h1-a",
        "v-h1-b",
        "v-h3-a",
        "v-h5-a",
        "v-h8-a",
    ]
    assert summary["missions"][3]["grounded_modes"] == ["heading_lateral"]
    assert summary["totals"] == {
        "simulation_time_s": 7.5,
        "wall_time_s": 2.5,
        "skill_invocations": 15,
        "transitions": 10,
    }
    validate_benchmark_summary(summary)


def test_build_benchmark_summary_keeps_empty_protocol_horizons() -> None:
    summary = _summary([_valid_run("v-h1-a", "H1", success=True)])
    for horizon in ("H3", "H5", "H8"):
        stats = summary["horizons"][horizon]
        assert stats["missions"] == 0
        assert stats["success_rate"] is None
        assert stats["mean_completed_nodes"] is None
        assert stats["mean_simulation_time_s"] is None
    validate_benchmark_summary(summary)


def test_build_benchmark_summary_tracks_rejections_and_expected_types() -> None:
    runs = [
        _valid_run("v-h1-a", "H1", success=True),
        _negative_run(
            "n-zero-step",
            expected_failure_type="VALIDATION_FAILURE",
            failure_type="VALIDATION_FAILURE",
        ),
        _negative_run(
            "n-wrong-type",
            expected_failure_type="CAPABILITY_UNKNOWN",
            failure_type="CAPABILITY_REJECTED",
        ),
        _negative_run(
            "n-no-expectation", expected_failure_type=None, failure_type="VALIDATION_FAILURE"
        ),
        _negative_run(
            "n-ran-sim",
            expected_failure_type="VALIDATION_FAILURE",
            failure_type="VALIDATION_FAILURE",
            simulation_steps=12,
        ),
    ]
    summary = _summary(runs)
    assert summary["valid"] == {"missions": 1, "successes": 1, "failures": 0, "success_rate": 1.0}
    assert summary["rejections"]["missions"] == 4
    assert summary["rejections"]["zero_step_compliant"] is False
    assert summary["rejections"]["expected_failure_types_ok"] is False
    assert summary["failure_taxonomy"] == {}
    assert summary["horizons"]["H1"]["missions"] == 1
    rejected = [payload for payload in summary["missions"] if payload["negative"]]
    assert [payload["mission_id"] for payload in rejected] == [
        "n-zero-step",
        "n-wrong-type",
        "n-no-expectation",
        "n-ran-sim",
    ]
    assert all(payload["horizon"] is None for payload in rejected)
    assert summary["missions"][-1]["simulation_steps_executed"] == 12


def test_build_benchmark_summary_accepts_clean_rejections() -> None:
    summary = _summary(
        [
            _valid_run("v-h1-a", "H1", success=True),
            _negative_run(
                "n-zero-step",
                expected_failure_type="VALIDATION_FAILURE",
                failure_type="VALIDATION_FAILURE",
            ),
        ]
    )
    assert summary["rejections"] == {
        "missions": 1,
        "zero_step_compliant": True,
        "expected_failure_types_ok": True,
    }
    validate_benchmark_summary(summary)


# ---------------------------------------------------------------------------
# validate_benchmark_summary
# ---------------------------------------------------------------------------
def _valid_summary() -> dict[str, Any]:
    return _summary(
        [
            _valid_run("v-h1-a", "H1", success=True),
            _negative_run(
                "n-zero-step",
                expected_failure_type="VALIDATION_FAILURE",
                failure_type="VALIDATION_FAILURE",
            ),
        ]
    )


def test_validate_benchmark_summary_accepts_a_valid_summary() -> None:
    validate_benchmark_summary(_valid_summary())


def test_validate_benchmark_summary_requires_every_field() -> None:
    summary = _valid_summary()
    del summary["failure_taxonomy"]
    with pytest.raises(ValueError, match="missing fields: failure_taxonomy"):
        validate_benchmark_summary(summary)


def test_validate_benchmark_summary_rejects_non_zero_step_rejections() -> None:
    summary = _valid_summary()
    summary["rejections"]["zero_step_compliant"] = False
    with pytest.raises(ValueError, match="rejected mission executed simulation steps"):
        validate_benchmark_summary(summary)


def test_validate_benchmark_summary_rejects_summaries_that_ran_a_rejection() -> None:
    summary = _summary(
        [
            _valid_run("v-h1-a", "H1", success=True),
            _negative_run(
                "n-ran-sim",
                expected_failure_type="VALIDATION_FAILURE",
                failure_type="VALIDATION_FAILURE",
                simulation_steps=7,
            ),
        ]
    )
    with pytest.raises(ValueError, match="rejected mission executed simulation steps"):
        validate_benchmark_summary(summary)


def test_validate_benchmark_summary_rejects_inconsistent_horizon_counts() -> None:
    summary = _valid_summary()
    summary["horizons"]["H1"]["failures"] += 1
    with pytest.raises(ValueError, match="horizon H1: success/failure counts do not add up"):
        validate_benchmark_summary(summary)
