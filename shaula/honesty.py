"""honesty — the Reviewer's voice (UX audit SH-F12).

The engine linter (engine/generate.py:lint) is the single source of honesty
truth and a HARD stop — this module never weakens it, never auto-repairs a
claim, and never adds a second linter. What it adds is narration: when the
gate fires, the therapist should read "your Reviewer refused a guarantee-style
claim — here is the sentence" instead of a raw regex fragment.

Three audiences, three strictness levels:

  * ``explain``        → the run's ``honesty.reasons`` record: which rule, in
                         plain words, with the offending sentence QUOTED. The
                         quote lives in run STATE (like every step output —
                         marketing copy, no PHI); it is never logged.
  * ``refusal_message``→ step-output-safe summary. Step outputs are pinned by
                         contract to never contain banned text, so this string
                         must not echo the claim OR the banned vocabulary.
  * ``revise_note``    → the one-click "rewrite without this claim" note that
                         feeds the revision loop (SH-F3) when the clinician
                         asks for changes without typing one.

NO PHI. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# engine/ is a sibling of this module inside the shaula package; put it on the
# path so this narration layer can import the ONE banned-language definition
# (engine/banned.py) and pin _PLAIN against it (see unknown_patterns() below).
_ENGINE = Path(__file__).resolve().parent / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))
import banned  # noqa: E402  — single source of truth for the banned-language gate

# Plain-words translations, keyed by the EXACT pattern strings the engine
# linter returns (engine/banned.py:BANNED_PATTERNS, re-exported as
# generate._BANNED). Unknown patterns fall back to a generic-but-honest line,
# so an engine-side addition never crashes here — and unknown_patterns() lets
# the proof gate assert this map covers the canonical list with no gaps.
_PLAIN: dict[str, str] = {
    r"\b\d{1,3}\s?%": "a percentage statistic — we never publish numbers we cannot source",
    r"\bproven\b": "language calling the work 'proven' — an efficacy claim",
    r"\bguarantee": "a guarantee — therapy outcomes cannot be guaranteed",
    "studies show": "an unsourced 'studies show' appeal",
    "research proves": "an unsourced 'research proves' appeal",
    "clinically proven": "a 'clinically proven' efficacy claim",
    r"\btestimonial": "testimonial language — client voices are never marketing material",
    r"\bcure\b": "a 'cure' promise",
    r"\bcures\b": "a 'cure' promise",
    r"\bmiracle": "'miracle' language",
    r"#1\b": "a '#1' superlative",
    r"\bbest therapist": "a 'best therapist' superlative",
    r"\bworld[- ]class\b": "a 'world-class' superlative",
    r"\bnumber one\b": "a 'number one' superlative",
}

_QUOTE_MAX = 240
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _plain(pattern: str) -> str:
    return _PLAIN.get(pattern, f"a claim style we never publish (rule: {pattern})")


def unknown_patterns() -> list[str]:
    """Canonical banned patterns that have no plain-words entry (drift guard).

    Must stay empty: tests/test_banned.py asserts it, so adding a pattern to
    engine/banned.py without a human-readable translation here trips the proof
    gate instead of silently degrading the Reviewer's narration to the generic
    fallback in _plain().
    """
    return [p for p in banned.BANNED_PATTERNS if p not in _PLAIN]


def _offending_sentence(text: str, pattern: str) -> str:
    """The first sentence of ``text`` that trips ``pattern`` (clipped)."""
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        return ""
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        sentence = sentence.strip()
        if sentence and rx.search(sentence):
            return sentence[:_QUOTE_MAX]
    return ""


def explain(text: str, violations: list[str]) -> list[dict]:
    """lint() hits → [{pattern, plain, quote}] for the run's honesty record."""
    reasons = []
    for pattern in violations[:5]:
        reasons.append(
            {
                "pattern": pattern,
                "plain": _plain(pattern),
                "quote": _offending_sentence(text, pattern),
            }
        )
    return reasons


def refusal_message(count: int) -> str:
    """Step-output-safe narration (must not echo banned vocabulary)."""
    noun = "a claim" if count <= 1 else f"{count} claims"
    return (
        f"Your Reviewer stopped this draft before anything shipped: it "
        f"contained {noun} Shaula never publishes. This is the honesty gate "
        "working, not a crash. Open this run's reviewer note to see exactly "
        "which sentence tripped it, then choose Request changes — the staff "
        "will rewrite without it."
    )


def revise_note(reasons: list[dict]) -> str:
    """The auto-filled revision note for one-click 'rewrite without this
    claim'. Quotes ride into the new run's context so the staff knows exactly
    what to remove — and are told not to repeat it."""
    if not reasons:
        return ""
    lines = ["The previous draft was refused by the honesty review. Rewrite it without these claims:"]
    for i, r in enumerate(reasons, 1):
        quote = (r.get("quote") or "").strip()
        plain = r.get("plain") or "a banned claim style"
        lines.append(f'{i}) "{quote}" — {plain}.' if quote else f"{i}) {plain}.")
    lines.append(
        "Do not repeat, quote, or reference the refused phrases anywhere in "
        "the new deliverable. Keep everything else that worked."
    )
    return "\n".join(lines)
