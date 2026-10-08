"""Phase 2.3 long-horizon corpus tests (generator + L1 self-check)."""

from __future__ import annotations

import yaml

from g1swarm.longhorizon import corpus as lh
from g1swarm.longhorizon import runner


def test_corpus_generation_is_deterministic() -> None:
    first = lh.build_corpus(per_horizon=2, seed=2300)
    second = lh.build_corpus(per_horizon=2, seed=2300)
    assert first == second


def test_corpus_structure_and_grounding_whitelist() -> None:
    corpus = lh.build_corpus(per_horizon=4, seed=2300)
    assert lh.validate_corpus(corpus) == []
    for mission in corpus["canonical_missions"]:
        steps = mission["steps"]
        assert len(steps) == lh.HORIZONS[mission["horizon"]]
        skills = [step["skill"] for step in steps]
        for first, second in zip(skills, skills[1:]):
            assert first != second
        if len(steps) > 1:
            assert skills[-1] == "stop"
        for step in steps:
            if step["skill"] == "walk_forward":
                assert step["parameters"]["distance_m"] in lh.WALK_DISTANCES_ALLOWED_M
            elif step["skill"] == "turn":
                assert abs(step["parameters"]["angle_deg"]) in lh.TURN_ANGLES_DEG
            elif step["skill"] == "stand":
                assert step["parameters"]["duration_s"] in lh.STAND_DURATIONS_S
            elif step["skill"] == "stop":
                assert step["parameters"] == {}


def test_language_conditions_are_present_and_distinct() -> None:
    corpus = lh.build_corpus(per_horizon=3, seed=2300)
    by_mission: dict[str, list[dict]] = {}
    for sample in corpus["language_samples"]:
        by_mission.setdefault(sample["mission_id"], []).append(sample)
    assert len(by_mission) == len(corpus["canonical_missions"])
    for samples in by_mission.values():
        conditions = {sample["condition"] for sample in samples}
        assert conditions == set(lh.CONDITIONS)
        texts = {sample["text"] for sample in samples}
        assert len(texts) == len(samples)


def test_l1_texts_reproduce_canonical_missions_with_frozen_grammar() -> None:
    corpus = lh.build_corpus(per_horizon=2, seed=2300)
    assert runner.verify_l1_realizations(corpus) == []


def test_safety_controls_cover_required_cases() -> None:
    corpus = lh.build_corpus(per_horizon=2, seed=2300)
    controls = {control["control_id"]: control for control in corpus["safety_controls"]}
    assert len(controls) == 6
    kinds = {control["kind"] for control in controls.values()}
    assert kinds == {
        "long_malformed",
        "long_ambiguous",
        "unsupported_embedded",
        "capability_unknown_embedded",
    }
    unknown = controls["lh-control-capability-unknown-embedded"]
    assert unknown["expected_compiler_status"] == "SUCCESS"
    assert unknown["expected_grounding"] == "CAPABILITY_UNKNOWN"
    assert unknown["expected_runtime"] == "REJECTED_ZERO_STEP"
    assert f"{lh.CAPABILITY_UNKNOWN_DISTANCE_M:g}米" in unknown["text"]
    malformed = [c for c in controls.values() if c["kind"] == "long_malformed"]
    assert len(malformed) == 3
    assert all(c["expected_compiler_status"] == "MALFORMED" for c in malformed)
    assert controls["lh-control-unsupported-embedded"]["expected_compiler_status"] == "UNSUPPORTED"


def test_generate_corpus_files_round_trip(tmp_path) -> None:
    outputs = runner.generate_corpus_files(per_horizon=2, seed=2300, out_dir=tmp_path)
    assert set(outputs) == {"canonical_missions", "language_realizations", "safety_controls"}
    missions = yaml.safe_load((tmp_path / "canonical_missions.yaml").read_text(encoding="utf-8"))
    samples = yaml.safe_load((tmp_path / "language_realizations.yaml").read_text(encoding="utf-8"))
    controls = yaml.safe_load((tmp_path / "safety_controls.yaml").read_text(encoding="utf-8"))
    corpus = {
        "canonical_missions": missions["missions"],
        "language_samples": samples["samples"],
        "safety_controls": controls["controls"],
    }
    assert lh.validate_corpus(corpus) == []
    assert runner.verify_l1_realizations(corpus) == []
