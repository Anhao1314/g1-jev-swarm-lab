"""Synthetic and metadata-only readiness tests; no model imports or stepping."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

import pytest

R = runpy.run_path(str(Path(__file__).with_name("readiness.py")))


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
    report = R["check_target"](require_manifest=False)
    assert report["official_asset_count"] == 91
    assert report["dependency_count"] == 41
    assert report["xml_resource_count"] == 28
    assert report["physics_steps"] == report["policy_inferences"] == 0
    assert not any(name in sys.modules for name in R["FORBIDDEN_IMPORTS"])


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
    (tmp_path / "readiness_manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="expected SHA"):
        R["check_target"](here=tmp_path, expected_sha="0" * 64)


def test_wrong_execution_head_rejected():
    with pytest.raises(ValueError, match="execution HEAD"):
        R["check_target"](require_manifest=False, execution_head="0" * 40)


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
    assert not any(name.endswith("/readiness_manifest.json") and
                   name.startswith("experiments/m2/unseen_halt_hold_readiness_001/") for name in paths)


def test_expected_source_closure_captures_all_new_python():
    paths = R["expected_source_paths"]()
    prefix = "experiments/m2/unseen_halt_hold_readiness_001/"
    for path in Path(__file__).parent.glob("*.py"):
        assert prefix + path.name in paths
    assert prefix + "dependencies.json" in paths
    assert prefix + "assets_receipt.json" in paths
