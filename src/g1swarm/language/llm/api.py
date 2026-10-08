"""Runner-facing Phase 2.2 bridge over the g1swarm.llm core stack.

``scripts/run_llm_compiler.py`` and the frozen Phase 2.2 protocol speak a small
adapter API: a provider backend configured from the protocol, a fail-closed
``LLMMissionCompiler``, recorded-response replay, and a campaign runner that
emits raw records plus a diagnostic summary.

All parsing, validation and failure taxonomy live in the core stack
(``g1swarm.llm.backend`` / ``g1swarm.llm.parsing`` / ``g1swarm.llm.compiler``).
This module only adapts signatures and record bookkeeping, so the repository
has exactly one LLM implementation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from ...llm.backend import (
    FAILURE_API_ERROR,
    FAILURE_TIMEOUT,
    DeepSeekResponsesBackend,
    LLMBackendConfig,
    LLMBackendError,
    LLMBackendResponse,
    LLMConfigurationError,
)
from ...llm.compiler import LLMMissionCompiler as CoreLLMMissionCompiler
from ..benchmark import evaluate_compiler_sample, summarize_compiler_results
from ..errors import LanguageErrorCode

COMPILER_VERSION = "2.2.0"
RECORD_SCHEMA_VERSION = "2.2.0"
CAMPAIGN_SCHEMA_VERSION = "2.2.0"
DEFAULT_MAX_INPUT_CHARS = 512
DEFAULT_MAX_OUTPUT_CHARS = 16384
FROZEN_SKILLS = ("stand", "walk_forward", "turn", "stop")
PLUMBING_BACKENDS = frozenset({"scripted", "oracle_plumbing"})


class BackendError(LLMBackendError):
    """Runner-facing transport error (``message``, ``reason`` and language code)."""

    def __init__(
        self, code: LanguageErrorCode, message: str, *, reason: str = "backend_error"
    ) -> None:
        failure_type = (
            FAILURE_TIMEOUT if code is LanguageErrorCode.LLM_TIMEOUT else FAILURE_API_ERROR
        )
        super().__init__(
            failure_type,
            message,
            attempts=1,
            retryable=False,
            context={"language_error_code": code.value, "reason": reason},
        )
        self.code = code
        self.reason = reason


class OpenAICompatibleBackend:
    """Protocol-configured Responses-API backend (class name kept for the runner)."""

    name = "openai_compatible"

    def __init__(self, config: LLMBackendConfig, *, provider: str = "openai-compatible") -> None:
        self.config = config
        self.provider = provider
        self.model = config.model
        self._core = DeepSeekResponsesBackend(config)

    @classmethod
    def from_env(
        cls,
        *,
        model: str,
        base_url: str,
        api_key_env: str,
        provider: str = "openai-compatible",
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        max_output_tokens: int = 768,
        max_network_retries: int = 2,
        retry_backoff_s: float = 0.5,
        environ: Mapping[str, str] | None = None,
    ) -> "OpenAICompatibleBackend":
        try:
            config = LLMBackendConfig.from_env(
                model=model,
                base_url=base_url,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
                max_network_retries=max_network_retries,
                retry_backoff_s=retry_backoff_s,
                api_key_envs=(str(api_key_env),),
                environ=environ,
            )
        except LLMConfigurationError as exc:
            raise BackendError(
                LanguageErrorCode.LLM_CONFIGURATION_ERROR,
                str(exc),
                reason="configuration",
            ) from None
        return cls(config, provider=provider)

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        return self._core.complete(system_prompt=system_prompt, user_text=user_text)


class ReplayBackend:
    """Deterministic replay of records produced by ``run_llm_campaign``."""

    name = "replay"

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records: dict[str, Mapping[str, Any]] = {}
        for record in records:
            key = record.get("request_key")
            if not isinstance(key, str) or not key:
                utterance = str(record.get("utterance", ""))
                key = _sha256_text(utterance)
            if key in self._records:
                raise ValueError(f"duplicate response record for request_key {key}")
            if not isinstance(record.get("response_text"), str):
                raise ValueError(f"response record {key} has no response_text")
            self._records[key] = dict(record)
        models = {str(record.get("model", "unknown")) for record in self._records.values()}
        self.model = models.pop() if len(models) == 1 else "mixed"

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        key = _sha256_text(user_text)
        record = self._records.get(key)
        if record is None:
            raise LLMConfigurationError(
                "no recorded response for the given utterance (replay miss)"
            )
        recorded_prompt = record.get("prompt_sha256")
        if recorded_prompt is not None and recorded_prompt != _sha256_text(system_prompt):
            raise LLMConfigurationError(
                "recorded response was produced with a different system prompt"
            )
        return LLMBackendResponse(
            text=str(record["response_text"]),
            model=str(record.get("model", self.model)),
            latency_s=float(record.get("latency_s") or 0.0),
            attempts=1,
            request_parameters={},
            usage=record.get("usage") if isinstance(record.get("usage"), Mapping) else None,
            response_id=record.get("request_id"),
            finish_reason=record.get("finish_reason"),
        )


class LLMMissionCompiler(CoreLLMMissionCompiler):
    """Protocol-shaped constructor used by the Phase 2.2 runner."""

    def __init__(
        self,
        backend,
        *,
        prompt_path: str | Path,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        expected_prompt_sha256: str | None = None,
        protocol: Mapping[str, Any] | None = None,
        validator=None,
    ) -> None:
        document = dict(protocol or {})
        compiler_config = dict(document.get("compiler", {}))
        compiler_config.setdefault("max_input_chars", int(max_input_chars))
        compiler_config.setdefault("max_output_chars", int(max_output_chars))
        compiler_config.setdefault("json_only", True)
        compiler_config.setdefault("automatic_repair", False)
        compiler_config.setdefault("allowed_skills", list(FROZEN_SKILLS))
        document["compiler"] = compiler_config
        if expected_prompt_sha256:
            prompt_config = dict(document.get("prompt", {}))
            prompt_config.setdefault("sha256", str(expected_prompt_sha256))
            document["prompt"] = prompt_config
        super().__init__(
            backend=backend,
            prompt_path=prompt_path,
            protocol=document,
            validator=validator,
        )


@dataclass(frozen=True)
class LLMCampaignRun:
    results: list[dict[str, Any]]
    summary: dict[str, Any]
    records: list[dict[str, Any]]


class _RecordingCompiler:
    """Caches compile() per utterance so each sample hits the backend once."""

    def __init__(self, compiler) -> None:
        self._compiler = compiler
        self._results: dict[str, Any] = {}

    def compile(self, text: str):
        key = str(text)
        if key not in self._results:
            self._results[key] = self._compiler.compile(key)
        return self._results[key]

    def result_for(self, text: str):
        return self._results.get(str(text))


def _build_record(
    sample: Mapping[str, Any], result, *, backend_kind: str, max_recorded_chars: int
) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics)
    raw = str(diagnostics.get("raw_response") or "")
    truncated = len(raw) > max_recorded_chars
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "sample_id": sample.get("sample_id"),
        "utterance": sample.get("utterance"),
        "request_key": _sha256_text(str(sample.get("utterance", ""))),
        "prompt_sha256": diagnostics.get("prompt_sha256"),
        "backend": backend_kind,
        "backend_kind": backend_kind,
        "model": diagnostics.get("model"),
        "latency_s": diagnostics.get("latency_s"),
        "finish_reason": diagnostics.get("provider_status"),
        "usage": diagnostics.get("usage"),
        "request_id": diagnostics.get("response_id"),
        "response_chars": len(raw),
        "response_sha256": _sha256_text(raw),
        "response_truncated": truncated,
        "response_text": raw[:max_recorded_chars],
        "parsed_result": {
            "status": result.status.value,
            "mission": result.mission.to_dict() if result.mission is not None else None,
            "error_code": result.error_code.value if result.error_code is not None else None,
        },
        "failure_type": diagnostics.get("failure_type"),
    }


def run_llm_campaign(
    *,
    compiler,
    samples: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
    corpus: Any,
    corpus_path: str | Path,
    campaign: str,
    backend_kind: str,
    record_raw: bool = True,
) -> LLMCampaignRun:
    recording = _RecordingCompiler(compiler)
    sample_list = [dict(sample) for sample in samples]
    results = [evaluate_compiler_sample(sample, recording) for sample in sample_list]
    diagnostics = [
        dict(recording.result_for(str(sample.get("utterance", ""))).diagnostics)
        for sample in sample_list
        if recording.result_for(str(sample.get("utterance", ""))) is not None
    ]
    summary = summarize_compiler_results(results)
    summary.update(
        {
            "schema_version": CAMPAIGN_SCHEMA_VERSION,
            "experiment_id": protocol.get("experiment_id"),
            "campaign": campaign,
            "backend_kind": backend_kind,
            "backend_name": str(getattr(getattr(compiler, "backend", None), "name", "unknown")),
            "model": getattr(compiler, "model", "unknown"),
            "prompt_sha256": getattr(compiler, "prompt_sha256", None),
            "prompt_path": _relative_or_absolute(Path(getattr(compiler, "prompt_path", ""))),
            "protocol_sha256": protocol.get("_protocol_sha256"),
            "dataset_id": getattr(corpus, "dataset_id", None),
            "dataset_sha256": _sha256_file(Path(corpus_path)),
            "live_llm_call": backend_kind == "http",
            "llm_plumbing_backend": backend_kind in PLUMBING_BACKENDS,
            "llm_diagnostics": summarize_llm_diagnostics(diagnostics),
            "non_success_with_mission_payload": sum(
                1
                for item in results
                if item["actual_status"] != "SUCCESS" and item["actual_mission"] is not None
            ),
        }
    )
    records: list[dict[str, Any]] = []
    if record_raw:
        for sample in sample_list:
            result = recording.result_for(str(sample.get("utterance", "")))
            if result is None:
                continue
            records.append(
                _build_record(
                    sample,
                    result,
                    backend_kind=backend_kind,
                    max_recorded_chars=int(getattr(compiler, "max_output_chars", 16384)),
                )
            )
    return LLMCampaignRun(results=results, summary=summary, records=records)


def summarize_llm_diagnostics(
    diagnostics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    taxonomy: dict[str, int] = {}
    for item in diagnostics:
        failure_type = item.get("failure_type")
        if failure_type:
            taxonomy[str(failure_type)] = taxonomy.get(str(failure_type), 0) + 1
    latencies = sorted(float(item.get("latency_s") or 0.0) for item in diagnostics)
    tokens = [
        int(item["usage"]["total_tokens"])
        for item in diagnostics
        if isinstance(item.get("usage"), Mapping)
        and isinstance(item["usage"].get("total_tokens"), int)
    ]
    return {
        "samples": len(diagnostics),
        "failure_taxonomy": taxonomy,
        "backend_error_samples": sum(
            taxonomy.get(item, 0) for item in (FAILURE_API_ERROR, FAILURE_TIMEOUT)
        ),
        "malformed_output_samples": taxonomy.get("MALFORMED_OUTPUT", 0),
        "invalid_schema_samples": taxonomy.get("INVALID_SCHEMA", 0),
        "hallucinated_field_samples": taxonomy.get("HALLUCINATED_FIELD", 0),
        "mean_provider_latency_s": mean(latencies) if latencies else None,
        "max_provider_latency_s": latencies[-1] if latencies else None,
        "total_tokens": sum(tokens) if tokens else None,
    }


def write_records(path: str | Path, records: Sequence[Mapping[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n")
    return target


def load_records(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_or_absolute(path: Path) -> str:
    from ...paths import repo_root

    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


__all__ = [
    "BackendError",
    "COMPILER_VERSION",
    "LLMMissionCompiler",
    "LLMCampaignRun",
    "OpenAICompatibleBackend",
    "ReplayBackend",
    "load_records",
    "run_llm_campaign",
    "summarize_llm_diagnostics",
    "write_records",
]
