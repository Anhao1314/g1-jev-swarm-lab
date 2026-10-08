"""Deterministic controlled-Chinese compiler for Mission IR 2.0.

The compiler is intentionally a language-to-IR boundary. It never invokes the
skill router, simulator, task graph, capability grounder or controller, and it
does not choose an execution mode or risk level.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import lark
from lark import Lark
from lark.exceptions import UnexpectedInput, VisitError

from ..mission.ir import MISSION_SCHEMA_VERSION, Mission, MissionStep
from ..mission.validator import MissionValidator
from .errors import CompilerStatus, LanguageCompileError, LanguageErrorCode
from .normalization import normalize_text
from .result import CompilerResult
from .transformer import MissionTransformer

COMPILER_VERSION = "2.1.0"
DEFAULT_MAX_INPUT_CHARS = 512
DEFAULT_STAND_DURATION_S = 2.0

UNSUPPORTED_PHRASES = (
    "跳",
    "跑",
    "坐下",
    "蹲下",
    "挥手",
    "拿",
    "抓",
    "找",
    "绕过",
    "障碍",
    "杯子",
    "桌子",
    "箱子",
    "推",
    "拉",
    "扔",
    "捡",
    "爬",
    "游泳",
    "打开",
    "关闭",
)

AMBIGUOUS_MARKERS = (
    "一点",
    "一会",
    "一段",
    "转过去",
    "转一下",
    "那边",
    "那里",
    "随便",
    "几米",
    "大概",
    "走一下",
    "转个方向",
    "差不多",
    "少量",
    "若干",
    "几个",
    "多少",
)

_INVALID_UNIT = re.compile(
    r"(?:[0-9零〇一二两三四五六七八九十百千]+)"
    r"(?:英尺|ft|英寸|inch|rad|弧度|公里|km|毫米|mm)"
)
_MALFORMED_NUMBER = re.compile(
    r"(?:[0-9]+\.[0-9]+\.[0-9]+|(?:nan|inf|infinity|1e999))",
    re.IGNORECASE,
)
_MISSING_TURN = re.compile(
    r"(?:左转|右转|向左转|向右转|逆时针转|顺时针转)"
    r"(?:(?:然后|再|接着|之后|最后)|,|$)"
)
_MISSING_WALK = re.compile(
    r"(?:前进|往前走|向前走|向前移动|往前移动)"
    r"(?:(?:然后|再|接着|之后|最后)|,|$)"
)
_CONTRADICTORY = re.compile(r"(?:左转|向左转|逆时针转).*(?:并且|同时).*(?:右转|向右转|顺时针转)|"
                            r"(?:右转|向右转|顺时针转).*(?:并且|同时).*(?:左转|向左转|逆时针转)")


class LanguageCompiler:
    """Compile a bounded controlled-Chinese utterance into Mission IR."""

    def __init__(self, *, max_input_chars: int = DEFAULT_MAX_INPUT_CHARS) -> None:
        self.max_input_chars = int(max_input_chars)
        grammar_path = Path(__file__).with_name("grammar.lark")
        grammar_text = grammar_path.read_text(encoding="utf-8")
        self.grammar_sha256 = hashlib.sha256(grammar_text.encode("utf-8")).hexdigest()
        self._parser = Lark(
            grammar_text,
            start="mission",
            parser="lalr",
            lexer="contextual",
            propagate_positions=True,
            maybe_placeholders=False,
        )

    def compile(self, text: str) -> CompilerResult:
        if not isinstance(text, str):
            return self._failure(
                normalized="",
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                message="language input must be a string",
            )

        normalized = normalize_text(text)
        diagnostics = {
            "compiler_version": COMPILER_VERSION,
            "grammar_sha256": self.grammar_sha256,
            "lark_version": getattr(lark, "__version__", "unknown"),
            "parser_mode": "lalr",
            "lexer": "contextual",
            "max_input_chars": self.max_input_chars,
            "normalized_length": len(normalized),
        }
        if not normalized:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.EMPTY_LANGUAGE_INPUT,
                message="language input is empty",
                diagnostics=diagnostics,
            )
        if len(normalized) > self.max_input_chars:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.INPUT_TOO_LONG,
                message=f"language input exceeds {self.max_input_chars} characters",
                diagnostics=diagnostics,
            )

        preflight = self._preflight(normalized, diagnostics)
        if preflight is not None:
            return preflight

        try:
            tree = self._parser.parse(normalized)
            commands = MissionTransformer().transform(tree)
        except VisitError as exc:
            original = exc.orig_exc
            if isinstance(original, LanguageCompileError):
                return self._from_language_error(normalized, original, diagnostics)
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                message=str(original),
                diagnostics=diagnostics,
            )
        except UnexpectedInput as exc:
            code = self._classify_parse_failure(normalized)
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=code,
                message=f"controlled grammar rejected the utterance: {type(exc).__name__}",
                diagnostics=diagnostics,
            )

        try:
            steps = tuple(
                MissionStep(
                    step_id=f"s{index}",
                    skill=command.skill,
                    parameters=dict(command.parameters),
                    depends_on=(f"s{index - 1}",) if index > 1 else (),
                )
                for index, command in enumerate(commands, start=1)
            )
        except (AttributeError, TypeError) as exc:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                message=f"compiler transformer returned malformed commands: {exc}",
                diagnostics=diagnostics,
            )

        mission = Mission(
            mission_id=self._mission_id(normalized),
            steps=steps,
            schema_version=MISSION_SCHEMA_VERSION,
        )
        report = MissionValidator().validate(mission)
        if not report.valid:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                message="; ".join(issue.message for issue in report.issues),
                diagnostics={**diagnostics, "validation": report.to_dict()},
            )
        diagnostics["step_count"] = len(steps)
        return CompilerResult(
            status=CompilerStatus.SUCCESS,
            mission=mission,
            normalized_text=normalized,
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------
    def _preflight(self, normalized: str, diagnostics: dict) -> CompilerResult | None:
        if _MALFORMED_NUMBER.search(normalized):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.MALFORMED_NUMBER,
                message="non-finite or malformed number",
                diagnostics=diagnostics,
            )
        if _INVALID_UNIT.search(normalized):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.INVALID_UNIT,
                message="unsupported unit",
                diagnostics=diagnostics,
            )
        if _CONTRADICTORY.search(normalized):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.CONTRADICTORY_COMMAND,
                message="contradictory turn directions",
                diagnostics=diagnostics,
            )
        if any(phrase in normalized for phrase in UNSUPPORTED_PHRASES):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.UNSUPPORTED,
                code=LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY,
                message="language capability is not supported by the current runtime",
                diagnostics=diagnostics,
            )
        # Vagueness takes precedence over a merely missing parameter: a phrase
        # such as "少量前进" is under-specified in kind, not only in value, and
        # classifies as AMBIGUOUS_COMMAND (spec sections 16/17).
        if any(marker in normalized for marker in AMBIGUOUS_MARKERS):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.AMBIGUOUS,
                code=LanguageErrorCode.AMBIGUOUS_COMMAND,
                message="vague quantity or direction is ambiguous",
                diagnostics=diagnostics,
            )
        if _MISSING_TURN.search(normalized) or _MISSING_WALK.search(normalized):
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.AMBIGUOUS,
                code=LanguageErrorCode.MISSING_PARAMETER,
                message="a required distance or angle is missing",
                diagnostics=diagnostics,
            )
        return None

    @staticmethod
    def _classify_parse_failure(normalized: str) -> LanguageErrorCode:
        if _MALFORMED_NUMBER.search(normalized):
            return LanguageErrorCode.MALFORMED_NUMBER
        if _INVALID_UNIT.search(normalized):
            return LanguageErrorCode.INVALID_UNIT
        return LanguageErrorCode.LANGUAGE_PARSE_ERROR

    @staticmethod
    def _mission_id(normalized: str) -> str:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"lang-{digest}"

    @staticmethod
    def _from_language_error(
        normalized: str,
        error: LanguageCompileError,
        diagnostics: dict,
    ) -> CompilerResult:
        status = (
            CompilerStatus.AMBIGUOUS
            if error.code in {LanguageErrorCode.AMBIGUOUS_COMMAND, LanguageErrorCode.MISSING_PARAMETER}
            else CompilerStatus.UNSUPPORTED
            if error.code is LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY
            else CompilerStatus.MALFORMED
        )
        return LanguageCompiler._failure(
            normalized=normalized,
            status=status,
            code=error.code,
            message=error.message,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _failure(
        *,
        normalized: str,
        status: CompilerStatus,
        code: LanguageErrorCode,
        message: str,
        diagnostics: dict | None = None,
    ) -> CompilerResult:
        return CompilerResult(
            status=status,
            mission=None,
            normalized_text=normalized,
            error_code=code,
            error_message=message,
            diagnostics=dict(diagnostics or {}),
        )
