"""M2.5A asset restore and target preflight; never imports simulator or policy.

The default command checks bytes and package metadata only. Restoring already
verified official assets is an explicit separate command and writes no Git file
except the requested receipt in this experiment namespace.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import runpy
import shutil
import sys


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
M24 = ROOT / "experiments/m2/cross_state_reliability_readiness_001"
M24_SOURCE = ROOT / "experiments/m2/cross_state_reliability_001/source_manifest.json"
M24_READINESS_SHA256 = "14219b6edc85d8346a97d5e50895d924c1157c6abffab37bd926dbfe4b138f08"
NEW_EXECUTION_FILES = (
    "experiments/m2/post_halt_hold_design_001/.gitattributes",
    "experiments/m2/post_halt_hold_design_001/protocol.json",
    "experiments/m2/post_halt_hold_design_001/freeze_manifest.json",
    "experiments/m2/post_halt_hold_design_001/source_binding.json",
    "experiments/m2/post_halt_hold_design_001/offline_check.py",
    "experiments/m2/post_halt_hold_design_001/acquire.py",
    "experiments/m2/post_halt_hold_design_001/readiness.py",
    "experiments/m2/post_halt_hold_design_001/audit.py",
    "experiments/m2/post_halt_hold_design_001/test_offline_check.py",
    "experiments/m2/post_halt_hold_design_001/test_acquire.py",
    "experiments/m2/post_halt_hold_design_001/test_readiness.py",
    "experiments/m2/post_halt_hold_design_001/test_audit.py",
    "experiments/m2/post_halt_hold_design_001/asset_restore_m25a.json",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


def in_root(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), "Path escapes expected root: " + relative)
    return path


def official_asset_rows(root: Path = ROOT) -> list[dict]:
    receipt = json_file(root / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json")
    rows = receipt["files"]
    require(receipt["asset_count"] == len(rows) == 91, "Official asset count mismatch")
    require(len({row["path"] for row in rows}) == 91, "Duplicate official asset path")
    return rows


def restore_assets(source_root: Path, *, root: Path = ROOT, receipt_path: Path | None = None) -> dict:
    """Copy only hash-matched files absent from this checkout; never overwrite."""
    source_root, root = source_root.resolve(), root.resolve()
    require(source_root != root, "Asset source and target must differ")
    rows = official_asset_rows(root)
    # Validate the complete source *before* any target write.
    for row in rows:
        source = in_root(source_root, row["path"])
        require(source.is_file() and source.stat().st_size == row["bytes"]
                and digest(source) == row["sha256"], "Official asset source mismatch: " + row["path"])
    copied = 0
    for row in rows:
        destination = in_root(root, row["path"])
        if destination.exists():
            require(destination.is_file() and destination.stat().st_size == row["bytes"]
                    and digest(destination) == row["sha256"], "Existing asset mismatch: " + row["path"])
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck containment after making parents; never follow an unexpected link.
        destination = in_root(root, row["path"])
        require(not destination.exists(), "Asset destination appeared during restore")
        shutil.copyfile(in_root(source_root, row["path"]), destination)
        require(destination.stat().st_size == row["bytes"] and digest(destination) == row["sha256"],
                "Copied asset mismatch: " + row["path"])
        copied += 1
    for row in rows:
        destination = in_root(root, row["path"])
        require(destination.is_file() and destination.stat().st_size == row["bytes"]
                and digest(destination) == row["sha256"], "Target asset missing after restore: " + row["path"])
    result = {
        "status": "VERIFIED_OFFICIAL_ASSETS_NO_PHYSICS",
        "source_root": source_root.as_posix(),
        "target_root": root.as_posix(),
        "source_receipt_sha256": digest(root / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"),
        "official_asset_count": len(rows),
        "copied": copied,
        "already_present": len(rows) - copied,
        "model_loads": 0,
        "policy_inferences": 0,
        "physics_steps": 0,
    }
    if receipt_path is not None:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.open("x", encoding="utf8", newline="\n") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    return result


def check_target(*, root: Path = ROOT, here: Path = HERE, require_new_source: bool = True) -> dict:
    """Verify the target environment and full inherited source closure, no physics."""
    root, here = root.resolve(), here.resolve()
    require("mujoco" not in sys.modules and "torch" not in sys.modules,
            "No-physics preflight requires a clean process without simulator or policy runtime imports")
    m24_source = json_file(root / M24_SOURCE.relative_to(ROOT))
    require(len(m24_source["files"]) == 241, "M2.4 source closure count changed")
    for name, expected in m24_source["files"].items():
        require(digest(in_root(root, name)) == expected, "M2.4 source or asset mismatch: " + name)
    require(digest(root / "experiments/m2/cross_state_reliability_readiness_001/readiness_manifest.json")
            == M24_READINESS_SHA256, "Published M2.4 readiness identity changed")
    assets = official_asset_rows(root)
    for row in assets:
        path = in_root(root, row["path"])
        require(path.is_file() and path.stat().st_size == row["bytes"] and digest(path) == row["sha256"],
                "Official asset mismatch: " + row["path"])
    xml = json_file(root / "experiments/m2/cross_state_reliability_readiness_001/xml_resource_check.json")
    require(xml["status"] == "PASS_XML_RESOURCES_WITHOUT_MODEL_COMPILATION"
            and xml["xml_documents"] == 2 and len(xml["resource_links"]) == 28,
            "Retained XML resource receipt mismatch")
    for link in xml["resource_links"]:
        require(digest(in_root(root, link["target"])) == link["sha256"],
                "XML resource target mismatch: " + link["target"])
    deps = json_file(root / "experiments/m2/cross_state_reliability_readiness_001/dependencies.json")
    require(len(deps["packages"]) == 41, "Dependency closure count changed")
    require(platform.python_version() == deps["python"] and platform.python_implementation() == deps["implementation"],
            "Python runtime mismatch")
    require(Path(sys.executable).resolve() == Path(deps["executable"]).resolve(), "Interpreter path mismatch")
    for package, version in deps["packages"].items():
        require(importlib.metadata.version(package) == version, "Dependency version mismatch: " + package)

    candidate = runpy.run_path(str(here / "offline_check.py"))["validate_sources"](root=root, here=here)
    new_count = None
    source_path = here / "source_manifest.json"
    if require_new_source:
        require(source_path.is_file(), "M2.5A execution source manifest missing")
    if source_path.is_file():
        new_source = json_file(source_path)
        require(new_source["status"] == "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY", "M2.5A source status mismatch")
        require(new_source["physics_authorized"] is False, "M2.5A source may not authorize physics")
        require(new_source["baseline_main_commit"] == candidate["baseline_main_commit"], "M2.5A source base mismatch")
        require(new_source["inherited_m24_source_sha256"] == digest(root / M24_SOURCE.relative_to(ROOT)),
                "Inherited M2.4 source identity mismatch")
        require(set(new_source["files"]) == set(m24_source["files"]) | set(NEW_EXECUTION_FILES),
                "M2.5A execution source closure changed")
        require(all(new_source["files"][name] == expected for name, expected in m24_source["files"].items()),
                "M2.5A inherited source hashes changed")
        for name, expected in new_source["files"].items():
            require(digest(in_root(root, name)) == expected, "M2.5A source mismatch: " + name)
        new_count = len(new_source["files"])
    require("mujoco" not in sys.modules and "torch" not in sys.modules,
            "No-physics preflight imported simulator or policy runtime")
    return {
        "status": "TARGET_PREFLIGHT_PASS_NO_PHYSICS" if require_new_source else "TARGET_INHERITED_PREFLIGHT_PASS_NO_PHYSICS",
        "baseline_main_commit": candidate["baseline_main_commit"],
        "inherited_source_sha256": digest(root / M24_SOURCE.relative_to(ROOT)),
        "inherited_readiness_sha256": M24_READINESS_SHA256,
        "official_asset_receipt_sha256": digest(root / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"),
        "dependency_receipt_sha256": digest(root / "experiments/m2/cross_state_reliability_readiness_001/dependencies.json"),
        "candidate_freeze_sha256": digest(here / "freeze_manifest.json"),
        "m25a_execution_source_sha256": digest(source_path) if source_path.is_file() else None,
        "inherited_source_count": len(m24_source["files"]),
        "official_asset_count": len(assets),
        "dependency_count": len(deps["packages"]),
        "xml_resource_count": len(xml["resource_links"]),
        "m25a_execution_source_count": new_count,
        "candidate_file_count": candidate["candidate_files_verified"],
        "simulator_imported": "mujoco" in sys.modules,
        "policy_runtime_imported": "torch" in sys.modules,
        "physics_steps": 0,
        "policy_inferences": 0,
    }


def freeze_execution_sources(*, root: Path = ROOT, here: Path = HERE) -> dict:
    """Write one source freeze after the independent no-physics inherited check."""
    inherited = check_target(root=root, here=here, require_new_source=False)
    old_path = root / M24_SOURCE.relative_to(ROOT)
    old = json_file(old_path)
    files = dict(old["files"])
    for name in NEW_EXECUTION_FILES:
        require(name not in files, "New source overlaps inherited closure: " + name)
        files[name] = digest(in_root(root, name))
    freeze = {
        "status": "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY",
        "physics_authorized": False,
        "baseline_main_commit": inherited["baseline_main_commit"],
        "inherited_m24_source_sha256": digest(old_path),
        "inherited_m24_file_count": len(old["files"]),
        "official_asset_count": inherited["official_asset_count"],
        "dependency_count": inherited["dependency_count"],
        "dependencies_sha256": digest(root / "experiments/m2/cross_state_reliability_readiness_001/dependencies.json"),
        "files": dict(sorted(files.items())),
    }
    path = here / "source_manifest.json"
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(freeze, stream, indent=2)
        stream.write("\n")
    return {"status": "EXECUTION_SOURCE_FREEZE_WRITTEN_NO_PHYSICS", "path": path.as_posix(),
            "sha256": digest(path), "files": len(files), "physics_authorized": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-from", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--inherited-only", action="store_true")
    parser.add_argument("--freeze-source", action="store_true")
    parser.add_argument("--write-check", type=Path)
    args = parser.parse_args()
    if args.restore_from:
        require(not args.freeze_source and not args.inherited_only and args.write_check is None,
                "Asset restore cannot combine with preflight/freeze")
        require(args.receipt is not None, "--receipt required for asset restore")
        result = restore_assets(args.restore_from, receipt_path=args.receipt)
    elif args.freeze_source:
        require(not args.inherited_only and args.receipt is None and args.write_check is None,
                "Source freeze options conflict")
        result = freeze_execution_sources()
    else:
        require(args.receipt is None, "--receipt is only valid with --restore-from")
        result = check_target(require_new_source=not args.inherited_only)
        if args.write_check:
            args.write_check.parent.mkdir(parents=True, exist_ok=True)
            with args.write_check.open("x", encoding="utf8", newline="\n") as stream:
                json.dump(result, stream, indent=2, sort_keys=True)
                stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
