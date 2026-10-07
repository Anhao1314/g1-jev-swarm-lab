"""Resolve the existing Pilot relay credentials only in this child process.

No credentials, auth-store contents, or secret fingerprints are emitted. The
scientific provider settings are supplied by the frozen protocol and harness.
This entry point never switches, edits, or replaces a provider configuration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tomllib

PROFILE = "relay-muwf8k5x"
ENDPOINT = "http://127.0.0.1:57321/v1"
BACKUP = "codex-plus-live-1791349446253"


def resolve_existing_provider() -> None:
    home = Path.home()
    settings = json.loads((home / ".codex-session-delete/settings.json").read_text(encoding="utf-8"))
    profile = next(row for row in settings["relayProfiles"] if row["id"] == PROFILE)
    config = tomllib.loads(profile["configContents"])
    historical = tomllib.loads((home / ".codex/backups" / BACKUP / "config.toml").read_text(encoding="utf-8"))
    for document in (config, historical):
        if (document.get("model") != "deepseek-flash"
                or document.get("model_provider") != "custom"
                or document["model_providers"]["custom"].get("base_url") != ENDPOINT
                or document["model_providers"]["custom"].get("wire_api") != "responses"):
            raise ValueError("Pilot provider identity cannot be established")
    if (settings.get("activeRelayId") != PROFILE
            or profile.get("upstreamBaseUrl") != "https://api.deepseek.com"
            or profile.get("protocol") != "chatCompletions"
            or profile.get("relayMode") != "pureApi"):
        raise ValueError("existing Pilot relay route is not active or has drifted")
    key = json.loads(profile["authContents"]).get("OPENAI_API_KEY")
    prior_key = json.loads((home / ".codex/backups" / BACKUP / "auth.json").read_text(encoding="utf-8")).get("OPENAI_API_KEY")
    if not key or key != prior_key:
        raise ValueError("existing Pilot credentials cannot be resolved consistently")
    if os.environ.get("LLM_COMPILER_BASE_URL", ENDPOINT) != ENDPOINT:
        raise ValueError("existing experiment endpoint differs from Pilot")
    if os.environ.get("LLM_COMPILER_API_KEY", key) != key:
        raise ValueError("existing experiment credentials conflict with Pilot")
    os.environ["LLM_COMPILER_BASE_URL"] = ENDPOINT
    os.environ["LLM_COMPILER_API_KEY"] = key


def main() -> int:
    try:
        resolve_existing_provider()
    except Exception as exc:
        # Only the exception type is printed; never stringify credential errors.
        print(f"BLOCKED_PROVIDER_PROVENANCE: {type(exc).__name__}")
        return 2
    try:
        from scripts.run_phase23_session4 import main as collect
    except ModuleNotFoundError:
        from run_phase23_session4 import main as collect
    return collect(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
