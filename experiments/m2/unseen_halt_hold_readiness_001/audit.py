"""Read-only M2.6A raw audit. No simulator, policy, or acquisition imports.

Raw numerical scoring reuses the reviewed pure M2.5A audit functions. Routing,
stimulus, historical reproduction, coverage and state comparisons are recomputed
here; adapter outcome labels never supply a successful scientific classification.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import zipfile

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DESIGN = ROOT / "experiments/m2/unseen_halt_hold_design_001"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = _module("m26_readonly_m25_math", ROOT / "experiments/m2/post_halt_hold_design_001/audit.py")
GEOMETRY = _module("m26_frozen_descriptor", DESIGN / "check_design.py")
EvidenceError, need = OLD.EvidenceError, OLD.need
read_json, read_jsonl, digest = OLD.read_json, OLD.read_jsonl, OLD.digest
DT = 0.002
PHYSICAL = yaml.safe_load((ROOT / "configs/robot/g1_locomotion_12dof.yaml").read_text(encoding="utf8"))["simulation"]
PREFIX_FIELDS = ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller")


def sealed_zip_member(archive: Path, manifest: dict, name: str) -> bytes:
    """No extraction, no source writes; verify archive and selected member bytes."""
    need(digest(archive) == manifest["archive"]["sha256"], "ARCHIVE_SHA_MISMATCH")
    with zipfile.ZipFile(archive) as stream:
        names = stream.namelist()
        need(len(names) == len(set(names)), "DUPLICATE_ARCHIVE_MEMBERS")
        need(set(names) == set(manifest["files"]), "ARCHIVE_MEMBER_SET_MISMATCH")
        for entry in stream.infolist():
            p = PurePosixPath(entry.filename)
            need(not p.is_absolute() and ".." not in p.parts and str(p) == entry.filename and entry.filename not in ("", ".") and "\\" not in entry.filename
                 and ":" not in entry.filename and not entry.is_dir(), "UNSAFE_ARCHIVE_MEMBER")
            need((entry.external_attr >> 16) & 0o170000 in (0, 0o100000), "ARCHIVE_NONREGULAR_FORBIDDEN")
        raw = stream.read(name)
    seal = manifest["files"][name]
    need(len(raw) == seal["bytes"] and hashlib.sha256(raw).hexdigest() == seal["sha256"],
         "ARCHIVE_MEMBER_HASH_MISMATCH:" + name)
    return raw


def restore_archive(archive: Path, manifest: dict, target: Path) -> dict:
    """Restore only into a new clean directory; reject all unsafe names first."""
    target = target.resolve()
    need(not target.exists(), "RESTORE_REQUIRES_NEW_DIRECTORY")
    # Validate every member before any output is created. Not physics execution.
    payloads = {name: sealed_zip_member(archive, manifest, name) for name in manifest["files"]}
    target.mkdir(parents=True)
    for name, raw in payloads.items():
        path = target.joinpath(*PurePosixPath(name).parts)
        need(path.resolve().is_relative_to(target), "RESTORE_PATH_ESCAPE")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return {"status": "CLEAN_RESTORE_BYTES_VERIFIED", "files": len(payloads),
            "sha256": {name: digest(target / name) for name in payloads}}


def historical_m25(*, root=ROOT) -> dict:
    folder = root / "experiments/m2/post_halt_hold_qualification_001"
    manifest = read_json(folder / "raw_manifest.json")
    archive = folder / manifest["archive"]["path"]
    result = {}
    for name in ("seen_failure_halt_hold", "turn45_failure_halt_hold", "normal_stop_hold_control"):
        # Determine actual sealed names instead of inventing reference mapping.
        candidates = [p.split("/")[0] for p in manifest["files"] if p.endswith("/hold_entry.json")]
        if name not in candidates:
            continue
        raw = sealed_zip_member(archive, manifest, name + "/hold_entry.json")
        entry = json.loads(raw)
        native_raw = sealed_zip_member(archive, manifest, name + "/native_incremental.jsonl")
        native = [json.loads(line) for line in native_raw.splitlines()]
        terminal = entry["terminal"]
        n = len(terminal["stop_poststep_speeds"])
        parent = [r for r in native if r["phase"] == "parent"]
        start_index = len(parent) - n
        need(start_index > 0, "HISTORICAL_STOP_ENTRY_MISSING")
        result[name] = {"request": parent[start_index - 1], "terminal": parent[-1],
                        "native": native, "entry_sha256": hashlib.sha256(raw).hexdigest(),
                        "native_sha256": hashlib.sha256(native_raw).hexdigest()}
    need(len(result) == 3, "THREE_HISTORICAL_M25_REFERENCES_REQUIRED", "MISSING_EVIDENCE")
    return result


def verify_acquisition_prefix(output: Path, cell_id: str) -> dict:
    """Mandatory post-worker stop gate; no resampling after a comparator failure."""
    output = Path(output)
    spec = read_json(DESIGN / "protocol.json")
    cell = next(c for c in spec["cells_in_order"] if c["id"] == cell_id)
    current = read_jsonl(output / cell_id / "native_incremental.jsonl")
    if cell_id in ("seen_no_push_anchor", "normal_stop_control"):
        history = historical_m25()
        old_id = "seen_failure_halt_hold" if cell_id == "seen_no_push_anchor" else "normal_stop_hold_control"
        previous = history[old_id]["native"]
        need(len(current) == len(previous), "ANCHOR_REPRODUCIBILITY_LENGTH_FAILURE")
        raw_prefix(current, previous, len(previous))
        return {"status": "SEALED_M25_FULL_NATIVE_REPRODUCED", "rows": len(current)}
    if cell_id == "seen_plus_y_early_control":
        old, sha = OLD.sealed_historical_member(
            {"m24_state": "push60_walk6", "historical_arm": "authorized_new_mission"},
            "predecision_native_trace.json")
        previous = json.loads(old)
        need(len(current) == len(previous), "ANCHOR_REPRODUCIBILITY_LENGTH_FAILURE")
        raw_prefix(current, previous, len(previous))
        return {"status": "SEALED_M24_FULL_NATIVE_REPRODUCED", "rows": len(current), "member_sha256": sha}
    anchor = read_jsonl(output / "seen_no_push_anchor" / "native_incremental.jsonl")
    n = min(cell["push"]["native_pre_step_start_index"], len(current))
    raw_prefix(current, anchor, n)
    return {"status": "OBSERVED_PREPULSE_PREFIX_REPRODUCED", "rows": n,
            "full_predeclared_prefix_observed": n == cell["push"]["native_pre_step_start_index"]}


def _snapshot_raw(snapshot):
    return {k: snapshot[k] for k in ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied")} | {
        "controller": {"_action": snapshot["controller_action"], "_target": snapshot["controller_target"],
                       "_counter": snapshot["controller_counter"]}}


def snapshot_matches(snapshot, rows, label, *, force_clear=False):
    index = snapshot["native_steps"]
    need(0 <= index <= len(rows), "SNAPSHOT_COUNTER_OUTSIDE_JOURNAL:" + label)
    if index:
        raw = _snapshot_raw(snapshot)
        fields = [k for k in PREFIX_FIELDS if not (force_clear and k == "xfrc_applied")]
        need(all(raw[k] == rows[index - 1][k] for k in fields), "SNAPSHOT_NATIVE_MISMATCH:" + label)
        if force_clear:
            need(all(all(v == 0 for v in f) for f in raw["xfrc_applied"]), "CLEARANCE_EVENT_NONZERO_FORCE")


def raw_prefix(left, right, count):
    need(len(left) >= count and len(right) >= count, "PREFIX_COVERAGE_MISSING", "MISSING_EVIDENCE")
    for index in range(count):
        need(all(left[index][k] == right[index][k] for k in PREFIX_FIELDS),
             "PAIRED_PREPULSE_PREFIX_MISMATCH:" + str(index + 1))
    return {"matched_poststeps": count, "fields": list(PREFIX_FIELDS)}


def force_audit(rows, force_rows, cell, walk_start, walk_end):
    need(len(force_rows) == len(rows), "FORCE_INTERVAL_JOURNAL_INCOMPLETE", "MISSING_EVIDENCE")
    nonzero = 0
    for seq, (row, witness) in enumerate(zip(rows, force_rows), 1):
        need(witness["sequence_next"] == seq, "FORCE_SEQUENCE_GAP")
        need(abs(witness["pre_time_s"] - (row["time_s"] - DT)) < 1e-8, "FORCE_PRESTEP_TIME_MISMATCH")
        walk_index = seq - 1 - walk_start
        active_walk = walk_start < seq <= walk_end
        expected = list(GEOMETRY.force_at_pre_step(cell["push"], walk_index)) if active_walk else [0., 0., 0.]
        need(witness["force_vector"] == expected, "FORCE_PROFILE_MISMATCH:" + str(seq))
        need(witness.get("first_walk_pre_index") == (walk_index if active_walk else None), "FORCE_WALK_INDEX_MISMATCH")
        force = row["xfrc_applied"]
        body = witness["body_index"]
        need(witness["body_name"] == "pelvis", "FORCE_TARGET_BODY_NAME_MISMATCH")
        need(isinstance(body, int) and 0 <= body < len(force), "FORCE_BODY_INDEX_MISSING")
        need(all(len(f) == 6 for f in force), "RAW_WRENCH_DIMENSION_MISMATCH")
        expected_wrench = [[0.] * 6 for _ in force]
        expected_wrench[body][:3] = expected
        need(force == expected_wrench and witness["xfrc_before"] == expected_wrench,
             "FORCE_WRENCH_OR_CLEARANCE_MISMATCH")
        nonzero += expected != [0., 0., 0.]
    push = cell["push"]
    complete_window = bool(push and walk_end - walk_start >= push["native_pre_step_start_index"] + 100)
    need(not complete_window or nonzero == 100, "FULL_DOSE_NOT_100_INTERVALS")
    return {"observed_nonzero_intervals": nonzero, "full_window_reached": complete_window,
            "exposure": "NO_PUSH" if not push else "COMPLETE_100_INTERVALS" if complete_window else "TRUNCATED_OR_NOT_REACHED"}


def _yaw(q):
    w, x, y, z = q[3:7]
    return math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


def strict_walk(entry, end, target, skill_status, raw_rows):
    """Frozen strict endpoint geometry from actual start and native final state."""
    flags = [OLD.physical_flags_from_native(row, PHYSICAL) for row in raw_rows]
    physical = all(f["raw_finite"] and not f["fallen"] for f in flags)
    if not physical or skill_status != "SUCCESS":
        return {"branch": "SKILL_OR_PHYSICAL_FAILURE_NO_HALT", "strict": None, "physical": physical}
    yaw = _yaw(entry["qpos"])
    dx, dy = (end["qpos"][i] - entry["qpos"][i] for i in range(2))
    progress = math.cos(yaw)*dx + math.sin(yaw)*dy
    lateral = math.cos(yaw)*dy - math.sin(yaw)*dx
    heading = math.degrees((_yaw(end["qpos"]) - yaw + math.pi) % (2*math.pi) - math.pi)
    elapsed = end["time_s"] - entry["time_s"]
    checks = {"distance": abs(progress-target) <= max(.15, .05*target),
              "lateral": abs(lateral) <= max(.20, .035*target), "heading": abs(heading) <= 8.,
              "duration": elapsed <= max(12., 5.*target)}
    return {"branch": "STRICT_PASS_NO_HALT" if all(checks.values()) else "STRICT_TRIGGER",
            "strict": all(checks.values()), "physical": physical, "checks": checks,
            "progress_m": progress, "lateral_m": lateral, "heading_deg": heading, "elapsed_s": elapsed}


def stop_score(start, stop_rows, skill_status, spec):
    flags = [OLD.physical_flags_from_native(row, PHYSICAL) for row in stop_rows]
    entry_flags = OLD.physical_flags_from_native(_snapshot_raw(start), PHYSICAL)
    speeds = [math.hypot(row["qvel"][0], row["qvel"][1]) if f["finite"] else float("inf")
              for row, f in zip(stop_rows, flags)]
    first = None
    for end in range(500, len(speeds)+1):
        # StopSkill tests fallen before appending this post-step speed. A fallen
        # final row is physical failure, not a fictitious successful crossing.
        if flags[end-1]["fallen"] or not flags[end-1]["finite"]:
            break
        if sum(speeds[end-500:end])/500 <= .1:
            first = end
            break
    if first is not None:
        need(first == len(speeds), "STOP_CONTINUED_AFTER_FIRST_CROSSING")
        need(skill_status == "SUCCESS", "STOP_FIRST_CROSSING_STATUS_MISMATCH")
    else:
        need(skill_status != "SUCCESS", "STOP_SUCCESS_WITHOUT_FIRST_CROSSING")
    end = stop_rows[-1] if stop_rows else start
    finite = entry_flags["raw_finite"] and all(f["raw_finite"] for f in flags)
    checks = {"first_crossing": first is not None, "stop_status": skill_status == "SUCCESS",
              "duration": end["time_s"]-start["time_s"] <= 4.+1e-8,
              "final_speed": bool(speeds) and speeds[-1] <= .1,
              "window_mean": len(speeds) >= 500 and sum(speeds[-500:])/500 <= .1,
              "displacement": math.dist(start["qpos"][:2], end["qpos"][:2]) <= .5,
              "finite": finite, "standing": entry_flags["standing"] and all(f["standing"] for f in flags),
              "no_fall": not entry_flags["fallen"] and not any(f["fallen"] for f in flags)}
    return {"status": "SUCCEEDED" if all(checks.values()) else "FAILED", "checks": checks,
            "first_crossing_step": first, "seed_speeds": speeds[-500:] if finite else [],
            "final_mean_mps": sum(speeds[-500:])/500 if len(speeds)>=500 and finite else None}


def hold_score(entry, native, journal, seed, spec):
    extra_nonfinite = len(native) == len(journal) + 1 and not OLD.physical_flags_from_native(native[-1], PHYSICAL)["raw_finite"]
    need(len(native) == len(journal) or extra_nonfinite, "HOLD_NATIVE_JOURNAL_DISAGREEMENT", "MISSING_EVIDENCE")
    if extra_nonfinite:
        journal = journal + [{"hold_step": len(native), "native_sequence": native[-1]["sequence"],
                             "command_xyz_mps_radps": [0., 0., 0.]}]
    rows = []
    for index, (raw, log) in enumerate(zip(native, journal), 1):
        need(log["hold_step"] == index and log["native_sequence"] == raw["sequence"], "HOLD_SEQUENCE_MISMATCH")
        need(log["command_xyz_mps_radps"] == [0., 0., 0.], "HOLD_NONZERO_COMMAND")
        need(abs(raw["time_s"]-entry["time_s"]-index*DT) < 1e-8, "HOLD_TIME_GAP")
        need(raw["controller"]["_counter"] == entry["controller_counter"] + index, "HOLD_CONTROLLER_COUNTER_GAP")
        need(all(all(v == 0 for v in f) for f in raw["xfrc_applied"]), "HOLD_FORCE_NOT_CLEAR")
        flags = OLD.physical_flags_from_native(raw, PHYSICAL)
        speed = math.hypot(raw["qvel"][0], raw["qvel"][1]) if flags["finite"] else 0.
        rows.append({"position_m": raw["qpos"][:3], "speed_mps": speed, **flags})
    old_spec = {"hold": spec["layer3_hold"]["contract"]}
    result = OLD.recompute_hold(seed, rows, entry, old_spec)
    return result


def _events(path):
    rows = read_jsonl(path)
    result = {}
    for row in rows:
        name = row["event"]
        need(name not in result, "REPLAYED_LIFECYCLE_EVENT:" + name)
        result[name] = row
    return result


def wall_receipt(value, bound, label):
    start, end, elapsed = (value[k] for k in ("wall_started_monotonic_s", "wall_ended_monotonic_s", "wall_elapsed_s"))
    need(all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end, elapsed)), "WALL_WITNESS_NONFINITE:" + label)
    need(0 <= end-start <= bound and abs((end-start)-elapsed) < 1e-6, "WALL_BUDGET_OR_TIMESTAMP_MISMATCH:" + label)
    return {"elapsed_s": elapsed, "bound_s": bound}


def _audit_cell(folder, spec, cell):
    rows = read_jsonl(folder / "native_incremental.jsonl")
    forces = read_jsonl(folder / "force_incremental.jsonl")
    events = _events(folder / "lifecycle_events.jsonl")
    witness = read_json(folder / "witness.json")
    outcome = read_json(folder / "outcome.json")
    cell_wall = wall_receipt(read_json(folder / "cell_wall_receipt.json"), cell["max_wall_s"], "cell")
    supervisor = read_json(folder / "supervisor_receipt.json")
    wall_receipt(supervisor, min(cell["max_wall_s"], supervisor["allocated_wall_bound_s"]), "supervisor")
    need(len(rows) <= cell["max_native_steps"], "CELL_NATIVE_BUDGET_EXCEEDED")
    need(witness["attempt"] == 1 and witness["native_steps"] == len(rows), "ATTEMPT_OR_NATIVE_COUNTER_MISMATCH")
    need(witness.get("reset_calls") == 2 and witness.get("native_reset_calls") == 2
         and witness.get("keyframe_reset_calls") == 0, "SIMULATOR_RESET_CONTINUITY_FAILED")
    need(not witness.get("integrity_failure") and not witness.get("budget_failure"), "EXPLICIT_INTEGRITY_FAILURE")
    for index, row in enumerate(rows, 1):
        need(row["sequence"] == index and abs(row["time_s"]-index*DT) < 1e-8, "NATIVE_TIME_OR_SEQUENCE_GAP")
        need(len(row["qpos"]) == 19 and len(row["qvel"]) == 18 and len(row["ctrl"]) == 12,
             "NATIVE_PHYSICAL_DIMENSIONS_MISSING", "MISSING_EVIDENCE")
        need(isinstance(row.get("controller"), dict) and len(row["controller"]["_action"]) == 12
             and len(row["controller"]["_target"]) == 12, "CONTROLLER_ARRAYS_MISSING", "MISSING_EVIDENCE")
    commands = read_jsonl(folder / "command_incremental.jsonl")
    need(len(commands) == len(rows), "COMMAND_NATIVE_JOURNAL_INCOMPLETE", "MISSING_EVIDENCE")
    for command, row in zip(commands, rows):
        need(command["sequence_next"] == row["sequence"] and command["phase"] == row["phase"], "COMMAND_SEQUENCE_MISMATCH")
        if row["phase"] == "hold":
            need(command["command_xyz_mps_radps"] == [0., 0., 0.], "ACTUAL_HOLD_COMMAND_NONZERO")
    ws, we = events["first_walk_start"], events["first_walk_end"]
    start, end = ws["snapshot"], we["snapshot"]
    for name, event in events.items():
        snapshot_matches(event["snapshot"], rows, name, force_clear=name in ("force_clear_walk_exit", "force_clear_backend_exit", "first_walk_end", "halt_request", "stop_start"))
    force = force_audit(rows, forces, cell, start["native_steps"], end["native_steps"])
    walk_rows = rows[start["native_steps"]:end["native_steps"]]
    target = cell["mission"]["steps"][0]["parameters"]["distance_m"]
    parent = strict_walk(start, end, target, we["skill_status"], walk_rows)
    normal = cell["id"] == "normal_stop_control"
    halt_requested = "halt_request" in events
    if not normal:
        need(halt_requested == (parent["branch"] == "STRICT_TRIGGER"), "STRICT_TRIGGER_HALT_ROUTING_MISMATCH")
    else:
        need(not halt_requested, "NORMAL_CONTROL_IS_NOT_FAILURE_HALT")
    result = {"cell_id": cell["id"], "audit_status": "PASS_RECOMPUTED", "status": "VALID",
              "parent_branch": parent["branch"], "parent": parent, "force": force,
              "native_steps": len(rows), "halt": "NOT_REQUESTED", "hold": "NOT_RUN",
              "request_snapshot": None, "terminal_snapshot": None}
    result["wall"] = cell_wall
    result["completion_status"] = "TECHNICAL_PARTIAL" if outcome.get("status") in ("TECHNICAL_PARTIAL", "INTEGRITY_FAILURE", "BUDGET_FAILURE") else "COMPLETE"
    normal_eligible = True
    if normal:
        parent_result = read_json(folder / "parent_result.json")
        normal_eligible = bool(parent["strict"] is True and parent_result.get("mission_success") is True
                               and parent_result.get("physical_success") is True and parent_result.get("completed_nodes") == 3
                               and not parent_result.get("physical_halt"))
        if not normal_eligible:
            need(not any(r["phase"] == "hold" for r in rows), "FAILED_NORMAL_PARENT_MUST_NOT_RUN_HOLD")
            result["parent_branch"] = "NORMAL_CONTROL_FAILED_NO_HOLD"
            return result
    if halt_requested or normal:
        if halt_requested and "stop_start" in events and "stop_return" not in events:
            stopstart = events["stop_start"]["snapshot"]
            need(events["halt_request"]["snapshot"] == stopstart, "HALT_REQUEST_STOP_ENTRY_GAP")
            stop_rows = rows[stopstart["native_steps"]:]
            if stop_rows:
                last_flags = OLD.physical_flags_from_native(stop_rows[-1], PHYSICAL)
                if not last_flags["raw_finite"] or last_flags["fallen"]:
                    need(not any(r["phase"] == "hold" for r in stop_rows), "UNSAFE_HALT_MUST_NOT_RUN_HOLD")
                    score = stop_score(stopstart, stop_rows, "UNSAFE", spec)
                    need(score["status"] == "FAILED", "UNSAFE_STOP_CANNOT_QUALIFY")
                    result.update(halt="FAILED", stop=score, request_snapshot=stopstart,
                                  terminal_snapshot=witness.get("final_snapshot"),
                                  terminal_coverage="OBSERVED_UNSAFE_RAW_TERMINAL_WITHOUT_STOP_RETURN")
                    return result
        ss, se = events["stop_start"], events["stop_return"]
        stopstart, terminal = ss["snapshot"], se["snapshot"]
        if halt_requested:
            need(events["halt_request"]["snapshot"] == stopstart, "HALT_REQUEST_STOP_ENTRY_GAP")
        stop_rows = rows[stopstart["native_steps"]:terminal["native_steps"]]
        need(all(c["command_xyz_mps_radps"] == [0., 0., 0.] for c in commands[stopstart["native_steps"]:terminal["native_steps"]]),
             "ACTUAL_STOP_COMMAND_NONZERO")
        score = stop_score(stopstart, stop_rows, se["status"], spec)
        result.update(stop=score, request_snapshot=stopstart, terminal_snapshot=terminal)
        if normal:
            result["parent_branch"] = "NORMAL_STOP"
        else:
            result["halt"] = score["status"]
        holds = [r for r in rows if r["phase"] == "hold"]
        if score["status"] == "SUCCEEDED":
            entry = read_json(folder / "hold_entry.json")["pre_first_step"]
            OLD.exact_snapshots(terminal, entry, label="TERMINAL_TO_HOLD_ENTRY")
            hold_logs = read_jsonl(folder / "hold_incremental.jsonl")
            hold = hold_score(entry, holds, hold_logs, score["seed_speeds"], spec)
            result["hold"] = "SUCCEEDED" if hold["status"] == "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE" else "FAILED" if hold["status"] == "HOLD_FAILED" else "TECHNICAL_PARTIAL"
            result["hold_recomputed"] = hold
            final = witness["final_snapshot"]
            for key in (*OLD.IDENTITY_KEYS, *OLD.COUNTER_KEYS):
                need(final[key] == terminal[key], "HOLD_IDENTITY_RESET_DISPATCH_CHANGED:" + key)
            snapshot_matches(final, rows, "final")
            if result["hold"] == "TECHNICAL_PARTIAL":
                result.update(status="TECHNICAL_PARTIAL", audit_status="TECHNICAL_PARTIAL")
        else:
            need(not holds, "FAILED_STOP_MUST_NOT_RUN_HOLD")
    else:
        need(not any(r["phase"] == "hold" for r in rows), "NONTRIGGER_MUST_NOT_RUN_HOLD")
    return result


def audit_cell(folder, spec, cell):
    try:
        return _audit_cell(Path(folder), spec, cell)
    except EvidenceError as exc:
        return {"cell_id": cell["id"], "status": exc.category, "audit_status": exc.category,
                "reason": exc.reason, "scientific_status": None}
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        return {"cell_id": cell["id"], "status": "MISSING_EVIDENCE", "audit_status": "MISSING_EVIDENCE",
                "reason": type(exc).__name__ + ": " + str(exc), "scientific_status": None}


def state_distinctness(results, historical, spec):
    thresholds = spec["state_distinctness"]["features"]
    controls = [r for r in results if r["cell_id"] in ("seen_no_push_anchor", "normal_stop_control")]
    primaries = [r for r in results if r["cell_id"] in spec["required_primary_cells"]]
    novel = set(spec["required_primary_cells"] + spec["secondary_unseen_cells"])
    for row in results:
        if row["cell_id"] not in novel or row.get("status") != "VALID":
            continue
        row["distinctness_pairs"] = {}
        for field, reference_key, flag in (("request_snapshot", "request", "request_distinct"),
                                           ("terminal_snapshot", "terminal", "hold_entry_distinct")):
            if row.get(field) is None:
                row[flag] = False
                continue
            refs = {"historical:" + name: state[reference_key] for name, state in historical.items()}
            refs.update({"same_campaign:" + r["cell_id"]: r[field] for r in controls if r.get(field)})
            refs.update({"primary:" + r["cell_id"]: r[field] for r in primaries if r["cell_id"] != row["cell_id"] and r.get(field)})
            pairs = {}
            for name, ref in refs.items():
                try:
                    pairs[name] = GEOMETRY.state_difference(row[field], ref, thresholds)
                except (ValueError, TypeError):
                    pairs[name] = {"operationally_distinct": False, "deltas": None, "coverage": "PHYSICAL_DESCRIPTOR_UNAVAILABLE"}
            row["distinctness_pairs"][field] = pairs
            row[flag] = len(historical) == 3 and bool(pairs) and all(p["operationally_distinct"] for p in pairs.values())
        other = [r for r in primaries if r["cell_id"] != row["cell_id"]]
        peer_names = ["primary:" + r["cell_id"] for r in other]
        row["distinct_from_other_primary"] = bool(other) and all(
            name in row["distinctness_pairs"].get(f, {}) and row["distinctness_pairs"][f][name]["operationally_distinct"]
            for name in peer_names for f in ("request_snapshot", "terminal_snapshot"))
    return results


def campaign_score(results, spec):
    """Independent layerwise decision; includes all planned NOT_RUN rows."""
    byid = {r["cell_id"]: r for r in results}
    planned = [c["id"] for c in spec["cells_in_order"]]
    need([r["cell_id"] for r in results] == planned, "CAMPAIGN_CELL_ORDER_MISMATCH")
    valid = [r for r in results if r.get("status") == "VALID"]
    new = set(spec["required_primary_cells"] + spec["secondary_unseen_cells"])
    negatives, aliases = [], []
    for r in valid:
        physical_negative = r.get("halt") == "FAILED" or r.get("hold") == "FAILED"
        if r["cell_id"] in new and physical_negative:
            distinct = r.get("request_distinct") and (r.get("halt") == "FAILED" or r.get("hold_entry_distinct"))
            (negatives if distinct else aliases).append(r["cell_id"])
    controls_ok = (byid[planned[0]].get("halt") == "SUCCEEDED" and byid[planned[0]].get("hold") == "SUCCEEDED"
                   and byid["seen_plus_y_early_control"].get("parent_branch") == "STRICT_PASS_NO_HALT"
                   and byid["normal_stop_control"].get("hold") == "SUCCEEDED")
    primary_ok = all(byid[p].get("halt") == byid[p].get("hold") == "SUCCEEDED"
                     and byid[p].get("request_distinct") and byid[p].get("hold_entry_distinct")
                     and byid[p].get("distinct_from_other_primary") for p in spec["required_primary_cells"])
    secondary_ok = all(byid[p].get("parent_branch") == "STRICT_PASS_NO_HALT" or
                       byid[p].get("halt") == byid[p].get("hold") == "SUCCEEDED" for p in spec["secondary_unseen_cells"])
    complete = len(valid) == len(planned) and all(r.get("completion_status", "COMPLETE") == "COMPLETE" for r in valid)
    scientific = ("BOUNDED_UNSEEN_COUNTEREXAMPLE" if negatives else "BOUNDED_PRIMARY_PAIR_SUPPORTED"
                  if complete and controls_ok and primary_ok and secondary_ok else "INCONCLUSIVE_COVERAGE_OR_TECHNICAL")
    requested = [r for r in valid if r.get("parent_branch") == "STRICT_TRIGGER"]
    eligible = [r for r in requested if r.get("halt") == "SUCCEEDED"]
    return {"scientific_signal": scientific, "campaign_completion": "COMPLETE" if complete else "PARTIAL",
            "counterexamples": negatives, "condition_negatives_not_distinct": aliases,
            "failure_chain_halt_denominator": len(requested), "failure_chain_hold_denominator": len(eligible),
            "halt_success_fraction": sum(r["halt"] == "SUCCEEDED" for r in requested)/len(requested) if requested else None,
            "hold_success_fraction": sum(r["hold"] == "SUCCEEDED" for r in eligible)/len(eligible) if eligible else None}


def verify_byte_maps(source_files, readiness_files, *, root=ROOT):
    for name in source_files.keys() & readiness_files.keys():
        need(source_files[name] == readiness_files[name], "FREEZE_MAP_CONFLICT:" + name)
    for name, sha in list(source_files.items()) + list(readiness_files.items()):
        path = (root / name).resolve()
        need(path.is_relative_to(root) and path.is_file() and digest(path) == sha, "FROZEN_SOURCE_OR_ASSET_MISMATCH:" + name)


def verify_sources(readiness_sha256, *, execution_head=None):
    """Independently verify explicit execution-byte authority, not old manifest counts."""
    ready_path = HERE / "readiness_manifest.json"
    need(digest(ready_path) == readiness_sha256, "EXACT_READINESS_SHA_MISMATCH")
    ready = read_json(ready_path)
    source_path = HERE / "source_manifest.json"
    source = read_json(source_path)
    need(ready["status"] == "READY_FOR_OWNER_ACQUISITION_AUTHORIZATION" and ready["physics_authorized"] is False,
         "READINESS_AUTHORITY_INVALID")
    need(source["status"] == "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY" and source["physics_authorized"] is False,
         "SOURCE_AUTHORITY_INVALID")
    need(digest(source_path) == ready["source_manifest_sha256"], "READINESS_SOURCE_HASH_MISMATCH")
    need(source["design_protocol_sha256"] == digest(DESIGN / "protocol.json"), "FROZEN_DESIGN_HASH_MISMATCH")
    required = {"experiments/m2/unseen_halt_hold_readiness_001/acquire.py",
                "experiments/m2/unseen_halt_hold_readiness_001/audit.py",
                "src/g1swarm/skills/basic.py", "src/g1swarm/control/g1_locomotion.py",
                "src/g1swarm/simulation/g1_simulation.py", "src/g1swarm/mission/live_session.py"}
    need(required <= set(source["files"]), "INCOMPLETE_EXECUTION_SOURCE_CLOSURE")
    verify_byte_maps(source["files"], ready["sha256"])
    return {"files": len(source["files"]), "readiness_sha256": readiness_sha256,
            "execution_head_expected": execution_head, "source_manifest_sha256": digest(source_path)}


def journal_coverage(path):
    """Retain valid prefix count when a killed worker left a partial JSON line."""
    count, incomplete = 0, False
    with Path(path).open(encoding="utf8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
                need(isinstance(row, dict), "JOURNAL_NONOBJECT_ROW")
                count += 1
            except (json.JSONDecodeError, EvidenceError):
                incomplete = True
                break
    return {"complete_rows": count, "truncated_or_invalid_tail": incomplete,
            "inflight_physics_step_count": "UNKNOWN" if incomplete else "NO_TRAILING_FRAGMENT"}


def audit_campaign(folder, *, spec_path=DESIGN / "protocol.json", historical=None,
                   readiness_sha256=None, execution_head=None):
    folder = Path(folder)
    spec = read_json(spec_path)
    source_receipt = verify_sources(readiness_sha256, execution_head=execution_head) if readiness_sha256 else None
    receipt = read_json(folder / "campaign_receipt.json")
    wall_issue = None
    try:
        wall = wall_receipt(receipt, spec["budget"]["maximum_wall_s_total"], "campaign")
    except EvidenceError as exc:
        wall_issue = {"audit_status": exc.category, "reason": exc.reason}
        wall = {"status": "INVALID_OR_OVERRUN", "recorded_receipt": receipt}
    need(receipt["frozen_budget"] == spec["budget"], "CAMPAIGN_BUDGET_BINDING_MISMATCH")
    unknown = [p.name for p in folder.iterdir() if p.is_dir() and p.name not in {c["id"] for c in spec["cells_in_order"]}]
    need(not unknown, "UNFROZEN_CELL_DIRECTORIES")
    results = [audit_cell(folder / cell["id"], spec, cell) if (folder/cell["id"]).exists()
               else {"cell_id": cell["id"], "status": "NOT_RUN", "audit_status": "NOT_RUN"}
               for cell in spec["cells_in_order"]]
    hist = historical_m25() if historical is None else historical
    state_distinctness(results, hist, spec)
    valid_byid = {r["cell_id"]: r for r in results if r.get("status") == "VALID"}
    raw_byid = {name: read_jsonl(folder/name/"native_incremental.jsonl") for name in valid_byid}
    anchor = raw_byid.get("seen_no_push_anchor")
    if anchor is not None:
        for cell in spec["cells_in_order"]:
            if cell["push"] and cell["id"] in raw_byid:
                prefix = cell["push"]["native_pre_step_start_index"]
                actual = min(prefix, len(raw_byid[cell["id"]]))
                raw_prefix(anchor, raw_byid[cell["id"]], actual)
    observed_ids = [r["cell_id"] for r in results if r.get("status") != "NOT_RUN"]
    need(observed_ids == [c["id"] for c in spec["cells_in_order"][:len(observed_ids)]], "CAMPAIGN_REORDER_OR_GAP")
    counts = {name: journal_coverage(folder/name/"native_incremental.jsonl") for name in observed_ids
              if (folder/name/"native_incremental.jsonl").is_file()}
    for name, coverage in counts.items():
        if not (folder/name/"witness.json").is_file() or (folder/name/"supervisor_timeout.json").exists():
            coverage["inflight_physics_step_count"] = "UNKNOWN"
    total = sum(c["complete_rows"] for c in counts.values())
    need(total <= spec["budget"]["maximum_native_steps_total"], "TOTAL_NATIVE_BUDGET_EXCEEDED")
    need(receipt.get("status") in ("PARTIAL_STOPPED", "ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT"), "UNKNOWN_CAMPAIGN_COMPLETION")
    if source_receipt:
        missing_source_witnesses = []
        for name in observed_ids:
            if not (folder/name/"witness.json").is_file() and receipt["status"] == "PARTIAL_STOPPED":
                missing_source_witnesses.append(name)
                continue
            witness = read_json(folder/name/"witness.json")
            need(witness.get("readiness_sha256") == readiness_sha256, "CELL_READINESS_BINDING_MISMATCH")
            need(witness.get("source_manifest_sha256") == source_receipt["source_manifest_sha256"], "CELL_SOURCE_BINDING_MISMATCH")
            need(witness.get("protocol_sha256") == digest(spec_path), "CELL_DESIGN_PROTOCOL_BINDING_MISMATCH")
        need(receipt.get("readiness_sha256") == readiness_sha256, "CAMPAIGN_READINESS_BINDING_MISMATCH")
        need(receipt.get("source_manifest_sha256") == source_receipt["source_manifest_sha256"], "CAMPAIGN_SOURCE_BINDING_MISMATCH")
        need(receipt.get("protocol_sha256") == digest(spec_path), "CAMPAIGN_DESIGN_BINDING_MISMATCH")
        if execution_head:
            need(receipt.get("execution_head") == execution_head, "CAMPAIGN_EXECUTION_HEAD_MISMATCH")
    decision = campaign_score(results, spec)
    observed_event_counts = {"first_walk_end": 0, "halt_request": 0, "stop_return": 0}
    for name in observed_ids:
        event_path = folder/name/"lifecycle_events.jsonl"
        if event_path.is_file():
            try:
                events = read_jsonl(event_path)
                for event_name in observed_event_counts:
                    observed_event_counts[event_name] += sum(row.get("event") == event_name for row in events)
            except EvidenceError:
                pass  # Raw bytes remain hashed; truncated event coverage is unavailable.
    coverage = {"planned_cells": len(spec["cells_in_order"]), "cells_with_native_journals": len(counts),
                "observed_events": observed_event_counts,
                "valid_scorable_failure_halt_requests": decision["failure_chain_halt_denominator"],
                "valid_failure_hold_eligible": decision["failure_chain_hold_denominator"],
                "halt_requests_not_independently_scorable": observed_event_counts["halt_request"] - decision["failure_chain_halt_denominator"],
                "fraction_basis": "success fractions condition on independently valid scorable chains; censored requests are listed separately, never scored as physical failure"}
    if receipt["status"] == "PARTIAL_STOPPED" or wall_issue:
        decision["campaign_completion"] = "PARTIAL"
        if decision["scientific_signal"] == "BOUNDED_PRIMARY_PAIR_SUPPORTED":
            decision["scientific_signal"] = "INCONCLUSIVE_COVERAGE_OR_TECHNICAL"
    return {"status": "READ_ONLY_RECOMPUTATION", "cells": results, "decision": decision,
            "source_verification": source_receipt,
            "missing_cell_source_witnesses": missing_source_witnesses if source_receipt else None,
            "campaign_integrity_issues": [wall_issue] if wall_issue else [],
            "native_journal_coverage": counts,
            "wall": wall,
            "layerwise_coverage": coverage,
            "native_steps": total, "raw_sha256": {p.relative_to(folder).as_posix(): digest(p)
                                                     for p in folder.rglob("*") if p.is_file()},
            "physics_policy_provider_calls": 0, "historical_verdicts_unchanged": spec["historical_results_unchanged"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--readiness-sha256", required=True)
    parser.add_argument("--execution-head", required=True)
    args = parser.parse_args()
    print(json.dumps(audit_campaign(args.campaign, readiness_sha256=args.readiness_sha256,
                                   execution_head=args.execution_head), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
