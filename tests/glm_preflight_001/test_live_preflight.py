"""Live-runner tests use mocked opener only, never a real key or API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from scripts.glm_preflight_001 import live_preflight as live

KEY = "SYNTHETIC_PREFLIGHT_KEY_NOT_A_REAL_CREDENTIAL_002"
REASONING = "MOCK_PRIVATE_REASONING_NEVER_PERSIST_THIS"


def certificate(**changes):
    result = {"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
              "plan": [["stand", 3], ["stop"]], "issues": []}
    result.update(changes)
    return result


def wire(content, *, usage=None, model="glm-5.3-flash", finish="stop", reasoning=REASONING):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"id": "fixture-response", "model": model,
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}}


def responses(*, reasoning=REASONING):
    return [wire("GLM_PREFLIGHT_OK", reasoning=reasoning),
            wire('{"preflight":"glm-5.3-flash","value":1}', reasoning=reasoning),
            wire(json.dumps(certificate()), reasoning=reasoning)]


class Response:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.raw[:limit]


def stub(monkeypatch, events):
    queue = list(events)
    calls = []
    sleeps = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append({"url": request.full_url, "body": json.loads(request.data), "timeout": timeout})
            event = queue.pop(0)
            if isinstance(event, BaseException):
                raise event
            return Response(json.dumps(event).encode("utf8"))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr("g1swarm.glm_preflight_001.chat_backend.time.sleep", sleeps.append)
    return calls, sleeps


def test_three_checks_ready_and_callback_receipts_are_secret_safe(monkeypatch):
    calls, sleeps = stub(monkeypatch, responses())
    progress = []
    receipt = live.run_preflight(KEY, progress=progress.append)
    assert receipt["ready"] and receipt["status"] == "READY"
    assert receipt["provider_calls"] == 3 and receipt["provider_attempts"] == 3
    assert all(item["passed"] for item in receipt["checks"])
    assert len(calls) == 3 and sleeps == [] and len(progress) == 3
    assert [item["name"] for item in progress] == list(live.CHECKS)
    assert all(item["url"] == live.BASE_URL + "/chat/completions" and item["timeout"] == 60 for item in calls)
    assert "response_format" not in calls[0]["body"]
    assert calls[1]["body"]["response_format"] == calls[2]["body"]["response_format"] == {"type": "json_object"}
    assert json.loads(calls[2]["body"]["messages"][1]["content"]) == {"source": live.SOURCE}
    assert receipt["checks"][2]["certificate"]["plan"] == [["stand", 3.0], ["stop"]]
    serialized = json.dumps({"receipt": receipt, "progress": progress}, ensure_ascii=False)
    assert KEY not in serialized and REASONING not in serialized
    assert receipt["reasoning_observation"] == "OBSERVED"
    assert receipt["token_stats"] == {"reported_total_tokens": 375, "requests_with_reported_total": 3,
                                     "requests_without_reported_total": 0, "attempts_without_reported_usage": 0,
                                     "reported_usage_complete_for_all_attempts": True}
    assert receipt["scored_calls"] == receipt["runtime_calls"] == receipt["held_out_calls"] == 0
    assert not receipt["billing_deduction_claimed"]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_first_failure_stops_remaining_checks_without_repair(monkeypatch, index):
    events = responses()
    events[index]["choices"][0]["finish_reason"] = "length"
    calls, sleeps = stub(monkeypatch, events)
    progress = []
    receipt = live.run_preflight(KEY, progress=progress.append)
    assert not receipt["ready"] and receipt["status"] == "NOT_READY"
    assert len(calls) == index + 1 and len(progress) == index + 1 and sleeps == []
    assert receipt["checks"][index]["status"] == "FAIL"
    assert all(item["status"] == "NOT_RUN" for item in receipt["checks"][index + 1:])


@pytest.mark.parametrize("kind", ["AMBIGUOUS", "UNKNOWN", "wrong_plan", "malformed"])
def test_typed_certificate_parse_success_alone_cannot_make_ready(monkeypatch, kind):
    events = responses()
    if kind in {"AMBIGUOUS", "UNKNOWN"}:
        body = certificate(status=kind, checks=["U"] * 6 + ["A" if kind == "AMBIGUOUS" else "?"], plan=None,
                           issues=[{"relation": "unresolved", "reason": "UNRESOLVED"}] if kind == "AMBIGUOUS"
                           else [{"relation": "unknown", "reason": "UNKNOWN"}])
    elif kind == "wrong_plan":
        body = certificate(plan=[["stand", 4], ["stop"]])
    else:
        body = {"incorrect": "certificate"}
    events[2]["choices"][0]["message"]["content"] = json.dumps(body)
    calls, _ = stub(monkeypatch, events)
    receipt = live.run_preflight(KEY)
    assert not receipt["ready"] and len(calls) == 3
    assert not receipt["checks"][2]["passed"]


@pytest.mark.parametrize("usage", [{"prompt_tokens": 0, "completion_tokens": 25, "total_tokens": 25},
                                   {"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100},
                                   {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                                   {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 0},
                                   {"prompt_tokens": 100, "completion_tokens": 25},
                                   {"prompt_tokens": True, "completion_tokens": 25, "total_tokens": 26},
                                   {"prompt_tokens": -1, "completion_tokens": 25, "total_tokens": 24}])
def test_positive_complete_usage_is_required_for_ready(monkeypatch, usage):
    events = responses()
    events[0]["usage"] = usage
    calls, _ = stub(monkeypatch, events)
    receipt = live.run_preflight(KEY)
    assert not receipt["ready"] and len(calls) == 1


@pytest.mark.parametrize("reasoning", [None, ""])
def test_absent_or_empty_reasoning_is_not_claimed_observed(monkeypatch, reasoning):
    stub(monkeypatch, responses(reasoning=reasoning))
    receipt = live.run_preflight(KEY)
    assert receipt["ready"]
    assert receipt["reasoning_observation"] == "NOT_OBSERVED"
    assert receipt["reasoning_effort_policy"] == "omitted_provider_default_not_live_verified"


def test_reasoning_only_failure_records_usage_without_reasoning_text(monkeypatch):
    calls, _ = stub(monkeypatch, [wire(None, finish="length")])
    receipt = live.run_preflight(KEY)
    assert not receipt["ready"] and len(calls) == 1
    error = receipt["checks"][0]["error"]
    assert error["reason"] == "NO_FINAL_ASSISTANT_CONTENT"
    assert error["usage"]["total_tokens"] == 125
    assert receipt["token_stats"]["reported_total_tokens"] == 125
    assert REASONING not in json.dumps(receipt)


def test_failed_transport_unknown_usage_is_not_reported_as_zero_known_cost(monkeypatch):
    failure = urllib.error.URLError("fixture transport failure containing " + KEY)
    calls, sleeps = stub(monkeypatch, [failure] * 3)
    receipt = live.run_preflight(KEY)
    assert not receipt["ready"] and len(calls) == 3 and sleeps == [0.5, 1.0]
    assert receipt["provider_calls"] == 1 and receipt["provider_attempts"] == 3
    assert receipt["token_stats"]["reported_total_tokens"] is None
    assert receipt["token_stats"]["attempts_without_reported_usage"] == 3
    assert not receipt["token_stats"]["reported_usage_complete_for_all_attempts"]
    assert KEY not in json.dumps(receipt)


def test_success_after_transport_retry_keeps_attempt_usage_gap(monkeypatch):
    events = responses()
    events.insert(0, urllib.error.HTTPError(live.BASE_URL, 503, "fixture", {}, None))
    calls, _ = stub(monkeypatch, events)
    receipt = live.run_preflight(KEY)
    assert receipt["ready"] and len(calls) == 4
    assert receipt["provider_calls"] == 3 and receipt["provider_attempts"] == 4
    assert receipt["token_stats"]["reported_total_tokens"] == 375
    assert receipt["token_stats"]["attempts_without_reported_usage"] == 1


@pytest.mark.parametrize("url", ["https://other.invalid", live.BASE_URL + "/", "https://open.bigmodel.cn/api/anthropic"])
def test_credentials_are_never_sent_outside_pinned_standard_route(monkeypatch, url):
    calls, _ = stub(monkeypatch, [])
    receipt = live.run_preflight(KEY, base_url=url)
    assert not receipt["ready"] and calls == [] and receipt["provider_calls"] == 0
    assert KEY not in json.dumps(receipt)


def test_credential_echo_never_reaches_certificate_hash_or_progress(monkeypatch):
    events = responses()
    events[2]["choices"][0]["message"]["content"] = KEY
    calls, _ = stub(monkeypatch, events)
    progress = []
    receipt = live.run_preflight(KEY, progress=progress.append)
    assert not receipt["ready"] and len(calls) == 3
    assert receipt["checks"][2]["error"]["reason"] == "CREDENTIAL_ECHO"
    assert KEY not in json.dumps({"receipt": receipt, "progress": progress})


def test_callback_failure_stops_and_never_copies_exception_text(monkeypatch):
    calls, _ = stub(monkeypatch, responses())
    def failed_callback(_):
        raise RuntimeError(KEY)
    receipt = live.run_preflight(KEY, progress=failed_callback)
    assert not receipt["ready"] and len(calls) == 1
    assert receipt["callback_error"]["reason"] == "CALLBACK_FAILED"
    assert KEY not in json.dumps(receipt)


def test_observer_reuse_cannot_create_second_actual_provider_call():
    class Backend:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return object()
    backend = Backend()
    observer = live._Observer(backend, KEY)
    with pytest.raises(Exception):
        observer.complete(system_prompt="s", user_text="u")
    with pytest.raises(Exception):
        observer.complete(system_prompt="s", user_text="u")
    assert backend.calls == observer.calls == 1
