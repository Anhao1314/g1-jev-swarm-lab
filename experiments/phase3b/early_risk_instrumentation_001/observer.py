"""Study-only, read-only instrumentation for the frozen Phase 3B.1b replay.

The hooks attach to an EpisodeRunner instance. They neither replace its
controller nor modify the simulation, policy observation, or command values.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from g1swarm.transition_learning.env import EpisodeRunner, wrap, yaw

CHECKPOINTS = (0.0, 1.0, 2.0)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def snapshot(runner, command_row):
    """Read only the pre-command simulator state at an existing trace tick."""
    state = runner.sim.get_robot_state()
    heading = yaw(state)
    local_forward, local_lateral = runner.frame.project(state.base_position)
    local_heading = runner.frame.heading_error_deg(state)
    offset = np.asarray(state.base_position[:2]) - runner.planned_origin
    axis = (math.cos(runner.planned_heading), math.sin(runner.planned_heading))
    route_forward = float(axis[0] * offset[0] + axis[1] * offset[1])
    route_lateral = float(-axis[1] * offset[0] + axis[0] * offset[1])
    vx, vy = state.linear_velocity[:2]
    command = command_row["applied_command"]
    nominal = command_row["nominal_command"]
    return {
        "node_index": runner.index,
        "elapsed_s": float(command_row["elapsed_s"]),
        "simulation_time_s": float(state.simulation_time),
        "world_xy_m": [float(x) for x in state.base_position[:2]],
        "world_heading_deg": math.degrees(heading),
        "route_frame_xy_m": [route_forward, route_lateral],
        "route_heading_error_deg": math.degrees(wrap(heading - runner.planned_heading)),
        "route_frame_vx_vy_mps": [float(axis[0] * vx + axis[1] * vy), float(-axis[1] * vx + axis[0] * vy)],
        "yaw_rate_radps": float(state.angular_velocity[2]),
        "local_forward_m": float(local_forward),
        "local_lateral_m": float(local_lateral),
        "local_heading_error_deg": float(local_heading),
        "reference_lateral_m": route_lateral,
        "reference_heading_error_deg": math.degrees(wrap(heading - runner.planned_heading)),
        "nominal_command": [float(x) for x in nominal],
        "applied_command": [float(x) for x in command],
        "actual_correction_delta": [float(a - b) for a, b in zip(command, nominal, strict=True)],
    }


class Observer:
    def __init__(self, runner: EpisodeRunner, selected_nodes: set[int], *, enabled: bool):
        self.runner = runner
        self.selected_nodes = set(selected_nodes)
        self.enabled = enabled
        self.snapshots = {}
        self.trace_rows = []
        self.command_sha256 = hashlib.sha256()
        self.command_count = 0
        self._attach()

    def _attach(self):
        original_trace = self.runner.trace
        original_torques = self.runner.base.compute_torques

        def trace(row):
            # The historical trace is emitted before each selected controller
            # tick's torque computation. Calling it first preserves its order.
            original_trace(row)
            self.trace_rows.append(row.copy())
            if not self.enabled or row["node_index"] not in self.selected_nodes:
                return
            if row["skill"] != "walk_forward":
                raise AssertionError("Predeclared observed node is not a walk")
            elapsed = float(row["elapsed_s"])
            for checkpoint in CHECKPOINTS:
                key = f"{row['node_index']}:{checkpoint:g}"
                if abs(elapsed - checkpoint) <= 1e-8 and key not in self.snapshots:
                    self.snapshots[key] = snapshot(self.runner, row)

        def compute_torques(**kwargs):
            # In BOTH arms, hash every actual command handed to the frozen
            # controller, without changing its ndarray or its keyword args.
            self.command_sha256.update(_canonical(np.asarray(kwargs["command"]).tolist()))
            self.command_sha256.update(b"\n")
            self.command_count += 1
            return original_torques(**kwargs)

        self.runner.trace = trace
        self.runner.base.compute_torques = compute_torques

    def evidence(self):
        return {
            "observer_enabled": self.enabled,
            "command_sha256": self.command_sha256.hexdigest(),
            "command_count": self.command_count,
            "trace_rows": self.trace_rows,
            "snapshots": self.snapshots,
        }


def replay_observed(case, selected_nodes: set[int], *, enabled: bool):
    runner = EpisodeRunner(case, "frozen_baseline")
    observer = Observer(runner, selected_nodes, enabled=enabled)
    try:
        record = runner.run()
        return {"record": record, "observer": observer.evidence()}
    finally:
        runner.close()


def comparable_record(record):
    """Exclude only host wall-clock timings, retaining every physics field."""
    comparable = json.loads(json.dumps(record, allow_nan=False))
    comparable.pop("wall_time_s", None)
    for node in comparable["nodes"]:
        node.get("skill_metrics", {}).pop("elapsed_wall_time_s", None)
    return comparable


def assert_equivalent(off, on):
    a, b = off["observer"], on["observer"]
    for key in ("command_sha256", "command_count", "trace_rows"):
        if a[key] != b[key]:
            raise AssertionError(f"Observer changed {key}")
    if comparable_record(off["record"]) != comparable_record(on["record"]):
        raise AssertionError("Observer changed episode record")
    if a["snapshots"]:
        raise AssertionError("Observer-off arm unexpectedly captured snapshots")
    return True


def load_cases(protocol_path: Path):
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    repo = protocol_path.parents[3]
    manifest = json.loads((repo / protocol["case_manifest"]).read_text(encoding="utf-8"))
    by_id = {case["id"]: case for group in manifest.values() if isinstance(group, list)
             for case in group if isinstance(case, dict)}
    return [(by_id[case_id], {int(cell["cell_id"].rsplit(":node-", 1)[1])
                              for cell in protocol["selected_nodes"] if cell["cell_id"].startswith(case_id + ":")})
            for case_id in protocol["selected_case_order"]]
