"""Credential identity checks use only isolated, invented configuration."""
import json
import os
from pathlib import Path

import pytest

from scripts import with_phase23_pilot_provider as resolver


def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = 'model = "deepseek-flash"\nmodel_provider = "custom"\n[model_providers.custom]\nbase_url = "http://127.0.0.1:57321/v1"\nwire_api = "responses"\n'
    auth = json.dumps({"OPENAI_API_KEY": "invented-offline-credential"})
    profile = {"id": resolver.PROFILE, "configContents": config, "authContents": auth,
               "upstreamBaseUrl": "https://api.deepseek.com", "protocol": "chatCompletions", "relayMode": "pureApi"}
    store = tmp_path / ".codex-session-delete"
    store.mkdir()
    settings = store / "settings.json"
    settings.write_text(json.dumps({"activeRelayId": resolver.PROFILE, "relayProfiles": [profile]}))
    backup = tmp_path / ".codex/backups" / resolver.BACKUP
    backup.mkdir(parents=True)
    (backup / "config.toml").write_text(config)
    (backup / "auth.json").write_text(auth)
    monkeypatch.delenv("LLM_COMPILER_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_COMPILER_API_KEY", raising=False)
    return settings, backup


def test_matching_provider_is_resolved_only_in_environment(tmp_path, monkeypatch, capsys):
    settings, backup = fake_home(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in [settings, backup / "config.toml", backup / "auth.json"]}
    resolver.resolve_existing_provider()
    assert os.environ["LLM_COMPILER_BASE_URL"] == resolver.ENDPOINT
    assert os.environ["LLM_COMPILER_API_KEY"] == "invented-offline-credential"
    assert all(path.read_bytes() == data for path, data in before.items())
    assert capsys.readouterr().out == ""


def test_different_active_provider_does_not_resolve_credentials(tmp_path, monkeypatch):
    settings, _ = fake_home(tmp_path, monkeypatch)
    value = json.loads(settings.read_text())
    value["activeRelayId"] = "other-provider"
    settings.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="drifted"):
        resolver.resolve_existing_provider()
    assert "LLM_COMPILER_API_KEY" not in os.environ


def test_conflicting_historical_credentials_are_fail_closed(tmp_path, monkeypatch):
    _, backup = fake_home(tmp_path, monkeypatch)
    (backup / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "different-invented-credential"}))
    with pytest.raises(ValueError, match="consistently"):
        resolver.resolve_existing_provider()
    assert "LLM_COMPILER_API_KEY" not in os.environ
