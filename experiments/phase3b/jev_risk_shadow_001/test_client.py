"""Mock-only contract checks; these tests never open a network connection."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("jev_risk_client", Path(__file__).with_name("client.py"))
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


def response(p=0.8, choice="STRICT_VIOLATION"):
    return {"model": "jev-2026", "answers": {"strict_risk": {
        "type": "choice", "choice": choice, "confidence": 0.8,
        "probabilities": {"STRICT_VIOLATION": p, "STRICT_PASS": 1-p},
    }}, "usage": {"input_tokens": 10, "output_tokens": 4}}


def test_typed_success_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "secret-test-key")
    calls = []

    def transport(body, key, timeout):
        calls.append((json.loads(body), key, timeout))
        return 200, json.dumps(response()).encode()

    record = client.evaluate_once(state={"route_position_m": 3.0}, sample_id="case_1",
                                  evidence_dir=tmp_path, transport=transport)
    assert len(calls) == 1
    assert calls[0][0]["questions"]["strict_risk"]["criteria"] == client.CRITERIA
    assert record["result"]["probability_strict_violation"] == 0.8
    assert record["transport_attempts"] == 1 and record["availability"]
    assert "secret-test-key" not in (tmp_path / "case_1.json").read_text()
    with pytest.raises(FileExistsError):
        client.evaluate_once(state={"route_position_m": 3.0}, sample_id="case_1",
                             evidence_dir=tmp_path, transport=transport)
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [
    {**response(), "answers": {}},
    response(p=1.2),
    response(p=0.8, choice="STRICT_PASS"),
    {**response(), "usage": {"input_tokens": -1, "output_tokens": 2}},
])
def test_invalid_response_fails_closed(bad, tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "secret-test-key")
    record = client.evaluate_once(state={"x": 1}, sample_id="bad", evidence_dir=tmp_path,
                                  transport=lambda *_: (200, json.dumps(bad).encode()))
    assert record["result"] is None and not record["availability"]
    assert record["failure"] == "ValueError"


def test_transport_failure_is_recorded_once(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "secret-test-key")
    calls = []

    def failing(*_):
        calls.append(True)
        raise TimeoutError("secret-test-key")

    record = client.evaluate_once(state={"x": 1}, sample_id="timeout",
                                  evidence_dir=tmp_path, transport=failing)
    assert len(calls) == 1 and record["failure"] == "TimeoutError"
    assert "secret-test-key" not in (tmp_path / "timeout.json").read_text()


def test_missing_key_prevents_call(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        client.evaluate_once(state={"x": 1}, sample_id="missing", evidence_dir=tmp_path,
                             transport=lambda *_: (_ for _ in ()).throw(AssertionError("called")))
