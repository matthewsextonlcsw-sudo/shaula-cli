"""The honesty gate — the moat. It must pass clean copy and HARD-stop banned
claims with a structured, narratable error (never auto-repair)."""

from __future__ import annotations

import pytest

from gate import BrainError, lint_gate


def test_clean_text_passes_through_unchanged():
    clean = "We offer compassionate, evidence-informed therapy for adults and couples."
    assert lint_gate(clean) == clean


@pytest.mark.parametrize(
    "banned",
    [
        "Our therapy is clinically proven to cure anxiety.",
        "Studies show a 95% success rate with our approach.",
        "We are the #1 best therapist in the city — guaranteed results.",
        "This treatment is a proven miracle cure.",
    ],
)
def test_banned_claims_are_blocked(banned):
    with pytest.raises(BrainError) as exc:
        lint_gate(banned)
    assert exc.value.category == "honesty"


def test_blocked_error_carries_detail_and_explanations():
    with pytest.raises(BrainError) as exc:
        lint_gate("Our therapy is clinically proven to cure anxiety — studies show 95% success.")
    err = exc.value
    assert err.category == "honesty"
    assert err.detail, "the detail string names the tripped rule(s)"
    # explanations are the Reviewer's plain-words narration with the quoted sentence
    assert isinstance(err.explanations, list) and err.explanations
    first = err.explanations[0]
    assert {"pattern", "plain", "quote"} <= set(first)
    assert first["plain"]


def test_gate_is_a_hard_stop_not_a_rewrite():
    # The gate never returns a "cleaned" string for banned input — it raises.
    with pytest.raises(BrainError):
        lint_gate("guaranteed cure")
