"""Migration identity fault tests; no simulator, policy, or model imports.

These test helpers before the metadata freeze. The full acceptance CLI must also
run in a fresh process against the separately published final HEAD and SHA.
"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = runpy.run_path(str(HERE / "readiness.py"))


def current_head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()


def test_complete_official_assets_and_xml_without_compilation():
    old = R["original_gate"](ROOT)
    assert len(old["verify_assets"](ROOT)) == 91
    resources = old["xml_resources"](ROOT)
    assert len(resources["xml_documents"]) == 2
    assert len(resources["resource_links"]) == 28
    assert resources["model_compilations"] == 0


def test_wrong_head_rejected_with_full_official_resources():
    # This deliberately proves the exact HEAD guard, rather than accepting an
    # earlier dependency-origin failure as an equivalent rejection.
    assert len(R["original_gate"](ROOT)["verify_assets"](ROOT)) == 91
    with pytest.raises(ValueError, match="HEAD"):
        R["git_identity"](ROOT, "0" * 40)


@pytest.mark.parametrize("fault,error", [
    ("toplevel", "Git toplevel"),
    ("registered_path", "registration missing/duplicated"),
    ("registered_head", "Registered worktree HEAD mismatch"),
])
def test_registered_git_location_drift_rejected(monkeypatch, fault, error):
    """Inject one Git identity observation while retaining real local receipts."""
    globals_ = R["git_location"].__globals__
    real_git = globals_["git"]
    head = current_head()
    def observed_git(root, *args):
        result = real_git(root, *args)
        if fault == "toplevel" and args == ("rev-parse", "--show-toplevel"):
            return b"D:/webcodex/mujoco-g1/language-codex\n"
        if args == ("worktree", "list", "--porcelain"):
            blocks = result.decode().split("\n\n")
            for index, block in enumerate(blocks):
                if block.splitlines() and block.splitlines()[0] == "worktree " + ROOT.as_posix():
                    if fault == "registered_path":
                        blocks[index] = block.replace("worktree " + ROOT.as_posix(), "worktree D:/wrong-registration", 1)
                    elif fault == "registered_head":
                        blocks[index] = block.replace("HEAD " + head, "HEAD " + "0" * 40, 1)
            return "\n\n".join(blocks).encode()
        return result
    monkeypatch.setitem(globals_, "git", observed_git)
    with pytest.raises(ValueError, match=error):
        R["git_location"](ROOT)


@pytest.mark.parametrize("head", ["3082e2b", "", "g" * 40, "0" * 39, "0" * 41])
def test_head_must_be_full_canonical_commit(head):
    with pytest.raises(ValueError):
        R["git_identity"](ROOT, head)


def test_intended_root_and_namespace_accepted():
    R["validate_location"](ROOT, HERE)


def test_different_workspace_rejected(tmp_path):
    with pytest.raises(ValueError):
        R["validate_location"](tmp_path, tmp_path / HERE.name)


def test_other_namespace_rejected():
    with pytest.raises(ValueError):
        R["validate_location"](ROOT, ROOT / "experiments/m2/unseen_halt_hold_p1_repair_001")


@pytest.mark.parametrize("relative", ["../outside", "../../outside", "D:/outside", "C:/Windows", "\\\\server\\share\\outside"])
def test_manifest_escape_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        R["checked_path"](tmp_path, relative)


def test_regular_contained_file_accepted(tmp_path):
    target = tmp_path / "safe.txt"
    target.write_text("frozen bytes", encoding="utf8")
    assert R["checked_path"](tmp_path, "safe.txt") == target.resolve()


def test_junction_alias_rejected(tmp_path):
    """Real Windows reparse point, even when its target stays inside the root."""
    import os
    if os.name != "nt":
        pytest.skip("Windows junction behavior requires Windows")
    target, alias = tmp_path / "real", tmp_path / "alias"
    target.mkdir()
    (target / "file.py").write_bytes(b"frozen source\n")
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                             capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    with pytest.raises(ValueError):
        R["checked_path"](tmp_path, "alias/file.py")


def test_digest_detects_real_disk_content_tampering(tmp_path):
    target = tmp_path / "source.py"
    target.write_bytes(b"frozen source\n")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    assert R["digest"](target) == expected
    target.write_bytes(b"altered source\n")
    assert R["digest"](target) != expected


def test_frozen_original_sources_still_match():
    assert R["verify_original"](ROOT)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf8")


def current_dependencies():
    return R["original_gate"](ROOT)["dependency_check"](ROOT)


def test_only_project_origin_rebound_with_same_external_environment(tmp_path):
    actual = current_dependencies()
    write_json(tmp_path / "dependencies.json", actual)
    verified = R["dependency_check"](ROOT, tmp_path)
    historical = R["load"](ROOT / R["ORIGINAL"] / "dependencies.json")
    assert len(verified["packages"]) == 41
    assert verified["packages"] == historical["packages"]
    assert verified["executable"] == historical["executable"]
    assert verified["module_origins_without_import"]["g1swarm"] == str(ROOT / "src/g1swarm/__init__.py")
    for name in ("mujoco", "torch", "numpy", "yaml", "pytest"):
        assert verified["module_origins_without_import"][name] == historical["module_origins_without_import"][name]


@pytest.mark.parametrize("module", ["g1swarm", "mujoco", "torch", "numpy", "yaml", "pytest"])
def test_wrong_dependency_origin_receipt_rejected(tmp_path, module):
    actual = current_dependencies()
    actual["module_origins_without_import"][module] = str(tmp_path / module / "__init__.py")
    write_json(tmp_path / "dependencies.json", actual)
    with pytest.raises(ValueError, match="receipt drift"):
        R["dependency_check"](ROOT, tmp_path)


def test_wrong_dependency_version_receipt_rejected(tmp_path):
    actual = current_dependencies()
    actual["packages"]["pytest"] = "0.0.0"
    write_json(tmp_path / "dependencies.json", actual)
    with pytest.raises(ValueError, match="receipt drift"):
        R["dependency_check"](ROOT, tmp_path)


def test_old_dependency_origin_is_not_accepted_as_new_identity(tmp_path):
    historical = R["load"](ROOT / R["ORIGINAL"] / "dependencies.json")
    write_json(tmp_path / "dependencies.json", historical)
    with pytest.raises(ValueError, match="receipt drift"):
        R["dependency_check"](ROOT, tmp_path)


def test_actual_controlled_resolver_selects_new_source_without_import():
    resolved = R["controlled_source_path"](ROOT)
    assert resolved == str(ROOT / "src/g1swarm/__init__.py")
    assert "g1swarm" not in sys.modules


@pytest.mark.parametrize("origin", ["D:/work/g1-m26a-p1-repair/src/g1swarm/__init__.py", "D:/webcodex/mujoco-g1/language-codex/src/g1swarm/__init__.py"])
def test_actual_resolver_origin_drift_rejected(monkeypatch, origin):
    from types import SimpleNamespace
    finder = R["controlled_source_path"].__globals__["PathFinder"]
    monkeypatch.setattr(finder, "find_spec", lambda *args: SimpleNamespace(origin=origin))
    with pytest.raises(ValueError, match="resolver origin mismatch"):
        R["controlled_source_path"](ROOT)


def test_external_environment_metadata_is_actual_and_hash_bound():
    rows = R["external_environment_source_metadata"]()
    assert len(rows) == 2
    assert {Path(row["path"]).suffix for row in rows} == {".pth", ".json"}
    assert all(R["digest"](row["path"]) == row["sha256"] for row in rows)


def valid_binding():
    # Loading the target's candidate receipt is not trusting it: the production
    # helper below independently reconstructs every permitted field and origin.
    return R["load"](HERE / "binding.json")


def test_binding_freezes_exact_origin_delta_and_external_metadata(tmp_path):
    data = valid_binding()
    write_json(tmp_path / "binding.json", data)
    assert R["verify_binding"](ROOT, tmp_path) == data


@pytest.mark.parametrize("field", ["source_root", "base_head", "origin_url", "physics_authorized", "external_environment_source_metadata"])
def test_binding_identity_or_authority_drift_rejected(tmp_path, field):
    data = valid_binding()
    data[field] = True if field == "physics_authorized" else "tampered"
    write_json(tmp_path / "binding.json", data)
    with pytest.raises(ValueError, match="binding identity"):
        R["verify_binding"](ROOT, tmp_path)


def test_binding_wrong_origin_delta_rejected(tmp_path):
    data = valid_binding()
    data["allowed_dependency_delta"]["new"] = str(tmp_path / "src/g1swarm/__init__.py")
    write_json(tmp_path / "binding.json", data)
    with pytest.raises(ValueError, match="binding identity"):
        R["verify_binding"](ROOT, tmp_path)


@pytest.mark.parametrize("mutation", ["raw_bytes", "code_bytes", "code_and_proposed_hash"])
def test_source_gate_rejects_real_temporary_file_tampering(tmp_path, monkeypatch, mutation):
    """Exercise byte and Git-pin checks on an explicit tiny offline Git fixture.

    Only independent membership enumeration is reduced for this fixture. Actual
    disk reads, SHA computation, Git commits and pinned-byte reads stay real.
    This is not reported as the complete target-worktree acceptance.
    """
    here = tmp_path / R["NAMESPACE"]
    here.mkdir(parents=True)
    code_name = R["NAMESPACE"] + "/fixture.py"
    data_name = R["NAMESPACE"] + "/raw.json"
    (tmp_path / code_name).write_bytes(b"# inert fixture; never imported\n")
    (tmp_path / data_name).write_bytes(b'{"frozen": true}\n')
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "--quiet")
    git("-c", "core.autocrlf=false", "add", "--", code_name, data_name)
    git("-c", "user.name=Offline Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "--quiet", "-m", "Offline source binding fixture")
    head = git("rev-parse", "HEAD")
    manifest = {"namespace": R["NAMESPACE"], "base_head": R["BASE_HEAD"],
                "physics_authorized": False, "execution_code_head": head,
                "execution_code_files": [code_name],
                "files": {name: R["digest"](tmp_path / name) for name in (code_name, data_name)}}
    write_json(here / "source_manifest.json", manifest)
    globals_ = R["verify_sources"].__globals__
    monkeypatch.setitem(globals_, "expected_source_paths", lambda root, here: {code_name, data_name})
    assert R["verify_sources"](tmp_path, here) == 2
    changed = data_name if mutation == "raw_bytes" else code_name
    (tmp_path / changed).write_bytes(b"tampered bytes\n")
    if mutation == "code_and_proposed_hash":
        manifest["files"][code_name] = R["digest"](tmp_path / code_name)
        write_json(here / "source_manifest.json", manifest)
    with pytest.raises(ValueError, match="byte drift|pinned Git bytes"):
        R["verify_sources"](tmp_path, here)


@pytest.mark.parametrize("sha", ["", "0" * 63, "0" * 65, "g" * 64])
def test_noncanonical_expected_readiness_identity_rejected(sha):
    with pytest.raises(ValueError, match="Readiness SHA"):
        R["check_target"](expected_sha=sha, execution_head=current_head())


def test_old_readiness_cannot_authorize_new_workspace():
    with pytest.raises(ValueError, match="Historical Readiness"):
        R["check_target"](expected_sha=R["ORIGINAL_READY_SHA"], execution_head=current_head())


def test_helpers_do_not_import_simulator_or_project():
    assert not {"mujoco", "torch", "g1swarm"}.intersection(sys.modules)


def test_cli_has_no_environment_only_bypass():
    result = subprocess.run([sys.executable, str(HERE / "readiness.py"), "--environment-only"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0


def test_cli_requires_separately_expected_identities():
    result = subprocess.run([sys.executable, str(HERE / "readiness.py")],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
