"""Preserve accepted scientific history; explicitly scoped Console changes only."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = "a114ec90a4f577420e6f183fe0c41cadedba03fd"
ALLOWED = {"console/server.py", "console/web/app.js", "console/web/data.js", "console/web/data.test.js",
           "console/web/styles.css", "ops/state.json"}


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(name, value):
    with (HERE / name).open("x", encoding="utf8", newline="\n") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


def snapshot():
    paths = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    record = {
        "base_commit": BASE, "allowed_console_paths": sorted(ALLOWED),
        "working_bytes": {p: sha(ROOT / p) for p in paths if p not in ALLOWED},
        "base_tree": git("rev-parse", BASE + "^{tree}").decode().strip(),
        "original_workspace_status": git("status", "--porcelain=v1", cwd="D:/work/g1-jev-swarm-lab").decode(),
        "source_workspace_status": git("status", "--porcelain=v1", cwd="D:/work/g1-source-authority").decode(),
        "source_branch_pin": "a2325d393c3ffc46eaf7252122b61179ea0e35cb",
        "protocol_sha256": sha(HERE / "protocol.json"),
    }
    write_new("history_before.json", record)
    print(json.dumps({"history_snapshot": "FROZEN", "files": len(record["working_bytes"])}))


def check():
    record = json.loads((HERE / "history_before.json").read_text())
    preserved = {p: s for p, s in record["working_bytes"].items() if p not in ALLOWED}
    mismatches = [p for p, s in preserved.items()
                  if not (ROOT / p).is_file() or sha(ROOT / p) != s]
    changed = git("diff", BASE, "--name-only", "--diff-filter=MDRT").decode().splitlines()
    outside = [p for p in changed if p not in ALLOWED]
    original = git("status", "--porcelain=v1", cwd="D:/work/g1-jev-swarm-lab").decode() == record["original_workspace_status"]
    source = git("status", "--porcelain=v1", cwd="D:/work/g1-source-authority").decode() == record["source_workspace_status"]
    protocol = sha(HERE / "protocol.json") == record["protocol_sha256"]
    value = {"status": "PASS" if not mismatches and not outside and original and source and protocol else "FAIL",
             "baseline_working_bytes_verified": len(preserved),
             "mismatches": mismatches, "outside_console_modifications": outside,
             "allowed_console_modifications": [p for p in changed if p in ALLOWED],
             "original_untracked_status_unchanged": original, "source_workspace_status_unchanged": source,
             "protocol_unchanged": protocol,
             "original_untracked_content_byte_audit_claim": False}
    print(json.dumps(value))
    if value["status"] != "PASS":
        raise SystemExit(1)
    return value


if __name__ == "__main__":
    {"snapshot": snapshot, "check": check}[sys.argv[1]]()
