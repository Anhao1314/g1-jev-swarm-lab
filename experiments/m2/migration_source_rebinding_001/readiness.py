"""Migration-only stdlib preflight; never grants acquisition or physics authority.

The PR21 source gate remains immutable. This gate proves a separately frozen
worktree identity and permits exactly one dependency-origin delta: g1swarm.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys

SOURCE_ROOT = Path("D:/webcodex/mujoco-g1/main-codex")
ROOT = SOURCE_ROOT
NAMESPACE = "experiments/m2/migration_source_rebinding_001"
HERE = Path(__file__).absolute().parent
BASE_HEAD = "3082e2b92b5b18171e06295d1c2d09af39f430ac"
ORIGINAL = "experiments/m2/unseen_halt_hold_p1_repair_001"
ORIGINAL_SOURCE_SHA = "27c6157625cd5853dfd735040555d024ff004d5b9da194c8827e974afb1fbd48"
ORIGINAL_READY_SHA = "7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af"
ORIGIN = "https://github.com/Anhao1314/g1-jev-swarm-lab.git"
COMMON_DIR = Path("D:/webcodex/mujoco-g1/repo/.git")
STATUS = "MIGRATION_PREFLIGHT_FROZEN_NO_PHYSICS_AUTHORITY"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def no_links(path):
    """Reject symlinks, junctions and every reparse ancestor before resolution."""
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            require(not candidate.is_symlink() and not (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                "Source path alias/reparse forbidden: " + str(candidate))
    require(path == path.resolve(), "Source path alias forbidden: " + str(path))
    return path


def checked_path(root, relative):
    require(isinstance(relative, str) and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts and "\\" not in relative,
            "Invalid source-relative path")
    path = no_links(Path(root) / relative)
    require(path.is_relative_to(Path(root).absolute()), "Source path escapes root")
    return path


def validate_location(root=ROOT, here=HERE):
    require(Path(root).absolute() == SOURCE_ROOT, "Wrong fixed source root")
    no_links(root)
    require(Path(here).absolute() == SOURCE_ROOT / NAMESPACE, "Wrong migration namespace")
    no_links(here)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def git_tree(root, revision):
    result = {}
    for record in git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if record:
            identity, name = record.split(b"\t", 1)
            result[name.decode("utf8")] = identity.decode("ascii")
    return result


def git_location(root=ROOT):
    """Bind Git's resolved worktree registration, not only the shell directory."""
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip())
    require(no_links(top) == SOURCE_ROOT, "Git toplevel is not fixed source worktree")
    directory = Path(git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    expected = COMMON_DIR / "worktrees/main-codex"
    require(no_links(directory) == expected, "Git per-worktree directory mismatch")
    pointer = checked_path(root, ".git").read_text(encoding="utf8").strip()
    require(pointer == "gitdir: " + expected.as_posix(), "Worktree Git pointer mismatch")
    registered = git(root, "worktree", "list", "--porcelain").decode().split("\n\n")
    matching = [block for block in registered if block.splitlines()
                and block.splitlines()[0] == "worktree " + SOURCE_ROOT.as_posix()]
    require(len(matching) == 1, "Source worktree registration missing/duplicated")
    actual = git(root, "rev-parse", "HEAD").decode().strip()
    require("HEAD " + actual in matching[0].splitlines(), "Registered worktree HEAD mismatch")
    require((directory / "gitdir").read_text(encoding="utf8").strip()
            == (SOURCE_ROOT / ".git").as_posix(), "Git worktree backlink mismatch")
    return {"git_toplevel": top.as_posix(), "git_directory": directory.as_posix(),
            "registered_head": actual}


def git_identity(root, execution_head):
    require(isinstance(execution_head, str) and re.fullmatch(r"[0-9a-f]{40}", execution_head),
            "Exact full execution HEAD required")
    require(not any(name in os.environ for name in
                    ("GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")),
            "Git identity override forbidden")
    actual = git(root, "rev-parse", "HEAD").decode().strip()
    require(actual == execution_head, "Current HEAD differs from exact execution HEAD")
    location = git_location(root)
    require(git(root, "remote", "get-url", "origin").decode().strip().rstrip("/").removesuffix(".git")
            == ORIGIN.removesuffix(".git"), "Git origin mismatch")
    common = Path(git(root, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = Path(root) / common
    require(no_links(common) == COMMON_DIR, "Wrong isolated Git common store")
    require(not (common / "objects/info/alternates").exists(), "External Git object alternates forbidden")
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE_HEAD, "HEAD"], cwd=root, check=True)
    base, current = git_tree(root, BASE_HEAD), git_tree(root, "HEAD")
    require(len(base) == 2787, "Original Git tree membership changed")
    require(all(current.get(name) == identity for name, identity in base.items()),
            "Historical Git mode/blob changed")
    require(all(name in base or name.startswith(NAMESPACE + "/") for name in current),
            "Unexpected tracked additions outside migration namespace")
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "Dirty/untracked worktree")
    ignored = git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split(b"\0")
    require(not any(Path(name.decode()).suffix in (".py", ".ps1", ".cmd", ".bat", ".sh")
                    for name in ignored if name), "Ignored untracked executable forbidden")
    return dict(location, execution_head=actual, preserved_git_entries=len(base),
                origin=ORIGIN, git_common_dir=common.as_posix())


def original_gate(root):
    source = checked_path(root, ORIGINAL + "/source_manifest.json")
    ready = checked_path(root, ORIGINAL + "/readiness_manifest.json")
    require(digest(source) == ORIGINAL_SOURCE_SHA and digest(ready) == ORIGINAL_READY_SHA,
            "Immutable PR21 receipt identity mismatch")
    # Pin helper bytes before executing its stdlib definitions. No mutation.
    helper = checked_path(root, ORIGINAL + "/readiness.py")
    expected = load(source)["files"][ORIGINAL + "/readiness.py"]
    require(digest(helper) == expected, "Original helper source mismatch")
    return runpy.run_path(str(helper), run_name="migration_immutable_pr21_helpers")


def verify_original(root=ROOT):
    old = original_gate(root)
    old["clean_process"]()
    manifest = load(root / ORIGINAL / "source_manifest.json")
    require(len(manifest["files"]) == 438, "Original source count changed")
    for name in manifest["files"]:
        checked_path(root, name)
    require(old["verify_sources"](root, root / ORIGINAL) == 438, "Original source check failed")
    assets = old["verify_assets"](root)
    resources = old["xml_resources"](root)
    for name, sha in load(root / ORIGINAL / "readiness_manifest.json")["sha256"].items():
        require(digest(checked_path(root, name)) == sha, "Original readiness member drift: " + name)
    return old, assets, resources


def dependency_check(root=ROOT, here=HERE):
    controlled_source_path(root)
    old = original_gate(root)
    actual = old["dependency_check"](root)
    historical = load(root / ORIGINAL / "dependencies.json")
    permitted = dict(historical)
    permitted["module_origins_without_import"] = dict(historical["module_origins_without_import"])
    project = str(checked_path(root, "src/g1swarm/__init__.py"))
    permitted["module_origins_without_import"]["g1swarm"] = project
    require(actual == permitted, "Dependency delta exceeds g1swarm source rebinding")
    require(load(here / "dependencies.json") == actual, "Migration dependency receipt drift")
    for value in actual["module_origins_without_import"].values():
        no_links(value)
    no_links(actual["executable"])
    return actual


def controlled_source_path(root=ROOT):
    """Bind this preflight's resolver; do not edit the external editable install."""
    require(Path(root).absolute() == SOURCE_ROOT, "Wrong controlled source root")
    source = no_links(Path(root) / "src")
    original_gate(root)["clean_process"]()
    spelling = str(source)
    if not sys.path or sys.path[0] != spelling:
        sys.path.insert(0, spelling)
    spec = PathFinder.find_spec("g1swarm", sys.path)
    require(spec is not None and spec.origin is not None
            and Path(spec.origin).absolute() == source / "g1swarm/__init__.py",
            "Actual controlled project resolver origin mismatch")
    no_links(spec.origin)
    return str(Path(spec.origin).absolute())


def external_environment_source_metadata():
    """Freeze existing editable source indirection without executing/importing it."""
    historical = load(SOURCE_ROOT / ORIGINAL / "dependencies.json")
    site = Path(historical["executable"]).parent.parent / "Lib/site-packages"
    pointer = site / "__editable__.g1_jev_swarm_lab-0.0.0.pth"
    distribution = importlib.metadata.distribution("g1-jev-swarm-lab")
    direct = Path(distribution.locate_file("g1_jev_swarm_lab-0.0.0.dist-info/direct_url.json"))
    require(direct.absolute().is_relative_to(site.absolute()), "Editable distribution metadata escapes interpreter")
    return [{"path": str(no_links(path)), "sha256": digest(path), "kind": kind}
            for path, kind in ((pointer, "pth"), (direct, "direct_url"))]


def verify_binding(root=ROOT, here=HERE):
    binding = load(here / "binding.json")
    old = load(root / ORIGINAL / "dependencies.json")
    required = {"source_root": str(SOURCE_ROOT), "namespace": NAMESPACE,
                "base_head": BASE_HEAD, "original_source_sha256": ORIGINAL_SOURCE_SHA,
                "original_readiness_sha256": ORIGINAL_READY_SHA,
                "git_common_dir": str(COMMON_DIR), "origin_url": ORIGIN,
                "physics_authorized": False,
                "acquisition_integrated": False,
                "source_selection": "migration preflight explicitly prepends the bound worktree src; stale external editable metadata retained",
                "external_environment_source_metadata": external_environment_source_metadata(),
                "allowed_dependency_delta": {
                    "module": "g1swarm",
                    "old": old["module_origins_without_import"]["g1swarm"],
                    "new": str(checked_path(root, "src/g1swarm/__init__.py"))}}
    require(binding == required, "Migration binding identity/delta mismatch")
    return binding


def verify_archive(root=ROOT, here=HERE):
    archive = load(here / "archive_index.json")
    actual = {p.relative_to(root).as_posix() for p in (here / "evidence").rglob("*") if p.is_file()}
    require(len(archive) == 34 and set(archive) == actual, "Prior failure archive membership mismatch")
    for name, row in archive.items():
        require(digest(checked_path(root, name)) == row["sha256"], "Prior failure receipt changed: " + name)
    return len(archive)


def expected_source_paths(root=ROOT, here=HERE):
    paths = set(load(root / ORIGINAL / "source_manifest.json")["files"])
    bundle = {name for name in git_tree(root, BASE_HEAD) if name.startswith(ORIGINAL + "/")}
    require(len(bundle) == 85, "Full immutable PR21 bundle membership changed")
    paths.update(bundle)
    # Enumerate independently of the proposed manifest, including nested code.
    paths.update(p.relative_to(root).as_posix() for p in here.rglob("*") if p.is_file()
                 and p.suffix in (".py", ".ps1", ".cmd", ".bat", ".sh"))
    paths.update({NAMESPACE + "/dependencies.json", NAMESPACE + "/binding.json"})
    paths.update(p.relative_to(root).as_posix() for p in (here / "evidence").rglob("*") if p.is_file())
    paths.add(NAMESPACE + "/archive_index.json")
    paths.add(NAMESPACE + "/.gitattributes")
    return paths


def verify_sources(root=ROOT, here=HERE):
    manifest = load(here / "source_manifest.json")
    require(manifest.get("namespace") == NAMESPACE and manifest.get("base_head") == BASE_HEAD
            and manifest.get("physics_authorized") is False, "Migration source identity mismatch")
    require(set(manifest["files"]) == expected_source_paths(root, here), "Migration source membership mismatch")
    code = {name for name in manifest["files"] if name.startswith(NAMESPACE + "/")
            and not name.startswith(NAMESPACE + "/evidence/")
            and Path(name).suffix in (".py", ".ps1", ".cmd", ".bat", ".sh")}
    require(code and set(manifest["execution_code_files"]) == code, "Migration executable membership mismatch")
    code_head = manifest["execution_code_head"]
    require(re.fullmatch(r"[0-9a-f]{40}", code_head), "Full execution code HEAD required")
    subprocess.run(["git", "merge-base", "--is-ancestor", code_head, "HEAD"], cwd=root, check=True)
    for name, sha in manifest["files"].items():
        require(digest(checked_path(root, name)) == sha, "Migration source byte drift: " + name)
        if name in code:
            require(hashlib.sha256(git(root, "show", code_head + ":" + name)).hexdigest() == sha,
                    "Migration executable differs from pinned Git bytes: " + name)
    return len(manifest["files"])


def check_target(*, expected_sha, execution_head, root=ROOT, here=HERE):
    validate_location(root, here)
    require(isinstance(expected_sha, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha),
            "Explicit full Readiness SHA required")
    require(expected_sha != ORIGINAL_READY_SHA, "Historical Readiness cannot authorize migration identity")
    require(digest(checked_path(root, NAMESPACE + "/readiness_manifest.json")) == expected_sha,
            "Migration Readiness SHA mismatch")
    identity = git_identity(root, execution_head)  # Wrong HEAD rejected before dependency work.
    old, assets, resources = verify_original(root)
    verify_binding(root, here)
    verify_archive(root, here)
    deps = dependency_check(root, here)
    count = verify_sources(root, here)
    ready = load(here / "readiness_manifest.json")
    source = load(here / "source_manifest.json")
    historical = load(root / ORIGINAL / "readiness_manifest.json")
    require(ready.get("status") == STATUS and ready.get("namespace") == NAMESPACE
            and ready.get("physics_authorized") is False and ready.get("base_head") == BASE_HEAD,
            "Migration Readiness identity/authority mismatch")
    require(ready.get("execution_code_head") == source["execution_code_head"], "Code HEAD binding mismatch")
    require(all(ready.get(key) == historical[key] for key in
                ("freeze", "cell_ids", "hold_window_s", "hold_native_steps")), "Scientific freeze changed")
    require(ready.get("source_manifest_sha256") == digest(here / "source_manifest.json"), "Source binding mismatch")
    required = {NAMESPACE + "/" + name for name in
                ("source_manifest.json", "dependencies.json", "binding.json", "offline_test_receipt.json", "archive_index.json")}
    require(required <= set(ready["sha256"]), "Missing migration readiness bindings")
    for name, sha in ready["sha256"].items():
        require(digest(checked_path(root, name)) == sha, "Migration bound receipt drift: " + name)
    old["clean_process"]()
    return dict(identity, status="MIGRATION_TARGET_PREFLIGHT_PASS_NO_PHYSICS",
                source_root=SOURCE_ROOT.as_posix(), execution_source_count=count,
                original_source_count=438, official_asset_count=len(assets),
                dependency_count=len(deps["packages"]), xml_documents=len(resources["xml_documents"]),
                xml_resource_count=len(resources["resource_links"]), readiness_sha256=expected_sha,
                source_manifest_sha256=digest(here / "source_manifest.json"),
                physics_authorized=False, physics_steps=0, policy_inferences=0, model_loads=0,
                authority="PREFLIGHT_ONLY_NOT_ACQUISITION_AUTHORIZATION")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--execution-head", required=True)
    args = parser.parse_args()
    print(json.dumps(check_target(expected_sha=args.expected_sha, execution_head=args.execution_head),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
