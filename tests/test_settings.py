"""On-disk config, the PHI function registry, and dated BAA attestations.
The compliance model is locked: shaula RECORDS the user's attestation, never
asserts a vendor's terms, and never hard-blocks."""

from __future__ import annotations

import json
import os

import pytest

import settings


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHAULA_HOME", str(tmp_path))
    return tmp_path


def test_defaults_when_absent(home):
    cfg = settings.load()
    assert cfg["provider"] is None          # resolve_model falls back to google
    assert set(cfg["enabled_functions"]) == set(settings.CORE_FUNCTIONS)
    assert cfg["attestations"] == []


def test_phi_vs_core_partition():
    # email/messaging carry PHI; author/research/workflow do not.
    assert "email" in settings.PHI_FUNCTIONS and "messaging" in settings.PHI_FUNCTIONS
    assert {"author", "research", "workflow"} <= settings.CORE_FUNCTIONS
    assert settings.PHI_FUNCTIONS.isdisjoint(settings.CORE_FUNCTIONS)


def test_set_provider_round_trips(home):
    settings.set_provider("anthropic", "claude-sonnet-4-6")
    cfg = settings.load()
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-sonnet-4-6"


def test_enable_function_persists(home):
    settings.enable_function("email")
    assert "email" in settings.load()["enabled_functions"]


def test_record_attestation_is_dated_and_recorded(home):
    settings.record_attestation("email", "Google Workspace", baa=False, note="will sign later")
    rec = settings.attestation_for("email")
    assert rec is not None
    assert rec["vendor"] == "Google Workspace"
    assert rec["baa"] is False               # user's own attestation, recorded as-is
    assert rec["date"]                       # an ISO date stamp is always present
    # latest-wins
    settings.record_attestation("email", "Google Workspace", baa=True, on="2026-06-16")
    assert settings.attestation_for("email")["baa"] is True


def test_config_file_is_0600(home):
    settings.set_provider("openai")
    cfg = home / "config.json"
    assert cfg.exists()
    if os.name == "posix":                    # 0600 is a POSIX guarantee; on Windows
        assert (cfg.stat().st_mode & 0o777) == 0o600   # the per-user profile dir isolates it


def test_corrupt_config_falls_back_to_defaults(home):
    (home / "config.json").write_text("{ this is not json", encoding="utf-8")
    cfg = settings.load()                     # must not raise
    assert cfg["provider"] is None


def test_env_loading_does_not_override_existing(home, monkeypatch):
    settings.write_env_key("OPENAI_API_KEY", "from-file")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    settings.load_env()
    assert os.environ["OPENAI_API_KEY"] == "from-env"   # explicit export wins


def test_env_loading_populates_when_unset(home, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings.write_env_key("GEMINI_API_KEY", "from-file")
    settings.load_env()
    assert os.environ.get("GEMINI_API_KEY") == "from-file"
    if os.name == "posix":                    # 0600 is a POSIX guarantee; Windows
        assert ((home / ".env").stat().st_mode & 0o777) == 0o600   # uses the profile dir
