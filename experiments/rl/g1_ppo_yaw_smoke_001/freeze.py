"""Nonphysical source/dependency/asset freeze; run once after implementation commit."""
import hashlib, importlib.metadata, json, os, platform, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if __name__=="__main__":
    output=Path(sys.argv[1]); prep=Path(sys.argv[2])
    if output.exists(): raise SystemExit("freeze already exists")
    if subprocess.check_output(["git","status","--porcelain","--untracked-files=no"],cwd=ROOT,text=True).strip():
        raise SystemExit("dirty source")
    paths=subprocess.check_output(["git","ls-files","src","configs/robot/g1_locomotion_12dof.yaml",
          "configs/experiments/g1_ppo_residual_t0.yaml","configs/experiments/g1_closed_loop_correction_001.yaml",
          "experiments/baselines/g1_closed_loop_correction_001/correction_comparison.json",
          "reports/g1_ppo_residual_t0","experiments/rl/g1_ppo_yaw_smoke_001","tests/test_residual_rl_smoke.py"],
          cwd=ROOT,text=True).splitlines()
    asset=json.loads((prep/"004-copied-assets.json").read_text())
    for row in asset["files"]:
        assert sha(ROOT/row["path"])==row["sha256"],row["path"]
        paths.append(row["path"])
    wheel=json.loads((prep/"python-wheel-lock.json").read_text())
    deps={d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}
    assert {n.lower().replace('_','-'):v for n,v in deps.items()}=={x["name"].lower().replace('_','-'):x["version"] for x in wheel}
    installed={}
    venv=Path(sys.prefix)
    for d in importlib.metadata.distributions():
        for f in d.files or []:
            p=Path(d.locate_file(f))
            if p.is_file() and not str(p).endswith('.pyc'):
                rel=os.path.relpath(p,venv)
                assert not rel.startswith('../'),str(p)
                installed[rel]=sha(p)
    m={"schema":"g1-t1-freeze-v1","t0_head":"e1ddd31978779365634989684579587668a56e7d",
       "execution_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
       "repository":str(ROOT),"venv":str(venv),"python":sys.version,"platform":platform.platform(),
       "python_executable_sha256":sha(Path(sys.executable).resolve()),
       "dependencies":deps,"installed_files":installed,"files":{p:sha(ROOT/p) for p in sorted(set(paths))},
       "assets":asset,"wheel_lock_sha256":sha(prep/"python-wheel-lock.json"),
       "scenario":{"case":"historical_seen_nominal4m","seed":7,"target_m":4.,"speed_mps":.5,"horizon_s":24.},
       "budgets":{"native_steps":60000,"physical_wall_s":1800,"ppo_decisions":256,"ppo_wall_s":600},
       "authorization":"Owner T1 First Real PPO Smoke task; single experiment, no retry, no efficacy claim"}
    with output.open('x') as fh: json.dump(m,fh,indent=2,sort_keys=True)
    print(json.dumps({"execution_head":m["execution_head"],"readiness_sha256":sha(output),
                      "source_and_asset_files":len(m["files"]),"installed_dependency_files":len(installed),
                      "dependencies":len(deps)}))
