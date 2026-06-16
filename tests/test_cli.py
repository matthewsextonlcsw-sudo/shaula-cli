"""The CLI surface: happy-path exit codes, and the honesty refusal exit (3) that
proves the moat narrates at the process boundary rather than crashing."""

from __future__ import annotations

import pytest

from shaula.cli import main


def test_version(capsys):
    assert main(["version"]) == 0
    assert "shaula" in capsys.readouterr().out


def test_version_flag(capsys):
    assert main(["--version"]) == 0


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_doctor_self_test_passes(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "honesty gate" in out


def test_author_stub(capsys):
    assert main(["author", "draft a weekly blog workflow", "--stub"]) == 0
    out = capsys.readouterr().out
    assert "reviewer" in out and "review gate" in out


def test_research_stub(capsys):
    assert main(["research", "sleep hygiene basics", "--stub"]) == 0
    assert "background brief" in capsys.readouterr().out.lower()


def test_providers_listing(capsys):
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    for pid in ("google", "anthropic", "openai", "stub"):
        assert pid in out


def test_honesty_refusal_exits_3(monkeypatch, capsys):
    # Force the resolved model to emit a banned claim; the CLI must narrate the
    # refusal and exit 3 (the moat), not raise.
    monkeypatch.setattr(
        "providers.resolve_model",
        lambda *a, **k: (lambda system, user: "We guarantee a clinically proven cure."),
    )
    code = main(["research", "anything", "--provider", "stub"])
    assert code == 3
    err = capsys.readouterr().err.lower()
    assert "honesty gate" in err
