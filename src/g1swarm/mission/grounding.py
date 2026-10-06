"""Deterministic capability grounding against real Phase 1.3 evidence.

The grounder reads the frozen risk map / boundary comparison (and, for skills
not re-explored in Phase 1.3, protocol-recorded historical limits with their
source phase). It never interpolates or extrapolates beyond recorded evidence
and it never invents an execution strategy: a walk that cannot be grounded is
rejected or marked unknown - never silently split into shorter segments.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ir import ExecutionModeOverride, Mission, MissionStep, SkillName

GROUNDED = "GROUNDED"
CAPABILITY_REJECTED = "CAPABILITY_REJECTED"
CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "UNKNOWN": 3}
DEFAULT_MODE_PREFERENCE = ("heading_lateral", "heading_only", "open_loop")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class GroundingResult:
    step_id: str
    skill: str
    supported: bool
    status: str
    execution_mode: str | None
    risk: str | None
    evidence_ref: str | None
    reason: str
    experimental_override: bool = False
    source_phase: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "skill": self.skill,
            "supported": self.supported,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "risk": self.risk,
            "evidence_ref": self.evidence_ref,
            "reason": self.reason,
            "experimental_override": self.experimental_override,
            "source_phase": self.source_phase,
        }


@dataclass(frozen=True)
class GroundedPlan:
    mission_id: str
    status: str
    results: tuple[GroundingResult, ...]
    map_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def grounded(self) -> bool:
        return self.status == GROUNDED

    @property
    def failure_type(self) -> str | None:
        if self.status == GROUNDED:
            return None
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "map_hashes": dict(self.map_hashes),
            "results": [result.to_dict() for result in self.results],
        }


class CapabilityGrounder:
    def __init__(
        self,
        *,
        risk_map_path: str | Path,
        boundary_comparison_path: str | Path,
        capability_map_path: str | Path | None = None,
        mode_preference: Iterable[str] = DEFAULT_MODE_PREFERENCE,
        historical_limits: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.risk_map_path = Path(risk_map_path)
        self.boundary_path = Path(boundary_comparison_path)
        self.risk_map = json.loads(self.risk_map_path.read_text(encoding="utf-8"))
        self.boundary = json.loads(self.boundary_path.read_text(encoding="utf-8"))
        self.mode_preference = tuple(mode_preference)
        self.historical_limits = dict(historical_limits or {})
        self.map_hashes = {
            "risk_map_v1_3": _sha256(self.risk_map_path),
            "boundary_comparison": _sha256(self.boundary_path),
        }
        if capability_map_path is not None:
            capability_path = Path(capability_map_path)
            self.capability_map = json.loads(capability_path.read_text(encoding="utf-8"))
            self.map_hashes["capability_map_v1_3"] = _sha256(capability_path)
        else:
            self.capability_map = None

    # ------------------------------------------------------------------
    def _walk_mode_evidence(self, distance_m: float) -> dict[str, tuple[str, str]]:
        """Return {mode: (risk, evidence_ref)} from tabulated per-distance
        evidence first, then from the boundary extension points. No
        interpolation between recorded distances."""

        evidence: dict[str, tuple[str, str]] = {}
        table = self.risk_map["skills"]["walk_forward"]["execution_mode"]
        key = f"{float(distance_m):g}"
        if key in table:
            for mode, payload in table[key].items():
                evidence[mode] = (
                    str(payload["risk"]),
                    f"{self.risk_map_path}#{key}/{mode}",
                )
        for mode, treatment in self.boundary["treatments"].items():
            if mode in evidence:
                continue
            evaluated = [float(value) for value in treatment["evaluated_distances_m"]]
            if not any(abs(float(distance_m) - value) < 1e-9 for value in evaluated):
                continue
            last_reliable = treatment["last_reliable_m"]
            if last_reliable is not None and float(distance_m) <= float(last_reliable) + 1e-9:
                evidence[mode] = ("MEDIUM", f"{self.boundary_path}#{mode}/{key}")
            else:
                evidence[mode] = ("HIGH", f"{self.boundary_path}#{mode}/{key}")
        return evidence

    def _ground_walk(self, step: MissionStep) -> GroundingResult:
        distance = float(step.parameters["distance_m"])
        evidence = self._walk_mode_evidence(distance)
        override = step.execution_mode_override.value if step.execution_mode_override else None
        if not evidence:
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=False,
                status=CAPABILITY_UNKNOWN,
                execution_mode=None,
                risk="UNKNOWN",
                evidence_ref=None,
                reason=(
                    f"no recorded evidence for walk_forward at {distance:g} m "
                    "(no interpolation or extrapolation)"
                ),
                source_phase="phase1.3",
            )
        if override is not None:
            if override not in evidence:
                return GroundingResult(
                    step_id=step.step_id,
                    skill=step.skill.value,
                    supported=False,
                    status=CAPABILITY_UNKNOWN,
                    execution_mode=None,
                    risk="UNKNOWN",
                    evidence_ref=None,
                    reason=(
                        f"override {override!r} has no recorded evidence at {distance:g} m"
                    ),
                    source_phase="phase1.3",
                )
            risk, reference = evidence[override]
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=True,
                status=GROUNDED,
                execution_mode=override,
                risk=risk,
                evidence_ref=reference,
                reason=f"explicit experimental override; recorded risk {risk}",
                experimental_override=True,
                source_phase="phase1.3",
            )
        candidates = [
            (mode, risk, reference)
            for mode, (risk, reference) in evidence.items()
            if risk in {"LOW", "MEDIUM"}
        ]
        if candidates:
            candidates.sort(
                key=lambda item: (
                    RISK_ORDER[item[1]],
                    self.mode_preference.index(item[0])
                    if item[0] in self.mode_preference
                    else len(self.mode_preference),
                )
            )
            mode, risk, reference = candidates[0]
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=True,
                status=GROUNDED,
                execution_mode=mode,
                risk=risk,
                evidence_ref=reference,
                reason=(
                    f"deterministic selection: best risk {risk}, preference "
                    f"{'>'.join(self.mode_preference)}"
                ),
                source_phase="phase1.3",
            )
        if evidence:
            modes = ", ".join(sorted(evidence))
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=False,
                status=CAPABILITY_REJECTED,
                execution_mode=None,
                risk="HIGH",
                evidence_ref=next(iter(evidence.values()))[1],
                reason=(
                    f"all validated execution modes are HIGH risk at {distance:g} m "
                    f"({modes}); automatic segmentation is not an allowed strategy"
                ),
                source_phase="phase1.3",
            )
        return GroundingResult(
            step_id=step.step_id,
            skill=step.skill.value,
            supported=False,
            status=CAPABILITY_UNKNOWN,
            execution_mode=None,
            risk="UNKNOWN",
            evidence_ref=None,
            reason="no usable evidence",
            source_phase="phase1.3",
        )

    def _ground_historical(self, step: MissionStep, skill_key: str) -> GroundingResult:
        limits = self.historical_limits.get(skill_key, {})
        source_phase = str(limits.get("source_phase", "phase1.1"))
        reference = limits.get("evidence_ref")
        if step.skill is SkillName.TURN:
            angle = abs(float(step.parameters["angle_deg"]))
            limit = float(limits.get("max_abs_angle_deg", 90.0))
            if angle > limit:
                return GroundingResult(
                    step_id=step.step_id,
                    skill=step.skill.value,
                    supported=False,
                    status=CAPABILITY_UNKNOWN,
                    execution_mode=None,
                    risk="UNKNOWN",
                    evidence_ref=reference,
                    reason=(
                        f"turn angle {angle:g} deg is beyond the validated range "
                        f"(+/-{limit:g} deg, {source_phase})"
                    ),
                    source_phase=source_phase,
                )
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=True,
                status=GROUNDED,
                execution_mode="heading_lateral",
                risk="LOW",
                evidence_ref=reference,
                reason=f"within validated range (+/-{limit:g} deg, {source_phase})",
                source_phase=source_phase,
            )
        if step.skill is SkillName.STAND:
            duration = float(
                step.parameters.get("duration_s", limits.get("default_duration_s", 2.0))
            )
            limit = float(limits.get("max_duration_s", 20.0))
            if duration > limit:
                return GroundingResult(
                    step_id=step.step_id,
                    skill=step.skill.value,
                    supported=False,
                    status=CAPABILITY_UNKNOWN,
                    execution_mode=None,
                    risk="UNKNOWN",
                    evidence_ref=reference,
                    reason=(
                        f"stand duration {duration:g} s is beyond the validated range "
                        f"(<= {limit:g} s, {source_phase})"
                    ),
                    source_phase=source_phase,
                )
            return GroundingResult(
                step_id=step.step_id,
                skill=step.skill.value,
                supported=True,
                status=GROUNDED,
                execution_mode="heading_lateral",
                risk="LOW",
                evidence_ref=reference,
                reason=f"within validated range (<= {limit:g} s, {source_phase})",
                source_phase=source_phase,
            )
        # stop: no parameters, validated stop criterion from Phase 1.1/1.2
        return GroundingResult(
            step_id=step.step_id,
            skill=step.skill.value,
            supported=True,
            status=GROUNDED,
            execution_mode="open_loop",
            risk="LOW",
            evidence_ref=reference,
            reason=f"stop criterion validated in {source_phase}",
            source_phase=source_phase,
        )

    # ------------------------------------------------------------------
    def ground_step(self, step: MissionStep) -> GroundingResult:
        if step.skill is SkillName.WALK_FORWARD:
            return self._ground_walk(step)
        return self._ground_historical(step, step.skill.value)

    def ground_mission(self, mission: Mission) -> GroundedPlan:
        results = tuple(self.ground_step(step) for step in mission.steps)
        if all(result.status == GROUNDED for result in results):
            status = GROUNDED
        elif any(result.status == CAPABILITY_REJECTED for result in results):
            status = CAPABILITY_REJECTED
        else:
            status = CAPABILITY_UNKNOWN
        return GroundedPlan(
            mission_id=mission.mission_id,
            status=status,
            results=results,
            map_hashes=dict(self.map_hashes),
        )
