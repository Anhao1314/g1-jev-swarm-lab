"""Number, unit, and normalization tests for the Phase 2.1 language layer."""

from __future__ import annotations

import pytest

from g1swarm.language.errors import LanguageCompileError, LanguageErrorCode
from g1swarm.language.normalization import normalize_text
from g1swarm.language.units import (
    angle_to_deg,
    distance_to_m,
    duration_to_s,
    known_angle_units,
    known_distance_units,
    parse_chinese_integer,
    parse_number,
)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("站立 5 秒", "站立5秒"),
        ("站立5秒。前进2米", "站立5秒,前进2米"),
        ("站立5秒，然后前进2米", "站立5秒然后前进2米"),
        ("左转４５度", "左转45度"),
        ("站立5秒，", "站立5秒"),
        ("\t站好\n2s\t", "站好2s"),
    ],
)
def test_normalization_is_deterministic_and_never_guesses(
    text: str, expected: str
) -> None:
    assert normalize_text(text) == expected
    assert normalize_text(text) == normalize_text(text)


def test_normalization_preserves_left_and_right_words() -> None:
    assert normalize_text("向左转45度 然后 向右转45度") == "向左转45度然后向右转45度"


def test_normalization_handles_non_string_input() -> None:
    assert normalize_text(None) == ""
    assert normalize_text(42) == ""


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("〇", 0.0),
        ("零", 0.0),
        ("一", 1.0),
        ("两", 2.0),
        ("五", 5.0),
        ("十", 10.0),
        ("二十", 20.0),
        ("四十五", 45.0),
        ("九十", 90.0),
        ("一百二十三", 123.0),
        ("两百", 200.0),
        ("两千", 2000.0),
    ],
)
def test_chinese_integer_conversion(text: str, expected: float) -> None:
    assert parse_chinese_integer(text) == expected


@pytest.mark.parametrize("text", ["一二", "零五", "十十", "一百零", "二十三三"])
def test_malformed_chinese_numbers_return_none(text: str) -> None:
    assert parse_chinese_integer(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0", 0.0), ("4", 4.0), ("2.5", 2.5), ("四十五", 45.0)],
)
def test_parse_number_accepts_only_controlled_forms(text: str, expected: float) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    "text", ["1.2.3", "nan", "NaN", "inf", "Infinity", "1e999", "-2", "+2"]
)
def test_parse_number_rejects_malformed_forms(text: str) -> None:
    with pytest.raises(LanguageCompileError) as excinfo:
        parse_number(text)
    assert excinfo.value.code is LanguageErrorCode.MALFORMED_NUMBER


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "unit", "expected_m"),
    [
        ("2", "m", 2.0),
        ("2", "米", 2.0),
        ("200", "厘米", 2.0),
        ("250", "cm", 2.5),
    ],
)
def test_distance_normalization_uses_meters(
    text: str, unit: str, expected_m: float
) -> None:
    assert distance_to_m(text, unit) == expected_m


@pytest.mark.parametrize(
    ("text", "unit", "expected_m"), [("2", "M", 2.0), ("2", "CM", 0.02)]
)
def test_uppercase_distance_units_declared_in_the_grammar_are_normalized(
    text: str, unit: str, expected_m: float
) -> None:
    assert distance_to_m(text, unit) == expected_m


@pytest.mark.parametrize(
    ("text", "unit", "expected_deg"), [("45", "度", 45.0), ("45", "°", 45.0)]
)
def test_angle_normalization_uses_degrees(
    text: str, unit: str, expected_deg: float
) -> None:
    assert angle_to_deg(text, unit) == expected_deg


@pytest.mark.parametrize(
    ("text", "unit", "expected_s"),
    [("2", "秒", 2.0), ("2", "s", 2.0), ("2", "S", 2.0)],
)
def test_duration_normalization_uses_seconds(
    text: str, unit: str, expected_s: float
) -> None:
    assert duration_to_s(text, unit) == expected_s


@pytest.mark.parametrize(
    ("convert", "unit"),
    [
        (distance_to_m, "公里"),
        (distance_to_m, "英尺"),
        (distance_to_m, "mm"),
        (angle_to_deg, "rad"),
        (angle_to_deg, "弧度"),
        (duration_to_s, "分钟"),
    ],
)
def test_unregistered_units_fail_with_invalid_unit(convert, unit: str) -> None:
    with pytest.raises(LanguageCompileError) as excinfo:
        convert("2", unit)
    assert excinfo.value.code is LanguageErrorCode.INVALID_UNIT


def test_known_unit_sets_are_closed_and_explicit() -> None:
    assert {"m", "米", "厘米", "cm"} <= known_distance_units()
    assert known_distance_units() & {"公里", "英尺", "mm"} == set()
    assert known_angle_units() == frozenset({"度", "°"})
