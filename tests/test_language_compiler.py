"""Controlled Chinese compiler tests for the Phase 2.1 language baseline."""

from __future__ import annotations

import re

import pytest

from g1swarm.language import (
    CompilerStatus,
    LanguageCompiler,
    LanguageErrorCode,
)
from g1swarm.mission import (
    CAPABILITY_UNKNOWN,
    MISSION_SCHEMA_VERSION,
    CapabilityGrounder,
    Mission,
    MissionStep,
    MissionValidator,
    SkillName,
    is_path_safe_mission_id,
)

SUPPORTED_SKILLS = {"stand", "walk_forward", "turn", "stop"}
REFERENCE_SEQUENCE = "站立2秒，然后前进2米，再左转45度，最后停止"


def _compile_ok(utterance: str, compiler: LanguageCompiler | None = None) -> Mission:
    result = (compiler or LanguageCompiler()).compile(utterance)
    assert result.status is CompilerStatus.SUCCESS
    assert result.success is True
    assert result.mission is not None
    assert result.error_code is None
    assert result.error_message is None
    return result.mission


def _canonical(mission: Mission) -> dict:
    """Language-independent Mission IR projection used for exact comparison."""

    document = mission.to_dict()
    document.pop("mission_id")
    return document


# ---------------------------------------------------------------------------
# Atomic grammar and synonyms
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("utterance", ["站立", "站好", "保持站立"])
def test_stand_synonyms_use_the_frozen_default_duration(utterance: str) -> None:
    mission = _compile_ok(utterance)
    assert mission.horizon == 1
    assert mission.steps[0].skill is SkillName.STAND
    assert mission.steps[0].parameters == {"duration_s": 2.0}


@pytest.mark.parametrize(
    ("utterance", "duration_s"),
    [("站立5秒", 5.0), ("站好2s", 2.0), ("保持站立3S", 3.0)],
)
def test_stand_accepts_explicit_durations(utterance: str, duration_s: float) -> None:
    mission = _compile_ok(utterance)
    assert mission.steps[0].skill is SkillName.STAND
    assert mission.steps[0].parameters == {"duration_s": duration_s}


@pytest.mark.parametrize("utterance", ["停止", "停下", "立即停止"])
def test_stop_synonyms_compile_to_stop(utterance: str) -> None:
    mission = _compile_ok(utterance)
    assert mission.horizon == 1
    assert mission.steps[0].skill is SkillName.STOP
    assert mission.steps[0].parameters == {}


@pytest.mark.parametrize(
    "utterance",
    ["前进4米", "往前走4米", "向前走4米", "向前移动4m", "往前移动4米"],
)
def test_walk_synonyms_compile_to_the_same_distance(utterance: str) -> None:
    mission = _compile_ok(utterance)
    assert mission.steps[0].skill is SkillName.WALK_FORWARD
    assert mission.steps[0].parameters == {"distance_m": 4.0}


@pytest.mark.parametrize(
    ("utterance", "angle_deg"),
    [
        ("左转30度", 30.0),
        ("向左转30度", 30.0),
        ("逆时针转30度", 30.0),
        ("逆时针旋转30度", 30.0),
        ("右转30度", -30.0),
        ("向右转30度", -30.0),
        ("顺时针转30度", -30.0),
        ("顺时针旋转30度", -30.0),
        ("向右转45°", -45.0),
    ],
)
def test_turn_direction_sign_matches_turn_skill_convention(
    utterance: str, angle_deg: float
) -> None:
    # TurnSkill maps non-negative target angles to +yaw and negative angles to -yaw.
    mission = _compile_ok(utterance)
    assert mission.steps[0].skill is SkillName.TURN
    assert mission.steps[0].parameters == {"angle_deg": angle_deg}


# ---------------------------------------------------------------------------
# Sequencing, punctuation, paraphrase consistency
# ---------------------------------------------------------------------------
def test_sequence_preserves_order_parameters_and_dependency_chain() -> None:
    mission = _compile_ok(
        "先站立2秒，然后前进4米，再左转45度，接着右转30度，之后停止，最后站立1秒"
    )
    assert [step.skill for step in mission.steps] == [
        SkillName.STAND,
        SkillName.WALK_FORWARD,
        SkillName.TURN,
        SkillName.TURN,
        SkillName.STOP,
        SkillName.STAND,
    ]
    assert [dict(step.parameters) for step in mission.steps] == [
        {"duration_s": 2.0},
        {"distance_m": 4.0},
        {"angle_deg": 45.0},
        {"angle_deg": -30.0},
        {},
        {"duration_s": 1.0},
    ]
    assert [step.depends_on for step in mission.steps] == [
        (),
        ("s1",),
        ("s2",),
        ("s3",),
        ("s4",),
        ("s5",),
    ]


@pytest.mark.parametrize(
    "utterance",
    [
        "站立2秒。前进2米;左转45度→停止",
        "站立2秒,前进2米,左转45度,停止",
        "站立2秒；前进2米；左转45度；停止",
    ],
)
def test_connector_and_punctuation_variants_match_the_reference_ir(utterance: str) -> None:
    assert _canonical(_compile_ok(utterance)) == _canonical(_compile_ok(REFERENCE_SEQUENCE))


PARAPHRASE_UTTERANCES = [
    "前进4米，然后右转45度，最后停止",
    "向前走四米，再向右转45°，之后停止",
    "先往前走4m接着顺时针转四十五度最后立即停止",
]


def test_paraphrases_compile_to_the_same_canonical_ir() -> None:
    missions = [_compile_ok(utterance) for utterance in PARAPHRASE_UTTERANCES]
    canonical = [_canonical(mission) for mission in missions]
    assert canonical[0] == canonical[1] == canonical[2]
    assert all(is_path_safe_mission_id(mission.mission_id) for mission in missions)


def test_compiled_sequence_equals_hand_built_oracle_ir() -> None:
    mission = _compile_ok("先前进4米，然后右转45度，最后停止")
    oracle = Mission(
        mission_id="oracle-phase2-001",
        steps=(
            MissionStep(
                step_id="s1",
                skill=SkillName.WALK_FORWARD,
                parameters={"distance_m": 4.0},
            ),
            MissionStep(
                step_id="s2",
                skill=SkillName.TURN,
                parameters={"angle_deg": -45.0},
                depends_on=("s1",),
            ),
            MissionStep(
                step_id="s3",
                skill=SkillName.STOP,
                parameters={},
                depends_on=("s2",),
            ),
        ),
    )
    assert _canonical(mission) == _canonical(oracle)
    assert mission.schema_version == MISSION_SCHEMA_VERSION == "2.0.0"


def test_all_compiled_valid_missions_pass_the_frozen_validator() -> None:
    for utterance in (
        "站立",
        "前进4米",
        "左转45度",
        "停止",
        REFERENCE_SEQUENCE,
        *PARAPHRASE_UTTERANCES,
    ):
        report = MissionValidator().validate(_compile_ok(utterance))
        assert report.valid, (utterance, report.to_dict())


def test_compiler_emits_only_mission_ir_and_no_runtime_decisions() -> None:
    mission = _compile_ok(REFERENCE_SEQUENCE)
    assert set(mission.to_dict()) == {"schema_version", "mission_id", "steps"}
    allowed_step_keys = {
        "id",
        "skill",
        "parameters",
        "depends_on",
        "execution_mode_override",
    }
    assert {step.skill.value for step in mission.steps} <= SUPPORTED_SKILLS
    for step in mission.steps:
        assert set(step.to_dict()) <= allowed_step_keys
        assert step.execution_mode_override is None


def test_mission_id_is_path_safe_and_content_derived() -> None:
    first = _compile_ok("前进4米")
    spaced = _compile_ok("前进 4 米")
    other = _compile_ok("前进5米")
    assert is_path_safe_mission_id(first.mission_id)
    assert first.mission_id == spaced.mission_id
    assert first.mission_id != other.mission_id


# ---------------------------------------------------------------------------
# CompilerResult contract
# ---------------------------------------------------------------------------
def test_success_result_contract_and_diagnostics() -> None:
    result = LanguageCompiler().compile("前进2米")
    assert result.status is CompilerStatus.SUCCESS
    assert result.success is True
    assert result.mission is not None
    assert result.error_code is None
    assert result.error_message is None
    assert result.normalized_text == "前进2米"

    payload = result.to_dict()
    assert set(payload) == {
        "status",
        "mission",
        "normalized_text",
        "error_code",
        "error_message",
        "diagnostics",
    }
    assert payload["status"] == "SUCCESS"
    assert payload["mission"] == result.mission.to_dict()
    assert Mission.from_dict(payload["mission"]) == result.mission
    diagnostics = payload["diagnostics"]
    for key in (
        "compiler_version",
        "grammar_sha256",
        "max_input_chars",
        "normalized_length",
        "step_count",
    ):
        assert key in diagnostics
    assert re.fullmatch(r"[0-9a-f]{64}", diagnostics["grammar_sha256"])


@pytest.mark.parametrize(
    ("utterance", "status", "code"),
    [
        ("", CompilerStatus.MALFORMED, LanguageErrorCode.EMPTY_LANGUAGE_INPUT),
        ("往前走一点", CompilerStatus.AMBIGUOUS, LanguageErrorCode.AMBIGUOUS_COMMAND),
        ("右转", CompilerStatus.AMBIGUOUS, LanguageErrorCode.MISSING_PARAMETER),
        (
            "跳一下",
            CompilerStatus.UNSUPPORTED,
            LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY,
        ),
        ("前进2公里", CompilerStatus.MALFORMED, LanguageErrorCode.INVALID_UNIT),
        ("前进NaN米", CompilerStatus.MALFORMED, LanguageErrorCode.MALFORMED_NUMBER),
        (
            "左转45度同时右转45度",
            CompilerStatus.MALFORMED,
            LanguageErrorCode.CONTRADICTORY_COMMAND,
        ),
    ],
)
def test_failure_result_contract(
    utterance: str, status: CompilerStatus, code: LanguageErrorCode
) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is status
    assert result.success is False
    assert result.mission is None
    assert result.error_code is code
    assert isinstance(result.error_message, str) and result.error_message
    payload = result.to_dict()
    assert payload["status"] == status.value
    assert payload["error_code"] == code.value
    assert payload["mission"] is None


# ---------------------------------------------------------------------------
# Ambiguity and missing parameters
# ---------------------------------------------------------------------------
VAGUE_UTTERANCES = [
    "往前走一点",
    "走一会",
    "前进一段",
    "转一下",
    "往那边走",
    "走到那里",
    "随便转个方向",
    "前进几米",
    "大概走一下",
]


@pytest.mark.parametrize("utterance", VAGUE_UTTERANCES)
def test_vague_quantities_fail_closed_as_ambiguous(utterance: str) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.error_code is LanguageErrorCode.AMBIGUOUS_COMMAND
    assert result.mission is None


def test_turn_over_there_is_ambiguous_not_unsupported() -> None:
    result = LanguageCompiler().compile("转过去")
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.error_code is LanguageErrorCode.AMBIGUOUS_COMMAND
    assert result.mission is None


@pytest.mark.parametrize("utterance", ["右转", "前进"])
def test_missing_parameters_are_never_silently_defaulted(utterance: str) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.error_code is LanguageErrorCode.MISSING_PARAMETER
    assert result.mission is None


@pytest.mark.parametrize("utterance", ["右转然后停止", "前进然后停止"])
def test_missing_parameter_before_a_connector_is_ambiguous(utterance: str) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.error_code is LanguageErrorCode.MISSING_PARAMETER
    assert result.mission is None


# ---------------------------------------------------------------------------
# Unsupported capabilities
# ---------------------------------------------------------------------------
UNSUPPORTED_UTTERANCES = [
    "跳一下",
    "跑起来",
    "坐下",
    "蹲下",
    "挥手",
    "拿杯子",
    "抓东西",
    "去桌子那里",
    "找红色箱子",
    "绕过障碍",
]


@pytest.mark.parametrize("utterance", UNSUPPORTED_UTTERANCES)
def test_unsupported_capabilities_fail_closed(utterance: str) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is CompilerStatus.UNSUPPORTED
    assert result.error_code is LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY
    assert result.mission is None


def test_unsupported_capability_wins_when_an_ambiguous_marker_is_also_present() -> None:
    result = LanguageCompiler().compile("去桌子那里")
    assert result.status is CompilerStatus.UNSUPPORTED
    assert result.error_code is LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY
    assert result.mission is None


# ---------------------------------------------------------------------------
# Malformed and adversarial input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("utterance", "code"),
    [
        ("前进2公里", LanguageErrorCode.INVALID_UNIT),
        ("前进2英尺", LanguageErrorCode.INVALID_UNIT),
        ("左转45弧度", LanguageErrorCode.INVALID_UNIT),
        ("前进1.2.3米", LanguageErrorCode.MALFORMED_NUMBER),
        ("前进NaN米", LanguageErrorCode.MALFORMED_NUMBER),
        ("前进Infinity米", LanguageErrorCode.MALFORMED_NUMBER),
        ("前进1e999米", LanguageErrorCode.MALFORMED_NUMBER),
        ("左转45度同时右转45度", LanguageErrorCode.CONTRADICTORY_COMMAND),
        ("右转45度并且左转45度", LanguageErrorCode.CONTRADICTORY_COMMAND),
        ("站立5", LanguageErrorCode.LANGUAGE_PARSE_ERROR),
        ("然后前进2米", LanguageErrorCode.LANGUAGE_PARSE_ERROR),
        ("前进2米然后然后停止", LanguageErrorCode.LANGUAGE_PARSE_ERROR),
        ("前进2米然后", LanguageErrorCode.LANGUAGE_PARSE_ERROR),
    ],
)
def test_malformed_inputs_return_machine_readable_codes(
    utterance: str, code: LanguageErrorCode
) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is code
    assert result.mission is None


@pytest.mark.parametrize(
    "value", [None, 123, ["前进2米"], {"utterance": "前进2米"}]
)
def test_non_string_input_is_rejected(value) -> None:
    result = LanguageCompiler().compile(value)
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.LANGUAGE_PARSE_ERROR
    assert result.mission is None


def test_input_length_limit_is_enforced_before_parsing() -> None:
    long_result = LanguageCompiler().compile("前进2米" * 200)
    assert long_result.status is CompilerStatus.MALFORMED
    assert long_result.error_code is LanguageErrorCode.INPUT_TOO_LONG
    assert long_result.mission is None

    bounded = LanguageCompiler(max_input_chars=4)
    assert bounded.compile("前进2米").status is CompilerStatus.SUCCESS
    over_limit = bounded.compile("前进2米停止")
    assert over_limit.status is CompilerStatus.MALFORMED
    assert over_limit.error_code is LanguageErrorCode.INPUT_TOO_LONG
    assert over_limit.diagnostics["max_input_chars"] == 4


ADVERSARIAL_UTTERANCES = [
    "$(Remove-Item -Recurse -Force D:\\work)",
    "__import__('os').system('echo pwned')",
    "python -c 'print(1)'",
    "!!python/object:os.system",
    "../../../etc/passwd",
    "a: [1, 2]",
    "前进2米; rm -rf /",
    "Infinity",
    "1e999",
]


@pytest.mark.parametrize("utterance", ADVERSARIAL_UTTERANCES)
def test_adversarial_input_is_never_executed_or_promoted_to_a_mission(
    utterance: str,
) -> None:
    result = LanguageCompiler().compile(utterance)
    assert result.success is False
    assert result.mission is None
    assert isinstance(result.error_code, LanguageErrorCode)


def test_pause_is_not_silently_mapped_to_stop() -> None:
    result = LanguageCompiler().compile("暂停一下")
    assert result.status is not CompilerStatus.SUCCESS
    assert result.mission is None


# ---------------------------------------------------------------------------
# Determinism and frozen integration boundary
# ---------------------------------------------------------------------------
def test_compilation_is_deterministic_across_repeats_and_instances() -> None:
    utterance = "先站立2秒，然后前进4米，再左转45度，最后停止"
    compiler = LanguageCompiler()
    first = compiler.compile(utterance).to_dict()
    assert compiler.compile(utterance).to_dict() == first
    assert LanguageCompiler().compile(utterance).to_dict() == first
    assert LanguageCompiler().grammar_sha256 == compiler.grammar_sha256


def test_capability_unknown_is_a_grounding_outcome_not_a_language_error(
    phase13_grounder: CapabilityGrounder,
) -> None:
    result = LanguageCompiler().compile("前进25米")
    assert result.status is CompilerStatus.SUCCESS
    assert result.mission is not None
    assert MissionValidator().validate(result.mission).valid

    plan = phase13_grounder.ground_mission(result.mission)
    assert plan.status == CAPABILITY_UNKNOWN
    assert len(plan.results) == 1
    assert plan.results[0].execution_mode is None
