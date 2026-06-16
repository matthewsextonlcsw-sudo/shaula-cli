"""Shaula engine — deterministic, honesty-gated content & workflow primitives.

The deterministic floor: every template block resolves to honest, per-practice
content with no network and no model key; the honesty linter guards every byte.

The modules in this package import one another with bare top-level names
(``import banned``, ``import citations``) and self-bootstrap ``engine/`` onto
``sys.path`` (see ``generate.py``), so they resolve whether imported as
``engine.<mod>`` (e.g. ``from engine.generate import lint``) or bare ``<mod>``.
The parent package's path setup (``shaula/__init__.py``) keeps both forms
pointing at one module identity.

Pure stdlib at import time — importing the engine pulls in no third-party
dependency. The optional model-enrichment seam (``generate(brain=…)``) is
caller-supplied; the bundled deterministic floor needs no network and no key.
"""
