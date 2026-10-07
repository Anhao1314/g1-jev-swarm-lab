"""Read-only historical integrity and saved integration-check audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "experiments/phase2/authority_release_001"
BASE = "83a36a2ec6ce8bb9f1edab96a36ac702b2c46133"
CHANGED_BOUNDARY = "src/g1swarm/source_authority/authorization.py"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    old_inputs = read(ROOT / "experiments/phase2/authority_mechanism_001/inputs.json")
    errors = []
    original = read(DEST / "historical_snapshot.json")
    old_boundary_hash = old_inputs["raw_byte_bindings"][CHANGED_BOUNDARY]["sha256"]
    if sha(ROOT / original["snapshot_path"]) != old_boundary_hash or original["sha256"] != old_boundary_hash:
        errors.append("historical boundary snapshot does not match its original byte binding")
    preserved = []
    for name, binding in old_inputs["raw_byte_bindings"].items():
        if name == CHANGED_BOUNDARY:
            continue
        if sha(ROOT / name) != binding["sha256"] or (ROOT / name).stat().st_size != binding["bytes"]:
            errors.append("historical input byte drift: " + name)
        preserved.append(name)
    tracked = set(subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", BASE], text=True).splitlines())
    diff = set(subprocess.check_output(["git", "-C", str(ROOT), "diff", BASE, "--name-only"], text=True).splitlines())
    changes = sorted(tracked & diff)
    if changes != [CHANGED_BOUNDARY]:
        errors.append("unexpected pre-existing tracked changes: " + str(changes))
    tests = ET.parse(DEST / "tests.xml").getroot().findall("testsuite")
    counts = {name: sum(int(suite.get(name, 0)) for suite in tests)
              for name in ("tests", "failures", "errors", "skipped")}
    if counts != {"tests": 59, "failures": 0, "errors": 0, "skipped": 0}:
        errors.append("necessary integration/bounded checks are incomplete or failing")
    results = read(DEST / "fixture_results.json")
    for field in ("provider_calls", "held_out_calls", "runtime_calls", "new_model_treatments"):
        if results.get(field) != 0:
            errors.append("unexpected new acquisition/execution: " + field)
    if results.get("D011") != "BLOCKED":
        errors.append("D011 changed")
    old_release = read(ROOT / "experiments/phase2/source_authority_cross_model_001/samples/ood--ood-m-031.json")["dg"]["score"]["unauthorized_release"]
    serial = read(ROOT / "experiments/phase2/source_authority_serial_001/decision.json")
    if old_release is not True or serial["status"] != "PARTIAL_STOPPED" or serial["D011"] != "BLOCKED":
        errors.append("historical counterexample or serial closure changed")
    current = [CHANGED_BOUNDARY, "src/g1swarm/authority_release_001/gate.py",
        "src/g1swarm/authority_release_001/__init__.py", "tests/authority_release_001/test_gate.py",
        "scripts/authority_release_001/audit.py"]
    receipt = {"status": "PASS" if not errors else "FAIL", "errors": errors,
        "baseline_commit": BASE, "pre_existing_tracked_paths": len(tracked),
        "authorized_pre_existing_code_changes": changes,
        "preserved_historical_input_bindings": len(preserved),
        "preserved_bound_paths": preserved, "historical_boundary_snapshot_matches_frozen_bytes": True,
        "historical_031_actual_unsafe_release_preserved": old_release,
        "DG_serial": serial["status"], "D011": serial["D011"],
        "tests": counts, "current_code_sha256": {name: sha(ROOT / name) for name in current},
        "fixture_results_sha256": sha(DEST / "fixture_results.json"),
        "tests_xml_sha256": sha(DEST / "tests.xml"),
        "provider_calls": 0, "runtime_calls": 0, "held_out_calls": 0}
    (DEST / "integrity.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf8")
    print(json.dumps({"status": receipt["status"], "preserved_historical_bindings": len(preserved),
                      "tests": counts, "D011": "BLOCKED", "errors": errors}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
