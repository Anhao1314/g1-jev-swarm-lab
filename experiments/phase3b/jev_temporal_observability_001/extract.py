"""Read-only extraction of fixed historical snapshots for Phase 3B.1a.

No simulator or provider imports are permitted here. The source traces do not
contain planar pose, heading, velocity, or reference tracking errors.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PRIOR = ROOT / "experiments/phase3b/jev_risk_shadow_001"
TRACE_DIR = ROOT / "experiments/phase3a/transition_learning_001/evidence/baseline/traces"
SNAPSHOTS = (0.0, 1.0, 2.0)
RECORDED = (
    "height_m", "tilt_deg", "nominal_command", "deterministic_command",
    "applied_command", "reset_count",
)
UNAVAILABLE = (
    "base_xy", "heading", "route_frame_planar_velocity", "yaw_rate",
    "local_lateral_error", "reference_correction_error",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trace_path(case_id: str) -> Path:
    plain = TRACE_DIR / f"frozen_baseline--{case_id}.jsonl"
    gzipped = TRACE_DIR / f"frozen_baseline--{case_id}.jsonl.gz"
    found = [p for p in (plain, gzipped) if p.is_file()]
    if len(found) != 1:
        raise ValueError(f"expected exactly one historical trace for {case_id}")
    return found[0]


def load_trace(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def fixed_snapshot(rows: list[dict], node_index: int, elapsed: float, node_duration: float) -> dict:
    """Select an actually recorded sample, never interpolate or use endpoint data."""
    if elapsed >= node_duration - 1e-8:
        return {"requested_elapsed_s": elapsed, "available": False, "reason": "at_or_after_node_endpoint"}
    matches = [r for r in rows if r["node_index"] == node_index and abs(r["elapsed_s"] - elapsed) <= 1e-8]
    if len(matches) != 1:
        return {"requested_elapsed_s": elapsed, "available": False, "reason": "recorded_sample_missing"}
    row = matches[0]
    missing = [field for field in RECORDED if field not in row]
    if missing:
        raise ValueError(f"historical trace lacks declared recorded fields: {missing}")
    return {
        "requested_elapsed_s": elapsed,
        "available": True,
        "recorded_elapsed_s": row["elapsed_s"],
        "recorded": {field: row[field] for field in RECORDED},
        "unavailable": list(UNAVAILABLE),
    }


def prior_class(row: dict) -> str:
    if not row["availability"]:
        return "unavailable"
    if row["false_safe"]:
        return "false_safe"
    if row["false_alarm"]:
        return "false_alarm"
    return "true_positive" if row["strict_violation"] else "true_safe"


def build() -> dict:
    protocol_path = STUDY / "protocol.json"
    protocol = read_json(protocol_path)
    if protocol["snapshots_elapsed_s"] != list(SNAPSHOTS):
        raise ValueError("fixed snapshot schedule changed")
    if protocol["recorded_dynamic_fields"] != list(RECORDED):
        raise ValueError("fixed recorded field allowlist changed")
    if protocol["candidate_geometric_fields"] != list(UNAVAILABLE):
        raise ValueError("fixed unavailable field list changed")
    benchmark_path, result_path = PRIOR / "benchmark.json", PRIOR / "result.json"
    benchmark, result = read_json(benchmark_path), read_json(result_path)
    if digest(benchmark_path) != result["benchmark_sha256"]:
        raise ValueError("prior scored result is not bound to frozen benchmark")
    if len(benchmark["cells"]) != 24 or len(benchmark["assessment_units"]["geometry_only"]) != 18:
        raise ValueError("prior frozen membership changed")
    prior = {cell: row for row in result["rows"] if row["variant"] == "geometry_only" for cell in row["source_cell_ids"]}
    if set(prior) != {c["cell_id"] for c in benchmark["cells"]}:
        raise ValueError("prior prediction coverage does not match frozen cells")
    summary_path = ROOT / "experiments/phase3a/transition_learning_001/evidence/baseline/evaluation_summary.json"
    summary = read_json(summary_path)
    records = {r["case_id"]: r for r in summary["records"] if r["treatment"] == "frozen_baseline"}
    paths = {c["case_id"]: trace_path(c["case_id"]) for c in benchmark["cells"]}
    traces = {case: load_trace(path) for case, path in paths.items()}
    cells = []
    for cell in benchmark["cells"]:
        case, index = cell["case_id"], cell["node_index"]
        node = records[case]["nodes"][index]
        if node["skill"] != "walk_forward" or bool(node["envelope"]["strict_violation"]) != cell["strict_violation"]:
            raise ValueError(f"source label or node mismatch: {cell['cell_id']}")
        snapshots = [fixed_snapshot(traces[case], index, time, node["duration_s"]) for time in SNAPSHOTS]
        entry, second = snapshots[0], snapshots[2]
        trend = None
        if entry["available"] and second["available"]:
            trend = {
                "height_delta_2s_minus_entry_m": second["recorded"]["height_m"] - entry["recorded"]["height_m"],
                "abs_tilt_delta_2s_minus_entry_deg": abs(second["recorded"]["tilt_deg"]) - abs(entry["recorded"]["tilt_deg"]),
            }
        prediction = prior[cell["cell_id"]]
        cells.append({
            "cell_id": cell["cell_id"], "case_id": case, "node_index": index,
            "family": cell["family"], "strict_violation": cell["strict_violation"],
            "prior_jev_class": prior_class(prediction),
            "prior_paired_unit_id": prediction["paired_unit_id"],
            "snapshots": snapshots, "predeclared_trend": trend,
        })
    return {
        "schema": "phase3b1a_historical_trace_snapshots_v1",
        "status": "seen_development_trace_audit_only",
        "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in
                          [protocol_path, benchmark_path, result_path, summary_path, *sorted(set(paths.values()))]},
        "source_cells": 24, "prior_assessment_units": 18,
        "snapshots_elapsed_s": list(SNAPSHOTS),
        "field_availability": {"recorded": list(RECORDED), "unavailable_in_trace": list(UNAVAILABLE)},
        "cells": cells,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8", newline="\n")
        print(f"wrote {args.output}")
    else:
        print(output)
