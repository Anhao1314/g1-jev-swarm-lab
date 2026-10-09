"""Bound acquisition-entry preflight. Standard library only; no physics authority.

Reuse byte-pinned PR22/PR21 verification helpers without changing their sealed
receipts or their old fixed-root gate. This namespace has a separate exact root.
"""
from __future__ import annotations

import hashlib
import json
from importlib.machinery import PathFinder
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path("D:/webcodex/mujoco-g1/acquisition-entry-binding")
NAMESPACE = "experiments/m2/acquisition_entry_binding_001"
HERE = ROOT / NAMESPACE
BASE_HEAD = "44d7a664e9d9ecca57661e98ea15200a216e5517"
MIGRATION = "experiments/m2/migration_source_rebinding_001"
MIGRATION_READY_SHA = "ed618a31de837f87aca0b855a21013701f9ac762939c841b371cd911fef1b21e"
MIGRATION_SOURCE_SHA = "17be268d950b2799aff72b6042921ce85be9307cea89cafad17c4fd5fedd9ad6"
DESIGN = "experiments/m2/unseen_halt_hold_design_001/protocol.json"
ORIGINAL = "experiments/m2/unseen_halt_hold_p1_repair_001"
COMMON = Path("D:/webcodex/mujoco-g1/repo/.git")
ORIGIN = "https://github.com/Anhao1314/g1-jev-swarm-lab.git"
STATUS = "ENTRY_BINDING_READY_NO_PHYSICS_AUTHORITY"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def helpers():
    """Hash against reviewed Git bytes BEFORE executing historical definitions."""
    path = ROOT / MIGRATION / "readiness.py"
    require(digest(path) == hashlib.sha256(git("show", BASE_HEAD + ":" + MIGRATION + "/readiness.py")).hexdigest(),
            "PR22 helper bytes changed")
    return runpy.run_path(str(path), run_name="entry_immutable_pr22_helpers")


def clean_process():
    forbidden = ("mujoco", "torch", "numpy", "g1swarm", "scripts.run_oracle_missions")
    require(not any(name == prefix or name.startswith(prefix + ".")
                    for name in sys.modules for prefix in forbidden),
            "Entry gate requires no loaded live modules")


def check_identity(execution_head):
    require(re.fullmatch(r"[0-9a-f]{40}", execution_head or ""), "Exact full execution HEAD required")
    require(not any(name in os.environ for name in
                    ("GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")),
            "Git identity override forbidden")
    require(git("rev-parse", "HEAD").decode().strip() == execution_head, "Current HEAD differs from execution HEAD")
    r = helpers()
    r["no_links"](ROOT)
    require(Path(__file__).absolute() == HERE / "readiness.py", "Wrong entry gate location")
    require(Path(git("rev-parse", "--show-toplevel").decode().strip()) == ROOT, "Wrong worktree toplevel")
    directory = COMMON / "worktrees/acquisition-entry-binding"
    require(Path(git("rev-parse", "--absolute-git-dir").decode().strip()) == directory, "Wrong Git worktree directory")
    r["no_links"](directory)
    require((ROOT / ".git").read_text().strip() == "gitdir: " + directory.as_posix(), "Wrong Git pointer")
    require((directory / "gitdir").read_text().strip() == (ROOT / ".git").as_posix(), "Wrong Git backlink")
    blocks = git("worktree", "list", "--porcelain").decode().split("\n\n")
    matching = [b.splitlines() for b in blocks if b.startswith("worktree " + ROOT.as_posix() + "\n")]
    require(len(matching) == 1 and "HEAD " + execution_head in matching[0], "Wrong registered worktree identity")
    common = Path(git("rev-parse", "--git-common-dir").decode().strip())
    require(r["no_links"](common if common.is_absolute() else ROOT / common) == COMMON, "Wrong common Git store")
    require(not (COMMON / "objects/info/alternates").exists(), "Git alternates forbidden")
    require(git("remote", "get-url", "origin").decode().strip() == ORIGIN, "Wrong Git origin")
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE_HEAD, "HEAD"], cwd=ROOT, check=True)
    base, current = r["git_tree"](ROOT, BASE_HEAD), r["git_tree"](ROOT, "HEAD")
    require(len(base) == 2842 and all(current.get(p) == v for p, v in base.items()), "PR22 historical Git tree changed")
    require(all(p in base or p.startswith(NAMESPACE + "/") for p in current), "Unexpected tracked additions")
    require(not git("status", "--porcelain", "--untracked-files=all"), "Dirty or untracked worktree")
    ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", "-z").split(b"\0")
    require(not any(Path(p.decode()).suffix in (".py", ".ps1", ".cmd", ".bat", ".sh") for p in ignored if p),
            "Ignored untracked executable forbidden")
    return {"execution_head": execution_head, "preserved_git_entries": len(base)}


def controlled_source():
    clean_process()
    r = helpers()
    for path in (ROOT, ROOT / "src"):
        spelling = str(r["no_links"](path))
        sys.path[:] = [value for value in sys.path if value != spelling]
        sys.path.insert(0, spelling)
    project = PathFinder.find_spec("g1swarm", sys.path)
    scripts = PathFinder.find_spec("scripts", sys.path)
    require(project is not None and project.origin == str(ROOT / "src/g1swarm/__init__.py"), "Actual project resolver origin drift")
    require(scripts is not None and set(scripts.submodule_search_locations or []) == {str(ROOT / "scripts")},
            "Actual scripts resolver origin drift")
    oracle = PathFinder.find_spec("scripts.run_oracle_missions", list(scripts.submodule_search_locations))
    require(oracle is not None and oracle.origin == str(ROOT / "scripts/run_oracle_missions.py"), "Oracle resolver origin drift")
    return {"g1swarm": project.origin, "scripts.run_oracle_missions": oracle.origin}


def environment():
    r = helpers()
    old, assets, resources = r["verify_original"](ROOT)
    for row in assets:
        r["no_links"](ROOT / row["path"])
    origins = controlled_source()
    actual = old["dependency_check"](ROOT)
    prior = r["load"](ROOT / ORIGINAL / "dependencies.json")
    prior["module_origins_without_import"]["g1swarm"] = str(ROOT / "src/g1swarm/__init__.py")
    require(actual == prior, "Dependency delta exceeds project relocation")
    for origin in actual["module_origins_without_import"].values():
        r["no_links"](origin)
    require(load(HERE / "dependencies.json") == actual, "Dependency receipt drift")
    # These retained external pointers remain stale; their bytes are accounted
    # for, but this process's resolver above must select the bound worktree.
    meta = load(ROOT / MIGRATION / "binding.json")["external_environment_source_metadata"]
    for row in meta:
        require(digest(r["no_links"](row["path"])) == row["sha256"], "External editable metadata drift")
    return {"official_asset_count": len(assets), "dependency_count": len(actual["packages"]),
            "xml_documents": len(resources["xml_documents"]), "module_origins": origins}


def source_paths():
    # Include the entire reviewed PR22 closure and all new operational files.
    paths = set(load(ROOT / MIGRATION / "source_manifest.json")["files"])
    paths.update(MIGRATION + "/" + name for name in ("source_manifest.json", "readiness_manifest.json"))
    paths.update(p.relative_to(ROOT).as_posix() for p in HERE.rglob("*") if p.is_file()
                 and p.suffix in (".py", ".ps1", ".cmd", ".bat", ".sh"))
    paths.update(NAMESPACE + "/" + n for n in (".gitattributes", "binding.json", "dependencies.json"))
    return paths


def verify_sources():
    r = helpers()
    require(digest(ROOT / MIGRATION / "source_manifest.json") == MIGRATION_SOURCE_SHA
            and digest(ROOT / MIGRATION / "readiness_manifest.json") == MIGRATION_READY_SHA, "PR22 receipt drift")
    source = load(HERE / "source_manifest.json")
    require(source["base_head"] == BASE_HEAD and source["namespace"] == NAMESPACE
            and source["physics_authorized"] is False, "Wrong source identity")
    require(set(source["files"]) == source_paths(), "Source membership drift")
    code = {p for p in source_paths() if p.startswith(NAMESPACE + "/") and Path(p).suffix == ".py"}
    require(set(source["execution_code_files"]) == code, "Code closure drift")
    require(re.fullmatch(r"[0-9a-f]{40}", source["execution_code_head"]), "Exact code HEAD required")
    subprocess.run(["git", "merge-base", "--is-ancestor", source["execution_code_head"], "HEAD"], cwd=ROOT, check=True)
    for name, sha in source["files"].items():
        require(digest(r["checked_path"](ROOT, name)) == sha, "Source byte drift: " + name)
        if name in code:
            require(hashlib.sha256(git("show", source["execution_code_head"] + ":" + name)).hexdigest() == sha,
                    "Code differs from pinned Git bytes: " + name)
    return source


def expected_binding():
    return {"source_root": str(ROOT), "base_head": BASE_HEAD, "namespace": NAMESPACE,
            "migration_readiness_sha256": MIGRATION_READY_SHA,
            "migration_source_sha256": MIGRATION_SOURCE_SHA,
            "acquisition_integrated": True, "physics_authorized": False,
            "owner_physics_authorization": None,
            "authority_scope": "TRUSTED_SERIAL_EXPERIMENT_ONLY_NO_PRODUCTION_IDENTITY"}


def authorize_operation(operation, authorize_physics):
    require(operation in ("acquire", "worker"), "Unknown physical operation")
    if not authorize_physics:
        raise PermissionError("Separate Owner physics authorization required; flag absent")
    # No Owner acquisition approval exists in this freeze. A CLI switch or
    # caller-made file cannot replace that review. Future approval needs a new
    # explicitly reviewed authorization binding/readiness, not an environment flag.
    raise PermissionError("OWNER_PHYSICS_AUTHORIZATION_NOT_GRANTED_IN_THIS_FREEZE")


def check_target(*, expected_sha, execution_head):
    clean_process()
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha or ""), "Exact Readiness SHA required")
    require(expected_sha not in (MIGRATION_READY_SHA, helpers()["ORIGINAL_READY_SHA"]), "Old Readiness cannot bind acquisition entry")
    require(digest(HERE / "readiness_manifest.json") == expected_sha, "Readiness SHA mismatch")
    identity = check_identity(execution_head)
    ready = load(HERE / "readiness_manifest.json")
    require(ready["namespace"] == NAMESPACE and ready["base_head"] == BASE_HEAD and ready["status"] == STATUS
            and ready["physics_authorized"] is False and ready["acquisition_integrated"] is True, "Wrong Readiness identity/authority")
    require(load(HERE / "binding.json") == expected_binding(), "Entry binding/authority drift")
    source = verify_sources()
    require(ready["execution_code_head"] == source["execution_code_head"], "Code HEAD binding drift")
    require(ready["source_manifest_sha256"] == digest(HERE / "source_manifest.json"), "Source manifest binding drift")
    old = load(ROOT / ORIGINAL / "readiness_manifest.json")
    require(all(ready[k] == old[k] for k in ("freeze", "cell_ids", "hold_window_s", "hold_native_steps")), "Scientific freeze changed")
    required = {NAMESPACE + "/" + n for n in ("source_manifest.json", "binding.json", "dependencies.json", "offline_test_receipt.json")}
    require(required <= set(ready["sha256"]), "Incomplete Readiness receipt closure")
    for name, sha in ready["sha256"].items():
        require(digest(helpers()["checked_path"](ROOT, name)) == sha, "Readiness member drift: " + name)
    env = environment()
    clean_process()
    return dict(identity, **env, status="ENTRY_PREFLIGHT_PASS_NO_PHYSICS", source_count=len(source["files"]),
                source_manifest_sha256=ready["source_manifest_sha256"], readiness_sha256=expected_sha,
                physics_authorized=False, physics_steps=0, policy_inferences=0, model_loads=0)
