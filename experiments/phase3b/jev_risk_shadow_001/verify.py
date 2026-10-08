"""Read-only Phase 3B.1 cohort-count and source-integrity audit; never calls Jev."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def verify() -> dict:
    manifest = read("experiments/phase3b/jev_risk_shadow_001/source_manifest.json")
    sources = manifest["sources"]
    if len(sources) != 13 or len({row["path"] for row in sources}) != 13:
        raise ValueError("Source membership changed")
    for row in sources:
        path = (ROOT / row["path"]).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Source drift: {row['path']}")

    phase12 = read("experiments/baselines/g1_failure_boundary_001/summary.json")
    strata = [row for experiment in phase12["experiments"].values() for row in experiment["final"]]
    p12_runs = sum(row["n_runs"] for row in strata)
    p12_pass = sum(row["task_successes"] for row in strata)
    if (p12_runs, p12_pass) != (57, 31):
        raise ValueError("Phase 1.2 final-stratum counts changed")

    boundary = read("experiments/baselines/g1_distance_segmentation_001/distance_boundary.json")
    distinct = {row["value"]: row["task_success_rate"] for row in boundary["final_observations"]}
    if distinct != {2.0: 1.0, 4.4375: 1.0, 4.53125: 1.0, 4.625: 0.0}:
        raise ValueError("Phase 1.2b unique distance boundary changed")

    comparison = read("experiments/baselines/g1_closed_loop_correction_001/correction_comparison.json")
    open_loop = {float(distance): rows["treatments"]["open_loop"]["task_success"]
                 for distance, rows in comparison["distances"].items() if float(distance) in {4, 6, 8, 10}}
    if open_loop != {4.0: True, 6.0: False, 8.0: False, 10.0: False}:
        raise ValueError("Phase 1.3 open-loop comparison changed")

    baseline = read("experiments/phase3a/transition_learning_001/evidence/baseline/evaluation_summary.json")
    cases = [row for row in baseline["records"] if row["treatment"] == "frozen_baseline"]
    group_counts = {group: {"n": sum(row["group"] == group for row in cases),
                            "fail": sum(row["group"] == group and not row["task_success"] for row in cases)}
                    for group in ("primitive", "transition", "sequence")}
    failures = sorted(row["case_id"] for row in cases if not row["task_success"])
    if (len(cases) != 26 or group_counts != {"primitive": {"n": 8, "fail": 1},
                                            "transition": {"n": 16, "fail": 0},
                                            "sequence": {"n": 2, "fail": 2}}
            or failures != ["primitive-walk-8", "sequence-mixed-12m", "sequence-mixed-16m"]):
        raise ValueError("Phase 3A baseline case/label distribution changed")

    decision = read("experiments/phase3b/jev_risk_shadow_001/readiness.json")
    benchmark = read("experiments/phase3b/jev_risk_shadow_001/benchmark.json")
    protocol = read("experiments/phase3b/jev_risk_shadow_001/protocol.json")
    if decision["verdict"] != "PENDING_SCORED_EVALUATION" or decision["scored_calls"] != 0:
        raise ValueError("Risk-shadow readiness drift")
    if benchmark["counts"]["source_cells"] != 24 or benchmark["counts"]["strict_fail_cells"] != 11:
        raise ValueError("Risk cohort membership/labels drift")
    if any(len(benchmark["assessment_units"][v]) != 18 for v in ("geometry_only", "geometry_plus_velocity")):
        raise ValueError("Risk cohort input partition drift")
    if any(benchmark["view_equivalence"][v]["same_input_opposite_label_hashes"] for v in ("geometry_only", "geometry_plus_velocity")):
        raise ValueError("Conflicting labels for identical model input")
    if protocol["decision_threshold"] != 0.5 or protocol["low_confidence_cutoff"] != 0.6:
        raise ValueError("Risk threshold drift")
    for path, expected in benchmark["source_hashes"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Benchmark source drift: {path}")
    return {"verified_sources": len(sources), "phase12_final": {"runs": p12_runs, "pass": p12_pass,
            "fail": p12_runs - p12_pass}, "phase12b_unique_distances": distinct,
            "phase13_open_loop": open_loop, "phase3a_frozen_baseline": group_counts,
            "verdict": decision["verdict"], "scored_calls": 0,
            "risk_cells": 24, "risk_assessment_units_per_view": 18}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
