"""Language-level failure taxonomy for the Phase 2.1 controlled compiler.

This taxonomy is deliberately separate from the Phase 2.0 Mission/Runtime
failure taxonomy. A language error means the compiler could not produce a
Mission IR; it never means that the robot rejected an otherwise valid mission.
"""

from __future__ import annotations

from enum import Enum


class CompilerStatus(str, Enum):
    SUCCESS = "SUCCESS"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    MALFORMED = "MALFORMED"


class LanguageErrorCode(str, Enum):
    LANGUAGE_PARSE_ERROR = "LANGUAGE_PARSE_ERROR"
    AMBIGUOUS_COMMAND = "AMBIGUOUS_COMMAND"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_UNIT = "INVALID_UNIT"
    UNSUPPORTED_LANGUAGE_CAPABILITY = "UNSUPPORTED_LANGUAGE_CAPABILITY"
    MALFORMED_NUMBER = "MALFORMED_NUMBER"
    CONTRADICTORY_COMMAND = "CONTRADICTORY_COMMAND"
    EMPTY_LANGUAGE_INPUT = "EMPTY_LANGUAGE_INPUT"
    INPUT_TOO_LONG = "INPUT_TOO_LONG"


class LanguageCompileError(ValueError):
    """Internal lexical/structural failure with a stable language error code."""

    def __init__(self, code: LanguageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
