"""Three explicit non-scored GLM checks; caller holds the key in memory only.

No credential/environment reads, files, raw HTTP documents, reasoning text or
credential fingerprints are written by this runner. Billing/package deduction
is not a technical readiness gate. The returned receipt describes these three
small checks only; it starts no scored campaign, held-out evaluation or Runtime.
"""

from __future__ import annotations

import copy
import json
import math
import time
from typing import Any, Callable, Mapping

from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.glm_preflight_001 import GLMChatConfig, create_backend
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse, LLMConfigurationError

BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
MODEL = "glm-5.3-flash"
SOURCE = "请先站立三秒，然后停止。"
EXPECTED_PLAN = [["stand", 3.0], ["stop"]]
CHECKS = ("ordinary_text", "json_object", "typed_certificate")
_CATEGORIES = {"SCHEMA", "HTTP", "TIMEOUT", "TRANSPORT", "TLS", "INPUT", "OUTPUT"}
_ERROR_REASONS = {
    "HTTP_STATUS", "TIMEOUT", "NETWORK_ERROR", "TLS_CERTIFICATE_ERROR",
    "UNEXPECTED_TRANSPORT_FAILURE", "RESPONSE_TOO_LARGE", "INVALID_RESPONSE_JSON",
    "INVALID_RESPONSE_OBJECT", "MISSING_MODEL", "MODEL_MISMATCH", "INVALID_CHOICES",
    "INVALID_CHOICE_INDEX", "MISSING_OR_UNSUPPORTED_FINISH_REASON", "INVALID_ASSISTANT_MESSAGE",
    "TOOL_CALL_RESPONSE", "INVALID_REASONING_FIELD", "INVALID_USAGE", "INVALID_USAGE_DETAILS",
    "USAGE_ACCOUNTING_MISMATCH", "USAGE_DETAILS_OUT_OF_BOUNDS", "NO_FINAL_ASSISTANT_CONTENT",
    "CREDENTIAL_ECHO", "INVALID_INPUT", "RETRY_EXHAUSTED", "OBSERVER_REUSED",
    "INVALID_BACKEND_RESPONSE",
}


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_usage(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    value: dict[str, Any] = {
        key: raw.get(key) if _int(raw.get(key)) else None
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    for outer, inner in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
        part = raw.get(outer)
        if isinstance(part, Mapping) and _int(part.get(inner)):
            value[outer] = {inner: part[inner]}
    return value if any(item is not None for item in value.values()) else None


def _safe_error(error: Exception, api_key: str) -> dict[str, Any]:
    if isinstance(error, LLMBackendError):
        context = error.context
        category = context.get("category")
        reason = context.get("reason")
        result = {"failure_type": error.failure_type if error.failure_type in {"API_ERROR", "TIMEOUT"} else "API_ERROR",
                  "category": category if isinstance(category, str) and category in _CATEGORIES else "TRANSPORT",
                  "reason": reason if isinstance(reason, str) and reason in _ERROR_REASONS and api_key not in reason else "UNCLASSIFIED",
                  "attempts": error.attempts if _int(error.attempts) else None,
                  "usage": _safe_usage(context.get("usage"))}
        if _int(context.get("http_status")) and 100 <= context["http_status"] <= 599:
            result["http_status"] = context["http_status"]
        if _int(context.get("reasoning_content_chars")):
            result["reasoning_content_chars"] = context["reasoning_content_chars"]
        return result
    return {"failure_type": "API_ERROR", "category": "CONFIGURATION" if isinstance(error, LLMConfigurationError) else "INTERNAL",
            "reason": "CONFIGURATION_INVALID" if isinstance(error, LLMConfigurationError) else "INTERNAL_FAILURE",
            "attempts": 0, "usage": None}


class _Observer:
    """One complete per stage; audit echoes before the certificate can hash text."""

    name = "glm_preflight_single_response_observer"
    model = MODEL

    def __init__(self, backend, api_key: str) -> None:
        self.backend = backend
        self.api_key = api_key
        self.calls = 0
        self.response: LLMBackendResponse | None = None
        self.error: Exception | None = None

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        if self.calls != 0:
            raise LLMBackendError("API_ERROR", "observer reused", context={"category": "INPUT", "reason": "OBSERVER_REUSED"})
        self.calls += 1
        try:
            response = self.backend.complete(system_prompt=system_prompt, user_text=user_text)
            if not isinstance(response, LLMBackendResponse) or not isinstance(response.text, str):
                raise LLMBackendError("API_ERROR", "invalid backend response", context={"category": "SCHEMA", "reason": "INVALID_BACKEND_RESPONSE"})
            if self.api_key in response.text:
                raise LLMBackendError("API_ERROR", "credential echo rejected", context={"category": "OUTPUT", "reason": "CREDENTIAL_ECHO"})
            self.response = response
            return response
        except Exception as error:
            self.error = error
            raise


def _response_receipt(response: LLMBackendResponse, *, json_mode: bool) -> dict[str, Any]:
    usage = _safe_usage(response.usage)
    metadata = response.request_parameters.get("adapter_response_metadata", {})
    reasoning_chars = metadata.get("reasoning_content_chars") if isinstance(metadata, Mapping) else None
    reasoning_present = metadata.get("reasoning_content_present") if isinstance(metadata, Mapping) else None
    # Only public expected request parameters enter the receipt. Provider or
    # caller-added arbitrary metadata is not copied across this boundary.
    parameters = {
        "model": MODEL, "wire_api": "chat_completions", "temperature": 0.0,
        "max_tokens": 4096, "stream": False, "thinking": {"type": "enabled"},
        "reasoning_effort": "provider_default_not_sent", "timeout_s": 60.0,
        "max_network_retries": 2, "retry_backoff_s": 0.5,
        "retry_statuses": [429, 500, 502, 503, 504],
    }
    if json_mode:
        parameters["response_format"] = {"type": "json_object"}
    return {
        "model": response.model if response.model == MODEL else "MODEL_MISMATCH",
        "finish_reason": response.finish_reason if response.finish_reason in {"stop", "length"} else "UNSUPPORTED",
        "provider_status": response.provider_status if response.provider_status in {"completed", "incomplete"} else "UNKNOWN",
        "request_parameters": parameters, "usage": usage,
        "latency_s": response.latency_s if isinstance(response.latency_s, (int, float)) and math.isfinite(response.latency_s) else None,
        "attempts": response.attempts if _int(response.attempts) else None,
        "final_text": response.text,
        "final_text_chars": len(response.text),
        "reasoning_content_present": reasoning_present if isinstance(reasoning_present, bool) else None,
        "reasoning_content_chars": reasoning_chars if _int(reasoning_chars) else None,
    }


def _complete(response: LLMBackendResponse, *, json_mode: bool) -> bool:
    usage = _safe_usage(response.usage)
    expected = {"wire_api": "chat_completions", "model": MODEL, "temperature": 0.0,
                "max_tokens": 4096, "stream": False, "thinking": {"type": "enabled"},
                "reasoning_effort": "provider_default_not_sent", "max_network_retries": 2,
                "retry_backoff_s": 0.5, "retry_statuses": [429, 500, 502, 503, 504]}
    if json_mode:
        expected["response_format"] = {"type": "json_object"}
    actual_parameters = response.request_parameters
    return bool(response.model == MODEL and response.finish_reason == "stop" and response.provider_status == "completed"
                and response.text.strip() and _int(response.attempts) and 1 <= response.attempts <= 3
                and isinstance(actual_parameters, Mapping)
                and all(actual_parameters.get(key) == value for key, value in expected.items())
                and usage and all(_int(usage.get(key)) for key in ("input_tokens", "output_tokens", "total_tokens"))
                and all(usage[key] > 0 for key in ("input_tokens", "output_tokens", "total_tokens"))
                and usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"])


def _json_object(text: str) -> bool:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value

    def constant(_):
        raise ValueError()

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        return (isinstance(value, dict) and set(value) == {"preflight", "value"}
                and value["preflight"] == MODEL and type(value["value"]) is int and value["value"] == 1)
    except (ValueError, TypeError, RecursionError):
        return False


def run_preflight(api_key: str, *, base_url: str = BASE_URL,
                  progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run at most three non-scored calls, stopping at the first failed check."""
    receipt: dict[str, Any] = {
        "schema": "glm_non_scored_live_preflight_v1", "provider_id": MODEL,
        "ready": False, "status": "NOT_READY", "non_scored": True,
        "scored_calls": 0, "runtime_calls": 0, "held_out_calls": 0,
        "raw_reasoning_persisted": False, "credential_or_credential_hash_persisted": False,
        "billing_deduction_claimed": False,
        "provider_calls": 0, "provider_attempts": 0,
        "checks": [{"name": name, "status": "NOT_RUN", "passed": False, "provider_calls": 0} for name in CHECKS],
    }
    try:
        if base_url != BASE_URL:
            raise LLMConfigurationError("official standard GLM Chat URL required")
        # No settings/credential discovery: every backend is built from this
        # exact caller-supplied key and this explicit route only.
        configurations = [GLMChatConfig(base_url, api_key, response_format_json_object=index > 0) for index in range(3)]
    except Exception as error:
        receipt["configuration_error"] = _safe_error(error, api_key if isinstance(api_key, str) else "")
        return receipt
    for index, name in enumerate(CHECKS):
        observer = _Observer(create_backend(MODEL, glm_config=configurations[index]), api_key)
        started = time.perf_counter()
        record: dict[str, Any] = {"name": name, "passed": False, "status": "FAIL", "provider_calls": 0}
        try:
            if name == "ordinary_text":
                response = observer.complete(system_prompt="Reply with exactly GLM_PREFLIGHT_OK. No other text.",
                                             user_text="Return the requested transport-check marker.")
                record["passed"] = _complete(response, json_mode=False) and response.text.strip() == "GLM_PREFLIGHT_OK"
            elif name == "json_object":
                response = observer.complete(system_prompt='Return exactly one JSON object: {"preflight":"glm-5.3-flash","value":1}. No markdown.',
                                             user_text="Return the requested JSON object.")
                record["passed"] = _complete(response, json_mode=True) and _json_object(response.text)
            else:
                outcome = SourceAuthorityCertificateIssuer(observer).issue_certificate(SOURCE)
                response = observer.response
                body = outcome.certificate.to_dict() if outcome.certificate else None
                record["certificate"] = body
                record["certificate_usable"] = outcome.usable
                record["passed"] = bool(response and _complete(response, json_mode=True) and outcome.usable
                    and body == {"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7, "plan": EXPECTED_PLAN, "issues": []})
                if observer.error is not None:
                    record["error"] = _safe_error(observer.error, api_key)
            if observer.response is not None:
                record["response"] = _response_receipt(observer.response, json_mode=index > 0)
            record["status"] = "PASS" if record["passed"] else "FAIL"
            if not record["passed"] and "error" not in record:
                record["error"] = {"failure_type": "CHECK_FAILED", "category": "VALIDATION", "reason": "EXPECTED_TECHNICAL_CONTRACT_NOT_MET"}
        except Exception as error:
            record["error"] = _safe_error(error, api_key)
        record["provider_calls"] = observer.calls
        record["wall_latency_s"] = time.perf_counter() - started
        # Audit the actual key before any callback/returned artifact. No
        # credential-derived hash or other fingerprint is computed.
        if api_key in json.dumps(record, ensure_ascii=False, allow_nan=False):
            record = {"name": name, "passed": False, "status": "FAIL", "provider_calls": observer.calls,
                      "error": {"category": "OUTPUT", "reason": "CREDENTIAL_ECHO", "failure_type": "API_ERROR"}}
        receipt["checks"][index] = record
        if progress is not None:
            try:
                progress(copy.deepcopy(record))
            except Exception:
                receipt["callback_error"] = {"category": "CALLBACK", "reason": "CALLBACK_FAILED"}
                break
        if not record["passed"]:
            break
    completed = [record for record in receipt["checks"] if record["status"] != "NOT_RUN"]
    usages = [record.get("response", {}).get("usage") or record.get("error", {}).get("usage") for record in completed]
    attempts = [record.get("response", {}).get("attempts", record.get("error", {}).get("attempts")) for record in completed]
    known_attempts = all(_int(value) for value in attempts)
    receipt["provider_calls"] = sum(record["provider_calls"] for record in receipt["checks"])
    receipt["provider_attempts"] = sum(attempts) if known_attempts else None
    reports = sum(bool(usage and _int(usage.get("total_tokens"))) for usage in usages)
    unknown_attempt_usage = sum(max(value - int(bool(usage and _int(usage.get("total_tokens")))), 0)
                                for value, usage in zip(attempts, usages)) if known_attempts else None
    receipt["token_stats"] = {
        "reported_total_tokens": sum(usage["total_tokens"] for usage in usages if usage and _int(usage.get("total_tokens"))) if reports else None,
        "requests_with_reported_total": reports,
        "requests_without_reported_total": sum(not (usage and _int(usage.get("total_tokens"))) for usage in usages),
        "attempts_without_reported_usage": unknown_attempt_usage,
        "reported_usage_complete_for_all_attempts": unknown_attempt_usage == 0 if known_attempts else False,
    }
    receipt["reasoning_observation"] = "OBSERVED" if any(
        record.get("response", {}).get("reasoning_content_present") is True
        and (record["response"].get("reasoning_content_chars") or 0) > 0
        or (record.get("error", {}).get("reasoning_content_chars") or 0) > 0
        for record in completed) else "NOT_OBSERVED"
    receipt["reasoning_effort_policy"] = "omitted_provider_default_not_live_verified"
    receipt["ready"] = all(record["passed"] for record in receipt["checks"]) and "callback_error" not in receipt
    receipt["status"] = "READY" if receipt["ready"] else "NOT_READY"
    return receipt


__all__ = ["run_preflight"]
