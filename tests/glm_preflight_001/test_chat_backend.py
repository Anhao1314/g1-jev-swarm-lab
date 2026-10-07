"""Fully stubbed transport tests: no live API, account or network access."""

from __future__ import annotations

import copy
import io
import json
import socket
import ssl
import traceback
import urllib.error
import urllib.request
from dataclasses import FrozenInstanceError

import pytest

from g1swarm.glm_preflight_001 import GLMChatCompletionsBackend, GLMChatConfig
from g1swarm.glm_preflight_001.chat_backend import _NoRedirect
from g1swarm.llm.backend import LLMBackend, LLMBackendError, LLMConfigurationError

KEY = "SYNTHETIC_KEY_NEVER_A_REAL_CREDENTIAL_001"


def config(**changes):
    return GLMChatConfig("https://provider.invalid/api/v4", KEY, **changes)


def document(**changes):
    value = {"id": "fixture-chat-1", "model": "glm-5.3-flash", "choices": [{
        "index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": ' {"ok":true}\n',
            "reasoning_content": "private fixture reasoning"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130,
                  "prompt_tokens_details": {"cached_tokens": 25},
                  "completion_tokens_details": {"reasoning_tokens": 20}}}
    value.update(changes)
    return value


class _Response:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.raw[:limit]


def stub(monkeypatch, events):
    queue = list(events)
    calls = []
    sleeps = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append({"url": request.full_url, "payload": json.loads(request.data),
                          "headers": dict(request.header_items()), "timeout": timeout})
            event = queue.pop(0)
            if isinstance(event, BaseException):
                raise event
            raw = event if isinstance(event, bytes) else json.dumps(event).encode("utf8")
            return _Response(raw)

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], _NoRedirect)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    monkeypatch.setattr("g1swarm.glm_preflight_001.chat_backend.time.sleep", sleeps.append)
    return calls, sleeps


def test_request_contract_and_final_only_content(monkeypatch):
    calls, _ = stub(monkeypatch, [document()])
    backend = GLMChatCompletionsBackend(config(response_format_json_object=True))
    assert isinstance(backend, LLMBackend)
    response = backend.complete(system_prompt="system fixture", user_text="user fixture")
    assert response.text == ' {"ok":true}\n'
    assert "private fixture reasoning" not in repr(response)
    assert response.model == "glm-5.3-flash"
    assert response.finish_reason == "stop" and response.provider_status == "completed"
    assert response.attempts == 1
    sent = calls[0]
    assert sent["url"] == "https://provider.invalid/api/v4/chat/completions"
    assert sent["timeout"] == 60
    assert sent["payload"] == {"model": "glm-5.3-flash", "messages": [
        {"role": "system", "content": "system fixture"}, {"role": "user", "content": "user fixture"}],
        "temperature": 0.0, "max_tokens": 4096, "stream": False,
        "thinking": {"type": "enabled"}, "response_format": {"type": "json_object"}}
    assert "reasoning_effort" not in sent["payload"]
    assert "response_format" not in GLMChatCompletionsBackend(config())._payload("s", "u")
    assert response.request_parameters["adapter_response_metadata"]["reasoning_content_chars"] == len("private fixture reasoning")


def test_usage_normalization_and_whitelist(monkeypatch):
    doc = document()
    doc["usage"]["untrusted_extra"] = KEY
    doc["usage"]["prompt_tokens_details"]["arbitrary"] = KEY
    stub(monkeypatch, [doc])
    response = GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert response.usage == {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
                             "input_tokens_details": {"cached_tokens": 25},
                             "output_tokens_details": {"reasoning_tokens": 20}}
    assert KEY not in repr(response.usage)


def test_sparse_usage_does_not_infer_total_or_zero(monkeypatch):
    stub(monkeypatch, [document(usage={"prompt_tokens": 7, "completion_tokens": 9})])
    response = GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert response.usage == {"input_tokens": 7, "output_tokens": 9, "total_tokens": None}


@pytest.mark.parametrize("usage", [{"prompt_tokens": True}, {"completion_tokens": -1}, {"total_tokens": 1.5},
                                   {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 10},
                                   {"prompt_tokens": 2, "prompt_tokens_details": {"cached_tokens": 3}},
                                   {"completion_tokens": 2, "completion_tokens_details": {"reasoning_tokens": 3}},
                                   {"prompt_tokens_details": {"cached_tokens": False}}, "not usage"])
def test_bad_usage_is_typed_schema_failure_without_retry(monkeypatch, usage):
    calls, _ = stub(monkeypatch, [document(usage=usage)])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.context["category"] == "SCHEMA"
    assert len(calls) == 1 and not error.value.retryable


def test_length_with_final_text_is_incomplete_not_completed(monkeypatch):
    doc = document()
    doc["choices"][0]["finish_reason"] = "length"
    calls, _ = stub(monkeypatch, [doc])
    response = GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert response.provider_status == "incomplete" and response.finish_reason == "length"
    assert len(calls) == 1


def test_reasoning_only_is_first_output_failure_and_usage_is_retained(monkeypatch):
    doc = document()
    doc["choices"][0]["message"]["content"] = None
    doc["choices"][0]["finish_reason"] = "length"
    calls, sleeps = stub(monkeypatch, [doc])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.failure_type == "API_ERROR"
    assert error.value.context["reason"] == "NO_FINAL_ASSISTANT_CONTENT"
    assert error.value.context["usage"]["total_tokens"] == 130
    assert error.value.context["reasoning_content_chars"] > 0
    assert "private fixture reasoning" not in repr(error.value.context)
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("change", ["missing_model", "wrong_model", "missing_finish", "dict_finish", "list_finish",
                                    "tool_finish", "tool_calls", "multiple_choices", "empty_choices", "wrong_role",
                                    "empty_content", "content_list", "wrong_index", "reasoning_list"])
def test_bad_response_schema_is_typed_and_never_semantically_retried(monkeypatch, change):
    doc = document()
    choice = doc["choices"][0]
    message = choice["message"]
    if change == "missing_model":
        del doc["model"]
    elif change == "wrong_model":
        doc["model"] = "another-model"
    elif change == "missing_finish":
        del choice["finish_reason"]
    elif change == "dict_finish":
        choice["finish_reason"] = {}
    elif change == "list_finish":
        choice["finish_reason"] = []
    elif change == "tool_finish":
        choice["finish_reason"] = "tool_calls"
    elif change == "tool_calls":
        message["tool_calls"] = [{"function": {"name": "do_not_execute"}}]
    elif change == "multiple_choices":
        doc["choices"].append(copy.deepcopy(choice))
    elif change == "empty_choices":
        doc["choices"] = []
    elif change == "wrong_role":
        message["role"] = "tool"
    elif change == "empty_content":
        message["content"] = " "
    elif change == "content_list":
        message["content"] = [{"text": "do not repair"}]
    elif change == "wrong_index":
        choice["index"] = True
    else:
        message["reasoning_content"] = ["not text"]
    calls, sleeps = stub(monkeypatch, [doc])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert not error.value.retryable and error.value.attempts == 1
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"{\"model\":\"a\",\"model\":\"b\"}",
                                 b"{\"extra\":NaN}", b"{\"extra\":Infinity}", b"\xff"])
def test_wire_schema_failures_do_not_retry(monkeypatch, raw):
    calls, _ = stub(monkeypatch, [raw])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.context["category"] == "SCHEMA" and len(calls) == 1


def test_response_size_cap(monkeypatch):
    calls, _ = stub(monkeypatch, [b"x" * 11])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config(max_response_bytes=10)).complete(system_prompt="s", user_text="u")
    assert error.value.context["reason"] == "RESPONSE_TOO_LARGE" and len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_http_statuses_use_frozen_transport_schedule(monkeypatch, status):
    failures = [urllib.error.HTTPError("https://provider.invalid", status, "redacted", {}, io.BytesIO(b"secret body"))] * 2
    calls, sleeps = stub(monkeypatch, [*failures, document()])
    response = GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert response.attempts == 3 and len(calls) == 3 and sleeps == [0.5, 1.0]


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404])
def test_nonretryable_http_statuses_and_redirects_fail_once(monkeypatch, status):
    calls, sleeps = stub(monkeypatch, [urllib.error.HTTPError("https://provider.invalid", status, KEY,
                                                           {"Authorization": KEY}, io.BytesIO(KEY.encode()))])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.context["http_status"] == status
    assert len(calls) == 1 and sleeps == []
    assert KEY not in str(error.value) + repr(error.value.context)
    assert KEY not in "".join(traceback.format_exception(error.value))
    assert error.value.__suppress_context__


def test_redirect_handler_never_constructs_forwarded_authorization_request():
    request = urllib.request.Request("https://origin.invalid/chat/completions",
                                     headers={"Authorization": f"Bearer {KEY}"})
    with pytest.raises(urllib.error.HTTPError) as error:
        _NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://other.invalid")
    assert error.value.code == 302


@pytest.mark.parametrize("failure,kind", [(socket.timeout(KEY), "TIMEOUT"),
                                         (urllib.error.URLError(socket.timeout(KEY)), "TIMEOUT"),
                                         (urllib.error.URLError(OSError(KEY)), "API_ERROR"),
                                         (OSError(KEY), "API_ERROR")])
def test_timeout_network_classification_and_exhaustion_are_secret_safe(monkeypatch, failure, kind):
    calls, sleeps = stub(monkeypatch, [failure] * 3)
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.failure_type == kind and error.value.attempts == 3
    assert len(calls) == 3 and sleeps == [0.5, 1.0]
    assert KEY not in str(error.value) + repr(error.value.context)
    assert KEY not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("wrapped", [False, True])
def test_tls_certificate_failure_is_not_retried(monkeypatch, wrapped):
    failure = ssl.SSLCertVerificationError(KEY)
    if wrapped:
        failure = urllib.error.URLError(failure)
    calls, sleeps = stub(monkeypatch, [failure])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.context["category"] == "TLS"
    assert error.value.attempts == 1 and not error.value.retryable
    assert len(calls) == 1 and sleeps == []
    assert KEY not in str(error.value) + repr(error.value.context)


def test_successful_content_echo_of_credential_is_rejected(monkeypatch):
    doc = document()
    doc["choices"][0]["message"]["content"] = '{"echo":"' + KEY + '"}'
    calls, _ = stub(monkeypatch, [doc])
    with pytest.raises(LLMBackendError) as error:
        GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert error.value.context["reason"] == "CREDENTIAL_ECHO"
    assert KEY not in repr(error.value.context) + str(error.value) and len(calls) == 1


def test_response_id_credential_is_redacted(monkeypatch):
    stub(monkeypatch, [document(id=KEY)])
    response = GLMChatCompletionsBackend(config()).complete(system_prompt="s", user_text="u")
    assert response.response_id == "<REDACTED>"


def test_config_is_immutable_and_key_is_hidden():
    value = config()
    assert KEY not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.model = "another-model"


@pytest.mark.parametrize("changes", [{"model": "another-model"}, {"thinking_enabled": False},
                                     {"temperature": float("nan")}, {"temperature": -1},
                                     {"temperature": 10 ** 400},
                                     {"max_tokens": 0}, {"max_tokens": True}, {"timeout_s": 0},
                                     {"max_network_retries": -1}, {"retry_backoff_s": -1},
                                     {"retry_statuses": frozenset({401})}, {"response_format_json_object": "true"}])
def test_invalid_config_has_safe_typed_errors(changes):
    with pytest.raises(LLMConfigurationError) as error:
        config(**changes)
    assert KEY not in str(error.value)


@pytest.mark.parametrize("url", ["http://public.invalid", "https://name:password@provider.invalid", "https://provider.invalid?secret=x",
                                 "https://provider.invalid#secret", "https://open.bigmodel.cn/api/anthropic",
                                 "https://provider.invalid/chat/completions", " https://provider.invalid",
                                 "https://provider.invalid/\r\npath"])
def test_bad_or_wrong_protocol_base_urls_are_rejected(url):
    with pytest.raises(LLMConfigurationError):
        GLMChatConfig(url, KEY)


def test_credential_with_surrounding_space_is_rejected_without_echo():
    with pytest.raises(LLMConfigurationError) as error:
        GLMChatConfig("https://provider.invalid", " " + KEY + " ")
    assert KEY not in str(error.value)


def test_mock_typed_certificate_integration_is_fixture_not_live_smoke(monkeypatch):
    from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer

    source = "请先站立三秒，然后停止。"
    certificate = {"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
                   "plan": [["stand", 3], ["stop"]], "issues": []}
    doc = document()
    doc["choices"][0]["message"]["content"] = json.dumps(certificate, ensure_ascii=False)
    doc["choices"][0]["message"]["reasoning_content"] = "MOCK_REASONING_MUST_NOT_ENTER_CERTIFICATE"
    calls, _ = stub(monkeypatch, [doc])
    outcome = SourceAuthorityCertificateIssuer(GLMChatCompletionsBackend(config())).issue_certificate(source)
    assert outcome.usable
    assert outcome.certificate.to_dict()["plan"] == [["stand", 3.0], ["stop"]]
    assert outcome.certificate.to_dict() == certificate
    assert "MOCK_REASONING_MUST_NOT_ENTER_CERTIFICATE" not in outcome.diagnostics["raw_response"]
    assert json.loads(calls[0]["payload"]["messages"][1]["content"]) == {"source": source}
    assert len(calls) == 1
