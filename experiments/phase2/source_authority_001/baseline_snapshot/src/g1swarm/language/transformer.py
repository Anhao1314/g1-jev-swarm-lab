"""Lark parse-tree transformer for the Phase 2.1 command grammar."""

from __future__ import annotations

from dataclasses import dataclass

from lark import Token, Transformer

from ..mission.ir import SkillName
from .errors import LanguageCompileError, LanguageErrorCode
from .units import angle_to_deg, distance_to_m, duration_to_s


@dataclass(frozen=True)
class CommandSpec:
    skill: SkillName
    parameters: dict[str, float]


def _tokens(items) -> list[Token]:
    return [item for item in items if isinstance(item, Token)]


def _find_token(items, token_type: str) -> Token | None:
    for item in items:
        if isinstance(item, Token) and item.type == token_type:
            return item
    return None


class MissionTransformer(Transformer):
    """Transform a parse tree into ordered, typed command specifications."""

    def stand_command(self, items):
        number = _find_token(items, "NUMBER")
        unit = _find_token(items, "SECOND_UNIT")
        duration = 2.0
        if number is not None:
            if unit is None:
                raise LanguageCompileError(
                    LanguageErrorCode.INVALID_UNIT,
                    "stand duration is missing a time unit",
                )
            duration = duration_to_s(str(number), str(unit))
        return CommandSpec(SkillName.STAND, {"duration_s": duration})

    def stop_command(self, items):
        return CommandSpec(SkillName.STOP, {})

    def walk_command(self, items):
        number = _find_token(items, "NUMBER")
        unit = _find_token(items, "DISTANCE_UNIT")
        if number is None or unit is None:
            raise LanguageCompileError(
                LanguageErrorCode.MISSING_PARAMETER,
                "walk distance is missing",
            )
        return CommandSpec(
            SkillName.WALK_FORWARD,
            {"distance_m": distance_to_m(str(number), str(unit))},
        )

    def turn_left_command(self, items):
        number = _find_token(items, "NUMBER")
        unit = _find_token(items, "ANGLE_UNIT")
        if number is None or unit is None:
            raise LanguageCompileError(
                LanguageErrorCode.MISSING_PARAMETER,
                "turn angle is missing",
            )
        return CommandSpec(
            SkillName.TURN,
            {"angle_deg": angle_to_deg(str(number), str(unit))},
        )

    def turn_right_command(self, items):
        number = _find_token(items, "NUMBER")
        unit = _find_token(items, "ANGLE_UNIT")
        if number is None or unit is None:
            raise LanguageCompileError(
                LanguageErrorCode.MISSING_PARAMETER,
                "turn angle is missing",
            )
        return CommandSpec(
            SkillName.TURN,
            {"angle_deg": -angle_to_deg(str(number), str(unit))},
        )

    def mission(self, items):
        commands = tuple(item for item in items if isinstance(item, CommandSpec))
        if not commands:
            raise LanguageCompileError(
                LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                "no supported command found",
            )
        return commands
