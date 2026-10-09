"""One-shot new identity freeze. Creates metadata exclusively; no live imports."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).absolute().parent

def write_new(path, data):
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")

def freeze(code_head):
    r = runpy.run_path(str(HERE / "readiness.py"))
    r["clean_process"]()
    r["environment"]()
    r["require"](r["load"](HERE / "binding.json") == r["expected_binding"](), "Binding mismatch")
    paths = r["source_paths"]()
    code = sorted(p for p in paths if p.startswith(r["NAMESPACE"] + "/") and Path(p).suffix == ".py")
    files = {p: r["digest"](r["helpers"]()["checked_path"](r["ROOT"], p)) for p in sorted(paths)}
    for p in code:
        r["require"](hashlib.sha256(r["git"]("show", code_head + ":" + p)).hexdigest() == files[p], "Code freeze drift: " + p)
    source = {"namespace": r["NAMESPACE"], "base_head": r["BASE_HEAD"], "physics_authorized": False,
              "execution_code_head": code_head, "execution_code_files": code, "files": files}
    write_new(HERE / "source_manifest.json", source)
    names = ["source_manifest.json", "binding.json", "dependencies.json", "offline_test_receipt.json"]
    names += sorted(p.relative_to(HERE).as_posix() for p in (HERE / "receipts").iterdir() if p.is_file())
    ready = {"namespace": r["NAMESPACE"], "base_head": r["BASE_HEAD"], "status": r["STATUS"],
             "execution_code_head": code_head, "physics_authorized": False, "acquisition_integrated": True,
             "source_manifest_sha256": r["digest"](HERE / "source_manifest.json"),
             "sha256": {r["NAMESPACE"] + "/" + n: r["digest"](HERE / n) for n in names},
             "exact_execution_head": "Final HEAD supplied by independent reviewer/Owner, not a self-hashing commit",
             "owner_authorization": "NOT_GRANTED; CLI flag cannot grant permission"}
    old = r["load"](r["ROOT"] / r["ORIGINAL"] / "readiness_manifest.json")
    ready.update({k: old[k] for k in ("freeze", "cell_ids", "hold_window_s", "hold_native_steps")})
    write_new(HERE / "readiness_manifest.json", ready)
    return {"execution_code_head": code_head, "source_count": len(files),
            "readiness_sha256": r["digest"](HERE / "readiness_manifest.json"),
            "source_manifest_sha256": r["digest"](HERE / "source_manifest.json"), "physics_authorized": False}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-head", required=True)
    print(json.dumps(freeze(parser.parse_args().code_head), indent=2))
