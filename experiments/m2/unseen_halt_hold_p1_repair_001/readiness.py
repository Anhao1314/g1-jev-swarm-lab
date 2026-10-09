"""Nonphysical byte/environment gate. No simulator, torch or policy imports.

Package origins are resolved with PathFinder; MJCF references with XML parsing.
This gate cannot grant physics authority or demonstrate real observer equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from importlib.machinery import PathFinder
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DESIGN_HEAD = "d5f33bc5254abdb9775bde9a169e3b360dedb810"
DESIGN = "experiments/m2/unseen_halt_hold_design_001"
OLD = "experiments/m2/cross_state_reliability_readiness_001"
BLOCKED_BUNDLE = "experiments/m2/unseen_halt_hold_readiness_001"
REPAIR_NAMESPACE = "experiments/m2/unseen_halt_hold_p1_repair_001"
BLOCKED_DELIVERY = {
    "head": "98fa234e69a9a81867ed33a07579a3e0904f0758",
    "readiness_sha256": "c052cb3b155a2182be0481f530b3c3dcbee4fa53c74c38313c8e8220923207eb",
    "status": "BLOCKED_FOR_ACQUISITION",
}
SUPERSEDED_IDENTITY = {
    "execution_code_head": "0eb17bb95319027219bc30f24b718a6fd6914d68",
    "readiness_sha256": "cf8aadc054d673a86f8835f205b2a4469fba00bc3fecafaba0a720926649e243",
    "source_manifest_sha256": "2decc94993c3164dfd75c8190e60ba4feb04ba01e1d1c3916a3f371e05315519",
    "status": "BLOCKED_SUPERSEDED_ENGINEERING_CANDIDATE",
}
FORBIDDEN_IMPORTS = ("mujoco", "torch", "g1swarm")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def contained(root, relative):
    require(not Path(relative).is_absolute(), "Absolute manifest path")
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), "Manifest path escapes root")
    return result


def repair_identity(manifest, *, source=False):
    """Old READY receipts are historical evidence, never authority for this repair."""
    require(manifest.get("repair_namespace") == REPAIR_NAMESPACE,
            "Wrong repair namespace; blocked delivery is not current readiness")
    require(manifest.get("blocked_delivery") == BLOCKED_DELIVERY,
            "Missing or changed blocked delivery identity")
    status = "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY" if source else "READY_FOR_OWNER_ACQUISITION_AUTHORIZATION"
    require(manifest.get("status") == status and manifest.get("physics_authorized") is False,
            "Wrong repair status or physics authority")
    require(manifest.get("execution_code_head") != BLOCKED_DELIVERY["head"],
            "Blocked execution HEAD cannot be the repaired execution code")
    require(manifest.get("execution_code_head") != SUPERSEDED_IDENTITY["execution_code_head"],
            "Superseded execution HEAD cannot be current repaired execution code")


def superseded_candidates(root=ROOT, here=HERE):
    """Bind rejected engineering receipts and byte-exact archived original files."""
    archive = here / "superseded_candidate_001"
    require(archive.resolve().is_relative_to(root.resolve()) and not archive.is_symlink(),
            "Superseded archive escapes root")
    for path in archive.rglob("*"):
        require(not path.is_symlink() and path.resolve().is_relative_to(archive.resolve()),
                "Superseded archive contains escaping links")
    rejection = archive / "rejection.json"
    data = load(rejection)
    require(all(data.get(key) == value for key, value in SUPERSEDED_IDENTITY.items()),
            "Superseded engineering candidate identity changed")
    originals = data["source_raw_sha256"]
    require(len(originals) == 25, "Superseded original archive membership changed")
    actual_originals = {path.relative_to(archive / "original_root").as_posix()
                        for path in (archive / "original_root").rglob("*") if path.is_file()}
    require(set(originals) == actual_originals, "Superseded original archive membership mismatch")
    for name, sha in originals.items():
        require(digest(contained(archive / "original_root", name)) == sha,
                "Superseded original bytes changed: " + name)
    for key, filename in (("readiness_sha256", "readiness_manifest.json"),
                          ("source_manifest_sha256", "source_manifest.json")):
        require(digest(archive / "original_root" / REPAIR_NAMESPACE / filename) == data[key],
                "Superseded original receipt hash mismatch")
    return [dict(SUPERSEDED_IDENTITY,
                 rejection_path=rejection.relative_to(root).as_posix(),
                 rejection_sha256=digest(rejection))]


def clean_process():
    require(not any(name in sys.modules for name in FORBIDDEN_IMPORTS),
            "Readiness requires a process without simulator/policy/project imports")


def official_rows(root=ROOT):
    rows = load(root / OLD / "asset_restore.json")["files"]
    require(len(rows) == 91 and len({r["path"] for r in rows}) == 91,
            "Official asset receipt membership changed")
    require(all(r["path"].startswith("third_party/") for r in rows),
            "Nonasset path in official receipt")
    return rows


def verify_assets(root=ROOT):
    rows = official_rows(root)
    for row in rows:
        path = contained(root, row["path"])
        require(path.is_file() and path.stat().st_size == row["bytes"]
                and digest(path) == row["sha256"], "Official asset mismatch: " + row["path"])
    return rows


def restore_assets(source_root, *, root=ROOT):
    """Copy only local official hash-matched assets, never replace an existing file."""
    source_root, root = Path(source_root).resolve(), root.resolve()
    require(source_root != root, "Restore source equals target")
    rows = verify_assets(source_root)  # Complete source check precedes writes.
    require(rows == official_rows(root), "Source/target official receipts differ")
    for row in rows:  # Complete existing target check also precedes writes.
        dest = contained(root, row["path"])
        if dest.exists():
            require(dest.is_file() and dest.stat().st_size == row["bytes"]
                    and digest(dest) == row["sha256"], "Existing asset mismatch")
    copied = 0
    for row in rows:
        dest = contained(root, row["path"])
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        require(contained(root, row["path"]) == dest, "Restore destination changed")
        # Exclusive creation prevents overwriting even when a file appears late.
        with contained(source_root, row["path"]).open("rb") as src, dest.open("xb") as out:
            shutil.copyfileobj(src, out)
        copied += 1
    verify_assets(root)
    return {"status": "VERIFIED_LOCAL_OFFICIAL_ASSETS_NO_PHYSICS",
            "source_root": source_root.as_posix(), "target_root": root.as_posix(),
            "official_asset_count": len(rows), "copied": copied,
            "already_present": len(rows) - copied,
            "official_receipt_sha256": digest(root / OLD / "asset_restore.json"),
            "files": rows, "physics_steps": 0, "policy_inferences": 0, "model_loads": 0}


def xml_resources(root=ROOT):
    """Resolve current MJCF include/mesh/texture file links, never compile a model."""
    start = root / "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml"
    documents, links, visited = [], [], set()
    def visit(path):
        path = path.resolve()
        require(path.is_relative_to(root.resolve()), "MJCF source escapes root")
        if path in visited:
            return
        visited.add(path)
        tree = ET.parse(path).getroot()
        documents.append({"path": path.relative_to(root).as_posix(), "sha256": digest(path)})
        compiler = tree.find("compiler")
        meshdir = compiler.get("meshdir", "") if compiler is not None else ""
        texturedir = compiler.get("texturedir", "") if compiler is not None else ""
        for element in tree.iter():
            reference = element.get("file")
            if reference is None:
                continue
            folder = meshdir if element.tag == "mesh" else texturedir if element.tag == "texture" else ""
            target = (path.parent / folder / reference).resolve()
            require(target.is_relative_to(root.resolve()) and target.is_file(), "Missing/escaping MJCF resource")
            links.append({"source": path.relative_to(root).as_posix(), "reference": reference,
                          "target": target.relative_to(root).as_posix(), "sha256": digest(target)})
            if element.tag == "include":
                visit(target)
    visit(start)
    require(len(documents) == 2 and len(links) == 28, "MJCF closure changed")
    old = load(root / OLD / "xml_resource_check.json")
    require(sorted(links, key=lambda r: (r["source"], r["reference"])) ==
            sorted(old["resource_links"], key=lambda r: (r["source"], r["reference"])),
            "Current XML resources differ from frozen historical links")
    return {"xml_documents": documents, "resource_links": links, "model_compilations": 0}


def dependency_check(root=ROOT):
    expected = load(root / OLD / "dependencies.json")
    require(len(expected["packages"]) == 41, "Dependency closure changed")
    require(platform.python_version() == expected["python"] and
            platform.python_implementation() == expected["implementation"], "Python version mismatch")
    require(Path(sys.executable).resolve() == Path(expected["executable"]).resolve(), "Interpreter path mismatch")
    actual = {name: importlib.metadata.version(name) for name in expected["packages"]}
    require(actual == expected["packages"], "Dependency versions mismatch")
    origins = {}
    for name in ("mujoco", "torch", "numpy", "yaml", "pytest"):
        spec = PathFinder.find_spec(name, sys.path)
        require(spec is not None and spec.origin is not None, "Missing package origin: " + name)
        origin = Path(spec.origin).resolve()
        require(origin.is_relative_to(Path(sys.executable).resolve().parent.parent / "Lib/site-packages"),
                "Unexpected package origin: " + name)
        origins[name] = str(origin)
    project = PathFinder.find_spec("g1swarm", [str(root / "src")])
    require(project is not None and Path(project.origin).resolve() == (root / "src/g1swarm/__init__.py").resolve(),
            "Project source origin mismatch")
    origins["g1swarm"] = str(Path(project.origin).resolve())
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": platform.platform(), "executable": str(Path(sys.executable).resolve()),
            "packages": actual, "module_origins_without_import": origins,
            "editable_pointer_is_not_source_authority": True, "dependency_installs_or_updates": 0}


def expected_source_paths(root=ROOT, here=HERE):
    """Executable/config/history closure, independent of a proposed source list.

    Old manifest paths are reused for membership only: old Windows CRLF execution
    hashes are never represented as current accepted-main Git byte identities.
    """
    old = load(root / "experiments/m2/post_halt_hold_design_001/source_manifest.json")
    require(len(old["files"]) == 254, "Inherited M2.5A source membership changed")
    paths = set(old["files"])
    tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", DESIGN_HEAD], cwd=root,
                          check=True, stdout=subprocess.PIPE, text=True).stdout.splitlines()
    paths.update(name for name in tree if
                 (name.startswith(("src/", "scripts/")) and name.endswith(".py")) or
                 (name.startswith("configs/") and name.endswith((".yaml", ".yml", ".json"))) or
                 name.startswith(DESIGN + "/") or
                 name.startswith("experiments/m2/cross_state_reliability_archives_001/") and name.endswith((".tar.gz", "/manifest.json")))
    paths.update({"experiments/m2/post_halt_hold_qualification_001/raw_manifest.json",
                  "experiments/m2/post_halt_hold_qualification_001/raw/campaign_001.zip",
                  "experiments/m2/post_halt_hold_design_001/source_manifest.json",
                  OLD + "/dependencies.json", OLD + "/asset_restore.json", OLD + "/xml_resource_check.json"})
    blocked_tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", BLOCKED_DELIVERY["head"], "--", BLOCKED_BUNDLE],
                                 cwd=root, check=True, stdout=subprocess.PIPE, text=True).stdout.splitlines()
    require(len(blocked_tree) == 41, "Blocked PR20 bundle membership changed")
    paths.update(blocked_tree)  # Complete failed delivery and its tests/receipts retained.
    superseded_candidates(root, here)
    archive = here / "superseded_candidate_001"
    paths.update(path.relative_to(root).as_posix() for path in archive.rglob("*") if path.is_file())
    prefix = here.relative_to(root).as_posix()
    paths.update(prefix + "/" + p.name for p in here.iterdir() if p.is_file() and
                 (p.suffix == ".py" or p.name in (".gitattributes", "dependencies.json", "assets_receipt.json")))
    require(all(contained(root, name).is_file() for name in paths), "Expected execution source missing")
    return paths


def verify_sources(root=ROOT, here=HERE):
    require(here.resolve() == contained(root, REPAIR_NAMESPACE), "Wrong repair source path")
    manifest = load(here / "source_manifest.json")
    repair_identity(manifest, source=True)
    require(manifest.get("superseded_engineering_candidates") == superseded_candidates(root, here),
            "Superseded candidate source binding mismatch")
    require(manifest["physics_authorized"] is False, "Source freeze cannot authorize physics")
    require(manifest["design_head"] == DESIGN_HEAD, "Wrong frozen design HEAD")
    code_head = manifest["execution_code_head"]
    require(subprocess.run(["git", "merge-base", "--is-ancestor", code_head, "HEAD"],
                           cwd=root, stdout=subprocess.PIPE).returncode == 0,
            "Frozen execution code is not an ancestor of current HEAD")
    design_seal = load(root / DESIGN / "freeze_manifest.json")
    require(len(design_seal["files"]) == 8, "Reviewed design seal membership changed")
    frozen_seal = subprocess.run(["git", "show", DESIGN_HEAD + ":" + DESIGN + "/freeze_manifest.json"],
                                cwd=root, check=True, stdout=subprocess.PIPE).stdout
    require(hashlib.sha256(frozen_seal).hexdigest() == digest(root / DESIGN / "freeze_manifest.json"),
            "Reviewed design seal changed")
    for name, sha in design_seal["files"].items():
        require(digest(contained(root, DESIGN + "/" + name)) == sha, "Reviewed design bytes changed")
    files = manifest["files"]
    require(isinstance(files, dict) and files, "Empty source closure")
    require(set(files) == expected_source_paths(root, here), "Execution source closure membership mismatch")
    code_files = manifest["execution_code_files"]
    require(code_files and len(code_files) == len(set(code_files)), "Missing/duplicate execution code membership")
    require(set(code_files) == {name for name in files if name.startswith(
        "experiments/m2/unseen_halt_hold_p1_repair_001/") and name.endswith(".py")},
        "Execution code membership does not cover new Python sources")
    for name in code_files:
        frozen = subprocess.run(["git", "show", code_head + ":" + name], cwd=root,
                                check=True, stdout=subprocess.PIPE).stdout
        require(hashlib.sha256(frozen).hexdigest() == files[name], "Pinned execution Git code differs from source freeze")
    for name, sha in files.items():
        require(digest(contained(root, name)) == sha, "Execution source mismatch: " + name)
    frozen_protocol = subprocess.run(["git", "show", DESIGN_HEAD + ":" + DESIGN + "/protocol.json"],
                                     cwd=root, check=True, stdout=subprocess.PIPE).stdout
    require(hashlib.sha256(frozen_protocol).hexdigest() == digest(root / DESIGN / "protocol.json"),
            "Frozen scientific protocol differs from reviewed design Git blob")
    require(manifest["design_protocol_sha256"] == digest(root / DESIGN / "protocol.json"), "Protocol binding mismatch")
    for key, filename in (("dependencies_sha256", "dependencies.json"),
                          ("official_assets_receipt_sha256", "assets_receipt.json")):
        require(manifest[key] == digest(here / filename), "Source metadata binding mismatch: " + key)
    return len(files)


def check_target(*, expected_sha=None, root=ROOT, here=HERE, require_manifest=True, execution_head=None):
    clean_process()
    require(here.resolve() == contained(root, REPAIR_NAMESPACE), "Wrong repair readiness path")
    require(expected_sha != BLOCKED_DELIVERY["readiness_sha256"], "Blocked readiness SHA cannot authorize repaired execution")
    require(expected_sha != SUPERSEDED_IDENTITY["readiness_sha256"],
            "Superseded readiness SHA cannot authorize repaired execution")
    if expected_sha is not None:
        require(require_manifest and digest(here / "readiness_manifest.json") == expected_sha,
                "Readiness identity differs from separately frozen expected SHA")
    rows = verify_assets(root)
    resources = xml_resources(root)
    deps = dependency_check(root)
    require(load(here / "dependencies.json") == deps, "Target dependency/origin receipt drift")
    receipt = load(here / "assets_receipt.json")
    require(receipt["files"] == rows and receipt["official_asset_count"] == 91, "New asset receipt drift")
    source_count = verify_sources(root, here) if require_manifest else None
    current_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                                  stdout=subprocess.PIPE, text=True).stdout.strip()
    if execution_head is not None:
        require(current_head == execution_head, "Current HEAD differs from separately frozen execution HEAD")
    if require_manifest:
        readiness = load(here / "readiness_manifest.json")
        repair_identity(readiness)
        source = load(here / "source_manifest.json")
        require(readiness.get("superseded_engineering_candidates") == source.get("superseded_engineering_candidates"),
                "Superseded candidate readiness binding mismatch")
        require(readiness["execution_code_head"] == source["execution_code_head"], "Readiness execution code identity mismatch")
        protocol = load(root / DESIGN / "protocol.json")
        require(readiness["freeze"] == protocol["budget"] and
                readiness["cell_ids"] == [cell["id"] for cell in protocol["cells_in_order"]] and
                readiness["hold_window_s"] == 2.0,
                "Readiness frozen matrix/budget/Hold contract changed")
        require(readiness["physics_authorized"] is False, "Readiness cannot authorize physics")
        require(readiness["source_manifest_sha256"] == digest(here / "source_manifest.json"), "Readiness source binding mismatch")
        for name, sha in readiness["sha256"].items():
            require(digest(contained(root, name)) == sha, "Readiness bound file changed: " + name)
    clean_process()
    return {"status": "TARGET_PREFLIGHT_PASS_NO_PHYSICS" if require_manifest else "TARGET_ENVIRONMENT_PASS_NO_PHYSICS_NOT_FINAL_FREEZE",
            "checked_execution_head": current_head, "expected_execution_head": execution_head,
            "design_head": DESIGN_HEAD, "official_asset_count": len(rows), "dependency_count": len(deps["packages"]),
            "blocked_delivery": BLOCKED_DELIVERY,
            "repair_namespace": REPAIR_NAMESPACE,
            "xml_documents": len(resources["xml_documents"]), "xml_resource_count": len(resources["resource_links"]),
            "execution_source_count": source_count,
            "source_manifest_sha256": digest(here / "source_manifest.json") if require_manifest else None,
            "readiness_sha256": digest(here / "readiness_manifest.json") if require_manifest else None,
            "simulator_imported": False, "policy_runtime_imported": False,
            "physics_steps": 0, "policy_inferences": 0, "model_loads": 0,
            "physics_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-from", type=Path)
    parser.add_argument("--environment-only", action="store_true")
    parser.add_argument("--execution-head")
    parser.add_argument("--expected-sha")
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    require(not (args.restore_from and (args.environment_only or args.execution_head or args.expected_sha)), "Conflicting modes")
    result = restore_assets(args.restore_from) if args.restore_from else check_target(
        expected_sha=args.expected_sha, require_manifest=not args.environment_only, execution_head=args.execution_head)
    if args.write:
        with args.write.open("x", encoding="utf8", newline="\n") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
