"""Synthetic saved-artifact checks; no MuJoCo, policy, or provider use."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
MODULE = importlib.util.spec_from_file_location("m25a_saved_audit", HERE / "audit.py")
assert MODULE is not None and MODULE.loader is not None
AUDIT = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(AUDIT)
SPEC = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, allow_nan=False) + "\n", encoding="utf8")


def journal(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows), encoding="utf8")


def snapshot(native_steps: int) -> dict:
    return {
        "time_s": native_steps * 0.002,
        "qpos": [native_steps * 0.0001, 0.0, 0.8, 1.0, 0.0, 0.0, 0.0],
        "qvel": [0.05, 0.0, 0.0, 0.0, 0.0, 0.0],
        "ctrl": [0.0], "xfrc_applied": [[0.0] * 6],
        "controller_action": [0.0], "controller_target": [0.0],
        "controller_counter": native_steps,
        "session_identity": 100, "simulation_identity": 101,
        "controller_identity": 102, "policy_identity": 103,
        "reset_calls": 2, "native_reset_calls": 2, "keyframe_reset_calls": 0,
        "controller_reset_calls": 2, "node_dispatches": 3,
        "executor_dispatches": 1, "native_steps": native_steps,
        "session_steps": native_steps,
    }


def make_hold_fixture(folder: Path) -> tuple[dict, dict]:
    folder.mkdir()
    cell = next(row for row in SPEC["cells_in_order"] if row["id"] == "normal_stop_hold_control")
    parent = {"state": "SUCCESS", "mission_success": True, "physical_success": True,
              "completed_nodes": 3, "physical_halt": None,
              "nodes": [{"skill": "walk_forward"}, {"skill": "turn"},
                        {"skill": "stop", "metrics": {"skill_status": "SUCCESS"}}]}
    save(folder / "parent_result.json", parent)
    save(folder / "parent_graph.json", {"nodes": ["s1", "s2", "s3"]})
    entry = snapshot(500)
    native = []
    for index in range(1, 1501):
        s = snapshot(index)
        native.append({"sequence": index, "phase": "parent" if index <= 500 else "hold",
                       "time_s": s["time_s"], "qpos": s["qpos"], "qvel": s["qvel"],
                       "ctrl": s["ctrl"], "xfrc_applied": s["xfrc_applied"], "raw_finite": True,
                       "controller": {"_counter": index, "_action": [0.0], "_target": [0.0]}})
    hold = []
    for index in range(1, 1001):
        s = snapshot(500 + index)
        hold.append({"hold_step": index, "native_sequence": 500 + index,
                     "time_s": s["time_s"], "position_m": s["qpos"][:3],
                     "speed_mps": 0.05, "base_height_m": 0.8,
                     "standing": True, "fallen": False, "finite": True,
                     "raw_finite": True, "orientation_wxyz": s["qpos"][3:7],
                     "controller_counter": 500 + index, "controller_action": [0.0],
                     "controller_target": [0.0], "contact_count": 2,
                     "mujoco_warning": None, "command_xyz_mps_radps": [0.0, 0.0, 0.0]})
    seed = [0.05] * 500
    terminal = {"stop_status": "SUCCESS", "stop_window_mean_mps": 0.05,
                "stop_crossing_time_s": 1.0, "stop_poststep_speeds": seed,
                "skill_return_snapshot": deepcopy(entry), "snapshot": deepcopy(entry)}
    save(folder / "hold_entry.json", {"terminal": terminal, "pre_first_step": deepcopy(entry),
                                      "seed_speeds_mps": seed})
    final = snapshot(1500)
    checks = {"complete_1000_steps": True, "rolling_mean": True, "final_speed": True,
              "xy_path_length": True, "finite_throughout": True,
              "standing_throughout": True, "no_fall_throughout": True}
    outcome = {"cell_id": cell["id"], "status": "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE",
               "coverage": "COMPLETE_HOLD", "checks": checks, "measured_steps": 1000,
               "xy_path_length_m": 0.1, "last_speed_mps": 0.05,
               "rolling_mean_speed_mps": [0.05] * 1000,
               "one_second_disjoint_means_mps": [0.05, 0.05],
               "maximum_instantaneous_speed_mps": 0.05,
               "hold_terminal": final, "hold_observed_steps": 1000,
               "native_steps": 1500}
    save(folder / "outcome.json", outcome)
    save(folder / "hold_metrics.json", {"result": outcome, "rows": hold})
    save(folder / "witness.json", {"attempt": 1, "native_steps": 1500,
                                   "native_journal_rows": 1500,
                                   "parent_native_steps": 500,
                                   "hold_native_steps": 1000,
                                   "hold_journal_rows": 1000,
                                   "hold_command_calls": 1000,
                                   "outcome_status": outcome["status"],
                                   "integrity_failure": None,
                                   "budget_failure": None,
                                   "terminal_snapshot": entry,
                                   "final_snapshot": final})
    journal(folder / "native_incremental.jsonl", native)
    journal(folder / "hold_incremental.jsonl", hold)
    return cell, outcome


def test_recomputes_all_seeded_windows_and_path_from_saved_rows(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    result = AUDIT.audit_cell(tmp_path / cell["id"], SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "PASS_RECOMPUTED", result
    assert result["classification"] == "BOUNDED_HOLD_IN_THIS_STATE"
    assert len(result["recomputed"]["rolling_means"]) == 1000
    assert abs(result["recomputed"]["xy_path_length_m"] - 0.1) < 1e-9


def test_false_success_from_last_speed_and_reset_is_rejected(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    folder = tmp_path / cell["id"]
    hold = AUDIT.read_jsonl(folder / "hold_incremental.jsonl")
    native = AUDIT.read_jsonl(folder / "native_incremental.jsonl")
    hold[-1]["speed_mps"] = 0.2
    native[-1]["qvel"][0] = 0.2
    journal(folder / "hold_incremental.jsonl", hold)
    journal(folder / "native_incremental.jsonl", native)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert result["scientific_status"] is None

    hold[-1]["speed_mps"] = 0.05
    native[-1]["qvel"][0] = 0.05
    journal(folder / "hold_incremental.jsonl", hold)
    journal(folder / "native_incremental.jsonl", native)
    outcome = AUDIT.read_json(folder / "outcome.json")
    outcome["hold_terminal"]["controller_reset_calls"] += 1
    save(folder / "outcome.json", outcome)
    save(folder / "hold_metrics.json", {"result": outcome, "rows": hold})
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert "RESET" in result["reason"]


def test_missing_seed_and_incomplete_hold_cannot_pass(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    folder = tmp_path / cell["id"]
    (folder / "hold_entry.json").unlink()
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "MISSING_EVIDENCE"

    make_hold_fixture(tmp_path / "other")
    folder = tmp_path / "other"
    hold = AUDIT.read_jsonl(folder / "hold_incremental.jsonl")[:-1]
    native = AUDIT.read_jsonl(folder / "native_incremental.jsonl")[:-1]
    journal(folder / "hold_incremental.jsonl", hold)
    journal(folder / "native_incremental.jsonl", native)
    witness = AUDIT.read_json(folder / "witness.json")
    witness.update(native_steps=len(native), native_journal_rows=len(native),
                   hold_native_steps=len(native) - 500, hold_journal_rows=len(hold))
    save(folder / "witness.json", witness)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert result["scientific_status"] is None


def test_no_halt_is_coverage_not_hold_failure(tmp_path):
    cell = SPEC["cells_in_order"][0]
    folder = tmp_path / cell["id"]
    folder.mkdir()
    save(folder / "parent_result.json", {"mission_success": True, "physical_halt": None})
    save(folder / "parent_graph.json", {"nodes": ["s1"]})
    save(folder / "outcome.json", {"cell_id": cell["id"],
                                   "status": "PARENT_PASS_NO_HALT_NO_HOLD", "coverage": "NO_HOLD"})
    save(folder / "witness.json", {"attempt": 1, "native_steps": 0,
                                   "native_journal_rows": 0,
                                   "parent_native_steps": 0,
                                   "hold_native_steps": 0,
                                   "hold_journal_rows": 0,
                                   "hold_command_calls": 0,
                                   "outcome_status": "PARENT_PASS_NO_HALT_NO_HOLD",
                                   "integrity_failure": None,
                                   "budget_failure": None})
    journal(folder / "native_incremental.jsonl", [])
    journal(folder / "hold_incremental.jsonl", [])
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "PASS_RECORDED_NO_HOLD", result
    assert result["classification"] == "NO_HOLD_COVERAGE"


def test_archived_parent_prefix_is_independently_sealed_and_compared(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    rows = AUDIT.read_jsonl(tmp_path / cell["id"] / "native_incremental.jsonl")[:500]
    root = tmp_path / "historical"
    arm = cell["m24_state"] + "--" + cell["historical_arm"]
    member = ("experiments/m2/cross_state_reliability_001/artifacts/"
              + arm + "/predecision_native_trace.json")
    raw = json.dumps(rows).encode()
    result_member = ("experiments/m2/cross_state_reliability_001/artifacts/"
                     + arm + "/parent_result.json")
    parent = AUDIT.read_json(tmp_path / cell["id"] / "parent_result.json")
    parent_raw = json.dumps(parent).encode()
    archive_dir = root / "experiments/m2/cross_state_reliability_archives_001"
    analysis_dir = root / "experiments/m2/cross_state_reliability_analysis_001"
    archive_dir.mkdir(parents=True)
    analysis_dir.mkdir(parents=True)
    archive = archive_dir / (arm + ".tar.gz")
    with tarfile.open(archive, "w:gz") as stream:
        info = tarfile.TarInfo(member)
        info.size = len(raw)
        stream.addfile(info, io.BytesIO(raw))
        info = tarfile.TarInfo(result_member)
        info.size = len(parent_raw)
        stream.addfile(info, io.BytesIO(parent_raw))
    save(archive_dir / "manifest.json", {"archives": {
        archive.name: {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}}})
    save(analysis_dir / "raw_evidence_manifest.json", {"files": {
        member: {"sha256": hashlib.sha256(raw).hexdigest()},
        result_member: {"sha256": hashlib.sha256(parent_raw).hexdigest()}}})
    verified = AUDIT.verify_historical_parent_prefix(rows, cell, root=root)
    assert verified["steps"] == 500
    assert verified["historical_member_sha256"] == hashlib.sha256(raw).hexdigest()
    result_receipt = AUDIT.verify_historical_parent_result(parent, cell, root=root)
    assert result_receipt["nodes"] == 3
    changed_parent = deepcopy(parent)
    changed_parent["nodes"][-1]["metrics"]["skill_status"] = "TIMEOUT"
    try:
        AUDIT.verify_historical_parent_result(changed_parent, cell, root=root)
    except AUDIT.EvidenceError as exc:
        assert exc.category == "INTEGRITY_FAILURE"
        assert "STRICT_METRICS_CHANGED" in exc.reason
    else:
        raise AssertionError("changed strict/Stop scoring was accepted")
    altered = deepcopy(rows)
    altered[42]["qvel"][0] = 1.0
    try:
        AUDIT.verify_historical_parent_prefix(altered, cell, root=root)
    except AUDIT.EvidenceError as exc:
        assert exc.category == "INTEGRITY_FAILURE"
        assert "PREFIX_MISMATCH" in exc.reason
    else:
        raise AssertionError("changed parent was accepted")


def test_partial_campaign_never_becomes_complete_pass(tmp_path):
    save(tmp_path / "campaign_receipt.json", {
        "status": "PARTIAL_STOPPED", "reason": "HARD_WALL_WATCHDOG",
        "completed_cells": [], "failed_cell": SPEC["cells_in_order"][0]["id"],
        "frozen_cells": [cell["id"] for cell in SPEC["cells_in_order"]],
        "no_retry": True,
    })
    result = AUDIT.audit_campaign(tmp_path, verify_sources=False, verify_prefix=False)
    assert result["status"] == "AUDIT_PARTIAL_RETAINED"
    assert result["native_steps"] == 0


def test_partial_cell_with_unsealed_native_rows_is_missing_not_science(tmp_path):
    cell = SPEC["cells_in_order"][0]
    folder = tmp_path / cell["id"]
    folder.mkdir()
    journal(folder / "native_incremental.jsonl", [{"sequence": 1, "phase": "parent"}])
    journal(folder / "hold_incremental.jsonl", [])
    save(tmp_path / "campaign_receipt.json", {
        "status": "PARTIAL_STOPPED", "reason": "WORKER_EXIT",
        "completed_cells": [], "failed_cell": cell["id"],
        "frozen_cells": [item["id"] for item in SPEC["cells_in_order"]],
        "no_retry": True,
    })
    result = AUDIT.audit_campaign(tmp_path, verify_sources=False, verify_prefix=False)
    assert result["status"] == "AUDIT_INCOMPLETE_OR_INVALID"
    assert result["cells"][0]["audit_status"] == "MISSING_EVIDENCE"
    assert result["cells"][0]["scientific_status"] is None


def test_eligible_parent_missing_seed_is_coverage_missing_not_hold_failure(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    folder = tmp_path / cell["id"]
    (folder / "hold_entry.json").unlink()
    (folder / "hold_metrics.json").unlink()
    journal(folder / "native_incremental.jsonl",
            AUDIT.read_jsonl(folder / "native_incremental.jsonl")[:500])
    journal(folder / "hold_incremental.jsonl", [])
    outcome = {"cell_id": cell["id"], "status": "INCONCLUSIVE_MISSING_EVIDENCE",
               "coverage": "NO_HOLD", "reason": "FIRST_CROSSING_WINDOW_MISSING"}
    save(folder / "outcome.json", outcome)
    witness = AUDIT.read_json(folder / "witness.json")
    witness.update(native_steps=500, native_journal_rows=500,
                   hold_native_steps=0, hold_journal_rows=0,
                   hold_command_calls=0, outcome_status=outcome["status"])
    save(folder / "witness.json", witness)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "MISSING_EVIDENCE"
    assert result["classification"] == "ELIGIBLE_NO_HOLD_MISSING_SOURCE"
    assert result["scientific_status"] is None


def test_first_stop_crossing_replayed_from_full_prior_trace():
    valid = AUDIT.verify_first_stop_crossing([50.0] + [0.05] * 500,
                                             window=500, threshold=0.1,
                                             reported_mean=0.05)
    assert valid["first_qualifying_stop_step"] == 501
    try:
        AUDIT.verify_first_stop_crossing([0.05] * 501, window=500,
                                         threshold=0.1, reported_mean=0.05)
    except AUDIT.EvidenceError as exc:
        assert exc.reason == "PRIOR_STOP_WINDOW_ALREADY_QUALIFIED"
    else:
        raise AssertionError("a late first-crossing claim was accepted")


def test_raw_posture_flags_and_final_state_cannot_be_tampered(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    folder = tmp_path / cell["id"]
    hold = AUDIT.read_jsonl(folder / "hold_incremental.jsonl")
    hold[37]["standing"] = False  # raw qpos remains upright at 0.8 m.
    journal(folder / "hold_incremental.jsonl", hold)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert result["reason"] == "HOLD_PHYSICAL_FLAG_MISMATCH:standing"

    hold[37]["standing"] = True
    journal(folder / "hold_incremental.jsonl", hold)
    outcome = AUDIT.read_json(folder / "outcome.json")
    outcome["hold_terminal"]["qpos"][0] += 0.01
    save(folder / "outcome.json", outcome)
    save(folder / "hold_metrics.json", {"result": outcome, "rows": hold})
    witness = AUDIT.read_json(folder / "witness.json")
    witness["final_snapshot"] = outcome["hold_terminal"]
    save(folder / "witness.json", witness)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert result["reason"] == "FINAL_SNAPSHOT_NATIVE_MISMATCH:qpos"


def test_raw_only_nonfinite_failure_requires_qpos_or_qvel_nonfinite(tmp_path):
    cell, _ = make_hold_fixture(tmp_path / "normal_stop_hold_control")
    folder = tmp_path / cell["id"]
    hold = AUDIT.read_jsonl(folder / "hold_incremental.jsonl")[:-1]
    native = AUDIT.read_jsonl(folder / "native_incremental.jsonl")
    # A broken force/ctrl witness cannot be presented as G1Simulation's
    # physical qpos/qvel nonfinite failure, even if raw_finite is false.
    native[-1]["ctrl"] = [{"nonfinite": "nan"}]
    native[-1]["raw_finite"] = False
    journal(folder / "hold_incremental.jsonl", hold)
    journal(folder / "native_incremental.jsonl", native)
    outcome = AUDIT.read_json(folder / "outcome.json")
    outcome.update(status="HOLD_FAILED", coverage="PARTIAL_PHYSICAL_NONFINITE",
                   hold_observed_steps=999, native_steps=1500,
                   reason="NONFINITE_PHYSICAL_STATE")
    save(folder / "outcome.json", outcome)
    save(folder / "hold_metrics.json", {"result": outcome, "rows": hold})
    witness = AUDIT.read_json(folder / "witness.json")
    witness.update(hold_journal_rows=999, outcome_status="HOLD_FAILED")
    save(folder / "witness.json", witness)
    result = AUDIT.audit_cell(folder, SPEC, cell, verify_prefix=False)
    assert result["audit_status"] == "INTEGRITY_FAILURE"
    assert result["reason"] == "NONFINITE_PHYSICAL_FAILURE_WITHOUT_QPOS_QVEL_NONFINITE"
