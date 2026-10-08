"""One-time freeze of new heading study, preserving all earlier experiment files."""
import hashlib
import json
import subprocess
from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import write_new

if __name__ == "__main__":
    root=repo_root();directory=root/"experiments/phase3a/heading_alignment_strength_001";directory.mkdir(parents=True,exist_ok=True)
    prefixes=("experiments/phase3a/transition_learning_001/","experiments/phase3a/reference_frame_ablation_001/","experiments/phase3a/origin_selection_ablation_001/",
              "src/g1swarm/transition_learning/","src/g1swarm/reference_ablation/","src/g1swarm/origin_ablation/",
              "scripts/run_phase3a.py","scripts/freeze_phase3a.py","scripts/export_phase3a.py",
              "scripts/run_phase3a_reference.py","scripts/freeze_phase3a_reference.py","scripts/export_phase3a_reference.py",
              "scripts/run_phase3a_origin.py","scripts/freeze_phase3a_origin.py","scripts/export_phase3a_origin.py",
              "tests/test_transition_learning","tests/test_reference_ablation.py","tests/test_origin_ablation.py")
    files={}
    for name in subprocess.check_output(["git","ls-files"],cwd=root,text=True).splitlines():
        if name.startswith(prefixes):
            raw=(root/name).read_bytes();files[name]={"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
    history_path=directory/"history_freeze.json";write_new(history_path,{"source_commit":"1eb802e2ab8d0dcb0cb2a2e601fd3a955f2fbb8f","files":files})
    origin_path=root/"experiments/phase3a/origin_selection_ablation_001/protocol.json";old=json.loads(origin_path.read_text(encoding="utf-8"))
    protocol={"experiment_id":"heading_alignment_strength_001","source_origin_commit":"1eb802e2ab8d0dcb0cb2a2e601fd3a955f2fbb8f",
        "factor":"heading alignment strength at fixed actual node-start origin","fixed_alphas":[0.0,0.5,1.0],
        "modes":{"actual_node_start":0.0,"midpoint_heading":0.5,"actual_origin_ideal_heading":1.0},
        "interpolation":"theta_ref=wrap(theta_actual+alpha*wrap(theta_commanded-theta_actual));wrap=atan2(sin,cos);exact old endpoint recipes at0/1 preservefloatidentity; midpoint finalangle normalized",
        "frame_scope":"Selected blended frame rotates both heading/lateral error axes;gains remain1.5/1.0;origin and local measurement frame stayactualnode-start",
        "no_alpha_search":True,"reject_other_alphas":True,
        "base_policy_sha256":old["base_policy_sha256"],"case_manifest_sha256":old["case_manifest_sha256"],
        "inherited_reference_protocol_sha256":old["inherited_reference_protocol_sha256"],
        "history_manifest_sha256":hashlib.sha256(history_path.read_bytes()).hexdigest(),
        "training_hypothesis_gate":old["training_hypothesis_gate"],"candidate_for_inherited_gate":"midpoint_heading alpha0.5;all criterion/threshold unchanged",
        "frozen_controls":old["frozen_controls"],"measurement_frame":old["measurement_frame"],
        "primary":"Same26cases peralpha,78total;16transitions8primitives2sequences",
        "repeatability":"Separate identical secondpass78;notpooled or independent samples",
        "data_scope":"Previouslyseen mechanismcases;no freshblindgeneralization",
        "PPO_reward_observation_network_bounds_window_budget":"All previoussources/config held;residualoff;no training in thisstudy",
        "residual_enabled":False,"PPO_training":False,"no_outcome_retry":True,"torch_threads":1,
        "language_Runtime_gate":"BLOCKED_UNCHANGED","Jev_or_MultiSwarm":False,"frozen":True}
    write_new(directory/"protocol.json",protocol)
    print(json.dumps({"historical_files":len(files),"protocol_sha256":hashlib.sha256((directory/"protocol.json").read_bytes()).hexdigest()}))
