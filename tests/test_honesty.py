"""The Reviewer's narration layer. It explains a refusal in plain words with the
offending sentence quoted — and it must never echo the banned vocabulary in the
step-output-safe summary, nor drift out of sync with the engine's banned list."""

from __future__ import annotations

import honesty
from gate import lint_gate, BrainError


def test_no_unknown_patterns_drift_guard():
    # Every canonical banned pattern has a human-readable translation. If someone
    # adds a rule to engine/banned.py without a plain-words entry, this trips.
    assert honesty.unknown_patterns() == []


def test_explain_quotes_the_offending_sentence():
    text = "Intro sentence. Our work is clinically proven to cure anxiety. Outro."
    try:
        lint_gate(text)
        raise AssertionError("expected the gate to fire")
    except BrainError as exc:
        reasons = exc.explanations
    assert reasons
    joined = " ".join(r["quote"] for r in reasons)
    assert "clinically proven to cure anxiety" in joined
    assert all(r["plain"] for r in reasons)


def test_refusal_message_does_not_echo_banned_vocabulary():
    msg = honesty.refusal_message(2).lower()
    for word in ("clinically proven", "guarantee", "cure", "miracle", "studies show", "#1"):
        assert word not in msg


def test_revise_note_lists_the_claims_to_remove():
    reasons = honesty.explain(
        "We guarantee a cure.", honesty.banned.lint("We guarantee a cure.")
    )
    note = honesty.revise_note(reasons)
    assert "Rewrite" in note
    assert "Do not repeat" in note
