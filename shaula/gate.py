"""gate — the honesty gate (``BrainError`` + ``lint_gate``), transport-free.

THE MOAT, unchanged: every model output that becomes a deliverable is run
through the SAME banned-language linter that guards the engine
(``engine/generate.py:lint`` == ``engine/banned.py:lint``). A banned claim is
NEVER auto-repaired — the call raises ``BrainError('honesty')`` and the run
parks for a human, exactly as in production.

This module is the gate ONLY. No model or network code lives here — that is
``providers.py``. It is just ``BrainError`` + ``lint_gate`` with no transport, so
the gate runs with zero cloud dependency and the SAME gate object is shared by
every provider and every test fake. Keeping the gate decoupled from the transport
is the point: a banned
claim is refused the same way whether it came from Google, Anthropic, OpenAI,
or a local stub.

No PHI by construction: the text it inspects is business/marketing/research
copy. The offending text is never logged — only the violation count is.

Stdlib + the engine linter only.
"""

from __future__ import annotations

import logging

from engine.generate import lint  # the single source of honesty truth (== banned.lint)
import honesty  # plain-words narration of a refusal (no second linter)

log = logging.getLogger("shaula.gate")


class BrainError(RuntimeError):
    """Category-coded model/gate failure.

    ``category`` is either a transport category raised by a provider adapter
    (e.g. ``'google_auth'``, ``'google_http'``, ``'anthropic_http'``,
    ``'openai_http'``, ``'empty'``, ``'malformed'``, ``'no_provider'``) or
    ``'honesty'`` for a banned-language refusal.

    On an honesty refusal, ``.explanations`` carries the plain-words narration
    of which rule tripped and the offending sentence (for the run record / UI);
    the engine never logs that text itself.
    """

    def __init__(self, category: str, detail: str = "") -> None:
        super().__init__(category)
        self.category = category
        self.detail = detail
        self.explanations: list[dict] = []


def lint_gate(text: str) -> str:
    """The hard stop, narrated.

    Raises ``BrainError('honesty')`` when ``text`` trips the engine linter;
    otherwise returns the text unchanged. Factored out of any model call so that
    test fakes and every provider run the REAL gate identically — never an
    imitation of it.
    """
    violations = lint(text)
    if violations:
        log.info("honesty_lint_tripped count=%d", len(violations))
        err = BrainError("honesty", "; ".join(violations[:3]))
        err.explanations = honesty.explain(text, violations)
        raise err
    return text
