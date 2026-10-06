"""End-to-end language-to-runtime equivalence helpers for Phase 2.1.

The language compiler is evaluated against the frozen Phase 2.0 runtime. The
oracle and compiled Mission IR are executed separately with the same seed; only
the IR entry path differs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..config import load_yaml
from ..evidence import EnvironmentInfo
from ..mission import (
    CapabilityGrounder,
    LiveMissionSession,
    Mission,
    MissionExecutor,
    MissionResult,
    MissionValidator,
)
from ..paths import repo_root, resolve_repo_path
from .benchmark import canonical_mission_hash, canonical_mission_payload

DEFAULT_RUNTIME_PROTOCOL = "configs/experiments/oracle_mission_runtime_001.yaml"
_VOLATILE_KEYS = {"total_wall_time_s", "wall_time_s"}


def load_runtime_protocol(path: str | Path = DEFAULT_RUNTIME_PROTOCOL) -> dict[str, Any]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    protocol["protocol_path"] = str(resolved.relative_to(repo_root()).as_posix())
    protocol["_protocol_sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return protocol


def build_runtime_grounder(protocol: Mapping[str, Any]) -> CapabilityGrounder:
    grounding = protocol["grounding"]
    evidence = grounding["evidence"]
    capability_map = evidence.get("capability_map")
    return CapabilityGrounder(
        risk_map_path=resolve_repo_path(evidence["risk_map"]),
        boundary_comparison_path=resolve_repo_path(evidence["boundary_comparison"]),
        capability_map_path=resolve_repo_path(capability_map) if capability_map else None,
        mode_preference=grounding.get(
            "mode_preference", ("heading_lateral", "heading_only", "open_loop")
        ),
        historical_limits=grounding.get("historical", {}),
    )


def build_runtime_executor(
    *,
    protocol: Mapping[str, Any],
    recorder_root: str | Path | None = None,
    seed: int = 0,
    provenance: Mapping[str, Any] | None = None,
) -> MissionExecutor:
    robot_config = load_yaml(resolve_repo_path(protocol["robot_config"]))

    def session_factory(seed_value: int) -> LiveMissionSession:
        return LiveMissionSession(
            robot_config=robot_config,
            protocol=protocol,
            seed=seed_value,
        )

    return MissionExecutor(
        validator=MissionValidator(),
        grounder=build_runtime_grounder(protocol),
        session_factory=session_factory,
        protocol=protocol,
        recorder_root=str(recorder_root) if recorder_root is not None else None,
        seed=seed,
        provenance=dict(provenance or {}),
    )


def run_mission(
    executor: MissionExecutor,
    mission: Mission | Mapping[str, Any],
    *,
    phase: str,
    write_evidence: bool = False,
) -> MissionResult:
    return executor.run(mission, phase=phase, write_evidence=write_evidence)


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_volatile(item)
            for key, item in value.items()
            if key not in _VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item) for item in value]
    return value


def runtime_result_payload(result: MissionResult) -> dict[str, Any]:
    """Canonical runtime comparison payload; wall-clock fields are excluded."""

    payload = _strip_volatile(result.to_dict())
    payload.pop("mission_id", None)
    return payload


def compare_runtime_results(
    compiled: MissionResult, oracle: MissionResult
) -> dict[str, Any]:
    compiled_payload = runtime_result_payload(compiled)
    oracle_payload = runtime_result_payload(oracle)
    same_result = compiled_payload == oracle_payload
    return {
        "runtime_equivalent": same_result,
        "compiled": {
            "state": compiled.state,
            "mission_success": compiled.mission_success,
            "failure_type": compiled.failure_type,
            "completed_nodes": compiled.completed_nodes,
            "simulation_steps_executed": compiled.simulation_steps_executed,
            "total_simulation_time_s": compiled.total_simulation_time_s,
            "transition_count": compiled.transition_count,
        },
        "oracle": {
            "state": oracle.state,
            "mission_success": oracle.mission_success,
            "failure_type": oracle.failure_type,
            "completed_nodes": oracle.completed_nodes,
            "simulation_steps_executed": oracle.simulation_steps_executed,
            "total_simulation_time_s": oracle.total_simulation_time_s,
            "transition_count": oracle.transition_count,
        },
        "differences": [] if same_result else ["runtime_result_payload"],
    }


def oracle_mission_from_sample(
    expected_mission: Mapping[str, Any], *, mission_id: str
) -> Mission:
    document = dict(expected_mission)
    document["mission_id"] = mission_id
    return Mission.from_dict(document)


def mission_equivalence(compiled: Mission, oracle: Mission) -> dict[str, Any]:
    compiled_payload = canonical_mission_payload(compiled)
    oracle_payload = canonical_mission_payload(oracle)
    return {
        "compiled_ir_hash": canonical_mission_hash(compiled),
        "oracle_ir_hash": canonical_mission_hash(oracle),
        "exact_match": compiled_payload == oracle_payload,
        "schema_version_match": compiled.schema_version == oracle.schema_version,
        "step_count_match": len(compiled.steps) == len(oracle.steps),
        "step_order_match": [
            step.skill.value for step in compiled.steps
        ]
        == [step.skill.value for step in oracle.steps],
    }


def environment_payload() -> dict[str, Any]:
    return EnvironmentInfo.collect().to_dict()


def write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
