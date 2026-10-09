"""New byte-binding seam; raw P1 scoring and historical controls stay unchanged."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[2]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

GATE = module("m26_entry_audit_gate", HERE / "readiness.py")
path = ROOT / GATE.ORIGINAL / "audit.py"
GATE.require(GATE.digest(path) == GATE.load(ROOT / GATE.ORIGINAL / "source_manifest.json")["files"][path.relative_to(ROOT).as_posix()],
             "Frozen P1 auditor drift")
RAW = module("m26_entry_frozen_raw_audit", path)

def verify_sources(readiness_sha256, *, execution_head=None):
    receipt = GATE.check_target(expected_sha=readiness_sha256, execution_head=execution_head)
    return {"files": receipt["source_count"], "readiness_sha256": readiness_sha256,
            "execution_head_expected": execution_head,
            "source_manifest_sha256": receipt["source_manifest_sha256"]}

RAW.verify_sources = verify_sources
verify_acquisition_prefix = RAW.verify_acquisition_prefix
audit_campaign = RAW.audit_campaign
