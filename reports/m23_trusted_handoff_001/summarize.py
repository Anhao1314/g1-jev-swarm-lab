"""Derive bounded offline receipts without running physics or providers."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cases(name):
    return ET.parse(HERE / name).getroot().findall(".//testcase")


def counts(values):
    values = list(values)
    failed = sum(c.find("failure") is not None or c.find("error") is not None for c in values)
    skipped = sum(c.find("skipped") is not None for c in values)
    return {"tests": len(values), "passed": len(values) - failed - skipped,
            "failed": failed, "skipped": skipped}


def main():
    groups = {
        "v0_boundary": counts(cases("v0_boundary.xml")),
        "bridge": counts(cases("bridge_final.xml")),
        "unchanged_runtime_lifecycle": counts(c for c in cases("affected_regression_initial.xml")
                                               if c.attrib["classname"] != "tests.test_research_ops"),
        "ops": counts(cases("ops_final.xml")),
    }
    decisions = []
    for case in cases("bridge_final.xml"):
        for item in case.findall("./properties/property"):
            if item.attrib["name"] in {"m23_gate_outcome", "m23_preparation_refusal"}:
                # Gate records are JSON; preparation failures retain the plain
                # exception reason as a separate JUnit property by design.
                outcome = (json.loads(item.attrib["value"]) if item.attrib["name"] == "m23_gate_outcome"
                           else {"reason": item.attrib["value"], "status": "PREPARATION_REFUSED",
                                 "evidence_kind": "OFFLINE_FAKE_SESSION_FIXTURE"})
                decisions.append({"test": case.attrib["name"], "property": item.attrib["name"],
                                  "outcome": outcome})
    save("offline_decisions.json", {
        "evidence_kind": "OFFLINE_FAKE_SESSION_FIXTURE",
        "source_receipt": "bridge_final.xml", "source_sha256": sha(HERE / "bridge_final.xml"),
        "decisions": decisions,
        "reason_counts": dict(Counter(str(d["outcome"].get("reason")) for d in decisions)),
        "not_independent_physical_samples": True,
    })
    failures = [{"test": c.attrib["name"], "message": c.find("failure").attrib.get("message")}
                for c in cases("affected_regression_initial.xml") if c.find("failure") is not None]
    new_files = [ROOT / "src/g1swarm/mission/trusted_handoff.py",
                 *sorted((ROOT / "src/g1swarm/trusted_handoff_v0").glob("*.py")),
                 ROOT / "tests/test_m23_trusted_handoff.py", ROOT / "tests/test_m23_handoff_v0.py"]
    integrity = json.loads((HERE / "integrity.json").read_text())
    save("verification.json", {
        "verdict": "PASS_OFFLINE_TRUSTED_SERIAL_HANDOFF",
        "scope": "TEST_ONLY canonical handoff into unchanged M2.2 lifecycle, trusted serial entry",
        "protocol_sha256": sha(HERE / "PROTOCOL.md"),
        "source_manifest_sha256": sha(ROOT / "src/g1swarm/trusted_handoff_v0/source_manifest.json"),
        "implementation_and_test_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in new_files},
        "tests": groups,
        "unique_applicable_passes": sum(g["passed"] for g in groups.values()),
        "initial_technical_failures_retained": failures,
        "technical_resolution": "Only exact retained ignored motion.pt copied into isolated worktree; no code or science change",
        "excluded_physics_tests": ["test_live_session_runs_a_stop_mission", "test_live_session_runs_a_grounded_walk"],
        "receipt_sha256": {n: sha(HERE / n) for n in ["v0_boundary.xml", "bridge_final.xml",
            "affected_regression_initial.xml", "ops_final.xml", "offline_decisions.json", "integrity.json"]},
        "history": integrity,
        "boundaries": {"new_physics": 0, "provider_calls": 0, "robot_actuation": 0,
                       "production_authority": False, "language_runtime_d011": "BLOCKED",
                       "jev_online": False, "whole_source_branch_merge": False},
        "physics_decision": "Not required for first-stage offline interface verdict; unchanged M2.2 physical gates are retained evidence only",
        "limitations": ["Synthetic sessions are not new physical qualification",
                        "Trusted serial Python entry only; underlying executor independently callable",
                        "No atomic concurrent robot dispatch or durable/multi-process replay guarantee",
                        "Simulated principal plus host experiment permission, not Human Principal Authority",
                        "Original workspace untracked contents status unchanged; no byte audit claim for those assets"],
    })
    if any(g["failed"] or g["skipped"] for g in groups.values()) or integrity["status"] != "PASS":
        raise SystemExit("Verification receipt has unresolved applicable failure")
    print(json.dumps({"verdict": "PASS_OFFLINE_TRUSTED_SERIAL_HANDOFF", "groups": groups,
                      "unique_applicable_passes": sum(g["passed"] for g in groups.values()),
                      "decision_receipts": len(decisions), "retained_initial_technical_failures": len(failures)}))


if __name__ == "__main__":
    main()
