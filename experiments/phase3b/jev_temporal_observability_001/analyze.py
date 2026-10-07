"""Deterministic descriptive controls for frozen Phase 3B.1a evidence."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "jev_risk_shadow_001"


def build() -> dict:
    benchmark = json.loads((PRIOR / "benchmark.json").read_text(encoding="utf-8"))
    result = json.loads((PRIOR / "result.json").read_text(encoding="utf-8"))
    snapshots = json.loads((HERE / "snapshots.json").read_text(encoding="utf-8"))
    states = {row["state_sha256"]: row for row in benchmark["states"]}
    prior = {row["paired_unit_id"]: row for row in result["rows"] if row["variant"] == "geometry_only"}
    representative = {}
    for cell in sorted(snapshots["cells"], key=lambda row: row["cell_id"]):
        representative.setdefault(cell["prior_paired_unit_id"], cell)
    rows = []
    for unit in benchmark["assessment_units"]["geometry_only"]:
        key = unit["paired_unit_id"]
        view = states[unit["base_state_sha256"][0]]["views"]["geometry_only"]
        limits = view["strict_limits"]
        heading = abs(view["route_heading_error_deg"])
        lateral = abs(view["route_frame_position_error_m"]["lateral"])
        entry_limit_breach = heading > limits["heading_error_max_deg"] or lateral > limits["lateral_drift_max_m"]
        cell = representative[key]
        rows.append({
            "paired_unit_id": key,
            "representative_cell_id": cell["cell_id"],
            "prior_jev_class": cell["prior_jev_class"],
            "strict_violation": unit["strict_violation"],
            "entry_limit_breach": entry_limit_breach,
            "prior_jev_predicted_violation": prior[key]["predicted_strict_violation"],
            "entry_heading_error_abs_deg": heading,
            "entry_lateral_error_abs_m": lateral,
            "tilt_1s_deg": cell["snapshots"][1]["recorded"]["tilt_deg"],
            "tilt_2s_deg": cell["snapshots"][2]["recorded"]["tilt_deg"],
            "height_delta_2s_minus_entry_m": cell["predeclared_trend"]["height_delta_2s_minus_entry_m"],
        })
    classes = Counter(row["prior_jev_class"] for row in rows)
    if classes != {"true_safe": 7, "false_safe": 7, "true_positive": 4}:
        raise ValueError("prior classification drift")
    return {
        "schema": "phase3b1a_descriptive_analysis_v1",
        "usage": "seen-development descriptive controls only; no threshold fitting",
        "representative_rule": "lexicographically first source cell per prior visible unit; clustered cells retained in snapshots.json",
        "source_cells": 24,
        "visible_units": 18,
        "class_counts": dict(classes),
        "exact_opposite_label_aliases": len(benchmark["view_equivalence"]["geometry_only"]["same_input_opposite_label_hashes"]),
        "entry_contract_limit_rule": {
            "status": "post_hoc_contract_derived_descriptive_control",
            "definition": "abs(entry heading)>frozen heading limit OR abs(entry lateral)>frozen lateral limit",
            "agreement_with_prior_jev_binary": sum(r["entry_limit_breach"] == r["prior_jev_predicted_violation"] for r in rows),
            "accuracy": sum(r["entry_limit_breach"] == r["strict_violation"] for r in rows),
            "false_safe": sum(r["strict_violation"] and not r["entry_limit_breach"] for r in rows),
            "false_alarm": sum(not r["strict_violation"] and r["entry_limit_breach"] for r in rows),
        },
        "always_risk_control": {"accuracy": sum(r["strict_violation"] for r in rows), "false_safe": 0, "false_alarm": sum(not r["strict_violation"] for r in rows)},
        "rows": rows,
    }


if __name__ == "__main__":
    (HERE / "analysis.json").write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
