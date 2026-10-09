"""New entry fault injection. No live backend is called, including positive tests."""
import ast
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

HERE = Path(__file__).absolute().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

E = module("entry_under_test", HERE / "acquire.py")
G = module("gate_under_test", HERE / "readiness.py")

def args(operation="acquire"):
    return SimpleNamespace(command=operation, readiness_sha256="a" * 64, execution_head="b" * 40,
                           authorize_physics=True)

def cli(operation):
    return [operation, "--readiness-sha256", "a" * 64, "--execution-head", "b" * 40, "--authorize-physics"]

@pytest.mark.parametrize("operation", ["acquire", "worker", "preflight"])
@pytest.mark.parametrize("failure", ["HEAD", "Readiness", "source byte drift", "actual resolver origin drift"])
def test_all_entry_modes_reject_gate_fault_before_adapter(monkeypatch, operation, failure):
    calls = []
    def gate(**kw):
        calls.append("gate")
        raise ValueError(failure)
    fake = SimpleNamespace(check_target=gate, authorize_operation=lambda *a: calls.append("authorize"))
    monkeypatch.setattr(E, "gate_module", lambda: fake)
    monkeypatch.setattr(E, "checked_adapter", lambda *a: calls.append("ADAPTER_LOADED"))
    with pytest.raises(ValueError, match=failure):
        E.main(cli(operation))
    assert calls == ["gate"]

@pytest.mark.parametrize("operation", ["acquire", "worker"])
@pytest.mark.parametrize("flag", [False, True])
def test_real_authority_gate_rejects_even_cli_assertion(monkeypatch, operation, flag):
    calls = []
    fake = SimpleNamespace(check_target=lambda **kw: {}, authorize_operation=G.authorize_operation)
    monkeypatch.setattr(E, "gate_module", lambda: fake)
    monkeypatch.setattr(E, "checked_adapter", lambda *a: calls.append("ADAPTER_LOADED"))
    command = cli(operation)
    if not flag:
        command.remove("--authorize-physics")
    with pytest.raises(PermissionError):
        E.main(command)
    assert calls == []

@pytest.mark.parametrize("operation", ["acquire", "worker"])
def test_positive_order_only_with_offline_authority_double(monkeypatch, operation):
    calls = []
    fake = SimpleNamespace(check_target=lambda **kw: calls.append("identity"),
                           authorize_operation=lambda *a: calls.append("authority"))
    monkeypatch.setattr(E, "gate_module", lambda: fake)
    monkeypatch.setattr(E, "checked_adapter", lambda *a: (calls.append("stdlib_adapter") or
                      SimpleNamespace(main=lambda: calls.append("FAKE_DISPATCH"))))
    E.main(cli(operation))
    assert calls == ["identity", "authority", "stdlib_adapter", "FAKE_DISPATCH"]

def test_preflight_never_loads_adapter_or_checks_physics_authority(monkeypatch):
    monkeypatch.setattr(E, "gate_module", lambda: SimpleNamespace(check_target=lambda **kw: {"physics_authorized": False}))
    monkeypatch.setattr(E, "checked_adapter", lambda *a: pytest.fail("unexpected adapter load"))
    assert E.main(cli("preflight")) == {"physics_authorized": False}

@pytest.mark.parametrize("name", ["g1swarm", "g1swarm.mission", "mujoco", "torch", "numpy", "scripts.run_oracle_missions"])
def test_preloaded_real_modules_forbidden(monkeypatch, name):
    monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    with pytest.raises(ValueError, match="loaded live modules"):
        G.clean_process()

def test_wrong_full_head_is_rejected_with_real_complete_assets():
    assert len(G.helpers()["original_gate"](G.ROOT)["verify_assets"](G.ROOT)) == 91
    with pytest.raises(ValueError, match="Current HEAD"):
        G.check_identity("0" * 40)

@pytest.mark.parametrize("sha", ["", "0" * 63, "g" * 64, G.MIGRATION_READY_SHA,
                                      "7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af"])
def test_invalid_or_old_readiness_rejected(sha):
    with pytest.raises(ValueError, match="Readiness"):
        G.check_target(expected_sha=sha, execution_head="0" * 40)

def test_resolver_is_actual_new_worktree_not_external_editable():
    assert G.controlled_source() == {"g1swarm": str(G.ROOT / "src/g1swarm/__init__.py"),
                                     "scripts.run_oracle_missions": str(G.ROOT / "scripts/run_oracle_missions.py")}
    assert "g1swarm" not in sys.modules

@pytest.mark.parametrize("origin", ["D:/work/g1-m26a-p1-repair/src/g1swarm/__init__.py",
                                    "D:/webcodex/mujoco-g1/main-codex/src/g1swarm/__init__.py"])
def test_live_resolver_wrong_origin_rejected(monkeypatch, origin):
    real = G.PathFinder.find_spec
    monkeypatch.setattr(G.PathFinder, "find_spec", lambda name, path: SimpleNamespace(origin=origin) if name == "g1swarm" else real(name, path))
    with pytest.raises(ValueError, match="resolver origin drift"):
        G.controlled_source()

@pytest.mark.parametrize("tamper_hash", [False, True])
def test_real_temporary_source_tampering_and_rehashed_code_rejected(tmp_path, monkeypatch, tamper_hash):
    retained_helpers = G.helpers()
    ns = G.NAMESPACE
    here = tmp_path / ns
    migration = tmp_path / G.MIGRATION
    here.mkdir(parents=True)
    migration.mkdir(parents=True)
    for name in ("source_manifest.json", "readiness_manifest.json"):
        (migration / name).write_bytes(b"{}\n")
    p = ns + "/acquire.py"
    (tmp_path / p).write_bytes(b"# inert fixture\n")
    def git(*a):
        return subprocess.check_output(["git", *a], cwd=tmp_path)
    git("init", "--quiet")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Fixture", "-c", "user.email=offline@example.invalid", "commit", "--quiet", "-m", "inert fixture")
    head = git("rev-parse", "HEAD").decode().strip()
    source = {"base_head": G.BASE_HEAD, "namespace": ns, "physics_authorized": False,
              "execution_code_head": head, "execution_code_files": [p], "files": {p: G.digest(tmp_path / p)}}
    def write():
        (here / "source_manifest.json").write_text(json.dumps(source), encoding="utf8")
    write()
    monkeypatch.setattr(G, "ROOT", tmp_path)
    monkeypatch.setattr(G, "HERE", here)
    monkeypatch.setattr(G, "MIGRATION_READY_SHA", G.digest(migration / "readiness_manifest.json"))
    monkeypatch.setattr(G, "MIGRATION_SOURCE_SHA", G.digest(migration / "source_manifest.json"))
    monkeypatch.setattr(G, "git", git)
    monkeypatch.setattr(G, "helpers", lambda: retained_helpers)
    monkeypatch.setattr(G, "source_paths", lambda: {p})
    assert G.verify_sources()["files"] == source["files"]
    (tmp_path / p).write_bytes(b"# tampered\n")
    if tamper_hash:
        source["files"][p] = G.digest(tmp_path / p)
        write()
    with pytest.raises(ValueError, match="Source byte drift|pinned Git bytes"):
        G.verify_sources()

def test_bound_adapter_preserves_p1_and_worker_path_with_fake_backend(tmp_path, monkeypatch):
    raw = G.ROOT / G.ORIGINAL / "acquire.py"
    fake = SimpleNamespace(ORIGINAL=G.ORIGINAL, DESIGN=G.DESIGN,
        require=G.require, digest=G.digest, load=lambda path: {"files": {raw.relative_to(G.ROOT).as_posix(): G.digest(raw)}} if path.name == "source_manifest.json" else G.load(path),
        check_target=lambda **kw: {"status": "OFFLINE_GATE_DOUBLE"}, authorize_operation=lambda *a: None)
    monkeypatch.delitem(sys.modules, "audit", raising=False)
    before = list(sys.path)
    try:
        adapter = E.checked_adapter(fake, args("worker"))
        assert adapter.HERE == HERE and adapter.READINESS == HERE / "readiness_manifest.json"
        assert adapter.assess_hold.__code__.co_filename == str(raw)
        assert adapter.exception_observer.__code__.co_filename == str(raw)
        assert adapter.preflight("a" * 64)[2]["status"] == "OFFLINE_GATE_DOUBLE"
        fake.check_target = lambda **kw: (_ for _ in ()).throw(ValueError("worker drift"))
        with pytest.raises(ValueError, match="worker drift"):
            with adapter.production_backend({}, {}, {}, tmp_path, 0):
                pytest.fail("backend reached")
        assert not {"mujoco", "torch", "g1swarm"}.intersection(sys.modules)
        tree = ast.parse(raw.read_text(encoding="utf8"))
        acquire = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "acquire")
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str"
                   and len(n.args) == 1 and isinstance(n.args[0], ast.BinOp)
                   and isinstance(n.args[0].left, ast.Name) and n.args[0].left.id == "HERE"
                   and isinstance(n.args[0].right, ast.Constant) and n.args[0].right.value == "acquire.py"
                   for n in ast.walk(acquire))
    finally:
        sys.path[:] = before

def test_audit_shim_preserves_original_raw_scoring():
    audit = module("audit_shim_under_test", HERE / "audit.py")
    for name in ("assess_hold", "exception_observer"):
        assert callable(getattr(module("p1_adapter_comparison", G.ROOT / G.ORIGINAL / "acquire.py"), name))
    assert audit.audit_campaign is audit.RAW.audit_campaign
    assert audit.verify_acquisition_prefix is audit.RAW.verify_acquisition_prefix
    assert audit.RAW.verify_sources is audit.verify_sources

def test_new_entry_module_loads_only_standard_library():
    result = subprocess.run([sys.executable, "-c", "import runpy,sys; runpy.run_path(sys.argv[1]); assert not {'mujoco','torch','numpy','g1swarm'}.intersection(sys.modules)", str(HERE / "acquire.py")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
