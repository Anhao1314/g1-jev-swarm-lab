"""Build a source-bound, decision-time walk-node strict-risk cohort.

This module is deliberately offline.  It reads retained Phase 3A evidence and
never runs physics or a provider.  Only ``build()`` returns data; a file is
written solely when the CLI is explicitly given ``--output``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EVALUATION = ROOT / "experiments/phase3a/transition_learning_001/evidence/baseline/evaluation_summary.json"
MANIFEST = ROOT / "experiments/phase3a/transition_learning_001/case_manifest.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_cases(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for category, rows in data.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                continue
            if row["id"] in cases:
                raise ValueError(f"duplicate manifest case ID: {row['id']}")
            cases[row["id"]] = {"category": category, **row}
    return cases


def _state(case: dict[str, Any], node: dict[str, Any], node_index: int) -> dict[str, Any]:
    planned_nodes = case["nodes"]
    planned = planned_nodes[node_index]
    if planned["skill"] != "walk_forward" or planned["parameters"] != node["parameters"]:
        raise ValueError("planned walk node differs from evaluated node")
    start = node["start_state"]
    required = ("base_position", "base_orientation", "linear_velocity", "angular_velocity")
    if any(key not in start for key in required):
        raise ValueError("missing predecision state")
    # No future nodes, node metrics, end state, case ID, family or outcome can
    # enter this object.  It is the sole object intended for model input.
    return {
        "current_skill": planned["skill"],
        "current_parameters": planned["parameters"],
        "planned_prefix": planned_nodes[:node_index],
        "initial_yaw_deg": case["initial_yaw_deg"],
        "predecision": {key: start[key] for key in required},
    }


def _views(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    distance = float(state["current_parameters"]["target_distance_m"])
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("invalid planned walk distance")
    route_heading_deg = float(state["initial_yaw_deg"])
    planned_x = 0.0
    planned_y = 0.0
    for prior in state["planned_prefix"]:
        if prior["skill"] == "walk_forward":
            prior_distance = float(prior["parameters"]["target_distance_m"])
            planned_x += prior_distance * math.cos(math.radians(route_heading_deg))
            planned_y += prior_distance * math.sin(math.radians(route_heading_deg))
        elif prior["skill"] == "turn":
            route_heading_deg += float(prior["parameters"]["target_angle_deg"])
    theta = math.radians(route_heading_deg)
    actual_x, actual_y = state["predecision"]["base_position"][:2]
    dx = actual_x - planned_x
    dy = actual_y - planned_y
    qw, qx, qy, qz = state["predecision"]["base_orientation"]
    actual_heading_deg = math.degrees(math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)))
    heading_error_deg = (actual_heading_deg - route_heading_deg + 180.0) % 360.0 - 180.0
    vx, vy = state["predecision"]["linear_velocity"][:2]
    yaw_rate = state["predecision"]["angular_velocity"][2]
    strict_limits = {
        "distance_error_max_m": max(0.15, 0.05 * distance),
        "lateral_drift_max_m": max(0.20, 0.035 * distance),
        "heading_error_max_deg": 8.0,
        "timeout_max_s": max(12.0, 5.0 * distance),
    }
    geometry = {
        "controller": "phase3a_frozen_baseline",
        "decision_epoch": "walk_node_start",
        "previous_skill": state["planned_prefix"][-1]["skill"] if state["planned_prefix"] else None,
        "target_distance_m": distance,
        "commanded_speed_mps": float(state["current_parameters"]["speed_mps"]),
        "route_frame_position_error_m": {
            "forward": dx * math.cos(theta) + dy * math.sin(theta),
            "lateral": -dx * math.sin(theta) + dy * math.cos(theta),
        },
        "route_heading_error_deg": heading_error_deg,
        "strict_limits": strict_limits,
    }
    return {
        "geometry_only": geometry,
        "geometry_plus_velocity": {
            **geometry,
            "route_frame_velocity": {
                "forward_mps": vx * math.cos(theta) + vy * math.sin(theta),
                "lateral_mps": -vx * math.sin(theta) + vy * math.cos(theta),
                "yaw_rate_radps": yaw_rate,
            },
        },
    }


def build() -> dict[str, Any]:
    source = json.loads(EVALUATION.read_text(encoding="utf-8"))
    cases = _manifest_cases(json.loads(MANIFEST.read_text(encoding="utf-8")))
    cells: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, Any]] = {}
    for record in source["records"]:
        if record.get("treatment") != "frozen_baseline":
            continue
        case_id = record["case_id"]
        case = cases.get(case_id)
        if case is None:
            raise ValueError(f"missing planned case: {case_id}")
        if len(record["nodes"]) != len(case["nodes"]):
            raise ValueError(f"evaluated/planned node count mismatch: {case_id}")
        if record["group"] != case["group"]:
            raise ValueError(f"case family mismatch: {case_id}")
        for index, node in enumerate(record["nodes"]):
            if node["skill"] != "walk_forward" or not isinstance(node.get("strict_success"), bool):
                continue
            strict = node["envelope"]["strict_envelope"]["satisfied"]
            if strict is not node["strict_success"]:
                raise ValueError(f"strict label/evaluator mismatch: {case_id}:{index}")
            visible = _state(case, node, index)
            views = _views(visible)
            actual_limits = node["envelope"]["strict_envelope"]["limits"]
            for key, expected in views["geometry_only"]["strict_limits"].items():
                if not math.isclose(float(actual_limits[key]), expected, abs_tol=1e-12):
                    raise ValueError(f"strict contract mismatch: {case_id}:{index}:{key}")
            state_hash = hashlib.sha256(_canonical(visible)).hexdigest()
            cell_id = f"{case_id}:node-{index}"
            cell = {
                "cell_id": cell_id,
                "case_id": case_id,
                "node_index": index,
                "family": case["group"],
                "state_sha256": state_hash,
                "strict_violation": not strict,
                "task_success": node["task_success"],
            }
            cells.append(cell)
            if state_hash not in grouped:
                grouped[state_hash] = {
                    "state_sha256": state_hash,
                    "base_state": visible,
                    "views": views,
                    "strict_violation": not strict,
                    "source_cell_ids": [],
                    "source_case_ids": [],
                    "families": [],
                }
            entry = grouped[state_hash]
            if entry["base_state"] != visible or entry["strict_violation"] is not (not strict):
                raise ValueError(f"conflicting duplicate decision state: {cell_id}")
            entry["source_cell_ids"].append(cell_id)
            if case_id not in entry["source_case_ids"]:
                entry["source_case_ids"].append(case_id)
            if case["group"] not in entry["families"]:
                entry["families"].append(case["group"])
    states = list(grouped.values())
    duplicates = [
        {"state_sha256": row["state_sha256"], "cell_ids": row["source_cell_ids"]}
        for row in states if len(row["source_cell_ids"]) > 1
    ]
    labels = Counter(row["strict_violation"] for row in states)
    family_counts = {
        family: {
            "cells": sum(cell["family"] == family for cell in cells),
            "strict_fail_cells": sum(cell["family"] == family and cell["strict_violation"] for cell in cells),
        }
        for family in sorted({cell["family"] for cell in cells})
    }
    view_equivalence = {}
    assessment_units = {}
    for variant in ("geometry_only", "geometry_plus_velocity"):
        view_groups: dict[str, list[dict[str, Any]]] = {}
        for row in states:
            digest = hashlib.sha256(_canonical(row["views"][variant])).hexdigest()
            view_groups.setdefault(digest, []).append(row)
        conflicts = [
            digest for digest, rows in view_groups.items()
            if len({row["strict_violation"] for row in rows}) > 1
        ]
        view_equivalence[variant] = {
            "unique_model_inputs": len(view_groups),
            "same_input_same_label_groups": [
                {"view_sha256": digest, "base_state_sha256": [row["state_sha256"] for row in rows]}
                for digest, rows in view_groups.items() if len(rows) > 1
            ],
            "same_input_opposite_label_hashes": conflicts,
        }
        if conflicts:
            raise ValueError(f"opposite labels for identical {variant} model input")
        assessment_units[variant] = [
            {
                "view_sha256": digest,
                "paired_unit_id": hashlib.sha256(_canonical(sorted(row["state_sha256"] for row in rows))).hexdigest(),
                "strict_violation": rows[0]["strict_violation"],
                "base_state_sha256": [row["state_sha256"] for row in rows],
                "source_cell_ids": [cell_id for row in rows for cell_id in row["source_cell_ids"]],
                "source_case_ids": sorted({case_id for row in rows for case_id in row["source_case_ids"]}),
                "families": sorted({family for row in rows for family in row["families"]}),
            }
            for digest, rows in view_groups.items()
        ]
    paired_a = {unit["paired_unit_id"] for unit in assessment_units["geometry_only"]}
    paired_b = {unit["paired_unit_id"] for unit in assessment_units["geometry_plus_velocity"]}
    return {
        "schema": "phase3b1_walk_node_strict_risk_v1",
        "status": "seen_development_evidence_only",
        "target": "current_walk_node_future_strict_violation",
        "source_hashes": {
            EVALUATION.relative_to(ROOT).as_posix(): _sha256(EVALUATION),
            MANIFEST.relative_to(ROOT).as_posix(): _sha256(MANIFEST),
        },
        "usage": "zero_shot_offline_assessment_only; no training, development tuning or fresh held-out claim",
        "model_input_fields": ["states[].views.geometry_only", "states[].views.geometry_plus_velocity"],
        "cells": cells,
        "states": states,
        "duplicate_clusters": duplicates,
        "view_equivalence": view_equivalence,
        "assessment_units": assessment_units,
        "paired_unit_identity": {
            "same_partition_across_views": paired_a == paired_b,
            "paired_unit_count": len(paired_a & paired_b),
        },
        "correlation_unit": "mission_case_id; sequence nodes from one mission are not independent",
        "counts": {
            "source_cells": len(cells),
            "unique_states": len(states),
            "strict_fail_cells": sum(cell["strict_violation"] for cell in cells),
            "strict_pass_cells": sum(not cell["strict_violation"] for cell in cells),
            "strict_fail_states": labels[True],
            "strict_pass_states": labels[False],
            "family": family_counts,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="explicit output path")
    args = parser.parse_args()
    output = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
