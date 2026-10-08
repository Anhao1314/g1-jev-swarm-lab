"""Read-only source binding and frozen-readiness check for the Phase 3B.0b study."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def verify() -> dict:
    manifest = load("experiments/phase3b/recovery_vocabulary_reframing_001/source_manifest.json")
    paths = [item["path"] for item in manifest["sources"]]
    if len(paths) != 22 or len(set(paths)) != 22:
        raise ValueError("Source inventory membership changed")
    for item in manifest["sources"]:
        path = (ROOT / item["path"]).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Source drift: {item['path']}")
    benchmark = load("experiments/phase3b/decision_benchmark_acquisition_001/benchmark.json")
    spec = importlib.util.spec_from_file_location(
        "frozen_phase3b_oracle", ROOT / "experiments/phase3b/decision_oracle_001/oracle.py"
    )
    assert spec is not None and spec.loader is not None
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    labels = [oracle.decide(row["state"], row["catalog_entry"])["mode"] for row in benchmark["records"]]
    decision = load("experiments/phase3b/recovery_vocabulary_reframing_001/decision.json")
    if labels != ["ABSTAIN", "CONTINUE", "ABSTAIN"]:
        raise ValueError("Retained benchmark readiness changed")
    if (decision["verdict"] != "RECOVERY_VOCABULARY_NOT_READY"
            or decision["readiness_conditions"]["unique_admissible_recovery_under_one_matched_contract"] is not False
            or decision["new_physics"] != 0 or decision["jev_calls"] != 0):
        raise ValueError("Decision record exceeds evidence")
    return {"source_hashes_verified": len(paths), "frozen_oracle_labels": labels,
            "verdict": decision["verdict"], "new_physics": 0, "jev_calls": 0}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
