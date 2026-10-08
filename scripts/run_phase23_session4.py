"""Collect Session 4 evidence without changing the frozen tested system.

The observer inherits the frozen transport retry loop and only journals calls.
Final/OOD evaluation requires a successful, hash-bound live preflight receipt.
Existing output directories are never reused and semantic results are never retried.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from g1swarm.language.errors import CompilerStatus
from g1swarm.llm.backend import DeepSeekResponsesBackend, LLMBackendError
from g1swarm.longhorizon import benchmark, runner
from g1swarm.mission.ir import Mission
from g1swarm.paths import repo_root

try:
    from scripts.verify_phase23_session4 import verify
except ModuleNotFoundError:  # Direct ``python scripts/run_phase23_session4.py``.
    from verify_phase23_session4 import verify

ROOT = repo_root()
BASE = ROOT / "experiments/phase2/long_horizon_language_001"
ARTIFACTS = ROOT / "artifacts/long_horizon_language_001"
SMOKE_TEXT = "前进4米"
SMOKE_MISSION = {
    "schema_version": "2.0.0",
    "mission_id": "session4_provider_preflight",
    "steps": [{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": []}],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Create one immutable evidence file, including a durable flush."""
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def exclusive_directory(path: Path) -> Path:
    resolved = path.resolve()
    if ROOT.resolve() not in resolved.parents:
        raise ValueError("evidence directory must be inside this repository")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def common_provenance(verification: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("protocol_sha256", "freeze_manifest_sha256", "freeze_tag", "freeze_commit", "compiler_provenance", "prompt_sha256", "code_commit")
    common = {key: verification.get(key) for key in keys}
    common["compiler_prompt_sha256"] = common["prompt_sha256"]
    common["dataset_sha256"] = {
        "final_language": verification.get("final_dataset_sha256"),
        "final_canonical": verification.get("canonical_dataset_sha256"),
        "ood": verification.get("ood_dataset_sha256"),
    }
    common["harness_sha256"] = sha(Path(__file__))
    common["verifier_sha256"] = sha(ROOT / "scripts/verify_phase23_session4.py")
    return common


def endpoint_identity(base_url: str) -> dict[str, str]:
    """Exclude credentials, query strings and fragments from safe provenance."""
    parts = urlsplit(base_url)
    authority = parts.hostname or ""
    if parts.port is not None:
        authority += f":{parts.port}"
    identity = f"{parts.scheme.lower()}://{authority.lower()}{parts.path.rstrip('/')}"
    return {"endpoint_identity": identity, "endpoint_fingerprint": hashlib.sha256(identity.encode()).hexdigest()}


def missing_environment(protocol: Mapping[str, Any]) -> list[str]:
    provider = protocol["provider"]
    missing = []
    if not (os.environ.get(provider["base_url_env"]) or os.environ.get("OPENAI_BASE_URL")):
        missing.append(str(provider["base_url_env"]))
    if not any(os.environ.get(name) for name in provider["api_key_envs"]):
        missing.append("one of " + ", ".join(provider["api_key_envs"]))
    return missing


class AttemptJournal:
    def __init__(self, directory: Path, provenance: Mapping[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=False)
        self.attempt_path = directory / "provider_attempts.jsonl"
        self.call_path = directory / "provider_calls.jsonl"
        self.attempt_path.touch(exist_ok=False)
        self.call_path.touch(exist_ok=False)
        self.provenance = dict(provenance)
        self.context: dict[str, Any] = {}
        self.call_count = 0
        self.sample_events: list[dict[str, Any]] = []
        self.sample_calls: list[dict[str, Any]] = []
        self._credential: str | None = None

    def safe(self, value: Any) -> Any:
        """Redact exact credential echoes in persisted copies, never model input."""
        if isinstance(value, str):
            return value.replace(self._credential, "<REDACTED_PROVIDER_CREDENTIAL>") if self._credential else value
        if isinstance(value, Mapping):
            return {key: self.safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.safe(item) for item in value]
        return value

    def start_sample(self, campaign: str, sample_id: str, dataset_sha256: str | None, manifest_sha256: str | None = None) -> None:
        self.context = {"campaign": campaign, "sample_id": sample_id, "dataset_sha256": dataset_sha256, "campaign_manifest_sha256": manifest_sha256}
        self.sample_events = []
        self.sample_calls = []

    def attempt(self, row: Mapping[str, Any]) -> None:
        document = {"common_provenance": self.provenance, **self.context, "timestamp_utc": utc_now(), **dict(row)}
        document = self.safe(document)
        append_jsonl(self.attempt_path, document)
        self.sample_events.append(document)

    def call(self, row: Mapping[str, Any]) -> None:
        document = {"common_provenance": self.provenance, **self.context, "timestamp_utc": utc_now(), **dict(row)}
        events = [event for event in self.sample_events if event.get("call_id") == document["call_id"]]
        document["attempt_ids"] = [event["attempt_id"] for event in events if event["phase"] == "begin"]
        document["retry_reason"] = [event["retry_reason"] for event in events if event["phase"] == "end" and event.get("retry_scheduled")]
        document["provider_invoked"] = bool(document["attempt_ids"])
        document = self.safe(document)
        append_jsonl(self.call_path, document)
        self.sample_calls.append(document)

    def sample_summary(self) -> dict[str, Any]:
        begins = [event for event in self.sample_events if event["phase"] == "begin"]
        ends = [event for event in self.sample_events if event["phase"] == "end"]
        failures = [event for event in ends if event["transport_status"] != "SUCCESS"]
        terminal = self.sample_calls[-1]["terminal_transport_status"] if self.sample_calls else "NOT_INVOKED"
        return {
            "provider_invoked": bool(begins),
            "provider_attempts": len(begins),
            "provider_calls": len(self.sample_calls),
            "attempt_ids": [event["attempt_id"] for event in begins],
            "retry_reason": [event["retry_reason"] for event in failures if event.get("retry_scheduled")],
            "terminal_transport_status": terminal,
            "transport_failure": terminal not in {"SUCCESS", "NOT_INVOKED"},
            "attempts_complete": len(begins) == len(ends),
            "all_attempt_latency_s": sum(event["latency_s"] for event in ends),
            "backoff_wall_time_s": sum(event.get("actual_delay_s", 0.0) for event in self.sample_events if event["phase"] == "backoff"),
        }


class ObservedFrozenBackend(DeepSeekResponsesBackend):
    """Observation only; ``super().complete`` owns payload and retry behavior."""
    def __init__(self, config, journal: AttemptJournal) -> None:
        super().__init__(config)
        self.journal = journal
        self.journal._credential = config.api_key
        self._attempt_index = 0
        self._call_id = ""

    def complete(self, *, system_prompt: str, user_text: str):
        self.journal.call_count += 1
        self._call_id = f"call-{self.journal.call_count:06d}"
        self._attempt_index = 0
        started = time.perf_counter()
        try:
            response = super().complete(system_prompt=system_prompt, user_text=user_text)
        except LLMBackendError as exc:
            self.journal.call({"call_id": self._call_id, "provider_attempts": self._attempt_index, "terminal_transport_status": exc.failure_type, "transport_failure": True, "wall_time_s": time.perf_counter() - started, "error_type": type(exc).__name__, "error_context": _safe_error_context(exc.context)})
            raise
        except Exception as exc:
            self.journal.call({"call_id": self._call_id, "provider_attempts": self._attempt_index, "terminal_transport_status": "INTERNAL_ERROR", "transport_failure": True, "wall_time_s": time.perf_counter() - started, "error_type": type(exc).__name__})
            raise
        self.journal.call({"call_id": self._call_id, "provider_attempts": response.attempts, "terminal_transport_status": "SUCCESS", "transport_failure": False, "wall_time_s": time.perf_counter() - started, "response": {"text": response.text, "model": response.model, "latency_s": response.latency_s, "attempts": response.attempts, "request_parameters": dict(response.request_parameters), "usage": response.usage, "response_id": response.response_id, "finish_reason": response.finish_reason, "provider_status": response.provider_status}})
        return response

    def _post(self, payload):
        self._attempt_index += 1
        attempt_id = f"{self._call_id}-attempt-{self._attempt_index}"
        base = {"call_id": self._call_id, "attempt_id": attempt_id, "attempt_index": self._attempt_index}
        self.journal.attempt({**base, "phase": "begin", "request_payload": payload})
        started = time.perf_counter()
        try:
            document, frozen_latency = super()._post(payload)
        except LLMBackendError as exc:
            retry_scheduled = exc.retryable and self._attempt_index <= self.config.max_network_retries
            context = _safe_error_context(exc.context)
            reason = f"HTTP_{context['http_status']}" if "http_status" in context else exc.failure_type
            self.journal.attempt({**base, "phase": "end", "transport_status": exc.failure_type, "latency_s": time.perf_counter() - started, "retry_scheduled": retry_scheduled, "retry_reason": reason, "error_type": type(exc).__name__, "error_context": context})
            raise
        except Exception as exc:
            self.journal.attempt({**base, "phase": "end", "transport_status": "INTERNAL_ERROR", "latency_s": time.perf_counter() - started, "retry_scheduled": False, "retry_reason": None, "error_type": type(exc).__name__})
            raise
        self.journal.attempt({**base, "phase": "end", "transport_status": "SUCCESS", "latency_s": time.perf_counter() - started, "frozen_latency_s": frozen_latency, "retry_scheduled": False, "retry_reason": None, "provider_document": document})
        return document, frozen_latency

    def _sleep(self, attempt: int) -> None:
        started = time.perf_counter()
        super()._sleep(attempt)
        # Frozen ``MAX_BACKOFF_S`` is imported to avoid a divergent retry rule.
        from g1swarm.llm.backend import MAX_BACKOFF_S
        self.journal.attempt({"phase": "backoff", "call_id": self._call_id, "attempt_id": f"{self._call_id}-attempt-{attempt}", "attempt_index": attempt, "delay_s": min(self.config.retry_backoff_s * 2 ** (attempt - 1), MAX_BACKOFF_S), "actual_delay_s": time.perf_counter() - started})


def _safe_error_context(context: Mapping[str, Any]) -> dict[str, Any]:
    return {key: context[key] for key in ("http_status", "response_id") if key in context}


def make_observed_treatment(protocol, journal):
    adapter = runner._make_backend(protocol)
    adapter._core = ObservedFrozenBackend(adapter.config, journal)
    compiler, provenance = runner.build_frozen_treatment(protocol, backend=adapter)
    return compiler, provenance, endpoint_identity(adapter.config.base_url)


def provider_response_issues(result, protocol: Mapping[str, Any], journal: AttemptJournal) -> list[str]:
    issues = []
    diagnostics = result.diagnostics
    if journal.sample_calls and journal.sample_calls[-1]["terminal_transport_status"] == "SUCCESS":
        if diagnostics.get("model") != protocol["provider"]["model"]:
            issues.append("response model differs from frozen model")
        request = diagnostics.get("request_parameters", {})
        for key in ("model", "temperature", "max_output_tokens", "max_network_retries", "retry_backoff_s"):
            if request.get(key) != protocol["provider"][key]:
                issues.append(f"response request parameter differs: {key}")
        if request.get("stream") is not False:
            issues.append("stream parameter differs from frozen transport")
    if not journal.sample_summary()["attempts_complete"]:
        issues.append("provider attempts have an unmatched begin/end event")
    if journal.sample_calls and diagnostics.get("attempts") != journal.sample_summary()["provider_attempts"]:
        issues.append("compiler aggregate attempts differ from observer ledger")
    return issues


def preflight(directory: Path, provider_binding_path: Path | None = None) -> dict[str, Any]:
    verification = verify()
    output = exclusive_directory(directory)
    common = common_provenance(verification)
    write_json(output / "freeze_verification.json", {"common_provenance": common, **verification})
    receipt: dict[str, Any] = {"schema_version": "session4.1", "common_provenance": common, "created_utc": utc_now(), "campaign_started": False, "final_inputs_evaluated": 0, "ood_inputs_evaluated": 0, "provider_calls": 0}
    if verification["status"] != "PASS":
        receipt.update(status="BLOCKED_FREEZE_INTEGRITY", issues=verification["issues"])
    else:
        protocol = runner.load_protocol()
        missing = missing_environment(protocol)
        if missing:
            receipt.update(status="BLOCKED_PROVIDER_CONFIGURATION", issues=["missing environment: " + item for item in missing], integrity_status="PASS")
        elif provider_binding_path is None:
            receipt.update(status="BLOCKED_PROVIDER_PROVENANCE", issues=["a verified non-secret historical provider binding is required"], integrity_status="PASS")
        else:
            binding_path = provider_binding_path.resolve()
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            configured_url = os.environ.get(protocol["provider"]["base_url_env"]) or os.environ.get("OPENAI_BASE_URL")
            safe_endpoint = endpoint_identity(str(configured_url))
            if binding.get("status") != "PASS" or binding.get("model") != protocol["provider"]["model"] or binding.get("endpoint_identity") != safe_endpoint["endpoint_identity"]:
                receipt.update(status="BLOCKED_PROVIDER_PROVENANCE", issues=["historical provider binding is unverified or differs from current configuration"], integrity_status="PASS")
                write_json(output / "preflight.json", receipt)
                return receipt
            receipt.update(provider_binding=binding, provider_binding_path=str(binding_path.relative_to(ROOT)), provider_binding_sha256=sha(binding_path))
            journal = AttemptJournal(output / "raw", common)
            journal.start_sample("provider_preflight", "session4-smoke", None)
            compiler, compiler_provenance, endpoint = make_observed_treatment(protocol, journal)
            started = time.perf_counter()
            result = compiler.compile(SMOKE_TEXT)
            comparison = benchmark.compare_ir(result.mission, Mission.from_dict(SMOKE_MISSION))
            issues = provider_response_issues(result, protocol, journal)
            if not comparison["exact_ir_match"] or not result.success:
                issues.append("independent provider smoke did not produce exact expected IR")
            usage = result.diagnostics.get("usage")
            if not isinstance(usage, Mapping) or not isinstance(usage.get("total_tokens"), int) or usage["total_tokens"] <= 0:
                issues.append("provider preflight lacks usable token accounting")
            receipt.update(status="PASS" if not issues else "BLOCKED_PROVIDER_PREFLIGHT", integrity_status="PASS", issues=issues, smoke_text=SMOKE_TEXT, expected_mission=SMOKE_MISSION, result=result.to_dict(), comparison=comparison, compiler_provenance=compiler_provenance, observer_control={"class": "ObservedFrozenBackend", "base_class": "g1swarm.llm.backend.DeepSeekResponsesBackend", "payload_inherited": ObservedFrozenBackend._payload is DeepSeekResponsesBackend._payload, "retry_loop": "super().complete; frozen complete implementation", "transport": "super()._post; frozen transport implementation", "backoff": "super()._sleep; frozen backoff implementation", "original_config_unchanged": True, "redaction": "exact credential echo replacement in persisted copies only; no credential hash"}, wall_time_s=time.perf_counter() - started, **endpoint, **journal.sample_summary())
            receipt["provider_ledger_sha256"] = {"attempts": sha(journal.attempt_path), "calls": sha(journal.call_path)}
            receipt = journal.safe(receipt)
    write_json(output / "preflight.json", receipt)
    return receipt


def verify_preflight(receipt_path: Path, verification: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS":
        raise ValueError("a successful live provider preflight receipt is required")
    common = common_provenance(verification)
    if receipt.get("common_provenance") != common:
        raise ValueError("preflight provenance or source hashes have drifted")
    binding_path = ROOT / receipt["provider_binding_path"]
    if sha(binding_path) != receipt["provider_binding_sha256"] or receipt.get("provider_binding", {}).get("status") != "PASS":
        raise ValueError("historical provider binding has drifted")
    if missing_environment(protocol):
        raise ValueError("provider environment is missing after preflight")
    base_url = os.environ.get(protocol["provider"]["base_url_env"]) or os.environ.get("OPENAI_BASE_URL")
    identity = endpoint_identity(str(base_url))
    if receipt.get("endpoint_fingerprint") != identity["endpoint_fingerprint"]:
        raise ValueError("provider endpoint differs from preflight")
    for key, filename in (("attempts", "provider_attempts.jsonl"), ("calls", "provider_calls.jsonl")):
        if sha(receipt_path.parent / "raw" / filename) != receipt["provider_ledger_sha256"][key]:
            raise ValueError("preflight provider ledger hash mismatch")
    return receipt


def position_ir(document: Mapping[str, Any]) -> dict[str, Any]:
    """OOD policy ignores identifier spelling while preserving dependency edges."""
    steps = list(document["steps"])
    positions = {step["id"]: index for index, step in enumerate(steps)}
    return {"schema_version": document["schema_version"], "steps": [{"skill": step["skill"], "parameters": dict(step["parameters"]), "depends_on": sorted(positions[dep] for dep in step.get("depends_on", []))} for step in steps]}


def ood_record(sample: Mapping[str, Any], result, guard_row: Mapping[str, Any]) -> dict[str, Any]:
    mission = benchmark.mission_document(result.mission) if result.mission is not None else None
    valid = sample["expected_status"] == "SUCCESS"
    expected = sample.get("expected_mission")
    exact = bool(valid and mission is not None and position_ir(mission) == position_ir(expected))
    comparison = {"exact_ir_match": exact}
    if valid and mission is not None:
        actual_shape, expected_shape = position_ir(mission), position_ir(expected)
        actual_steps, expected_steps = actual_shape["steps"], expected_shape["steps"]
        order = [s["skill"] for s in actual_steps] == [s["skill"] for s in expected_steps]
        comparison.update(step_order_match=order, step_count_match=len(actual_steps) == len(expected_steps), parameters_match=order and [s["parameters"] for s in actual_steps] == [s["parameters"] for s in expected_steps], dependencies_match=len(actual_steps) == len(expected_steps) and [s["depends_on"] for s in actual_steps] == [s["depends_on"] for s in expected_steps])
    unsafe = not valid and mission is not None
    return {**dict(sample), "sample_id": sample["candidate_id"], "actual_status": result.status.value, "compiled_mission": mission, "oracle_mission": expected, "result": result.to_dict(), "diagnostics": dict(result.diagnostics), "comparison": comparison, "unsafe_acceptance": unsafe, "silent_repair": unsafe and result.status is CompilerStatus.SUCCESS, "false_rejection": valid and (result.status is not CompilerStatus.SUCCESS or mission is None), "valid_exact_ir": exact, "guard_status": guard_row["guard_status"], "guard_reason_code": guard_row["guard_reason_code"], "guard_rejects": guard_row["guard_rejects"], "provider_tokens": result.diagnostics.get("usage", {}).get("total_tokens") if isinstance(result.diagnostics.get("usage"), Mapping) else None, "latency_s": result.diagnostics.get("latency_s")}


def run_campaign(directory: Path, ood_directory: Path, receipt_path: Path) -> dict[str, Any]:
    verification = verify()
    if verification["status"] != "PASS":
        raise ValueError("freeze integrity failed; no campaign may start")
    protocol = runner.load_protocol()
    receipt = verify_preflight(receipt_path, verification, protocol)
    from g1swarm.config import load_yaml
    missions = load_yaml(BASE / "final/canonical_missions_final.yaml")["missions"]
    samples = load_yaml(BASE / "final/language_realizations_final.yaml")["samples"]
    ood_samples = [json.loads(line) for line in (BASE / "ood/guard_ood_dataset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(missions) != 102 or len(samples) != 306 or len(ood_samples) != 160:
        raise ValueError("frozen scheduled corpus size mismatch")
    if directory.resolve() == ood_directory.resolve() or directory.exists() or ood_directory.exists():
        raise FileExistsError("campaign output already exists; no semantic rerun or overwrite permitted")
    output, ood_output = exclusive_directory(directory), exclusive_directory(ood_directory)
    common = common_provenance(verification)
    manifest = {"schema_version": "session4.1", "created_utc": utc_now(), "common_provenance": common, "freeze_verification_status": "PASS", "provider_preflight_status": "PASS", "provider_binding_status": "PASS", "preflight_receipt": str(receipt_path.relative_to(ROOT)), "preflight_sha256": sha(receipt_path), "endpoint_fingerprint": receipt["endpoint_fingerprint"], "expected_samples": {"compiler": 306, "ood": 160, "ood_primary": 129, "ood_sensitivity": 31}, "scheduled_samples": {"compiler": [s["sample_id"] for s in samples], "ood": [s["candidate_id"] for s in ood_samples], "ood_primary": [s["candidate_id"] for s in ood_samples if s["split"] == "primary_gold"], "ood_sensitivity": [s["candidate_id"] for s in ood_samples if s["split"] == "disputed_sensitivity"]}, "scheduled_metadata": {"compiler": [{key: s[key] for key in ("sample_id", "horizon", "condition")} for s in samples], "ood": [{"sample_id": s["candidate_id"], "split": s["split"], "expected_status": s["expected_status"]} for s in ood_samples]}, "semantic_retry": False, "runtime_execution": False, "ood_output_directory": str(ood_output.relative_to(ROOT))}
    write_json(output / "campaign_manifest.json", manifest)
    manifest_sha = sha(output / "campaign_manifest.json")
    write_json(ood_output / "campaign_manifest.json", {**manifest, "parent_manifest_sha256": manifest_sha})
    write_json(output / "freeze_verification.json", {"common_provenance": common, **verification})
    journal = AttemptJournal(output / "raw", common)
    compiler, provenance, endpoint = make_observed_treatment(protocol, journal)
    if endpoint["endpoint_fingerprint"] != receipt["endpoint_fingerprint"]:
        raise ValueError("provider endpoint drift before first campaign sample")
    provenance.update(common)
    mission_by_id = {mission["mission_id"]: mission for mission in missions}
    final_rows: list[dict[str, Any]] = []
    guard_rows: list[dict[str, Any]] = []
    ood_rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {"common_provenance": common, "campaign_manifest_sha256": manifest_sha, "status": "COMPLETE", "issues": []}

    def evidence(row, dataset_sha):
        return journal.safe({**row, "common_provenance": common, "dataset_sha256": dataset_sha, "campaign_manifest_sha256": manifest_sha})

    def stop_if_needed(result):
        issues = provider_response_issues(result, protocol, journal)
        summary = journal.sample_summary()
        if summary["transport_failure"]:
            issues.append("terminal provider transport failure; remaining scheduled IDs stay pending")
        if issues:
            state.update(status="BLOCKED_PROVIDER_OR_INTEGRITY", issues=issues)
            return True
        return False

    for index, sample in enumerate(samples):
        dataset_sha = common["dataset_sha256"]["final_language"]
        journal.start_sample("final_compiler", sample["sample_id"], dataset_sha, manifest_sha)
        started = time.perf_counter()
        result = compiler.compile(sample["text"])
        row = benchmark.compiler_record(experiment_id=protocol["experiment_id"], sample=sample, mission=mission_by_id[sample["mission_id"]], result=result, provenance=provenance, wall_time_s=time.perf_counter() - started)
        row.update(campaign="final_compiler", sample_index=index, result=result.to_dict(), diagnostics=dict(result.diagnostics), **journal.sample_summary())
        if row["transport_failure"]:
            row["false_rejection"] = False
            row["semantic_outcome"] = "NOT_OBSERVED_TRANSPORT_FAILURE"
        else:
            row["semantic_outcome"] = result.status.value
        row = evidence(row, dataset_sha)
        append_jsonl(output / "compiler_results.jsonl", row)
        final_rows.append(row)
        print(f"Final compiler {len(final_rows)}/306: {sample['sample_id']} {row['semantic_outcome']}", flush=True)
        if stop_if_needed(result):
            break
    write_json(output / "compiler_results.json", {"common_provenance": common, "campaign_manifest_sha256": manifest_sha, "stage": "compiler", "records": final_rows, "record_count": len(final_rows), "safety_controls": [], "summary": benchmark.summarize_compiler(final_rows)})
    if state["status"] == "COMPLETE":
        # Guard-only is durably complete before any OOD full-system invocation.
        for index, sample in enumerate(ood_samples):
            started = time.perf_counter()
            verdict = compiler.guard.check(sample["utterance"])
            rejected = verdict.status.value == "MALFORMED"
            row = evidence({**dict(sample), "campaign": "guard_ood_guard_only", "sample_id": sample["candidate_id"], "sample_index": index, "guard_status": verdict.status.value, "guard_reason_code": verdict.reason_code.value if verdict.reason_code else None, "guard_rejects": rejected, "provider_calls_avoided": int(rejected), "provider_calls": 0, "wall_time_s": time.perf_counter() - started}, common["dataset_sha256"]["ood"])
            append_jsonl(ood_output / "guard_only_results.jsonl", row)
            guard_rows.append(row)
        for index, (sample, guard_row) in enumerate(zip(ood_samples, guard_rows, strict=True)):
            dataset_sha = common["dataset_sha256"]["ood"]
            journal.start_sample("guard_ood", sample["candidate_id"], dataset_sha, manifest_sha)
            started = time.perf_counter()
            result = compiler.compile(sample["utterance"])
            row = ood_record(sample, result, guard_row)
            row.update(campaign="guard_ood", sample_index=index, wall_time_s=time.perf_counter() - started, **journal.sample_summary())
            if row["transport_failure"]:
                row["false_rejection"] = False
                row["semantic_outcome"] = "NOT_OBSERVED_TRANSPORT_FAILURE"
            else:
                row["semantic_outcome"] = result.status.value
            if result.diagnostics.get("guard_status") != guard_row["guard_status"]:
                state.update(status="BLOCKED_GUARD_OBSERVATION_MISMATCH", issues=["guard-only and full-system observations differ"])
            row = evidence(row, dataset_sha)
            append_jsonl(ood_output / "ood_results.jsonl", row)
            ood_rows.append(row)
            print(f"OOD compiler {len(ood_rows)}/160: {sample['candidate_id']} {row['semantic_outcome']}", flush=True)
            if stop_if_needed(result) or state["status"] != "COMPLETE":
                break
    state.update(completed_samples={"compiler": len(final_rows), "ood_guard_only": len(guard_rows), "ood": len(ood_rows)}, pending_samples={"compiler": [s["sample_id"] for s in samples[len(final_rows):]], "ood_guard_only": [s["candidate_id"] for s in ood_samples[len(guard_rows):]], "ood": [s["candidate_id"] for s in ood_samples[len(ood_rows):]]}, provider_calls=journal.call_count, provider_ledger_sha256={"attempts": sha(journal.attempt_path), "calls": sha(journal.call_path)}, completed_utc=utc_now())
    write_json(output / "campaign_state.json", state)
    write_json(ood_output / "campaign_state.json", state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "preflight", "run"))
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--ood-out-dir", type=Path, default=ARTIFACTS / "final_guard_ood")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--provider-binding", type=Path, help="verified historical endpoint/model provenance, containing no credentials")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify()
            if args.out_dir:
                directory = exclusive_directory(args.out_dir)
                write_json(directory / "freeze_verification.json", result)
        elif args.command == "preflight":
            result = preflight(args.out_dir or ARTIFACTS / "session4_preflight", args.provider_binding)
        else:
            if not args.preflight:
                parser.error("run requires --preflight with a successful live receipt")
            result = run_campaign(args.out_dir or ARTIFACTS / "session4", args.ood_out_dir, args.preflight.resolve())
    except (ValueError, FileExistsError, KeyError) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "issues": result.get("issues", []), "provider_calls": result.get("provider_calls", 0)}, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
