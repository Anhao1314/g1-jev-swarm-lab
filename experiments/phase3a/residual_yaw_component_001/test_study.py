"""Offline intervention isolation checks. No simulator or policy is constructed."""
from __future__ import annotations
import importlib.util
import inspect
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("yaw_component_study_offline", HERE / "study.py")
study = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = study
spec.loader.exec_module(study)
controller = study.controller


def fake_runner(*, window=14., elapsed=2.1, node=1, skill="walk_forward", steps=1050, zero=False, correction_yaw=.2):
    state = SimpleNamespace(simulation_time=10.+elapsed, base_position=[0., 0., .8], base_orientation=[1., 0., 0., 0.])
    r = SimpleNamespace(authority_window_s=window, abort=Event(), treatment="learned", skill=skill,
                        index=node, previous="stand" if node == 1 else "turn", frame=None,
                        node_start=SimpleNamespace(simulation_time=10.), node_steps=steps, resets=0,
                        action=np.array([0., 0., -1.]), seen=[], rows=[])
    r.sim = SimpleNamespace(get_robot_state=lambda: state)
    r.correction = SimpleNamespace(compute=lambda _state, _frame, command, **kw: (np.array([command[0], command[1], correction_yaw]), None))
    r.observation = lambda nominal, active: (r.seen.append(active) or np.zeros(61, np.float32))
    r.dense_reward = lambda: 0.
    r.control = lambda obs, reward: (np.zeros(3) if zero else study.profile_action("yaw_only", node, skill, steps//50, window))
    r.trace = r.rows.append
    r.base = SimpleNamespace(compute_torques=lambda **kw: kw["command"].copy())
    return r


def apply(r, cls=controller.WindowController):
    return cls(r).compute_torques(command=np.array([.5, 0., 0.]))


def test_long_authority_keeps_legacy_observation_active_semantics():
    r = fake_runner()
    np.testing.assert_allclose(apply(r), [.5, 0., .08], rtol=0, atol=1e-15)
    assert r.seen == [False]
    assert r.rows[0]["active"] is True
    assert r.rows[0]["observation_active"] is False


@pytest.mark.parametrize("elapsed,steps", [(0., 0), (1.9, 950)])
def test_14s_adapter_matches_original_before_2s_for_zero_yaw_action(elapsed, steps):
    old, new = (fake_runner(window=14., elapsed=elapsed, steps=steps, zero=True) for _ in range(2))
    np.testing.assert_array_equal(apply(old, controller.ORIGINAL_CONTROLLER), apply(new))
    assert old.seen == new.seen
    assert [{k: v for k, v in row.items() if k != "observation_active"} for row in new.rows] == old.rows


def test_authority_expires_on_physics_tick_without_waiting_for_decision():
    r = fake_runner(elapsed=14.002, steps=7001)
    np.testing.assert_array_equal(apply(r), [.5, 0., .2])
    assert r.seen == []
    np.testing.assert_array_equal(r.action, [0., 0., 0.])


@pytest.mark.parametrize("node,skill", [(3, "walk_forward"), (1, "turn"), (5, "stop"), (0, "stand")])
def test_long_authority_does_not_leak_to_other_nodes(node, skill):
    r = fake_runner(node=node, skill=skill)
    apply(r)
    np.testing.assert_array_equal(r.action, [0., 0., 0.])
    assert not r.rows[0]["active"]


def test_total_yaw_clipping_stays_frozen():
    r = fake_runner(correction_yaw=-.7)
    assert apply(r)[2] == -.6


def test_zero_long_authority_has_no_command_effect():
    r = fake_runner(zero=True)
    np.testing.assert_array_equal(apply(r), [.5, 0., .2])
    assert r.seen == [False]


@pytest.mark.parametrize("tick,expected", [(0, [0.,0.,-1.]), (19, [0.,0.,-1.]), (20, [0.,0.,-1.]), (139, [0.,0.,-1.]), (140, [0.,0.,0.])])
def test_frozen_14s_action_schedule(tick, expected):
    np.testing.assert_array_equal(study.profile_action("yaw_only", 1, "walk_forward", tick, 14.), expected)


def test_no_undeclared_profiles_or_durations():
    with pytest.raises(ValueError):
        study.profile_action("lateral_only", 1, "walk_forward", 0, 14.)
    with pytest.raises(ValueError):
        study.profile_action("yaw_only", 1, "walk_forward", 0, 8.)
    assert len(study.RUN_PLAN) == 2
    assert [row[2] for row in study.RUN_PLAN] == [14.,14.]


def test_scoped_adapter_restores_after_exception():
    original_runner = study.old.ProbeRunner
    with pytest.raises(RuntimeError, match="synthetic abort"):
        with study.acquisition_adapter(14.):
            assert controller.legacy._Controller is controller.WindowController
            assert study.old.ProbeRunner is not original_runner
            raise RuntimeError("synthetic abort")
    assert controller.legacy._Controller is controller.ORIGINAL_CONTROLLER
    assert study.old.ProbeRunner is original_runner
    assert controller.legacy.WINDOW == 2.


def test_nested_substitution_rejected_without_losing_restore():
    with controller.isolated_controller():
        with pytest.raises(RuntimeError):
            with controller.isolated_controller():
                pass
    assert controller.legacy._Controller is controller.ORIGINAL_CONTROLLER


def test_adapter_has_only_declared_source_changes():
    old = inspect.getsource(controller.ORIGINAL_CONTROLLER.compute_torques)
    expected = old.replace('active = r.treatment == "learned" and eligible and elapsed < WINDOW-1e-9',
        'observation_active = r.treatment == "learned" and eligible and elapsed < WINDOW-1e-9\n        limit = r.authority_window_s if r.index == 1 and r.skill == "walk_forward" else WINDOW\n        active = r.treatment == "learned" and eligible and elapsed < limit-1e-9')
    expected = expected.replace('obs = r.observation(nominal, active)', 'obs = r.observation(nominal, observation_active)')
    expected = expected.replace('"eligible": eligible, "active": active, "nominal_command": nominal.tolist(),',
        '"eligible": eligible, "active": active, "observation_active": observation_active,\n                     "nominal_command": nominal.tolist(),')
    assert inspect.getsource(controller.WindowController.compute_torques) == expected
