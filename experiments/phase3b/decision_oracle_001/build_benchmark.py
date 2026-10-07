"""One-time offline extraction of retained predecision states and outcomes."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

from oracle import CONTRACT_ID, context_fingerprint, state_fingerprint, validate_state

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("benchmark.json")
EVAL = Path("experiments/phase3a/frame_residual_learning_001/evidence/evaluation")
COMPONENT = Path("experiments/phase3a/residual_yaw_component_001/component_analysis.json")
MODE_MAP = {"off": "CONTINUE", "lateral": "LATERAL_RECOVERY", "yaw": "YAW_RECOVERY", "combined": "COMBINED_RECOVERY"}


def digest(rel: Path) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def first_trace(rel: Path, node: int) -> dict:
    with gzip.open(ROOT / rel, "rt", encoding="utf-8") as stream:
        for line in stream:
            sample = json.loads(line)
            if sample["node_index"] == node:
                assert sample["elapsed_s"] == 0.0
                return sample
    raise AssertionError(f"node {node} absent from {rel}")


def read_results() -> dict:
    wanted = {"primitive-walk-8", "sequence-mixed-12m"}
    selected = {}
    with gzip.open(ROOT / EVAL / "results.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if (row["case_id"] in wanted and row["heading_alignment_alpha"] == 0.5
                    and row["learned_policy_configured"] is False
                    and row["evaluation_set"] == "seen_regression" and row["phase"] == "primary"):
                assert row["case_id"] not in selected
                selected[row["case_id"]] = row
    assert set(selected) == wanted
    return selected


def make_state(case: str, trace_rel: Path, node: int, target_distance: float, strict_limit: float, transition: str) -> dict:
    sample = first_trace(trace_rel, node)
    ref = sample["walking_reference"]
    correction = sample["walking_correction_sample"]
    pose = sample["state_before_command"]["base_position"]
    planned = ref["planned_origin"]
    assert sample["skill"] == "walk_forward" and sample["previous_skill"] == ("stand" if node else None)
    assert correction["sim_time_s"] == sample["time_s"]
    state = {
        "state_id": f"{case}:first-walk-entry:alpha0.5:seed0",
        "context": {
            "case_id": case,
            "seed": 0,
            "decision_epoch": "first_walk_entry",
            "skill": f"Walk{target_distance:g}m",
            "transition": transition,
            "alpha": 0.5,
            "origin": "actual-start",
            "reference_id": "midpoint_heading@alpha0.5",
            "controller_id": "phase3a-frozen-frame-residual-controller",
            "evaluator_id": "phase3a-original-nominal-strict-physical-and-paired-global",
            "policy_id": "phase3a-inherited-frozen-unitree-g1-policy",
            "residual_bounds_id": "vx0.1-vy0.06-yaw0.12",
            "recovery_contract_id": CONTRACT_ID,
        },
        "observables": {
            "local_lateral_error_m": correction["lateral_error_m"],
            "local_heading_error_deg": math.degrees(correction["heading_error_rad"]),
            "route_x_error_m": pose[0] - planned[0],
            "route_y_error_m": pose[1] - planned[1],
            "route_heading_error_deg": math.degrees(ref["measurement_heading_rad"] - ref["planned_heading_rad"]),
            "reference_heading_deg": math.degrees(ref["control_heading_rad"]),
            "instantaneous_strict_margin_m": strict_limit - abs(correction["lateral_error_m"]),
            "remaining_distance_m": target_distance,
            "previous_recovery": None,
        },
    }
    validate_state(state)
    return state


def outcome_from_row(row: dict, source: str) -> dict:
    final = row["final_state"]["base_position"]
    target = row["ideal_endpoint_reference_xy"]
    last = row["nodes"][-1]
    return {
        "nominal": bool(row["task_success"]),
        "physical": bool(row["physical_success"]),
        "all_strict": all(node["strict_success"] for node in row["nodes"]),
        "final_world_x_error_m": final[0] - target[0],
        "final_world_y_error_m": final[1] - target[1],
        "final_lateral_error_m": last["ideal_path_lateral_error_m"],
        "final_heading_error_deg": last["ideal_path_heading_error_deg"],
        "endpoint_norm_m": row["ideal_endpoint_error_m"],
        "evidence_source": source,
    }


def entry(state: dict, outcomes: dict) -> dict:
    return {
        "state_id": state["state_id"],
        "context_fingerprint": context_fingerprint(state["context"]),
        "state_fingerprint": state_fingerprint(state),
        "outcomes": outcomes,
    }


def main() -> None:
    rows = read_results()
    result_rel = EVAL / "results.jsonl.gz"
    analysis = json.loads((ROOT / COMPONENT).read_text(encoding="utf-8"))
    states = []
    catalog = []
    state_sources = {}
    for case, node, distance, limit, transition in (
        ("primitive-walk-8", 0, 8.0, 0.28, "Start->Walk8m"),
        ("sequence-mixed-12m", 1, 4.0, 0.20, "Stand->Walk4m"),
        ("sequence-mixed-16m", 1, 8.0, 0.28, "Stand->Walk8m"),
    ):
        trace = (EVAL / "traces" / f"primary--alpha0.5-residual-off--{case}.jsonl.gz")
        if case == "sequence-mixed-16m":
            trace = Path("experiments/phase3a/residual_authority_window_001/evidence/runs/02--zero14--control/trace.jsonl.gz")
        state = make_state(case, trace, node, distance, limit, transition)
        states.append(state)
        state_sources[state["state_id"]] = {"path": trace.as_posix(), "sha256": digest(trace), "selector": f"first sample of node_index={node}, elapsed_s=0"}
        if case != "sequence-mixed-16m":
            source = f"{result_rel.as_posix()}#sha256={digest(result_rel)};case_id={case};alpha=0.5;off;phase=primary"
            outcomes = {"CONTINUE": outcome_from_row(rows[case], source)}
        else:
            outcomes = {}
            for arm, mode in MODE_MAP.items():
                t = analysis["treatments"][arm]
                source_item = analysis["evidence_sources"][arm]["result"]
                source = f"{source_item['path']}#sha256={source_item['sha256']}"
                assert digest(Path(source_item["path"])) == source_item["sha256"]
                raw = json.loads((ROOT / source_item["path"]).read_text(encoding="utf-8"))
                outcomes[mode] = outcome_from_row(raw, source)
                for key, raw_key in (("final_world_x_error_m", "x_m"), ("final_world_y_error_m", "y_m"),
                                     ("endpoint_norm_m", "norm_m"), ("final_heading_error_deg", "heading_deg")):
                    assert math.isclose(outcomes[mode][key], t[raw_key], abs_tol=1e-12)
        catalog.append(entry(state, outcomes))
    benchmark = {
        "benchmark_id": "phase3b0_seen_evidence_first_decision_v0",
        "status": "DEVELOPMENT_ONLY; no independent Jev-heldout claim",
        "contract_id": CONTRACT_ID,
        "state_source_rule": "Only trace samples at first-Walk entry (elapsed=0), before residual action. Current strict margin is instantaneous, never formal endpoint strict outcome.",
        "seed_source_rule": "The retained FrameRunner/EpisodeRunner builds the simulation with seed=0; legacy result rows do not carry seed as a top-level field.",
        "outcome_source_rule": "Outcomes are separate from state. 16m fixed14 four-cell outcomes are context-matched. The primitive and12m CONTINUE rows are historical zero-action runs with the inherited2s callback mask; recovery cells are unknown. Window duration does not affect zero injected action, but exact14s callback equivalence is not independently acquired for these two states.",
        "states": states,
        "catalog": catalog,
        "state_sources": state_sources,
        "coverage": {
            "n_distinct_predecision_states": 3,
            "n_fixed14s_full_mode_states": 1,
            "observed_modes_by_state": {item["state_id"]: sorted(item["outcomes"]) for item in catalog},
            "missing_modes_by_state": {item["state_id"]: sorted(set(MODE_MAP.values()) - set(item["outcomes"])) for item in catalog},
            "expected_offline_oracle_modes": {states[0]["state_id"]: "CONTINUE", states[1]["state_id"]: "CONTINUE", states[2]["state_id"]: "ABSTAIN"},
            "limitations": ["The two CONTINUE rows have no observed fixed14s recovery counterfactuals.", "There is no observed state with an admissible recovery under the joint contract.", "The primitive Walk has no prior transition and is ineligible for residual recovery; it is a CONTINUE guardrail.", "The12m endpoint norm is a measurement, not an absolute global failure label.", "Phase1 controllers and task envelopes are not used as outcome cells."]
        },
        "artifact_sources": {
            "frame_residual_result_archive": {"path": result_rel.as_posix(), "sha256": digest(result_rel)},
            "fixed14s_component_analysis": {"path": COMPONENT.as_posix(), "sha256": digest(COMPONENT)},
            "fixed14s_case": {"path": "experiments/phase3a/residual_yaw_component_001/case.json", "sha256": analysis["case_sha256"]},
            "runner_seed_source": {"path": "src/g1swarm/transition_learning/env.py", "sha256": digest(Path("src/g1swarm/transition_learning/env.py"))},
        },
    }
    OUT.write_text(json.dumps(benchmark, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
