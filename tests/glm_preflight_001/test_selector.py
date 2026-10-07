"""Explicit selection tests; no configuration stores or network access."""

import pytest

from g1swarm.glm_preflight_001 import GLMChatConfig, GLMChatCompletionsBackend, create_backend
from g1swarm.llm.backend import DeepSeekResponsesBackend, LLMBackendConfig, LLMConfigurationError


def glm_config():
    return GLMChatConfig("https://provider.invalid/v4", "synthetic-glm-only-credential")


def deepseek_config():
    return LLMBackendConfig(model="deepseek-flash", base_url="https://provider.invalid/v1",
                            api_key="synthetic-deepseek-only-credential")


def test_explicit_glm_selection():
    backend = create_backend("glm-5.3-flash", glm_config=glm_config())
    assert isinstance(backend, GLMChatCompletionsBackend)
    assert backend.model == "glm-5.3-flash"


def test_deepseek_selection_returns_original_backend_without_editing_it():
    value = deepseek_config()
    backend = create_backend("deepseek-flash", deepseek_config=value)
    assert type(backend) is DeepSeekResponsesBackend
    assert backend.config is value
    assert backend.config.responses_path == "/responses"


@pytest.mark.parametrize("provider", ["", "glm_chat", "deepseek_responses", "unknown", "GLM-5.3-FLASH"])
def test_no_implicit_provider_selection(provider):
    with pytest.raises(LLMConfigurationError):
        create_backend(provider)


def test_glm_cannot_borrow_old_provider_credentials():
    with pytest.raises(LLMConfigurationError):
        create_backend("glm-5.3-flash", deepseek_config=deepseek_config())


def test_deepseek_cannot_borrow_glm_credentials():
    with pytest.raises(LLMConfigurationError):
        create_backend("deepseek-flash", glm_config=glm_config())


@pytest.mark.parametrize("provider", ["glm-5.3-flash", "deepseek-flash"])
def test_ambiguous_configs_are_rejected(provider):
    with pytest.raises(LLMConfigurationError):
        create_backend(provider, glm_config=glm_config(), deepseek_config=deepseek_config())


def test_deepseek_selected_model_must_match():
    value = LLMBackendConfig(model="other", base_url="https://provider.invalid", api_key="synthetic")
    with pytest.raises(LLMConfigurationError):
        create_backend("deepseek-flash", deepseek_config=value)
