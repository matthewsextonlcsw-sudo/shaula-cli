"""settings — shaula's on-disk config, BYO-key handling, and BAA attestations.

Everything shaula remembers between runs lives under ``~/.shaula`` (override with
``SHAULA_HOME``):

  * ``config.json`` — chosen provider/model, which functions the user enabled,
    and the dated BAA attestations they recorded. Non-secret; 0600 anyway.
  * ``.env`` — optional ``KEY=value`` lines for provider API keys, loaded into the
    process environment at startup if the vars are not already set. 0600.

Compliance model (locked): shaula RECOMMENDS a BAA, DISCLOSES PHI exposure, and
lets the user choose — it never hard-blocks, and it never asserts anything about
a vendor's terms. A BAA is an explicit user ATTESTATION, recorded with a date.
The no-PHI-by-construction engine wall stays underneath as belt-and-suspenders.

Stdlib only. No secret is ever printed or logged by this module.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

CONFIG_VERSION = 1


def home() -> Path:
    """The shaula config directory (``~/.shaula`` or ``$SHAULA_HOME``)."""
    return Path(os.environ.get("SHAULA_HOME", str(Path.home() / ".shaula")))


def _config_path() -> Path:
    return home() / "config.json"


def _env_path() -> Path:
    return home() / ".env"


# --------------------------------------------------------------------------- #
# Function registry — every capability tagged by PHI exposure (the disclosure
# the setup wizard reads from). no-PHI core vs PHI-capable connectors.
# --------------------------------------------------------------------------- #
FUNCTIONS: list[dict[str, Any]] = [
    {"name": "author", "phi": False,
     "desc": "Draft honest office workflows from a plain-language request (no PHI)."},
    {"name": "research", "phi": False,
     "desc": "Draft honest, sourced background briefs on business topics (no PHI)."},
    {"name": "workflow", "phi": False,
     "desc": "Generate and validate vetted workflow task-graphs (no PHI)."},
    {"name": "email", "phi": True,
     "desc": "Draft, send, or triage email — can carry client PHI."},
    {"name": "messaging", "phi": True,
     "desc": "Draft, send, or triage messages — can carry client PHI."},
]

PHI_FUNCTIONS = frozenset(f["name"] for f in FUNCTIONS if f["phi"])
CORE_FUNCTIONS = frozenset(f["name"] for f in FUNCTIONS if not f["phi"])


def _default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "provider": None,        # set by setup; resolve_model falls back to "google"
        "model": None,           # None → provider default
        "enabled_functions": sorted(CORE_FUNCTIONS),  # PHI functions opt-in only
        "attestations": [],      # list of attestation records (see record_attestation)
    }


# --------------------------------------------------------------------------- #
# Load / save
# --------------------------------------------------------------------------- #
def load() -> dict[str, Any]:
    """Read ``config.json`` (returning defaults if absent), tolerant of an older
    or partial file — missing keys are filled from the defaults."""
    cfg = _default_config()
    path = _config_path()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                cfg.update({k: v for k, v in stored.items() if v is not None or k in stored})
        except (OSError, json.JSONDecodeError):
            pass  # a corrupt config never crashes the agent — fall back to defaults
    return cfg


def save(cfg: dict[str, Any]) -> Path:
    """Write ``config.json`` under the config dir. Perms are 0600/0700 on POSIX;
    on Windows ``chmod`` is best-effort and the per-user profile dir isolates it.
    Returns the path."""
    d = home()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    path = _config_path()
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


# --------------------------------------------------------------------------- #
# Convenience mutators
# --------------------------------------------------------------------------- #
def set_provider(provider: str, model: Optional[str] = None) -> dict[str, Any]:
    cfg = load()
    cfg["provider"] = provider
    cfg["model"] = model
    save(cfg)
    return cfg


def enable_function(name: str) -> dict[str, Any]:
    cfg = load()
    enabled = set(cfg.get("enabled_functions", []))
    enabled.add(name)
    cfg["enabled_functions"] = sorted(enabled)
    save(cfg)
    return cfg


def record_attestation(
    function: str,
    vendor: str,
    *,
    baa: bool,
    note: str = "",
    on: Optional[str] = None,
) -> dict[str, Any]:
    """Append a dated BAA acknowledgment record.

    ``baa`` is the user's own attestation that a BAA is (or is not) in place with
    ``vendor`` for ``function`` — never an assertion shaula makes. The record
    captures that the user was warned and chose to proceed.
    """
    cfg = load()
    cfg.setdefault("attestations", []).append({
        "function": function,
        "vendor": vendor,
        "baa": bool(baa),
        "note": note,
        "date": on or date.today().isoformat(),
    })
    save(cfg)
    return cfg


def attestation_for(function: str) -> Optional[dict[str, Any]]:
    """The most recent attestation recorded for ``function`` (or None)."""
    records = [a for a in load().get("attestations", []) if a.get("function") == function]
    return records[-1] if records else None


# --------------------------------------------------------------------------- #
# .env loading — populate provider keys without putting secrets in config.json
# --------------------------------------------------------------------------- #
def load_env() -> None:
    """Load ``~/.shaula/.env`` into ``os.environ`` for any var not already set.

    Lines are ``KEY=value``; ``#`` comments and blanks are ignored. Existing
    environment variables win, so an explicit export always overrides the file.
    """
    path = _env_path()
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def write_env_key(key: str, value: str) -> Path:
    """Store one ``KEY=value`` in ``~/.shaula/.env`` (0600), replacing any prior
    line for the same key. The value is never echoed back to the caller."""
    d = home()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _env_path()
    lines: list[str] = []
    if path.exists():
        lines = [
            ln for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.strip().startswith(f"{key}=")
        ]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
