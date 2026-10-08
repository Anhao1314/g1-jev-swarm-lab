"""Stage A audit: recompute Phase 1.2b case evaluations from raw evidence.

Read-only with respect to artifacts. Writes audit artifacts under
``experiments/baselines/g1_distance_segmentation_001/audit/``.
"""

from __future__ import annotations

import json
from pathlib import Path

from g1swarm.boundary.envelope import NOMINAL_WALK_ENVELOPE, STRICT_WALK_ENVELOPE
from g1swarm.paths import repo_root

EXPERIMENT_DIR = repo_root() / "experiments" / "baselines" / "g1_distance_segmentation_001"
ARTIFACT_DIR = repo_root() / "artifacts" / "g1_distance_segmentation_001" / "final"

CASES = {
    "case1_direct_long_4m": {
        "run_dir": "direct_long-4m-final-seed000",
        "kind": "segmentation_mission",
        "target_m": 4.0,
    },
    "case2_boundary_4.53125m": {
        "run_dir": "A_distance-final-4.53125-seed000",
        "kind": "distance_boundary",
        "target_m": 4.53125,
    },
    "case3_boundary_4.625m": {
        "run_dir": "A_distance-final-4.625-seed000",
        "kind": "distance_boundary",
        "target_m": 4.625,
    },
}

CANONICAL_KEYS = ("lateral_drift_m", "heading_error_deg", "forward_displacement_m")


def _load(run_dir: str) -> dict:
    path = ARTIFACT_DIR / run_dir / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(metrics: dict) -> dict:
    lateral = metrics.get("lateral_drift_m")
    if lateral is None:
        lateral = metrics.get("final_lateral_drift_m")
    heading = metrics.get("heading_error_deg")
    if heading is None:
        heading = metrics.get("final_heading_error_deg")
    forward = metrics.get("forward_displacement_m")
    if forward is None:
        forward = metrics.get("final_forward_progress_m")
    completion = metrics.get("completion_sim_time_s")
    if completion is None:
        completion = metrics.get("total_simulation_time_s")
    return {
        "forward_displacement_m": forward,
        "lateral_drift_m": lateral,
        "heading_error_deg": heading,
        "completion_sim_time_s": completion,
        "absolute_distance_error_m": metrics.get("absolute_distance_error_m"),
    }


def audit_case(name: str, spec: dict) -> dict:
    metrics = _load(spec["run_dir"])
    target = float(metrics.get("target_distance_m") or metrics.get("total_target_distance_m") or spec["target_m"])
    canonical = _canonical(metrics)
    missing = [key for key in CANONICAL_KEYS if metrics.get(key) is None]
    nominal = NOMINAL_WALK_ENVELOPE.evaluate(canonical, target)
    strict = STRICT_WALK_ENVELOPE.evaluate(canonical, target)
    recomputed_task = bool(metrics["physical_success"] and nominal.satisfied)
    recorded_violations = list(metrics.get("task_violations") or [])
    recorded_nominal = metrics.get("nominal_envelope", {})
    return {
        "run_dir": spec["run_dir"],
        "kind": spec["kind"],
        "target_m": target,
        "canonical_keys_missing_in_raw_metrics": missing,
        "actual": {
            "forward_displacement_m": canonical["forward_displacement_m"],
            "absolute_distance_error_m": canonical["absolute_distance_error_m"],
            "lateral_drift_m": canonical["lateral_drift_m"],
            "heading_error_deg": canonical["heading_error_deg"],
            "completion_sim_time_s": canonical["completion_sim_time_s"],
        },
        "nominal_limits": nominal.limits.to_dict(),
        "strict_limits": strict.limits.to_dict(),
        "recomputed": {
            "nominal_satisfied": nominal.satisfied,
            "nominal_violations": list(nominal.violations),
            "strict_satisfied": strict.satisfied,
            "strict_violations": list(strict.violations),
            "task_success": recomputed_task,
        },
        "recorded": {
            "task_success": metrics.get("task_success"),
            "task_violations": recorded_violations,
            "failure_type": metrics.get("failure_type"),
            "nominal_envelope_lateral_drift_m": recorded_nominal.get("lateral_drift_m"),
            "nominal_envelope_heading_error_deg": recorded_nominal.get("heading_error_deg"),
            "nominal_envelope_satisfied": recorded_nominal.get("satisfied"),
        },
        "agreement": {
            "task_success_matches": bool(metrics.get("task_success") == recomputed_task),
            "violations_match": bool(sorted(recorded_violations) == sorted(nominal.violations)),
        },
    }


def main() -> int:
    audit_dir = EXPERIMENT_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    cases = {name: audit_case(name, spec) for name, spec in CASES.items()}

    root_cause = {
        "summary": (
            "The segmentation-mission metrics used final_* key names while the shared "
            "walk-envelope evaluator reads canonical lateral_drift_m / heading_error_deg "
            "keys; the missing keys defaulted to +infinity and produced spurious "
            "EXCESSIVE_DRIFT and HEADING_ERROR violations."
        ),
        "affected_path": "src/g1swarm/segmentation/runner.py (run_mission metrics dict)",
        "unaffected_path": "src/g1swarm/boundary/runner.py (distance boundary runs already use canonical keys)",
        "missing_keys_case1": cases["case1_direct_long_4m"]["canonical_keys_missing_in_raw_metrics"],
        "mission_recorded_infinity": cases["case1_direct_long_4m"]["recorded"][
            "nominal_envelope_lateral_drift_m"
        ],
    }

    verdict = "FAIL"
    reasons = [
        "Segmentation missions and distance-boundary runs did not feed the same metric keys to "
        "the shared evaluator (canonical keys missing for every segmentation mission).",
        "The published Phase 1.2b statement that all 12 segmentation missions failed the nominal "
        "envelope is not supported by the raw evidence: with the canonical values the 4 m "
        "direct_long run satisfies the nominal envelope.",
        "The refined distance boundary (4.53125 m reliable / 4.625 m failure) is unaffected: "
        "those runs carry canonical keys and their recorded evaluations agree with the "
        "independent recomputation.",
    ]
    unaffected = [
        "Refined distance boundary 4.53125-4.625 m (canonical-key runs, recomputation agrees)",
        "Phase 1.2 / 1.1 / 1 frozen artifacts",
        "Boundary evidence bundles",
    ]
    affected = [
        "experiments/baselines/g1_distance_segmentation_001/summary.json",
        "experiments/baselines/g1_distance_segmentation_001/segmentation_comparison.json",
        "experiments/baselines/g1_distance_segmentation_001/risk_map_v1_2b.json",
        "experiments/baselines/g1_distance_segmentation_001/execution_strategy_map.json",
        "experiments/baselines/g1_distance_segmentation_001/report.md",
        "12 segmentation mission evidence bundles (must be re-run with the fixed evaluator)",
    ]

    (audit_dir / "case_comparison.json").write_text(
        json.dumps({"cases": cases, "root_cause": root_cause}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (audit_dir / "audit_summary.json").write_text(
        json.dumps(
            {
                "audit_verdict": verdict,
                "reasons": reasons,
                "affected": affected,
                "unaffected": unaffected,
                "cases": {name: case["agreement"] for name, case in cases.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    for name, case in cases.items():
        print(f"== {name} ({case['run_dir']}) ==")
        print(
            f"  drift={case['actual']['lateral_drift_m']:+.6f} "
            f"nominal_limit={case['nominal_limits']['lateral_drift_max_m']:.4f} "
            f"strict_limit={case['strict_limits']['lateral_drift_max_m']:.4f}"
        )
        print(
            f"  heading={case['actual']['heading_error_deg']:+.4f} "
            f"nominal_limit={case['nominal_limits']['heading_error_max_deg']:.1f} "
            f"strict_limit={case['strict_limits']['heading_error_max_deg']:.1f}"
        )
        print(
            f"  distance_error={case['actual']['absolute_distance_error_m']:.6f} "
            f"nominal_limit={case['nominal_limits']['distance_error_max_m']:.4f}"
        )
        print(
            f"  recorded_task_success={case['recorded']['task_success']} "
            f"recomputed={case['recomputed']['task_success']} "
            f"recorded_violations={case['recorded']['task_violations']} "
            f"recomputed_violations={case['recomputed']['nominal_violations']}"
        )
        print(f"  missing_canonical_keys={case['canonical_keys_missing_in_raw_metrics']}")
    print(f"AUDIT VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
