"""Interpolate only the correction frame heading, at actual node-start origin."""
from __future__ import annotations
import gzip
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess

import torch

from ..paths import repo_root,resolve_repo_path
from ..segmentation.mission import MissionFrame
from ..origin_ablation.experiment import OriginCorrectionPolicy,OriginRunner,verify_history as verify_origin_history
from ..reference_ablation.experiment import canonical_physics,compare_reference_records,sha,write_new
from ..transition_learning.cases import EVAL_CASES,PRIMITIVE_CASES,SEQUENCE_CASES
from ..transition_learning.analysis import summarize_results

ALPHAS=(0.0,0.5,1.0)
MODE_BY_ALPHA={0.0:"actual_node_start",0.5:"midpoint_heading",1.0:"actual_origin_ideal_heading"}
DIRECTORY="experiments/phase3a/heading_alignment_strength_001"
ORIGIN="experiments/phase3a/origin_selection_ablation_001"
REFERENCE="experiments/phase3a/reference_frame_ablation_001"
PILOT="experiments/phase3a/transition_learning_001"


def validate_alpha(alpha):
    if isinstance(alpha,bool):
        raise ValueError("Only fixed numeric alpha0,0.5,1 is allowed")
    try:value=float(alpha)
    except (ValueError,TypeError):raise ValueError("Only fixed numeric alpha0,0.5,1 is allowed") from None
    if not math.isfinite(value) or value not in ALPHAS:
        raise ValueError("Only predeclared alpha0,0.5,1 is allowed; no search")
    return value


def wrap(angle):
    return math.atan2(math.sin(angle),math.cos(angle))


class HeadingCorrectionPolicy(OriginCorrectionPolicy):
    def __init__(self,runner,alpha,delegate):
        self.alpha=validate_alpha(alpha)
        super().__init__(runner,"actual_origin_ideal_heading" if self.alpha==1.0 else "actual_node_start",delegate)
        self.reference_mode=MODE_BY_ALPHA[self.alpha]

    def selected_frame(self,local_frame):
        if self.alpha==0.0:
            return local_frame  # preserve exact historical endpoint recipe
        if self.alpha==1.0:
            heading=float(self.runner.planned_heading)  # preserve exact hybrid recipe
        else:
            heading=wrap(local_frame.initial_yaw_rad+self.alpha*wrap(
                float(self.runner.planned_heading)-local_frame.initial_yaw_rad))
        return MissionFrame(initial_position=local_frame.initial_position,initial_yaw_rad=heading)


class HeadingRunner(OriginRunner):
    def __init__(self,case,alpha,trace_path=None):
        self.alpha=validate_alpha(alpha)
        super().__init__(case,"actual_origin_ideal_heading" if self.alpha==1.0 else "actual_node_start",trace_path)
        self.reference_mode=MODE_BY_ALPHA[self.alpha]
        self.correction=HeadingCorrectionPolicy(self,self.alpha,self.correction.delegate)

    def run(self):
        record=super().run()
        record["heading_alignment_alpha"]=self.alpha
        return record


def replay_heading(case,alpha,trace_path=None):
    runner=HeadingRunner(case,alpha,trace_path)
    try:return runner.run()
    finally:runner.close()


def canonical_alignment(value):
    if isinstance(value,dict):value={k:canonical_alignment(v) for k,v in value.items() if k!="heading_alignment_alpha"}
    elif isinstance(value,list):value=[canonical_alignment(v) for v in value]
    return canonical_physics(value)


def verify_history():
    checks=verify_origin_history()
    path=repo_root()/DIRECTORY/"history_freeze.json"
    pins=json.loads(path.read_text(encoding="utf-8"));failures=[]
    for relative,expected in pins["files"].items():
        source=repo_root()/relative
        if not source.is_file() or sha(source)!=expected["sha256"] or source.stat().st_size!=expected["bytes"]:
            failures.append(relative)
    if failures:raise RuntimeError(f"Historical files changed: {failures}")
    checks.update(all_heading_history_files_verified=len(pins["files"]),
                  heading_history_manifest_sha256=sha(path),historical_drift=False)
    return checks


def run_campaign(output_dir,protocol_path=DIRECTORY+"/protocol.json"):
    root=repo_root();path=resolve_repo_path(protocol_path)
    protocol=json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("frozen") is not True or tuple(protocol["fixed_alphas"])!=ALPHAS:
        raise ValueError("Frozen fixed-alpha protocol required")
    history=verify_history()
    if history["heading_history_manifest_sha256"]!=protocol["history_manifest_sha256"]:
        raise RuntimeError("Historical pin changed")
    case_path=root/PILOT/"case_manifest.json"
    if sha(case_path)!=protocol["case_manifest_sha256"]:raise RuntimeError("Cases changed")
    gate_path=root/REFERENCE/"protocol.json";old=json.loads(gate_path.read_text(encoding="utf-8"))
    if sha(gate_path)!=protocol["inherited_reference_protocol_sha256"] or old["training_hypothesis_gate"]!=protocol["training_hypothesis_gate"]:
        raise RuntimeError("Inherited gate changed")
    output=resolve_repo_path(output_dir);output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    provenance={"code_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),
        "protocol_sha256":sha(path),"case_manifest_sha256":sha(case_path),"history_manifest_sha256":history["heading_history_manifest_sha256"],
        "inherited_reference_protocol_sha256":sha(gate_path),"baseline_freeze_sha256":history["baseline"]["baseline_freeze_sha256"],
        "base_policy_sha256":protocol["base_policy_sha256"],
        "source_hashes":{p.relative_to(root).as_posix():sha(p) for p in sorted([*Path(__file__).parent.glob("*.py"),root/"scripts/run_phase3a_heading.py"])},
        "packages":{n:importlib.metadata.version(n) for n in ["torch","numpy","mujoco","gymnasium","stable-baselines3"]},
        "device":"cpu","torch_threads":1,"residual_enabled":False,"PPO_training":False,"language_Runtime":False,"Jev":False}
    write_new(output/"manifest.json",{"protocol":protocol,"provenance":provenance,"history_before":history})
    prior_rows=[json.loads(x) for x in gzip.decompress((root/ORIGIN/"evidence/results.jsonl.gz").read_bytes()).decode().splitlines()]
    prior={(r["case_id"],r["reference_mode"]):r for r in prior_rows if r["phase"]=="primary"}
    case_sets=[("unseen_transition",EVAL_CASES),("primitive_regression",PRIMITIVE_CASES),("unseen_sequence",SEQUENCE_CASES)]
    records=[];anchor_checks=[]
    try:
        for repetition,phase in [(0,"primary"),(1,"repeatability")]:
            for alpha in ALPHAS:
                mode=MODE_BY_ALPHA[alpha]
                for evaluation_set,collection in case_sets:
                    for case in collection:
                        trace=output/"traces"/(f"{phase}--{mode}--{case['id']}.jsonl")
                        record=replay_heading(case,alpha,trace)
                        record.update(phase=phase,repetition=repetition,evaluation_set=evaluation_set,provenance=provenance)
                        records.append(record)
                        with (output/"results.jsonl").open("a",encoding="utf-8",newline="\n") as handle:handle.write(json.dumps(record,allow_nan=False)+"\n")
                        if alpha in (0.0,1.0):
                            identical=canonical_alignment(record)==canonical_alignment(prior[(case["id"],mode)])
                            anchor_checks.append({"case_id":case["id"],"phase":phase,"alpha":alpha,"passed":identical})
                            if not identical:raise RuntimeError(f"Historical alpha endpoint changed: {alpha}/{case['id']}")
        primary=[r for r in records if r["phase"]=="primary"];repeat=[r for r in records if r["phase"]=="repeatability"]
        index={(r["case_id"],r["reference_mode"]):r for r in primary}
        repeat_checks=[{"case_id":r["case_id"],"alpha":r["heading_alignment_alpha"],
            "passed":canonical_alignment(r)==canonical_alignment(index[(r["case_id"],r["reference_mode"])])} for r in repeat]
        if not all(x["passed"] for x in repeat_checks):raise RuntimeError("Repeatability failed")
        after=verify_history()
        if sha(path)!=provenance["protocol_sha256"]:raise RuntimeError("Protocol changed")
        write_new(output/"summary.json",summarize_results(primary))
        write_new(output/"comparison.json",compare_reference_records(primary))
        write_new(output/"completion.json",{"status":"COMPLETE","records":len(records),"primary_runs":len(primary),"repeatability_runs":len(repeat),
            "history_after":after,"anchor_identity":anchor_checks,"repeatability_identity":repeat_checks,"provenance":provenance})
        return {"status":"COMPLETE","primary_runs":len(primary),"repeatability_runs":len(repeat)}
    except Exception as exc:
        write_new(output/"failure.json",{"status":"FAILED","completed_records":len(records),"exception":type(exc).__name__,"message":str(exc),"provenance":provenance})
        raise
