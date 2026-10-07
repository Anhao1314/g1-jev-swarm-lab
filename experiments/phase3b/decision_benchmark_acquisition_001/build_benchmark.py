"""Assemble the frozen Phase 3B.0a offline benchmark from exported evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("phase3b0a_study", HERE / "study.py")
assert spec is not None and spec.loader is not None
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
ROOT = study.ROOT
EVIDENCE = HERE / "evidence_attempt02"
OUT = HERE / "benchmark.json"


def build() -> dict:
    manifest_path = HERE / "evidence_manifest_attempt02.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, receipt in manifest["files"].items():
        if study.digest(ROOT / relative) != receipt["sha256"]:
            raise ValueError(f"Exported evidence hash mismatch: {relative}")
    completion = json.loads((EVIDENCE / "primary_completion.json").read_text(encoding="utf-8"))
    if completion["stop_reason"] is not None or completion["completed_primary_cells"] != 12:
        raise ValueError("Frozen primary matrix is incomplete")
    records = []
    for index in range(1, 4):
        path = EVIDENCE / f"{index:02d}--oracle_entry.json"
        item = json.loads(path.read_text(encoding="utf-8"))
        state, entry = item["state"], item["catalog_entry"]
        if item["oracle_label"] != study.ORACLE.decide(state, entry):
            raise ValueError("Oracle label does not reproduce")
        if set(entry["outcomes"]) != set(study.MODES):
            raise ValueError("Incomplete four-mode outcome catalog")
        if set(item["outcome_completeness"].values()) != {"COMPLETE"}:
            raise ValueError("Censored or unaudited outcome")
        for outcome in entry["outcomes"].values():
            locator, expected_hash = outcome["evidence_source"].split("#sha256=")
            if study.digest(ROOT / locator) != expected_hash:
                raise ValueError(f"Outcome source mismatch: {locator}")
        records.append(item)
    if [item["state"]["state_id"] for item in records] != [
            row["state_id"] for row in study.declarations()[1]["states"]]:
        raise ValueError("State membership or order changed")
    return {
        "benchmark_id": "phase3b0a_frozen_distinct_state_acquisition_v1",
        "status": "DEVELOPMENT_ONLY",
        "contract_id": study.ORACLE.CONTRACT_ID,
        "source_manifest": "experiments/phase3b/decision_benchmark_acquisition_001/evidence_manifest_attempt02.json",
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "first_attempt_manifest_sha256": study.amendment()["first_attempt"]["evidence_manifest_sha256"],
        "records": records,
        "readiness_verdict": "RECOVERY_VOCABULARY_NOT_READY",
    }


if __name__ == "__main__":
    if OUT.exists():
        raise FileExistsError(OUT)
    OUT.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
