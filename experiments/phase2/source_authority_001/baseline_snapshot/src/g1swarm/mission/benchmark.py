"""Oracle mission benchmark aggregation (Phase 2.0)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import yaml

from ..evidence import utc_timestamp
from .runtime import MissionResult

CORPUS_KEYS = ("schema_version", "corpus_id", "missions", "negatives")
REQUIRED_SUMMARY_KEYS = (
    "experiment_id",
    "campaign",
    "corpus_id",
    "protocol_sha256",
    "source_commit",
    "generated_at",
    "horizons",
    "valid",
    "rejections",
    "failure_taxonomy",
    "missions",
)


class CorpusError(ValueError):
    """The mission corpus is malformed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(path: str | Path) -> dict[str, Any]:
    corpus_path = Path(path)
    text = corpus_path.read_text(encoding="utf-8")
    if corpus_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    validate_corpus(data)
    return data


def validate_corpus(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise CorpusError("corpus must be a mapping")
    missing = [key for key in CORPUS_KEYS if key not in data]
    if missing:
        raise CorpusError(f"corpus missing fields: {', '.join(missing)}")
    seen: set[str] = set()
    for section in ("missions", "negatives"):
        entries = data[section]
        if not isinstance(entries, list):
            raise CorpusError(f"{section} must be a list")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise CorpusError(f"{section} entry must be a mapping")
            mission_id = entry.get("mission_id")
            if not isinstance(mission_id, str) or not mission_id:
                raise CorpusError(f"{section} entry without a mission_id")
            if mission_id in seen:
                raise CorpusError(f"duplicate mission_id {mission_id!r}")
            seen.add(mission_id)
            if not isinstance(entry.get("steps"), list):
                raise CorpusError(f"{mission_id}: steps must be a list")
            if "expected" not in entry:
                raise CorpusError(f"{mission_id}: expected outcome missing")


def mission_document(entry: Mapping[str, Any], corpus_schema_version: str) -> dict[str, Any]:
    return {
        "schema_version": entry.get("schema_version", corpus_schema_version),
        "mission_id": entry["mission_id"],
        "steps": entry["steps"],
    }


@dataclass(frozen=True)
class MissionRun:
    entry: Mapping[str, Any]
    negative: bool
    result: MissionResult


def build_transition_map(runs: list[MissionRun]) -> dict[str, Any]:
    transitions: dict[str, dict[str, Any]] = {}
    for run in runs:
        success_ids = {
            node["node_id"]
            for node in run.result.nodes
            if node["metrics"].get("task_success")
        }
        for transition in run.result.transitions:
            key = f"{transition['previous_skill']}->{transition['next_skill']}"
            entry = transitions.setdefault(
                key,
                {
                    "previous_skill": transition["previous_skill"],
                    "next_skill": transition["next_skill"],
                    "executions": 0,
                    "next_node_successes": 0,
                    "next_node_failures": 0,
                    "position_delta_m": [],
                    "heading_delta_deg": [],
                    "mission_ids": [],
                },
            )
            entry["executions"] += 1
            if transition["next_node_id"] in success_ids:
                entry["next_node_successes"] += 1
            else:
                entry["next_node_failures"] += 1
            entry["position_delta_m"].append(list(transition["position_delta_m"]))
            entry["heading_delta_deg"].append(float(transition["heading_delta_deg"]))
            entry["mission_ids"].append(run.result.mission_id)
    payload: dict[str, Any] = {}
    for key, entry in sorted(transitions.items()):
        positions = entry["position_delta_m"]
        headings = entry["heading_delta_deg"]
        representative = [
            round(mean(axis[index] for axis in positions), 6) for index in range(3)
        ]
        mission_ids = sorted(set(entry["mission_ids"]))
        identical_observed = all(
            heading == headings[0] for heading in headings
        ) and all(position == positions[0] for position in positions)
        repeated_template = len(mission_ids) < len(positions)
        payload[key] = {
            "previous_skill": entry["previous_skill"],
            "next_skill": entry["next_skill"],
            "executions": entry["executions"],
            "next_node_successes": entry["next_node_successes"],
            "next_node_failures": entry["next_node_failures"],
            "representative_position_delta_m": representative,
            "representative_heading_delta_deg": round(mean(headings), 6),
            "deterministic": identical_observed if repeated_template else None,
            "determinism_note": (
                "identical deltas observed for repeated execution of the same mission template"
                if repeated_template
                else "not established: each observed execution came from a different mission template"
            ),
            "evidence_refs": mission_ids,
        }
    return {
        "schema_version": "2.0.0",
        "generated_at": utc_timestamp(),
        "transitions": payload,
    }


def build_benchmark_summary(
    *,
    protocol: Mapping[str, Any],
    corpus: Mapping[str, Any],
    corpus_path: str | Path,
    runs: list[MissionRun],
    source_commit: str | None,
    campaign: str,
) -> dict[str, Any]:
    horizon_names = list(protocol.get("horizons", {}))
    horizon_stats: dict[str, Any] = {
        name: {"missions": 0, "successes": 0, "failures": 0, "completed_nodes": [], "simulation_time_s": []}
        for name in horizon_names
    }
    missions_payload: list[dict[str, Any]] = []
    taxonomy: dict[str, int] = {}
    valid_successes = 0
    valid_failures = 0
    rejected = 0
    zero_step_compliant = True
    expectation_ok = True
    physical_successes = 0
    mission_successes = 0
    for run in runs:
        entry = run.entry
        result = run.result
        expected = entry.get("expected", {})
        payload = {
            "mission_id": result.mission_id,
            "horizon": entry.get("horizon"),
            "negative": run.negative,
            "state": result.state,
            "mission_success": result.mission_success,
            "failure_type": result.failure_type,
            "failure_reason": result.failure_reason,
            "completed_nodes": result.completed_nodes,
            "horizon_nodes": result.horizon,
            "simulation_steps_executed": result.simulation_steps_executed,
            "total_simulation_time_s": result.total_simulation_time_s,
            "total_wall_time_s": result.total_wall_time_s,
            "skill_invocations": result.skill_invocations,
            "physical_success": result.physical_success,
            "transition_count": result.transition_count,
            "controller_memory_resets": result.controller_memory_resets,
            "grounded_modes": [
                grounding.get("execution_mode") for grounding in result.grounding.get("results", [])
            ],
        }
        missions_payload.append(payload)
        if not run.negative:
            horizon = str(entry.get("horizon"))
            stats = horizon_stats.setdefault(
                horizon,
                {"missions": 0, "successes": 0, "failures": 0, "completed_nodes": [], "simulation_time_s": []},
            )
            stats["missions"] += 1
            stats["completed_nodes"].append(result.completed_nodes)
            stats["simulation_time_s"].append(result.total_simulation_time_s)
            if result.mission_success:
                stats["successes"] += 1
                valid_successes += 1
                mission_successes += 1
            else:
                stats["failures"] += 1
                valid_failures += 1
            if result.failure_type:
                taxonomy[result.failure_type] = taxonomy.get(result.failure_type, 0) + 1
            if result.physical_success:
                physical_successes += 1
        else:
            rejected += 1
            if result.simulation_steps_executed != 0:
                zero_step_compliant = False
            expected_type = expected.get("failure_type")
            if expected_type and result.failure_type != expected_type:
                expectation_ok = False
    for name, stats in horizon_stats.items():
        missions = stats.pop("missions")
        successes = stats.pop("successes")
        failures = stats.pop("failures")
        completed = stats.pop("completed_nodes")
        sim_times = stats.pop("simulation_time_s")
        stats.update(
            {
                "missions": missions,
                "successes": successes,
                "failures": failures,
                "success_rate": (successes / missions) if missions else None,
                "mean_completed_nodes": mean(completed) if completed else None,
                "mean_simulation_time_s": mean(sim_times) if sim_times else None,
            }
        )
    valid_total = valid_successes + valid_failures
    return {
        "experiment_id": protocol.get("experiment_id", "oracle_mission_runtime_001"),
        "campaign": campaign,
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": _sha256(Path(corpus_path)),
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "source_commit": source_commit,
        "generated_at": utc_timestamp(),
        "valid": {
            "missions": valid_total,
            "successes": valid_successes,
            "failures": valid_failures,
            "success_rate": (valid_successes / valid_total) if valid_total else None,
        },
        "rejections": {
            "missions": rejected,
            "zero_step_compliant": zero_step_compliant,
            "expected_failure_types_ok": expectation_ok,
        },
        "horizons": horizon_stats,
        "mission_success_by_horizon": {
            name: stats["success_rate"] for name, stats in horizon_stats.items()
        },
        "physical_successes": physical_successes,
        "mission_successes": mission_successes,
        "failure_taxonomy": taxonomy,
        "totals": {
            "simulation_time_s": sum(payload["total_simulation_time_s"] for payload in missions_payload),
            "wall_time_s": sum(payload["total_wall_time_s"] for payload in missions_payload),
            "skill_invocations": sum(payload["skill_invocations"] for payload in missions_payload),
            "transitions": sum(payload["transition_count"] for payload in missions_payload),
        },
        "determinism_note": (
            "The simulator/controller are deterministic; success is reported per distinct "
            "mission template, not as repeated identical samples."
        ),
        "missions": missions_payload,
    }


def validate_benchmark_summary(data: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_SUMMARY_KEYS if key not in data]
    if missing:
        raise ValueError(f"benchmark summary missing fields: {', '.join(missing)}")
    if not data["rejections"].get("zero_step_compliant", False):
        raise ValueError("a rejected mission executed simulation steps")
    for name, stats in data["horizons"].items():
        if stats["missions"] and stats["successes"] + stats["failures"] != stats["missions"]:
            raise ValueError(f"horizon {name}: success/failure counts do not add up")
