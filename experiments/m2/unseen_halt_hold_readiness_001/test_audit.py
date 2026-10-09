"""Synthetic and sealed-byte tests only; never execute a simulator or policy."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("m26_raw_audit_test", HERE / "audit.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
SPEC = A.read_json(A.DESIGN / "protocol.json")


def snapshot(n=0, speed=.05, y=0.):
    return {"time_s": n*.002, "qpos": [n*.0001,y,.8,1.,0.,0.,0.] + [0.]*12,
            "qvel": [speed,0.,0.,0.,0.,0.] + [0.]*12, "ctrl": [0.]*12,
            "xfrc_applied": [[0.]*6], "controller_action": [0.]*12,
            "controller_target": [0.]*12, "controller_counter": n,
            "session_identity": 1, "simulation_identity": 2, "controller_identity": 3,
            "policy_identity": 4, "reset_calls": 2, "native_reset_calls": 2,
            "keyframe_reset_calls": 0, "controller_reset_calls": 1,
            "node_dispatches": 1, "executor_dispatches": 1, "native_steps": n, "session_steps": n}


def raw(n, speed=.05, phase="parent"):
    s=snapshot(n,speed)
    return {"sequence":n,"phase":phase,**A._snapshot_raw(s),"raw_finite":True}


def test_hold_recomputed_not_label_and_all_windows():
    entry=snapshot(500)
    native=[raw(n,phase="hold") for n in range(501,1501)]
    journal=[{"hold_step":i,"native_sequence":r["sequence"],"command_xyz_mps_radps":[0.,0.,0.]} for i,r in enumerate(native,1)]
    scored=A.hold_score(entry,native,journal,[.05]*500,SPEC)
    assert scored["status"]=="HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"
    assert len(scored["rolling_means"])==1000
    native[-1]["qvel"][0]=.2
    assert A.hold_score(entry,native,journal,[.05]*500,SPEC)["status"]=="HOLD_FAILED"


@pytest.mark.parametrize("mutation",["command","counter","force","time"])
def test_hold_integrity_rejects_command_reset_force_time(mutation):
    native=[raw(n,phase="hold") for n in range(501,1501)]
    logs=[{"hold_step":i,"native_sequence":r["sequence"],"command_xyz_mps_radps":[0.,0.,0.]} for i,r in enumerate(native,1)]
    if mutation=="command": logs[1]["command_xyz_mps_radps"][0]=.01
    if mutation=="counter": native[1]["controller"]["_counter"] =0
    if mutation=="force": native[1]["xfrc_applied"][0][1]=1.
    if mutation=="time": native[1]["time_s"]+=.002
    with pytest.raises(A.EvidenceError): A.hold_score(snapshot(500),native,logs,[.05]*500,SPEC)


def test_first_crossing_not_later_cherry_pick():
    score=A.stop_score(snapshot(),[raw(n) for n in range(1,501)],"SUCCESS",SPEC)
    assert score["first_crossing_step"]==500
    with pytest.raises(A.EvidenceError,match="CONTINUED_AFTER"):
        A.stop_score(snapshot(),[raw(n) for n in range(1,502)],"SUCCESS",SPEC)


def test_instantaneous_stop_failure_independent_of_mean():
    rows=[raw(n) for n in range(1,501)]
    rows[-1]["qvel"][0]=.15
    score=A.stop_score(snapshot(),rows,"SUCCESS",SPEC)
    assert score["first_crossing_step"]==500 and score["status"]=="FAILED"


def test_timeout_without_crossing_is_real_negative():
    score=A.stop_score(snapshot(),[raw(n,speed=.2) for n in range(1,2001)],"TIMEOUT",SPEC)
    assert score["status"]=="FAILED" and score["first_crossing_step"] is None


def test_hold_missing_is_technical_not_physical_and_unsafe_is_failure():
    rows=[raw(501,phase="hold")]
    logs=[{"hold_step":1,"native_sequence":501,"command_xyz_mps_radps":[0.,0.,0.]}]
    assert A.hold_score(snapshot(500),rows,logs,[.05]*500,SPEC)["status"]=="TECHNICAL_PARTIAL"
    rows[0]["qpos"][2]=.3
    assert A.hold_score(snapshot(500),rows,logs,[.05]*500,SPEC)["status"]=="HOLD_FAILED"


def test_endpoint_strict_projection_no_trigger_and_failure():
    a=snapshot(); b=snapshot(1000)
    b["qpos"][0]=6.
    assert A.strict_walk(a,b,6.,"SUCCESS",[raw(1)])["branch"]=="STRICT_PASS_NO_HALT"
    b["qpos"][1]=-.4
    assert A.strict_walk(a,b,6.,"SUCCESS",[raw(1)])["branch"]=="STRICT_TRIGGER"
    assert A.strict_walk(a,b,6.,"TIMEOUT",[raw(1)])["branch"]=="SKILL_OR_PHYSICAL_FAILURE_NO_HALT"


@pytest.mark.parametrize("cid",["unseen_minus_y_early","unseen_minus_y_late","unseen_plus_y_late_partner"])
def test_exact_stimulus_native_windows_clearance(cid):
    cell=next(c for c in SPEC["cells_in_order"] if c["id"]==cid)
    rows=[raw(n) for n in range(1,2201)]
    force=[]
    for r in rows:
        expected=list(A.GEOMETRY.force_at_pre_step(cell["push"],r["sequence"]-1))
        r["xfrc_applied"][0][:3]=expected
        force.append({"sequence_next":r["sequence"],"pre_time_s":(r["sequence"]-1)*.002,
                      "first_walk_pre_index":r["sequence"]-1,"force_vector":expected,
                      "body_index":0,"body_name":"pelvis","xfrc_before":deepcopy(r["xfrc_applied"])})
    assert A.force_audit(rows,force,cell,0,len(rows))["observed_nonzero_intervals"]==100
    force[10]["force_vector"]=[0.,-60.,0.]
    with pytest.raises(A.EvidenceError): A.force_audit(rows,force,cell,0,len(rows))


def test_prepulse_comparator_not_just_endpoint():
    left=[raw(n) for n in range(1,501)]; right=deepcopy(left)
    assert A.raw_prefix(left,right,500)["matched_poststeps"]==500
    right[20]["qvel"][1]=.000001
    with pytest.raises(A.EvidenceError,match="PREFIX_MISMATCH"): A.raw_prefix(left,right,500)


def matrix():
    return [{"cell_id":c["id"],"status":"VALID","parent_branch":"STRICT_TRIGGER",
             "halt":"SUCCEEDED","hold":"SUCCEEDED","request_distinct":True,
             "hold_entry_distinct":True,"distinct_from_other_primary":True} for c in SPEC["cells_in_order"]]


def test_denominators_exclude_normal_and_preserve_n_a():
    rows=matrix()
    for r in rows: r.update(parent_branch="STRICT_PASS_NO_HALT",halt="NOT_REQUESTED",hold="NOT_RUN")
    rows[-1].update(parent_branch="NORMAL_STOP",hold="SUCCEEDED")
    score=A.campaign_score(rows,SPEC)
    assert score["halt_success_fraction"] is None and score["failure_chain_halt_denominator"]==0


def test_alias_negative_retained_counterexample_survives_technical_partial():
    rows=matrix(); rows[1]["hold"]="FAILED"; rows[2]["status"]="TECHNICAL_PARTIAL"
    score=A.campaign_score(rows,SPEC)
    assert score["scientific_signal"]=="BOUNDED_UNSEEN_COUNTEREXAMPLE" and score["campaign_completion"]=="PARTIAL"
    rows[1]["hold_entry_distinct"]=False
    score=A.campaign_score(rows,SPEC)
    assert score["condition_negatives_not_distinct"]==[rows[1]["cell_id"]]


def test_global_xy_yaw_not_new_state():
    s=snapshot(); t=deepcopy(s)
    t["qpos"][:2]=[100.,200.]
    t["qpos"][3:7]=[0.,0.,0.,1.]
    t["qvel"][0]=-.05
    result=A.GEOMETRY.state_difference(s,t,SPEC["state_distinctness"]["features"])
    assert not result["operationally_distinct"]


def zip_fixture(tmp_path,name="folder/raw.json"):
    archive=tmp_path/"raw.zip"; value=b'{"original":true}\n'
    with zipfile.ZipFile(archive,"w") as z: z.writestr(name,value)
    manifest={"archive":{"sha256":A.digest(archive)},"files":{name:{"bytes":len(value),"sha256":hashlib.sha256(value).hexdigest()}}}
    return archive,manifest


def test_archive_clean_restore_and_existing_target_rejected(tmp_path):
    archive,manifest=zip_fixture(tmp_path)
    target=tmp_path/"clean"
    receipt=A.restore_archive(archive,manifest,target)
    assert receipt["files"]==1
    with pytest.raises(A.EvidenceError): A.restore_archive(archive,manifest,target)


@pytest.mark.parametrize("name",["../escape","/absolute","C:/escape","bad\\escape"])
def test_archive_unsafe_members_rejected_before_output(tmp_path,name):
    archive,manifest=zip_fixture(tmp_path,name)
    with pytest.raises(A.EvidenceError): A.restore_archive(archive,manifest,tmp_path/"clean")
    assert not (tmp_path/"clean").exists()


def test_member_hash_mismatch_no_restore(tmp_path):
    archive,manifest=zip_fixture(tmp_path)
    manifest["files"]["folder/raw.json"]["sha256"]="0"*64
    with pytest.raises(A.EvidenceError): A.restore_archive(archive,manifest,tmp_path/"clean")
    assert not (tmp_path/"clean").exists()


def test_sealed_m25_three_reference_native_bytes():
    historical=A.historical_m25()
    assert len(historical)==3
    for ref in historical.values():
        assert len(ref["request"]["qpos"])==19
        assert len(ref["terminal"]["qvel"])==18
        assert len(ref["native_sha256"])==64


def dump(path,value):
    path.write_text(json.dumps(value)+"\n",encoding="utf8")


def lines(path,value):
    path.write_text("".join(json.dumps(row)+"\n" for row in value),encoding="utf8")


def full_cell(folder):
    folder.mkdir()
    cell=SPEC["cells_in_order"][0]
    snapshots=[]
    for n in range(2501):
        s=snapshot(n)
        if n <=1000:
            s["qpos"][0]=n*.006
            s["qpos"][1]=n*(-.0004)
        else:
            s["qpos"][0]=6.+(n-1000)*.0001
            s["qpos"][1]=-.4
        snapshots.append(s)
    native=[{"sequence":n,"phase":"parent" if n<=1500 else "hold",**A._snapshot_raw(s),"raw_finite":True}
            for n,s in enumerate(snapshots) if n]
    forces=[{"sequence_next":r["sequence"],"pre_time_s":(r["sequence"]-1)*.002,
             "first_walk_pre_index":r["sequence"]-1 if r["sequence"]<=1000 else None,
             "force_vector":[0.,0.,0.],"body_index":0,"body_name":"pelvis","xfrc_before":[[0.]*6]} for r in native]
    events=[{"event":"first_walk_start","snapshot":snapshots[0]},
            {"event":"first_walk_end","snapshot":snapshots[1000],"skill_status":"SUCCESS"},
            {"event":"halt_request","snapshot":snapshots[1000]},
            {"event":"stop_start","snapshot":snapshots[1000]},
            {"event":"stop_return","snapshot":snapshots[1500],"status":"SUCCESS"}]
    commands=[{"sequence_next":r["sequence"],"phase":r["phase"],
               "command_xyz_mps_radps":[.5,0.,0.] if r["sequence"]<=1000 else [0.,0.,0.]} for r in native]
    logs=[{"hold_step":i,"native_sequence":1500+i,"command_xyz_mps_radps":[0.,0.,0.]} for i in range(1,1001)]
    lines(folder/"native_incremental.jsonl",native)
    lines(folder/"force_incremental.jsonl",forces)
    lines(folder/"lifecycle_events.jsonl",events)
    lines(folder/"command_incremental.jsonl",commands)
    lines(folder/"hold_incremental.jsonl",logs)
    dump(folder/"witness.json",{"attempt":1,"native_steps":2500,"reset_calls":2,"native_reset_calls":2,
                               "keyframe_reset_calls":0,"final_snapshot":snapshots[-1]})
    dump(folder/"outcome.json",{"status":"HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"})
    dump(folder/"hold_entry.json",{"pre_first_step":snapshots[1500]})
    dump(folder/"cell_wall_receipt.json",{"wall_started_monotonic_s":100., "wall_ended_monotonic_s":110., "wall_elapsed_s":10.})
    dump(folder/"supervisor_receipt.json",{"wall_started_monotonic_s":100., "wall_ended_monotonic_s":109., "wall_elapsed_s":9., "allocated_wall_bound_s":120.})
    return cell


def test_full_raw_artifact_classification_ignores_saved_success(tmp_path):
    folder=tmp_path/"raw"; cell=full_cell(folder)
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="PASS_RECOMPUTED",result
    assert result["parent_branch"]=="STRICT_TRIGGER" and result["halt"]==result["hold"]=="SUCCEEDED"
    data=A.read_json(folder/"outcome.json");data["status"]="TECHNICAL_PARTIAL";dump(folder/"outcome.json",data)
    result=A.audit_cell(folder,SPEC,cell)
    assert result["hold"]=="SUCCEEDED" and result["completion_status"]=="TECHNICAL_PARTIAL"


@pytest.mark.parametrize("mutation",["reset","force","routing","command"])
def test_full_raw_corruption_cannot_supply_success(tmp_path,mutation):
    folder=tmp_path/"raw";cell=full_cell(folder)
    if mutation=="reset":
        data=A.read_json(folder/"witness.json");data["final_snapshot"]["controller_reset_calls"]+=1;dump(folder/"witness.json",data)
    if mutation=="force":
        data=A.read_jsonl(folder/"force_incremental.jsonl");data[10]["force_vector"]=[0.,60.,0.];lines(folder/"force_incremental.jsonl",data)
    if mutation=="routing":
        data=A.read_jsonl(folder/"lifecycle_events.jsonl");data=[r for r in data if r["event"]!="halt_request"];lines(folder/"lifecycle_events.jsonl",data)
    if mutation=="command":
        data=A.read_jsonl(folder/"command_incremental.jsonl");data[-1]["command_xyz_mps_radps"]=[.1,0.,0.];lines(folder/"command_incremental.jsonl",data)
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="INTEGRITY_FAILURE" and result["scientific_status"] is None,result


def test_truncated_journal_preserves_prefix_and_unknown_inflight(tmp_path):
    path=tmp_path/"partial.jsonl"
    path.write_text('{"sequence":1}\n{"sequence":',encoding="utf8")
    result=A.journal_coverage(path)
    assert result["complete_rows"]==1 and result["truncated_or_invalid_tail"]
    assert result["inflight_physics_step_count"]=="UNKNOWN"


@pytest.mark.parametrize("change",["elapsed","overrun","nonfinite"])
def test_wall_budget_receipt_cannot_be_falsely_passed(change):
    value={"wall_started_monotonic_s":100.,"wall_ended_monotonic_s":110.,"wall_elapsed_s":10.}
    if change=="elapsed": value["wall_elapsed_s"]=9.
    if change=="overrun": value.update(wall_ended_monotonic_s=221.,wall_elapsed_s=121.)
    if change=="nonfinite": value["wall_elapsed_s"]=float("nan")
    with pytest.raises(A.EvidenceError): A.wall_receipt(value,120.,"test")


def test_fallen_low_speed_terminal_does_not_invent_first_crossing():
    native=[raw(n) for n in range(1,501)]
    native[-1]["qpos"][2]=.3
    scored=A.stop_score(snapshot(),native,"UNSAFE",SPEC)
    assert scored["status"]=="FAILED" and scored["first_crossing_step"] is None
    bad_entry=snapshot();bad_entry["qpos"][2]=.5
    assert A.stop_score(bad_entry,[raw(n) for n in range(1,501)],"SUCCESS",SPEC)["status"]=="FAILED"


def test_full_raw_valid_hold_failure_then_technical_completion_preserved(tmp_path):
    folder=tmp_path/"raw";cell=full_cell(folder)
    native=A.read_jsonl(folder/"native_incremental.jsonl")
    native[-1]["qvel"][0]=.2
    lines(folder/"native_incremental.jsonl",native)
    witness=A.read_json(folder/"witness.json")
    witness["final_snapshot"]["qvel"][0]=.2
    dump(folder/"witness.json",witness)
    dump(folder/"outcome.json",{"status":"TECHNICAL_PARTIAL","exception":"saved after raw Hold completion"})
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="PASS_RECOMPUTED" and result["hold"]=="FAILED",result
    assert result["completion_status"]=="TECHNICAL_PARTIAL"
    rows=matrix(); rows[1].update(hold="FAILED",completion_status="TECHNICAL_PARTIAL")
    score=A.campaign_score(rows,SPEC)
    assert score["scientific_signal"]=="BOUNDED_UNSEEN_COUNTEREXAMPLE" and score["campaign_completion"]=="PARTIAL"


def test_full_raw_interruption_after_halt_before_stop_return_cannot_pass(tmp_path):
    folder=tmp_path/"raw";cell=full_cell(folder)
    events=A.read_jsonl(folder/"lifecycle_events.jsonl")
    lines(folder/"lifecycle_events.jsonl",[e for e in events if e["event"]!="stop_return"])
    dump(folder/"outcome.json",{"status":"TECHNICAL_PARTIAL"})
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="MISSING_EVIDENCE" and result["scientific_status"] is None


def test_source_readiness_overlapping_hash_cannot_override(tmp_path):
    (tmp_path/"code.py").write_bytes(b"frozen bytes")
    sha=A.digest(tmp_path/"code.py")
    A.verify_byte_maps({"code.py":sha},{"code.py":sha},root=tmp_path)
    with pytest.raises(A.EvidenceError,match="FREEZE_MAP_CONFLICT"):
        A.verify_byte_maps({"code.py":"0"*64},{"code.py":sha},root=tmp_path)


def test_source_map_escape_cannot_bind_outside_checkout(tmp_path):
    with pytest.raises(A.EvidenceError,match="SOURCE_OR_ASSET"):
        A.verify_byte_maps({"../outside":"0"*64},{},root=tmp_path)


def test_normal_parent_failure_without_stop_is_valid_missing_coverage(tmp_path):
    folder=tmp_path/"raw";full_cell(folder)
    cell=SPEC["cells_in_order"][-1]
    rows=A.read_jsonl(folder/"native_incremental.jsonl")[:1000]
    lines(folder/"native_incremental.jsonl",rows)
    lines(folder/"force_incremental.jsonl",A.read_jsonl(folder/"force_incremental.jsonl")[:1000])
    lines(folder/"command_incremental.jsonl",A.read_jsonl(folder/"command_incremental.jsonl")[:1000])
    events=A.read_jsonl(folder/"lifecycle_events.jsonl")[:2]
    events[-1]["skill_status"]="TIMEOUT"
    lines(folder/"lifecycle_events.jsonl",events)
    witness=A.read_json(folder/"witness.json");witness["native_steps"]=1000;dump(folder/"witness.json",witness)
    dump(folder/"parent_result.json",{"mission_success":False,"physical_success":True,"completed_nodes":0,"failure_type":"TIMEOUT"})
    dump(folder/"outcome.json",{"status":"CONTROL_FAILED_NO_HOLD"})
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="PASS_RECOMPUTED" and result["parent_branch"]=="NORMAL_CONTROL_FAILED_NO_HOLD",result
    assert result["halt"]=="NOT_REQUESTED" and result["hold"]=="NOT_RUN"


def test_nonfinite_halt_native_exit_without_stop_return_is_physical_negative(tmp_path):
    folder=tmp_path/"raw";cell=full_cell(folder)
    native=A.read_jsonl(folder/"native_incremental.jsonl")[:1001]
    native[-1]["qvel"][0]={"nonfinite":"nan"}
    native[-1]["raw_finite"]=False
    lines(folder/"native_incremental.jsonl",native)
    lines(folder/"force_incremental.jsonl",A.read_jsonl(folder/"force_incremental.jsonl")[:1001])
    lines(folder/"command_incremental.jsonl",A.read_jsonl(folder/"command_incremental.jsonl")[:1001])
    lines(folder/"lifecycle_events.jsonl",A.read_jsonl(folder/"lifecycle_events.jsonl")[:4])
    witness=A.read_json(folder/"witness.json");witness["native_steps"]=1001;witness["final_snapshot"]=None
    dump(folder/"witness.json",witness)
    dump(folder/"outcome.json",{"status":"HALT_FAILED_NO_HOLD"})
    result=A.audit_cell(folder,SPEC,cell)
    assert result["audit_status"]=="PASS_RECOMPUTED" and result["halt"]=="FAILED",result
    assert result["hold"]=="NOT_RUN" and "WITHOUT_STOP_RETURN" in result["terminal_coverage"]


def test_nonfinite_terminal_novelty_unavailable_keeps_request_evidence():
    state=snapshot();state["qpos"][7]=.2
    terminal=deepcopy(state);terminal["qvel"][0]={"nonfinite":"nan"}
    row={"cell_id":"unseen_minus_y_early","status":"VALID","halt":"FAILED",
         "request_snapshot":state,"terminal_snapshot":terminal}
    hist={name:{"request":snapshot(),"terminal":snapshot()} for name in ("seen","turn","normal")}
    A.state_distinctness([row],hist,SPEC)
    assert row["request_distinct"] and not row["hold_entry_distinct"]
    assert all(p["coverage"]=="PHYSICAL_DESCRIPTOR_UNAVAILABLE" for p in row["distinctness_pairs"]["terminal_snapshot"].values())


def test_hardkill_missing_witness_returns_partial_raw_inventory(tmp_path,monkeypatch):
    folder=tmp_path/"campaign";folder.mkdir()
    first=SPEC["cells_in_order"][0]["id"]
    cell=folder/first;cell.mkdir()
    lines(cell/"native_incremental.jsonl",[raw(1)])
    dump(folder/"campaign_receipt.json",{"status":"PARTIAL_STOPPED", "wall_started_monotonic_s":100.,
         "wall_ended_monotonic_s":101.,"wall_elapsed_s":1.,"frozen_budget":SPEC["budget"],
         "readiness_sha256":"expected","source_manifest_sha256":"source", "protocol_sha256":A.digest(A.DESIGN/"protocol.json")})
    monkeypatch.setattr(A,"verify_sources",lambda *args,**kwargs: {"source_manifest_sha256":"source"})
    result=A.audit_campaign(folder,historical={},readiness_sha256="expected")
    assert result["decision"]["campaign_completion"]=="PARTIAL"
    assert result["native_steps"]==1 and result["missing_cell_source_witnesses"]==[first]
    assert result["cells"][0]["audit_status"]=="MISSING_EVIDENCE"
    assert result["native_journal_coverage"][first]["inflight_physics_step_count"]=="UNKNOWN"
