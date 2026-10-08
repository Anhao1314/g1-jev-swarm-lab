"""Tests for the Phase 2.2 Responses-API backend (transport only)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from g1swarm.llm.backend import (
    DeepSeekResponsesBackend,
    LLMBackendConfig,
    LLMBackendError,
    LLMConfigurationError,
    ScriptedBackend,
)

_ENVELOPE_TEXT = json.dumps(
    {"status": "MALFORMED", "mission": None, "error_code": "LANGUAGE_PARSE_ERROR"}
)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append(
            {"path": self.path, "headers": dict(self.headers), "json": body}
        )
        self.server.calls += 1
        if self.server.behavior == "timeout":
            time.sleep(0.4)
        if self.server.remaining_failures > 0:
            self.server.remaining_failures -= 1
            payload = json.dumps({"error": {"message": "temporary"}}).encode("utf-8")
            self.send_response(self.server.failure_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.server.behavior == "bad_json":
            payload = b"<html>not json</html>"
        elif self.server.behavior == "chat_shape":
            payload = json.dumps(
                {
                    "id": "chat-1",
                    "model": "compat-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": _ENVELOPE_TEXT},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                }
            ).encode("utf-8")
        else:
            payload = json.dumps(
                {
                    "id": "resp-1",
                    "model": "deepseek-flash",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": _ENVELOPE_TEXT}],
                        }
                    ],
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 24,
                        "total_tokens": 144,
                    },
                }
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # silence test server logs
        return


@pytest.fixture()
def provider_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.calls = 0
    server.behavior = "ok"
    server.remaining_failures = 0
    server.failure_status = 500
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _config(server: ThreadingHTTPServer, **overrides) -> LLMBackendConfig:
    host, port = server.server_address[:2]
    values = {
        "model": "deepseek-flash",
        "base_url": f"http://127.0.0.1:{port}/v1",
        "api_key": "secret-key",
        "temperature": 0.0,
        "max_output_tokens": 768,
        "timeout_s": 5.0,
        "max_network_retries": 2,
        "retry_backoff_s": 0.0,
        "responses_path": "/responses",
    }
    values.update(overrides)
    return LLMBackendConfig(**values)


def test_config_from_env_reads_base_url_and_key() -> None:
    config = LLMBackendConfig.from_env(
        model="deepseek-flash",
        temperature=0.0,
        max_output_tokens=768,
        timeout_s=60.0,
        max_network_retries=2,
        retry_backoff_s=0.5,
        environ={
            "LLM_COMPILER_BASE_URL": "https://llm.example.com/v1",
            "LLM_COMPILER_API_KEY": "k-1",
        },
    )
    assert config.base_url == "https://llm.example.com/v1"
    assert config.api_key == "k-1"
    assert config.max_network_retries == 2


def test_config_from_env_falls_back_to_openai_api_key() -> None:
    config = LLMBackendConfig.from_env(
        model="m",
        environ={
            "LLM_COMPILER_BASE_URL": "https://llm.example.com/v1",
            "OPENAI_API_KEY": "k-2",
        },
    )
    assert config.api_key == "k-2"


def test_config_from_env_requires_base_url_and_key() -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_COMPILER_BASE_URL"):
        LLMBackendConfig.from_env(model="m", environ={})
    with pytest.raises(LLMConfigurationError, match="no API key"):
        LLMBackendConfig.from_env(
            model="m", environ={"LLM_COMPILER_BASE_URL": "https://llm.example.com/v1"}
        )


def test_config_rejects_untrusted_plain_http_host() -> None:
    with pytest.raises(LLMConfigurationError, match="https://"):
        LLMBackendConfig.from_env(
            model="m",
            environ={
                "LLM_COMPILER_BASE_URL": "http://evil.example.com/v1",
                "LLM_COMPILER_API_KEY": "k",
            },
        )


def test_complete_posts_responses_payload_and_extracts_text(provider_server) -> None:
    backend = DeepSeekResponsesBackend(_config(provider_server))
    response = backend.complete(system_prompt="SYSTEM PROMPT", user_text="前进4米")
    assert response.text == _ENVELOPE_TEXT
    assert response.model == "deepseek-flash"
    assert response.attempts == 1
    assert response.usage == {"input_tokens": 120, "output_tokens": 24, "total_tokens": 144}
    assert response.response_id == "resp-1"
    sent = provider_server.requests[0]
    assert sent["path"] == "/v1/responses"
    assert sent["json"]["model"] == "deepseek-flash"
    assert sent["json"]["temperature"] == 0.0
    assert sent["json"]["max_output_tokens"] == 768
    assert sent["json"]["stream"] is False
    assert [item["role"] for item in sent["json"]["input"]] == ["system", "user"]
    assert sent["json"]["input"][0]["content"] == "SYSTEM PROMPT"
    assert sent["json"]["input"][1]["content"] == "前进4米"
    assert sent["headers"]["Authorization"] == "Bearer secret-key"


def test_complete_retries_retryable_statuses_only(provider_server) -> None:
    provider_server.remaining_failures = 2
    backend = DeepSeekResponsesBackend(_config(provider_server, max_network_retries=2))
    response = backend.complete(system_prompt="s", user_text="u")
    assert response.attempts == 3
    assert provider_server.calls == 3


def test_complete_does_not_retry_client_errors(provider_server) -> None:
    provider_server.remaining_failures = 1
    provider_server.failure_status = 400
    backend = DeepSeekResponsesBackend(_config(provider_server, max_network_retries=2))
    with pytest.raises(LLMBackendError) as info:
        backend.complete(system_prompt="s", user_text="u")
    assert info.value.failure_type == "API_ERROR"
    assert info.value.retryable is False
    assert info.value.attempts == 1
    assert provider_server.calls == 1


def test_complete_exhausts_retry_budget_then_raises(provider_server) -> None:
    provider_server.remaining_failures = 99
    backend = DeepSeekResponsesBackend(_config(provider_server, max_network_retries=1))
    with pytest.raises(LLMBackendError) as info:
        backend.complete(system_prompt="s", user_text="u")
    assert info.value.attempts == 2
    assert info.value.context["http_status"] == 500


def test_complete_maps_timeout(provider_server) -> None:
    provider_server.behavior = "timeout"
    backend = DeepSeekResponsesBackend(
        _config(provider_server, timeout_s=0.1, max_network_retries=0)
    )
    with pytest.raises(LLMBackendError) as info:
        backend.complete(system_prompt="s", user_text="u")
    assert info.value.failure_type == "TIMEOUT"
    assert info.value.retryable is True


def test_complete_rejects_non_json_provider_payload(provider_server) -> None:
    provider_server.behavior = "bad_json"
    backend = DeepSeekResponsesBackend(_config(provider_server))
    with pytest.raises(LLMBackendError) as info:
        backend.complete(system_prompt="s", user_text="u")
    assert info.value.failure_type == "API_ERROR"
    assert info.value.retryable is False


def test_complete_tolerates_chat_completions_shape(provider_server) -> None:
    provider_server.behavior = "chat_shape"
    backend = DeepSeekResponsesBackend(_config(provider_server))
    response = backend.complete(system_prompt="s", user_text="u")
    assert response.text == _ENVELOPE_TEXT
    assert response.model == "compat-model"


def test_scripted_backend_records_requests() -> None:
    backend = ScriptedBackend({"前进4米": _ENVELOPE_TEXT})
    response = backend.complete(system_prompt="S", user_text="前进4米")
    assert response.text == _ENVELOPE_TEXT
    assert backend.requests == [{"system_prompt": "S", "user_text": "前进4米"}]
    with pytest.raises(LLMConfigurationError):
        backend.complete(system_prompt="S", user_text="未知")
