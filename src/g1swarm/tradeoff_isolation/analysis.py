"""Independent, read-only diagnostics for the frozen correction trade-off study.

No evaluator, controller or physics function is imported here. Stored outcomes
remain authoritative. Coordinate/command reconstruction audits the evidence;
the geometric decomposition explains outcomes without changing their labels.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

AUDIT_TOL = 1e-10
SEQUENCE_ID = "sequence-mixed-16m"
PRIMITIVE_ID = "primitive-walk-8"
SEQUENCE_ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
PRIMITIVE_ALPHAS = (0.0, 0.5, 1.0)


def wrap(angle: float) -> float:
    return math.atan2(math.sin(float(angle)), math.cos(float(angle)))


def yaw_from_quaternion(quaternion: Sequence[float]) -> float:
    """MuJoCo free-joint quaternion is w,x,y,z; normalize independently."""
    w, x, y, z = (float(v) for v in quaternion)
    norm = math.sqrt(w*w+x*x+y*y+z*z)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Quaternion must be finite and nonzero")
    w, x, y, z = w/norm, x/norm, y/norm, z/norm
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def project(position: Sequence[float], origin: Sequence[float], heading: float) -> tuple[float, float]:
    """World XY to an independently constructed orthonormal reference."""
    dx, dy = float(position[0])-float(origin[0]), float(position[1])-float(origin[1])
    c, s = math.cos(float(heading)), math.sin(float(heading))
    return c*dx+s*dy, -s*dx+c*dy


def lateral_decomposition(local_forward: float, control_lateral: float, delta: float) -> dict[str, float]:
    """Same-origin frame rotation: local_y = local_x*tan(delta)+control_y/cos(delta)."""
    c = math.cos(delta)
    if abs(c) < 1e-12:
        raise ValueError("Lateral decomposition is singular near a 90-degree frame rotation")
    geometry = float(local_forward)*math.tan(delta)
    tracking = float(control_lateral)/c
    return {"rotation_component_m": geometry, "selected_tracking_component_m": tracking,
            "reconstructed_local_lateral_m": geometry+tracking}


def reconstruct_command(nominal: Sequence[float], heading_error_rad: float,
                        control_lateral_m: float) -> dict[str, Any]:
    """Reconstruct the frozen 1.5/1.0 gains, 0.01 deadband and 0.6 clamp."""
    before_deadband = -1.5*float(heading_error_rad)-float(control_lateral_m)
    after_deadband = 0.0 if abs(before_deadband) < 0.01 else before_deadband
    clipped = max(-0.6, min(0.6, after_deadband))
    return {"command": [float(nominal[0]), float(nominal[1]), clipped],
            "yaw_before_deadband_radps": before_deadband,
            "yaw_raw_radps": after_deadband, "yaw_clipped_radps": clipped,
            "saturated": abs(after_deadband) > 0.6+1e-12}


def _alpha(record: Mapping[str, Any]) -> float:
    value = record.get("heading_alignment_alpha", record.get("alpha"))
    if value is None:
        raise ValueError("Result has no alpha identity")
    return float(value)


def _run_id(record: Mapping[str, Any]) -> str:
    return str(record.get("run_id", f"{record['phase']}--alpha{_alpha(record):g}--{record['case_id']}"))


class _Audits:
    def __init__(self):
        self.groups: dict[str, dict[str, Any]] = {}
        self.failures: list[dict[str, Any]] = []

    def flag(self, group: str, passed: bool, locator: str, detail: Any = None) -> None:
        summary = self.groups.setdefault(group, {"checks": 0, "failures": 0, "max_abs_error": 0.0})
        summary["checks"] += 1
        if not passed:
            summary["failures"] += 1
            if len(self.failures) < 100:
                self.failures.append({"audit": group, "locator": locator, "detail": detail})

    def close(self, group: str, observed: float, expected: float, locator: str) -> None:
        finite = math.isfinite(float(observed)) and math.isfinite(float(expected))
        error = abs(float(observed)-float(expected)) if finite else None
        self.flag(group, finite and error <= AUDIT_TOL, locator,
                  {"observed": float(observed) if math.isfinite(float(observed)) else None,
                   "independent_expected": float(expected) if math.isfinite(float(expected)) else None, "abs_error": error})
        if error is not None:
            self.groups[group]["max_abs_error"] = max(self.groups[group]["max_abs_error"], error)

    @property
    def passed(self) -> bool:
        return all(group["failures"] == 0 for group in self.groups.values())


def _strip_annotations(value: Any) -> Any:
    """Repeat identity excludes publication annotations and wall time, not scores."""
    excluded = {"provenance", "run_id", "phase", "repetition", "evaluation_set", "recorded_at"}
    if isinstance(value, dict):
        return {key: _strip_annotations(item) for key, item in value.items()
                if key not in excluded and "wall" not in key}
    if isinstance(value, list):
        return [_strip_annotations(item) for item in value]
    return value


def _check_array_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if set(left) != set(right):
        return False
    return all(np.array_equal(np.asarray(left[key]), np.asarray(right[key]), equal_nan=True) for key in left)


def _node_diagnostics(record: Mapping[str, Any], audits: _Audits) -> list[dict[str, Any]]:
    run_id = _run_id(record)
    first_start = record["nodes"][0]["start_state"]
    planned_origin = [float(v) for v in first_start["base_position"][:2]]
    planned_heading = yaw_from_quaternion(first_start["base_orientation"])
    nodes: list[dict[str, Any]] = []
    for index, node in enumerate(record["nodes"]):
        locator = f"{run_id}#/nodes/{index}"
        start, end = node["start_state"], node["end_state"]
        heading = yaw_from_quaternion(start["base_orientation"])
        actual_heading = yaw_from_quaternion(end["base_orientation"])
        forward, lateral = project(end["base_position"], start["base_position"], heading)
        measured_heading = math.degrees(wrap(actual_heading-heading))
        if node["skill"] == "turn":
            measured_heading -= float(node["parameters"]["target_angle_deg"])
        audits.close("node_local_forward", node["forward_progress_m"], forward, locator)
        audits.close("node_local_lateral", node["lateral_drift_m"], lateral, locator)
        audits.close("node_local_heading", node["heading_error_deg"], measured_heading, locator)
        _, global_lateral = project(end["base_position"], planned_origin, planned_heading)
        global_target_heading = planned_heading
        if node["skill"] == "turn":
            global_target_heading += math.radians(float(node["parameters"]["target_angle_deg"]))
        global_heading = math.degrees(wrap(actual_heading-global_target_heading))
        audits.close("node_global_lateral", node["ideal_path_lateral_error_m"], global_lateral, locator)
        audits.close("node_global_heading", node["ideal_path_heading_error_deg"], global_heading, locator)
        diagnostic: dict[str, Any] = {
            "node_index": index, "skill": node["skill"], "source_locator": locator,
            "local_forward_m": forward, "local_lateral_m": lateral,
            "local_heading_error_deg": measured_heading,
            "ideal_lateral_m": global_lateral, "ideal_heading_error_deg": global_heading,
            "task_success": bool(node["task_success"]), "strict_success": bool(node["strict_success"]),
            "physical_success": bool(node["physical_success"]), "fallen": bool(node["fallen"]),
            "max_tilt_deg": float(node["max_tilt_deg"]), "min_height_m": float(node["min_height_m"]),
            "duration_s": float(node["duration_s"]), "transition_metrics": node["transition_metrics"],
            "planned_origin_xy": list(planned_origin), "planned_heading_rad": planned_heading,
        }
        start_global_heading = wrap(heading-planned_heading)
        actual_dx = float(end["base_position"][0])-float(start["base_position"][0])
        actual_dy = float(end["base_position"][1])-float(start["base_position"][1])
        planned_dx = planned_dy = 0.0
        heading_multiplier = 1.0
        heading_injection = wrap(actual_heading-heading)
        if node["skill"] == "walk_forward":
            ref = node["walking_reference"]
            selected = float(ref["control_heading_rad"])
            expected_selected = wrap(heading+_alpha(record)*wrap(planned_heading-heading))
            audits.close("selected_heading_interpolation", wrap(selected-expected_selected), 0, locator)
            for axis in range(2):
                audits.close("actual_origin_preserved", ref["control_origin"][axis], start["base_position"][axis], locator)
                audits.close("measurement_origin_preserved", ref["measurement_origin"][axis], start["base_position"][axis], locator)
                audits.close("planned_origin_consistency", ref["planned_origin"][axis], planned_origin[axis], locator)
            audits.close("measurement_heading_preserved", ref["measurement_heading_rad"], heading, locator)
            audits.close("planned_heading_consistency", wrap(ref["planned_heading_rad"]-planned_heading), 0, locator)
            control_forward, control_lateral = project(end["base_position"], start["base_position"], selected)
            control_heading = math.degrees(wrap(actual_heading-selected))
            heading_multiplier = 1.0-_alpha(record)
            heading_injection = math.radians(control_heading)
            recurrence = wrap(heading_multiplier*start_global_heading+heading_injection)
            audits.close("walk_global_heading_recurrence", wrap(math.radians(global_heading)-recurrence), 0, locator)
            delta = wrap(selected-heading)
            parts = lateral_decomposition(forward, control_lateral, delta)
            audits.close("endpoint_rotation_identity", lateral, parts["reconstructed_local_lateral_m"], locator)
            audits.close("endpoint_heading_identity", wrap(math.radians(measured_heading)-math.radians(control_heading)-delta), 0, locator)
            for key, expected in (("forward_m", control_forward), ("lateral_m", control_lateral), ("heading_error_deg", control_heading)):
                audits.close("stored_control_diagnostics", node["control_frame_diagnostics"][key], expected, locator)
            envelope = node["envelope"]
            for name in ("nominal", "strict"):
                source = envelope[f"{name}_envelope"]
                limits = source["limits"]
                target = float(node["parameters"]["target_distance_m"])
                expected_limits = ({"distance_error_max_m": max(0.30, 0.10*target),
                                    "lateral_drift_max_m": max(0.35, 0.07*target),
                                    "heading_error_max_deg": 15.0, "timeout_max_s": max(15.0, 6.0*target)}
                                   if name == "nominal" else
                                   {"distance_error_max_m": max(0.15, 0.05*target),
                                    "lateral_drift_max_m": max(0.20, 0.035*target),
                                    "heading_error_max_deg": 8.0, "timeout_max_s": max(12.0, 5.0*target)})
                for key, value in expected_limits.items():
                    audits.close("frozen_envelope_limits_preserved", limits[key], value, locator+f"/envelope/{name}/{key}")
                independent = []
                for violation, value, limit in (
                    ("DISTANCE_ERROR", abs(forward-node["parameters"]["target_distance_m"]), limits["distance_error_max_m"]),
                    ("EXCESSIVE_DRIFT", abs(lateral), limits["lateral_drift_max_m"]),
                    ("HEADING_ERROR", abs(measured_heading), limits["heading_error_max_deg"]),
                    ("TIMEOUT", node["duration_s"], limits["timeout_max_s"]),
                ):
                    if value > limit:
                        independent.append(violation)
                audits.flag("frozen_envelope_interpretation", independent == source["violations"], locator+f"/envelope/{name}",
                            {"source_violations": source["violations"], "independent_violations": independent})
                expected_success = node["status"] == "SUCCESS" and bool(node["physical_success"]) and not independent
                stored_success = node["task_success"] if name == "nominal" else node["strict_success"]
                audits.flag("frozen_node_outcome_interpretation", stored_success == expected_success, locator+f"/{name}")
            nominal_limit = envelope["nominal_envelope"]["limits"]["lateral_drift_max_m"]
            strict_limit = envelope["strict_envelope"]["limits"]["lateral_drift_max_m"]
            remainder = abs(parts["selected_tracking_component_m"])
            geometry = abs(parts["rotation_component_m"])
            diagnostic.update(reference_rotation_deg=math.degrees(delta), control_forward_m=control_forward,
                control_lateral_m=control_lateral, control_heading_error_deg=control_heading,
                **parts, target_distance_projection_m=float(node["parameters"]["target_distance_m"])*math.tan(delta),
                strict_lateral_limit_m=float(strict_limit), nominal_lateral_limit_m=float(nominal_limit),
                tracking_remainder_fraction_of_strict_limit=remainder/float(strict_limit),
                tracking_remainder_fraction_of_rotation=remainder/geometry if geometry else None,
                rotation_magnitude_exceeds_tracking_remainder=geometry > remainder,
                strict_source_violations=list(envelope["strict_envelope"]["violations"]),
                nominal_source_violations=list(envelope["nominal_envelope"]["violations"]),
                walking_correction_stats=node["walking_correction_stats"])
            distance = float(node["parameters"]["target_distance_m"])
            planned_dx, planned_dy = distance*math.cos(planned_heading), distance*math.sin(planned_heading)
            planned_origin[0] += planned_dx
            planned_origin[1] += planned_dy
        elif node["skill"] == "turn":
            heading_injection = wrap(actual_heading-heading)-math.radians(float(node["parameters"]["target_angle_deg"]))
            recurrence = wrap(start_global_heading+heading_injection)
            audits.close("turn_global_heading_recurrence", wrap(math.radians(global_heading)-recurrence), 0, locator)
            planned_heading = wrap(planned_heading+math.radians(float(node["parameters"]["target_angle_deg"])))
        else:
            recurrence = wrap(start_global_heading+heading_injection)
            audits.close("stationary_skill_heading_recurrence", wrap(math.radians(global_heading)-recurrence), 0, locator)
        diagnostic["heading_recurrence"] = {
            "start_ideal_heading_error_deg": math.degrees(start_global_heading),
            "inherited_error_multiplier": heading_multiplier,
            "control_or_relative_skill_residual_deg": math.degrees(heading_injection),
            "reconstructed_end_ideal_heading_error_deg": math.degrees(wrap(heading_multiplier*start_global_heading+heading_injection)),
            "role": "Algebraic attribution; walking control residual and nonwalking motion remain measured evidence",
        }
        diagnostic["endpoint_vector_budget"] = {
            "actual_displacement_xy_m": [actual_dx, actual_dy],
            "commanded_displacement_xy_m": [planned_dx, planned_dy],
            "error_contribution_xy_m": [actual_dx-planned_dx, actual_dy-planned_dy],
            "role": "World-coordinate contribution; Stand/Turn/Stop translations are retained",
        }
        nodes.append(diagnostic)
    final = record["final_state"]["base_position"]
    endpoint = math.hypot(final[0]-planned_origin[0], final[1]-planned_origin[1])
    audits.close("final_endpoint_metric", record["ideal_endpoint_error_m"], endpoint, run_id)
    return nodes


def _sequence_budgets(record: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]], audits: _Audits) -> dict[str, Any]:
    """Exact endpoint-vector budget and a measured heading-error recurrence."""
    run_id = _run_id(record)
    actual_initial = record["nodes"][0]["start_state"]["base_position"]
    actual_final = record["final_state"]["base_position"]
    planned_final = record["ideal_endpoint_reference_xy"]
    actual_delta = [float(actual_final[i])-float(actual_initial[i]) for i in range(2)]
    commanded_delta = [float(planned_final[i])-float(actual_initial[i]) for i in range(2)]
    summed_actual = [sum(node["endpoint_vector_budget"]["actual_displacement_xy_m"][i] for node in nodes) for i in range(2)]
    summed_commanded = [sum(node["endpoint_vector_budget"]["commanded_displacement_xy_m"][i] for node in nodes) for i in range(2)]
    summed_error = [sum(node["endpoint_vector_budget"]["error_contribution_xy_m"][i] for node in nodes) for i in range(2)]
    endpoint_vector = [float(actual_final[i])-float(planned_final[i]) for i in range(2)]
    for i in range(2):
        audits.close("actual_displacement_telescoping", summed_actual[i], actual_delta[i], run_id)
        audits.close("planned_displacement_telescoping", summed_commanded[i], commanded_delta[i], run_id)
        audits.close("endpoint_vector_budget_identity", summed_error[i], endpoint_vector[i], run_id)
    contributions = []
    for i, node in enumerate(nodes):
        later_multiplier = math.prod(later["heading_recurrence"]["inherited_error_multiplier"] for later in nodes[i+1:])
        contributions.append({"node_index": node["node_index"], "skill": node["skill"],
                              "residual_deg": node["heading_recurrence"]["control_or_relative_skill_residual_deg"],
                              "later_walk_attenuation": later_multiplier,
                              "final_heading_contribution_deg": node["heading_recurrence"]["control_or_relative_skill_residual_deg"]*later_multiplier})
    initial_error = nodes[0]["heading_recurrence"]["start_ideal_heading_error_deg"]
    initial_multiplier = math.prod(node["heading_recurrence"]["inherited_error_multiplier"] for node in nodes)
    reconstructed = math.degrees(wrap(math.radians(initial_error*initial_multiplier+sum(item["final_heading_contribution_deg"] for item in contributions))))
    audits.close("whole_sequence_heading_budget", wrap(math.radians(reconstructed-nodes[-1]["ideal_heading_error_deg"])), 0, run_id)
    by_skill = {}
    for node in nodes:
        skill = node["skill"]
        by_skill.setdefault(skill, [0.0, 0.0])
        for i in range(2):
            by_skill[skill][i] += node["endpoint_vector_budget"]["error_contribution_xy_m"][i]
    first_walk = next(node for node in nodes if node["skill"] == "walk_forward")
    walk_count = sum(node["skill"] == "walk_forward" for node in nodes)
    return {
        "endpoint": {"actual_total_displacement_xy_m": actual_delta, "commanded_total_displacement_xy_m": commanded_delta,
                     "final_error_vector_xy_m": endpoint_vector, "sum_node_error_contribution_xy_m": summed_error,
                     "error_contributions_by_skill_xy_m": by_skill,
                     "first_walk_world_y_displacement_m": first_walk["endpoint_vector_budget"]["actual_displacement_xy_m"][1]},
        "heading": {"initial_error_deg": initial_error, "initial_error_final_multiplier": initial_multiplier,
                    "node_residual_contributions": contributions, "reconstructed_final_ideal_error_deg": reconstructed,
                    "walk_count": walk_count,
                    "first_walk_inherited_error_deg": first_walk["heading_recurrence"]["start_ideal_heading_error_deg"],
                    "idealized_first_walk_inherited_error_final_multiplier": (1.0-_alpha(record))**walk_count,
                    "idealized_first_walk_inherited_error_final_component_deg": first_walk["heading_recurrence"]["start_ideal_heading_error_deg"]*(1.0-_alpha(record))**walk_count,
                    "idealized_component_scope": "Only inherited first-walk error; excludes measured controller, turn and stationary residuals"},
    }


def _trace_diagnostics(record: Mapping[str, Any], traces: Sequence[Mapping[str, Any]], audits: _Audits) -> dict[str, Any]:
    run_id = _run_id(record)
    walks = 0
    max_geometry_error = 0.0
    for line, row in enumerate(traces, 1):
        locator = f"traces/{run_id}.jsonl#decoded-line={line}"
        audits.flag("residual_off_activation", row["active"] is False, locator)
        for component in row["residual"]:
            audits.close("residual_off", component, 0, locator)
        for component in row["action"]:
            audits.close("residual_off_action", component, 0, locator)
        if row["skill"] != "walk_forward":
            continue
        walks += 1
        ref, state, sample = row["walking_reference"], row["state_before_command"], row["walking_correction_sample"]
        node = record["nodes"][int(row["node_index"])]
        audits.flag("trace_reference_node_consistency", ref == node["walking_reference"], locator)
        local_x, local_y = project(state["base_position"], ref["measurement_origin"], ref["measurement_heading_rad"])
        _, control_y = project(state["base_position"], ref["control_origin"], ref["control_heading_rad"])
        heading_error = wrap(yaw_from_quaternion(state["base_orientation"])-float(ref["control_heading_rad"]))
        delta = wrap(float(ref["control_heading_rad"])-float(ref["measurement_heading_rad"]))
        parts = lateral_decomposition(local_x, control_y, delta)
        max_geometry_error = max(max_geometry_error, abs(local_y-parts["reconstructed_local_lateral_m"]))
        audits.close("trace_rotation_identity", local_y, parts["reconstructed_local_lateral_m"], locator)
        audits.close("trace_sample_lateral", sample["lateral_error_m"], control_y, locator)
        audits.close("trace_sample_heading", wrap(float(sample["heading_error_rad"])-heading_error), 0, locator)
        audits.close("trace_sample_time", sample["sim_time_s"], row["time_s"], locator)
        audits.close("trace_state_time", state["simulation_time"], row["time_s"], locator)
        expected = reconstruct_command(row["nominal_command"], heading_error, control_y)
        for field in ("deterministic_command", "applied_command"):
            for component, (observed, target) in enumerate(zip(row[field], expected["command"])):
                audits.close("frozen_command_reconstruction", observed, target, locator+f"/{field}/{component}")
        audits.close("sample_raw_yaw_reconstruction", sample["yaw_raw"], expected["yaw_raw_radps"], locator)
        audits.close("sample_clipped_yaw_reconstruction", sample["yaw_clipped"], expected["yaw_clipped_radps"], locator)
        audits.flag("sample_saturation_reconstruction", sample["saturated"] == expected["saturated"], locator)
    audits.flag("trace_present", bool(traces) and walks > 0, run_id)
    return {"samples": len(traces), "walk_samples": walks, "maximum_rotation_identity_error_m": max_geometry_error,
            "sampling": "10 Hz command-decision trace; not a complete 500 Hz command history"}


def _pose_diagnostics(record: Mapping[str, Any], poses: Mapping[str, Any], audits: _Audits) -> dict[str, Any]:
    run_id = _run_id(record)
    times, qpos, indices = np.asarray(poses["time_s"]), np.asarray(poses["qpos"]), np.asarray(poses["node_index"])
    audits.flag("pose_time_order", len(times) > 1 and bool(np.all(np.diff(times) > 0)), run_id)
    audits.flag("finite_pose_state", bool(np.isfinite(qpos).all()) and bool(np.isfinite(poses["qvel"]).all())
                and bool(np.isfinite(poses["ctrl"]).all()), run_id)
    peak_local: dict[int, float] = {}
    max_rotation_error = 0.0
    initial_pre_node_captures = 0
    for point, index_value in enumerate(indices):
        index = int(index_value)
        if not 0 <= index < len(record["nodes"]):
            audits.flag("pose_node_index", False, f"{run_id}#pose={point}")
            continue
        node = record["nodes"][index]
        locator = f"poses/{run_id}.npz#frame={point}"
        node_heading = yaw_from_quaternion(node["start_state"]["base_orientation"])
        for axis in range(2):
            audits.close("pose_local_origin", poses["local_origin"][point][axis], node["start_state"]["base_position"][axis], locator)
        audits.close("pose_local_heading", wrap(float(poses["local_heading"][point])-node_heading), 0, locator)
        local_x, local_y = project(qpos[point], node["start_state"]["base_position"], node_heading)
        peak_local[index] = max(peak_local.get(index, 0.0), abs(local_y))
        if node["skill"] == "walk_forward":
            selected = float(node["walking_reference"]["control_heading_rad"])
            captured_reference = float(poses["reference_heading"][point])
            initial_pre_node = point == 0 and index == 0 and math.isnan(captured_reference) and times[point] == node["start_state"]["simulation_time"]
            if initial_pre_node:
                # The frozen offline observer snapshots constructor state before
                # a primitive Walk has assigned its node/selected frame.
                initial_pre_node_captures += 1
            else:
                audits.close("pose_reference_heading", wrap(captured_reference-selected), 0, locator)
            _, control_y = project(qpos[point], node["start_state"]["base_position"], selected)
            parts = lateral_decomposition(local_x, control_y, wrap(selected-node_heading))
            max_rotation_error = max(max_rotation_error, abs(local_y-parts["reconstructed_local_lateral_m"]))
            audits.close("pose_rotation_identity", local_y, parts["reconstructed_local_lateral_m"], locator)
    audits.close("pose_final_time", times[-1], record["final_state"]["simulation_time"], run_id)
    for component in range(3):
        audits.close("pose_final_position", qpos[-1, component], record["final_state"]["base_position"][component], run_id)
    return {"samples": int(len(times)), "frequency_hz": 20,
            "sampled_peak_abs_local_lateral_m_by_node": {str(k): float(v) for k, v in peak_local.items()},
            "peak_metric_role": "Derived sampled diagnostic; does not replace frozen endpoint scoring",
            "initial_pre_node_reference_unavailable_samples": initial_pre_node_captures,
            "maximum_rotation_identity_error_m": max_rotation_error}


def audit_one_run(record: Mapping[str, Any], trace_rows: Sequence[Mapping[str, Any]],
                  poses: Mapping[str, Any]) -> dict[str, Any]:
    """Per-acquisition stop gate; it makes no collection-size/outcome judgment."""
    audits = _Audits()
    nodes = _node_diagnostics(record, audits)
    budgets = _sequence_budgets(record, nodes, audits)
    trace = _trace_diagnostics(record, trace_rows, audits)
    pose = _pose_diagnostics(record, poses, audits)
    return {"passed": audits.passed, "audit_tolerance": AUDIT_TOL,
            "audit_groups": audits.groups, "failures": audits.failures,
            "nodes": nodes, "sequence_budgets": budgets,
            "trace_diagnostics": trace, "pose_diagnostics": pose}


def build_analysis(records: Sequence[Mapping[str, Any]], trace_rows_by_run: Mapping[str, Sequence[Mapping[str, Any]]],
                   pose_arrays_by_run: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Audit/interpret the predeclared 16 runs without altering any result."""
    audits = _Audits()
    expected = {(case, alpha, repetition) for case, alphas in
                ((SEQUENCE_ID, SEQUENCE_ALPHAS), (PRIMITIVE_ID, PRIMITIVE_ALPHAS))
                for alpha in alphas for repetition in (0, 1)}
    observed = [(r["case_id"], _alpha(r), int(r["repetition"])) for r in records]
    audits.flag("predeclared_collection", len(observed) == len(expected) and set(observed) == expected,
                "results.jsonl", {"expected_runs": len(expected), "observed_runs": len(observed),
                                  "missing": [list(item) for item in sorted(expected-set(observed))]})
    index = {(_alpha(r), r["case_id"], int(r["repetition"])): r for r in records}
    runs: list[dict[str, Any]] = []
    for record in records:
        run_id = _run_id(record)
        nodes = _node_diagnostics(record, audits)
        traces, poses = trace_rows_by_run.get(run_id), pose_arrays_by_run.get(run_id)
        audits.flag("run_artifacts_present", traces is not None and poses is not None, run_id)
        trace_summary = _trace_diagnostics(record, traces, audits) if traces is not None else None
        pose_summary = _pose_diagnostics(record, poses, audits) if poses is not None else None
        first_walk = next((n for n in nodes if n["skill"] == "walk_forward"), None)
        source_nodes = record["nodes"]
        budgets = _sequence_budgets(record, nodes, audits)
        standing = [n["transition_metrics"]["standing_fraction"] for n in source_nodes
                    if n["transition_metrics"].get("eligible")]
        last = nodes[-1]
        runs.append({"run_id": run_id, "case_id": record["case_id"], "alpha": _alpha(record),
            "phase": record["phase"], "repetition": int(record["repetition"]),
            "task_success": bool(record["task_success"]), "physical_success": bool(record["physical_success"]),
            "strict_success": all(bool(n["strict_success"]) for n in source_nodes),
            "failure_taxonomy": record["failure_taxonomy"], "total_sim_time_s": float(record["total_sim_time_s"]),
            "final_ideal_lateral_m": last["ideal_lateral_m"], "final_ideal_heading_error_deg": last["ideal_heading_error_deg"],
            "final_endpoint_error_m": float(record["ideal_endpoint_error_m"]), "first_walk": first_walk,
            "physical_diagnostics": {"fallen": any(n["fallen"] for n in source_nodes),
                "max_tilt_deg": max(n["max_tilt_deg"] for n in source_nodes),
                "min_height_m": min(n["min_height_m"] for n in source_nodes),
                "minimum_eligible_transition_standing_fraction": min(standing) if standing else None,
                "frozen_fall_thresholds": {"height_m": 0.45, "tilt_deg": 65.0},
                "within_frozen_fall_diagnostic_bounds": min(n["min_height_m"] for n in source_nodes) >= 0.45
                    and max(n["max_tilt_deg"] for n in source_nodes) <= 65.0},
            "nodes": nodes, "trace_diagnostics": trace_summary, "pose_diagnostics": pose_summary,
            "sequence_budgets": budgets,
            "provenance": record.get("provenance", {})})
    repeat_checks = []
    for alpha, case, repetition in sorted(index):
        if repetition != 1 or (alpha, case, 0) not in index:
            continue
        primary, repeated = index[(alpha, case, 0)], index[(alpha, case, 1)]
        primary_id, repeated_id = _run_id(primary), _run_id(repeated)
        result_equal = _strip_annotations(primary) == _strip_annotations(repeated)
        trace_equal = trace_rows_by_run.get(primary_id) == trace_rows_by_run.get(repeated_id)
        poses_present = primary_id in pose_arrays_by_run and repeated_id in pose_arrays_by_run
        pose_equal = poses_present and _check_array_identity(pose_arrays_by_run[primary_id], pose_arrays_by_run[repeated_id])
        check = {"case_id": case, "alpha": alpha, "result_equal": result_equal,
                 "trace_equal": trace_equal, "poses_equal": pose_equal}
        repeat_checks.append(check)
        audits.flag("exact_repeatability", result_equal and trace_equal and pose_equal, repeated_id, check)
    sequence = sorted((run for run in runs if run["case_id"] == SEQUENCE_ID and run["repetition"] == 0), key=lambda run: run["alpha"])
    primitive = sorted((run for run in runs if run["case_id"] == PRIMITIVE_ID and run["repetition"] == 0), key=lambda run: run["alpha"])
    for alpha in SEQUENCE_ALPHAS:
        if (alpha, SEQUENCE_ID, 0) in index and (0.0, SEQUENCE_ID, 0) in index:
            node = next(n for n in index[(alpha, SEQUENCE_ID, 0)]["nodes"] if n["skill"] == "walk_forward")
            baseline_node = next(n for n in index[(0.0, SEQUENCE_ID, 0)]["nodes"] if n["skill"] == "walk_forward")
            audits.flag("identical_first_walk_start_state", node["start_state"] == baseline_node["start_state"], _run_id(index[(alpha, SEQUENCE_ID, 0)]))
    primitive_checks = []
    for alpha in PRIMITIVE_ALPHAS:
        if (alpha, PRIMITIVE_ID, 0) not in index or (0.0, PRIMITIVE_ID, 0) not in index:
            continue
        base, candidate = index[(0.0, PRIMITIVE_ID, 0)], index[(alpha, PRIMITIVE_ID, 0)]
        base_id, candidate_id = _run_id(base), _run_id(candidate)
        pose_equal = base_id in pose_arrays_by_run and candidate_id in pose_arrays_by_run and _check_array_identity(
            pose_arrays_by_run[base_id], pose_arrays_by_run[candidate_id])
        commands_equal = [row["applied_command"] for row in trace_rows_by_run.get(base_id, [])] == [
            row["applied_command"] for row in trace_rows_by_run.get(candidate_id, [])]
        endpoint_equal = candidate["final_state"] == base["final_state"]
        check = {"alpha": alpha, "poses_equal": pose_equal, "applied_commands_equal": commands_equal,
                 "final_state_equal": endpoint_equal}
        primitive_checks.append(check)
        audits.flag("zero_mismatch_primitive_negative_control", pose_equal and commands_equal and endpoint_equal, candidate_id, check)
    positive = [run for run in sequence if run["alpha"] > 0]
    geometry_dominates = bool(positive) and all(run["first_walk"]["rotation_magnitude_exceeds_tracking_remainder"] for run in positive)
    physical_preserved = bool(sequence) and all(run["physical_success"] and not run["physical_diagnostics"]["fallen"] for run in sequence)
    local_abs = [abs(run["first_walk"]["local_lateral_m"]) for run in sequence]
    monotonic_local = len(local_abs) == len(SEQUENCE_ALPHAS) and all(a <= b for a, b in zip(local_abs, local_abs[1:]))
    anchor0 = next((run for run in sequence if run["alpha"] == 0), None)
    anchor05 = next((run for run in sequence if run["alpha"] == 0.5), None)
    midpoint_gain = bool(anchor0 and anchor05) and abs(anchor05["final_ideal_lateral_m"]) < abs(anchor0["final_ideal_lateral_m"]) and abs(
        anchor05["final_ideal_heading_error_deg"]) < abs(anchor0["final_ideal_heading_error_deg"])
    if not audits.passed:
        verdict = "ROOTCAUSE_AUDIT_BLOCKED"
    elif geometry_dominates and physical_preserved and monotonic_local and midpoint_gain:
        verdict = "SUPPORTED_GEOMETRIC_LOCAL_CONTRACT_CONFLICT"
    else:
        verdict = "MECHANISM_NOT_FULLY_SUPPORTED"
    gains = None
    if anchor0 and anchor05:
        gains = {"absolute_global_lateral_reduction_m": abs(anchor0["final_ideal_lateral_m"])-abs(anchor05["final_ideal_lateral_m"]),
                 "absolute_global_heading_reduction_deg": abs(anchor0["final_ideal_heading_error_deg"])-abs(anchor05["final_ideal_heading_error_deg"]),
                 "endpoint_error_reduction_m": anchor0["final_endpoint_error_m"]-anchor05["final_endpoint_error_m"],
                 "first_walk_world_y_displacement_delta_m": anchor05["sequence_budgets"]["endpoint"]["first_walk_world_y_displacement_m"]-
                    anchor0["sequence_budgets"]["endpoint"]["first_walk_world_y_displacement_m"],
                 "world_endpoint_error_vector_delta_xy_m": [anchor05["sequence_budgets"]["endpoint"]["final_error_vector_xy_m"][i]-
                    anchor0["sequence_budgets"]["endpoint"]["final_error_vector_xy_m"][i] for i in range(2)]}
    return {"experiment_id": "correction_tradeoff_isolation_001", "verdict": verdict,
            "all_audits_passed": audits.passed, "audit_tolerance": AUDIT_TOL,
            "audit_groups": audits.groups, "audit_failures_first_100": audits.failures,
            "primary_runs": sum(r["repetition"] == 0 for r in runs), "repeatability_runs": sum(r["repetition"] == 1 for r in runs),
            "per_arm": sequence, "primitive_negative_controls": primitive,
            "repeatability": {"checks": repeat_checks, "scope": "Exact deterministic replays; not independent seeds or scientific sample-size expansion"},
            "primitive_identity_checks": primitive_checks, "alpha05_minus_alpha0_improvement": gains,
            "mechanism_diagnostics": {"rotation_component_exceeds_tracking_remainder_all_positive_alpha": geometry_dominates,
                "monotonic_first_walk_absolute_local_drift": monotonic_local,
                "physical_outcomes_preserved": physical_preserved, "midpoint_global_lateral_and_heading_gain_reproduced": midpoint_gain,
                "dominance_role": "Geometric hypothesis interpretation only; no task/scoring threshold is introduced",
                "coordinate_identity_role": "Algebraic audit, not independent causal proof; actual tracking remainder is reported separately",
                "local_stability_interpretation": "Local corridor departure is distinct from physical instability",
                "no_best_alpha_selection": True},
            "limits": ["Frozen deterministic 16m mechanism case; no population or disturbance generalization claim",
                       "Sampled pose peaks are 20Hz derived diagnostics, not original endpoint scoring",
                       "Command reconstruction covers retained 10Hz traces, not all 500Hz controller calls",
                       "Historical anchors and frozen source/file hashes require the campaign's separate integrity certificate"],
            "next_gate": "STOP; Phase3A.5 training remains paused"}


def render_figures(analysis: Mapping[str, Any], pose_arrays_by_run: Mapping[str, Mapping[str, Any]], output_dir) -> list[str]:
    """Standalone scientific figures; no Console/UI modification."""
    from pathlib import Path
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    arms = analysis["per_arm"]
    if not arms:
        return []
    alpha = [run["alpha"] for run in arms]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.4), layout="constrained")
    axes[0].plot(alpha, [run["first_walk"]["local_lateral_m"] for run in arms], "o-", label="Frozen local endpoint")
    axes[0].plot(alpha, [run["first_walk"]["rotation_component_m"] for run in arms], "s--", label="Frame-rotation component")
    axes[0].plot(alpha, [run["first_walk"]["selected_tracking_component_m"] for run in arms], ".:", label="Selected-axis tracking remainder")
    axes[0].axhline(arms[0]["first_walk"]["strict_lateral_limit_m"], color="#b45309", linestyle="--", label="Frozen strict limit")
    axes[0].axhline(arms[0]["first_walk"]["nominal_lateral_limit_m"], color="#64748b", linestyle=":", label="Frozen nominal limit")
    axes[0].set(title="First Walk8m: local-corridor conflict", xlabel="Heading alignment alpha", ylabel="Signed lateral displacement (m)")
    axes[0].legend(fontsize=7)
    axes[1].plot(alpha, [abs(run["final_ideal_lateral_m"]) for run in arms], "o-", label="Absolute global lateral")
    axes[1].plot(alpha, [run["final_endpoint_error_m"] for run in arms], "s--", label="Endpoint error")
    axes[1].set(title="16m final global precision", xlabel="Heading alignment alpha", ylabel="Error (m)")
    heading_axis = axes[1].twinx()
    heading_axis.plot(alpha, [abs(run["final_ideal_heading_error_deg"]) for run in arms], ".:", color="#64748b", label="Absolute ideal heading")
    heading_axis.set_ylabel("Heading error (degrees)")
    axes[1].legend(fontsize=8, loc="upper right")
    colors = plt.colormaps["viridis"](np.linspace(0, 1, len(arms)))
    for run, color in zip(arms, colors):
        poses = pose_arrays_by_run.get(run["run_id"])
        if poses is not None:
            qpos = np.asarray(poses["qpos"])
            axes[2].plot(qpos[:, 0], qpos[:, 1], color=color, label=f"alpha={run['alpha']:g}")
    axes[2].plot([0, 8, 8, 12], [0, 0, -4, -4], "k--", linewidth=1, label="Frozen commanded route")
    axes[2].set(title="Real acquired trajectories (20Hz)", xlabel="World X (m)", ylabel="World Y (m)")
    axes[2].set_aspect("equal", adjustable="datalim")
    axes[2].legend(fontsize=8)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(alpha=.2)
    fig.suptitle("Phase3A.4b · Fixed 16m case · residual OFF · no alpha optimization", fontsize=12)
    path = output/"correction_tradeoff.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return [str(path)]
