"""Offline semantics audit. Stdlib only; never imports a simulator or evaluator.

Reproduce into a NEW directory with --output; existing receipts are never replaced.
The historical labels are verification inputs, not outputs of a new campaign.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = "experiments/phase3a/correction_tradeoff_isolation_001"
TOL = 1e-10  # Roundoff audit only; never a task threshold.


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw(state):
    w, x, y, z = state["base_orientation"]
    return math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


def project(point, origin, heading):
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    c, s = math.cos(heading), math.sin(heading)
    return c*dx + s*dy, -s*dx + c*dy


def endpoint_box_distance(target_in_local, distance, limits):
    """Euclidean lower bound over acceptance box, not dynamic reachability."""
    x, y = target_in_local
    a, b = limits["distance_error_max_m"], limits["lateral_drift_max_m"]
    closest = [min(max(x, distance-a), distance+a), min(max(y, -b), b)]
    return {"closest_local_xy_m": closest,
            "position_error_lower_bound_m": math.hypot(x-closest[0], y-closest[1]),
            "role": "Acceptance-box relaxation; ignores termination, path, time and dynamics"}


def analyze():
    checks = {"numeric_checks": 0, "predicate_checks": 0, "maximum_roundoff_difference": 0.0}

    def close(actual, expected):
        checks["numeric_checks"] += 1
        error = abs(actual - expected)
        checks["maximum_roundoff_difference"] = max(checks["maximum_roundoff_difference"], error)
        if not math.isfinite(error) or error > TOL:
            raise AssertionError(f"Arithmetic mismatch: {actual!r} != {expected!r}")

    def require(condition, name):
        checks["predicate_checks"] += 1
        if not condition:
            raise AssertionError(name)

    protocol = read(HERE.relative_to(ROOT) / "protocol.json")
    sources = read(HERE.relative_to(ROOT) / "source_manifest.json")
    require(sha(HERE / "source_manifest.json") == protocol["source_manifest_sha256"], "Source manifest changed")
    for path, digest in sources["files"].items():
        require(sha(ROOT / path) == digest, f"Source changed: {path}")
    exports = read(f"{OLD}/evidence_manifest.json")
    for path, item in exports["files"].items():
        payload = (ROOT / path).read_bytes()
        require(hashlib.sha256(payload).hexdigest() == item["sha256"], path)
        require(len(payload) == item["bytes"], f"Size: {path}")
        raw = gzip.decompress(payload) if item["encoding"] == "gzip" else payload
        require(hashlib.sha256(raw).hexdigest() == item["raw_sha256"], f"Decoded source: {path}")
    records = [json.loads(line) for line in gzip.decompress((ROOT / f"{OLD}/evidence/results.jsonl.gz").read_bytes()).splitlines()]
    prior_protocol = read(f"{OLD}/protocol.json")
    cases = {c["id"]: c for c in read(f"{OLD}/case_manifest.json")["cases"]}
    require(len(records) == len(prior_protocol["schedule"]) == 16, "Exact retained membership")
    rows = []
    for line_number, (record, scheduled) in enumerate(zip(records, prior_protocol["schedule"]), 1):
        require(all(record[k] == scheduled[k] for k in ("case_id", "alpha", "phase", "repetition")), "Frozen order")
        require(record["provenance"]["protocol_sha256"] == sha(ROOT / f"{OLD}/protocol.json"), "Acquisition protocol")
        require(record["provenance"]["case_manifest_sha256"] == sha(ROOT / f"{OLD}/case_manifest.json"), "Acquisition cases")
        require(record["provenance"]["code_commit"] == sources["scientific_acquisition_commit"], "Acquisition code")
        require(not record["residual_enabled"] and not record["PPO_training"], "Residual-off source")
        case = cases[record["case_id"]]
        require(len(record["nodes"]) == len(case["nodes"]), "No omitted nodes")
        first = record["nodes"][0]["start_state"]
        planned_origin, planned_heading = list(first["base_position"][:2]), yaw(first)
        node_rows = []
        for index, (node, expected) in enumerate(zip(record["nodes"], case["nodes"])):
            require(node["skill"] == expected["skill"] and node["parameters"] == expected["parameters"], "Immutable node semantics")
            start, end = node["start_state"], node["end_state"]
            local_heading = yaw(start)
            lx, ly = project(end["base_position"], start["base_position"], local_heading)
            close(lx, node["forward_progress_m"])
            close(ly, node["lateral_drift_m"])
            terminal_origin = list(planned_origin)
            terminal_heading = planned_heading
            if node["skill"] == "walk_forward":
                distance = node["parameters"]["target_distance_m"]
                terminal_origin[0] += distance*math.cos(planned_heading)
                terminal_origin[1] += distance*math.sin(planned_heading)
            elif node["skill"] == "turn":
                terminal_heading = wrap(planned_heading + math.radians(node["parameters"]["target_angle_deg"]))
            along, lateral = project(end["base_position"], terminal_origin, planned_heading)
            global_heading = math.degrees(wrap(yaw(end)-terminal_heading))
            close(lateral, node["ideal_path_lateral_error_m"])
            close(global_heading, node["ideal_path_heading_error_deg"])
            vector = [end["base_position"][j]-terminal_origin[j] for j in range(2)]
            derived = {"node_index": index, "skill": node["skill"],
                       "source_locator": f"{OLD}/evidence/results.jsonl.gz#decoded-line={line_number}&pointer=/nodes/{index}",
                       "commanded_terminal_xy_m": terminal_origin, "commanded_terminal_heading_deg": math.degrees(terminal_heading),
                       "world_terminal_error_xy_m": vector, "world_terminal_error_norm_m": math.hypot(*vector),
                       "along_commanded_axis_terminal_error_m": along, "cross_commanded_axis_terminal_error_m": lateral,
                       "world_terminal_heading_error_deg": global_heading,
                       "actual_start_origin_xy_m": start["base_position"][:2], "actual_start_heading_deg": math.degrees(local_heading),
                       "original_nominal_success": node["task_success"], "original_strict_success": node["strict_success"],
                       "original_physical_success": node["physical_success"], "original_status": node["status"]}
            if node["skill"] == "walk_forward":
                reference = node["walking_reference"]
                for j in range(2):
                    close(reference["measurement_origin"][j], start["base_position"][j])
                    close(reference["control_origin"][j], start["base_position"][j])
                    close(reference["planned_origin"][j], planned_origin[j])
                close(reference["measurement_heading_rad"], local_heading)
                close(reference["planned_heading_rad"], planned_heading)
                selected_heading = reference["control_heading_rad"]
                rx, ry = project(end["base_position"], reference["control_origin"], selected_heading)
                delta = wrap(selected_heading - local_heading)
                close(ry, node["control_frame_diagnostics"]["lateral_m"])
                close(ry, -lx*math.sin(delta)+ly*math.cos(delta))
                close(ly, lx*math.tan(delta)+ry/math.cos(delta))
                target_local = project(terminal_origin, start["base_position"], local_heading)
                feasibility = {}
                for profile in ("nominal", "strict"):
                    original = node["envelope"][f"{profile}_envelope"]
                    limits = original["limits"]
                    values = [abs(lx-distance), abs(ly), abs(node["heading_error_deg"]), node["duration_s"]]
                    bounds = [limits[k] for k in ("distance_error_max_m", "lateral_drift_max_m", "heading_error_max_deg", "timeout_max_s")]
                    verified = all(v <= b for v, b in zip(values, bounds))
                    require(verified == original["satisfied"], "Original envelope arithmetic; no relabeling")
                    require(bool(verified and node["physical_success"] and node["status"] == "SUCCESS") == node[f'{profile}_success' if profile == "strict" else "task_success"], "Original complete predicate")
                    b, c, s = limits["lateral_drift_max_m"], math.cos(delta), math.sin(delta)
                    interval = sorted([-lx*s-b*c, -lx*s+b*c])
                    feasibility[profile] = {
                        "original_limits": limits, "original_violations": original["violations"],
                        "compatible_reference_lateral_interval_at_observed_forward_m": interval,
                        "zero_reference_lateral_compatible_at_observed_forward": interval[0] <= 0 <= interval[1],
                        "reference_ray_local_lateral_at_observed_forward_m": lx*math.tan(delta),
                        "ideal_waypoint_inside_local_position_box": abs(target_local[0]-distance) <= limits["distance_error_max_m"] and abs(target_local[1]) <= b,
                        "global_waypoint_box_relaxation": endpoint_box_distance(target_local, distance, limits)}
                derived.update(local_endpoint_xy_m=[lx, ly], selected_reference_endpoint_xy_m=[rx, ry],
                               selected_reference_heading_deg=math.degrees(selected_heading),
                               reference_axis_rotation_deg=math.degrees(delta),
                               ideal_waypoint_in_fixed_local_xy_m=list(target_local), compatibility=feasibility)
            node_rows.append(derived)
            planned_origin, planned_heading = terminal_origin, terminal_heading
        final = record["final_state"]["base_position"]
        final_vector = [final[j]-planned_origin[j] for j in range(2)]
        close(math.hypot(*final_vector), record["ideal_endpoint_error_m"])
        require(record["task_success"] == all(n["task_success"] for n in record["nodes"]), "Nominal sequence predicate")
        rows.append({"run_id": record["run_id"], "alpha": record["alpha"], "case_id": record["case_id"],
                     "phase": record["phase"], "decoded_source_line": line_number,
                     "original_nominal_success": record["task_success"],
                     "original_strict_success": all(n["strict_success"] for n in record["nodes"]),
                     "original_physical_success": record["physical_success"],
                     "world_final_error_xy_m": final_vector, "world_final_error_norm_m": record["ideal_endpoint_error_m"],
                     "nodes": node_rows})
    half = next(r for r in rows if r["case_id"] == "sequence-mixed-16m" and r["phase"] == "primary" and r["alpha"] == .5)
    walk = half["nodes"][1]
    require(not half["original_strict_success"] and half["original_nominal_success"] and half["original_physical_success"], "Retain alpha0.5 negative result")
    require(not walk["compatibility"]["strict"]["zero_reference_lateral_compatible_at_observed_forward"], "Tracking zero vs strict conflict")
    require(not walk["compatibility"]["nominal"]["ideal_waypoint_inside_local_position_box"], "Exact waypoint vs nominal conflict")
    quarter = next(r for r in rows if r["case_id"] == "sequence-mixed-16m" and r["phase"] == "primary" and r["alpha"] == .25)
    baseline = next(r for r in rows if r["case_id"] == "sequence-mixed-16m" and r["phase"] == "primary" and r["alpha"] == 0)
    require(quarter["original_strict_success"] and quarter["world_final_error_norm_m"] < baseline["world_final_error_norm_m"], "Retain non-universal conflict counterexample; no alpha selection")

    # Analytic examples only. These are not robot trajectories or new gold cases.
    counterexamples = [
        {"id": "C01_reference_score_substitution", "kind": "retained_acquisition", "run_id": half["run_id"],
         "local_lateral_m": walk["local_endpoint_xy_m"][1], "reference_lateral_m": walk["selected_reference_endpoint_xy_m"][1],
         "original_strict_success": False, "conclusion": "Reference tracking cannot replace fixed local acceptance."},
        {"id": "C02_endpoint_return", "kind": "synthetic_geometry_not_physics", "xy_m": [[0,0],[4,1],[8,0]],
         "endpoint_lateral_m": 0, "path_peak_lateral_m": 1,
         "conclusion": "Endpoint containment does not imply all-path containment."},
        {"id": "C03_sample_aliasing", "kind": "synthetic_geometry_not_physics",
         "analytic_lateral_function": "sin(pi*t/0.05)^2 m for 0<=t<=0.05s",
         "sample_times_s": [0,.05], "sample_lateral_m": [0,0], "between_samples_peak_m": 1,
         "conclusion": "Even all 20Hz samples inside cannot certify continuous containment."},
        {"id": "C04_final_cancellation", "kind": "synthetic_geometry_not_physics",
         "ordered_node_error_vectors_m": [[0,1],[0,-1],[0,0]], "final_error_norm_m": 0,
         "conclusion": "Final error cannot erase earlier node deviations or prove route completion."},
        {"id": "C05_along_track_hidden", "kind": "synthetic_geometry_not_physics",
         "commanded_xy_m": [8,0], "actual_xy_m": [6,0], "lateral_error_m": 0, "endpoint_norm_m": 2,
         "conclusion": "Lateral alone hides failed forward progress."},
        {"id": "C06_origin_reset", "kind": "synthetic_geometry_not_physics",
         "world_point_m": [8,1], "authorized_origin_m": [0,0], "posthoc_origin_m": [8,1],
         "fixed_lateral_m": 1, "posthoc_lateral_m": 0,
         "conclusion": "Actor/analyst cannot move the evaluation anchor to the observed state."},
        {"id": "C07_upstream_yaw_laundering", "kind": "synthetic_geometry_not_physics",
         "world_commanded_heading_deg": 0, "actual_node_start_deg": -5, "actual_node_end_deg": -5,
         "local_heading_error_deg": 0, "world_heading_error_deg": -5,
         "conclusion": "Local success retains inherited world error; latch time/node authority is fixed."},
        {"id": "C08_turn_phase_semantics", "kind": "synthetic_geometry_not_physics",
         "commanded_turn_deg": -90, "actual_turn_deg": -90, "relative_turn_error_deg": 0,
         "conclusion": "Raw heading change includes intentional rotation; not a heading-error metric."},
        {"id": "C09_physical_failure_masking", "kind": "synthetic_logical_predicate_not_physics",
         "all_terminal_geometry_zero": True, "fall_event_recorded": True, "physical_eligibility": False,
         "conclusion": "Good geometry or reward cannot compensate a physical event."},
        {"id": "C10_timeout_is_not_fall", "kind": "synthetic_logical_predicate_not_physics",
         "skill_status": "TIMEOUT", "fallen": False, "finite": True, "simulation_completed": True,
         "frozen_physical_predicate": True, "skill_task_completion": False,
         "conclusion": "Physical survival, skill status and complete mission remain separate."},
        {"id": "C11_waypoint_skip", "kind": "synthetic_logical_predicate_not_physics",
         "final_endpoint_error_m": 0, "required_nodes": 7, "observed_nodes": 2, "complete_execution": False,
         "conclusion": "Fixed ordered node membership cannot be replaced by reaching the final point."},
        {"id": "C12_nonzero_tracking_for_compliance", "kind": "derived_static_geometry_not_physics",
         "source_run_id": half["run_id"], "strict_compatible_reference_lateral_interval_m": walk["compatibility"]["strict"]["compatible_reference_lateral_interval_at_observed_forward_m"],
         "conclusion": "Local-compliant endpoint needs nonzero reference deviation here; dynamics not established."}]
    require(counterexamples[1]["endpoint_lateral_m"] < .28 < counterexamples[1]["path_peak_lateral_m"], "Endpoint-return distinction")
    close(math.sin(math.pi*.025/.05)**2, counterexamples[2]["between_samples_peak_m"])
    require(all(abs(math.sin(math.pi*t/.05)**2) < TOL for t in counterexamples[2]["sample_times_s"]), "Aliasing distinction")
    close(math.hypot(6-8, 0), counterexamples[4]["endpoint_norm_m"])
    close(project([8,1], [0,0], 0)[1], counterexamples[5]["fixed_lateral_m"])
    close(project([8,1], [8,1], 0)[1], counterexamples[5]["posthoc_lateral_m"])
    close(math.degrees(wrap(math.radians(-90)-math.radians(-90))), 0)
    require(set(r["run_id"] for r in rows).__len__() == 16, "Unique retained run identities")
    return {"evidence_type": "offline_derived_semantics; no original score replaced", "records": rows,
            "counterexamples": counterexamples, "checks": checks}, {
                "verdict": "PASS_OFFLINE_CONTRACT_DISTINCTIONS", "source_files_verified": len(sources["files"]),
                "exports_encoded_and_decoded_verified": len(exports["files"]), "retained_records_verified": len(rows),
                "counterexamples_retained": len(counterexamples), "roundoff_tolerance": TOL,
                "roundoff_role": "not a scientific success threshold", "checks": checks,
                "new_physics_episodes": 0, "training_steps": 0, "provider_calls": 0,
                "protocol_sha256": sha(HERE/"protocol.json"), "source_manifest_sha256": sha(HERE/"source_manifest.json"),
                "analysis_script_sha256": sha(Path(__file__)),
                "analysis_execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    targets = [args.output/name for name in ("analysis.json", "validation.json")]
    if any(p.exists() for p in targets):
        raise SystemExit("Refusing to overwrite retained receipts; use a NEW --output directory")
    analysis, validation = analyze()
    for target, value in zip(targets, [analysis, validation]):
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print(json.dumps(validation, indent=2))
