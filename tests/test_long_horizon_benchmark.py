"""Phase 2.3 benchmark scoring/aggregation tests and a runtime smoke test."""

from __future__ import annotations

from typing import Any

from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.longhorizon import benchmark as bench
from g1swarm.longhorizon import corpus as lh
from g1swarm.longhorizon import runner
from g1swarm.mission.ir import Mission, SkillName
from g1swarm.mission.runtime import MissionResult

RUNTIME_PROTOCOL = "configs/experiments/oracle_mission_runtime_001.yaml"


def _doc(mission_id: str = "m1", steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "mission_id": mission_id,
        "steps": steps
        or [
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 4.0},
                "depends_on": [],
            }
        ],
    }


def _result(document: dict[str, Any] | None, *, status: str = "SUCCESS", **diagnostics: Any) -> CompilerResult:
    mission = Mission.from_dict(document) if document is not None and status == "SUCCESS" else None
    return CompilerResult(
        status=CompilerStatus(status),
        mission=mission,
        normalized_text="text",
        diagnostics=dict(diagnostics),
    )


def _mission_result(
    *,
    mission_id: str = "m1",
    horizon: int = 1,
    success: bool = True,
    failure_type: str | None = None,
    state: str | None = None,
    grounding_status: str = "GROUNDED",
    transitions: tuple[dict[str, Any], ...] = (),
) -> MissionResult:
    return MissionResult(
        mission_id=mission_id,
        mission_schema_version="2.0.0",
        horizon=horizon,
        state=state or ("SUCCESS" if success else "FAILED"),
        mission_success=success,
        failure_type=failure_type,
        failure_reason=None,
        completed_nodes=1 if success else 0,
        failed_node=None,
        total_simulation_time_s=1.0,
        total_wall_time_s=2.0,
        skill_invocations=1,
        physical_success=success,
        path_length_m=1.0,
        transition_count=len(transitions),
        controller_memory_resets=0,
        simulation_steps_executed=10,
        nodes=(),
        transitions=transitions,
        grounding={"status": grounding_status, "results": []},
        validation={"valid": True},
        map_hashes={},
    )


def _sample(mission_id: str = "m1", condition: str = "L1") -> dict[str, Any]:
    return {
        "sample_id": f"{mission_id}__{condition}",
        "mission_id": mission_id,
        "horizon": "H1",
        "condition": condition,
        "text": "向前走4米。",
    }


def test_supported_skills_match_frozen_skill_enum() -> None:
    assert bench.SUPPORTED_SKILLS == {skill.value for skill in SkillName}


def test_compiler_record_flags_exact_and_parameter_errors() -> None:
    oracle = _doc()
    exact = bench.compiler_record(
        experiment_id="x",
        sample=_sample(),
        mission=oracle,
        result=_result(oracle),
        provenance={},
    )
    assert exact["exact_ir_match"] is True
    assert exact["step_order_match"] is True
    assert exact["parameters_match"] is True
    assert exact["false_rejection"] is False

    wrong_parameter = _doc(
        steps=[
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 6.0},
                "depends_on": [],
            }
        ]
    )
    record = bench.compiler_record(
        experiment_id="x",
        sample=_sample(),
        mission=oracle,
        result=_result(wrong_parameter),
        provenance={},
    )
    assert record["exact_ir_match"] is False
    assert record["step_order_match"] is True
    assert record["parameters_match"] is False

    wrong_order = _doc(
        steps=[
            {"id": "s1", "skill": "turn", "parameters": {"angle_deg": 45.0}, "depends_on": []},
            {"id": "s2", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": ["s1"]},
        ]
    )
    ordered_oracle = _doc(
        steps=[
            {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": []},
            {"id": "s2", "skill": "turn", "parameters": {"angle_deg": 45.0}, "depends_on": ["s1"]},
        ]
    )
    record = bench.compiler_record(
        experiment_id="x",
        sample=_sample(),
        mission=ordered_oracle,
        result=_result(wrong_order),
        provenance={},
    )
    assert record["step_order_match"] is False
    assert record["parameters_match"] is False


def test_compiler_record_false_rejection() -> None:
    record = bench.compiler_record(
        experiment_id="x",
        sample=_sample(),
        mission=_doc(),
        result=_result(None, status="MALFORMED", route="GUARD_REJECT"),
        provenance={},
    )
    assert record["false_rejection"] is True
    assert record["exact_ir_match"] is False
    assert record["route"] == "GUARD_REJECT"


def test_control_record_detects_unsafe_acceptance() -> None:
    control = {
        "control_id": "c1",
        "kind": "long_malformed",
        "text": "向前走4米，然后然后停止。",
        "expected_compiler_status": "MALFORMED",
        "expected_runtime": "NOT_RUN",
    }
    accepted = bench.control_record(
        experiment_id="x", control=control, result=_result(_doc()), provenance={}
    )
    assert accepted["status_match"] is False
    assert accepted["unsafe_acceptance"] is True
    rejected = bench.control_record(
        experiment_id="x",
        control=control,
        result=_result(None, status="MALFORMED"),
        provenance={},
    )
    assert rejected["status_match"] is True
    assert rejected["unsafe_acceptance"] is False


def test_summarize_compiler_rates() -> None:
    rows = [
        {"actual_status": "SUCCESS", "exact_ir_match": True, "step_order_match": True, "parameters_match": True,
         "hallucinated_skills": [], "unsafe_acceptance": False, "latency_s": 1.0, "provider_tokens": 100,
         "horizon": "H1", "condition": "L1", "false_rejection": False},
        {"actual_status": "SUCCESS", "exact_ir_match": False, "step_order_match": True, "parameters_match": False,
         "hallucinated_skills": [], "unsafe_acceptance": False, "latency_s": 3.0, "provider_tokens": 300,
         "horizon": "H1", "condition": "L2", "false_rejection": False},
    ]
    summary = bench.summarize_compiler(rows)
    assert summary["overall"]["samples"] == 2
    assert summary["overall"]["exact_ir_count"] == 1
    assert summary["overall"]["exact_ir_rate"] == 0.5
    assert summary["overall"]["wrong_parameter_count"] == 1
    assert summary["by_horizon"]["H1"]["samples"] == 2


def test_horizon_summary_end_to_end_math() -> None:
    compiler_rows = [
        {"horizon": "H1", "condition": "L1", "exact_ir_match": True, "false_rejection": False,
         "step_order_match": True, "parameters_match": True, "hallucinated_skills": []},
        {"horizon": "H1", "condition": "L1", "exact_ir_match": False, "false_rejection": False,
         "step_order_match": False, "parameters_match": False, "hallucinated_skills": []},
    ]
    runtime_rows = [
        {"horizon": "H1", "condition": "L1", "mission_success": True, "oracle": {"mission_success": True},
         "attribution": None, "runtime_equivalent": True, "transition_count": 0, "controller_memory_resets": 0},
    ]
    summary = bench.build_horizon_summary(compiler_rows, runtime_rows)
    row = summary["rows"]["H1/L1"]
    assert row["language_samples"] == 2
    assert row["exact_ir_rate"] == 0.5
    assert row["runtime_success_given_exact_ir"] == 1.0
    assert row["end_to_end_success_rate"] == 0.5
    assert row["oracle_runtime_success_rate"] == 1.0


def test_attribute_runtime_failure() -> None:
    unknown = _mission_result(success=False, failure_type="CAPABILITY_UNKNOWN", state="REJECTED", grounding_status="CAPABILITY_UNKNOWN")
    assert (
        bench.attribute_runtime_failure(
            language_result=unknown, oracle_result=None, equivalence=None, grounded=False
        )
        == "GROUNDING_UNKNOWN"
    )
    failed = _mission_result(success=False, failure_type="TRANSITION_FAILURE")
    assert (
        bench.attribute_runtime_failure(
            language_result=failed,
            oracle_result=_mission_result(),
            equivalence={"runtime_equivalent": False},
            grounded=True,
        )
        == "RUNTIME_CONTRADICTION"
    )
    assert (
        bench.attribute_runtime_failure(
            language_result=_mission_result(), oracle_result=None, equivalence=None, grounded=True
        )
        is None
    )


def test_transition_analysis_pair_threshold() -> None:
    transition = {
        "previous_skill": "walk_forward",
        "next_skill": "turn",
        "previous_node_id": "s1",
        "next_node_id": "s2",
        "position_delta_m": [0.01, 0.0, 0.0],
        "heading_delta_deg": 0.5,
        "controller_memory_reset": 1,
    }
    records = [
        {"transitions": [transition], "transition_count": 1, "failed_node": "s2" if i == 0 else None}
        for i in range(6)
    ]
    analysis = bench.transition_analysis(records)
    pair = analysis["pairs"]["walk_forward->turn"]
    assert pair["count"] == 6
    assert pair["failed_next_count"] == 1
    assert pair["rate_reportable"] is True
    small = bench.transition_analysis(records[:2])
    assert small["pairs"]["walk_forward->turn"]["rate_reportable"] is False


def test_latency_token_summary() -> None:
    rows = [
        {"horizon": "H1", "latency_s": 1.0, "provider_tokens": 100, "exact_ir_match": True},
        {"horizon": "H1", "latency_s": 3.0, "provider_tokens": 300, "exact_ir_match": False},
    ]
    summary = bench.latency_token_summary(rows)
    assert summary["H1"]["latency_median_s"] == 2.0
    assert summary["H1"]["provider_tokens_total"] == 400
    assert summary["H1"]["provider_tokens_per_successful_mission"] == 100


def test_scripted_compiler_stage() -> None:
    corpus = lh.build_corpus(per_horizon=1, seed=2300)
    compiler = runner.ScriptedOracleCompiler(runner.scripted_answers_from_corpus(corpus))
    stage = runner.run_compiler_stage(
        corpus, compiler, provenance={"compiler_architecture": "scripted_oracle"}
    )
    assert stage["record_count"] == len(corpus["language_samples"])
    assert all(record["exact_ir_match"] for record in stage["records"])
    controls = stage["safety_controls"]
    assert all(not control["unsafe_acceptance"] for control in controls)


def test_runtime_stage_smoke_on_single_h1_walk() -> None:
    mission = {
        "mission_id": "lh-h1-smoke-w4",
        "horizon": "H1",
        "steps": [
            {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": []}
        ],
    }
    sample = {
        "sample_id": "lh-h1-smoke-w4__L1",
        "mission_id": "lh-h1-smoke-w4",
        "horizon": "H1",
        "condition": "L1",
        "text": "向前走4米。",
    }
    corpus = {"canonical_missions": [mission], "language_samples": [sample], "safety_controls": []}
    compiler = runner.ScriptedOracleCompiler(
        {sample["text"]: ("SUCCESS", bench.mission_document(mission))}
    )
    compiler_stage = runner.run_compiler_stage(
        corpus, compiler, provenance={"compiler_architecture": "scripted_oracle"}
    )
    assert compiler_stage["records"][0]["exact_ir_match"] is True
    oracle_stage = runner.run_oracle_stage(corpus, runtime_protocol_path=RUNTIME_PROTOCOL)
    assert oracle_stage["results"][mission["mission_id"]]["mission_success"] is True
    assert "transitions" in oracle_stage["results"][mission["mission_id"]]
    runtime_stage = runner.run_language_stage(
        compiler_stage,
        oracle_stage,
        runtime_protocol_path=RUNTIME_PROTOCOL,
        provenance={"compiler_architecture": "scripted_oracle"},
    )
    assert runtime_stage["record_count"] == 1
    record = runtime_stage["records"][0]
    assert record["grounding_status"] == "GROUNDED"
    assert record["mission_success"] is True
    assert record["runtime_equivalent"] is True
    assert record["attribution"] is None
