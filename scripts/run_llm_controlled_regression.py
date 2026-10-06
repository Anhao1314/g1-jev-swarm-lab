"""Run the frozen DeepSeek compiler over the Phase 2.1 controlled corpus.

This is the Set A controlled-regression comparison required by Phase 2.2. It
does not tune the prompt or modify the frozen protocol; it only calls the
already-frozen compiler on the Phase 2.1 corpus and records the result.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import json
from pathlib import Path
from typing import Any

from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo, utc_timestamp
from g1swarm.language.corpus import load_corpus
from g1swarm.language.errors import LanguageErrorCode
from g1swarm.language.llm import (
    BackendError,
    LLMMissionCompiler,
    OpenAICompatibleBackend,
    run_llm_campaign,
    write_records,
)
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

EXPERIMENT_ID = "llm_compiler_001"
DEFAULT_PROTOCOL = "configs/experiments/llm_compiler_001.yaml"
CONTROLLED_CORPUS = "configs/language/controlled_language_001.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _make_compiler(protocol: dict[str, Any]) -> LLMMissionCompiler:
    provider = protocol["provider"]
    base_url = os.environ.get(str(provider["base_url_env"])) or os.environ.get(
        "OPENAI_BASE_URL"
    )
    if not base_url:
        raise BackendError(
            LanguageErrorCode.LLM_CONFIGURATION_ERROR,
            f"environment variable {provider['base_url_env']} is not set",
            reason="configuration",
        )
    api_key_env = next(
        (
            str(name)
            for name in provider["api_key_envs"]
            if os.environ.get(str(name))
        ),
        str(provider["api_key_envs"][0]),
    )
    backend = OpenAICompatibleBackend.from_env(
        model=str(provider["model"]),
        base_url=base_url,
        api_key_env=api_key_env,
        provider="deepseek-relay",
        timeout_s=float(provider["timeout_s"]),
        temperature=float(provider["temperature"]),
        max_output_tokens=int(provider["max_output_tokens"]),
        max_network_retries=int(provider["max_network_retries"]),
        retry_backoff_s=float(provider["retry_backoff_s"]),
    )
    return LLMMissionCompiler(
        backend,
        prompt_path=resolve_repo_path(protocol["prompt"]["path"]),
        max_input_chars=int(protocol["compiler"]["max_input_chars"]),
        max_output_chars=int(protocol["compiler"]["max_output_chars"]),
        expected_prompt_sha256=str(protocol["prompt"]["sha256"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--corpus", default=CONTROLLED_CORPUS)
    args = parser.parse_args(argv)

    protocol_path = resolve_repo_path(args.protocol)
    protocol = load_yaml(protocol_path)
    protocol["_protocol_sha256"] = _sha256(protocol_path)
    if not bool(protocol.get("frozen", False)):
        raise SystemExit("protocol is not frozen")
    corpus_path = resolve_repo_path(args.corpus)
    corpus = load_corpus(corpus_path)
    samples = [sample.to_dict() for sample in corpus.samples]
    compiler = _make_compiler(protocol)
    run = run_llm_campaign(
        compiler=compiler,
        samples=samples,
        protocol=protocol,
        corpus=corpus,
        corpus_path=corpus_path,
        campaign="controlled_regression",
        backend_kind="http",
        record_raw=True,
    )
    summary = dict(run.summary)
    summary.update(
        {
            "experiment_id": EXPERIMENT_ID,
            "campaign": "controlled_regression",
            "corpus_sha256": _sha256(corpus_path),
            "prompt_sha256": _sha256(resolve_repo_path(protocol["prompt"]["path"])),
            "environment": EnvironmentInfo.collect().to_dict(),
            "generated_at": utc_timestamp(),
        }
    )
    out_dir = repo_root() / "experiments" / "phase2" / EXPERIMENT_ID
    _write_json(out_dir / "controlled_regression.json", {"summary": summary, "results": run.results})
    raw_dir = artifacts_dir() / EXPERIMENT_ID / "controlled_regression"
    write_records(raw_dir / "raw_responses.jsonl", run.records)
    _write_json(raw_dir / "request_summary.json", summary)
    print(
        json.dumps(
            {
                "samples": summary.get("total_samples"),
                "exact_mission_ir_match": summary.get("valid_sample_exact_ir_match"),
                "schema_valid_rate": summary.get("schema_valid_rate"),
                "unsupported_recall": summary.get("unsupported_recall"),
                "hard_gates": {
                    "hallucinated_skill_count": summary.get("hallucinated_skill_count"),
                    "invalid_language_reaching_robot": summary.get("invalid_language_reaching_robot"),
                    "ambiguous_language_reaching_robot": summary.get("ambiguous_language_reaching_robot"),
                    "unsupported_language_reaching_robot": summary.get("unsupported_language_reaching_robot"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
