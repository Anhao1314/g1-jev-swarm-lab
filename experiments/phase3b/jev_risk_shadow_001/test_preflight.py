"""Mock-only tests for the non-scored, synthetic Jev preflight."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("jev_risk_preflight", Path(__file__).with_name("preflight.py"))
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def answer():
    return {"model": "jev-release", "answers": {"strict_risk": {
        "type": "choice", "choice": "STRICT_PASS", "confidence": 0.75,
        "probabilities": {"STRICT_VIOLATION": 0.25, "STRICT_PASS": 0.75},
    }}, "usage": {"input_tokens": 12, "output_tokens": 3}}


def test_non_scored_preflight(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "secret-test-key")
    calls = []

    def models(key, timeout):
        calls.append("models")
        return 200, json.dumps({"models": [{"name": "jev-latest", "description": "test",
                                               "release_date": "2026-01-01"}]}).encode()

    def question(body, key, timeout):
        calls.append("question")
        assert json.loads(body)["state"]["synthetic_preflight_only"] is True
        return 200, json.dumps(answer()).encode()

    receipt = preflight.run_preflight(evidence_dir=tmp_path, models_transport=models,
                                      question_transport=question)
    assert calls == ["models", "question"]
    assert receipt["purpose"] == "NON_SCORED_CONNECTION_PREFLIGHT"
    assert receipt["typed_question_model"] == "jev-release"
    assert receipt["typed_question_usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert receipt["transport_attempts"] == 2
    assert "secret-test-key" not in (tmp_path / "preflight_receipt.json").read_text()
    assert "secret-test-key" not in (tmp_path / "synthetic_question.json").read_text()
    with pytest.raises(FileExistsError):
        preflight.run_preflight(evidence_dir=tmp_path, models_transport=models,
                                question_transport=question)


def test_unavailable_model_skips_question(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "secret-test-key")
    receipt = preflight.run_preflight(
        evidence_dir=tmp_path,
        models_transport=lambda *_: (200, b'{"models": [{"name": "other"}]}'),
        question_transport=lambda *_: (_ for _ in ()).throw(AssertionError("called")),
    )
    assert receipt["failure"] == "MODEL_UNAVAILABLE"
    assert receipt["transport_attempts"] == 1


def test_no_key_prevents_network(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        preflight.run_preflight(evidence_dir=tmp_path,
            models_transport=lambda *_: (_ for _ in ()).throw(AssertionError("called")))
