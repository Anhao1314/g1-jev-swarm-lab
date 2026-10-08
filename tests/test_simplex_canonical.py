"""Tests for the Phase 2.2b deterministic canonicalizer."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from g1swarm.language.benchmark import canonical_mission_hash, canonical_mission_payload
from g1swarm.mission import MISSION_SCHEMA_VERSION, Mission, MissionValidator, SkillName
from g1swarm.mission.benchmark import load_corpus, mission_document
from g1swarm.simplex.canonical import (
    CanonicalizationCode,
    CanonicalizationError,
    canonical_document,
    canonical_json,
    canonical_sha256,
    canonicalize_mission,
    comparison_hash,
    comparison_payload,
    normalize_parameter,
    normalize_skill,
)

CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "phase2"
    / "oracle_mission_runtime_001"
    / "mission_corpus.yaml"
)


def _draft(**overrides) -> dict:
    document = {
        "schema_version": MISSION_SCHEMA_VERSION,
        "mission_id": "mission-001",
        "steps": [
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 5.0},
                "depends_on": [],
            },
            {
                "id": "s2",
                "skill": "turn",
                "parameters": {"angle_deg": 45.0},
                "depends_on": [],
            },
            {
                "id": "s3",
                "skill": "stop",
                "parameters": {},
                "depends_on": ["s2"],
            },
        ],
    }
    document.update(overrides)
    return document


def _code_of(callable_, *args, **kwargs) -> CanonicalizationCode:
    with pytest.raises(CanonicalizationError) as excinfo:
        callable_(*args, **kwargs)
    return excinfo.value.code


def test_frozen_corpus_matches_phase21_comparison_helpers() -> None:
    corpus = load_corpus(CORPUS_PATH)
    assert corpus["missions"]
    for entry in corpus["missions"]:
        document = mission_document(entry, corpus["schema_version"])
        mission = Mission.from_dict(document)
        assert comparison_payload(document) == canonical_mission_payload(mission)
        assert comparison_hash(document) == canonical_mission_hash(mission)
        assert canonical_sha256(document) != comparison_hash(document)


def test_mission_id_only_changes_full_hash() -> None:
    first = _draft(mission_id="run-a")
    second = _draft(mission_id="run-b")
    assert comparison_hash(first) == comparison_hash(second)
    assert canonical_sha256(first) != canonical_sha256(second)
    assert comparison_payload(first, include_mission_id=True)["mission_id"] == "run-a"


def test_representation_variants_collapse_to_one_canonical_form() -> None:
    integer = _draft(
        steps=[
            {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 5}},
            {"id": "s2", "skill": "turn", "parameters": {"angle_deg": 45}},
        ]
    )
    floating = _draft(
        steps=[
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 5.0},
                "depends_on": [],
            },
            {
                "id": "s2",
                "skill": "turn",
                "parameters": {"angle_deg": 45.0},
                "depends_on": [],
            },
        ]
    )
    assert canonical_json(integer) == canonical_json(floating)
    assert canonical_sha256(integer) == canonical_sha256(floating)


def test_negative_zero_is_normalized() -> None:
    document = _draft(
        steps=[
            {
                "id": "s1",
                "skill": "turn",
                "parameters": {"angle_deg": -0.0},
                "depends_on": [],
            }
        ]
    )
    value = canonical_document(document)["steps"][0]["parameters"]["angle_deg"]
    assert value == 0.0
    assert math.copysign(1.0, value) == 1.0


def test_skill_and_parameter_aliases_and_unit_suffixes() -> None:
    document = {
        "schema_version": MISSION_SCHEMA_VERSION,
        "mission_id": "alias-run",
        "steps": [
            {"id": "s1", "skill": "Walk", "parameters": {"distance": "2.50 m"}},
            {"id": "s2", "skill": "rotate", "parameters": {"angle": "45度"}},
            {"id": "s3", "skill": "站立", "parameters": {"时长": "2 s"}},
            {"id": "s4", "skill": "halt", "parameters": {}},
        ],
    }
    mission = canonicalize_mission(document)
    assert [step.skill for step in mission.steps] == [
        SkillName.WALK_FORWARD,
        SkillName.TURN,
        SkillName.STAND,
        SkillName.STOP,
    ]
    assert mission.steps[0].parameters == {"distance_m": 2.5}
    assert mission.steps[1].parameters == {"angle_deg": 45.0}
    assert mission.steps[2].parameters == {"duration_s": 2.0}
    assert mission.steps[3].parameters == {}


def test_structured_quantity_and_unit_conversion() -> None:
    document = _draft(
        steps=[
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance": {"value": 250, "unit": "cm"}},
            }
        ]
    )
    assert canonical_document(document)["steps"][0]["parameters"]["distance_m"] == 2.5


def test_dependency_deduplication_preserves_first_seen_order() -> None:
    document = _draft(
        steps=[
            {"id": "s1", "skill": "stop", "parameters": {}},
            {"id": "s2", "skill": "stand", "parameters": {}, "depends_on": ["s1", "s1"]},
        ]
    )
    mission = canonicalize_mission(document)
    assert mission.steps[1].depends_on == ("s1",)
    assert canonical_document(document)["steps"][1]["depends_on"] == ["s1"]


def test_repair_mode_fills_only_representation_defaults() -> None:
    document = {
        "mission_id": "repair-run",
        "steps": [
            {"skill": "walk_forward", "parameters": {"distance": "4 m"}},
            {"skill": "stop"},
        ],
    }
    strict_error = _code_of(canonicalize_mission, document)
    assert strict_error is CanonicalizationCode.INVALID_SCHEMA_VERSION
    mission = canonicalize_mission(document, strict=False)
    assert mission.schema_version == MISSION_SCHEMA_VERSION
    assert [step.step_id for step in mission.steps] == ["s1", "s2"]
    assert mission.steps[0].depends_on == ()
    assert mission.steps[0].parameters == {"distance_m": 4.0}


def test_strict_mode_requires_step_ids_even_with_schema() -> None:
    document = _draft(steps=[{"skill": "stop", "parameters": {}}])
    assert _code_of(canonicalize_mission, document) is CanonicalizationCode.INVALID_STEP_ID


def test_duplicate_ids_are_rejected() -> None:
    document = _draft(
        steps=[
            {"id": "s1", "skill": "stop", "parameters": {}},
            {"id": "s1", "skill": "stand", "parameters": {}},
        ]
    )
    assert _code_of(canonicalize_mission, document) is CanonicalizationCode.DUPLICATE_STEP_ID


def test_unknown_dependency_is_rejected() -> None:
    document = _draft(
        steps=[
            {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
            {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s9"]},
        ]
    )
    assert _code_of(canonicalize_mission, document) is CanonicalizationCode.UNKNOWN_DEPENDENCY


@pytest.mark.parametrize(
    ("document", "code"),
    [
        (
            _draft(steps=[{"id": "s1", "skill": "navigate", "parameters": {}}]),
            CanonicalizationCode.UNKNOWN_SKILL,
        ),
        (
            _draft(steps=[{"id": "s1", "skill": "walk_forward", "parameters": {"speed_mps": 1.0}}]),
            CanonicalizationCode.UNKNOWN_PARAMETER,
        ),
        (
            _draft(steps=[{"id": "s1", "skill": "walk_forward", "parameters": {}}]),
            CanonicalizationCode.MISSING_PARAMETER,
        ),
        (
            _draft(
                steps=[
                    {
                        "id": "s1",
                        "skill": "walk_forward",
                        "parameters": {"distance_m": 4.0, "meters": 4.0},
                    }
                ]
            ),
            CanonicalizationCode.AMBIGUOUS_PARAMETER,
        ),
        (
            _draft(steps=[{"id": "s1", "skill": "stop", "parameters": {}, "risk": "low"}]),
            CanonicalizationCode.UNKNOWN_STEP_FIELD,
        ),
        (_draft(controller="motion.pt"), CanonicalizationCode.UNKNOWN_MISSION_FIELD),
        (_draft(mission_id="../escape"), CanonicalizationCode.INVALID_MISSION_ID),
        (_draft(schema_version="1.0.0"), CanonicalizationCode.INVALID_SCHEMA_VERSION),
        (_draft(steps=[]), CanonicalizationCode.INVALID_STEPS),
    ],
)
def test_typed_rejections(document: dict, code: CanonicalizationCode) -> None:
    assert _code_of(canonicalize_mission, document) is code


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_non_finite_and_boolean_values_are_rejected(value: object) -> None:
    document = _draft(
        steps=[{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": value}}]
    )
    code = _code_of(canonicalize_mission, document)
    assert code in {
        CanonicalizationCode.NON_FINITE_NUMBER,
        CanonicalizationCode.INVALID_PARAMETER_VALUE,
    }


@pytest.mark.parametrize("text", ["nan", "inf", "5-", "abc", "1e3", "5,5"])
def test_malformed_text_numbers_are_rejected(text: str) -> None:
    document = _draft(
        steps=[{"id": "s1", "skill": "walk_forward", "parameters": {"distance": text}}]
    )
    assert (
        _code_of(canonicalize_mission, document)
        is CanonicalizationCode.INVALID_PARAMETER_VALUE
    )


def test_text_numbers_can_be_disabled() -> None:
    document = _draft(
        steps=[{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": "5 m"}}]
    )
    assert (
        _code_of(canonicalize_mission, document, allow_text_numbers=False)
        is CanonicalizationCode.INVALID_PARAMETER_VALUE
    )


def test_step_limit_is_enforced() -> None:
    steps = [{"id": f"s{index}", "skill": "stop", "parameters": {}} for index in range(33)]
    code = _code_of(canonicalize_mission, _draft(steps=steps))
    assert code is CanonicalizationCode.TOO_MANY_STEPS


def test_execution_mode_override_is_forbidden_by_default() -> None:
    document = _draft(
        steps=[
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 4.0},
                "execution_mode_override": "open_loop",
            }
        ]
    )
    assert _code_of(canonicalize_mission, document) is CanonicalizationCode.FORBIDDEN_FIELD
    mission = canonicalize_mission(document, allow_execution_mode_override=True)
    assert mission.steps[0].execution_mode_override is not None
    canonical = canonical_document(document, allow_execution_mode_override=True)
    assert canonical["steps"][0]["execution_mode_override"] == "open_loop"
    assert "execution_mode_override" not in comparison_payload(
        document, allow_execution_mode_override=True
    )["steps"][0]


def test_invalid_execution_mode_is_rejected_when_allowed() -> None:
    document = _draft(
        steps=[
            {
                "id": "s1",
                "skill": "stop",
                "parameters": {},
                "execution_mode_override": "teleport",
            }
        ]
    )
    assert (
        _code_of(canonicalize_mission, document, allow_execution_mode_override=True)
        is CanonicalizationCode.INVALID_EXECUTION_MODE
    )


def test_negative_distance_survives_to_validator() -> None:
    document = _draft(
        steps=[{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": -2.0}}]
    )
    mission = canonicalize_mission(document)
    assert mission.steps[0].parameters["distance_m"] == -2.0
    assert MissionValidator().validate(mission).valid is False


def test_canonical_json_is_byte_stable_and_hashes_match() -> None:
    document = _draft(
        mission_id="golden",
        steps=[
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 5.0},
                "depends_on": [],
            }
        ],
    )
    expected = (
        '{"mission_id":"golden","schema_version":"2.0.0","steps":['
        '{"depends_on":[],"id":"s1","parameters":{"distance_m":5.0},"skill":"walk_forward"}]}'
    )
    assert canonical_json(document) == expected
    assert canonical_sha256(document) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_mission_instance_round_trips_through_canonicalizer() -> None:
    mission = Mission.from_dict(_draft())
    canonical = canonicalize_mission(mission)
    assert canonical_document(mission) == canonical_document(canonical)
    assert comparison_hash(mission) == comparison_hash(_draft())


def test_public_alias_helpers() -> None:
    assert normalize_skill("WALK-FORWARD") is SkillName.WALK_FORWARD
    assert normalize_parameter(SkillName.WALK_FORWARD, "Meters") == "distance_m"
    assert _code_of(normalize_skill, "fly") is CanonicalizationCode.UNKNOWN_SKILL
    assert (
        _code_of(normalize_parameter, SkillName.STOP, "distance_m")
        is CanonicalizationCode.UNKNOWN_PARAMETER
    )
