"""The provider seam: a one-line swap behind ``Callable[[str, str], str]``.
Construction never hits the network; resolution honors the documented precedence;
the offline stub returns structurally valid, honest output for each shape."""

from __future__ import annotations

import json

import pytest

import providers
from gate import BrainError, lint_gate


def test_resolve_stub_flag_wins():
    m = providers.resolve_model("google", stub=True)
    assert isinstance(m, providers.StubModel)


def test_resolve_explicit_provider():
    assert isinstance(providers.resolve_model("anthropic"), providers.AnthropicModel)
    assert isinstance(providers.resolve_model("openai"), providers.OpenAIModel)
    assert isinstance(providers.resolve_model("google"), providers.GoogleModel)


def test_resolve_default_is_google(monkeypatch):
    monkeypatch.delenv("SHAULA_PROVIDER", raising=False)
    # no provider arg, no env, fresh temp config (no provider set) -> google
    assert isinstance(providers.resolve_model(None), providers.GoogleModel)


def test_resolve_env_override(monkeypatch):
    monkeypatch.setenv("SHAULA_PROVIDER", "openai")
    assert isinstance(providers.resolve_model(None), providers.OpenAIModel)


def test_unknown_provider_raises():
    with pytest.raises(BrainError) as exc:
        providers.resolve_model("llama-on-a-toaster")
    assert exc.value.category == "no_provider"


def test_construction_makes_no_network_call():
    # Constructing a cloud adapter with no key must not raise (key checked at call).
    g = providers.GoogleModel()
    a = providers.AnthropicModel()
    o = providers.OpenAIModel()
    assert g.name == "google" and a.name == "anthropic" and o.name == "openai"


def test_calling_a_keyless_adapter_raises_a_clean_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BrainError) as exc:
        providers.AnthropicModel()("system", "user")
    assert exc.value.category == "anthropic_auth"


def test_stub_workflow_shape_is_valid_json():
    out = providers.StubModel()("You are a workflow architect.", "draft something")
    data = json.loads(out)
    assert data["steps"], "workflow stub returns steps"
    assert data["steps"][-1]["assignee"] == "reviewer"
    assert data["steps"][-1]["requires_review"] is True


def test_stub_research_brief_is_honest():
    out = providers.StubModel()("you are blog", 'write a brief on "sleep"')
    # The stub's own output must survive the real gate (it claims nothing banned).
    assert lint_gate(out) == out
    assert "sleep" in out


def test_stub_skill_shape():
    out = providers.StubModel()("write a skill pack", "intake summary")
    data = json.loads(out)
    assert data["name"] and data["body"]
