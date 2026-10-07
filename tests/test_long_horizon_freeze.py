"""Phase 2.3 protocol-freeze verification tests (Session 3 checks)."""

from __future__ import annotations

import hashlib
import json

import yaml

from g1swarm.config import load_yaml
from g1swarm.longhorizon import corpus as lh
from g1swarm.longhorizon import runner
from g1swarm.paths import repo_root

BASE = repo_root() / "experiments" / "phase2" / "long_horizon_language_001"
FINAL = BASE / "final"


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _final_corpus() -> dict:
    missions = load_yaml(FINAL / "canonical_missions_final.yaml")["missions"]
    samples = load_yaml(FINAL / "language_realizations_final.yaml")["samples"]
    return {"canonical_missions": missions, "language_samples": samples, "safety_controls": []}


def _protocol() -> dict:
    return yaml.safe_load((BASE / "protocol.yaml").read_text(encoding="utf-8"))


def test_final_corpus_sizes_and_horizon_distribution() -> None:
    corpus = _final_corpus()
    missions = corpus["canonical_missions"]
    assert len(missions) == 102
    assert len([s for s in corpus["language_samples"]]) == 306
    per_horizon = {}
    for mission in missions:
        per_horizon[mission["horizon"]] = per_horizon.get(mission["horizon"], 0) + 1
    assert per_horizon == {h: 17 for h in lh.HORIZONS}


def test_pilot_final_exclusion_is_total() -> None:
    pilot = json.loads((BASE / "pilot_selection.json").read_text(encoding="utf-8"))
    pilot_ids = {m["mission_id"] for m in pilot["missions"]}
    assert pilot["excluded_from_final"] is True
    corpus = _final_corpus()
    final_ids = {m["mission_id"] for m in corpus["canonical_missions"]}
    assert pilot_ids & final_ids == set()
    pilot_artifact = (
        repo_root()
        / "artifacts"
        / "long_horizon_language_001"
        / "pilot"
        / "language_realizations.yaml"
    )
    pilot_texts = {s["text"].strip() for s in load_yaml(pilot_artifact)["samples"]}
    final_texts = {s["text"].strip() for s in corpus["language_samples"]}
    assert pilot_texts & final_texts == set()


def test_final_corpus_is_validated_and_grounded() -> None:
    corpus = _final_corpus()
    assert lh.validate_corpus(corpus) == []
    for mission in corpus["canonical_missions"]:
        for step in mission["steps"]:
            if step["skill"] == "walk_forward":
                assert step["parameters"]["distance_m"] in lh.WALK_DISTANCES_ALLOWED_M
            elif step["skill"] == "turn":
                assert abs(step["parameters"]["angle_deg"]) in lh.TURN_ANGLES_DEG
            elif step["skill"] == "stand":
                assert step["parameters"]["duration_s"] in lh.STAND_DURATIONS_S


def test_final_l1_self_check_under_frozen_lark() -> None:
    corpus = _final_corpus()
    assert runner.verify_l1_realizations(corpus) == []


def test_protocol_freeze_candidate_state() -> None:
    protocol = _protocol()
    assert protocol["status"] == "draft"
    assert protocol["frozen"] is False
    candidate = protocol["freeze_candidate"]
    assert candidate["state"] == "prepared_pending_ood_sidecar"
    assert candidate["final_sample_size"]["canonical_missions"] == 102
    assert candidate["final_sample_size"]["language_samples"] == 306
    sidecar = candidate["guard_ood_safety_sidecar"]
    assert sidecar["status"] == "pending_independent_authoring_session"
    assert sidecar["freeze_blocking"] is True
    assert candidate["no_pretty_gates"] is True


def test_provider_configuration_unchanged() -> None:
    protocol = _protocol()
    provider = protocol["provider"]
    assert provider["model"] == "deepseek-flash"
    assert float(provider["temperature"]) == 0.0
    assert int(provider["max_output_tokens"]) == 4096
    assert float(provider["timeout_s"]) == 60.0
    assert int(provider["max_network_retries"]) == 2
    compiler = protocol["freeze_candidate"]["compiler_provenance"]
    assert compiler["architecture"] == "guarded_direct_llm_v1"
    assert compiler["guard_version"] == "2.2b.2"
    assert (
        compiler["prompt_sha256"]
        == "913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110"
    )


def test_attempts_schema_is_required() -> None:
    protocol = _protocol()
    required = protocol["freeze_candidate"]["attempts_persistence"]["required_fields"]
    assert required == ["provider_attempts", "retry_reason", "terminal_transport_status"]
    # the record builder must expose provider_attempts
    record = runner.benchmark.compiler_record(
        experiment_id="x",
        sample={"sample_id": "s", "mission_id": "m", "horizon": "H1", "condition": "L1", "text": "t"},
        mission={"mission_id": "m", "steps": [{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}, "depends_on": []}]},
        result=type("R", (), {"status": None, "mission": None, "diagnostics": {}, "error_code": None, "error_message": None})(),
        provenance={},
    )
    assert "provider_attempts" in record


def test_evidence_paths_are_campaign_scoped() -> None:
    protocol = _protocol()
    for value in protocol["evidence"].values():
        if isinstance(value, list):
            continue
        assert not str(value).startswith("/")
        assert "pilot" not in str(value)


def test_ood_and_main_corpus_are_separated() -> None:
    protocol = _protocol()
    sidecar = protocol["freeze_candidate"]["guard_ood_safety_sidecar"]
    assert "never in the H1-H16 curves" in sidecar["separation"]
    mission_text = (FINAL / "canonical_missions_final.yaml").read_text(encoding="utf-8")
    assert "ood" not in mission_text.lower()
    language_text = (FINAL / "language_realizations_final.yaml").read_text(encoding="utf-8")
    assert "ood" not in language_text.lower()


def test_freeze_manifest_hashes_are_reproducible() -> None:
    manifest = json.loads((BASE / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_status"] == "pending_ood_sidecar"
    assert manifest["freeze_commit"] is None
    assert manifest["ood_dataset_sha256"] is None
    assert manifest["protocol"]["sha256"] == _sha(BASE / "protocol.yaml")
    assert manifest["canonical_corpus"]["sha256"] == _sha(FINAL / "canonical_missions_final.yaml")
    assert manifest["language_corpus"]["sha256"] == _sha(FINAL / "language_realizations_final.yaml")
    assert manifest["pilot_exclusion"]["sha256"] == _sha(BASE / "pilot_selection.json")
    assert manifest["leakage_audit"]["pilot_final_id_overlap"] == 0
    assert manifest["leakage_audit"]["historical_exact_text_overlap"]["phase2.2_blind"] == 0
