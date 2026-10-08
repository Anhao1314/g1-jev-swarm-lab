"""Serial, bounded offline Jev risk shadow.  Explicit CLI only; no robot imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from client import evaluate_once
from score import LOW_CONFIDENCE_BELOW, RISK_THRESHOLD, VARIANTS, score

TIMEOUT_S = 30.0
MAX_CALLS = 36
MAX_CONSECUTIVE_FAILURES = 3
MAX_WALL_S = 300.0


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _write_once(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _validate_protocol(protocol: dict) -> None:
    if (protocol.get("schema") != "phase3b1_jev_risk_shadow_protocol_v1"
            or protocol.get("status") != "FROZEN_BEFORE_SCORED_CALLS"
            or protocol.get("model") != "jev-latest"
            or protocol.get("primary_view") != VARIANTS[0]
            or protocol.get("secondary_view") != VARIANTS[1]
            or protocol.get("decision_threshold") != RISK_THRESHOLD
            or protocol.get("low_confidence_cutoff") != LOW_CONFIDENCE_BELOW):
        raise ValueError("protocol identity or scoring contract mismatch")
    budget = protocol.get("scored_call_budget", {})
    if budget != {
        "max_calls": MAX_CALLS, "concurrency": 1, "attempts_per_unit": 1,
        "timeout_seconds": TIMEOUT_S,
        "stop_after_consecutive_transport_failures": MAX_CONSECUTIVE_FAILURES,
        "wall_clock_cap_seconds": MAX_WALL_S,
    }:
        raise ValueError("protocol call budget mismatch")


def run(benchmark_path: Path, protocol_path: Path, output_dir: Path) -> dict:
    """Run each frozen unit/view once; preserve partial evidence on failure.

    A new empty output directory is required. This prevents resumed runs from
    silently reusing or replacing prior provider calls.
    """
    if not os.environ.get("JEV_API_KEY"):
        raise RuntimeError("JEV_API_KEY is unavailable")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    _validate_protocol(protocol)
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if benchmark.get("schema") != "phase3b1_walk_node_strict_risk_v1":
        raise ValueError("unexpected benchmark schema")
    if benchmark.get("status") != "seen_development_evidence_only":
        raise ValueError("unexpected benchmark status")
    states = {row["state_sha256"]: row for row in benchmark["states"]}
    for variant in VARIANTS:
        if len(benchmark["assessment_units"][variant]) != 18:
            raise ValueError("assessment membership drift")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    calls_dir = output_dir / "calls"
    calls_dir.mkdir()
    started = time.monotonic()
    records: list[dict] = []
    consecutive_failures = 0
    stop_reason = "COMPLETE"
    try:
        for variant in VARIANTS:
            for unit in benchmark["assessment_units"][variant]:
                if len(records) >= MAX_CALLS:
                    stop_reason = "CALL_CAP"
                    break
                if time.monotonic() - started >= MAX_WALL_S:
                    stop_reason = "WALL_CAP"
                    break
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    stop_reason = "CONSECUTIVE_PROVIDER_FAILURES"
                    break
                row = states[unit["base_state_sha256"][0]]
                view = row["views"][variant]
                if hashlib.sha256(_canonical(view)).hexdigest() != unit["view_sha256"]:
                    raise ValueError("frozen view hash mismatch")
                sample_id = f"{variant}-{unit['paired_unit_id'][:20]}"
                call = evaluate_once(state=view, sample_id=sample_id,
                                     evidence_dir=calls_dir, timeout_s=TIMEOUT_S)
                records.append({"variant": variant, "paired_unit_id": unit["paired_unit_id"],
                                "record": call})
                progress = output_dir / "progress.json"
                if len(records) == 1:
                    _write_once(progress, {"records": records})
                else:
                    temp = output_dir / "progress.tmp"
                    temp.write_text(json.dumps({"records": records}, sort_keys=True), encoding="utf-8")
                    temp.replace(progress)
                consecutive_failures = 0 if call["availability"] else consecutive_failures + 1
            if stop_reason != "COMPLETE":
                break
    except Exception:
        stop_reason = "INTERNAL_ERROR"
        raise
    finally:
        result = score(benchmark, records)
        result["stop_reason"] = stop_reason
        result["elapsed_s"] = time.monotonic() - started
        result["benchmark_sha256"] = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
        result["protocol_sha256"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        _write_once(output_dir / "score.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.benchmark, args.protocol, args.output_dir)
    print(json.dumps({"stop_reason": result["stop_reason"],
                      "summary": result["summary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
