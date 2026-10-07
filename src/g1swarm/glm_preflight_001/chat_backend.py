"""Independent GLM OpenAI Chat transport, compatible with frozen LLMBackend.

Credentials are supplied by the caller. This module reads no environment,
Claude/Codex settings or credential stores. It does not select an account,
validate subscription entitlement, disable TLS, parse mission certificates,
repair output, execute tools or fall back to another model/provider.

Only final message.content becomes response.text. Reasoning is measured as
presence/character count in request_parameters.adapter_response_metadata and
never mixed with final content. Chat stop/length maps explicitly to normalized
completed/incomplete status; native finish_reason remains intact. Optional
usage details preserve only integer cached/reasoning token counts. Raw HTTP
error bodies, headers and exception messages are never echoed.
"""

from __future__ import annotations

import ipaddress
import json
import math
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..llm.backend import (
    DEFAULT_RETRY_STATUSES,
    FAILURE_API_ERROR,
    FAILURE_TIMEOUT,
    LLMBackendError,
    LLMBackendResponse,
    LLMConfigurationError,
)

MODEL = "glm-5.3-flash"


def _number(value: Any, *, minimum: float, field_name: str) -> None:
    try:
        invalid = isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < minimum
    except (OverflowError, ValueError):
        invalid = True
    if invalid:
        raise LLMConfigurationError(f"invalid {field_name}")


def _integer(value: Any, *, minimum: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LLMConfigurationError(f"invalid {field_name}")


@dataclass(frozen=True)
class GLMChatConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str = MODEL
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 60.0
    max_network_retries: int = 2
    retry_backoff_s: float = 0.5
    retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES
    max_response_bytes: int = 1_048_576
    response_format_json_object: bool = False
    thinking_enabled: bool = True

    def __post_init__(self) -> None:
        if self.model != MODEL:
            raise LLMConfigurationError("GLM adapter requires glm-5.3-flash")
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or self.api_key != self.api_key.strip() or any(c in self.api_key for c in "\r\n")):
            raise LLMConfigurationError("explicit GLM credential is required")
        if not isinstance(self.base_url, str) or not self.base_url or any(c.isspace() for c in self.base_url):
            raise LLMConfigurationError("explicit GLM Chat base URL is required")
        try:
            url = urllib.parse.urlsplit(self.base_url)
            if (not url.hostname or url.username or url.password or url.query or url.fragment
                    or url.path.rstrip("/").endswith(("/anthropic", "/messages", "/responses", "/chat/completions"))):
                raise ValueError()
            if url.scheme != "https":
                if url.scheme != "http" or not (url.hostname == "localhost" or ipaddress.ip_address(url.hostname).is_loopback):
                    raise ValueError()
        except (ValueError, TypeError):
            raise LLMConfigurationError("Chat base URL must be HTTPS or HTTP loopback, with no credentials/query/fragment") from None
        _number(self.temperature, minimum=0, field_name="temperature")
        if self.temperature > 2:
            raise LLMConfigurationError("invalid temperature")
        _integer(self.max_tokens, minimum=1, field_name="max_tokens")
        _number(self.timeout_s, minimum=0, field_name="timeout_s")
        if self.timeout_s == 0:
            raise LLMConfigurationError("invalid timeout_s")
        _integer(self.max_network_retries, minimum=0, field_name="max_network_retries")
        _number(self.retry_backoff_s, minimum=0, field_name="retry_backoff_s")
        _integer(self.max_response_bytes, minimum=1, field_name="max_response_bytes")
        if not isinstance(self.retry_statuses, frozenset) or not self.retry_statuses <= DEFAULT_RETRY_STATUSES:
            raise LLMConfigurationError("invalid transport retry status set")
        if not isinstance(self.response_format_json_object, bool):
            raise LLMConfigurationError("response format option must be boolean")
        if self.thinking_enabled is not True:
            raise LLMConfigurationError("glm-5.3-flash requires enabled thinking")


def _error(reason: str, *, category: str = "SCHEMA", attempts: int = 1,
           failure_type: str = FAILURE_API_ERROR, retryable: bool = False,
           context: Mapping[str, Any] | None = None) -> LLMBackendError:
    return LLMBackendError(failure_type, f"GLM transport failed: {reason}", attempts=attempts,
                           retryable=retryable, context={"category": category, "reason": reason, **dict(context or {})})


def _usage(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _error("INVALID_USAGE")
    normalized: dict[str, Any] = {}
    for name, wire_name in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens")):
        value = raw.get(wire_name, raw.get(name))
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise _error("INVALID_USAGE")
        normalized[name] = value
    if all(normalized[name] is not None for name in ("input_tokens", "output_tokens", "total_tokens")):
        if normalized["total_tokens"] != normalized["input_tokens"] + normalized["output_tokens"]:
            raise _error("USAGE_ACCOUNTING_MISMATCH")
    for wire_name, name, allowed in (
        ("prompt_tokens_details", "input_tokens_details", {"cached_tokens"}),
        ("completion_tokens_details", "output_tokens_details", {"reasoning_tokens"}),
    ):
        details = raw.get(wire_name)
        if details is None:
            continue
        if not isinstance(details, dict):
            raise _error("INVALID_USAGE_DETAILS")
        kept = {}
        for key in allowed & set(details):
            value = details[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _error("INVALID_USAGE_DETAILS")
            kept[key] = value
        if kept:
            normalized[name] = kept
            primary = normalized["input_tokens" if name == "input_tokens_details" else "output_tokens"]
            if primary is not None and any(value > primary for value in kept.values()):
                raise _error("USAGE_DETAILS_OUT_OF_BOUNDS")
    return normalized if any(value is not None for value in normalized.values()) else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an authenticated request, including same-host redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", None, None)


def _wire_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate wire JSON key")
        result[key] = value
    return result


def _wire_constant(name):
    raise ValueError("nonfinite wire JSON constant")


class GLMChatCompletionsBackend:
    name = "glm_openai_chat"

    def __init__(self, config: GLMChatConfig) -> None:
        if not isinstance(config, GLMChatConfig):
            raise LLMConfigurationError("explicit GLMChatConfig is required")
        self.config = config
        self.model = config.model

    def request_parameters(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "wire_api": "chat_completions", "model": self.model,
            "temperature": self.config.temperature, "max_tokens": self.config.max_tokens,
            "stream": False, "thinking": {"type": "enabled"},
            "reasoning_effort": "provider_default_not_sent",
            "max_network_retries": self.config.max_network_retries,
            "retry_backoff_s": self.config.retry_backoff_s,
            "retry_statuses": sorted(self.config.retry_statuses),
        }
        if self.config.response_format_json_object:
            result["response_format"] = {"type": "json_object"}
        return result

    def _payload(self, system_prompt: str, user_text: str) -> dict[str, Any]:
        result = {"model": self.model, "messages": [
            {"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
            "temperature": self.config.temperature, "max_tokens": self.config.max_tokens,
            "stream": False, "thinking": {"type": "enabled"}}
        if self.config.response_format_json_object:
            result["response_format"] = {"type": "json_object"}
        return result

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        if not isinstance(system_prompt, str) or not isinstance(user_text, str):
            raise _error("INVALID_INPUT", category="INPUT", attempts=0)
        payload = self._payload(system_prompt, user_text)
        attempts = 0
        started = time.perf_counter()
        while attempts <= self.config.max_network_retries:
            attempts += 1
            try:
                document = self._post(payload)
            except LLMBackendError as exc:
                if exc.retryable and attempts <= self.config.max_network_retries:
                    time.sleep(min(self.config.retry_backoff_s * 2 ** (attempts - 1), 8.0))
                    continue
                raise LLMBackendError(exc.failure_type, exc.message, attempts=attempts,
                                      retryable=exc.retryable, context=exc.context) from None
            # All response interpretation errors are first-output failures and
            # therefore bypass the transport retry branch above.
            try:
                return self._response(document, attempts, time.perf_counter() - started)
            except LLMBackendError as exc:
                raise LLMBackendError(exc.failure_type, exc.message, attempts=attempts,
                                      retryable=False, context=exc.context) from None
        raise _error("RETRY_EXHAUSTED", category="TRANSPORT", attempts=attempts)

    def _post(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf8"), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=self.config.timeout_s) as response:
                raw = response.read(self.config.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raise _error("HTTP_STATUS", category="HTTP", retryable=status in self.config.retry_statuses,
                         context={"http_status": status}) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise _error("TLS_CERTIFICATE_ERROR", category="TLS") from None
            timeout = isinstance(exc.reason, (socket.timeout, TimeoutError))
            raise _error("TIMEOUT" if timeout else "NETWORK_ERROR", category="TIMEOUT" if timeout else "TRANSPORT",
                         failure_type=FAILURE_TIMEOUT if timeout else FAILURE_API_ERROR, retryable=True) from None
        except (socket.timeout, TimeoutError):
            raise _error("TIMEOUT", category="TIMEOUT", failure_type=FAILURE_TIMEOUT, retryable=True) from None
        except ssl.SSLCertVerificationError:
            raise _error("TLS_CERTIFICATE_ERROR", category="TLS") from None
        except OSError:
            raise _error("NETWORK_ERROR", category="TRANSPORT", retryable=True) from None
        except Exception:
            raise _error("UNEXPECTED_TRANSPORT_FAILURE", category="TRANSPORT") from None
        if len(raw) > self.config.max_response_bytes:
            raise _error("RESPONSE_TOO_LARGE")
        try:
            document = json.loads(raw.decode("utf8"), object_pairs_hook=_wire_pairs, parse_constant=_wire_constant)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _error("INVALID_RESPONSE_JSON") from None
        if not isinstance(document, dict):
            raise _error("INVALID_RESPONSE_OBJECT")
        return document

    def _response(self, document: Mapping[str, Any], attempts: int, latency: float) -> LLMBackendResponse:
        if not isinstance(document.get("model"), str) or not document["model"]:
            raise _error("MISSING_MODEL")
        if document["model"] != self.model:
            raise _error("MODEL_MISMATCH")
        choices = document.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise _error("INVALID_CHOICES")
        choice = choices[0]
        if type(choice.get("index")) is not int or choice["index"] != 0:
            raise _error("INVALID_CHOICE_INDEX")
        finish = choice.get("finish_reason")
        if not isinstance(finish, str) or finish not in {"stop", "length"}:
            raise _error("MISSING_OR_UNSUPPORTED_FINISH_REASON")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise _error("INVALID_ASSISTANT_MESSAGE")
        if message.get("tool_calls") or message.get("function_call"):
            raise _error("TOOL_CALL_RESPONSE")
        reasoning = message.get("reasoning_content")
        if reasoning is not None and not isinstance(reasoning, str):
            raise _error("INVALID_REASONING_FIELD")
        usage = _usage(document.get("usage"))
        metadata = {"reasoning_content_present": "reasoning_content" in message,
                    "reasoning_content_chars": len(reasoning) if isinstance(reasoning, str) else 0,
                    "normalized_status_basis": "Chat finish_reason stop/length"}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error("NO_FINAL_ASSISTANT_CONTENT", category="OUTPUT", context={
                "provider_status": "completed" if finish == "stop" else "incomplete",
                "finish_reason": finish, "usage": usage, **metadata})
        if self.config.api_key in content:
            raise _error("CREDENTIAL_ECHO", category="OUTPUT")
        parameters = self.request_parameters()
        parameters["adapter_response_metadata"] = metadata
        response_id = document.get("id") if isinstance(document.get("id"), str) else None
        if response_id and self.config.api_key in response_id:
            response_id = "<REDACTED>"
        return LLMBackendResponse(content, self.model, latency, attempts, parameters, usage, response_id,
                                  finish, "completed" if finish == "stop" else "incomplete")


ChatCompletionsBackend = GLMChatCompletionsBackend

__all__ = ["ChatCompletionsBackend", "GLMChatCompletionsBackend", "GLMChatConfig"]
