"""Phase 2.2 LLM Mission Compiler stack (datasets, backend, compiler, scoring)."""

from .backend import (
    DeepSeekResponsesBackend,
    LLMBackend,
    LLMBackendConfig,
    LLMBackendError,
    LLMBackendResponse,
    LLMConfigurationError,
    ScriptedBackend,
)
from .compiler import COMPILER_VERSION, LLMMissionCompiler
from .datasets import (
    LLMDataset,
    LLMDatasetError,
    LLMSample,
    load_dataset,
    parse_dataset,
)
from .parsing import (
    LLMContractError,
    LLMEnvelope,
    contract_violations,
    parse_envelope,
)
from .scoring import compare_engines, evaluate_sample, summarize_results

__all__ = [
    "COMPILER_VERSION",
    "DeepSeekResponsesBackend",
    "LLMBackend",
    "LLMBackendConfig",
    "LLMBackendError",
    "LLMBackendResponse",
    "LLMConfigurationError",
    "LLMContractError",
    "LLMDataset",
    "LLMDatasetError",
    "LLMEnvelope",
    "LLMMissionCompiler",
    "LLMSample",
    "ScriptedBackend",
    "compare_engines",
    "contract_violations",
    "evaluate_sample",
    "load_dataset",
    "parse_dataset",
    "parse_envelope",
    "summarize_results",
]
