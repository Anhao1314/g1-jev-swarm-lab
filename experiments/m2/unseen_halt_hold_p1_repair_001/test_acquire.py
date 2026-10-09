"""M2.5A adapter contract tests. Every backend here is fake; zero physics."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
spec_module = importlib.util.spec_from_file_location("m26a_acquire_under_test", HERE / "acquire.py")
acquire = importlib.util.module_from_spec(spec_module)
spec_module.loader.exec_module(acquire)
SPEC = json.loads(acquire.DESIGN.read_text(encoding="utf8"))
M24 = json.loads((acquire.M24).read_text(encoding="utf8"))


def parent_result(*, normal=False, halt_status="HALT_SUCCEEDED", has_halt=True):
    if normal:
        return {"state": "SUCCESS", "mission_success": True, "physical_success": True,
                "completed_nodes": 3, "physical_halt": None, "nodes": [
                    {"skill": "walk_forward"}, {"skill": "turn"},
                    {"skill": "stop", "metrics": {"skill_status": "SUCCESS"}}]}
    return {"state": "FAILED", "mission_success": False, "failure_type": "TASK_ENVELOPE_VIOLATION",
            "failed_node": "s1", "physical_halt": None if not has_halt else {
                "status": halt_status, "skill_status": "SUCCESS" if halt_status == "HALT_SUCCEEDED" else "TIMEOUT",
                "checks": {"skill_success": halt_status == "HALT_SUCCEEDED"},
                "trace": [{"speed_mps": 0.3}] + [{"speed_mps": 0.1} for _ in range(500)]}}


class FakeBackend:
    def __init__(self, parent: dict, *, speeds=None, standing=True, fail_step=None,
                 fail_exception=RuntimeError, continuity_change=False,
                 reset_on_hold=False, parent_steps=7139, observer_enabled=True):
        self.parent = parent
        self.speeds = speeds or [0.05] * 1000
        self.standing, self.fail_step = standing, fail_step
        self.fail_exception = fail_exception
        self.continuity_change, self.reset_on_hold = continuity_change, reset_on_hold
        self.parent_steps = parent_steps
        self.observer_enabled = observer_enabled
        self.commands = []
        self.steps = 0
        self.witness = {"native_steps": parent_steps, "integrity_failure": None,
                        "budget_failure": None, "hold_command_calls": 0}
        self.snap = {"time_s": 14.278, "qpos": [0.0, 0.0, 0.8], "qvel": [0.0, 0.0, 0.0],
                     "ctrl": [0.0], "xfrc_applied": [[0.0]],
                     "controller_action": [0.0], "controller_target": [0.0], "controller_counter": 7000,
                     "session_identity": 1, "simulation_identity": 2, "controller_identity": 3,
                     "policy_identity": 4, "reset_calls": 2, "native_reset_calls": 2,
                     "keyframe_reset_calls": 0, "controller_reset_calls": 2,
                     "node_dispatches": 1, "executor_dispatches": 1,
                     "native_steps": parent_steps, "session_steps": parent_steps}
        self.terminal = {"stop_status": "SUCCESS", "stop_window_mean_mps": 0.1,
                         "stop_crossing_time_s": self.snap["time_s"],
                         "stop_poststep_speeds": [0.1] * 500,
                         "snapshot": deepcopy(self.snap),
                         "skill_return_snapshot": deepcopy(self.snap)}
        self.entered_hold = False

    @contextmanager
    def __call__(self, spec, m24, cell, run_dir, prior_native_steps):
        backend = self

        class Executor:
            last_graph = SimpleNamespace(to_dict=lambda: {"nodes": [{"node_id": "s1"}]})

            def run(self, mission, *, existing_session, phase):
                assert existing_session is session and phase == "m26a_parent"
                assert mission["mission_id"] in ("m2-open-loop-walk6-turn45-stop",
                                                  "m24-parent-turn45-walk6", "m2-safe-walk4-turn45-stop")
                return SimpleNamespace(to_dict=lambda: deepcopy(backend.parent))

        session = object()

        def snapshot():
            value = deepcopy(backend.snap)
            if backend.continuity_change and not backend.entered_hold and backend.steps == 0:
                value["qpos"][0] = 0.001
            return value

        def step_zero():
            assert backend.entered_hold
            backend.commands.append([0.0, 0.0, 0.0])
            backend.witness["hold_command_calls"] += 1
            if backend.fail_step == backend.steps:
                raise backend.fail_exception("synthetic backend fault")
            backend.steps += 1
            backend.witness["native_steps"] += 1
            backend.snap["native_steps"] += 1
            backend.snap["session_steps"] += 1
            backend.snap["controller_counter"] += 1
            backend.snap["time_s"] += 0.002
            if backend.reset_on_hold and backend.steps == 1:
                backend.snap["controller_reset_calls"] += 1
            return object()

        def row(state, index):
            return {"hold_step": index, "native_sequence": backend.witness["native_steps"],
                    "time_s": backend.snap["time_s"], "position_m": [0.0, 0.0, 0.8],
                    "speed_mps": backend.speeds[index - 1], "standing": backend.standing,
                    "fallen": False, "finite": True, "raw_finite": True,
                    "command_xyz_mps_radps": [0.0, 0.0, 0.0]}

        def journal(row):
            if backend.observer_enabled:
                with (run_dir / "hold_incremental.jsonl").open("a", encoding="utf8") as stream:
                    stream.write(json.dumps(row) + "\n")

        yield {"session": session, "executor": Executor(), "terminal": self.terminal,
               "witness": self.witness, "snapshot": snapshot,
               "verify_historical_parent": lambda: {"status": "EXACT_M24_PARENT_NATIVE_PREFIX_MATCH"},
               "begin_hold": lambda: setattr(self, "entered_hold", True),
               "step_zero": step_zero, "state_row": row, "raw_last": lambda: {"raw_finite": True},
               "guard": lambda: None, "journal_hold_row": journal}


def run_fake(tmp_path, backend, cell_index=0):
    cell = SPEC["cells_in_order"][cell_index]
    result = acquire.run_cell(SPEC, M24, cell, tmp_path, backend)
    return result


def test_import_has_no_simulator_or_policy_import():
    module = ast.parse((HERE / "acquire.py").read_text(encoding="utf8"))
    imported = []
    for statement in module.body:
        if isinstance(statement, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom) and statement.module:
            imported.append(statement.module.split(".")[0])
    assert not {"mujoco", "torch", "g1swarm"} & set(imported)
    assert SPEC["physics_authorized"] is False


def test_fresh_worker_pins_import_origin_to_this_checkout_without_live_import():
    code = (
        "import importlib.util,json,sys;"
        f"p={str(HERE / 'acquire.py')!r};"
        "s=importlib.util.spec_from_file_location('m26a_path_test',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "w=m.target_import_witness();"
        "print(json.dumps({'witness':w,'mujoco_loaded':'mujoco' in sys.modules,'torch_loaded':'torch' in sys.modules}))"
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True,
                               text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["witness"]["module_origins"]["g1swarm"] == (acquire.ROOT / "src/g1swarm/__init__.py").as_posix()
    assert result["witness"]["module_origins"]["scripts.run_oracle_missions"] == (acquire.ROOT / "scripts/run_oracle_missions.py").as_posix()
    assert not result["mujoco_loaded"] and not result["torch_loaded"]


def test_loaded_stale_editable_package_fails_closed(monkeypatch):
    stale = SimpleNamespace(__spec__=SimpleNamespace(origin="D:/work/other-checkout/src/g1swarm/__init__.py"))
    monkeypatch.setitem(sys.modules, "g1swarm", stale)
    with pytest.raises(acquire.IntegrityFailure, match="TARGET_CHECKOUT_IMPORT_ORIGIN_MISMATCH:g1swarm"):
        acquire.target_import_witness()


def test_loaded_stale_submodule_fails_closed(monkeypatch):
    stale = SimpleNamespace(__spec__=SimpleNamespace(origin="D:/work/other-checkout/src/g1swarm/mission/runtime.py"))
    monkeypatch.setitem(sys.modules, "g1swarm.mission.runtime", stale)
    with pytest.raises(acquire.IntegrityFailure, match="STALE_LOADED_G1SWARM_SUBMODULE"):
        acquire.target_import_witness()


def test_exact_1000_zero_command_continuation_and_parent_preservation(tmp_path):
    backend = FakeBackend(parent_result())
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"
    assert outcome["coverage"] == "COMPLETE_HOLD"
    assert backend.steps == backend.witness["hold_command_calls"] == 1000
    assert backend.snap["controller_counter"] == 8000
    assert len((tmp_path / "hold_incremental.jsonl").read_text().splitlines()) == 1000
    assert (tmp_path / "parent_result.json").is_file()
    entry = json.loads((tmp_path / "hold_entry.json").read_text())
    assert entry["terminal"]["snapshot"] == entry["pre_first_step"]
    assert len(entry["seed_speeds_mps"]) == 500


def test_fake_observer_ab_does_not_change_control_execution(tmp_path):
    """Offline seam check only; real MuJoCo observer equivalence remains unmeasured."""
    on_dir, off_dir = tmp_path / "on", tmp_path / "off"
    on_dir.mkdir()
    off_dir.mkdir()
    on, off = FakeBackend(parent_result(), observer_enabled=True), FakeBackend(parent_result(), observer_enabled=False)
    on_outcome, off_outcome = run_fake(on_dir, on), run_fake(off_dir, off)
    assert on.commands == off.commands == [[0.0, 0.0, 0.0]] * 1000
    assert on.steps == off.steps == 1000
    assert on.snap == off.snap
    assert on_outcome == off_outcome
    assert (on_dir / "hold_incremental.jsonl").exists()
    assert not (off_dir / "hold_incremental.jsonl").exists()


def test_normal_stop_control_can_enter_hold_without_failure_halt(tmp_path):
    backend = FakeBackend(parent_result(normal=True), parent_steps=5991)
    outcome = run_fake(tmp_path, backend, cell_index=5)
    assert outcome["status"] == "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"
    assert outcome["parent_halt_status"] is None


def test_unsafe_early_stop_is_scientific_failure_with_partial_rows(tmp_path):
    backend = FakeBackend(parent_result(), standing=False)
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_FAILED"
    assert outcome["coverage"] == "PARTIAL_PHYSICAL_UNSAFE"
    assert backend.steps == 1


def test_complete_rolling_mean_failure_is_retained(tmp_path):
    backend = FakeBackend(parent_result(), speeds=[0.2] * 999 + [0.05])
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_FAILED"
    assert not outcome["checks"]["rolling_mean"]
    assert outcome["checks"]["final_speed"]


def test_backend_error_is_technical_partial_and_no_retry(tmp_path):
    backend = FakeBackend(parent_result(), fail_step=4)
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "TECHNICAL_PARTIAL"
    assert outcome["hold_observed_steps"] == 4
    assert backend.witness["hold_command_calls"] == 5


@pytest.mark.parametrize("failure_type", [acquire.IntegrityFailure, acquire.BudgetFailure])
def test_integrity_or_budget_exception_cannot_be_censored_as_technical(tmp_path, failure_type):
    backend = FakeBackend(parent_result(), fail_step=0, fail_exception=failure_type)
    with pytest.raises(failure_type, match="synthetic backend fault"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0
    assert not (tmp_path / "outcome.json").exists()


def test_mutated_terminal_is_integrity_failure_before_step(tmp_path):
    backend = FakeBackend(parent_result(), continuity_change=True)
    with pytest.raises(acquire.IntegrityFailure, match="TERMINAL_STOP_TO_HOLD_ENTRY_CHANGED"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0


def test_controller_reset_during_hold_is_integrity_failure(tmp_path):
    backend = FakeBackend(parent_result(), reset_on_hold=True)
    with pytest.raises(acquire.IntegrityFailure, match="FORBIDDEN_RESET_OR_DISPATCH"):
        run_fake(tmp_path, backend)


def test_missing_first_crossing_seed_cannot_pass(tmp_path):
    backend = FakeBackend(parent_result())
    backend.terminal["stop_poststep_speeds"] = [0.1] * 499
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "INCONCLUSIVE_MISSING_EVIDENCE"
    assert outcome["coverage"] == "NO_HOLD"
    assert backend.steps == 0


def test_native_budget_refuses_unaffordable_hold_before_step(tmp_path):
    backend = FakeBackend(parent_result(), parent_steps=29901)
    backend.snap["native_steps"] = 29901
    backend.terminal["snapshot"]["native_steps"] = 29901
    backend.terminal["skill_return_snapshot"]["native_steps"] = 29901
    with pytest.raises(acquire.BudgetFailure, match="CELL_NATIVE_STEPS_CANNOT_FIT_HOLD"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0


def test_reset_contract_allows_parent_controller_only():
    assert acquire.reset_permitted("simulation", "initialization", False)
    assert acquire.reset_permitted("native", "initialization", False)
    assert acquire.reset_permitted("controller", "parent", False)
    for phase in ("parent", "hold"):
        assert not acquire.reset_permitted("simulation", phase, False)
        assert not acquire.reset_permitted("native", phase, False)
    assert not acquire.reset_permitted("controller", "parent", True)
    assert not acquire.reset_permitted("controller", "hold", True)
    assert not acquire.reset_permitted("keyframe", "initialization", False)


def test_external_supervisor_kills_blocked_nonphysics_worker(tmp_path):
    with pytest.raises(acquire.BudgetFailure, match="HARD_WALL_WATCHDOG"):
        acquire.supervise([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 0.1)
    receipt = json.loads((tmp_path / "supervisor_timeout.json").read_text(encoding="utf8"))
    assert receipt["status"] == "PARTIAL_STOPPED" and receipt["no_retry"] is True



@pytest.mark.parametrize("cell_index", [1,2,3,4])
def test_force_exact_100_intervals_and_clear(cell_index):
    push = SPEC["cells_in_order"][cell_index]["push"]
    start = push["native_pre_step_start_index"]
    vectors = [acquire.force_at_pre_step(push, n) for n in range(2202)]
    assert sum(any(v) for v in vectors) == 100
    assert all(v == [0.0,0.0,0.0] for v in vectors[:start])
    assert vectors[start] == [float(push["force_n"])*d for d in push["direction_world"]]
    assert vectors[start+99] == vectors[start]
    assert vectors[start+100] == [0.0,0.0,0.0]

@pytest.mark.parametrize("failure_type", ["SKILL_TIMEOUT", "PHYSICAL_FAILURE"])
def test_unsupported_parent_failure_never_enters_hold(tmp_path, failure_type):
    parent = parent_result(has_halt=False)
    parent["failure_type"] = failure_type
    backend = FakeBackend(parent)
    out = run_fake(tmp_path, backend, cell_index=1)
    assert out["status"] == "PARENT_SKILL_OR_PHYSICAL_FAILURE_NO_HALT_NO_HOLD"
    assert not backend.entered_hold and backend.steps == 0
    assert json.loads((tmp_path/"parent_result.json").read_text()) == parent

def test_strict_trigger_missing_halt_is_integrity_not_no_coverage(tmp_path):
    backend=FakeBackend(parent_result(has_halt=False))
    with pytest.raises(acquire.IntegrityFailure, match="TRIGGER_ROUTING"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0

def test_valid_halt_failure_retained_without_hold(tmp_path):
    backend=FakeBackend(parent_result(halt_status="HALT_FAILED"))
    result=run_fake(tmp_path,backend)
    assert result["status"] == "HALT_FAILED_NO_HOLD"
    assert backend.steps == 0

def test_complete_no_trigger_preserves_full_parent_and_never_forces_hold(tmp_path):
    parent={"state":"SUCCESS", "mission_success": True, "physical_success":True,"completed_nodes":3,"physical_halt":None}
    backend=FakeBackend(parent)
    result=run_fake(tmp_path,backend,cell_index=4)
    assert result["status"] == "NO_HALT_TRIGGER" and backend.steps == 0
    assert json.loads((tmp_path/"parent_result.json").read_text()) == parent

def test_no_authorization_does_not_preflight_or_create_output(tmp_path,monkeypatch):
    monkeypatch.setattr(acquire,"preflight",lambda *_: pytest.fail("preflight forbidden"))
    with pytest.raises(PermissionError):
        acquire.acquire(authorize_physics=False,readiness_sha256="x",output=tmp_path/"absent",execution_head="x")
    assert not (tmp_path/"absent").exists()

def test_write_once_preserves_original(tmp_path):
    path=tmp_path/"raw.json"
    acquire.write_new(path,{"negative":True})
    with pytest.raises(FileExistsError):
        acquire.write_new(path,{"negative":False})
    assert json.loads(path.read_text()) == {"negative":True}

def test_nonfinite_raw_preserved_explicitly():
    assert acquire.json_safe({"raw":[float("nan"),float("inf")]}) == {"raw":[{"nonfinite":"nan"},{"nonfinite":"inf"}]}

def test_exact_execution_head_required_before_execution():
    with pytest.raises(acquire.IntegrityFailure,match="OWNER_EXECUTION_HEAD"):
        acquire.require_execution_head("bad")

def test_real_native_observer_seam_does_not_mutate_fake_execution():
    class Array(list):
        def tolist(self): return deepcopy(list(self))
    data=SimpleNamespace(time=1.0,qpos=Array([0.0,0.0,0.8]),qvel=Array([0.0]*6),ctrl=Array([0.1]),xfrc_applied=Array([[0.0]*6]),warning=[SimpleNamespace(number=0,lastinfo=0)])
    controller=SimpleNamespace(_action=Array([0.0]),_target=Array([0.1]),_counter=500)
    before=deepcopy(data.__dict__),deepcopy(controller.__dict__)
    raw=acquire.observe_native(data,controller,sequence=500,phase="parent")
    assert data.time==before[0]["time"] and data.qpos==before[0]["qpos"] and data.ctrl==before[0]["ctrl"]
    assert controller._action==before[1]["_action"] and controller._counter==500
    assert raw["warnings"]==[{"index":0,"number":0,"lastinfo":0}] and raw["raw_finite"]

def test_actual_command_passthrough_seam_preserves_identity_and_output():
    class Command(list):
        def tolist(self): return list(self)
    command=Command([0.0,0.0,0.0]); emissions=[]; calls=[]
    def original(controller,**kwargs):
        calls.append((controller,kwargs["command"]));return [0.1]
    controller=object()
    result=acquire.observed_call(original,emissions.append)(controller,command=command)
    assert calls==[(controller,command)] and calls[0][1] is command
    assert emissions==[[0.0,0.0,0.0]] and result==[0.1]

def test_missing_warning_metadata_is_evidence_failure():
    with pytest.raises(acquire.MissingEvidence): acquire.warning_counters(object())

@pytest.mark.parametrize("error", [RuntimeError, acquire.IntegrityFailure, acquire.BudgetFailure])
def test_real_walk_exit_cleanup_seam_clears_force_even_on_exception(error):
    fake={"force":[0.0,-60.0,0.0],"native_rows":[{"negative":"preserved"}]}
    def operation(): raise error("retained failure")
    def clear(): fake["force"]=[0.0,0.0,0.0]
    with pytest.raises(error,match="retained failure"):
        acquire.call_with_cleanup(operation,clear)
    assert fake=={"force":[0.0,0.0,0.0],"native_rows":[{"negative":"preserved"}]}

def test_real_walk_exit_cleanup_seam_clears_after_normal_result():
    force=[-60.0]; calls=[]
    def clear(): force[0]=0.0;calls.append("released")
    assert acquire.call_with_cleanup(lambda:"SUCCESS",clear)=="SUCCESS"
    assert force==[0.0] and calls==["released"]

def test_runtime_caught_observer_fault_is_technical_partial_not_physical_halt_failure(tmp_path):
    parent = parent_result(halt_status="HALT_FAILED")
    parent["physical_halt"].update(failure_stage="stop_skill_or_observer",failure_type="OSError",failure_reason="fixture observer disk failure")
    backend = FakeBackend(parent)
    result = run_fake(tmp_path,backend)
    assert result["status"] == "TECHNICAL_PARTIAL" and backend.steps == 0
    assert result["technical_failure"] == parent["physical_halt"]
    assert json.loads((tmp_path/"parent_result.json").read_text()) == parent

def test_raw_nonfinite_can_retain_physical_halt_failure_despite_caught_exception():
    parent=parent_result(halt_status="HALT_FAILED")
    parent["physical_halt"].update(failure_stage="stop_skill_or_observer",failure_type="ValueError")
    assert acquire.entry_classification(parent,SPEC["cells_in_order"][0],None,explicit_raw_unsafe=True)==(None,"HALT_FAILED_NO_HOLD")

@pytest.mark.parametrize("elapsed", [720.0,720.1,1000.0])
def test_global_wall_guard_rejects_at_or_after_bound_before_more_dispatch(elapsed):
    with pytest.raises(acquire.BudgetFailure,match="CAMPAIGN_WALL"):
        acquire.campaign_wall_guard(100.0,SPEC,clock=lambda:100.0+elapsed)

def test_global_wall_guard_before_bound():
    acquire.campaign_wall_guard(100.0,SPEC,clock=lambda:819.999)

def test_prefix_audit_is_bracketed_by_wall_guards_and_previous_worker_rejects_technical_partial():
    source=(HERE/"acquire.py").read_text()
    supervisor=source[source.index("def acquire(*"):source.index("def main()")]
    before,after=supervisor.split('verify_acquisition_prefix(output, cell["id"])')
    assert 'campaign_wall_guard(started, spec)' in before
    assert after.lstrip().startswith('campaign_wall_guard(started, spec)')
    worker=source[source.index('preceding = spec['):]
    assert '"TECHNICAL_PARTIAL"' in worker and '"INCONCLUSIVE_MISSING_EVIDENCE"' in worker

def test_success_supervisor_has_independent_wall_receipt(tmp_path):
    acquire.supervise([sys.executable,"-c","pass"],tmp_path,5.0)
    receipt=json.loads((tmp_path/"supervisor_receipt.json").read_text())
    assert receipt["status"]=="WORKER_COMPLETED" and receipt["worker_exit_code"]==0
    assert receipt["allocated_wall_bound_s"]==5.0 and receipt["wall_elapsed_s"]>=0
    assert receipt["wall_ended_monotonic_s"]>=receipt["wall_started_monotonic_s"]

def test_failed_supervisor_persists_wall_receipt(tmp_path):
    with pytest.raises(acquire.IntegrityFailure):
        acquire.supervise([sys.executable,"-c","raise RuntimeError('fixture')"],tmp_path,5.0)
    receipt=json.loads((tmp_path/"supervisor_receipt.json").read_text())
    assert receipt["status"]=="WORKER_EXIT_FAILURE" and receipt["worker_exit_code"]!=0

def test_hardkill_preserves_independent_allocated_wall_receipt(tmp_path):
    with pytest.raises(acquire.BudgetFailure):
        acquire.supervise([sys.executable,"-c","import time;time.sleep(10)"],tmp_path,0.05)
    receipt=json.loads((tmp_path/"supervisor_receipt.json").read_text())
    assert receipt["status"]=="HARD_WALL_WATCHDOG" and receipt["allocated_wall_bound_s"]==0.05
    assert receipt["wall_elapsed_s"]>=0.05

def test_cell_wall_includes_prefix_audit_bound():
    cell=SPEC["cells_in_order"][0]
    with pytest.raises(acquire.BudgetFailure,match="INCLUDING_PREFIX_AUDIT"):
        acquire.cell_wall_guard(10.0,cell,clock=lambda:130.0)
    acquire.cell_wall_guard(10.0,cell,clock=lambda:129.9)

def test_campaign_success_and_partial_share_exact_provenance_and_budget_fields():
    source=(HERE/"acquire.py").read_text()
    body=source[source.index("def acquire(*"):source.index("def main()")]
    for field in ("execution_head","readiness_sha256","source_manifest_sha256","protocol_sha256","frozen_budget"):
        assert '"'+field+'"' in body
    assert body.count('**bindings, **wall_fields(started)')==3
    assert 'cell_wall_guard(cell_started, cell)' in body


@pytest.mark.parametrize("stage", ["parent_node:walk_forward", "failure_halt_stop", "post_halt_hold"])
@pytest.mark.parametrize("message", ["control contains non-finite values", "control has wrong shape"])
def test_original_router_unsafe_keeps_control_error_source_and_forces_technical(tmp_path, stage, message):
    acquire.target_import_witness()
    from g1swarm.simulation.errors import InvalidControlError
    from g1swarm.skills.router import SkillRouter
    from g1swarm.skills.contract import Skill, SkillContext, SkillStatus
    witness = {"native_steps": 7, "phase": "hold" if stage == "post_halt_hold" else "parent", "stage": stage}
    records = []
    original_error = InvalidControlError(message)
    def malformed(*args, **kwargs):
        raise original_error from ValueError("synthetic original control computation")
    retained = acquire.exception_observer(malformed, "simulation.step", witness, records.append,
        lambda: {"qpos": [0.0], "qvel": [0.0], "ctrl": [float("nan")]})
    class FakeFaultSkill(Skill):
        name = "fixture"
        def run(self, context):
            retained()
    actual_router = SkillRouter([FakeFaultSkill()])
    routed = actual_router.execute("fixture", SkillContext(simulation=object()))
    assert routed.status == SkillStatus.UNSAFE  # shared Router behaviour unchanged
    assert records[0]["qualified_type"] == "g1swarm.simulation.errors.InvalidControlError"
    assert records[0]["stage"] == stage and records[0]["native_steps"] == 7
    assert "malformed" in records[0]["traceback"] and records[0]["cause_chain"][0]["qualified_type"] == "builtins.ValueError"
    assert witness["technical_failures"] == records
    backend = FakeBackend({"state": "FAILED", "mission_success": False, "failure_type": "SKILL_FAILURE"})
    backend.witness["technical_failures"] = records
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == outcome["completion_status"] == "TECHNICAL_PARTIAL"
    assert outcome["halt"] == "TECHNICAL_UNASSESSED" and not backend.entered_hold and backend.steps == 0


def test_exception_observer_is_identity_preserving_on_valid_path():
    argument, result, records = object(), object(), []
    witness = {"native_steps": 0}
    def original(value, *, command):
        assert value is argument and command is argument
        return result
    call = acquire.exception_observer(original, "controller.compute_torques", witness, records.append, lambda: pytest.fail("normal observation forbidden"))
    assert call(argument, command=argument) is result and not records and "technical_failures" not in witness


def test_new_native_nonfinite_is_physical_but_stale_nonfinite_is_not():
    acquire.target_import_witness()
    from g1swarm.simulation.errors import SimulationStateError
    for advances in (False, True):
        witness, records = {"native_steps": 2, "phase": "parent"}, []
        def native_failure():
            witness["native_steps"] += int(advances)
            raise SimulationStateError("non-finite simulation state")
        call = acquire.exception_observer(native_failure, "simulation.step", witness, records.append,
            lambda: {"qpos": [float("nan")], "qvel": [0.0]})
        with pytest.raises(SimulationStateError):
            call()
        assert bool(witness.get("technical_failures")) is not advances
        assert records[0]["classification"] == ("OBSERVED_NATIVE_PHYSICAL_NONFINITE" if advances else "TECHNICAL_CONTROL_OR_ADAPTER_ERROR")


@pytest.mark.parametrize("criterion", ["rolling_mean", "xy_path_length"])
def test_partial_hold_observed_failure_survives_later_technical_error(tmp_path, criterion):
    backend = FakeBackend(parent_result(), fail_step=1, speeds=[1.0] * 1000)
    if criterion == "xy_path_length":
        # One recorded prefix row crossed the existing path bound.
        original_backend = backend.__call__
        @contextmanager
        def path_backend(*args):
            with original_backend(*args) as rt:
                original_row = rt["state_row"]
                def row(state, index):
                    value = original_row(state, index)
                    value["position_m"][0] = 0.21
                    return value
                rt["state_row"] = row
                yield rt
        selected = path_backend
    else:
        selected = backend
    outcome = acquire.run_cell(SPEC, M24, SPEC["cells_in_order"][0], tmp_path, selected)
    assert outcome["status"] == outcome["completion_status"] == "TECHNICAL_PARTIAL"
    assert outcome["hold_physical_status"] == "HOLD_FAILED" and outcome["observed_hold_failure"] is True
    assert any(item["criterion"] == criterion for item in outcome["observed_physical_failures"])
    assert backend.steps == 1


@pytest.mark.parametrize("status", ["TECHNICAL_PARTIAL", "HOLD_FAILED"])
def test_technical_outcome_stops_campaign_before_next_worker(tmp_path, monkeypatch, status):
    monkeypatch.setattr(acquire, "preflight", lambda *_: (SPEC, M24, {}))
    monkeypatch.setattr(acquire, "require_execution_head", lambda *_: None)
    monkeypatch.setattr(acquire, "sha256", lambda *_: "fixture")
    workers = []
    def supervise(command, run_dir, timeout):
        workers.append(run_dir.name)
        acquire.write_new(run_dir / "outcome.json", {"status": status, "completion_status": "TECHNICAL_PARTIAL", "observed_hold_failure": True})
        acquire.write_new(run_dir / "witness.json", {"native_steps": 0, "technical_failures": [{"qualified_type": "g1swarm.simulation.errors.InvalidControlError"}]})
        (run_dir / "native_incremental.jsonl").write_text("")
    monkeypatch.setattr(acquire, "supervise", supervise)
    with pytest.raises(RuntimeError, match="CELL_TECHNICAL_PARTIAL_NO_RETRY"):
        acquire.acquire(authorize_physics=True, readiness_sha256="fixture", execution_head="fixture", output=tmp_path / "campaign")
    assert workers == [SPEC["cells_in_order"][0]["id"]]
    receipt = json.loads((tmp_path / "campaign/campaign_receipt.json").read_text())
    assert receipt["status"] == "PARTIAL_STOPPED" and receipt["completed_cells"][0]["observed_hold_failure"] is True


@pytest.mark.parametrize("error", [RuntimeError("control calculation fault"), ValueError("observation shape fault")])
def test_control_helper_errors_before_compute_preserve_exception_identity_and_capture_failure(error):
    witness, records = {"native_steps": 17, "phase": "parent", "stage": "parent_node:walk_forward"}, []
    def original(*args):
        raise error
    def broken_observer():
        raise RuntimeError("snapshot unavailable")
    call = acquire.exception_observer(original, "control._policy_torques", witness, records.append, broken_observer)
    with pytest.raises(type(error)) as raised:
        call()
    assert raised.value is error and witness["technical_failures"] == records
    assert records[0]["raw_evidence"] is None and records[0]["raw_evidence_error"] == "RuntimeError: snapshot unavailable"
    assert records[0]["native_steps_before_call"] == records[0]["native_steps"] == 17


def test_partial_instant_speed_is_not_formal_endpoint_failure(tmp_path):
    backend = FakeBackend(parent_result(), speeds=[0.101] * 1000, fail_step=1)
    outcome = run_fake(tmp_path, backend)
    # Seed is0.1: even0.101 shiftsrollingmeanabove0.1; useexplicitlowerseed.
    assert outcome["observed_hold_failure"]
    lower_seed = [0.05] * 500
    row = {"speed_mps": 0.101, "position_m": [0.0, 0.0, 0.8],
        "finite": True, "raw_finite": True, "standing": True, "fallen": False}
    measured = acquire.assess_hold([row], lower_seed, SPEC, backend.terminal)
    assert measured["completion_status"] == "TECHNICAL_PARTIAL"
    assert measured["status"] == "TECHNICAL_PARTIAL"
    assert measured["observed_physical_failures"] == [] and measured["observed_hold_failure"] is False


def test_router_control_attempt_counter_advance_is_recorded_without_native_step():
    acquire.target_import_witness()
    from g1swarm.simulation.errors import InvalidControlError
    from g1swarm.skills.router import SkillRouter
    from g1swarm.skills.contract import Skill, SkillContext, SkillStatus
    witness, records = {"native_steps": 23, "phase": "hold", "stage": "post_halt_hold"}, []
    snapshot = {"native_steps": 23, "session_steps": 23, "time_s": 0.046,
        "qpos": [0.0, 0.0, 0.8], "qvel": [0.0] * 6, "ctrl": [0.0],
        "xfrc_applied": [[0.0] * 6], "controller_counter": 23,
        "controller_action": [0.0], "controller_target": [0.0],
        "session_identity": 1, "simulation_identity": 2, "controller_identity": 3,
        "policy_identity": 4, "reset_calls": 2, "native_reset_calls": 2,
        "keyframe_reset_calls": 0, "controller_reset_calls": 2,
        "node_dispatches": 1, "executor_dispatches": 1}
    before = deepcopy(snapshot)
    def reject_control(*args, **kwargs):
        raise InvalidControlError("control contains non-finite values")
    rejected_step = acquire.exception_observer(reject_control, "simulation.step", witness,
        records.append, lambda: deepcopy(snapshot))
    class FakePolicyAttempt(Skill):
        name = "fixture"
        def run(self, context):
            snapshot["controller_counter"] += 1
            snapshot["controller_action"] = [0.3]
            snapshot["controller_target"] = [float("nan")]
            rejected_step()
    result = SkillRouter([FakePolicyAttempt()]).execute("fixture", SkillContext(simulation=object()))
    assert result.status == SkillStatus.UNSAFE
    assert witness["native_steps"] == records[0]["native_steps"] == records[0]["native_steps_before_call"] == 23
    assert records[0]["sequence_next"] == 24
    captured = records[0]["raw_evidence"]
    assert captured["controller_counter"] == 24 and captured["controller_action"] == [0.3]
    for key in ("qpos", "qvel", "time_s", "ctrl", "session_steps", "simulation_identity", "controller_identity", "policy_identity", "reset_calls"):
        assert captured[key] == before[key]
    assert witness["technical_failures"] == records
    assert acquire.json_safe(captured)["controller_target"] == [{"nonfinite": "nan"}]
