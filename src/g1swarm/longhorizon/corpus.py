"""Phase 2.3 long-horizon language corpus generation.

Design rules (to be frozen in ``experiments/phase2/long_horizon_language_001/
protocol.yaml`` after the pilot):

- Canonical Mission IR is generated first. Language realizations are derived
  from the canonical IR, so the exact semantic ground truth is the IR itself.
- Only capability-grounded parameter values are used. The walk-distance /
  turn-angle / stand-duration pools follow the frozen Phase 1.3 risk map and
  the Phase 1.1 validated ranges (``risk_map_v1_3.json``,
  ``boundary_comparison.json``); no interpolation or extrapolation is allowed.
- Language realization is deterministic (templates only). The tested
  DeepSeek compiler never authors its own evaluation text.
- Malformed/ambiguous/unsupported/capability-unknown inputs are kept in a
  separate safety-control set and never mixed into the horizon success curves.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

EXPERIMENT_ID = "long_horizon_language_001"
MISSION_SCHEMA_VERSION = "2.0.0"
GENERATOR_VERSION = "2.3.0"

#: Primary horizon definition: number of Mission IR steps (not tokens).
HORIZONS: dict[str, int] = {
    "H1": 1,
    "H3": 3,
    "H5": 5,
    "H8": 8,
    "H12": 12,
    "H16": 16,
}

#: Capability-grounded parameter pools (frozen evidence, no extrapolation).
#: risk_map_v1_3.json tabulates 4/6/8/10 m (heading_lateral LOW at all four);
#: boundary_comparison.json records 12/15/20 m extension points with
#: last_reliable_m = 20.0 (MEDIUM risk). Any other distance is
#: CAPABILITY_UNKNOWN.
WALK_DISTANCES_LOW_M: tuple[float, ...] = (4.0, 6.0, 8.0, 10.0)
WALK_DISTANCES_EXTENSION_M: tuple[float, ...] = (12.0, 15.0, 20.0)
WALK_DISTANCES_ALLOWED_M: tuple[float, ...] = WALK_DISTANCES_LOW_M + WALK_DISTANCES_EXTENSION_M

#: Phase 1.1 validated turn range: |angle| <= 90 deg (frozen protocol
#: historical limit); stand <= 20 s (default 2.0); stop takes no parameters.
TURN_ANGLES_DEG: tuple[float, ...] = (30.0, 45.0, 60.0, 90.0)
STAND_DURATIONS_S: tuple[float, ...] = (1.0, 2.0, 5.0)
STAND_MAX_DURATION_S = 20.0

#: Deliberately outside the grounded evidence: used only by the
#: capability-unknown safety control, never in the success corpus.
CAPABILITY_UNKNOWN_DISTANCE_M = 25.0

CONDITIONS: tuple[str, ...] = ("L1", "L2", "L3")
ORACLE_CONDITION = "L0"
CONDITION_LABELS = {
    "L0": "Oracle IR (no language compiler)",
    "L1": "Controlled language (Phase 2.1 compatible)",
    "L2": "Natural clear language",
    "L3": "Colloquial / noisy valid language",
}

SKILLS: tuple[str, ...] = ("stand", "walk_forward", "turn", "stop")

EVIDENCE_REFS = {
    "risk_map": "experiments/baselines/g1_closed_loop_correction_001/risk_map_v1_3.json",
    "boundary_comparison": (
        "experiments/baselines/g1_closed_loop_correction_001/boundary_comparison.json"
    ),
    "skill_characterization": (
        "experiments/baselines/g1_skill_characterization_001/summary.json"
    ),
}

_CN_DIGITS = {
    1.0: "一",
    2.0: "二",
    4.0: "四",
    5.0: "五",
    6.0: "六",
    8.0: "八",
    10.0: "十",
    12.0: "十二",
    15.0: "十五",
    20.0: "二十",
    30.0: "三十",
    45.0: "四十五",
    60.0: "六十",
    90.0: "九十",
}


def _fmt_num(value: float) -> str:
    """Fixed Arabic formatting for the allowed pools (4, 4.5 would stay 4.5)."""
    return f"{float(value):g}"


def cn_number(value: float) -> str:
    if float(value) not in _CN_DIGITS:
        raise ValueError(f"no Chinese numeral for unsupported value {value!r}")
    return _CN_DIGITS[float(value)]


# ---------------------------------------------------------------------------
# Canonical Mission IR generation


def _rng_for(seed: int, horizon: str, index: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{horizon}:{index}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _walk_step(step_id: str, distance: float, depends_on: Sequence[str]) -> dict[str, Any]:
    return {
        "id": step_id,
        "skill": "walk_forward",
        "parameters": {"distance_m": float(distance)},
        "depends_on": list(depends_on),
    }


def _turn_step(step_id: str, angle: float, depends_on: Sequence[str]) -> dict[str, Any]:
    return {
        "id": step_id,
        "skill": "turn",
        "parameters": {"angle_deg": float(angle)},
        "depends_on": list(depends_on),
    }


def _stand_step(step_id: str, duration: float, depends_on: Sequence[str]) -> dict[str, Any]:
    return {
        "id": step_id,
        "skill": "stand",
        "parameters": {"duration_s": float(duration)},
        "depends_on": list(depends_on),
    }


def _stop_step(step_id: str, depends_on: Sequence[str]) -> dict[str, Any]:
    return {"id": step_id, "skill": "stop", "parameters": {}, "depends_on": list(depends_on)}


def _choose_distance(rng: random.Random, *, allow_extension: bool) -> float:
    if allow_extension and rng.random() < 0.2:
        return float(rng.choice(WALK_DISTANCES_EXTENSION_M))
    return float(rng.choice(WALK_DISTANCES_LOW_M))


def _choose_turn(rng: random.Random) -> float:
    angle = float(rng.choice(TURN_ANGLES_DEG))
    return angle if rng.random() < 0.5 else -angle


def _generate_single_step_mission(horizon: str, index: int, rng: random.Random) -> list[dict[str, Any]]:
    """H1 covers every primitive deterministically in rounds."""
    order = ("walk_forward", "turn", "stand", "stop")
    skill = order[index % len(order)]
    if skill == "walk_forward":
        distance = WALK_DISTANCES_LOW_M[(index // len(order)) % len(WALK_DISTANCES_LOW_M)]
        return [_walk_step("s1", distance, ())]
    if skill == "turn":
        angle = TURN_ANGLES_DEG[(index // len(order)) % len(TURN_ANGLES_DEG)]
        signed = angle if index % 2 == 0 else -angle
        return [_turn_step("s1", signed, ())]
    if skill == "stand":
        duration = STAND_DURATIONS_S[(index // len(order)) % len(STAND_DURATIONS_S)]
        return [_stand_step("s1", duration, ())]
    return [_stop_step("s1", ())]


def _generate_composed_mission(
    horizon: str, index: int, length: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Deterministic composition: mixed primitives, final stop, chain deps."""
    allow_extension = length >= 8
    pool = ("stand", "walk_forward", "turn")
    skills: list[str] = [rng.choice(("stand", "walk_forward"))]
    while len(skills) < length - 1:
        choices = [s for s in pool if s != skills[-1]]
        skills.append(rng.choice(choices))
    skills.append("stop")
    if "walk_forward" not in skills:
        for i in range(len(skills) - 1):
            left = skills[i - 1] if i > 0 else None
            if left != "walk_forward" and skills[i + 1] != "walk_forward":
                skills[i] = "walk_forward"
                break
    for i in range(1, len(skills) - 1):
        if skills[i] == skills[i - 1]:
            skills[i] = rng.choice([s for s in pool if s != skills[i - 1]])
    steps: list[dict[str, Any]] = []
    previous: list[str] = []
    for i, skill in enumerate(skills, start=1):
        step_id = f"s{i}"
        if skill == "walk_forward":
            step = _walk_step(step_id, _choose_distance(rng, allow_extension=allow_extension), previous)
        elif skill == "turn":
            step = _turn_step(step_id, _choose_turn(rng), previous)
        elif skill == "stand":
            step = _stand_step(step_id, float(rng.choice(STAND_DURATIONS_S)), previous)
        else:
            step = _stop_step(step_id, previous)
        steps.append(step)
        previous = [step_id]
    return steps


def _mission_slug(steps: Iterable[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for step in steps:
        skill = str(step["skill"])
        if skill == "walk_forward":
            parts.append("w" + _fmt_num(step["parameters"]["distance_m"]))
        elif skill == "turn":
            angle = float(step["parameters"]["angle_deg"])
            parts.append(("l" if angle > 0 else "r") + _fmt_num(abs(angle)))
        elif skill == "stand":
            parts.append("s" + _fmt_num(step["parameters"]["duration_s"]))
        else:
            parts.append("x")
    return "-".join(parts)


def generate_canonical_missions(
    *, per_horizon: int = 20, seed: int = 2300
) -> list[dict[str, Any]]:
    """Generate the canonical mission set. Deterministic for a fixed seed."""
    if per_horizon <= 0:
        raise ValueError("per_horizon must be positive")
    missions: list[dict[str, Any]] = []
    for horizon, length in HORIZONS.items():
        for index in range(per_horizon):
            rng = _rng_for(seed, horizon, index)
            steps = (
                _generate_single_step_mission(horizon, index, rng)
                if length == 1
                else _generate_composed_mission(horizon, index, length, rng)
            )
            mission_id = f"lh-{horizon.lower()}-{index:02d}-{_mission_slug(steps)}"
            missions.append(
                {
                    "mission_id": mission_id,
                    "horizon": horizon,
                    "ir_step_count": len(steps),
                    "steps": steps,
                }
            )
    return missions


# ---------------------------------------------------------------------------
# Language realization (canonical IR -> text; template-only, deterministic)


def _skill_clause_l1(step: Mapping[str, Any]) -> str:
    skill = step["skill"]
    params = step["parameters"]
    if skill == "walk_forward":
        return f"向前走{_fmt_num(params['distance_m'])}米"
    if skill == "turn":
        angle = float(params["angle_deg"])
        direction = "向左转" if angle > 0 else "向右转"
        return f"{direction}{_fmt_num(abs(angle))}度"
    if skill == "stand":
        return f"站立{_fmt_num(params['duration_s'])}秒"
    return "停止"


def _skill_clause_l2(step: Mapping[str, Any]) -> str:
    skill = step["skill"]
    params = step["parameters"]
    if skill == "walk_forward":
        return f"向前走{_fmt_num(params['distance_m'])}米"
    if skill == "turn":
        angle = float(params["angle_deg"])
        return f"向左转{_fmt_num(abs(angle))}度" if angle > 0 else f"向右转{_fmt_num(abs(angle))}度"
    if skill == "stand":
        return f"保持站立{_fmt_num(params['duration_s'])}秒"
    return "停下来"


def _skill_clause_l3(step: Mapping[str, Any], variant: int) -> str:
    skill = step["skill"]
    params = step["parameters"]
    if skill == "walk_forward":
        distance = params["distance_m"]
        if variant == 1:
            return f"向前走{cn_number(distance)}米"
        if variant == 2:
            return f"往前走{distance:g}m"
        return f"往前走个{_fmt_num(distance)}米"
    if skill == "turn":
        angle = float(params["angle_deg"])
        direction = "往左拐" if angle > 0 else "往右拐"
        if variant == 1:
            return f"向{'左' if angle > 0 else '右'}转{cn_number(abs(angle))}度"
        return f"{direction}{_fmt_num(abs(angle))}°"
    if skill == "stand":
        duration = params["duration_s"]
        if variant == 1:
            return f"站着不动{cn_number(duration)}秒"
        return f"原地站{_fmt_num(duration)}秒"
    if variant == 1:
        return "最后立即停止"
    if variant == 2:
        return "最后停一下"
    return "最后停下来哈"


def _join_l1(steps: Sequence[Mapping[str, Any]]) -> str:
    clauses = [_skill_clause_l1(step) for step in steps]
    return "，然后".join(clauses) + "。"


def _join_l2(steps: Sequence[Mapping[str, Any]]) -> str:
    if len(steps) == 1:
        return "先" + _skill_clause_l2(steps[0]) + "。"
    clauses = [_skill_clause_l2(step) for step in steps]
    head, middle, tail = clauses[0], clauses[1:-1], clauses[-1]
    parts = ["先" + head]
    for clause in middle:
        parts.append("再" + clause)
    parts.append("最后" + tail)
    return "，然后".join([parts[0], *parts[1:-1]]) + "，" + parts[-1] + "。"


def _join_l3(steps: Sequence[Mapping[str, Any]], variant: int) -> str:
    clauses = [_skill_clause_l3(step, variant) for step in steps]
    if len(steps) == 1:
        return clauses[0] + ("。" if variant != 2 else "哈。")
    connector = {0: "接着", 1: "然后", 2: "然后呢"}[variant]
    body = f"，{connector}".join(clauses[:-1])
    text = f"{body}，{clauses[-1]}"
    if variant == 0:
        return f"麻烦你{text}，谢谢。"
    if variant == 2:
        return f"帮我{text}吧。"
    return text + "。"


def realize_text(steps: Sequence[Mapping[str, Any]], condition: str, *, variant: int = 0) -> str:
    if condition == "L1":
        return _join_l1(steps)
    if condition == "L2":
        return _join_l2(steps)
    if condition == "L3":
        return _join_l3(steps, variant % 3)
    raise ValueError(f"unknown language condition {condition!r}")


def realize_language_samples(
    missions: Sequence[Mapping[str, Any]], *, conditions: Sequence[str] = CONDITIONS
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for mission in missions:
        variant = int(hashlib.sha256(str(mission["mission_id"]).encode("utf-8")).hexdigest()[:8], 16) % 3
        for condition in conditions:
            text = realize_text(mission["steps"], condition, variant=variant)
            samples.append(
                {
                    "sample_id": f"{mission['mission_id']}__{condition}",
                    "mission_id": mission["mission_id"],
                    "horizon": mission["horizon"],
                    "condition": condition,
                    "text": text,
                }
            )
    return samples


# ---------------------------------------------------------------------------
# Safety controls (separate set; never part of the horizon success curves)


def _base_control_mission() -> dict[str, Any]:
    return {
        "mission_id": "lh-control-base",
        "horizon": "H8",
        "ir_step_count": 8,
        "steps": [
            _stand_step("s1", 2.0, ()),
            _walk_step("s2", 4.0, ("s1",)),
            _turn_step("s3", 45.0, ("s2",)),
            _walk_step("s4", 6.0, ("s3",)),
            _turn_step("s5", -45.0, ("s4",)),
            _walk_step("s6", 4.0, ("s5",)),
            _turn_step("s7", 90.0, ("s6",)),
            _stop_step("s8", ("s7",)),
        ],
    }


def generate_safety_controls() -> list[dict[str, Any]]:
    """Long-input safety controls; expected behavior verified against the
    frozen guard / compiler / grounder in later sessions."""
    base = _base_control_mission()
    text = realize_text(base["steps"], "L2")
    unsupported = text.replace("，然后", "，然后抓杯子，", 1) if "，然后" in text else text
    ambiguous_text = (
        "先保持站立2秒，然后向前走，再向右转45度，"
        "然后向前走4米，再向左转30度，最后停下来。"
    )
    unknown_steps = [dict(step) for step in base["steps"]]
    unknown_steps[3] = _walk_step("s4", CAPABILITY_UNKNOWN_DISTANCE_M, ("s3",))
    return [
        {
            "control_id": "lh-control-malformed-repeated-connector",
            "kind": "long_malformed",
            "text": text.replace("，然后", "，然后然后", 1),
            "expected_compiler_status": "MALFORMED",
            "expected_runtime": "NOT_RUN",
            "expected_note": "repeated connector inside a long valid mission",
        },
        {
            "control_id": "lh-control-malformed-dangling-connector",
            "kind": "long_malformed",
            "text": text[:-1] + "然后。",
            "expected_compiler_status": "MALFORMED",
            "expected_runtime": "NOT_RUN",
            "expected_note": "dangling trailing connector",
        },
        {
            "control_id": "lh-control-malformed-empty-clause",
            "kind": "long_malformed",
            "text": text.replace("，然后", "，，然后", 1),
            "expected_compiler_status": "MALFORMED",
            "expected_runtime": "NOT_RUN",
            "expected_note": "empty clause between separators",
        },
        {
            "control_id": "lh-control-ambiguous-missing-parameter",
            "kind": "long_ambiguous",
            "text": ambiguous_text,
            "expected_compiler_status": "AMBIGUOUS",
            "expected_runtime": "NOT_RUN",
            "expected_note": "one step is missing its distance parameter",
        },
        {
            "control_id": "lh-control-unsupported-embedded",
            "kind": "unsupported_embedded",
            "text": unsupported,
            "expected_compiler_status": "UNSUPPORTED",
            "expected_runtime": "NOT_RUN",
            "expected_note": "unsupported capability embedded inside a long mission",
        },
        {
            "control_id": "lh-control-capability-unknown-embedded",
            "kind": "capability_unknown_embedded",
            "text": realize_text(unknown_steps, "L2"),
            "expected_compiler_status": "SUCCESS",
            "expected_grounding": "CAPABILITY_UNKNOWN",
            "expected_runtime": "REJECTED_ZERO_STEP",
            "expected_note": (
                f"walk {CAPABILITY_UNKNOWN_DISTANCE_M:g} m has no recorded evidence; "
                "compiler may succeed, grounder must reject before execution"
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Validation and serialization


def validate_corpus(corpus: Mapping[str, Any]) -> list[str]:
    """Return a list of validation problems (empty means valid)."""
    problems: list[str] = []
    missions = list(corpus.get("canonical_missions", []))
    seen: set[str] = set()
    for mission in missions:
        mission_id = str(mission["mission_id"])
        if mission_id in seen:
            problems.append(f"duplicate mission_id {mission_id}")
        seen.add(mission_id)
        horizon = str(mission["horizon"])
        steps = list(mission["steps"])
        if len(steps) != HORIZONS[horizon]:
            problems.append(f"{mission_id}: {len(steps)} steps for horizon {horizon}")
        skills = [str(step["skill"]) for step in steps]
        for first, second in zip(skills, skills[1:]):
            if first == second:
                problems.append(f"{mission_id}: consecutive identical skill {first}")
        if len(steps) > 1 and skills[-1] != "stop":
            problems.append(f"{mission_id}: last step is {skills[-1]}, expected stop")
        if len(steps) > 1 and "walk_forward" not in skills:
            problems.append(f"{mission_id}: no walk step")
        for step in steps:
            skill = step["skill"]
            params = step["parameters"]
            if skill == "walk_forward":
                distance = float(params["distance_m"])
                if distance not in WALK_DISTANCES_ALLOWED_M:
                    problems.append(f"{mission_id}: ungrounded distance {distance}")
            elif skill == "turn":
                angle = abs(float(params["angle_deg"]))
                if angle not in TURN_ANGLES_DEG:
                    problems.append(f"{mission_id}: ungrounded turn {angle}")
            elif skill == "stand":
                duration = float(params["duration_s"])
                if duration not in STAND_DURATIONS_S:
                    problems.append(f"{mission_id}: ungrounded stand {duration}")
            elif skill != "stop":
                problems.append(f"{mission_id}: unknown skill {skill}")
    samples = list(corpus.get("language_samples", []))
    by_mission: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_mission.setdefault(str(sample["mission_id"]), []).append(sample)
    for mission_id, group in by_mission.items():
        texts = {str(sample["text"]) for sample in group}
        if len(texts) < len(group):
            problems.append(f"{mission_id}: duplicate realization text across conditions")
        conditions = {str(sample["condition"]) for sample in group}
        if conditions != set(CONDITIONS):
            problems.append(f"{mission_id}: missing language conditions {sorted(set(CONDITIONS) - conditions)}")
    missing = seen - set(by_mission)
    if missing:
        problems.append(f"{len(missing)} missions without language samples")
    return problems


def build_corpus(*, per_horizon: int = 20, seed: int = 2300) -> dict[str, Any]:
    missions = generate_canonical_missions(per_horizon=per_horizon, seed=seed)
    return {
        "schema_version": MISSION_SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "generator_version": GENERATOR_VERSION,
        "generator_seed": int(seed),
        "per_horizon": int(per_horizon),
        "horizons": dict(HORIZONS),
        "conditions": list(CONDITIONS),
        "grounding_evidence": dict(EVIDENCE_REFS),
        "parameter_pool": {
            "walk_distances_low_m": list(WALK_DISTANCES_LOW_M),
            "walk_distances_extension_m": list(WALK_DISTANCES_EXTENSION_M),
            "turn_angles_deg": list(TURN_ANGLES_DEG),
            "stand_durations_s": list(STAND_DURATIONS_S),
        },
        "canonical_missions": missions,
        "language_samples": realize_language_samples(missions),
        "safety_controls": generate_safety_controls(),
    }
