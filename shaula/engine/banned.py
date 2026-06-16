#!/usr/bin/env python3
r"""banned — the single source of truth for Shaula's banned-language gate.

Every honesty surface in the system refuses to publish the SAME set of marketing
claims (fabricated stats, efficacy claims, superlatives, testimonial language).
That list used to be defined or hand-copied in five places — engine/generate.py,
engine/geo.py, svc/honesty.py, scripts/honesty_scan.py, and the two proof scripts
(scripts/prove.sh, scripts/e2e_synthetic.sh) — which could silently DRIFT apart.
This module is the ONE definition they all derive from. tests/test_banned.py pins
that every consumer's effective banned set is this module's, so they cannot diverge.

TWO TIERS, because the gate runs against two different kinds of text:

  * VALUE tier (``BANNED_PATTERNS`` / ``lint`` / ``VALUE_REGEX``) — the FULL list,
    applied to TEXT VALUES: operator input (honesty_scan.py), every generated block
    (generate.py), and the GEO/SEO structured-data pass (geo.py). This is the
    primary gate; there is no CSS here to confuse the patterns.

  * RENDER tier (``RENDER_BANNED_PATTERNS`` / ``render_lint`` /
    ``render_banned_shell_regex``) — a deliberately CSS-safe SUBSET, applied to
    RENDERED OUTPUT (app.js / index.html / llms.txt) by the proof scripts. It omits
    patterns that false-positive on CSS-in-JS:
      - ``\b\d{1,3}\s?%``  would hit ``width:100%``
      - ``#1\b``           would hit hex colors like ``#1a2b3c``
    and also ``\bnumber one\b``, which carries no CSS risk but is ALREADY enforced
    on the very same rendered site by geo.py at the value level (geo runs before
    the render scan), so it belongs in the value tier, not this safety-net subset.

The VALUE tier is a strict superset of the historical per-file lists. The one
behavioral consolidation: ``\bnumber one\b`` was previously enforced ONLY by
geo.py's regex. Hoisting it here keeps geo's protection when geo derives from this
module, AND closes the same gap in generate.py / honesty_scan.py — it is the
spelled-out form of the already-banned ``#1``. Nothing is relaxed; one phrase is
now enforced in more places.

Pure stdlib, dependency-free leaf module — safe for any engine / svc / script to
import without a cycle. NO PHI: these are marketing-claim patterns only.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# VALUE tier — the full banned-language list, applied to text values.
# Order is preserved for stable, human-readable lint output and receipts.
# --------------------------------------------------------------------------- #
BANNED_PATTERNS: list[str] = [
    r"\b\d{1,3}\s?%",          # any percentage claim
    r"\bproven\b",
    r"\bguarantee",            # guarantee / guaranteed / guarantees
    r"studies show",
    r"research proves",
    r"clinically proven",
    r"\btestimonial",
    r"\bcure\b",
    r"\bcures\b",
    r"\bmiracle",
    r"#1\b",
    r"\bbest therapist",
    r"\bworld[- ]class\b",
    r"\bnumber one\b",         # spelled-out form of "#1" (hoisted from geo.py)
]

# --------------------------------------------------------------------------- #
# RENDER tier — CSS-safe subset for scanning rendered output. See module docstring
# for why each excluded pattern is excluded. Derived (not re-listed) so it cannot
# drift from the value tier.
# --------------------------------------------------------------------------- #
_RENDER_EXCLUDED: frozenset[str] = frozenset({
    r"\b\d{1,3}\s?%",   # CSS false-positive: width:100%
    r"#1\b",            # CSS false-positive: #1a2b3c hex colors
    r"\bnumber one\b",  # already enforced at the value level by geo on the same site
})
RENDER_BANNED_PATTERNS: list[str] = [p for p in BANNED_PATTERNS if p not in _RENDER_EXCLUDED]

# Singleton compiled value-tier regex. geo.py consumes this for .search()/.findall();
# compiling once keeps the GEO pass cheap and guarantees it uses the canonical set.
VALUE_REGEX = re.compile("|".join(BANNED_PATTERNS), re.IGNORECASE)


def lint(text: str) -> list[str]:
    """Return the VALUE-tier banned patterns found in ``text`` (empty == clean).

    This is THE box-wide honesty linter: generate.py re-exports it as
    ``generate.lint`` and every caller (build_practice, staff, gemini, brain,
    honesty_scan, validate_survey, the workflow builder) routes through it.
    """
    return [p for p in BANNED_PATTERNS if re.search(p, text, re.I)]


def render_lint(text: str) -> list[str]:
    """Return the RENDER-tier (CSS-safe subset) banned patterns found in ``text``."""
    return [p for p in RENDER_BANNED_PATTERNS if re.search(p, text, re.I)]


def render_banned_shell_regex() -> str:
    """The RENDER-tier patterns as a single ``grep -E`` alternation.

    scripts/prove.sh and scripts/e2e_synthetic.sh scan rendered output with
    ``grep -riE`` using EXACTLY this string (derived at run time via
    ``python3 -c '... print(banned.render_banned_shell_regex())'``), so the shell
    gate and the Python gate cannot disagree. BSD and GNU ``grep -E`` both honor
    ``\b`` word boundaries, matching Python's semantics for these patterns.
    """
    return "|".join(RENDER_BANNED_PATTERNS)


if __name__ == "__main__":  # tiny self-check / introspection aid
    import json

    print(json.dumps({
        "value_tier": BANNED_PATTERNS,
        "render_tier": RENDER_BANNED_PATTERNS,
        "render_excluded": sorted(_RENDER_EXCLUDED),
        "render_shell_regex": render_banned_shell_regex(),
    }, indent=2))
