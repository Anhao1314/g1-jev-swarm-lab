"""New M2.6A entry; every process gates before loading the frozen adapter.

No physical authorization is granted by this nonphysical integration freeze.
The legacy entry remains unchanged and is not an alternate migrated entry.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[2]


def gate_module():
    # Load by exact file, never by ambiguous `from readiness import ...`.
    spec = importlib.util.spec_from_file_location("m26_entry_readiness", HERE / "readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_adapter(gate, args):
    """Reachable only after process gate + explicit authorization check."""
    gate.check_target(expected_sha=args.readiness_sha256, execution_head=args.execution_head)
    gate.authorize_operation(args.command, args.authorize_physics)
    path = ROOT / gate.ORIGINAL / "acquire.py"
    # Already in verified source closure; check again at the load seam.
    source = gate.load(HERE / "source_manifest.json")
    gate.require(gate.digest(path) == source["files"][path.relative_to(ROOT).as_posix()], "Adapter bytes changed at load")
    spec = importlib.util.spec_from_file_location("m26_entry_frozen_p1_adapter", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.HERE = HERE
    adapter.READINESS = HERE / "readiness_manifest.json"
    def bound_preflight(sha):
        gate.require(sha == args.readiness_sha256, "Adapter requested different Readiness")
        receipt = gate.check_target(expected_sha=sha, execution_head=args.execution_head)
        gate.authorize_operation(args.command, args.authorize_physics)
        return gate.load(ROOT / gate.DESIGN), gate.load(adapter.M24), receipt
    adapter.preflight = bound_preflight
    original_backend = adapter.production_backend
    @contextmanager
    def guarded_backend(*positional, **keywords):
        bound_preflight(args.readiness_sha256)
        with original_backend(*positional, **keywords) as backend:
            yield backend
    adapter.production_backend = guarded_backend
    # Supervisor's unchanged worker command uses this namespace's acquire.py.
    # The unchanged prefix audit import resolves only the new audited shim.
    sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
    if "audit" in sys.modules:
        raise ValueError("Preloaded ambiguous audit module forbidden")
    return adapter


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "acquire", "worker"))
    parser.add_argument("--readiness-sha256", required=True)
    parser.add_argument("--execution-head", required=True)
    parser.add_argument("--authorize-physics", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cell-index", type=int)
    parser.add_argument("--prior-native-steps", type=int, default=0)
    args = parser.parse_args(arguments)
    gate = gate_module()
    receipt = gate.check_target(expected_sha=args.readiness_sha256, execution_head=args.execution_head)
    if args.command == "preflight":
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return receipt
    gate.authorize_operation(args.command, args.authorize_physics)
    adapter = checked_adapter(gate, args)
    # Delegate all ordering, no-retry, raw retention, budgets and P1 classifications.
    previous = sys.argv
    try:
        sys.argv = [str(HERE / "acquire.py"), *arguments]
        return adapter.main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    main()
