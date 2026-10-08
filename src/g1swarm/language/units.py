"""Deterministic number and unit handling for controlled Chinese commands."""

from __future__ import annotations

import math
import re

from .errors import LanguageCompileError, LanguageErrorCode

_ARABIC_NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_CHINESE_NUMBER = re.compile(r"^[零〇一二两三四五六七八九十百千]+$")
_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_DISTANCE_UNITS = {
    "m": 1.0,
    "米": 1.0,
    "M": 1.0,
    "cm": 0.01,
    "厘米": 0.01,
    "CM": 0.01,
}
_ANGLE_UNITS = {"°": 1.0, "度": 1.0}


def parse_chinese_integer(text: str) -> float | None:
    """Parse a bounded Chinese integer using a deterministic grammar.

    The converter intentionally covers the controlled subset needed by Phase
    2.1: 0-9999 with units 十/百/千, including zero-separated forms. It returns
    ``None`` for malformed combinations instead of guessing.
    """

    if not text or not _CHINESE_NUMBER.match(text):
        return None
    if all(char in _CN_DIGITS for char in text):
        if len(text) != 1:
            return None
        return float(_CN_DIGITS[text])
    if text.endswith("零"):
        return None

    total = 0
    section = 0
    number = 0
    last_unit = 10000
    previous_was_digit = False
    for char in text:
        if char in _CN_DIGITS:
            if previous_was_digit and char != "零":
                return None
            number = _CN_DIGITS[char]
            previous_was_digit = True
            continue
        unit = _CN_UNITS[char]
        if unit >= last_unit:
            return None
        if number == 0:
            number = 1
        section += number * unit
        number = 0
        last_unit = unit
        previous_was_digit = False
    return float(section + number)


def parse_number(text: str) -> float:
    """Parse an Arabic or controlled Chinese number, rejecting all other forms."""

    if _ARABIC_NUMBER.match(text):
        value = float(text)
    elif _CHINESE_NUMBER.match(text):
        value = parse_chinese_integer(text)
        if value is None:
            raise LanguageCompileError(
                LanguageErrorCode.MALFORMED_NUMBER,
                f"malformed Chinese number {text!r}",
            )
    else:
        raise LanguageCompileError(
            LanguageErrorCode.MALFORMED_NUMBER,
            f"unsupported number token {text!r}",
        )
    if not math.isfinite(value):
        raise LanguageCompileError(
            LanguageErrorCode.MALFORMED_NUMBER,
            f"number is not finite: {text!r}",
        )
    return float(value)


def distance_to_m(text: str, unit: str) -> float:
    value = parse_number(text)
    factor = _DISTANCE_UNITS.get(unit)
    if factor is None:
        raise LanguageCompileError(
            LanguageErrorCode.INVALID_UNIT,
            f"unsupported distance unit {unit!r}",
        )
    return value * factor


def angle_to_deg(text: str, unit: str) -> float:
    value = parse_number(text)
    factor = _ANGLE_UNITS.get(unit)
    if factor is None:
        raise LanguageCompileError(
            LanguageErrorCode.INVALID_UNIT,
            f"unsupported angle unit {unit!r}",
        )
    return value * factor


def duration_to_s(text: str, unit: str) -> float:
    value = parse_number(text)
    if unit not in {"秒", "s", "S"}:
        raise LanguageCompileError(
            LanguageErrorCode.INVALID_UNIT,
            f"unsupported duration unit {unit!r}",
        )
    return value


def known_distance_units() -> frozenset[str]:
    return frozenset(_DISTANCE_UNITS)


def known_angle_units() -> frozenset[str]:
    return frozenset(_ANGLE_UNITS)
