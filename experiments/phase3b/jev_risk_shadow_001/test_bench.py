"""Focused offline checks for the retained strict-risk node cohort."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).with_name("bench.py")
SPEC = importlib.util.spec_from_file_location("phase3b1_bench", MODULE)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_cohort_counts_and_family_clusters() -> None:
    result = bench.build()
    assert result["counts"]["source_cells"] == 24
    assert result["counts"]["unique_states"] == 20
    assert result["counts"]["strict_fail_cells"] == 11
    assert result["counts"]["strict_pass_cells"] == 13
    assert result["counts"]["strict_fail_states"] == 11
    assert result["counts"]["strict_pass_states"] == 9
    assert result["counts"]["family"] == {
        "primitive": {"cells": 2, "strict_fail_cells": 2},
        "sequence": {"cells": 6, "strict_fail_cells": 6},
        "transition": {"cells": 16, "strict_fail_cells": 3},
    }
    assert sorted(len(row["cell_ids"]) for row in result["duplicate_clusters"]) == [3, 3]
    assert len({row["case_id"] for row in result["cells"] if row["family"] == "sequence"}) == 2


def test_model_visible_state_is_predecision_only() -> None:
    result = bench.build()
    forbidden = (
        "case_id", "family", "strict", "task_success", "end_state", "envelope",
        "failure", "future", "outcome", "metrics", "trace", "duration_s",
    )
    for row in result["states"]:
        state = row["base_state"]
        assert set(state) == {
            "current_skill", "current_parameters", "planned_prefix",
            "initial_yaw_deg", "predecision",
        }
        assert set(state["predecision"]) == {
            "base_position", "base_orientation", "linear_velocity", "angular_velocity"
        }
        assert all(term not in state for term in forbidden)
        geometry = row["views"]["geometry_only"]
        velocity = row["views"]["geometry_plus_velocity"]
        assert set(geometry) == {
            "controller", "decision_epoch", "previous_skill", "target_distance_m",
            "commanded_speed_mps", "route_frame_position_error_m",
            "route_heading_error_deg", "strict_limits",
        }
        assert "route_frame_velocity" not in geometry
        assert {k: v for k, v in velocity.items() if k != "route_frame_velocity"} == geometry
        assert set(velocity["route_frame_velocity"]) == {
            "forward_mps", "lateral_mps", "yaw_rate_radps"
        }
        distance = geometry["target_distance_m"]
        assert geometry["strict_limits"] == {
            "distance_error_max_m": max(0.15, 0.05 * distance),
            "lateral_drift_max_m": max(0.20, 0.035 * distance),
            "heading_error_max_deg": 8.0,
            "timeout_max_s": max(12.0, 5.0 * distance),
        }
    assert result["model_input_fields"] == [
        "states[].views.geometry_only", "states[].views.geometry_plus_velocity"
    ]
    for variant in ("geometry_only", "geometry_plus_velocity"):
        equivalence = result["view_equivalence"][variant]
        assert equivalence["unique_model_inputs"] == 18
        assert len(equivalence["same_input_same_label_groups"]) == 2
        assert equivalence["same_input_opposite_label_hashes"] == []
        units = result["assessment_units"][variant]
        assert len(units) == 18
        assert len({unit["view_sha256"] for unit in units}) == 18
        assert sum(unit["strict_violation"] for unit in units) == 11
        assert sum(not unit["strict_violation"] for unit in units) == 7
        assert sum(len(unit["source_cell_ids"]) for unit in units) == 24
        assert set(cell for unit in units for cell in unit["source_cell_ids"]) == {
            cell["cell_id"] for cell in result["cells"]
        }
    assert result["paired_unit_identity"] == {
        "same_partition_across_views": True,
        "paired_unit_count": 18,
    }
    assert {
        unit["paired_unit_id"] for unit in result["assessment_units"]["geometry_only"]
    } == {
        unit["paired_unit_id"] for unit in result["assessment_units"]["geometry_plus_velocity"]
    }


def test_source_binding_and_label_consistency() -> None:
    result = bench.build()
    assert set(result["source_hashes"]) == {
        bench.EVALUATION.relative_to(bench.ROOT).as_posix(),
        bench.MANIFEST.relative_to(bench.ROOT).as_posix(),
    }
    assert all(len(digest) == 64 for digest in result["source_hashes"].values())
    by_hash = {row["state_sha256"]: row for row in result["states"]}
    for cell in result["cells"]:
        assert cell["strict_violation"] == by_hash[cell["state_sha256"]]["strict_violation"]
        assert cell["cell_id"] in by_hash[cell["state_sha256"]]["source_cell_ids"]
    # Four task successes still violate strict; the two labels must not alias.
    assert sum(cell["task_success"] and cell["strict_violation"] for cell in result["cells"]) == 4


def test_conflicting_planned_node_fails_closed() -> None:
    source = bench.json.loads(bench.EVALUATION.read_text(encoding="utf-8"))
    cases = bench._manifest_cases(bench.json.loads(bench.MANIFEST.read_text(encoding="utf-8")))
    record = next(row for row in source["records"] if row["treatment"] == "frozen_baseline")
    case = cases[record["case_id"]]
    node = record["nodes"][0]
    case["nodes"][0]["parameters"]["target_distance_m"] = -1
    with pytest.raises(ValueError, match="planned walk node differs"):
        bench._state(case, node, 0)
