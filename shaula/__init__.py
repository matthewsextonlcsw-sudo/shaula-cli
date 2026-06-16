"""shaula — a downloadable, honesty-gated research & workflow agent.

Importing this package wires the in-package code trees onto ``sys.path`` so the
``engine/`` and ``workflows/`` modules — which import each other with bare
top-level names (``import banned``, ``from engine.generate import lint``) —
resolve identically whether shaula is run from a source checkout, installed via
``pip``/``uv``, or launched by the clone-bootstrap installer.

This is the ONE place that path setup happens. Every other module (``gate``,
``providers``, ``cli`` …) relies on it, so any entrypoint that touches shaula
imports this package first (``shaula.cli`` / ``python -m shaula`` both do).

Engine lineage: the ``engine/`` + ``workflows/`` trees were seeded from the
honesty/research engine and evolve independently here (engine-source A). The
honesty gate (``gate.py``) is the moat and is never weakened.
"""

from __future__ import annotations

import os
import sys

__version__ = "0.1.0"
__all__ = ["__version__"]

# The package directory holds engine/, workflows/, honesty.py, gate.py, etc.
# Putting it (and engine/) on sys.path lets the legacy top-level import style
# resolve to a single module identity, no matter how shaula was launched.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.join(_PKG_DIR, "engine")
for _p in (_ENGINE_DIR, _PKG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
