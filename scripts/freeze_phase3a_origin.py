"""Create only the new origin experiment's prior-evidence and protocol pins."""
import hashlib
import json
import subprocess
from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import write_new

if __name__ == "__main__":
    root=repo_root();directory=root/"experiments/phase3a/origin_selection_ablation_001"
    directory.mkdir(parents=True,exist_ok=True)
    prefixes=("experiments/phase3a/transition_learning_001/","experiments/phase3a/reference_frame_ablation_001/",
              "src/g1swarm/transition_learning/","src/g1swarm/reference_ablation/",
              "scripts/run_phase3a.py","scripts/freeze_phase3a.py","scripts/export_phase3a.py",
              "scripts/run_phase3a_reference.py","scripts/freeze_phase3a_reference.py","scripts/export_phase3a_reference.py",
              "tests/test_transition_learning","tests/test_reference_ablation.py")
    files={}
    for name in subprocess.check_output(["git","ls-files"],cwd=root,text=True).splitlines():
        if name.startswith(prefixes):
            raw=(root/name).read_bytes();files[name]={"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
    history_path=directory/"history_freeze.json"
    write_new(history_path,{"source_commit":"642dcc123fa721b16ff50c3bb2007e21d0c53077","files":files})
    old_path=root/"experiments/phase3a/reference_frame_ablation_001/protocol.json"
    old=json.loads(old_path.read_text(encoding="utf-8"))
    protocol={"experiment_id":"origin_selection_ablation_001","source_reference_commit":"642dcc123fa721b16ff50c3bb2007e21d0c53077",
        "factor":"correction origin selection conditional on fixed ideal commanded heading",
        "treatments":{"actual_node_start":"actual-origin actual-heading historical gate anchor",
                      "actual_origin_ideal_heading":"actual node-start origin, ideal commanded heading",
                      "ideal_commanded_axis":"planned origin, ideal commanded heading retained full-ideal"},
        "factor_scope":"Hybrid versus full isolates origin at ideal heading; hybrid versus historical anchor isolates heading at actual origin. Three arms do not establish a full2x2 interaction.",
        "base_policy_sha256":old["base_policy_sha256"],"case_manifest_sha256":old["case_manifest_sha256"],
        "inherited_reference_protocol_sha256":hashlib.sha256(old_path.read_bytes()).hexdigest(),
        "history_manifest_sha256":hashlib.sha256(history_path.read_bytes()).hexdigest(),
        "training_hypothesis_gate":old["training_hypothesis_gate"],
        "candidate_for_inherited_gate":"actual_origin_ideal_heading; criterion and all old task thresholds unchanged",
        "primary":"Same26 cases perarm,78 total;16transitions,8primitives,2sequences",
        "repeatability":"Separate identical second pass78;not pooled or treated as independent samples",
        "data_scope":"Previously seen diagnostic/mechanism cases;no new blind generalization claim",
        "frozen_controls":old["frozen_controls"],"measurement_frame":old["measurement_frame"],
        "PPO_reward_observation_network_bounds_window_budget":"Unmodified retained pilot source/config;residualoff,no PPO training",
        "residual_enabled":False,"PPO_training":False,"no_outcome_retry":True,
        "torch_threads":1,"language_Runtime_gate":"BLOCKED_UNCHANGED","Jev_or_MultiSwarm":False,"frozen":True}
    write_new(directory/"protocol.json",protocol)
    print(json.dumps({"historical_files":len(files),"protocol_sha256":hashlib.sha256((directory/"protocol.json").read_bytes()).hexdigest()}))
