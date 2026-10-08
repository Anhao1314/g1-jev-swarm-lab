"""Independent offline arithmetic/authority audit for the frozen 3A.4d gate.

This module does not import the controller, evaluator, simulator or training
code. Original result rows remain authoritative and are never rewritten.
Full-step digests certify retained execution identity, not trajectory coverage.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


PAIRS = {("walk_forward", "turn"), ("turn", "walk_forward"),
         ("walk_forward", "stop"), ("stand", "walk_forward")}
BAD_PHYSICAL_STATUS = {"UNSAFE", "NON_FINITE_STATE", "INVALID_CONTROL", "INTERRUPTED"}
META = {"run_id", "probe_id", "repetition", "phase", "provenance", "wall_time_s",
        "elapsed_wall_time_s"}


def _wrap(value):
    return math.atan2(math.sin(value), math.cos(value))


def _yaw(state, *, normalize=True):
    w, x, y, z = map(float, state["base_orientation"])
    if normalize:
        norm = math.sqrt(w*w+x*x+y*y+z*z)
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError("Invalid orientation quaternion")
        w, x, y, z = w/norm, x/norm, y/norm, z/norm
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def _project(state, origin, heading):
    dx = float(state["base_position"][0])-float(origin[0])
    dy = float(state["base_position"][1])-float(origin[1])
    return math.cos(heading)*dx+math.sin(heading)*dy, -math.sin(heading)*dx+math.cos(heading)*dy


def _finite_state(state):
    names = ("base_position", "base_orientation", "linear_velocity", "angular_velocity")
    values = [state["simulation_time"]]
    for name in names:
        values.extend(state[name])
    for name in ("joint_positions", "joint_velocities"):
        if state.get(name) is not None:
            values.extend(state[name])
    return all(math.isfinite(float(value)) for value in values)


def _case():
    return json.loads(Path(__file__).with_name("case.json").read_text(encoding="utf-8"))


def _projection(value):
    if isinstance(value, dict):
        return {key: _projection(item) for key, item in value.items() if key not in META}
    if isinstance(value, list):
        return [_projection(item) for item in value]
    return value


def _world(record, case):
    """Frozen commanded-world targets; no actual endpoint reanchoring."""
    initial = record["nodes"][0]["start_state"]
    target = list(map(float, initial["base_position"][:2]))
    heading = _yaw(initial, normalize=False)  # original planned-heading recipe
    nodes = []
    for index, spec in enumerate(case["nodes"]):
        skill, params = spec["skill"], spec["parameters"]
        if skill == "walk_forward":
            distance = params["target_distance_m"]
            target[0] += distance*math.cos(heading)
            target[1] += distance*math.sin(heading)
        elif skill == "turn":
            heading = _wrap(heading+math.radians(params["target_angle_deg"]))
        if index < len(record["nodes"]):
            node = record["nodes"][index]
            end = node["end_state"]
            error = [float(end["base_position"][i])-target[i] for i in (0, 1)]
            translation = [float(end["base_position"][i])-float(node["start_state"]["base_position"][i])
                           for i in (0, 1)]
            nodes.append({"node_index": index, "skill": skill,
                          "commanded_terminal_xy_m": target.copy(),
                          "commanded_terminal_heading_deg": math.degrees(heading),
                          "world_error_xy_m": error, "world_error_norm_m": math.hypot(*error),
                          "commanded_along_error_m": math.cos(heading)*error[0]+math.sin(heading)*error[1],
                          "commanded_lateral_error_m": -math.sin(heading)*error[0]+math.cos(heading)*error[1],
                          "world_heading_error_deg": math.degrees(_wrap(_yaw(end, normalize=False)-heading)),
                          "translation_xy_m": translation,
                          "translation_norm_m": math.hypot(*translation),
                          "local_lateral_m": node["lateral_drift_m"],
                          "local_heading_deg": node["heading_error_deg"],
                          "nominal_success": node["task_success"],
                          "strict_success": node["strict_success"],
                          "physical_success": node["physical_success"], "status": node["status"]})
    final = record["final_state"]
    error = [float(final["base_position"][i])-target[i] for i in (0, 1)]
    return {"nodes": nodes, "final_commanded_xy_m": target,
            "final_commanded_heading_deg": math.degrees(heading),
            "final_world_error_xy_m": error, "final_endpoint_error_m": math.hypot(*error),
            "final_global_lateral_m": -math.sin(heading)*error[0]+math.cos(heading)*error[1],
            "final_global_heading_deg": math.degrees(_wrap(_yaw(final, normalize=False)-heading))}


class _Checks:
    def __init__(self, tolerance):
        self.tolerance = float(tolerance)
        self.numeric = self.predicates = 0
        self.max_error = 0.0
        self.failures = []

    def check(self, passed, locator):
        self.predicates += 1
        if not passed:
            self.failures.append({"locator": locator, "kind": "predicate"})

    def near(self, observed, expected, locator):
        actual, target = np.asarray(observed, dtype=float), np.asarray(expected, dtype=float)
        self.numeric += int(actual.size)
        finite = actual.shape == target.shape and np.isfinite(actual).all() and np.isfinite(target).all()
        error = float(np.max(np.abs(actual-target))) if finite and actual.size else (0.0 if finite else math.inf)
        if math.isfinite(error):
            self.max_error = max(self.max_error, error)
        if not finite or error > self.tolerance:
            self.failures.append({"locator": locator, "kind": "numeric",
                                  "max_abs_error": error if math.isfinite(error) else None})

    def result(self):
        return {"passed": not self.failures, "numeric_checks": self.numeric,
                "predicate_checks": self.predicates, "maximum_roundoff": self.max_error,
                "tolerance": self.tolerance, "failures": self.failures}


def _probe_action(record, row, protocol):
    if row["node_index"] != 1 or row["skill"] != "walk_forward" or not row["active"]:
        return [0.0]*3
    probe = next((value for value in protocol["probes_in_order"] if value["id"] == record["probe_id"]), None)
    if probe is None:
        return [0.0]*3  # zero actor; residual-off has no callback ledger
    elapsed = float(row["elapsed_s"])
    if elapsed < float(probe["onset_s"])-1e-9 or elapsed >= float(probe["end_s"])-1e-9:
        return [0.0]*3
    if "switch_s" in probe:
        return probe["action_first"] if elapsed < float(probe["switch_s"])-1e-9 else probe["action_second"]
    return probe["action"]


def _profile(node, name):
    """Duplicate frozen envelope arithmetic independently; never rescore rows."""
    distance = float(node["parameters"]["target_distance_m"])
    if name == "nominal":
        limits = {"distance_error_max_m": max(.30, .10*distance),
                  "lateral_drift_max_m": max(.35, .07*distance),
                  "heading_error_max_deg": 15.0, "timeout_max_s": max(15.0, 6.0*distance)}
    else:
        limits = {"distance_error_max_m": max(.15, .05*distance),
                  "lateral_drift_max_m": max(.20, .035*distance),
                  "heading_error_max_deg": 8.0, "timeout_max_s": max(12.0, 5.0*distance)}
    measured = {"distance_error_m": abs(float(node["forward_progress_m"])-distance),
                "lateral_drift_m": abs(float(node["lateral_drift_m"])),
                "heading_error_deg": abs(float(node["heading_error_deg"])),
                "completion_sim_time_s": float(node["duration_s"])}
    pairs = (("distance_error_m", "distance_error_max_m", "DISTANCE_ERROR"),
             ("lateral_drift_m", "lateral_drift_max_m", "EXCESSIVE_DRIFT"),
             ("heading_error_deg", "heading_error_max_deg", "HEADING_ERROR"),
             ("completion_sim_time_s", "timeout_max_s", "TIMEOUT"))
    violations = [label for metric, limit, label in pairs if measured[metric] > limits[limit]]
    return limits, measured, violations


def audit_run(record, trace_rows, decision_rows, audit_receipt, protocol):
    """Check one retained run without mutating it or executing physics."""
    check = _Checks(protocol["roundoff_audit_tolerance"])
    case = _case()
    authority = protocol["authority"]
    check.check(record["case_id"] == case["id"], "case_id")
    check.check(hashlib.sha256(Path(__file__).with_name("case.json").read_bytes()).hexdigest()
                == protocol["case_sha256"], "frozen_case_hash")
    check.check(record.get("PPO_training") is False, "no_training")
    check.check(record["heading_alignment_alpha"] == protocol["reference_alpha"], "fixed_alpha")
    check.check(len(record["nodes"]) <= len(case["nodes"]), "no_extra_node")
    plans, local_frames, selected_frames = {}, {}, {}
    initial = record["nodes"][0]["start_state"]
    planned_xy = list(map(float, initial["base_position"][:2]))
    planned_heading = _yaw(initial, normalize=False)
    endpoints = []
    for index, node in enumerate(record["nodes"]):
        prefix = f"nodes/{index}"
        spec = case["nodes"][index]
        check.check(node["skill"] == spec["skill"] and node["parameters"] == spec["parameters"], prefix+"/frozen_spec")
        start, end = node["start_state"], node["end_state"]
        check.check(_finite_state(start) and _finite_state(end), prefix+"/finite_endpoint_states")
        if index:
            check.check(start == record["nodes"][index-1]["end_state"], prefix+"/original_node_latch")
        heading, origin = _yaw(start), start["base_position"]
        local_frames[index] = (origin, heading)
        selected_heading = _wrap(heading+protocol["reference_alpha"]*_wrap(planned_heading-heading))
        selected_frames[index] = (origin, selected_heading)
        plans[index] = (planned_xy.copy(), planned_heading)
        forward, lateral = _project(end, origin, heading)
        check.near(node["forward_progress_m"], forward, prefix+"/local_forward")
        check.near(node["lateral_drift_m"], lateral, prefix+"/fixed_local_lateral")
        if node["skill"] != "turn":
            check.near(node["heading_error_deg"], math.degrees(_wrap(_yaw(end)-heading)), prefix+"/fixed_local_heading")
        else:
            check.near(node["heading_error_deg"], node["skill_metrics"]["heading_error_deg"], prefix+"/original_turn_heading")
        check.near(node["duration_s"], end["simulation_time"]-start["simulation_time"], prefix+"/duration")
        physical = not (end["fallen"] or node["skill_metrics"].get("fallen", False)) and _finite_state(end) and node["status"] not in BAD_PHYSICAL_STATUS
        check.check(node["physical_success"] == physical, prefix+"/physical_predicate")
        check.check(node["fallen"] == bool(end["fallen"] or node["skill_metrics"].get("fallen", False)), prefix+"/fallen")
        nominal, strict = physical and node["status"] == "SUCCESS", physical and node["status"] == "SUCCESS"
        if node["skill"] == "walk_forward":
            ref = node["walking_reference"]
            check.near(ref["measurement_origin"], origin, prefix+"/measurement_origin")
            check.near(ref["measurement_heading_rad"], heading, prefix+"/measurement_heading")
            check.near(ref["control_origin"], origin, prefix+"/actual_control_origin")
            check.near(ref["control_heading_rad"], selected_heading, prefix+"/unchanged_selector")
            check.near(ref["planned_origin"], planned_xy, prefix+"/planned_origin")
            check.near(ref["planned_heading_rad"], planned_heading, prefix+"/planned_heading")
            ref_forward, ref_lateral = _project(end, origin, selected_heading)
            diagnostics = node["control_frame_diagnostics"]
            check.near(diagnostics["forward_m"], ref_forward, prefix+"/reference_forward")
            check.near(diagnostics["lateral_m"], ref_lateral, prefix+"/reference_lateral")
            check.near(diagnostics["heading_error_deg"], math.degrees(_wrap(_yaw(end)-selected_heading)), prefix+"/reference_heading")
            outcomes = {}
            for name in ("nominal", "strict"):
                limits, measured, violations = _profile(node, name)
                source = node["envelope"][name+"_envelope"]
                for key, value in limits.items():
                    check.near(source["limits"][key], value, prefix+"/"+name+"_limit/"+key)
                for key, value in measured.items():
                    check.near(source[key], value, prefix+"/"+name+"_metric/"+key)
                check.check(source["violations"] == violations, prefix+"/"+name+"_violations")
                check.check(source["satisfied"] == (not violations), prefix+"/"+name+"_satisfied")
                outcomes[name] = not violations
            nominal = nominal and outcomes["nominal"]
            strict = strict and outcomes["strict"]
            endpoints.append({"node_index": index, "local_forward_m": forward,
                              "local_lateral_m": lateral, "reference_lateral_m": ref_lateral,
                              "axis_rotation_deg": math.degrees(_wrap(selected_heading-heading)),
                              "local_heading_error_deg": node["heading_error_deg"],
                              "reference_heading_error_deg": diagnostics["heading_error_deg"],
                              "nominal_success": node["task_success"], "strict_success": node["strict_success"]})
            distance = node["parameters"]["target_distance_m"]
            planned_xy = [planned_xy[0]+distance*math.cos(planned_heading),
                          planned_xy[1]+distance*math.sin(planned_heading)]
        elif node["skill"] == "turn":
            planned_heading = _wrap(planned_heading+math.radians(node["parameters"]["target_angle_deg"]))
        check.check(node["task_success"] == nominal, prefix+"/original_nominal_score")
        check.check(node["strict_success"] == strict, prefix+"/original_strict_score")
    complete = len(record["nodes"]) == len(case["nodes"])
    check.check(record["physical_success"] == (complete and all(n["physical_success"] for n in record["nodes"])), "sequence_physical")
    check.check(record["task_success"] == (complete and all(n["task_success"] for n in record["nodes"])), "sequence_nominal")
    check.check(record["final_state"] == record["nodes"][-1]["end_state"], "final_state")
    check.near(record["total_sim_time_s"], record["final_state"]["simulation_time"], "total_time")
    check.check(record["trace_samples"] == len(trace_rows), "trace_count")
    eligible_traces = []
    active_count = scope_count = 0
    integrals = np.zeros(3)
    latest_ticks = {}
    for position, row in enumerate(trace_rows):
        index = int(row["node_index"])
        prefix = f"trace/{position}"
        node = record["nodes"][index]
        previous = record["nodes"][index-1]["skill"] if index else None
        eligible = index > 0 and (previous, node["skill"]) in PAIRS
        active = record["treatment"] == "learned" and eligible and float(row["elapsed_s"]) < authority["window_s"]-1e-9
        check.check(row["skill"] == node["skill"] and row["previous_skill"] == previous, prefix+"/skill_identity")
        check.check(row["eligible"] == eligible and row["active"] == active, prefix+"/original_mask")
        tick = latest_ticks.get(index, -1)+1
        latest_ticks[index] = tick
        check.near(row["elapsed_s"], tick*authority["decision_period_s"], prefix+"/cadence")
        state = row["state_before_command"]
        check.near(row["time_s"], state["simulation_time"], prefix+"/state_time")
        check.near(row["elapsed_s"], row["time_s"]-node["start_state"]["simulation_time"], prefix+"/node_elapsed")
        check.check(_finite_state(state), prefix+"/finite_state")
        nominal = np.asarray(row["nominal_command"], float)
        corrected = nominal.copy()
        if node["skill"] == "walk_forward":
            origin, selected_heading = selected_frames[index]
            heading_error = _wrap(_yaw(state)-selected_heading)
            _, lateral_error = _project(state, origin, selected_heading)
            raw = -1.5*heading_error-lateral_error
            deadband_raw = 0.0 if abs(raw) < .01 else raw
            corrected[2] = float(np.clip(deadband_raw, -.6, .6))
            sample = row["walking_correction_sample"]
            check.near(sample["heading_error_rad"], heading_error, prefix+"/feedback_heading")
            check.near(sample["lateral_error_m"], lateral_error, prefix+"/feedback_lateral")
            check.near(sample["yaw_raw"], deadband_raw, prefix+"/feedback_deadband")
            check.near(nominal, [.5, 0.0, 0.0], prefix+"/frozen_walk_command")
            ref = row["walking_reference"]
            check.near(ref["control_origin"], origin, prefix+"/fixed_origin")
            check.near(ref["control_heading_rad"], selected_heading, prefix+"/fixed_reference")
            check.near(ref["measurement_origin"], local_frames[index][0], prefix+"/fixed_measurement_origin")
            check.near(ref["measurement_heading_rad"], local_frames[index][1], prefix+"/fixed_measurement_heading")
        check.near(row["deterministic_command"], corrected, prefix+"/deterministic_command")
        action = np.asarray(row["action"], float)
        check.check(action.shape == (3,) and np.isfinite(action).all() and np.all(np.abs(action) <= 1), prefix+"/action_box")
        expected_action = np.asarray(_probe_action(record, row, protocol), float) if active else np.zeros(3)
        check.near(action, expected_action, prefix+"/predeclared_profile")
        expected_command = corrected+action*np.asarray(authority["physical_bounds"])
        expected_command[2] = float(np.clip(expected_command[2], -authority["total_yaw_limit_radps"], authority["total_yaw_limit_radps"]))
        check.near(row["applied_command"], expected_command, prefix+"/bounded_command")
        check.near(row["residual"], expected_command-corrected, prefix+"/applied_residual")
        if active:
            active_count += 1
            if index == 1:
                scope_count += 1
                integrals += np.asarray(row["residual"])*authority["decision_period_s"]
        if eligible:
            eligible_traces.append((tick, row))
    configured = bool(record.get("learned_policy_configured"))
    check.check(len(decision_rows) == (len(eligible_traces) if configured else 0), "callback_count")
    check.check(record.get("policy_decision_calls") == len(decision_rows), "record_callback_count")
    for position, (decision, (tick, row)) in enumerate(zip(decision_rows, eligible_traces)):
        prefix = f"decision/{position}"
        for key in ("node_index", "skill", "active"):
            check.check(decision[key] == row[key], prefix+"/"+key)
        check.check(decision["decision_tick"] == tick, prefix+"/tick")
        for key in ("time_s", "elapsed_s"):
            check.near(decision[key], row[key], prefix+"/"+key)
        check.near(decision["proposed_action"], _probe_action(record, row, protocol), prefix+"/proposed_profile")
        check.check(math.isfinite(float(decision["reward"])), prefix+"/finite_original_reward")
        digest = decision["observation_sha256"]
        check.check(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), prefix+"/observation_digest")
    check.check(audit_receipt["reward_calls"] == len(decision_rows), "original_reward_calls")
    check.check(audit_receipt["optimizer_updates"] == 0 and audit_receipt["checkpoint_writes"] == 0, "zero_optimizer_checkpoint")
    steps = sum(node["simulation_steps"] for node in record["nodes"])
    check.check(audit_receipt["physics_steps"] == steps, "full_physics_steps")
    check.near(steps*authority["physics_timestep_s"], record["total_sim_time_s"]-initial["simulation_time"], "frozen_timestep")
    check.check(audit_receipt["full_step_authority_checks"] == steps, "full_step_authority_coverage")
    violations = audit_receipt["full_step_authority_violations"]
    check.check(violations == 0 or violations == [], "full_step_authority_no_violation")
    for name in ("physics_state_sha256", "initial_tensors_sha256", "final_tensors_sha256"):
        value = audit_receipt[name]
        check.check(isinstance(value, str) and len(value) == 64, "receipt/"+name)
    for name in ("commands", "torques", "base_observations", "base_actions", "residual_observations", "rewards"):
        stream = audit_receipt["streams"][name]
        check.check(isinstance(stream["sha256"], str) and len(stream["sha256"]) == 64, "stream/"+name+"/digest")
        expected_count = steps if name in ("commands", "torques") else (len(eligible_traces) if name == "residual_observations" else (len(decision_rows) if name == "rewards" else None))
        if expected_count is not None:
            check.check(stream["count"] == expected_count, "stream/"+name+"/count")
        else:
            check.check(isinstance(stream["count"], int) and 0 < stream["count"] <= steps, "stream/"+name+"/count")
    first_walk_traces = [row for row in trace_rows if row["node_index"] == 1]
    window_state = None
    if first_walk_traces:
        row = min(first_walk_traces, key=lambda item: abs(item["elapsed_s"]-authority["window_s"]))
        state = row["state_before_command"]
        local_origin, local_heading = local_frames[1]
        ref_origin, ref_heading = selected_frames[1]
        forward, lateral = _project(state, local_origin, local_heading)
        ref_forward, ref_lateral = _project(state, ref_origin, ref_heading)
        window_state = {"elapsed_s": row["elapsed_s"], "time_s": row["time_s"],
                        "source": "nearest retained pre-command trace state to original 2s boundary",
                        "sampling_offset_s": row["elapsed_s"]-authority["window_s"],
                        "local_forward_m": forward, "local_lateral_m": lateral,
                        "reference_forward_m": ref_forward, "reference_lateral_m": ref_lateral,
                        "world_heading_deg": math.degrees(_yaw(state, normalize=False)),
                        "local_heading_error_deg": math.degrees(_wrap(_yaw(state)-local_heading)),
                        "reference_heading_error_deg": math.degrees(_wrap(_yaw(state)-ref_heading)),
                        "world_position_xyz_m": state["base_position"],
                        "speed_mps": math.hypot(*state["linear_velocity"][:2])}
    return {**check.result(), "run_id": record["run_id"],
            "authority_summary": {"callback_count": len(decision_rows), "active_trace_decisions": active_count,
                                  "first_walk_active_trace_decisions": scope_count,
                                  "first_walk_residual_command_integral": integrals.tolist(),
                                  "integral_role": "command exposure, not position/reachability bound",
                                  "full_step_checks": audit_receipt["full_step_authority_checks"]},
            "walk_endpoints": endpoints, "first_walk_window_state": window_state,
            "world_metrics": _world(record, case),
            "coverage": "10Hz retained trace arithmetic plus separately recorded full-step authority checks; no continuous corridor certification"}


def summarize(records, baseline, protocol):
    """Frozen joint gate; failed finite probes never certify full-space exclusion."""
    case, tolerance = _case(), float(protocol["roundoff_audit_tolerance"])
    baseline_world = _world(baseline, case)
    runs, eligible = [], []
    for record in records:
        world = _world(record, case)
        complete = len(record["nodes"]) == len(case["nodes"])
        physical = complete and bool(record["physical_success"])
        statuses = complete and all(node["status"] == "SUCCESS" for node in record["nodes"])
        strict = complete and all(node["strict_success"] for node in record["nodes"])
        nominal = complete and bool(record["task_success"])
        norm_delta = world["final_endpoint_error_m"]-baseline_world["final_endpoint_error_m"]
        lateral_delta = abs(world["final_global_lateral_m"])-abs(baseline_world["final_global_lateral_m"])
        heading_delta = abs(world["final_global_heading_deg"])-abs(baseline_world["final_global_heading_deg"])
        gain = norm_delta < -tolerance and lateral_delta <= tolerance and heading_delta <= tolerance
        joint = strict and physical and statuses and gain
        item = {"run_id": record["run_id"], "probe_id": record["probe_id"], "repetition": record["repetition"],
                "complete": complete, "physical_success": physical, "all_node_SUCCESS": statuses,
                "nominal_success": nominal, "all_node_strict_success": strict,
                "paired_global_condition": gain, "joint_qualifier": joint,
                "same_reference_baseline_run_id": baseline["run_id"],
                "delta_endpoint_error_m": norm_delta, "delta_absolute_global_lateral_m": lateral_delta,
                "delta_absolute_global_heading_deg": heading_delta,
                "delta_final_world_xy_m": [a-b for a, b in zip(world["final_world_error_xy_m"], baseline_world["final_world_error_xy_m"])],
                "first_walk_local_lateral_m": record["nodes"][1]["lateral_drift_m"] if len(record["nodes"]) > 1 else None,
                "first_walk_reference_lateral_m": record["nodes"][1].get("control_frame_diagnostics", {}).get("lateral_m") if len(record["nodes"]) > 1 else None,
                "max_tilt_deg": max(node["max_tilt_deg"] for node in record["nodes"]),
                "min_height_m": min(node["min_height_m"] for node in record["nodes"]),
                "falls": sum(bool(node["fallen"]) for node in record["nodes"]),
                "failure_taxonomy": record["failure_taxonomy"], "world_metrics": world}
        runs.append(item)
        if joint:
            eligible.append(record)
    repeated = []
    for primary in eligible:
        if primary["repetition"] != 0:
            continue
        for confirmation in eligible:
            if confirmation["probe_id"] == primary["probe_id"] and confirmation["repetition"] != 0:
                identical = _projection(primary) == _projection(confirmation)
                repeated.append({"probe_id": primary["probe_id"], "primary_run_id": primary["run_id"],
                                 "confirmation_run_id": confirmation["run_id"], "exact_scientific_record": identical})
    feasible = any(item["exact_scientific_record"] for item in repeated)
    return {"verdict": "FEASIBLE" if feasible else "INCONCLUSIVE",
            "baseline_world_metrics": baseline_world, "runs": runs, "repeated_joint_witnesses": repeated,
            "full_space_infeasibility_certificate": False,
            "verdict_reason": "Repeated constructive joint witness inside the unchanged authority" if feasible else
                              "No repeated joint witness; finite deterministic probes do not exclude all admissible continuous actions",
            "scope": "Frozen alpha0.5/sequence-mixed-16m strict endpoint claim; deterministic reproducibility, not independent-seed generalization",
            "delta_convention": "probe minus its own alpha0.5 residual-off baseline",
            "roundoff_role": "verification resolution only; original scores and limits copied unchanged",
            "training_gate": "Phase3A.5 remains paused; no training authorized by this result"}
