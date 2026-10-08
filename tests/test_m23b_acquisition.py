"""Offline runner checks only; no real MuJoCo construction or stepping.

The physics witness uses explicit stub classes. Authority controls reuse the
already-labelled fake lifecycle fixtures; their outcomes are not physics claims.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from experiments.m2.trusted_handoff_qualification_001 import acquire as runner
from g1swarm.mission.ir import Mission
from g1swarm.mission.lifecycle import mission_sha256
from g1swarm.trusted_handoff_v0 import full_plan_json
from g1swarm.state import RobotState
from test_m23_trusted_handoff import SOURCE, fixture


def empty_witness():
    return {"steps": 0, "node_calls": 0, "executor_calls": 0,
            "reset_calls": 0, "reset_data_calls": 0, "reset_keyframe_calls": 0}


def test_source_freeze_is_append_only_and_rejects_changed_membership(monkeypatch, tmp_path):
    root = tmp_path
    here = root / "experiment"
    here.mkdir()
    (here / "acquire.py").write_text("stub runner", encoding="utf8")
    (root / "pinned.py").write_text("frozen source", encoding="utf8")
    spec = {"frozen_source_paths": ["pinned.py"]}
    (here / "protocol.json").write_text(json.dumps(spec), encoding="utf8")
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "HERE", here)
    runner.freeze()
    assert runner.verify_sources()["status"] == "FROZEN_BEFORE_FORMAL_M2_3B_PHYSICS"
    frozen = (here / "source_manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        runner.freeze()
    assert (here / "source_manifest.json").read_bytes() == frozen
    (root / "pinned.py").write_text("changed source", encoding="utf8")
    with pytest.raises(ValueError, match="Frozen source mismatch"):
        runner.verify_sources()


def stub_surfaces(monkeypatch):
    native = []
    module = SimpleNamespace(
        mj_resetData=lambda *args, **kw: native.append(("reset", args, kw)),
        mj_resetDataKeyframe=lambda *args, **kw: native.append(("keyframe", args, kw)),
    )

    class Simulation:
        def __init__(self):
            self._data = SimpleNamespace(qpos=np.zeros(9), qvel=np.zeros(8),
                                         ctrl=np.zeros(2), time=0.0)
            self._mujoco = module
            self.steps = 0

        def state(self):
            return RobotState.from_dict({
                "base_position": [0.0, 0.0, 0.78],
                "base_orientation": [1.0, 0.0, 0.0, 0.0],
                "linear_velocity": [0.0, 0.0, 0.0],
                "angular_velocity": [0.0, 0.0, 0.0],
                "standing": True, "fallen": False,
                "simulation_time": self._data.time, "active_skill": "walk_forward",
            })

        def reset(self, *args, **kwargs):
            self._mujoco.mj_resetData("model", "data")
            return self.state()

        def step(self, control=None):
            self.steps += 1
            self._data.time += 0.002
            if control is not None:
                self._data.ctrl[:] = control
            return self.state()

    class Live:
        def __init__(self, simulation):
            self.simulation = simulation

        def run_node(self, node, mode):
            return self.simulation.step(np.ones(2))

    monkeypatch.setattr(runner, "G1Simulation", Simulation)
    monkeypatch.setattr(runner, "LiveMissionSession", Live)
    return Simulation, Live, module, native


def test_witness_calls_through_stubs_enforces_budget_and_restores(monkeypatch):
    simulation_class, live_class, module, native = stub_surfaces(monkeypatch)
    original = (simulation_class.reset, simulation_class.step, live_class.run_node,
                module.mj_resetData, module.mj_resetDataKeyframe)
    simulation = simulation_class()
    node = SimpleNamespace(node_id="n1", skill=SimpleNamespace(value="walk_forward"),
                           parameters={"distance_m": 4.0}, depends_on=())
    with runner.execution_witness(maximum_steps=1, maximum_wall_s=60,
                                  mujoco_module=module) as witness:
        simulation.reset(seed=0)
        state = live_class(simulation).run_node(node, "heading_lateral")
        assert state.simulation_time == 0.002 and simulation.steps == 1
        assert witness["steps"] == witness["node_calls"] == 1
        assert witness["reset_calls"] == witness["reset_data_calls"] == 1
        assert witness["trace"][0]["speed_mps"] == 0.0
        assert witness["node_dispatches"][0]["parameters"] == {"distance_m": 4.0}
        with pytest.raises(RuntimeError, match="PHYSICS_STEP_BUDGET_EXHAUSTED"):
            simulation.step(np.ones(2))
        assert simulation.steps == witness["steps"] == 1
    assert (simulation_class.reset, simulation_class.step, live_class.run_node,
            module.mj_resetData, module.mj_resetDataKeyframe) == original
    assert len(native) == 1


def test_witness_wall_budget_rejects_before_stub_execution(monkeypatch):
    simulation_class, _, module, native = stub_surfaces(monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(runner.time, "perf_counter", lambda: clock[0])
    simulation = simulation_class()
    with runner.execution_witness(maximum_steps=5, maximum_wall_s=1,
                                  mujoco_module=module) as witness:
        clock[0] = 1.0
        with pytest.raises(TimeoutError, match="WALL_TIME_BUDGET_EXHAUSTED"):
            simulation.reset()
        assert witness["reset_calls"] == witness["steps"] == 0
    assert native == []


def test_snapshot_captures_controller_memory_read_only(phase13_grounder, tmp_path):
    bundle = fixture(phase13_grounder, tmp_path)
    witness = empty_witness()
    before = runner.snapshot(bundle.session, witness)
    original_action = bundle.session.controller._action.copy()
    original_target = bundle.session.controller._target.copy()
    assert before["controller_action"] == [0.0, 0.0]
    assert before["controller_target"] == [0.0, 0.0]
    assert before["controller_counter"] == 0
    assert np.array_equal(bundle.session.controller._action, original_action)
    assert np.array_equal(bundle.session.controller._target, original_target)
    bundle.session.controller._counter = 1
    assert runner.snapshot(bundle.session, witness) != before


def test_executor_boundary_state_normalizes_only_its_call_counter(phase13_grounder, tmp_path):
    bundle = fixture(phase13_grounder, tmp_path)
    before = runner.snapshot(bundle.session, empty_witness())
    actual = deepcopy(before)
    actual["executor_calls"] += 1
    assert runner.canonical_entry_state_exact(before, actual)
    for field in ("time_s", "controller_counter", "node_calls", "reset_calls", "session_identity"):
        changed = deepcopy(actual)
        changed[field] += 1
        assert not runner.canonical_entry_state_exact(before, changed)
    changed = deepcopy(actual)
    changed["qvel"][0] += 0.001
    assert not runner.canonical_entry_state_exact(before, changed)


def test_complete_plan_and_lifecycle_hash_domains_are_separately_verified(phase13_grounder, tmp_path):
    bundle = fixture(phase13_grounder, tmp_path)
    import hashlib
    preparation = bundle.bridge.prepare(source=SOURCE, mission=bundle.mission)
    assert preparation.canonical_mission == full_plan_json(bundle.mission).encode("utf8")
    assert preparation.handoff_plan_sha256 == hashlib.sha256(preparation.canonical_mission).hexdigest()
    assert preparation.lifecycle_mission_sha256 == mission_sha256(bundle.mission)
    assert preparation.handoff_plan_sha256 != preparation.lifecycle_mission_sha256
    detached = Mission.from_dict(json.loads(preparation.canonical_mission))
    assert full_plan_json(detached).encode("utf8") == preparation.canonical_mission


def test_all_five_frozen_invalid_controls_have_zero_fixture_dispatch(phase13_grounder, tmp_path):
    bundle = fixture(phase13_grounder, tmp_path)
    witness = empty_witness()
    requests, events = [], []
    before = runner.snapshot(bundle.session, witness)
    old_files = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    calls = list(bundle.session.calls)
    runner.invalid_controls(
        bundle.bridge, bundle.authority, bundle.handoff,
        source=SOURCE, mission=bundle.mission, principal="alice", display_only_principal="display-only",
        session=bundle.session, witness=witness, requests=requests, events=events,
    )
    assert [r["request"] for r in requests] == [
        "missing_grant", "copied_registered_grant", "changed_plan_distance_4_to_6",
        "replay_burned_plan_mismatch_grant", "registered_display_only_principal_without_continuation_permission",
    ]
    assert [r["result"]["reason"] for r in requests] == [
        "UNTRUSTED_HANDOFF", "UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF", "PLAN_CHANGED",
        "UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF", "PRINCIPAL_CONTINUATION_PERMISSION_MISSING",
    ]
    assert runner.snapshot(bundle.session, witness) == before
    assert bundle.session.calls == calls
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == old_files
    assert all(runner.control_summary(request)["raw_state_unchanged"] for request in requests)
    assert all(event["simulation_steps"] == 0 for event in events)
    assert all(event["production_authority"] is False for event in events)


def test_complete_canonical_graph_comparison_includes_parameters_dependencies_and_identity():
    mission = {
        "schema_version": "2.0.0", "mission_id": "test-plan", "steps": [
            {"id": "n1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
            {"id": "n2", "skill": "stop", "parameters": {}, "depends_on": ["n1"]},
        ],
    }
    graph = {"nodes": [
        {"node_id": "n1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": []},
        {"node_id": "n2", "skill": "stop", "parameters": {}, "depends_on": ["n1"]},
    ]}
    assert runner.graph_plan(graph) == runner.canonical_graph_plan(mission)
    graph["nodes"][0]["parameters"]["distance_m"] = 6.0
    assert runner.graph_plan(graph) != runner.canonical_graph_plan(mission)
    graph["nodes"][0]["parameters"]["distance_m"] = 4.0
    graph["nodes"][1]["depends_on"] = []
    assert runner.graph_plan(graph) != runner.canonical_graph_plan(mission)


def test_trace_comparison_rejects_a_single_changed_physics_row(tmp_path):
    path = tmp_path / "trace.jsonl.gz"
    rows = [{"sequence": 1, "speed_mps": 0.1, "time_s": 0.002}]
    runner.save_trace(path, rows)
    assert runner.trace_equal(rows, path)
    changed = deepcopy(rows)
    changed[0]["speed_mps"] = 0.2
    assert not runner.trace_equal(changed, path)


@pytest.mark.parametrize("count,speed,expected", [(500, 0.099, True), (499, 0.01, False), (500, 0.101, False)])
def test_final_stop_window_has_frozen_criterion_and_requires_complete_history(count, speed, expected):
    result = {"mission_success": True, "physical_success": True,
              "nodes": [{"skill": "stop", "metrics": {"skill_status": "SUCCESS"}}]}
    rows = [{"active_skill": "stop", "speed_mps": speed, "finite": True,
             "standing": True, "fallen": False} for _ in range(count)]
    checks, metrics = runner.new_task_physical_checks(result, rows, timestep=0.002)
    assert checks["window_mean_speed"] is expected
    assert metrics["final_stop_window_steps"] == 500
    assert metrics["complete_window"] is (count >= 500)
    if count < 500:
        assert metrics["final_stop_window_mean_speed_mps"] is None
    else:
        assert metrics["final_stop_window_mean_speed_mps"] == pytest.approx(speed)


def test_new_task_failed_before_final_stop_stays_failed():
    result = {"mission_success": False, "physical_success": True,
              "nodes": [{"skill": "walk_forward", "metrics": {"skill_status": "SUCCESS"}}]}
    checks, metrics = runner.new_task_physical_checks(result, [], timestep=0.002)
    assert not checks["mission_success"] and not checks["final_stop_node_success"]
    assert not checks["window_mean_speed"] and not checks["finite_throughout"]
    assert metrics["final_stop_window_mean_speed_mps"] is None
