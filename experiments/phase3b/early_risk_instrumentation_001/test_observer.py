"""No-physics checks for the study-only observer hooks."""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from g1swarm.segmentation.mission import MissionFrame

spec = importlib.util.spec_from_file_location("early_risk_observer", Path(__file__).with_name("observer.py"))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def _state(t):
    return SimpleNamespace(
        simulation_time=t,
        base_position=(0.5, 0.1, 0.8),
        base_orientation=(1.0, 0.0, 0.0, 0.0),
        linear_velocity=(0.4, -0.1, 0.0),
        angular_velocity=(0.0, 0.0, -0.2),
    )


def _runner():
    traces = []
    received = []
    r = SimpleNamespace()
    r.trace = traces.append
    r.base = SimpleNamespace(compute_torques=lambda **kwargs: received.append(kwargs["command"]) or "ok")
    r.sim = SimpleNamespace(get_robot_state=lambda: _state(1.0))
    r.index = 1
    r.frame = MissionFrame.from_state(_state(0.0))
    r.planned_origin = np.array([0.0, 0.0])
    r.planned_heading = 0.0
    return r, traces, received


def _row(t):
    return {"node_index": 1, "skill": "walk_forward", "elapsed_s": t,
            "applied_command": [0.4, 0.0, 0.0], "nominal_command": [0.4, 0.0, 0.0]}


def test_snapshot_at_exact_tick_without_command_mutation():
    runner, traces, received = _runner()
    watcher = observer.Observer(runner, {1}, enabled=True)
    runner.trace(_row(0.9))
    runner.trace(_row(1.0))
    runner.trace(_row(1.0))
    command = np.array([0.4, 0.0, 0.0])
    assert runner.base.compute_torques(command=command) == "ok"
    assert received[0] is command
    assert traces == [_row(0.9), _row(1.0), _row(1.0)]
    assert set(watcher.snapshots) == {"1:1"}
    data = watcher.snapshots["1:1"]
    assert data["route_frame_xy_m"] == [0.5, 0.1]
    assert data["route_frame_vx_vy_mps"] == [0.4, -0.1]
    assert data["yaw_rate_radps"] == -0.2
    assert data["actual_correction_delta"] == [0.0, 0.0, 0.0]


def test_off_arm_records_commands_and_trace_but_not_snapshots():
    runner, _, _ = _runner()
    watcher = observer.Observer(runner, {1}, enabled=False)
    runner.trace(_row(1.0))
    runner.base.compute_torques(command=np.array([0.4, 0.0, 0.0]))
    assert watcher.snapshots == {}
    assert watcher.command_count == 1
    assert len(watcher.trace_rows) == 1


def test_equivalence_rejects_command_difference():
    record = {"wall_time_s": 2.0, "nodes": [], "total_sim_time_s": 2.0}
    off = {"record": record, "observer": {"command_sha256": "a", "command_count": 1,
                                           "trace_rows": [], "snapshots": {}}}
    on = {"record": {**record, "wall_time_s": 3.0}, "observer": {"command_sha256": "a",
            "command_count": 1, "trace_rows": [], "snapshots": {"0:1": {}}}}
    assert observer.assert_equivalent(off, on)
    on["observer"]["command_sha256"] = "b"
    try:
        observer.assert_equivalent(off, on)
    except AssertionError as exc:
        assert "command_sha256" in str(exc)
    else:
        raise AssertionError("command mismatch was accepted")


def test_equivalence_ignores_only_host_wall_clock_fields():
    record = {"wall_time_s": 2.0, "nodes": [{"duration_s": 3.0,
              "skill_metrics": {"elapsed_wall_time_s": 1.0, "distance_m": 1.5}}]}
    off = {"record": record, "observer": {"command_sha256": "same", "command_count": 10,
           "trace_rows": [], "snapshots": {}}}
    on = {"record": {"wall_time_s": 9.0, "nodes": [{"duration_s": 3.0,
          "skill_metrics": {"elapsed_wall_time_s": 8.0, "distance_m": 1.5}}]},
          "observer": {"command_sha256": "same", "command_count": 10,
          "trace_rows": [], "snapshots": {"0:1": {}}}}
    assert observer.assert_equivalent(off, on)
    on["record"]["nodes"][0]["skill_metrics"]["distance_m"] = 1.6
    try:
        observer.assert_equivalent(off, on)
    except AssertionError as exc:
        assert "episode record" in str(exc)
    else:
        raise AssertionError("scientific metric difference was accepted")
