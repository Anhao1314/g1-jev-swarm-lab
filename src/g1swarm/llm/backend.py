"""OpenAI-compatible Responses API backend for the Phase 2.2 LLM compiler.

A backend is a transport only: it sends the frozen system prompt plus one
utterance and returns raw model text. It never parses, repairs or executes
model output.

Retry policy is frozen in ``configs/experiments/llm_compiler_001.yaml``: only
transport failures are retried (HTTP 429/500/502/503/504, network errors and
timeouts) with a bounded number of attempts and exponential backoff. Model
output is never retried here, and Phase 2.2 has no output repair loop.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_API_KEY_ENVS = ("LLM_COMPILER_API_KEY", "OPENAI_API_KEY")
DEFAULT_BASE_URL_ENV = "LLM_COMPILER_BASE_URL"
DEFAULT_RESPONSES_PATH = "/responses"
MAX_BACKOFF_S = 8.0

# Scoring failure taxonomy shared with g1swarm.llm.scoring.
FAILURE_API_ERROR = "API_ERROR"
FAILURE_TIMEOUT = "TIMEOUT"


class LLMConfigurationError(RuntimeError):
    """The backend cannot be configured from the environment/protocol."""


class LLMBackendError(RuntimeError):
    """Typed transport failure carrying a scoring ``failure_type``."""

    def __init__(
        self,
        failure_type: str,
        message: str,
        *,
        attempts: int = 1,
        retryable: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.message = message
        self.attempts = int(attempts)
        self.retryable = bool(retryable)
        self.context = dict(context or {})


@dataclass(frozen=True)
class LLMBackendConfig:
    """Resolved provider configuration (never logged, never persisted)."""

    model: str
    base_url: str
    api_key: str
    temperature: float = 0.0
    max_output_tokens: int = 768
    timeout_s: float = 60.0
    max_network_retries: int = 2
    retry_backoff_s: float = 0.5
    retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES
    responses_path: str = DEFAULT_RESPONSES_PATH
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    @classmethod
    def from_env(
        cls,
        *,
        model: str,
        temperature: float = 0.0,
        max_output_tokens: int = 768,
        timeout_s: float = 60.0,
        max_network_retries: int = 2,
        retry_backoff_s: float = 0.5,
        base_url_env: str = DEFAULT_BASE_URL_ENV,
        api_key_envs: Sequence[str] = DEFAULT_API_KEY_ENVS,
        environ: Mapping[str, str] | None = None,
        base_url: str | None = None,
        responses_path: str = DEFAULT_RESPONSES_PATH,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> "LLMBackendConfig":
        source = os.environ if environ is None else environ
        if not model:
            raise LLMConfigurationError("provider model is empty")
        if base_url is None:
            base_url = str(source.get(base_url_env, "")).strip()
        else:
            base_url = str(base_url).strip()
        if not base_url:
            raise LLMConfigurationError(
                f"environment variable {base_url_env} is not set; "
                "set it to the OpenAI-compatible Responses API base URL"
            )
        if not _is_trusted_base_url(base_url):
            raise LLMConfigurationError(
                "provider base URL must be https:// or a loopback/private-network "
                "http:// endpoint so the API key is never sent in clear text to "
                "an untrusted host"
            )
        api_key = ""
        for name in api_key_envs:
            value = str(source.get(name, "")).strip()
            if value:
                api_key = value
                break
        if not api_key:
            raise LLMConfigurationError(
                "no API key configured; set one of: "
                + ", ".join(str(name) for name in api_key_envs)
            )
        if temperature < 0.0:
            raise LLMConfigurationError("temperature must be >= 0")
        if int(max_output_tokens) <= 0:
            raise LLMConfigurationError("max_output_tokens must be positive")
        if float(timeout_s) <= 0.0:
            raise LLMConfigurationError("timeout_s must be positive")
        if int(max_network_retries) < 0:
            raise LLMConfigurationError("max_network_retries must be >= 0")
        if float(retry_backoff_s) < 0.0:
            raise LLMConfigurationError("retry_backoff_s must be >= 0")
        return cls(
            model=str(model),
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            temperature=float(temperature),
            max_output_tokens=int(max_output_tokens),
            timeout_s=float(timeout_s),
            max_network_retries=int(max_network_retries),
            retry_backoff_s=float(retry_backoff_s),
            responses_path=responses_path,
            max_response_bytes=int(max_response_bytes),
        )


@dataclass(frozen=True)
class LLMBackendResponse:
    text: str
    model: str
    latency_s: float
    attempts: int
    request_parameters: Mapping[str, Any]
    usage: Mapping[str, Any] | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    provider_status: str | None = None


@runtime_checkable
class LLMBackend(Protocol):
    name: str
    model: str

    def complete(
        self, *, system_prompt: str, user_text: str
    ) -> LLMBackendResponse:  # pragma: no cover - protocol
        ...


class DeepSeekResponsesBackend:
    """Single-prompt client for an OpenAI-compatible ``/responses`` endpoint."""

    name = "openai_compatible_responses"

    def __init__(self, config: LLMBackendConfig) -> None:
        self.config = config
        self.model = config.model

    def _payload(self, system_prompt: str, user_text: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_output_tokens,
            "stream": False,
        }

    def request_parameters(self) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_output_tokens,
            "max_network_retries": self.config.max_network_retries,
            "retry_backoff_s": self.config.retry_backoff_s,
            "stream": False,
        }

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        payload = self._payload(system_prompt, user_text)
        attempts = 0
        while attempts <= self.config.max_network_retries:
            attempts += 1
            try:
                document, latency_s = self._post(payload)
            except LLMBackendError as exc:
                if exc.retryable and attempts <= self.config.max_network_retries:
                    self._sleep(attempts)
                    continue
                raise LLMBackendError(
                    exc.failure_type,
                    exc.message,
                    attempts=attempts,
                    retryable=exc.retryable,
                    context=exc.context,
                ) from None
            text = _extract_output_text(document)
            if not text:
                raise LLMBackendError(
                    FAILURE_API_ERROR,
                    "provider response contained no assistant text",
                    attempts=attempts,
                    context={"response_id": document.get("id")},
                )
            return LLMBackendResponse(
                text=text,
                model=str(document.get("model", self.config.model)),
                latency_s=latency_s,
                attempts=attempts,
                request_parameters=self.request_parameters(),
                usage=_normalize_usage(document.get("usage")),
                response_id=document.get("id") if isinstance(document.get("id"), str) else None,
                finish_reason=_finish_reason(document),
                provider_status=(
                    document.get("status")
                    if isinstance(document.get("status"), str)
                    else None
                ),
            )
        raise LLMBackendError(  # pragma: no cover - defensive
            FAILURE_API_ERROR,
            "backend exhausted its retry budget without a response",
            attempts=attempts,
        )

    # ------------------------------------------------------------------
    def _post(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
        url = f"{self.config.base_url}{self.config.responses_path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "g1-jev-swarm-lab/phase2.2",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                raw = response.read(self.config.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            detail = _read_error_body(exc)
            retryable = status in self.config.retry_statuses
            raise LLMBackendError(
                FAILURE_API_ERROR,
                f"provider returned HTTP {status}: {detail}",
                retryable=retryable,
                context={"http_status": status},
            ) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise LLMBackendError(
                    FAILURE_TIMEOUT,
                    f"provider call exceeded {self.config.timeout_s:.3f}s",
                    retryable=True,
                ) from None
            raise LLMBackendError(
                FAILURE_API_ERROR,
                f"provider connection failed: {type(exc.reason).__name__}",
                retryable=True,
            ) from None
        except (TimeoutError, socket.timeout):
            raise LLMBackendError(
                FAILURE_TIMEOUT,
                f"provider call exceeded {self.config.timeout_s:.3f}s",
                retryable=True,
            ) from None
        except OSError as exc:
            raise LLMBackendError(
                FAILURE_API_ERROR,
                f"provider transport error: {type(exc).__name__}",
                retryable=True,
            ) from None
        latency_s = time.perf_counter() - started

        if len(raw) > self.config.max_response_bytes:
            raise LLMBackendError(
                FAILURE_API_ERROR,
                f"provider response exceeded {self.config.max_response_bytes} bytes",
                retryable=False,
            )
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LLMBackendError(
                FAILURE_API_ERROR,
                "provider response is not valid UTF-8 JSON",
                retryable=False,
            ) from None
        if not isinstance(document, dict):
            raise LLMBackendError(
                FAILURE_API_ERROR,
                "provider response is not a JSON object",
                retryable=False,
            )
        return document, latency_s

    def _sleep(self, attempt: int) -> None:
        delay = min(self.config.retry_backoff_s * (2 ** (attempt - 1)), MAX_BACKOFF_S)
        if delay > 0:
            time.sleep(delay)


class ScriptedBackend:
    """Deterministic test double; never used by a real campaign."""

    name = "scripted"

    def __init__(
        self,
        responses: Mapping[str, str] | Callable[..., str],
        *,
        model: str = "scripted",
    ) -> None:
        self._responses = responses
        self.model = model
        self.requests: list[dict[str, str]] = []

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        self.requests.append({"system_prompt": system_prompt, "user_text": user_text})
        started = time.perf_counter()
        if callable(self._responses):
            text = self._responses(system_prompt=system_prompt, user_text=user_text)
        else:
            try:
                text = self._responses[user_text]
            except KeyError:
                raise LLMConfigurationError(
                    "no scripted response for the given utterance"
                ) from None
        return LLMBackendResponse(
            text=str(text),
            model=self.model,
            latency_s=time.perf_counter() - started,
            attempts=1,
            request_parameters={"model": self.model},
        )


def _extract_output_text(document: Mapping[str, Any]) -> str:
    pieces: list[str] = []
    output = document.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") in {"output_text", "text"} and isinstance(
                    part.get("text"), str
                ):
                    pieces.append(part["text"])
    if pieces:
        return "".join(pieces).strip()
    top_level = document.get("output_text")
    if isinstance(top_level, str) and top_level.strip():
        return top_level.strip()
    # Tolerate chat-completions-shaped providers behind the same base URL.
    choices = document.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _normalize_usage(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    usage = {
        "input_tokens": raw.get("input_tokens", raw.get("prompt_tokens")),
        "output_tokens": raw.get("output_tokens", raw.get("completion_tokens")),
        "total_tokens": raw.get("total_tokens"),
    }
    return usage if any(value is not None for value in usage.values()) else None


def _finish_reason(document: Mapping[str, Any]) -> str | None:
    incomplete = document.get("incomplete_details")
    if isinstance(incomplete, Mapping) and isinstance(incomplete.get("reason"), str):
        return incomplete["reason"]
    choices = document.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        reason = choices[0].get("finish_reason")
        if isinstance(reason, str):
            return reason
    status = document.get("status")
    return status if isinstance(status, str) else None


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(1024)
    except Exception:  # pragma: no cover - defensive
        return "<unreadable>"
    text = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
    return text[:400] if text else "<empty>"


def _is_trusted_base_url(base_url: str) -> bool:
    """https anywhere; http only for loopback or private-network endpoints."""

    lowered = base_url.strip().lower()
    if lowered.startswith("https://"):
        return True
    if not lowered.startswith("http://"):
        return False
    host = lowered[len("http://") :].split("/", 1)[0].split(":", 1)[0]
    if host in {"localhost", "[::1]", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local
