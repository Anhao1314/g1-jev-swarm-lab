"""Independent, read-only M2.5A saved-evidence audit; never imports physics.

This module deliberately recomputes the hold score from the native and hold
journals instead of accepting the acquisition worker's summary. A physical
failure is still a valid recorded result; missing or inconsistent evidence is
not converted into a scientific result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tarfile
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SNAPSHOT_KEYS = (
    "time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller_action",
    "controller_target", "controller_counter", "session_identity",
    "simulation_identity", "controller_identity", "policy_identity", "reset_calls",
    "native_reset_calls", "keyframe_reset_calls", "controller_reset_calls",
    "node_dispatches", "executor_dispatches", "native_steps", "session_steps",
)
COUNTER_KEYS = (
    "reset_calls", "native_reset_calls", "keyframe_reset_calls",
    "controller_reset_calls", "node_dispatches", "executor_dispatches",
)
IDENTITY_KEYS = (
    "session_identity", "simulation_identity", "controller_identity", "policy_identity",
)


class EvidenceError(Exception):
    def __init__(self, category: str, reason: str):
        self.category = category
        self.reason = reason
        super().__init__(reason)


def need(condition: bool, reason: str, category: str = "INTEGRITY_FAILURE") -> None:
    if not condition:
        raise EvidenceError(category, reason)


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise EvidenceError("MISSING_EVIDENCE", "MISSING_FILE:" + path.name)
    try:
        value = json.loads(path.read_text(encoding="utf8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("TECHNICAL_PARTIAL", "UNREADABLE_JSON:" + path.name) from exc
    need(isinstance(value, dict), "JSON_OBJECT_REQUIRED:" + path.name)
    return value


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise EvidenceError("MISSING_EVIDENCE", "MISSING_FILE:" + path.name)
    rows = []
    try:
        with path.open(encoding="utf8") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    raise EvidenceError("TECHNICAL_PARTIAL", f"BLANK_JOURNAL_ROW:{path.name}:{number}")
                value = json.loads(line)
                need(isinstance(value, dict), f"JOURNAL_OBJECT_REQUIRED:{path.name}:{number}")
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("TECHNICAL_PARTIAL", "TRUNCATED_JOURNAL:" + path.name) from exc
    return rows


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sealed_historical_member(cell: dict, filename: str, *, root: Path = ROOT) -> tuple[bytes, str]:
    """Return one archived member only after archive and member SHA checks."""
    root = root.resolve()
    arm = cell["m24_state"] + "--" + cell["historical_arm"]
    member_name = ("experiments/m2/cross_state_reliability_001/artifacts/"
                   + arm + "/" + filename)
    archive = root / "experiments/m2/cross_state_reliability_archives_001" / (arm + ".tar.gz")
    seal = read_json(root / "experiments/m2/cross_state_reliability_analysis_001/raw_evidence_manifest.json")
    archive_seal = read_json(root / "experiments/m2/cross_state_reliability_archives_001/manifest.json")
    need(archive.is_file() and digest(archive) == archive_seal["archives"][archive.name]["sha256"],
         "HISTORICAL_ARCHIVE_HASH_MISMATCH")
    try:
        with tarfile.open(archive, "r:gz") as stream:
            member = stream.extractfile(member_name)
            need(member is not None, "HISTORICAL_PARENT_MEMBER_MISSING", "MISSING_EVIDENCE")
            with member:
                raw = member.read()
    except (OSError, tarfile.TarError) as exc:
        raise EvidenceError("TECHNICAL_PARTIAL", "HISTORICAL_ARCHIVE_UNREADABLE") from exc
    sha = hashlib.sha256(raw).hexdigest()
    need(sha == seal["files"][member_name]["sha256"], "HISTORICAL_PARENT_HASH_MISMATCH")
    return raw, sha


def verify_historical_parent_prefix(parent_rows: list[dict], cell: dict, *, root: Path = ROOT) -> dict:
    """Compare the new entire parent native trace with the sealed M2.4 arm."""
    raw, sha = sealed_historical_member(cell, "predecision_native_trace.json", root=root)
    arm = cell["m24_state"] + "--" + cell["historical_arm"]
    historical = json.loads(raw)
    need(isinstance(historical, list) and len(historical) == len(parent_rows),
         "HISTORICAL_PARENT_LENGTH_MISMATCH")
    fields = ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller")
    for index, (old, new) in enumerate(zip(historical, parent_rows, strict=True), 1):
        need(all(old.get(field) == new.get(field) for field in fields),
             "HISTORICAL_PARENT_PREFIX_MISMATCH:" + str(index))
    return {"arm": arm, "steps": len(parent_rows), "historical_member_sha256": sha}


def verify_historical_parent_result(parent: dict, cell: dict, *, root: Path = ROOT) -> dict:
    """Compare retained strict/Halt scoring, excluding elapsed wall/provenance."""
    raw, sha = sealed_historical_member(cell, "parent_result.json", root=root)
    historical = json.loads(raw)
    top = ("state", "mission_success", "physical_success", "failure_type", "failed_node",
           "completed_nodes", "simulation_steps_executed", "skill_invocations")
    for key in top:
        need(parent.get(key) == historical.get(key), "HISTORICAL_PARENT_RESULT_MISMATCH:" + key)
    old_nodes, new_nodes = historical.get("nodes", []), parent.get("nodes", [])
    need(len(old_nodes) == len(new_nodes), "HISTORICAL_PARENT_NODE_COUNT_MISMATCH")
    for number, (old, new) in enumerate(zip(old_nodes, new_nodes, strict=True), 1):
        for key in ("node_id", "skill", "execution_mode"):
            need(old.get(key) == new.get(key), f"HISTORICAL_PARENT_NODE_{number}_MISMATCH:{key}")
        old_metrics = {key: value for key, value in old.get("metrics", {}).items() if key != "wall_time_s"}
        new_metrics = {key: value for key, value in new.get("metrics", {}).items() if key != "wall_time_s"}
        need(old_metrics == new_metrics, f"HISTORICAL_PARENT_NODE_{number}_STRICT_METRICS_CHANGED")
    old_halt, new_halt = historical.get("physical_halt"), parent.get("physical_halt")
    need(bool(old_halt) == bool(new_halt), "HISTORICAL_PARENT_HALT_PRESENCE_CHANGED")
    if old_halt:
        for key in ("status", "skill_status", "checks", "final_state", "skill_metrics"):
            need(old_halt.get(key) == new_halt.get(key), "HISTORICAL_PARENT_HALT_MISMATCH:" + key)
        need(len(old_halt.get("trace", [])) == len(new_halt.get("trace", [])),
             "HISTORICAL_PARENT_HALT_TRACE_LENGTH_CHANGED")
    return {"historical_parent_result_sha256": sha, "nodes": len(old_nodes)}


def verify_frozen_sources(*, root: Path = ROOT, here: Path = HERE,
                          readiness_sha256: str | None = None) -> dict:
    """Read-only source/asset closure, independent of acquisition preflight."""
    root, here = root.resolve(), here.resolve()
    readiness = here / "readiness_manifest.json"
    need(readiness.is_file(), "READINESS_MANIFEST_MISSING", "MISSING_EVIDENCE")
    if readiness_sha256 is not None:
        need(digest(readiness) == readiness_sha256, "READINESS_SHA256_MISMATCH")
    receipt = read_json(readiness)
    need(receipt.get("status") == "READY_FOR_OWNER_ACQUISITION_AUTHORIZATION"
         and receipt.get("physics_authorized") is False, "READINESS_AUTHORITY_MISMATCH")
    source = read_json(here / "source_manifest.json")
    need(source.get("status") == "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY"
         and source.get("physics_authorized") is False, "SOURCE_FREEZE_AUTHORITY_MISMATCH")
    files = source.get("files")
    need(isinstance(files, dict) and len(files) >= 241, "SOURCE_CLOSURE_INCOMPLETE")
    for name, expected in files.items():
        path = (root / name).resolve()
        need(path.is_relative_to(root) and path.is_file() and digest(path) == expected,
             "SOURCE_HASH_MISMATCH:" + name)
    need(receipt.get("source_manifest_sha256") == digest(here / "source_manifest.json"),
         "READINESS_SOURCE_HASH_MISMATCH")
    for name, expected in receipt.get("sha256", {}).items():
        path = (root / name).resolve()
        need(path.is_relative_to(root) and path.is_file() and digest(path) == expected,
             "READINESS_HASH_MISMATCH:" + name)
    return {"status": "FROZEN_SOURCES_VERIFIED_NO_PHYSICS", "files": len(files),
            "readiness_sha256": digest(readiness)}


def exact_snapshots(left: dict, right: dict, *, label: str) -> None:
    for key in SNAPSHOT_KEYS:
        need(key in left and key in right, f"{label}_FIELD_MISSING:{key}", "MISSING_EVIDENCE")
        need(left[key] == right[key], f"{label}_CHANGED:{key}")


def stop_eligibility(parent: dict, cell: dict) -> str:
    """A result distinct from eligible is coverage, not a hold verdict."""
    if cell["role"] == "failure_halt_qualification":
        if parent.get("mission_success") is True:
            return "PARENT_PASS_NO_HALT_NO_HOLD"
        if parent.get("failure_type") != "TASK_ENVELOPE_VIOLATION" or parent.get("failed_node") != "s1":
            return "INCONCLUSIVE_MISSING_EVIDENCE"
        halt = parent.get("physical_halt")
        if not halt:
            return "HALT_NOT_REQUESTED_NO_HOLD"
        if halt.get("status") != "HALT_SUCCEEDED":
            return "HALT_FAILED_NO_HOLD"
        if halt.get("skill_status") != "SUCCESS" or not halt.get("checks") or not all(halt["checks"].values()):
            return "INCONCLUSIVE_MISSING_EVIDENCE"
        return "ELIGIBLE"
    if cell["role"] == "ordinary_stop_measurement_control_not_matched_failure_state":
        nodes = parent.get("nodes") or []
        if (parent.get("mission_success") is True and parent.get("physical_success") is True
                and parent.get("completed_nodes") == 3 and not parent.get("physical_halt")
                and nodes and nodes[-1].get("skill") == "stop"
                and nodes[-1].get("metrics", {}).get("skill_status") == "SUCCESS"):
            return "ELIGIBLE"
        return "CONTROL_FAILED_NO_HOLD"
    raise EvidenceError("INTEGRITY_FAILURE", "UNKNOWN_CELL_ROLE")


def _finite_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("MISSING_EVIDENCE", "NON_NUMERIC_PHYSICAL_VALUE") from exc
    need(math.isfinite(number), "NONFINITE_NUMERIC_VALUE", "MISSING_EVIDENCE")
    return number


def _close(a: float, b: float, *, tolerance: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=0, abs_tol=tolerance)


def verify_first_stop_crossing(speeds: list[float], *, window: int,
                               threshold: float, reported_mean: float) -> dict:
    """Replay StopSkill's first qualifying full window from every Stop step."""
    need(len(speeds) >= window, "STOP_TRACE_SHORTER_THAN_WINDOW", "MISSING_EVIDENCE")
    values = [_finite_number(value) for value in speeds]
    for end in range(window, len(values) + 1):
        mean = sum(values[end - window:end]) / window
        if mean <= threshold:
            need(end == len(values), "PRIOR_STOP_WINDOW_ALREADY_QUALIFIED")
            need(_close(mean, reported_mean), "STOP_FIRST_WINDOW_REPORTED_MEAN_MISMATCH")
            return {"first_qualifying_stop_step": end, "first_qualifying_mean_mps": mean}
    raise EvidenceError("INTEGRITY_FAILURE", "NO_QUALIFYING_STOP_WINDOW_IN_SAVED_TRACE")


def _all_finite(value: Any) -> bool:
    if isinstance(value, (tuple, list)):
        return all(_all_finite(item) for item in value)
    if isinstance(value, dict):
        return False  # json_safe encodes nonfinite values as an object.
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def physical_flags_from_native(raw: dict, limits: dict) -> dict:
    """Match RobotState and raw finite/standing/fall semantics from frozen config."""
    qpos, qvel = raw.get("qpos"), raw.get("qvel")
    controller = raw.get("controller") or {}
    need(isinstance(qpos, list) and len(qpos) >= 7
         and isinstance(qvel, list) and len(qvel) >= 6,
         "NATIVE_POSE_OR_VELOCITY_INCOMPLETE", "MISSING_EVIDENCE")
    state_finite = _all_finite(raw.get("time_s")) and _all_finite(qpos[:7]) and _all_finite(qvel[:6])
    raw_finite = (state_finite and _all_finite(qpos) and _all_finite(qvel)
                  and _all_finite(raw.get("ctrl")) and _all_finite(raw.get("xfrc_applied"))
                  and _all_finite(controller.get("_action")) and _all_finite(controller.get("_target")))
    if not state_finite:
        return {"finite": False, "raw_finite": False, "standing": None,
                "fallen": None, "tilt_deg": None}
    w, x, y, z = [float(value) for value in qpos[3:7]]
    norm = math.sqrt(w*w + x*x + y*y + z*z)
    if norm == 0.0:
        tilt = 0.0
    else:
        x, y = x / norm, y / norm
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * (x*x + y*y)))))
    height = float(qpos[2])
    fallen = height < limits["fall_height_m"] or tilt > limits["fall_tilt_deg"]
    standing = (not fallen and height >= limits["standing_min_height_m"]
                and tilt <= limits["standing_max_tilt_deg"])
    return {"finite": True, "raw_finite": raw_finite, "standing": standing,
            "fallen": fallen, "tilt_deg": tilt}


def recompute_hold(seed: list[float], rows: list[dict], entry: dict, spec: dict) -> dict:
    """Re-score all recorded postqualification steps from raw state, no labels."""
    hold = spec["hold"]
    n = hold["native_steps"]
    width = hold["rolling_window_steps"]
    need(len(seed) == width, "SEED_WINDOW_INCOMPLETE", "MISSING_EVIDENCE")
    seed = [_finite_number(value) for value in seed]
    need(len(rows) <= n, "EXCESS_HOLD_ROWS")
    rolling = list(seed)
    means = []
    path = 0.0
    previous = entry["qpos"][:2]
    speeds = []
    unsafe = False
    for row in rows:
        if row.get("raw_finite") is False or row.get("finite") is False:
            unsafe = True
            break
        speed = _finite_number(row["speed_mps"])
        xy = [_finite_number(v) for v in row["position_m"][:2]]
        path += math.dist(previous, xy)
        previous = xy
        rolling.pop(0)
        rolling.append(speed)
        means.append(sum(rolling) / width)
        speeds.append(speed)
        if row.get("fallen") is True or row.get("standing") is False:
            unsafe = True
            break
    acceptance = hold["acceptance"]
    if len(rows) < n:
        return {"status": "HOLD_FAILED" if unsafe else "TECHNICAL_PARTIAL",
                "complete": False, "unsafe": unsafe, "observed_steps": len(rows),
                "rolling_means": means, "xy_path_length_m": path}
    checks = {
        "complete_1000_steps": len(rows) == n,
        "rolling_mean": len(means) == n and all(value <= acceptance["all_1000_rolling_means_at_most_mps"] for value in means),
        "final_speed": bool(speeds) and speeds[-1] <= acceptance["final_instantaneous_speed_at_most_mps"],
        "xy_path_length": path <= acceptance["hold_xy_path_length_at_most_m"],
        "finite_throughout": all(row["finite"] and row["raw_finite"] for row in rows),
        "standing_throughout": all(row["standing"] for row in rows),
        "no_fall_throughout": not any(row["fallen"] for row in rows),
    }
    return {"status": "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE" if all(checks.values()) else "HOLD_FAILED",
            "complete": True, "unsafe": unsafe, "observed_steps": n,
            "checks": checks, "rolling_means": means, "xy_path_length_m": path,
            "last_speed_mps": speeds[-1], "maximum_instantaneous_speed_mps": max(speeds),
            "one_second_disjoint_means_mps": [sum(speeds[0:500]) / 500, sum(speeds[500:1000]) / 500]}


def _audit_cell(cell_dir: Path, spec: dict, cell: dict, *, root: Path,
                verify_prefix: bool) -> dict:
    parent = read_json(cell_dir / "parent_result.json")
    graph = read_json(cell_dir / "parent_graph.json")
    outcome = read_json(cell_dir / "outcome.json")
    witness = read_json(cell_dir / "witness.json")
    native = read_jsonl(cell_dir / "native_incremental.jsonl")
    hold_rows = read_jsonl(cell_dir / "hold_incremental.jsonl")
    need(bool(graph), "EMPTY_PARENT_GRAPH", "MISSING_EVIDENCE")
    need(outcome.get("cell_id") == cell["id"], "CELL_ID_MISMATCH")
    need(len(native) <= cell["max_native_steps"], "CELL_NATIVE_BUDGET_EXCEEDED")
    need(all(row.get("sequence") == index for index, row in enumerate(native, 1)),
         "NATIVE_SEQUENCE_GAP_OR_REPLAY")
    need(witness.get("native_steps") == witness.get("native_journal_rows") == len(native),
         "NATIVE_WITNESS_JOURNAL_MISMATCH")
    need(witness.get("attempt") == 1, "ATTEMPT_COUNT_OR_WITNESS_MISSING")
    need(not witness.get("integrity_failure") and not witness.get("budget_failure"),
         "WITNESS_INTEGRITY_OR_BUDGET_FAILURE")
    need(witness.get("outcome_status") == outcome.get("status"), "WITNESS_OUTCOME_MISMATCH")
    if verify_prefix:
        for name, path in (("protocol_sha256", HERE / "protocol.json"),
                           ("readiness_sha256", HERE / "readiness_manifest.json"),
                           ("source_manifest_sha256", HERE / "source_manifest.json")):
            need(path.is_file() and witness.get(name) == digest(path),
                 "WITNESS_FROZEN_HASH_MISMATCH:" + name)
    parent_native = [row for row in native if row.get("phase") == "parent"]
    hold_native = [row for row in native if row.get("phase") == "hold"]
    need(len(parent_native) + len(hold_native) == len(native), "UNKNOWN_NATIVE_PHASE")
    need(native == parent_native + hold_native, "PARENT_HOLD_PHASE_REORDERED")
    need(witness.get("parent_native_steps") == len(parent_native)
         and witness.get("hold_native_steps") == len(hold_native)
         and witness.get("hold_journal_rows") == len(hold_rows),
         "NATIVE_PHASE_WITNESS_MISMATCH")
    historical_result = None
    if verify_prefix:
        historical_result = verify_historical_parent_result(parent, cell, root=root)
    if outcome.get("status") == "TECHNICAL_PARTIAL":
        need(witness.get("hold_command_calls") in (len(hold_native), len(hold_native) + 1),
             "TECHNICAL_PARTIAL_COMMAND_WITNESS_MISMATCH")
    else:
        need(witness.get("hold_command_calls") == len(hold_native),
             "HOLD_COMMAND_NATIVE_WITNESS_MISMATCH")
    prefix = None
    if verify_prefix:
        expected_prefix = verify_historical_parent_prefix(parent_native, cell, root=root)
        recorded_prefix = read_json(cell_dir / "historical_parent_prefix.json")
        need(recorded_prefix.get("status") == "EXACT_M24_PARENT_NATIVE_PREFIX_MATCH"
             and all(recorded_prefix.get(key) == value for key, value in expected_prefix.items()),
             "HISTORICAL_PARENT_RECEIPT_MISMATCH")
        prefix = expected_prefix
    unmatched_native = len(hold_native) - len(hold_rows)
    need(unmatched_native in (0, 1), "HOLD_NATIVE_JOURNAL_MISMATCH")
    if unmatched_native:
        need(outcome.get("status") in ("HOLD_FAILED", "TECHNICAL_PARTIAL")
             and outcome.get("coverage") in ("PARTIAL_PHYSICAL_NONFINITE", "PARTIAL_TECHNICAL"),
             "UNMATCHED_NATIVE_ROW_WITHOUT_PARTIAL_RECEIPT")
        if outcome.get("coverage") == "PARTIAL_PHYSICAL_NONFINITE":
            final_raw = hold_native[-1]
            need(final_raw.get("raw_finite") is False
                 and (not _all_finite(final_raw.get("qpos"))
                      or not _all_finite(final_raw.get("qvel"))),
                 "NONFINITE_PHYSICAL_FAILURE_WITHOUT_QPOS_QVEL_NONFINITE")
    eligibility = stop_eligibility(parent, cell)
    if (outcome.get("status") == "INCONCLUSIVE_MISSING_EVIDENCE"
            and outcome.get("coverage") == "NO_HOLD"):
        need(not hold_rows and not hold_native and not (cell_dir / "hold_entry.json").exists()
             and not (cell_dir / "hold_metrics.json").exists(),
             "MISSING_COVERAGE_BUT_HOLD_WAS_EXECUTED")
        if verify_prefix and (cell_dir / "historical_parent_prefix.json").exists():
            expected_prefix = verify_historical_parent_prefix(parent_native, cell, root=root)
            recorded_prefix = read_json(cell_dir / "historical_parent_prefix.json")
            need(recorded_prefix.get("status") == "EXACT_M24_PARENT_NATIVE_PREFIX_MATCH"
                 and all(recorded_prefix.get(key) == value for key, value in expected_prefix.items()),
                 "MISSING_COVERAGE_PREFIX_RECEIPT_MISMATCH")
        return {"cell_id": cell["id"], "audit_status": "MISSING_EVIDENCE",
                "classification": "ELIGIBLE_NO_HOLD_MISSING_SOURCE" if eligibility == "ELIGIBLE"
                                  else "PARENT_STATE_COVERAGE_MISSING",
                "reason": outcome.get("reason", "REQUIRED_PRE_HOLD_EVIDENCE_MISSING"),
                "scientific_status": None, "native_steps": len(native), "hold_steps": 0,
                "historical_parent_result": historical_result}
    if eligibility != "ELIGIBLE":
        need(not hold_rows and not hold_native, "HOLD_EXECUTED_WITHOUT_ELIGIBILITY")
        need(not (cell_dir / "hold_entry.json").exists() and not (cell_dir / "hold_metrics.json").exists(),
             "HOLD_EVIDENCE_WITHOUT_ELIGIBILITY")
        need(outcome.get("status") == eligibility and outcome.get("coverage") == "NO_HOLD",
             "NO_HOLD_OUTCOME_MISMATCH")
        classification = ("PHYSICAL_HALT_FAILURE_NO_HOLD" if eligibility == "HALT_FAILED_NO_HOLD"
                          else "NO_HOLD_COVERAGE")
        return {"cell_id": cell["id"], "audit_status": "PASS_RECORDED_NO_HOLD",
                "classification": classification, "scientific_status": eligibility,
                "native_steps": len(native), "hold_steps": 0, "historical_parent_prefix": prefix,
                "historical_parent_result": historical_result}
    entry = read_json(cell_dir / "hold_entry.json")
    metrics = read_json(cell_dir / "hold_metrics.json")
    terminal = entry.get("terminal")
    before = entry.get("pre_first_step")
    need(isinstance(terminal, dict) and isinstance(before, dict), "ENTRY_SNAPSHOTS_MISSING", "MISSING_EVIDENCE")
    terminal_snapshot = terminal.get("snapshot")
    need(isinstance(terminal_snapshot, dict), "TERMINAL_SNAPSHOT_MISSING", "MISSING_EVIDENCE")
    exact_snapshots(terminal_snapshot, before, label="TERMINAL_TO_HOLD")
    skill_return = terminal.get("skill_return_snapshot")
    need(isinstance(skill_return, dict), "SKILL_RETURN_SNAPSHOT_MISSING", "MISSING_EVIDENCE")
    # Parent recording may change counters only through explicitly visible dispatch;
    # it must never advance the simulator, controller or reset any state.
    for key in ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller_action",
                "controller_target", "controller_counter", *IDENTITY_KEYS, "native_steps", *COUNTER_KEYS):
        need(key in skill_return, "SKILL_RETURN_FIELD_MISSING:" + key, "MISSING_EVIDENCE")
        need(skill_return[key] == terminal_snapshot[key], "SKILL_RETURN_TO_TERMINAL_CHANGED:" + key)
    need(terminal.get("stop_status") == "SUCCESS", "STOP_FIRST_CROSSING_NOT_SUCCESSFUL")
    need(_close(_finite_number(terminal.get("stop_crossing_time_s")),
                _finite_number(terminal_snapshot["time_s"])),
         "STOP_CROSSING_TO_HOLD_TIME_CHANGED")
    need(len(parent_native) >= spec["hold"]["rolling_window_steps"],
         "PARENT_SEED_NATIVE_ROWS_MISSING", "MISSING_EVIDENCE")
    need(before["native_steps"] == len(parent_native), "PARENT_NATIVE_ENTRY_COUNT_MISMATCH")
    last_parent = parent_native[-1]
    for source_key, snapshot_key in (("time_s", "time_s"), ("qpos", "qpos"),
                                     ("qvel", "qvel"), ("ctrl", "ctrl"),
                                     ("xfrc_applied", "xfrc_applied")):
        need(last_parent[source_key] == before[snapshot_key], "PARENT_LAST_NATIVE_ENTRY_MISMATCH:" + source_key)
    seed = entry.get("seed_speeds_mps")
    need(isinstance(seed, list) and len(seed) == 500, "EXACT_500_SEED_REQUIRED", "MISSING_EVIDENCE")
    seed = [_finite_number(v) for v in seed]
    recent_stop = terminal.get("stop_poststep_speeds")
    need(isinstance(recent_stop, list) and recent_stop[-500:] == seed,
         "STOP_SEED_ORIGIN_MISMATCH")
    need(len(recent_stop) <= len(parent_native), "STOP_TRACE_EXCEEDS_PARENT_NATIVE")
    native_stop = [math.hypot(_finite_number(row["qvel"][0]), _finite_number(row["qvel"][1]))
                   for row in parent_native[-len(recent_stop):]]
    need(all(_close(a, b) for a, b in zip(native_stop, recent_stop)),
         "NATIVE_STOP_TRACE_ORIGIN_MISMATCH")
    first_crossing = verify_first_stop_crossing(
        recent_stop, window=spec["hold"]["rolling_window_steps"],
        threshold=spec["fixed_config"]["stop_skill_parameters"]["speed_threshold_mps"],
        reported_mean=_finite_number(terminal["stop_window_mean_mps"]))
    dt = spec["fixed_config"]["native_timestep_s"]
    limits = yaml.safe_load((root / spec["fixed_config"]["robot_config"]).read_text(encoding="utf8"))["simulation"]
    for index, (row, raw) in enumerate(zip(hold_rows, hold_native), 1):
        need(row.get("hold_step") == index and row.get("native_sequence") == raw["sequence"],
             "HOLD_SEQUENCE_MISMATCH")
        need(row.get("command_xyz_mps_radps") == [0.0, 0.0, 0.0],
             "HOLD_NONZERO_COMMAND")
        need(_close(_finite_number(row["time_s"]), _finite_number(raw["time_s"]))
             and _close(_finite_number(raw["time_s"]), _finite_number(before["time_s"]) + index * dt),
             "HOLD_TIME_DISCONTINUITY")
        if row.get("raw_finite") and raw.get("raw_finite"):
            need(row["position_m"] == raw["qpos"][:3]
                 and row["orientation_wxyz"] == raw["qpos"][3:7], "HOLD_STATE_NATIVE_MISMATCH")
            need(_close(_finite_number(row["speed_mps"]),
                        math.hypot(_finite_number(raw["qvel"][0]), _finite_number(raw["qvel"][1]))),
                 "HOLD_SPEED_NATIVE_MISMATCH")
        need(row.get("raw_finite") == raw.get("raw_finite"), "HOLD_RAW_FINITE_MISMATCH")
        independent_flags = physical_flags_from_native(raw, limits)
        for key in ("finite", "raw_finite", "standing", "fallen"):
            need(row.get(key) == independent_flags[key], "HOLD_PHYSICAL_FLAG_MISMATCH:" + key)
        if independent_flags["finite"]:
            need(_close(_finite_number(row.get("base_height_m")), _finite_number(raw["qpos"][2])),
                 "HOLD_BASE_HEIGHT_MISMATCH")
        controller = raw.get("controller")
        need(isinstance(controller, dict), "NATIVE_CONTROLLER_WITNESS_MISSING", "MISSING_EVIDENCE")
        need(controller.get("_counter") == row.get("controller_counter")
             and controller.get("_action") == row.get("controller_action")
             and controller.get("_target") == row.get("controller_target"),
             "HOLD_CONTROLLER_NATIVE_MISMATCH")
        need(row.get("controller_counter") == before["controller_counter"] + index,
             "HOLD_CONTROLLER_COUNTER_GAP")
    score = recompute_hold(seed, hold_rows, before, spec)
    if unmatched_native and outcome.get("coverage") == "PARTIAL_PHYSICAL_NONFINITE":
        need(not score["complete"], "NONFINITE_EXTRA_NATIVE_AFTER_COMPLETE_HOLD")
        score["status"] = "HOLD_FAILED"
        score["unsafe"] = True
    need(outcome.get("status") == score["status"], "SAVED_STATUS_DISAGREES_WITH_RAW_SCORE")
    need(outcome.get("hold_observed_steps") == len(hold_rows), "SAVED_HOLD_STEP_COUNT_MISMATCH")
    need(outcome.get("native_steps") == len(native), "SAVED_NATIVE_STEP_COUNT_MISMATCH")
    need(metrics.get("rows") == hold_rows and metrics.get("result") == outcome,
         "HOLD_METRICS_DIVERGE_FROM_JOURNAL")
    if score["complete"]:
        need(outcome.get("coverage") == "COMPLETE_HOLD", "COMPLETE_HOLD_COVERAGE_MISMATCH")
        need(outcome.get("checks") == score["checks"], "SAVED_CHECKS_DISAGREE_WITH_RAW_SCORE")
        need(_close(_finite_number(outcome.get("xy_path_length_m")), score["xy_path_length_m"]),
             "SAVED_PATH_DISAGREES_WITH_RAW_SCORE")
        saved_means = outcome.get("rolling_mean_speed_mps")
        need(isinstance(saved_means, list) and len(saved_means) == 1000
             and all(_close(_finite_number(a), b) for a, b in zip(saved_means, score["rolling_means"])),
             "SAVED_ROLLING_MEANS_DISAGREE_WITH_RAW_SCORE")
        for key in ("last_speed_mps", "maximum_instantaneous_speed_mps"):
            need(_close(_finite_number(outcome.get(key)), score[key]), "SAVED_METRIC_DISAGREES:" + key)
        need(all(_close(_finite_number(a), b) for a, b in zip(outcome.get("one_second_disjoint_means_mps", []),
                                                               score["one_second_disjoint_means_mps"]))
             and len(outcome.get("one_second_disjoint_means_mps", [])) == 2,
             "SAVED_DISJOINT_MEANS_DISAGREE")
    else:
        need(outcome.get("coverage") in ("PARTIAL_PHYSICAL_UNSAFE", "PARTIAL_PHYSICAL_NONFINITE", "PARTIAL_TECHNICAL"),
             "PARTIAL_COVERAGE_MISMATCH")
    final = outcome.get("hold_terminal")
    need(isinstance(final, dict), "HOLD_TERMINAL_MISSING", "MISSING_EVIDENCE")
    need(final.get("native_steps") == len(native), "HOLD_TERMINAL_NATIVE_COUNT_MISMATCH")
    for key in (*IDENTITY_KEYS, *COUNTER_KEYS):
        need(key in final and key in before, "HOLD_FINAL_WITNESS_MISSING:" + key, "MISSING_EVIDENCE")
        need(final[key] == before[key], "FORBIDDEN_RESET_DISPATCH_IDENTITY_CHANGE:" + key)
    need(witness.get("native_steps") == final["native_steps"], "WITNESS_TERMINAL_NATIVE_MISMATCH")
    if hold_native:
        last_raw = hold_native[-1]
        for key in ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied"):
            need(final.get(key) == last_raw.get(key), "FINAL_SNAPSHOT_NATIVE_MISMATCH:" + key)
        last_controller = last_raw.get("controller") or {}
        need(final.get("controller_counter") == last_controller.get("_counter")
             and final.get("controller_action") == last_controller.get("_action")
             and final.get("controller_target") == last_controller.get("_target"),
             "FINAL_CONTROLLER_NATIVE_MISMATCH")
    witness_terminal = witness.get("terminal_snapshot")
    witness_final = witness.get("final_snapshot")
    need(isinstance(witness_terminal, dict) and isinstance(witness_final, dict),
         "WITNESS_SNAPSHOTS_MISSING", "MISSING_EVIDENCE")
    exact_snapshots(witness_terminal, terminal_snapshot, label="WITNESS_TERMINAL")
    exact_snapshots(witness_final, final, label="WITNESS_FINAL")
    if score["complete"]:
        need(witness.get("hold_command_calls") == len(hold_rows) == len(hold_native),
             "HOLD_COMMAND_COUNT_MISMATCH")
        need(final.get("controller_counter") == before["controller_counter"] + len(hold_rows),
             "FINAL_CONTROLLER_COUNTER_MISMATCH")
        need(final.get("session_steps") == before["session_steps"] + len(hold_rows),
             "FINAL_SESSION_STEP_COUNT_MISMATCH")
    return {"cell_id": cell["id"], "audit_status": "PASS_RECOMPUTED",
            "classification": ("PHYSICAL_HOLD_FAILURE" if score["status"] == "HOLD_FAILED"
                               else "TECHNICAL_PARTIAL" if score["status"] == "TECHNICAL_PARTIAL"
                               else "BOUNDED_HOLD_IN_THIS_STATE"),
            "scientific_status": score["status"], "native_steps": len(native),
            "hold_steps": len(hold_rows), "historical_parent_prefix": prefix,
            "historical_parent_result": historical_result, "first_crossing": first_crossing,
            "recomputed": score}


def audit_cell(cell_dir: Path, spec: dict, cell: dict, *, root: Path = ROOT,
               verify_prefix: bool = True) -> dict:
    try:
        return _audit_cell(Path(cell_dir), spec, cell, root=root, verify_prefix=verify_prefix)
    except EvidenceError as exc:
        return {"cell_id": cell["id"], "audit_status": exc.category,
                "reason": exc.reason, "scientific_status": None}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {"cell_id": cell["id"], "audit_status": "MISSING_EVIDENCE",
                "reason": type(exc).__name__ + ": " + str(exc), "scientific_status": None}


def audit_campaign(output: Path, *, spec_path: Path = HERE / "protocol.json",
                   verify_sources: bool = True, verify_prefix: bool = True,
                   readiness_sha256: str | None = None) -> dict:
    """Audit one write-once campaign directory; emit no modifications."""
    output = Path(output)
    spec = read_json(Path(spec_path))
    source = verify_frozen_sources(readiness_sha256=readiness_sha256) if verify_sources else None
    receipt = read_json(output / "campaign_receipt.json")
    cells = spec["cells_in_order"]
    observed = [cell["id"] for cell in cells if (output / cell["id"]).exists()]
    unknown_directories = sorted(path.name for path in output.iterdir()
                                 if path.is_dir() and path.name not in {cell["id"] for cell in cells})
    need(not unknown_directories, "UNFROZEN_CAMPAIGN_DIRECTORIES:" + ",".join(unknown_directories))
    need(observed == [cell["id"] for cell in cells[:len(observed)]], "CAMPAIGN_ORDER_OR_EXTRA_CELL")
    results = [audit_cell(output / cell["id"], spec, cell, verify_prefix=verify_prefix)
               for cell in cells if (output / cell["id"]).exists()]
    total = sum(row.get("native_steps", 0) for row in results)
    integrity = [row for row in results if row["audit_status"] in ("INTEGRITY_FAILURE", "MISSING_EVIDENCE", "TECHNICAL_PARTIAL")]
    need(total <= spec["budget"]["maximum_native_steps_total"], "CAMPAIGN_NATIVE_BUDGET_EXCEEDED")
    if receipt.get("status") == "ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT":
        need(len(results) == len(cells), "COMPLETE_RECEIPT_MISSING_CELL")
        need(not integrity, "COMPLETE_RECEIPT_HAS_INVALID_CELL")
        need(receipt.get("native_steps") == total, "CAMPAIGN_NATIVE_SUM_MISMATCH")
        need(receipt.get("protocol_sha256") == digest(Path(spec_path)), "CAMPAIGN_PROTOCOL_HASH_MISMATCH")
        if verify_sources:
            need(receipt.get("readiness_sha256") == digest(HERE / "readiness_manifest.json"),
                 "CAMPAIGN_READINESS_HASH_MISMATCH")
        need([row.get("cell_id") for row in receipt.get("cells", [])] == observed,
             "CAMPAIGN_RECEIPT_CELL_ORDER_MISMATCH")
        for cell in cells:
            need(read_json(output / cell["id"] / "outcome.json") == receipt["cells"][cells.index(cell)],
                 "CAMPAIGN_RECEIPT_OUTCOME_MISMATCH:" + cell["id"])
    else:
        need(receipt.get("status") == "PARTIAL_STOPPED" and receipt.get("no_retry") is True,
             "UNRECOGNIZED_CAMPAIGN_RECEIPT")
    artifact_hashes = {str(path.relative_to(output)).replace("\\", "/"): digest(path)
                       for path in sorted(output.rglob("*")) if path.is_file()}
    return {"status": ("AUDIT_INCOMPLETE_OR_INVALID" if integrity
                       else "AUDIT_PARTIAL_RETAINED" if receipt["status"] == "PARTIAL_STOPPED"
                       else "AUDIT_PASS_RECORDED_RESULTS"),
            "historical_scientific_verdict": spec["historical_scientific_verdict"],
            "source_binding": source, "cells": results, "native_steps": total,
            "raw_artifact_sha256": artifact_hashes,
            "physics_or_policy_calls_by_auditor": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="saved campaign directory")
    parser.add_argument("--readiness-sha256", required=True)
    args = parser.parse_args()
    result = audit_campaign(args.output, readiness_sha256=args.readiness_sha256)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    if result["status"] != "AUDIT_PASS_RECORDED_RESULTS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
