"""Offline-only TypeSafe System One risk client. Importing this module never sends a request.

The caller must supply already frozen, decision-time state and an evidence directory.
This module has no robot, controller, outcome, or label dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
QUESTION = "strict_risk"
CRITERIA = {
    "STRICT_VIOLATION": "The current node will violate its frozen strict criterion.",
    "STRICT_PASS": "The current node will pass its frozen strict criterion.",
}
Transport = Callable[[bytes, str, float], tuple[int, bytes]]


def build_request(state: Mapping[str, Any]) -> dict[str, Any]:
    """Construct the single frozen risk question; no outcome lookup is performed."""
    if not isinstance(state, Mapping) or not state:
        raise ValueError("state must be a nonempty mapping")
    # A round trip rejects unserializable values and takes a defensive copy.
    copied = json.loads(json.dumps(dict(state), allow_nan=False, sort_keys=True))
    return {
        "model": MODEL,
        "state": copied,
        "questions": {QUESTION: {
            "type": "choice",
            "instructions": "Predict the future strict outcome using only this decision-time state.",
            "criteria": CRITERIA,
        }},
    }


def parse_response(document: Any) -> dict[str, Any]:
    """Fail closed on malformed or inconsistent probabilities; never infer a command."""
    if not isinstance(document, dict) or not isinstance(document.get("model"), str) or not document["model"]:
        raise ValueError("invalid response model")
    answers = document.get("answers")
    if not isinstance(answers, dict) or set(answers) != {QUESTION}:
        raise ValueError("invalid answer keys")
    answer = answers[QUESTION]
    if (not isinstance(answer, dict) or set(answer) != {"type", "choice", "confidence", "probabilities"}
            or answer.get("type") != "choice"):
        raise ValueError("invalid answer type")
    choice = answer.get("choice")
    probabilities = answer.get("probabilities")
    confidence = answer.get("confidence")
    if choice not in CRITERIA or not isinstance(probabilities, dict) or set(probabilities) != set(CRITERIA):
        raise ValueError("invalid choice or probabilities")
    if not _unit(confidence) or any(not _unit(p) for p in probabilities.values()):
        raise ValueError("nonfinite or out-of-range probability")
    if abs(sum(probabilities.values()) - 1.0) > 0.01:
        raise ValueError("probabilities do not sum to one")
    if probabilities[choice] + 1e-9 < max(probabilities.values()):
        raise ValueError("choice conflicts with probabilities")
    usage = document.get("usage")
    if not isinstance(usage, dict) or any(
        not isinstance(usage.get(k), int) or isinstance(usage.get(k), bool) or usage[k] < 0
        for k in ("input_tokens", "output_tokens")
    ):
        raise ValueError("invalid usage")
    return {
        "model": document["model"],
        "choice": choice,
        "probability_strict_violation": probabilities["STRICT_VIOLATION"],
        "confidence": confidence,
        "usage": {k: usage[k] for k in ("input_tokens", "output_tokens")},
    }


def _unit(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def _http_transport(body: bytes, key: str, timeout_s: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def evaluate_once(
    *, state: Mapping[str, Any], sample_id: str, evidence_dir: Path,
    timeout_s: float = 30.0, transport: Transport | None = None,
) -> dict[str, Any]:
    """Make exactly one explicit call and retain its raw evidence, including failures.

    Calls are synchronous, so an outer serial loop preserves caller order. Each
    sample ID is write-once to prevent silent replacement of prior evidence.
    """
    key = os.environ.get("JEV_API_KEY", "")
    if not key:
        raise RuntimeError("JEV_API_KEY is unavailable")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", sample_id):
        raise ValueError("invalid sample_id")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    payload = build_request(state)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / f"{sample_id}.json"
    if target.exists():
        raise FileExistsError(target)
    started = time.monotonic()
    status: int | None = None
    raw: bytes | None = None
    parsed: dict[str, Any] | None = None
    failure: str | None = None
    try:
        status, raw = (transport or _http_transport)(body, key, timeout_s)
        if status != 200:
            failure = f"HTTP_{status}"
        else:
            parsed = parse_response(json.loads(raw))
    except Exception as error:
        # Never retain arbitrary exception messages: a transport may include headers.
        failure = f"{type(error).__name__}"
    elapsed = time.monotonic() - started
    record = {
        "sample_id": sample_id,
        "endpoint": ENDPOINT,
        "request_sha256": hashlib.sha256(body).hexdigest(),
        "request": payload,
        "http_status": status,
        "raw_response_text": raw.decode("utf-8", errors="replace").replace(key, "[REDACTED]") if raw is not None else None,
        "response_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "result": parsed,
        "failure": failure,
        "availability": parsed is not None,
        "latency_s": elapsed,
        "transport_attempts": 1,
    }
    # Atomic create, no overwrite, and no credentials in the record.
    with target.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return record
