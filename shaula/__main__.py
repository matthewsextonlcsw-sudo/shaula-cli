"""``python -m shaula`` → the shaula CLI.

Importing this module triggers ``shaula/__init__.py`` (the path bootstrap)
before the CLI's own top-level imports run.
"""

from __future__ import annotations

from shaula.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
