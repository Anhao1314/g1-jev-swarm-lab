"""Non-scored Jev connection preflight with a synthetic state and no benchmark labels.

No network activity occurs on import. Run explicitly after JEV_API_KEY is available.
Receipts belong in ignored artifacts, never in scored benchmark evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

_SPEC = importlib.util.spec_from_file_location("jev_risk_client", Path(__file__).with_name("client.py"))
client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(client)

MODELS_URL = "https://api.typesafe.ai/v1/models"
SYNTHETIC_STATE = {
    "synthetic_preflight_only": True,
    "node": "synthetic_straight_walk",
    "distance_remaining_m": 4.0,
    "route_frame_lateral_m": 0.01,
    "heading_error_rad": 0.0,
}
ModelsTransport = Callable[[str, float], tuple[int, bytes]]


def _models_transport(key: str, timeout_s: float) -> tuple[int, bytes]:
    request = urllib.request.Request(MODELS_URL, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def run_preflight(*, evidence_dir: Path, models_transport: ModelsTransport | None = None,
                  question_transport: client.Transport | None = None,
                  timeout_s: float = 30.0) -> dict:
    key = os.environ.get("JEV_API_KEY", "")
    if not key:
        raise RuntimeError("JEV_API_KEY is unavailable")
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence_dir / "preflight_receipt.json"
    call_path = evidence_dir / "synthetic_question.json"
    if receipt_path.exists() or call_path.exists():
        raise FileExistsError("preflight evidence already exists")
    started = time.monotonic()
    status = None
    raw = None
    failure = None
    model_available = False
    try:
        status, raw = (models_transport or _models_transport)(key, timeout_s)
        if status != 200:
            failure = f"HTTP_{status}"
        else:
            document = json.loads(raw)
            models = document.get("models")
            if not isinstance(models, list) or not all(isinstance(m, dict) and isinstance(m.get("name"), str) for m in models):
                raise ValueError("invalid models response")
            model_available = client.MODEL in {m["name"] for m in models}
            if not model_available:
                failure = "MODEL_UNAVAILABLE"
    except Exception as error:
        failure = type(error).__name__
    models_latency = time.monotonic() - started
    question = None
    if model_available:
        question = client.evaluate_once(state=SYNTHETIC_STATE, sample_id="synthetic_question",
                                        evidence_dir=evidence_dir, timeout_s=timeout_s,
                                        transport=question_transport)
        if not question["availability"]:
            failure = "QUESTION_" + str(question["failure"])
    receipt = {
        "purpose": "NON_SCORED_CONNECTION_PREFLIGHT",
        "model_requested": client.MODEL,
        "models_http_status": status,
        "models_raw_response_text": raw.decode("utf-8", errors="replace").replace(key, "[REDACTED]") if raw is not None else None,
        "models_latency_s": models_latency,
        "model_available": model_available,
        "typed_question_available": bool(question and question["availability"]),
        "typed_question_model": question["result"]["model"] if question and question["result"] else None,
        "typed_question_usage": question["result"]["usage"] if question and question["result"] else None,
        "typed_question_latency_s": question["latency_s"] if question else None,
        "failure": failure,
        "transport_attempts": 1 + (1 if question is not None else 0),
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=Path("artifacts/jev_risk_preflight"))
    args = parser.parse_args()
    result = run_preflight(evidence_dir=args.evidence_dir)
    print("PREFLIGHT_PASS" if result["model_available"] and result["typed_question_available"] else "PREFLIGHT_FAIL")
