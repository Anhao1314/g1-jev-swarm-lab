"""Synthetic and metadata-only readiness tests; no model imports or stepping."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

R = runpy.run_path(str(Path(__file__).with_name("readiness.py")))


def child_gate(**kwargs):
    """Run the actual non-import gate in its required clean process boundary.

    Fault-injection tests elsewhere legitimately load the Router into pytest.
    Never delete those modules or weaken the production clean-process guard.
    """
    load_project = kwargs.pop("load_project", False)
    encoded = {key: str(value) if isinstance(value, Path) else value for key, value in kwargs.items()}
    program = f"""import json, runpy, sys
from pathlib import Path
r = runpy.run_path({str(Path(__file__).with_name('readiness.py'))!r})
kwargs = json.loads({json.dumps(encoded)!r})
for key in ('root', 'here'):
    if key in kwargs:
        kwargs[key] = Path(kwargs[key])
if {load_project!r}:
    sys.path.insert(0, str(r['ROOT'] / 'src'))
    import g1swarm
try:
    report = r['check_target'](**kwargs)
    result = {{'ok': True, 'report': report}}
except ValueError as exc:
    result = {{'ok': False, 'error': str(exc)}}
result['forbidden_imports_present'] = [name for name in r['FORBIDDEN_IMPORTS'] if name in sys.modules]
print(json.dumps(result))
"""
    receipt = subprocess.run([sys.executable, "-c", program], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return json.loads(receipt.stdout)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def asset_fixture(path, corrupt=None):
    rows = []
    for i in range(91):
        name = f"third_party/official/asset{i}"
        data = str(i).encode()
        p = path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"corrupt" if i == corrupt else data)
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    write_json(path / R["OLD"] / "asset_restore.json", {"files": rows})
    return rows


def test_target_environment_no_imports():
    child = child_gate(require_manifest=False)
    assert child["ok"]
    report = child["report"]
    assert report["official_asset_count"] == 91
    assert report["dependency_count"] == 41
    assert report["xml_resource_count"] == 28
    assert report["physics_steps"] == report["policy_inferences"] == 0
    assert child["forbidden_imports_present"] == []


def test_actual_project_import_is_rejected_by_child_gate():
    child = child_gate(require_manifest=False, load_project=True)
    assert not child["ok"] and "without simulator" in child["error"]
    assert child["forbidden_imports_present"] == ["g1swarm"]


def test_origins_resolved_without_import():
    report = R["dependency_check"]()
    assert set(report["module_origins_without_import"]) == {"mujoco", "torch", "numpy", "yaml", "pytest", "g1swarm"}
    assert "mujoco" not in sys.modules and "torch" not in sys.modules


def test_asset_restore_checks_full_source_before_writes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    rows = asset_fixture(source, corrupt=90)
    write_json(target / R["OLD"] / "asset_restore.json", {"files": rows})
    with pytest.raises(ValueError, match="Official asset mismatch"):
        R["restore_assets"](source, root=target)
    assert not (target / "third_party").exists()


def test_restore_never_overwrites_target(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    rows = asset_fixture(source)
    asset_fixture(target, corrupt=90)
    before = (target / rows[-1]["path"]).read_bytes()
    with pytest.raises(ValueError, match="Existing asset mismatch"):
        R["restore_assets"](source, root=target)
    assert (target / rows[-1]["path"]).read_bytes() == before


def test_valid_restore_is_idempotent(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    rows = asset_fixture(source)
    write_json(target / R["OLD"] / "asset_restore.json", {"files": rows})
    assert R["restore_assets"](source, root=target)["copied"] == 91
    assert R["restore_assets"](source, root=target)["copied"] == 0


def test_duplicate_asset_receipt_rejected(tmp_path):
    rows = asset_fixture(tmp_path)
    rows[-1] = rows[0]
    write_json(tmp_path / R["OLD"] / "asset_restore.json", {"files": rows})
    with pytest.raises(ValueError, match="membership"):
        R["official_rows"](tmp_path)


def test_nonasset_receipt_rejected(tmp_path):
    rows = asset_fixture(tmp_path)
    rows[-1]["path"] = "src/evil.py"
    write_json(tmp_path / R["OLD"] / "asset_restore.json", {"files": rows})
    with pytest.raises(ValueError, match="Nonasset"):
        R["official_rows"](tmp_path)


@pytest.mark.parametrize("path", ["../outside", "D:/outside", "../../src"])
def test_path_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        R["contained"](tmp_path, path)


@pytest.mark.parametrize("module", ["mujoco", "torch", "g1swarm"])
def test_import_guard(module, monkeypatch):
    monkeypatch.setitem(sys.modules, module, object())
    with pytest.raises(ValueError, match="without simulator"):
        R["clean_process"]()


def test_bad_expected_readiness_sha_rejected_before_environment(tmp_path):
    here = tmp_path / R["REPAIR_NAMESPACE"]
    here.mkdir(parents=True)
    (here / "readiness_manifest.json").write_text("{}")
    child = child_gate(root=tmp_path, here=here, expected_sha="0" * 64)
    assert not child["ok"] and "expected SHA" in child["error"]
    assert child["forbidden_imports_present"] == []


def test_wrong_execution_head_rejected():
    child = child_gate(require_manifest=False, execution_head="0" * 40)
    assert not child["ok"] and "execution HEAD" in child["error"]


def test_current_xml_parser_without_compilation():
    result = R["xml_resources"]()
    assert len(result["xml_documents"]) == 2
    assert len(result["resource_links"]) == 28
    assert result["model_compilations"] == 0


def test_bad_xml_resource_rejected(tmp_path):
    start = tmp_path / "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml"
    start.parent.mkdir(parents=True)
    start.write_text('<mujoco><include file="missing.xml"/></mujoco>')
    with pytest.raises(ValueError, match="MJCF resource"):
        R["xml_resources"](tmp_path)


def test_expected_source_closure_includes_runtime_and_raw_history():
    paths = R["expected_source_paths"]()
    assert "src/g1swarm/skills/basic.py" in paths
    assert "experiments/m2/post_halt_hold_qualification_001/raw/campaign_001.zip" in paths
    assert "experiments/m2/cross_state_reliability_archives_001/manifest.json" in paths
    assert sum(name.startswith(R["DESIGN"] + "/") for name in paths) == 16
    assert R["REPAIR_NAMESPACE"] + "/readiness_manifest.json" not in paths


def test_expected_source_closure_captures_all_new_python():
    paths = R["expected_source_paths"]()
    prefix = "experiments/m2/unseen_halt_hold_p1_repair_001/"
    for path in Path(__file__).parent.glob("*.py"):
        assert prefix + path.name in paths
    assert prefix + "dependencies.json" in paths
    assert prefix + "assets_receipt.json" in paths


def test_blocked_sha_rejected_before_environment():
    child = child_gate(expected_sha=R["BLOCKED_DELIVERY"]["readiness_sha256"])
    assert not child["ok"] and "Blocked readiness SHA" in child["error"]


def test_old_path_rejected_before_environment():
    child = child_gate(here=Path(__file__).parents[1] / "unseen_halt_hold_readiness_001")
    assert not child["ok"] and "Wrong repair readiness path" in child["error"]


def test_old_ready_manifest_is_not_repaired_authority():
    old = R["load"](R["ROOT"] / R["BLOCKED_BUNDLE"] / "readiness_manifest.json")
    with pytest.raises(ValueError, match="Wrong repair namespace"):
        R["repair_identity"](old)


def test_repair_identity_requires_explicit_blocked_delivery():
    value = {"status": "READY_FOR_OWNER_ACQUISITION_AUTHORIZATION", "physics_authorized": False,
             "repair_namespace": R["REPAIR_NAMESPACE"], "execution_code_head": "a" * 40}
    with pytest.raises(ValueError, match="blocked delivery identity"):
        R["repair_identity"](value)
    value["blocked_delivery"] = R["BLOCKED_DELIVERY"]
    R["repair_identity"](value)
    value["execution_code_head"] = R["BLOCKED_DELIVERY"]["head"]
    with pytest.raises(ValueError, match="Blocked execution HEAD"):
        R["repair_identity"](value)


def test_source_closure_preserves_complete_blocked_bundle():
    paths = R["expected_source_paths"]()
    blocked = {p for p in paths if p.startswith(R["BLOCKED_BUNDLE"] + "/")}
    assert len(blocked) == 41
    assert R["BLOCKED_BUNDLE"] + "/readiness_manifest.json" in blocked
    assert R["BLOCKED_BUNDLE"] + "/source_manifest.json" in blocked


def test_superseded_archive_membership_and_original_hashes():
    candidates = R["superseded_candidates"]()
    assert len(candidates) == 1
    assert candidates[0]["readiness_sha256"] == R["SUPERSEDED_IDENTITY"]["readiness_sha256"]
    paths = R["expected_source_paths"]()
    prefix = R["REPAIR_NAMESPACE"] + "/superseded_candidate_001/"
    assert len([name for name in paths if name.startswith(prefix)]) == 33
    assert candidates[0]["rejection_path"] in paths


def test_superseded_original_hash_drift_rejected(monkeypatch):
    # Fault inject a hash mismatch without mutating the preserved archive or
    # duplicating its deliberately deep provenance path under a Windows tempdir.
    archive = R["HERE"] / "superseded_candidate_001"
    victim = archive / "original_root" / R["REPAIR_NAMESPACE"] / "dependencies.json"
    real_digest = R["digest"]
    def mismatched_digest(path):
        return "0" * 64 if Path(path).resolve() == victim.resolve() else real_digest(path)
    monkeypatch.setitem(R["superseded_candidates"].__globals__, "digest", mismatched_digest)
    with pytest.raises(ValueError, match="Superseded original bytes changed"):
        R["superseded_candidates"]()


def test_superseded_readiness_sha_refused_before_environment():
    child = child_gate(expected_sha=R["SUPERSEDED_IDENTITY"]["readiness_sha256"])
    assert not child["ok"] and "Superseded readiness SHA" in child["error"]
