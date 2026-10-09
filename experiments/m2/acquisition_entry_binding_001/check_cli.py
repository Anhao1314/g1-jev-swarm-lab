"""Final clean-process acceptance with live-import tripwires, never a live run."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[2]
LAUNCHER = """
import importlib.abc,json,runpy,sys
blocked=('mujoco','torch','numpy','g1swarm','scripts.run_oracle_missions')
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in blocked):
            raise RuntimeError('FORBIDDEN_LIVE_IMPORT:'+fullname)
sys.meta_path.insert(0,Deny())
entry=sys.argv[1]
sys.argv=sys.argv[1:]
runpy.run_path(entry,run_name='__main__')
assert not any(n==p or n.startswith(p+'.') for n in sys.modules for p in blocked)
"""

def check(head, sha):
    cases = [("correct_preflight", "preflight", head, sha, False, None),
             ("wrong_head", "preflight", "0" * 40, sha, False, "Current HEAD"),
             ("wrong_readiness", "preflight", head, "0" * 64, False, "Readiness SHA mismatch"),
             ("old_migration_readiness", "preflight", head,
              "ed618a31de837f87aca0b855a21013701f9ac762939c841b371cd911fef1b21e", False, "Old Readiness"),
             ("old_p1_readiness", "preflight", head,
              "7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af", False, "Old Readiness")]
    for operation in ("acquire", "worker"):
        cases.append((operation + "_flag_absent", operation, head, sha, False, "flag absent"))
        cases.append((operation + "_flag_is_not_owner_authority", operation, head, sha, True,
                      "OWNER_PHYSICS_AUTHORIZATION_NOT_GRANTED_IN_THIS_FREEZE"))
        cases.append((operation + "_wrong_head", operation, "0" * 40, sha, True, "Current HEAD"))
    results = []
    for name, operation, selected_head, selected_sha, flag, expected in cases:
        command = [sys.executable, "-c", LAUNCHER, str(HERE / "acquire.py"), operation,
                   "--execution-head", selected_head, "--readiness-sha256", selected_sha]
        if flag:
            command.append("--authorize-physics")
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=45)
        row = {"case": name, "command": command, "returncode": completed.returncode,
               "stdout": completed.stdout, "stderr": completed.stderr}
        results.append(row)
        print(json.dumps(row), flush=True)
        assert "FORBIDDEN_LIVE_IMPORT" not in completed.stderr, name
        if expected:
            assert completed.returncode != 0 and expected in completed.stderr, name
        else:
            assert completed.returncode == 0, completed.stderr
            receipt = json.loads(completed.stdout)
            assert receipt["execution_head"] == head and receipt["readiness_sha256"] == sha
            assert receipt["physics_authorized"] is False and receipt["official_asset_count"] == 91
            assert receipt["dependency_count"] == 41 and receipt["physics_steps"] == 0
    print(json.dumps({"status": "PASS_CLEAN_PROCESS_ENTRY_BINDING_NO_PHYSICS",
                      "cases": len(results), "execution_head": head, "readiness_sha256": sha,
                      "live_import_tripwire_hits": 0, "physics_steps": 0, "policy_inferences": 0}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-head", required=True)
    parser.add_argument("--readiness-sha256", required=True)
    args = parser.parse_args()
    check(args.execution_head, args.readiness_sha256)
