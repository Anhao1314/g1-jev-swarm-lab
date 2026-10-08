"""Focused checks of retained, paired observer evidence when available locally."""

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def test_frozen_acquisition_analysis():
    if not (HERE / "artifacts" / "resumed_completed.json").exists():
        pytest.skip("ignored local physics evidence is unavailable in this checkout")
    spec = importlib.util.spec_from_file_location("early_risk_analysis", HERE / "analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build()
    assert (result["case_count"], result["execution_count"], result["selected_cells"]) == (7, 14, 8)
    assert (result["strict_failures"], result["strict_passes"]) == (5, 3)
    assert all(value == {"true_positive": 0, "false_safe": 5, "true_safe": 3, "false_alarm": 0}
               for value in result["fixed_rule_by_elapsed_s"].values())
    rows = {row["cell_id"]: row for row in result["rows"]}
    safe = rows["eval-ws-01:node-0"]
    fail = rows["primitive-walk-4:node-0"]
    assert safe["target_distance_m"] != fail["target_distance_m"]
    for time in range(3):
        for field in ("local_lateral_m", "local_heading_error_deg", "reference_lateral_m",
                      "reference_heading_error_deg", "route_frame_vx_vy_mps", "yaw_rate_radps"):
            assert safe["snapshots"][time][field] == fail["snapshots"][time][field]
