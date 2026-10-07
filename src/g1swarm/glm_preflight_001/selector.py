"""Explicit provider selection only; never discovers or borrows credentials."""

from __future__ import annotations

from ..llm.backend import DeepSeekResponsesBackend, LLMBackendConfig, LLMConfigurationError
from .chat_backend import GLMChatCompletionsBackend, GLMChatConfig


def create_backend(provider_id: str, *, glm_config: GLMChatConfig | None = None,
                   deepseek_config: LLMBackendConfig | None = None):
    if provider_id == "glm-5.3-flash":
        if not isinstance(glm_config, GLMChatConfig) or deepseek_config is not None:
            raise LLMConfigurationError("glm-5.3-flash requires only explicit GLMChatConfig")
        return GLMChatCompletionsBackend(glm_config)
    if provider_id == "deepseek-flash":
        if not isinstance(deepseek_config, LLMBackendConfig) or glm_config is not None:
            raise LLMConfigurationError("deepseek-flash requires only explicit DeepSeek configuration")
        if deepseek_config.model != "deepseek-flash":
            raise LLMConfigurationError("DeepSeek model identity does not match selected provider")
        return DeepSeekResponsesBackend(deepseek_config)
    raise LLMConfigurationError("unsupported explicit provider selection")


__all__ = ["create_backend"]
