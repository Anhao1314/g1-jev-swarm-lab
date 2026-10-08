"""Independent adapter checks: fake state-machine resources, never real physics.
Actual unchanged Runtime/lifecycle/handoff execute fixture outcomes. These are not
new scientific labels and establish no physical reproducibility or safety.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from experiments.m2.cross_state_reliability_001 import acquire as adapter
from experiments.m2.trusted_handoff_qualification_001 import acquire as old
from g1swarm.characterization.perturbations import DisturbanceProxy, PushSpec
from g1swarm.mission import MissionExecutor, MissionValidator
from g1swarm.mission.ir import Mission
from g1swarm.state import RobotState
from g1swarm.trusted_handoff_v0 import full_plan_json
from test_m2_mission_lifecycle import Session
from test_mission_runtime import FakeSession, _protocol

DESIGN = Path(__file__).resolve().parents[1] / "experiments/m2/cross_state_reliability_design_001/protocol.json"

def spec():
    return json.loads(DESIGN.read_text(encoding="utf8"))

@pytest.fixture(autouse=True)
def forbid_real_execution(monkeypatch):
    import mujoco
    import torch
    import g1swarm.config as config
    from g1swarm.simulation.g1_simulation import G1Simulation
    denied = []
    def fail(*args, **kwargs):
        denied.append("forbidden live execution")
        raise AssertionError("NO_REAL_PHYSICS_OR_MODEL_INFERENCE_IN_READINESS")
    for name in ("mj_step", "mj_forward", "mj_resetData", "mj_resetDataKeyframe"):
        monkeypatch.setattr(mujoco, name, fail)
    for name in ("__init__", "step", "reset"):
        monkeypatch.setattr(G1Simulation, name, fail)
    monkeypatch.setattr(config, "build_simulation", fail)
    monkeypatch.setattr(config, "build_controller", fail)
    monkeypatch.setattr(torch.jit, "load", fail)
    yield denied
    assert denied == [], "A test attempted a real live path"

class FixturePoses:
    def capture(self, simulation):
        pass
    def save(self, path, simulation):
        Path(path).write_bytes(b"OFFLINE_FAKE_POSES_NOT_SCIENTIFIC_EVIDENCE")

class OrchestrationSession(Session):
    def __init__(self, mode, witness, raw, budget, cell):
        super().__init__()
        self.mode, self.witness, self.raw, self.budget, self.cell = mode, witness, raw, budget, cell
        self.timestep = 0.002
        self._data.xfrc_applied = np.zeros((1, 6))
        self.native_count = [0]
    def record(self, count, skill):
        for _ in range(count):
            self.budget.guard(self.cell, self.native_count[0], stepping=True)
            self.native_count[0] += 1
            self.budget.native_steps += 1
            self.witness["steps"] += 1
            self.witness["trace"].append({"sequence":self.witness["steps"],"phase":self.witness["phase"],"active_skill":skill,"speed_mps":0.05,"finite":True,"standing":True,"fallen":False})
            self.raw.append({"time_s":float(self._data.time),"qpos":self._data.qpos.tolist(),"qvel":self._data.qvel.tolist(),"ctrl":self._data.ctrl.tolist(),"xfrc_applied":self._data.xfrc_applied.tolist(),"controller":{"counter":self.controller._counter}})
    def run_node(self, node, execution_mode):
        self.witness["node_calls"] += 1
        self.witness["node_dispatches"].append({"node_id":node.node_id,"skill":node.skill.value,"parameters":deepcopy(node.parameters),"depends_on":list(node.depends_on),"phase":self.witness["phase"]})
        result = super().run_node(node, execution_mode)
        if node.node_id == "s1":
            result.metrics["lateral_drift_m"] = 0.30 if self.mode not in {"no_trigger", "normal", "skill_failure"} else 0.0
        if self.mode == "skill_failure" and node.node_id == "s1":
            result.status = "FAILURE"
        if self.mode == "child_failure" and node.node_id == "n1":
            result.metrics["lateral_drift_m"] = 0.30
        result.metrics["skill_status"] = result.status
        self._state["active_skill"] = node.skill.value
        if node.skill.value == "stop":
            self._state["linear_velocity"] = [0.05, 0.0, 0.0]
        self.record(500 if node.skill.value == "stop" else 10, node.skill.value)
        return result
    def run_failure_halt(self, contract):
        result = super().run_failure_halt(contract)
        self.record(10, "stop")
        if self.mode == "halt_failed":
            result["status"] = "HALT_FAILED"
            result["checks"]["window_mean_speed"] = False
            result["skill_metrics"]["final_window_mean_speed_mps"] = 0.2
        if self.mode == "ineligible":
            self._state["linear_velocity"] = [0.451, 0.0, 0.0]
        if self.mode == "budget_swallowed":
            self.witness["budget_failure"] = "WALL_TIME_BUDGET_EXHAUSTED"
        return result
    def step(self, control):
        # One deterministic fake tick for the real stale-grant orchestration.
        self._data.ctrl[:] = control
        self._state["simulation_time"] += self.timestep
        self._state["base_position"][0] += 0.001
        self._data.time = self._state["simulation_time"]
        self._data.qpos[0] = self._state["base_position"][0]
        self.record(1, self._state["active_skill"])
        return self.get_robot_state()

def fake_backend(grounder, mode="eligible", captures=None, mutate_parent=False):
    @contextmanager
    def backend(science, cell, run_dir, budget):
        witness={"steps":0,"node_calls":0,"executor_calls":0,"reset_calls":2,"reset_data_calls":2,"reset_keyframe_calls":0,"phase":"parent","trace":[],"node_dispatches":[],"budget_failure":None}
        raw=[]
        session=OrchestrationSession(mode,witness,raw,budget,cell)
        executor=MissionExecutor(validator=MissionValidator(),grounder=grounder,session_factory=lambda seed:pytest.fail("external session"),protocol=_protocol(),recorder_root=str(run_dir/"ledger"),walk_strict_gate=True,physical_halt_contract=json.loads((adapter.ROOT/science["contracts"]["halt_contract"]).read_text(encoding="utf8")))
        runtime={"session":session,"executor":executor,"witness":witness,"raw_rows":raw,"helpers":old,"poses":FixturePoses(),"protocol":_protocol(),"force_zero":lambda:True,"native_count":session.native_count,"push_events":lambda:[]}
        if captures is not None:captures.append(runtime)
        try:
            yield runtime
        finally:
            if mutate_parent:
                executor.last_graph.nodes[0].parameters["tamper"] = True
            session.close()
    return backend

def run_fixture(tmp_path, grounder, mode="eligible", arm="authorization_refusals", captures=None):
    science=spec();cell=deepcopy(next(c for c in science["run_order"] if c["state_id"]=="transition_turn45_walk6" and c["arm"]==arm))
    run_dir=tmp_path/"offline_fixture";run_dir.mkdir()
    budget=adapter.CampaignBudget(science)
    result=adapter.run_arm(science,cell,run_dir,fake_backend(grounder,mode,captures),budget)
    return result,run_dir

@pytest.mark.parametrize("mode,expected",[("no_trigger","NO_HALT_TRIGGER"),("skill_failure","NO_HALT_TRIGGER"),("halt_failed","HALT_FAILED"),("ineligible","INELIGIBLE")])
def test_conditional_failure_branches_never_issue_or_dispatch(phase13_grounder,tmp_path,mode,expected):
    captures=[];result,path=run_fixture(tmp_path,phase13_grounder,mode,captures=captures)
    assert result["status"]==expected
    assert result["coverage"]=="NOT_ISSUED"
    assert json.loads((path/"handoff_events.json").read_text())==[]
    assert json.loads((path/"dispatch_entries.json").read_text())==[]
    assert (path/"parent_result.json").exists() and (path/"outcome.json").exists()
    assert captures[0]["session"].closed
    assert not any(x[0].startswith("n") for x in captures[0]["session"].calls)


def test_real_gate_refusals_retain_six_requests_and_one_deliberate_fake_tick(phase13_grounder,tmp_path):
    result,path=run_fixture(tmp_path,phase13_grounder)
    assert result["status"]=="AUTHORIZATION_REFUSALS"
    requests=json.loads((path/"requests.json").read_text())
    assert [r["request"] for r in requests]==spec()["negative_requests_if_eligible_order"]
    assert all(r["result"]["status"]=="ESCALATE" for r in requests)
    assert all(r["before"]==r["after"] for r in requests)
    assert requests[1]["result"]["reason"]=="PLAN_CHANGED"
    assert requests[3]["result"]["reason"]=="PRINCIPAL_CONTINUATION_PERMISSION_MISSING"
    assert requests[4]["result"]["reason"]=="ASSESSMENT_REJECTED"
    assert json.loads((path/"stale_state_step.json").read_text())["deliberate_physics_steps"]==1
    assert json.loads((path/"dispatch_entries.json").read_text())==[]

@pytest.mark.parametrize("mode,expected",[("eligible","NEW_TASK_SUCCESS"),("child_failure","NEW_TASK_FAILED")])
def test_actual_canonical_gate_dispatch_and_child_failure_retention(phase13_grounder,tmp_path,mode,expected):
    result,path=run_fixture(tmp_path,phase13_grounder,mode,"authorized_new_mission")
    assert result["status"]==expected
    assert json.loads((path/"parent_result.json").read_text())["state"]=="FAILED"
    entries=json.loads((path/"dispatch_entries.json").read_text())
    assert len(entries)==1
    assert entries[0]["canonical_mission"] == json.loads(full_plan_json(Mission.from_dict(spec()["new_mission"])))
    assert json.loads((path/"requests.json").read_text())[-1]["result"]["reason"]=="UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF"


def test_swallowed_budget_failure_is_partial_not_scientific_failure(phase13_grounder,tmp_path):
    with pytest.raises(RuntimeError,match="BUDGET_EXCEPTION_CAPTURED"):
        run_fixture(tmp_path,phase13_grounder,"budget_swallowed")
    outcome=json.loads((tmp_path/"offline_fixture/outcome.json").read_text())
    assert outcome["status"]=="PARTIAL_STOPPED"
    assert (tmp_path/"offline_fixture/state_trace.jsonl.gz").exists()


def test_two_fake_prefixes_identical_without_observer_rng_or_extra_commands(phase13_grounder,tmp_path):
    snapshots=[]
    before=random.getstate()
    for arm in ("authorized_new_mission","authorization_refusals"):
        folder=tmp_path/arm;folder.mkdir()
        _,path=run_fixture(folder,phase13_grounder,"eligible",arm)
        snapshots.append((path/"predecision_native_trace.json").read_bytes())
    assert snapshots[0]==snapshots[1]
    assert random.getstate()==before


def test_unapproved_acquire_cannot_even_enter_preflight(monkeypatch,tmp_path):
    monkeypatch.setattr(adapter,"preflight",lambda:pytest.fail("preflight entered"))
    with pytest.raises(PermissionError,match="authorize-physics"):
        adapter.acquire(output=tmp_path/"never_created")
    assert not (tmp_path/"never_created").exists()

@pytest.mark.parametrize("which",["arm_steps","total_steps","arm_wall","total_wall"])
def test_fixed_budget_guards_before_mutation(monkeypatch,which):
    clock=[0.0];monkeypatch.setattr(adapter.time,"perf_counter",lambda:clock[0])
    b=adapter.CampaignBudget(spec());cell=spec()["run_order"][0];steps=0
    if which=="arm_steps":steps=cell["max_steps"]
    if which=="total_steps":b.native_steps=270000
    if which=="arm_wall":clock[0]=120
    if which=="total_wall":clock[0]=840;b.arm_started=clock[0]
    with pytest.raises((RuntimeError,TimeoutError)):
        b.guard(cell,steps,stepping=True)
    assert b.native_steps in {0,270000}


def test_native_push_exact_activation_and_release_without_physics():
    class Sim:
        simulation_time=0.0
        def __init__(self):self.force=np.zeros(3);self.calls=[]
        def apply_base_force(self,value):self.force[:]=value;self.calls.append(("apply",value.tolist()))
        def clear_applied_forces(self):self.force[:]=0;self.calls.append(("clear",))
        def step(self,control):self.calls.append(("step",control));return "fixture_state"
    sim=Sim();proxy=DisturbanceProxy(sim,PushSpec(60.0,(0,1,0),0.2,1.0))
    for now,force in [(0.998,0),(1.0,60),(1.198,60),(1.2,0)]:
        sim.simulation_time=now;assert proxy.step("unchanged")=="fixture_state";assert sim.force[1]==force
    assert [e["event"] for e in proxy.events]==["push_start","push_end"]
    assert sum(c[0]=="step" for c in sim.calls)==4
    sim.simulation_time=1.01;proxy.step("same");proxy.release();assert np.all(sim.force==0)


def test_write_once_and_nonfinite_negative_retention(tmp_path):
    p=tmp_path/"evidence.json";adapter.write_new(p,{"state":{"speed":float("nan")},"failure":True})
    d=json.loads(p.read_text());assert d["failure"] is True
    assert "nan" in p.read_text().lower()
    before=p.read_bytes()
    with pytest.raises(FileExistsError):adapter.write_new(p,{"replacement":True})
    assert p.read_bytes()==before


def test_external_watchdog_kills_only_dummy_blocked_process(tmp_path):
    # Child imports no simulator/policy. Exact production supervisor is exercised.
    with pytest.raises(TimeoutError):
        adapter.supervise([sys.executable,"-c","import time; print('dummy entered',flush=True); time.sleep(10)"],run_dir=tmp_path,timeout_s=0.2)
    receipt=json.loads((tmp_path/"supervisor_timeout.json").read_text())
    assert receipt["no_retry"] is True
    assert (tmp_path/"worker.log").exists()


def install_production_substitutes(monkeypatch, *, raise_on_push=False):
    """Real adapter hooks around explicit Python substitutes; no native engine."""
    import mujoco
    import g1swarm.mission as mission_package
    import g1swarm.simulation.g1_simulation as sim_module
    calls={"native_steps":0,"native_resets":0,"commands":[],"force_at_step":[]}
    def native_reset(model,data):
        calls["native_resets"]+=1;data.time=0.0
    def native_step(model,data):
        calls["native_steps"]+=1
        calls["commands"].append(data.ctrl.tolist())
        calls["force_at_step"].append(data.xfrc_applied[0,1])
        data.qpos[0]+=float(data.ctrl[0])*0.002;data.time+=0.002
    monkeypatch.setattr(mujoco,"mj_resetData",native_reset)
    monkeypatch.setattr(mujoco,"mj_step",native_step)
    monkeypatch.setattr(mujoco,"mj_resetDataKeyframe",lambda *a:pytest.fail("keyframe implementation entered"))
    class Sim:
        timestep=0.002
        def __init__(self):
            self._model=object();self._data=SimpleNamespace(qpos=np.array([0.,0.,.78,1.,0.,0.,0.,0.,0.]),qvel=np.zeros(8),ctrl=np.zeros(2),time=0.,xfrc_applied=np.zeros((1,6)));self.closed=False;self.reset()
        @property
        def simulation_time(self):return self._data.time
        def reset(self,*args,**kwargs):mujoco.mj_resetData(self._model,self._data);return self.get_robot_state()
        def get_robot_state(self):return RobotState(self._data.time,tuple(self._data.qpos[:3]),tuple(self._data.qpos[3:7]),(0.,0.,0.),(0.,0.,0.),True,False,"walk_forward")
        def apply_base_force(self,value):self._data.xfrc_applied[0,:3]=value
        def clear_applied_forces(self):self._data.xfrc_applied[:]=0
        def step(self,control=None):
            if raise_on_push and self._data.xfrc_applied[0,1]:raise RuntimeError("fixture failure while force active")
            self._data.ctrl[:]=control;mujoco.mj_step(self._model,self._data);return self.get_robot_state()
        def close(self):self.closed=True
    class Monitor:
        def __init__(self,simulation):self._simulation=simulation
        def step(self,control):return self._simulation.step(control)
        def __getattr__(self,name):return getattr(self._simulation,name)
    class Live:
        def __init__(self,robot_config,protocol,seed,simulation_wrapper):
            self.simulation=Sim();self.simulation.reset();self.current_state=self.simulation.get_robot_state();self.total_steps=0;self.wrapper=simulation_wrapper;self.controller=SimpleNamespace(_counter=0,_action=np.zeros(2),_target=np.zeros(2))
        def run_node(self,node,execution_mode):
            view=self.wrapper(Monitor(self.simulation))
            for now in (1.498,1.5,1.698,1.7):
                self.simulation._data.time=now;self.controller._counter+=1
                self.current_state=view.step(np.array([.1,.2]));self.total_steps+=1
        def run_failure_halt(self,contract):return {"status":"fixture-only"}
        def close(self):self.simulation.close()
    monkeypatch.setattr(sim_module,"G1Simulation",Sim);monkeypatch.setattr(old,"G1Simulation",Sim)
    monkeypatch.setattr(mission_package,"LiveMissionSession",Live);monkeypatch.setattr(old,"LiveMissionSession",Live)
    node=SimpleNamespace(node_id="s1",skill=SimpleNamespace(value="walk_forward"),parameters={},depends_on=[])
    return calls,Sim,Live,Monitor,node

@pytest.mark.parametrize("break_on_push",[False,True])
def test_actual_production_hook_push_timing_release_and_no_extra_step(monkeypatch,tmp_path,break_on_push):
    calls,Sim,Live,Monitor,node=install_production_substitutes(monkeypatch,raise_on_push=break_on_push)
    monkeypatch.setattr(adapter,"HERE",tmp_path)
    (tmp_path/"source_manifest.json").write_text("fixture manifest")
    science=spec();cell=next(c for c in science["run_order"] if c["state_id"]=="push60_walk6" and c["arm"]=="authorized_new_mission")
    budget=adapter.CampaignBudget(science)
    with adapter.production_backend(science,cell,tmp_path,budget) as runtime:
        session=runtime["session"];session.simulation._data.time=.5
        if break_on_push:
            with pytest.raises(RuntimeError,match="force active"):session.run_node(node,"open_loop")
        else:session.run_node(node,"open_loop")
        assert runtime["force_zero"]()
        assert calls["native_resets"]==2
        assert calls["commands"]==[[.1,.2]]*(1 if break_on_push else 4)
        assert runtime["witness"]["steps"]==calls["native_steps"]==runtime["native_count"][0]
        events=runtime["push_events"]()
        assert events[0]["sim_time"]==1.5
        assert events[-1]["event"]=="push_end"
        assert np.all(session.simulation._data.xfrc_applied==0)
        if not break_on_push:assert calls["force_at_step"]==[0.,60.,60.,0.]
    assert session.simulation.closed


def test_native_reset_rejected_before_substitute_reset_executes(monkeypatch,tmp_path):
    import mujoco
    calls,_,_,_,_=install_production_substitutes(monkeypatch)
    monkeypatch.setattr(adapter,"HERE",tmp_path);(tmp_path/"source_manifest.json").write_text("fixture manifest")
    science=spec();cell=science["run_order"][-1]
    with adapter.production_backend(science,cell,tmp_path,adapter.CampaignBudget(science)) as runtime:
        simulation=runtime["session"].simulation
        with pytest.raises(ValueError,match="NATIVE_RESET_FORBIDDEN"):mujoco.mj_resetData(simulation._model,simulation._data)
        assert calls["native_resets"]==2
        assert runtime["integrity_failure"]=="POST_INITIALIZATION_NATIVE_RESET_FORBIDDEN"


def test_parent_supervisor_resets_arm_clock_without_resetting_campaign(monkeypatch,tmp_path):
    science=spec();clock=[0.];monkeypatch.setattr(adapter.time,"perf_counter",lambda:clock[0])
    monkeypatch.setattr(adapter,"preflight",lambda:{"spec":science,"manifest_sha256":"fixture"})
    monkeypatch.setattr(adapter,"verify_readiness",lambda *a:None)
    def worker(command,*,run_dir,timeout_s):
        assert timeout_s==120
        clock[0]+=119
        adapter.write_new(run_dir/"witness.json",{"steps":0})
        adapter.write_new(run_dir/"predecision_trace.json",[])
        adapter.write_new(run_dir/"predecision_native_trace.json",[])
    monkeypatch.setattr(adapter,"supervise",worker)
    adapter.acquire(authorize_physics=True,readiness_sha256="fixture",output=tmp_path/"fake_campaign")
    r=json.loads((tmp_path/"fake_campaign/campaign_receipt.json").read_text())
    assert len(r["completed_cells"])==7 and clock[0]==833
    assert r["status"]=="ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT"


def test_abort_saves_all_planned_cells_and_never_retries(monkeypatch,tmp_path):
    science=spec();monkeypatch.setattr(adapter,"preflight",lambda:{"spec":science,"manifest_sha256":"fixture"});monkeypatch.setattr(adapter,"verify_readiness",lambda *a:None)
    calls=[]
    def worker(command,*,run_dir,timeout_s):calls.append(run_dir);raise TimeoutError("fixture blocked worker")
    monkeypatch.setattr(adapter,"supervise",worker)
    output=tmp_path/"fake_campaign"
    with pytest.raises(TimeoutError):adapter.acquire(authorize_physics=True,readiness_sha256="fixture",output=output)
    r=json.loads((output/"campaign_receipt.json").read_text());assert r["status"]=="PARTIAL_STOPPED" and len(r["frozen_planned_cells"])==7 and r["completed_cells"]==[]
    assert len(calls)==1
    with pytest.raises(FileExistsError):adapter.acquire(authorize_physics=True,readiness_sha256="fixture",output=output)
    assert len(calls)==1


def test_raw_predecision_mismatch_blocks_before_any_handoff(phase13_grounder,tmp_path):
    science=spec();cell=next(c for c in science["run_order"] if c["state_id"]=="transition_turn45_walk6" and c["arm"]=="authorization_refusals")
    path=tmp_path/"fixture";path.mkdir()
    with pytest.raises(ValueError,match="PREDECISION"):
        adapter.run_arm(science,cell,path,fake_backend(phase13_grounder),adapter.CampaignBudget(science),b"mismatch")
    assert json.loads((path/"handoff_events.json").read_text())==[]
    assert json.loads((path/"outcome.json").read_text())["status"]=="PARTIAL_STOPPED"
