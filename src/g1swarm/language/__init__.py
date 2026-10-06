"""Controlled Chinese language compiler for Mission IR 2.0."""

from .compiler import (
    COMPILER_VERSION,
    DEFAULT_MAX_INPUT_CHARS,
    LanguageCompiler,
)
from .benchmark import (
    canonical_mission_hash,
    canonical_mission_payload,
    evaluate_compiler_sample,
    summarize_compiler_results,
)
from .errors import CompilerStatus, LanguageCompileError, LanguageErrorCode
from .result import CompilerResult
from .equivalence import (
    build_runtime_executor,
    compare_runtime_results,
    mission_equivalence,
    oracle_mission_from_sample,
    runtime_result_payload,
)

__all__ = [
    "COMPILER_VERSION",
    "DEFAULT_MAX_INPUT_CHARS",
    "CompilerResult",
    "CompilerStatus",
    "LanguageCompileError",
    "LanguageCompiler",
    "LanguageErrorCode",
    "build_runtime_executor",
    "canonical_mission_hash",
    "canonical_mission_payload",
    "compare_runtime_results",
    "evaluate_compiler_sample",
    "mission_equivalence",
    "oracle_mission_from_sample",
    "runtime_result_payload",
    "summarize_compiler_results",
]
