"""Phase 2.2 LLM Mission Compiler adapter (runner-facing API).

The implementation lives in the ``g1swarm.llm`` core stack
(``backend`` / ``parsing`` / ``compiler`` / ``datasets`` / ``scoring``); this
package exposes the stable names consumed by ``scripts/run_llm_compiler.py``.
"""

from .api import (
    COMPILER_VERSION,
    BackendError,
    LLMCampaignRun,
    LLMMissionCompiler,
    OpenAICompatibleBackend,
    ReplayBackend,
    load_records,
    run_llm_campaign,
    summarize_llm_diagnostics,
    write_records,
)

__all__ = [
    "COMPILER_VERSION",
    "BackendError",
    "LLMCampaignRun",
    "LLMMissionCompiler",
    "OpenAICompatibleBackend",
    "ReplayBackend",
    "load_records",
    "run_llm_campaign",
    "summarize_llm_diagnostics",
    "write_records",
]
