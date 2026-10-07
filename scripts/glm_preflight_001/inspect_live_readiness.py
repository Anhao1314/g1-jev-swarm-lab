"""Read the latest non-secret live receipt; never read a key or call a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "experiments/provider_glm_preflight_001"
INDEX = FOLDER / "current_live_receipt.json"


def inspect() -> dict:
    public = {"provider_id": "glm-5.3-flash", "ready_for_cross_model_pilot": False,
              "scored_pilot_started": False, "credential_read": False, "provider_calls_by_inspector": 0}
    try:
        index = json.loads(INDEX.read_bytes())
        relative = index["receipt_path"]
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError()
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(FOLDER.resolve()) or target.is_symlink():
            raise ValueError()
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != index["receipt_sha256"]:
            raise ValueError()
        receipt = json.loads(raw)
        names = ("ordinary_text", "json_object", "typed_certificate")
        checks = receipt["checks"]
        technical = (receipt["provider_id"] == "glm-5.3-flash" and receipt["ready"] is True
            and receipt["status"] == "READY" and receipt["non_scored"] is True
            and receipt.get("reasoning_observation") == "OBSERVED"
            and receipt["scored_calls"] == receipt["runtime_calls"] == receipt["held_out_calls"] == 0
            and len(checks) == 3 and tuple(c["name"] for c in checks) == names
            and all(c["passed"] is True and c["status"] == "PASS" for c in checks))
        public["ready_for_cross_model_pilot"] = technical
        public["status"] = "READY" if technical else "NOT_READY"
        public["receipt_path"] = relative
        public["billing_deduction"] = "NOT_INDEPENDENTLY_VERIFIED_NOT_A_SCIENTIFIC_GATE"
    except (OSError, ValueError, TypeError, KeyError):
        public["status"] = "NOT_READY_NO_VALID_LIVE_RECEIPT"
    return public


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["glm-5.3-flash"])
    parser.parse_args()
    result = inspect()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready_for_cross_model_pilot"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
