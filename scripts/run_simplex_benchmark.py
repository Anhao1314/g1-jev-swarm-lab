"""Run Phase 2.2b A/B/C/D treatments over a frozen dataset.

The four treatments share one model backend and one cache. Treatment A always
requests direct Mission IR. Treatment B reuses A's cached direct response when
the structural guard passes. Treatment C requests canonical controlled text.
Treatment D reuses the same canonicalizer response only when the frozen Lark
fast path fails. This keeps architecture comparisons on the same model calls
and makes escalation/avoided-call metrics meaningful.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo, utc_timestamp
from g1swarm.language.llm import OpenAICompatibleBackend
from g1swarm.llm.backend import LLMBackend, LLMBackendResponse
from g1swarm.llm.compiler import LLMMissionCompiler
from g1swarm.llm.datasets import LLMSample, load_dataset
from g1swarm.simplex.canonicalizer import LLMMissionCanonicalizer
from g1swarm.simplex.metrics import (
    comparison_row,
    evaluate_hard_gates,
    evaluate_simplex_sample,
    summarize_simplex_results,
)
from g1swarm.simplex.structural_guard import StructuralGuard
from g1swarm.simplex.treatments import (
    CanonicalBridgeTreatment,
    DirectLLMTreatment,
    GuardedDirectLLMTreatment,
    SimplexCanonicalTreatment,
)
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

EXPERIMENT_ID = "simplex_compiler_001"
DEFAULT_PROTOCOL = "configs/experiments/simplex_compiler_001.yaml"
TREATMENTS = ("A", "B", "C", "D")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


@dataclass
class _CacheEvent:
    kind: str
    system_prompt_sha256: str
    user_text: str
    response: LLMBackendResponse


class CachingBackend:
    """Thread-safe cache around the shared provider backend."""

    def __init__(self, backend: LLMBackend, *, direct_prompt_sha256: str) -> None:
        self.backend = backend
        self.model = str(getattr(backend, "model", "unknown"))
        self.name = str(getattr(backend, "name", "cached"))
        self.direct_prompt_sha256 = direct_prompt_sha256
        self._cache: dict[tuple[str, str], LLMBackendResponse] = {}
        self.events: list[_CacheEvent] = []
        self.network_calls = 0

    def request_parameters(self) -> dict[str, Any]:
        return dict(getattr(self.backend, "request_parameters", lambda: {})())

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        key = (_sha256_text(system_prompt), str(user_text))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        response = self.backend.complete(system_prompt=system_prompt, user_text=user_text)
        self._cache[key] = response
        self.network_calls += 1
        kind = "direct" if key[0] == self.direct_prompt_sha256 else "canonicalizer"
        self.events.append(
            _CacheEvent(
                kind=kind,
                system_prompt_sha256=key[0],
                user_text=str(user_text),
                response=response,
            )
        )
        return response

    def seed(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        system_prompt_sha256: str,
    ) -> None:
        for record in records:
            utterance = record.get("utterance")
            text = record.get("response_text")
            if not isinstance(utterance, str) or not isinstance(text, str):
                continue
            key = (system_prompt_sha256, utterance)
            if key in self._cache:
                continue
            self._cache[key] = LLMBackendResponse(
                text=text,
                model=str(record.get("model", self.model)),
                latency_s=float(record.get("latency_s") or 0.0),
                attempts=int(record.get("attempts") or 1),
                request_parameters={},
                usage=record.get("usage") if isinstance(record.get("usage"), Mapping) else None,
                response_id=record.get("request_id"),
                finish_reason=record.get("finish_reason"),
                provider_status=record.get("finish_reason"),
            )


def _load_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    protocol["_protocol_sha256"] = _sha256_file(resolved)
    return protocol, resolved


def _make_backend(protocol: Mapping[str, Any]) -> OpenAICompatibleBackend:
    provider = protocol["provider"]
    base_url = os.environ.get(str(provider["base_url_env"])) or os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(f"environment variable {provider['base_url_env']} is not set")
    env_name = next(
        (str(name) for name in provider["api_key_envs"] if os.environ.get(str(name))),
        str(provider["api_key_envs"][0]),
    )
    return OpenAICompatibleBackend.from_env(
        model=str(provider["model"]),
        base_url=base_url,
        api_key_env=env_name,
        provider="deepseek-relay",
        timeout_s=float(provider["timeout_s"]),
        temperature=float(provider["temperature"]),
        max_output_tokens=int(provider["max_output_tokens"]),
        max_network_retries=int(provider["max_network_retries"]),
        retry_backoff_s=float(provider["retry_backoff_s"]),
    )


def _make_architectures(protocol: Mapping[str, Any], cache: CachingBackend):
    direct_backend = cache
    direct = LLMMissionCompiler(
        backend=direct_backend,
        prompt_path=resolve_repo_path(protocol["prompt"]["direct"]),
        protocol=protocol,
    )
    canonicalizer = LLMMissionCanonicalizer(
        backend=direct_backend,
        prompt_path=resolve_repo_path(protocol["prompt"]["canonicalizer"]),
        expected_prompt_sha256=str(protocol["prompt"]["canonicalizer_sha256"]),
        max_input_chars=int(protocol["compiler"]["max_input_chars"]),
        max_output_chars=int(protocol["compiler"]["max_output_chars"]),
    )
    guard = StructuralGuard()
    return {
        "A": DirectLLMTreatment(direct),
        "B": GuardedDirectLLMTreatment(guard, direct),
        "C": CanonicalBridgeTreatment(guard, canonicalizer),
        "D": SimplexCanonicalTreatment(guard, canonicalizer),
    }


def _evaluate_all(
    sample: LLMSample,
    architectures: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_simplex_sample(sample.to_dict(), architecture)
        for name, architecture in architectures.items()
    }


def _summarize_treatment(
    rows: Sequence[Mapping[str, Any]],
    *,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    valid = [row for row in rows if row.get("expected_status") == "SUCCESS"]
    open_valid = [row for row in valid if row.get("category") == "clear_open_valid"]
    summary = summarize_simplex_results(rows)
    summary["valid_sample_exact_ir_match"] = (
        sum(bool(row.get("exact_ir_match")) for row in valid) / len(valid)
        if valid
        else None
    )
    summary["open_language_coverage"] = (
        sum(row.get("actual_status") == "SUCCESS" for row in open_valid) / len(open_valid)
        if open_valid
        else None
    )
    summary["protocol_sha256"] = protocol.get("_protocol_sha256")
    summary["hard_gates"] = evaluate_hard_gates(summary)
    summary["comparison"] = comparison_row(summary)
    return summary


def _seed_direct(
    cache: CachingBackend,
    protocol: Mapping[str, Any],
    seed_path: str | Path | None,
) -> None:
    if seed_path is None:
        return
    resolved = resolve_repo_path(seed_path)
    if not resolved.exists():
        return
    records = [
        json.loads(line)
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cache.seed(records, system_prompt_sha256=str(protocol["prompt"]["direct_sha256"]))


def run(
    *,
    protocol_path: str | Path,
    dataset_path: str | Path,
    campaign: str,
    workers: int,
    seed_direct_path: str | Path | None = None,
    require_frozen: bool = False,
) -> dict[str, Any]:
    protocol, protocol_file = _load_protocol(protocol_path)
    if require_frozen and not bool(protocol.get("frozen", False)):
        raise SystemExit("protocol is not frozen")
    dataset_file = resolve_repo_path(dataset_path)
    dataset = load_dataset(dataset_file)
    base_backend = _make_backend(protocol)
    cache = CachingBackend(base_backend, direct_prompt_sha256=str(protocol["prompt"]["direct_sha256"]))
    _seed_direct(cache, protocol, seed_direct_path)
    architectures = _make_architectures(protocol, cache)

    rows_by_treatment: dict[str, list[dict[str, Any]]] = {name: [] for name in TREATMENTS}
    samples = list(dataset.samples)

    def evaluate_one(sample: LLMSample) -> dict[str, dict[str, Any]]:
        return _evaluate_all(sample, architectures)

    if workers <= 1:
        evaluated = [evaluate_one(sample) for sample in samples]
    else:
        evaluated = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(evaluate_one, sample) for sample in samples]
            for future in concurrent.futures.as_completed(futures):
                evaluated.append(future.result())

    # Restore dataset order for deterministic evidence.
    order = {sample.sample_id: index for index, sample in enumerate(samples)}
    evaluated.sort(key=lambda item: order[next(iter(item.values()))["sample_id"]])
    for item in evaluated:
        for name, row in item.items():
            rows_by_treatment[name].append(row)

    out_dir = repo_root() / "experiments" / "phase2" / EXPERIMENT_ID
    summaries: dict[str, Any] = {}
    for name in TREATMENTS:
        summary = _summarize_treatment(rows_by_treatment[name], protocol=protocol)
        summary.update(
            {
                "campaign": campaign,
                "dataset_id": dataset.dataset_id,
                "dataset_sha256": _sha256_file(dataset_file),
                "model": protocol["provider"]["model"],
                "generated_at": utc_timestamp(),
                "environment": EnvironmentInfo.collect().to_dict(),
            }
        )
        summaries[name] = summary
        _write_json(out_dir / f"treatment_{name.lower()}.json", {
            "summary": summary,
            "results": rows_by_treatment[name],
        })
    comparison = {
        "schema_version": "1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "campaign": campaign,
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "dataset_sha256": _sha256_file(dataset_file),
        "treatments": summaries,
        "table": {name: summaries[name]["comparison"] for name in TREATMENTS},
        "generated_at": utc_timestamp(),
    }
    _write_json(out_dir / "comparison.json", comparison)

    raw_dir = artifacts_dir() / EXPERIMENT_ID / campaign / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with (raw_dir / "provider_calls.jsonl").open("w", encoding="utf-8") as handle:
        for event in cache.events:
            handle.write(
                json.dumps(
                    {
                        "kind": event.kind,
                        "system_prompt_sha256": event.system_prompt_sha256,
                        "utterance": event.user_text,
                        "response_text": event.response.text,
                        "model": event.response.model,
                        "latency_s": event.response.latency_s,
                        "attempts": event.response.attempts,
                        "usage": event.response.usage,
                        "response_id": event.response.response_id,
                        "finish_reason": event.response.finish_reason,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    _write_json(
        artifacts_dir() / EXPERIMENT_ID / campaign / "request_summary.json",
        {
            "campaign": campaign,
            "network_provider_calls": cache.network_calls,
            "events": len(cache.events),
            "dataset_sha256": _sha256_file(dataset_file),
            "protocol_sha256": protocol.get("_protocol_sha256"),
        },
    )
    print(json.dumps(comparison["table"], ensure_ascii=False, indent=2, sort_keys=True))
    return comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed-direct", default=None)
    parser.add_argument("--require-frozen", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(
            protocol_path=args.protocol,
            dataset_path=args.dataset,
            campaign=args.campaign,
            workers=args.workers,
            seed_direct_path=args.seed_direct,
            require_frozen=args.require_frozen,
        )
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
