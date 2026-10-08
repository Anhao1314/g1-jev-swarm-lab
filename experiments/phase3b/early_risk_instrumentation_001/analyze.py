"""Frozen, descriptive analysis of the completed 3B.1b observer evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from acquire import HERE, validate_membership, validate_observation
from observer import CHECKPOINTS, assert_equivalent


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict:
    protocol, cases, historical = validate_membership()
    artifacts = HERE / "artifacts"
    completed = _read(artifacts / "resumed_completed.json")
    if completed["status"] != "ACQUISITION_COMPLETE" or completed["executions"] != 14:
        raise ValueError("Frozen acquisition incomplete")
    evidence_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(artifacts.iterdir()) if path.is_file()}
    by_case = {}
    for case, nodes in cases:
        off = _read(artifacts / f"{case['id']}.observer_off.json")
        on = _read(artifacts / f"{case['id']}.observer_on.json")
        assert_equivalent(off, on)
        validate_observation(case, nodes, on, historical)
        by_case[case["id"]] = (case, on)
    repo = HERE.parents[2]
    benchmark = _read(repo / protocol["historical_cohort"])
    strict_limits = {cell_id: state["views"]["geometry_only"]["strict_limits"]
                     for state in benchmark["states"] for cell_id in state["source_cell_ids"]}
    rows = []
    for selected in protocol["selected_nodes"]:
        case_id, node_str = selected["cell_id"].split(":node-")
        node_index = int(node_str)
        case, on = by_case[case_id]
        node = on["record"]["nodes"][node_index]
        target = float(case["nodes"][node_index]["parameters"]["target_distance_m"])
        shots = [on["observer"]["snapshots"][f"{node_index}:{time:g}"] for time in CHECKPOINTS]
        limits = strict_limits[selected["cell_id"]]
        fixed_flags = [abs(s["local_lateral_m"]) > limits["lateral_drift_max_m"] or
                       abs(s["local_heading_error_deg"]) > limits["heading_error_max_deg"]
                       for s in shots]
        rows.append({
            "cell_id": selected["cell_id"], "prior_class": selected["prior_class"],
            "strict_violation": not node["strict_success"], "target_distance_m": target,
            "strict_limits": limits, "snapshots": shots,
            "fixed_local_limit_risk_flags": fixed_flags,
            "local_lateral_delta_0_1_m": shots[1]["local_lateral_m"] - shots[0]["local_lateral_m"],
            "local_lateral_delta_0_2_m": shots[2]["local_lateral_m"] - shots[0]["local_lateral_m"],
            "reference_lateral_delta_0_2_m": shots[2]["reference_lateral_m"] - shots[0]["reference_lateral_m"],
            "local_heading_delta_0_2_deg": shots[2]["local_heading_error_deg"] - shots[0]["local_heading_error_deg"],
            "reference_heading_delta_0_2_deg": shots[2]["reference_heading_error_deg"] - shots[0]["reference_heading_error_deg"],
            "endpoint_strict_violations": node["envelope"]["strict_envelope"]["violations"],
        })
    if len(rows) != 8 or sum(row["strict_violation"] for row in rows) != 5:
        raise ValueError("Selected outcomes drift")
    fixed = {}
    for index, time in enumerate(CHECKPOINTS):
        fixed[str(int(time))] = {
            "true_positive": sum(r["strict_violation"] and r["fixed_local_limit_risk_flags"][index] for r in rows),
            "false_safe": sum(r["strict_violation"] and not r["fixed_local_limit_risk_flags"][index] for r in rows),
            "true_safe": sum(not r["strict_violation"] and not r["fixed_local_limit_risk_flags"][index] for r in rows),
            "false_alarm": sum(not r["strict_violation"] and r["fixed_local_limit_risk_flags"][index] for r in rows),
        }
    return {
        "schema": "phase3b1b_early_risk_analysis_v1", "use": "seen development mechanism only",
        "source_commit": protocol["source_commit"],
        "case_count": len(cases), "execution_count": completed["executions"],
        "selected_cells": len(rows), "strict_failures": 5, "strict_passes": 3,
        "fixed_rule_by_elapsed_s": fixed,
        "evidence_file_sha256": evidence_hashes,
        "rows": rows,
    }


if __name__ == "__main__":
    (HERE / "analysis.json").write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8", newline="\n")
