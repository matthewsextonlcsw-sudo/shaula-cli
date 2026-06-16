"""Shared test bootstrap.

Importing ``shaula`` runs the one-time path bootstrap (it puts the package dir
and the seeded ``engine/`` dir on ``sys.path``) so the legacy top-level imports
the engine relies on — ``import banned``, ``from engine.generate import lint``,
``import gate`` / ``providers`` / ``settings`` — resolve in tests exactly as they
do under the installed console script. Tests therefore import those modules by
their top-level names, never via fragile relative paths.

Every test also runs against a throwaway ``SHAULA_HOME`` so the suite can never
read or write the real ``~/.shaula``.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import shaula  # noqa: E402,F401 — triggers the path bootstrap before any engine import


@pytest.fixture(autouse=True, scope="session")
def _safe_home(tmp_path_factory):
    """Point SHAULA_HOME at a temp dir for the whole run so nothing touches the
    user's real config. Individual tests can still override per-test."""
    home = tmp_path_factory.mktemp("shaula_home")
    os.environ["SHAULA_HOME"] = str(home)
    yield
