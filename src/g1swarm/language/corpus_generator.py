"""Deterministic, bounded corpus generator for the Phase 2.1 language study.

The generator follows the GPSR/SCAN methodology at the level of *ideas*: it
emits utterance / semantic-representation pairs from a grammar-shaped template
space, with a deterministic seed, a bounded sample count and no duplicate
utterances. The semantic representation is constructed directly from the chosen
structure - the compiler is never called - so the generated subset is an
independent expectation, not a parser artefact.

Generated samples deliberately stay inside the frozen Phase 2.0 evidence
envelope (walk 4/6/8/10/12/15/20 m, turns <= 90 deg, stands <= 20 s) and are
marked ``source: generated`` in the corpus.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261006
MAX_GENERATED_SAMPLES = 128

WALK_VERBS = ("前进", "往前走", "向前走", "向前移动", "往前移动")
TURN_LEFT_VERBS = ("左转", "向左转", "逆时针转")
TURN_RIGHT_VERBS = ("右转", "向右转", "顺时针转")
CONNECTORS = ("然后", "再", "接着", "之后", "最后")
DISTANCES_M = (4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0)
TURN_ANGLES_DEG = (30.0, 45.0, 60.0, 90.0)
STAND_DURATIONS_S = (1.0, 2.0, 5.0, 10.0, 20.0)
_CHINESE_NUMERAL_CHARS = "零〇一二两三四五六七八九十百千"

_CHINESE_INTEGER = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
    12: "十二",
    15: "十五",
    20: "二十",
    30: "三十",
    45: "四十五",
    60: "六十",
    90: "九十",
}


@dataclass(frozen=True)
class GeneratedSample:
    sample_id: str
    group_id: str
    category: str
    source: str
    utterance: str
    expected_compiler_status: str
    expected_error_code: str | None
    expected_mission: dict[str, Any] | None
    expected_runtime_status: str
    expected_failure_type: str | None
    expected_simulation_steps: int | None
    e2e: bool
    horizon: int | None
    oracle_mission_id: str | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "group_id": self.group_id,
            "category": self.category,
            "source": self.source,
            "utterance": self.utterance,
            "expected_compiler_status": self.expected_compiler_status,
            "expected_error_code": self.expected_error_code,
            "expected_mission": self.expected_mission,
            "expected_runtime_status": self.expected_runtime_status,
            "expected_failure_type": self.expected_failure_type,
            "expected_simulation_steps": self.expected_simulation_steps,
            "e2e": self.e2e,
            "horizon": self.horizon,
            "oracle_mission_id": self.oracle_mission_id,
            "notes": self.notes,
        }


def _mission(sample_id: str, steps: Sequence[tuple[str, dict[str, float]]]) -> dict[str, Any]:
    """Build an expected Mission IR document from an explicit step structure."""

    return {
        "schema_version": "2.0.0",
        "mission_id": f"oracle-{sample_id}",
        "steps": [
            {
                "id": f"s{index}",
                "skill": skill,
                "parameters": dict(parameters),
                **({"depends_on": [f"s{index - 1}"]} if index > 1 else {}),
            }
            for index, (skill, parameters) in enumerate(steps, start=1)
        ],
    }


def _sample(
    sample_id: str,
    group_id: str,
    category: str,
    utterance: str,
    steps: Sequence[tuple[str, dict[str, float]]],
    notes: str,
) -> GeneratedSample:
    return GeneratedSample(
        sample_id=sample_id,
        group_id=group_id,
        category=category,
        source="generated",
        utterance=utterance,
        expected_compiler_status="SUCCESS",
        expected_error_code=None,
        expected_mission=_mission(sample_id, steps),
        expected_runtime_status="SUCCESS",
        expected_failure_type=None,
        expected_simulation_steps=None,
        e2e=False,
        horizon=len(steps),
        oracle_mission_id=None,
        notes=notes,
    )


def _arabic(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _walk_forms(distance_m: float, verb: str, rng: random.Random) -> list[str]:
    candidates = [
        f"{verb}{_arabic(distance_m)}米",
        f"{verb}{_arabic(distance_m)}m",
        f"{verb}{_arabic(distance_m * 100)}厘米",
        f"{verb}{_arabic(distance_m * 100)}cm",
        f"{verb}{distance_m:.1f}米",
    ]
    chinese = _CHINESE_INTEGER.get(int(distance_m)) if float(distance_m).is_integer() else None
    if chinese is not None:
        candidates.append(f"{verb}{chinese}米")
    rng.shuffle(candidates)
    return candidates


def _atomic_candidates(rng: random.Random) -> list[tuple[str, list[tuple[str, dict[str, float]]], str]]:
    candidates: list[tuple[str, list[tuple[str, dict[str, float]]], str]] = []
    for distance in DISTANCES_M:
        verb = WALK_VERBS[rng.randrange(len(WALK_VERBS))]
        for form in _walk_forms(distance, verb, rng):
            # cm and Chinese-number forms belong to the dedicated unit/number
            # battery; keeping them out of the atomic battery avoids double
            # consuming the same utterance category.
            if "厘米" in form or "cm" in form:
                continue
            if any(char in _CHINESE_NUMERAL_CHARS for char in form):
                continue
            candidates.append(
                (form, [("walk_forward", {"distance_m": float(distance)})], f"generated atomic walk {distance:g} m")
            )
    for angle in TURN_ANGLES_DEG:
        left_verb = TURN_LEFT_VERBS[rng.randrange(len(TURN_LEFT_VERBS))]
        right_verb = TURN_RIGHT_VERBS[rng.randrange(len(TURN_RIGHT_VERBS))]
        candidates.append(
            (f"{left_verb}{_arabic(angle)}度", [("turn", {"angle_deg": float(angle)})], f"generated left turn {angle:g} deg")
        )
        candidates.append(
            (f"{right_verb}{_arabic(angle)}度", [("turn", {"angle_deg": -float(angle)})], f"generated right turn {angle:g} deg")
        )
    candidates.append(("停止", [("stop", {})], "generated stop synonym"))
    candidates.append(("立即停止", [("stop", {})], "generated stop synonym"))
    for duration in STAND_DURATIONS_S:
        candidates.append(
            (
                f"站立{_arabic(duration)}秒",
                [("stand", {"duration_s": float(duration)})],
                f"generated stand {duration:g} s",
            )
        )
    rng.shuffle(candidates)
    return candidates


def _unit_candidates() -> list[tuple[str, list[tuple[str, dict[str, float]]], str]]:
    plans = [
        ("前进400厘米", 4.0),
        ("前进600厘米", 6.0),
        ("前进800厘米", 8.0),
        ("前进1200厘米", 12.0),
        ("前进四米", 4.0),
        ("前进八米", 8.0),
        ("前进十五米", 15.0),
        ("前进二十米", 20.0),
    ]
    return [
        (form, [("walk_forward", {"distance_m": value})], f"generated unit/number variant {value:g} m")
        for form, value in plans
    ]


def _sequence_candidates(rng: random.Random) -> list[tuple[str, list[tuple[str, dict[str, float]]], str]]:
    connectors = list(CONNECTORS)
    rng.shuffle(connectors)
    plans: list[tuple[list[tuple[str, dict[str, float]]], str]] = [
        (
            [("walk_forward", {"distance_m": 4.0}), ("turn", {"angle_deg": 45.0}), ("stop", {})],
            "generated walk4-left45-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 6.0}), ("turn", {"angle_deg": -45.0}), ("stop", {})],
            "generated walk6-right45-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 8.0}), ("turn", {"angle_deg": 90.0}), ("walk_forward", {"distance_m": 4.0})],
            "generated walk8-left90-walk4 sequence",
        ),
        (
            [("turn", {"angle_deg": -45.0}), ("walk_forward", {"distance_m": 6.0}), ("stop", {})],
            "generated right45-walk6-stop sequence",
        ),
        (
            [("stand", {"duration_s": 2.0}), ("walk_forward", {"distance_m": 4.0}), ("stop", {})],
            "generated stand2-walk4-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 12.0}), ("turn", {"angle_deg": -90.0}), ("stop", {})],
            "generated walk12-right90-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 4.0}), ("turn", {"angle_deg": 45.0}), ("walk_forward", {"distance_m": 4.0}), ("stop", {})],
            "generated walk4-left45-walk4-stop sequence",
        ),
        (
            [("stand", {"duration_s": 5.0}), ("walk_forward", {"distance_m": 6.0}), ("turn", {"angle_deg": -45.0}), ("stop", {})],
            "generated stand5-walk6-right45-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 10.0}), ("turn", {"angle_deg": -90.0}), ("walk_forward", {"distance_m": 6.0}), ("stop", {})],
            "generated walk10-right90-walk6-stop sequence",
        ),
        (
            [("turn", {"angle_deg": -90.0}), ("walk_forward", {"distance_m": 6.0}), ("turn", {"angle_deg": 90.0}), ("stop", {})],
            "generated right90-walk6-left90-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 15.0}), ("turn", {"angle_deg": 30.0}), ("walk_forward", {"distance_m": 4.0}), ("stop", {})],
            "generated walk15-left30-walk4-stop sequence",
        ),
        (
            [("walk_forward", {"distance_m": 4.0}), ("turn", {"angle_deg": 60.0}), ("walk_forward", {"distance_m": 4.0}), ("turn", {"angle_deg": -60.0}), ("stop", {})],
            "generated walk4-left60-walk4-right60-stop sequence",
        ),
    ]
    candidates: list[tuple[str, list[tuple[str, dict[str, float]]], str]] = []
    for plan, note in plans:
        parts: list[str] = []
        labels = {
            "walk_forward": WALK_VERBS[rng.randrange(len(WALK_VERBS))],
            "turn_left": TURN_LEFT_VERBS[rng.randrange(len(TURN_LEFT_VERBS))],
            "turn_right": TURN_RIGHT_VERBS[rng.randrange(len(TURN_RIGHT_VERBS))],
        }
        for index, (skill, parameters) in enumerate(plan):
            if skill == "walk_forward":
                verb = labels["walk_forward"]
                forms = _walk_forms(float(parameters["distance_m"]), verb, rng)
                parts.append(forms[0])
            elif skill == "turn":
                angle = float(parameters["angle_deg"])
                verb = labels["turn_left"] if angle > 0 else labels["turn_right"]
                parts.append(f"{verb}{_arabic(abs(angle))}度")
            elif skill == "stop":
                parts.append(rng.choice(("停止", "停下", "立即停止")))
            elif skill == "stand":
                parts.append(f"站立{_arabic(float(parameters['duration_s']))}秒")
            else:  # pragma: no cover - defensive, plans are fixed above
                raise ValueError(f"unsupported generator skill {skill!r}")
        punctuated = parts[0]
        plain = parts[0]
        for connector_index, command in enumerate(parts[1:]):
            connector = connectors[connector_index % len(connectors)]
            punctuated += f"，{connector}{command}"
            plain += f"{connector}{command}"
        candidates.append((punctuated, list(plan), note))
        # A punctuation-free variant keeps the same structure with a different
        # surface form; connector words alone carry the sequence.
        candidates.append((plain, list(plan), note + " (no punctuation)"))
    rng.shuffle(candidates)
    return candidates


def generate_samples(
    *,
    seed: int = DEFAULT_SEED,
    count: int = 38,
    avoid_utterances: Iterable[str] = (),
) -> tuple[GeneratedSample, ...]:
    """Generate ``count`` deterministic utterance/IR pairs.

    ``avoid_utterances`` keeps the generated subset disjoint from the
    hand-authored subset; the same value reproduces the frozen corpus exactly.
    """

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_GENERATED_SAMPLES:
        raise ValueError(f"count must not exceed the {MAX_GENERATED_SAMPLES} bound")

    rng = random.Random(int(seed))
    avoid = set(avoid_utterances)
    atomic = _atomic_candidates(rng)
    units = _unit_candidates()
    sequences = _sequence_candidates(rng)

    wanted = {
        "atomic_valid": max(1, round(count * 12 / 38)),
        "unit_variant": max(1, round(count * 8 / 38)),
    }
    wanted["sequence_variant"] = count - wanted["atomic_valid"] - wanted["unit_variant"]

    selected: list[GeneratedSample] = []
    seen: set[str] = set()

    def take(
        candidates: list[tuple[str, list[tuple[str, dict[str, float]]], str]],
        group_id: str,
        category: str,
        limit: int,
    ) -> None:
        taken = 0
        for utterance, steps, note in candidates:
            if taken >= limit or len(selected) >= count:
                break
            if utterance in avoid or utterance in seen:
                continue
            seen.add(utterance)
            sample_id = f"cl-gen-{len(selected) + 1:03d}"
            # Generated batteries hold many different missions, so each sample
            # gets its own group id; paraphrase consistency is only meaningful
            # for the hand-authored paraphrase groups.
            group_id = f"{group_id}-{len(selected) + 1:03d}"
            selected.append(_sample(sample_id, group_id, category, utterance, steps, note))
            taken += 1

    take(atomic, "gen-atomic-battery", "atomic_valid", wanted["atomic_valid"])
    take(units, "gen-unit-number-battery", "unit_variant", wanted["unit_variant"])
    take(sequences, "gen-sequence-battery", "sequence_variant", wanted["sequence_variant"])

    if len(selected) != count:
        # Top up deterministically from every remaining candidate before
        # failing; a shortfall means the template space is exhausted.
        for candidates, group_id, category in (
            (atomic, "gen-atomic-battery", "atomic_valid"),
            (units, "gen-unit-number-battery", "unit_variant"),
            (sequences, "gen-sequence-battery", "sequence_variant"),
        ):
            take(candidates, group_id, category, count - len(selected))
        if len(selected) != count:
            raise ValueError(
                f"generator template space exhausted: produced {len(selected)} of {count}"
            )
    return tuple(selected)
