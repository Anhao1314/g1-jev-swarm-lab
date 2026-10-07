"""Inspect the non-secret GLM profile without reading credentials or calling API.

This is a readiness inspector, not a live provider preflight or scored harness.
An unverified billing route always exits blocked. Changing a profile flag alone
is not a substitute for account/package evidence and a real live preflight.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "experiments/provider_glm_preflight_001/provider_profile.json"
STATUS = ROOT / "experiments/provider_glm_preflight_001/preflight_status.json"


def inspect() -> dict:
    profile = json.loads(PROFILE.read_bytes())
    status = json.loads(STATUS.read_bytes())
    # Whitelist public fields; never serialize arbitrary profile or env values.
    return {
        "provider_id": profile["provider_id"],
        "model_id": profile["model_id"],
        "protocol": profile["endpoint"]["protocol"],
        "configuration_verdict": profile["configuration_verdict"],
        "credential_bound": status["credential_bound"],
        "billing_verified": profile["billing_gate"]["verified"],
        "preflight_status": status["status"],
        "provider_calls": status["provider_calls"],
        "ready_for_cross_model_pilot": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["glm-5.3-flash"])
    parser.parse_args()
    print(json.dumps(inspect(), ensure_ascii=True, sort_keys=True))
    return 3  # This receipt has no live capability or billing-route verification.


if __name__ == "__main__":
    raise SystemExit(main())
