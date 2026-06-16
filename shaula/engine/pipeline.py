#!/usr/bin/env python3
"""pipeline — in-process survey → finished website, one call.

This is the orchestration seam behind a single survey→site build call.
It chains the three proven, independently-tested engine stages with NO network,
NO LLM, and NO subprocess shell-out:

    survey (dict)
      → build_practice.build_practice()   # ~17 answers → 53 honest tokens
      → generate.generate()               # 37 blocks (11 resolved, honesty-linted)
      → fill.run()                        # copy template, fill, verify (0 leaks)
      → sites/<slug>/                      # a finished, hostable static site

Why a module (not just inline in office.py): the survey→site logic is pure and
deterministic, so it is unit-testable and reusable (prove.sh, future n8n node,
batch runs) without standing up an HTTP server. office.py stays a thin HTTP shell
over `build_site()`.

Honesty + safety by construction:
  * build_practice lints every produced value (HonestyError on a banned claim).
  * generate re-lints every emitted block (SystemExit(2) on a violation).
  * fill verifies zero {{token}} leaks / zero AI-GENERATE markers (FillError).
  Any stage failure raises — `build_site` never returns a half-built site.

The intermediate practice.json + generated.json are written to a TEMP dir, never
into the served site directory: generated.json legitimately contains the template's
`AI-GENERATE` marker text inside its `find` fields, and fill.py's verifier scans
*.json in its output tree for exactly that marker — so persisting it alongside the
site would trip the honesty verifier. Ephemeral by design.

Pure stdlib. Python 3.8+.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile

# Engine siblings (this file lives in engine/).
_ENGINE = pathlib.Path(__file__).resolve().parent
_REPO = _ENGINE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import build_practice as BP  # noqa: E402
import generate as G  # noqa: E402
import fill as F  # noqa: E402
import geo as GEO  # noqa: E402

# Re-export so callers can `except pipeline.HonestyError` without importing BP.
HonestyError = BP.HonestyError

# Repo-default locations (overridable per call for tests / alternate layouts).
DEFAULT_SITES_DIR = _REPO / "sites"
DEFAULT_TEMPLATE_DIR = _REPO / "templates" / "private-practice"
DEFAULT_BLOCKS_PATH = _ENGINE / "template_blocks.json"

# A slug must be filesystem- and URL-safe: lowercase alnum + single hyphens,
# 1..64 chars, no leading/trailing hyphen. This is also the regex office.py
# enforces on the /site/<slug>/ route, so the two can never disagree.
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class PipelineError(RuntimeError):
    """Any failure turning a survey into a finished site."""


def slugify(business_name: str) -> str:
    """Derive a safe slug from a business name; never returns an empty/invalid slug."""
    base = G._slug(business_name or "")  # reuse the engine's slugger (single source)
    base = base.strip("-")[:64].strip("-")
    if not base or not SLUG_RE.match(base):
        base = "practice"
    return base


def build_site(
    survey: dict,
    *,
    sites_dir: pathlib.Path | str = DEFAULT_SITES_DIR,
    template_dir: pathlib.Path | str = DEFAULT_TEMPLATE_DIR,
    blocks_path: pathlib.Path | str = DEFAULT_BLOCKS_PATH,
    slug: str | None = None,
    brain=None,
    inquiry_origin: str = "",
    site_url: str = "",
) -> dict:
    """Turn a survey dict into a finished site under ``sites_dir/<slug>/``.

    Returns ``{slug, dir, owner_name, business_name, practice}``.

    ``site_url`` is the eventual public URL when the caller knows it (used for
    the canonical ``url`` in the injected JSON-LD); empty simply omits it —
    the GEO pass (JSON-LD + OG meta + llms.txt) ships either way (SH-F6).

    ``brain`` is an OPTIONAL, caller-supplied enrichment seam. Left None (the
    default) this is the verified deterministic pipeline, byte for byte. When
    supplied, prose-only blocks are model-enriched behind the same honesty rails;
    any brain failure transparently falls back to the floor.

    ``inquiry_origin`` is the full URL the built site's contact form POSTs to
    (your own form endpoint). When supplied, the site's form delivers for real;
    when empty, the template renders an honest direct-contact card (email/phone)
    instead of a form — a submission can never silently evaporate.

    Raises:
      * ``HonestyError`` — survey input contained a banned marketing claim.
      * ``ValueError``   — a required survey field is missing.
      * ``PipelineError``— generation or fill failed (wraps SystemExit / FillError).
    """
    sites_dir = pathlib.Path(sites_dir)
    template_dir = pathlib.Path(template_dir)
    blocks_path = pathlib.Path(blocks_path)

    # 1) survey → full token dict (raises HonestyError / ValueError).
    practice = BP.build_practice(survey)

    # 2) pick + validate the slug.
    slug = slug or slugify(practice.get("business_name", ""))
    if not SLUG_RE.match(slug):
        raise ValueError(f"unsafe slug: {slug!r}")

    # 2b) wire the contact form's delivery endpoint now that the slug is known.
    #     (build_practice emitted the "" placeholder; empty keeps the template's
    #     honest direct-contact fallback — never a form that drops submissions.)
    if inquiry_origin:
        practice["inquiry_endpoint"] = inquiry_origin.rstrip("/")

    out_dir = sites_dir / slug

    # 3) load the template block map.
    try:
        template_blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"could not read template_blocks ({blocks_path}): {exc}") from exc

    # 4) practice → generated blocks (honesty-linted). generate() raises
    #    SystemExit(2) on a violation and SystemExit(str) on an unresolved
    #    modality — normalize both into PipelineError so the HTTP layer can
    #    return a clean 400 instead of the process exiting.
    try:
        generated = G.generate(practice, template_blocks, brain=brain)
    except SystemExit as exc:
        raise PipelineError(f"content generation refused (honesty/data): {exc}") from exc

    # 5) fill: copy template, apply blocks, substitute tokens, verify. fill.run
    #    is file-based, so stage the two intermediate JSONs in a temp dir that
    #    is NEVER inside the served site (see module docstring).
    sites_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"tvo-build-{slug}-") as td:
        tmp = pathlib.Path(td)
        practice_path = tmp / "practice.json"
        generated_path = tmp / "generated.json"
        practice_path.write_text(
            json.dumps(practice, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        generated_path.write_text(
            json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            rc = F.run(
                template=template_dir.resolve(),
                practice_path=practice_path.resolve(),
                generated_path=generated_path.resolve(),
                out=out_dir.resolve(),
                lenient=False,
            )
        except F.FillError as exc:
            raise PipelineError(f"fill failed: {exc}") from exc
        if rc != 0:
            raise PipelineError(f"fill returned non-zero ({rc})")

    # 6) GEO finishing pass (UX audit SH-F6): JSON-LD (MedicalBusiness +
    #    FAQPage), OG/Twitter meta, and llms.txt — deterministic, idempotent,
    #    every value from the already-linted practice tokens. This is the
    #    "get found on Google + AI search" deliverable, shipped on EVERY
    #    build path (the svc runner included), not just prove.sh's rail.
    #    geo.py self-aborts (SystemExit) on a banned phrase — normalize like
    #    generate's honesty exit so callers get one exception type.
    try:
        GEO.inject(out_dir, practice, site_url)
    except SystemExit as exc:
        raise PipelineError(f"geo pass refused (honesty): {exc}") from exc
    except (OSError, FileNotFoundError) as exc:
        raise PipelineError(f"geo pass failed: {exc}") from exc

    return {
        "slug": slug,
        "dir": str(out_dir),
        "owner_name": practice.get("owner_name", ""),
        "business_name": practice.get("business_name", ""),
        "practice": practice,
    }


__all__ = [
    "build_site",
    "slugify",
    "HonestyError",
    "PipelineError",
    "SLUG_RE",
    "DEFAULT_SITES_DIR",
    "DEFAULT_TEMPLATE_DIR",
    "DEFAULT_BLOCKS_PATH",
]
