#!/usr/bin/env python3
"""
fill.py — Website-fill engine for the Solo Private-Practice template (and any
template that follows the same FILL_MANIFEST contract).

WHAT IT DOES
------------
Given a template directory, a `practice.json` (the customer's facts) and a
`generated.json` (the resolved AI-GENERATE prose), it produces a finished,
ready-to-host site in an output directory by:

  1. Copying the entire template tree to the output dir (assets, CSS, JS, etc.
     are carried over byte-for-byte; the template itself is never modified).
  2. For every file that has AI-GENERATE blocks, replacing each block's neutral
     placeholder with its final written content from generated.json, then
     stripping the `<!-- AI-GENERATE:... -->` marker comments.
  3. Substituting every `{{token}}` across the configured content files using
     the flat key/value map in practice.json.
  4. Verifying the result: zero `{{...}}` tokens left, zero `AI-GENERATE`
     markers left, and (best-effort) `node --check` on any *.js content file.

This is exactly what a dashboard "Build site" button would invoke: it is fully
non-interactive — it reads JSON + template and writes output, nothing more. No
prompts, no network, no third-party packages. Python 3.8+ standard library only.

USAGE
-----
    python3 fill.py \
        --template /path/to/template-dir \
        --practice /path/to/practice.json \
        --generated /path/to/generated.json \
        --out /path/to/output-dir

All four flags have sensible defaults (see DEFAULTS below) so that, run from the
`_demo-fill` directory with the demo data in place, a bare `python3 fill.py`
produces `./cedar-sage-output/`.

DESIGN NOTES
------------
* generated.json drives the AI-GENERATE step. Each block entry is::

      "<block_id>": {
          "file":    "<relative file the block lives in, e.g. app.js>",
          "find":    "<the exact neutral placeholder text shipped in the template>",
          "replace": "<the final written content>"
      }

  Using an explicit `find` (copied verbatim from the template) instead of trying
  to parse HTML/JS boundaries makes the substitution exact and auditable: if a
  template placeholder ever changes, the engine fails loudly on that block
  rather than silently producing a half-filled page.

* Order matters. AI-GENERATE replacements run BEFORE token substitution. The
  generated `replace` strings already have their tokens resolved, so they are
  never re-processed; only the static shell tokens that remain in the markup get
  filled. This keeps each region under exactly one owner.

* Strict by default: a missing `find`, a leftover `{{token}}`, or a surviving
  `AI-GENERATE` marker raises a clear error and exits non-zero, so a broken
  build can never be shipped unnoticed. `--lenient` downgrades these to warnings.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (resolved relative to this script's directory, so a bare run works)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULTS = {
    "template": SCRIPT_DIR.parent / "_templates" / "private-practice",
    "practice": SCRIPT_DIR / "practice.json",
    "generated": SCRIPT_DIR / "generated.json",
    "out": SCRIPT_DIR / "cedar-sage-output",
}

# Files we run token substitution over. Per the manifest, only these two carry
# customer content; styles.css / tweaks.js are pure design/dev and are copied
# untouched. Kept as a tuple so the engine is general but predictable; any file
# referenced by a generated.json block is automatically added to this set too.
CONTENT_FILES = ("index.html", "app.js")

# Build-time documentation that lives in the template but must NOT ship inside a
# customer's finished site (it describes the fill mechanism and contains literal
# {{token}} / AI-GENERATE examples). Excluded from the copied output tree.
EXCLUDE_FROM_OUTPUT = ("FILL_MANIFEST.md", "README.md")

# Literal find→replace pairs applied to content files AFTER token substitution.
# Used to neutralize template-authoring scaffolding (e.g. the source banner that
# tells a developer the file uses tokens + AI-GENERATE blocks) so the finished
# site contains no fill-mechanism residue. Kept data-driven and transparent
# rather than magic regexes; extend per template as needed.
BANNER_SCRUB = (
    (
        "   Solo Private-Practice Template — single-page interactive prototype\n"
        "   Client-side routing, content templates, motion, form.\n"
        "   Owner-specific text lives as double-curly tokens and AI-GENERATE comment blocks.",
        "   Single-page site — client-side routing, content sections, motion, and contact form.",
    ),
)

TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
# Matches a whole `<!-- AI-GENERATE:name | prompt... -->` comment (HTML style)
# OR a `// AI-GENERATE:name | prompt...` line comment (JS style, used for the
# blog_posts block). Non-greedy, DOTALL so multi-line prompts are consumed.
AIGEN_HTML_RE = re.compile(r"<!--\s*AI-GENERATE:.*?-->", re.DOTALL)
AIGEN_JS_RE = re.compile(r"^[ \t]*//[ \t]*AI-GENERATE:.*?(?=\n[ \t]*const |\n[ \t]*\$\{|\n\n)", re.DOTALL | re.MULTILINE)


class FillError(RuntimeError):
    """Raised on any condition that would ship a broken site."""


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Load inputs
# ---------------------------------------------------------------------------
def load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise FillError(f"{label} not found: {path}")
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise FillError(f"{label} is not valid JSON ({path}): {exc}") from exc


def build_token_map(practice: dict) -> dict[str, str]:
    """Flatten practice.json into {token_name: string_value}, ignoring _comment.

    Values are HTML-escaped with quote=True. Tokens are substituted verbatim into
    template HTML/JS including ATTRIBUTE contexts (alt="{{business_name}}",
    content="...{{owner_name}}..."), so an un-escaped survey value like
    `"><script>...` would break out of the attribute and execute on the published
    site (stored XSS). quote=True neutralizes < > & " ' for both element-text and
    attribute contexts; browsers decode the entities on render, so display is
    unchanged. The AI-GENERATE blocks are applied earlier and carry intentional
    HTML — they are NOT in this flat token map, so they are not double-escaped.
    """
    tokens: dict[str, str] = {}
    for key, val in practice.items():
        if key.startswith("_"):
            continue
        tokens[key] = "" if val is None else html.escape(str(val), quote=True)
    return tokens


# ---------------------------------------------------------------------------
# Step 1 — copy template tree to output
# ---------------------------------------------------------------------------
def copy_template(template_dir: Path, out_dir: Path) -> None:
    if not template_dir.is_dir():
        raise FillError(f"Template directory not found: {template_dir}")
    if out_dir.exists():
        log(f"  · output dir exists, clearing: {out_dir}")
        shutil.rmtree(out_dir)
    # copytree preserves the full tree (assets/, styles.css, tweaks.js, ...),
    # minus the build-time docs that should not ship in a finished site.
    ignore = shutil.ignore_patterns(*EXCLUDE_FROM_OUTPUT)
    shutil.copytree(template_dir, out_dir, ignore=ignore)
    log(f"  · copied template → {out_dir}")
    if EXCLUDE_FROM_OUTPUT:
        log(f"  · excluded build docs: {', '.join(EXCLUDE_FROM_OUTPUT)}")


def scrub_banners(out_dir: Path, content_files: set[str]) -> None:
    """Remove template-authoring scaffolding from content files (see BANNER_SCRUB)."""
    if not BANNER_SCRUB:
        return
    for rel_file in sorted(content_files):
        fpath = out_dir / rel_file
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8")
        changed = False
        for find, replace in BANNER_SCRUB:
            if find in text:
                text = text.replace(find, replace)
                changed = True
        if changed:
            fpath.write_text(text, encoding="utf-8")
            log(f"  · scrubbed authoring banner in {rel_file}")


# ---------------------------------------------------------------------------
# Step 2 — resolve AI-GENERATE blocks (per file), then strip markers
# ---------------------------------------------------------------------------
def apply_generated_blocks(
    out_dir: Path, generated: dict, lenient: bool
) -> set[str]:
    """Apply every block's find→replace in its target file. Returns the set of
    relative file paths that were touched (so token substitution covers them)."""
    blocks = generated.get("blocks", {})
    if not blocks:
        raise FillError("generated.json has no 'blocks' object.")

    # Group blocks by their target file so we read/write each file once.
    by_file: dict[str, list[tuple[str, dict]]] = {}
    for block_id, spec in blocks.items():
        target = spec.get("file")
        if not target:
            raise FillError(f"Block '{block_id}' is missing its 'file' field.")
        by_file.setdefault(target, []).append((block_id, spec))

    touched: set[str] = set()
    for rel_file, items in by_file.items():
        fpath = out_dir / rel_file
        if not fpath.is_file():
            raise FillError(f"Block target file not found in output: {rel_file}")
        text = fpath.read_text(encoding="utf-8")

        for block_id, spec in items:
            find = spec.get("find")
            replace = spec.get("replace")
            if find is None or replace is None:
                raise FillError(f"Block '{block_id}' needs both 'find' and 'replace'.")
            count = text.count(find)
            if count == 0:
                msg = (
                    f"Block '{block_id}': its 'find' placeholder was not located "
                    f"in {rel_file}. The template may have changed — re-sync the "
                    f"block's 'find' text with the template."
                )
                if lenient:
                    log(f"  ! WARN {msg}")
                    continue
                raise FillError(msg)
            if count > 1:
                msg = (
                    f"Block '{block_id}': its 'find' placeholder matched {count} "
                    f"times in {rel_file}; expected exactly 1 (ambiguous)."
                )
                if lenient:
                    log(f"  ! WARN {msg} — replacing all occurrences.")
                else:
                    raise FillError(msg)
            text = text.replace(find, replace)

        # Strip the AI-GENERATE marker comments now that content is in place.
        text = AIGEN_HTML_RE.sub("", text)
        text = AIGEN_JS_RE.sub("", text)

        fpath.write_text(text, encoding="utf-8")
        touched.add(rel_file)
        log(f"  · resolved {len(items)} AI-GENERATE block(s) in {rel_file}")

    return touched


# ---------------------------------------------------------------------------
# Step 3 — substitute {{tokens}} across content files
# ---------------------------------------------------------------------------
def substitute_tokens(
    out_dir: Path, content_files: set[str], tokens: dict[str, str], lenient: bool
) -> None:
    unknown_seen: set[str] = set()
    for rel_file in sorted(content_files):
        fpath = out_dir / rel_file
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8")

        def _replace(match: re.Match) -> str:
            name = match.group(1)
            if name in tokens:
                return tokens[name]
            unknown_seen.add(name)
            return match.group(0)  # leave untouched so it shows up in verify

        new_text, n = TOKEN_RE.subn(_replace, text)
        fpath.write_text(new_text, encoding="utf-8")
        log(f"  · substituted tokens in {rel_file} ({n} replacements)")

    if unknown_seen:
        msg = (
            "No value in practice.json for token(s): "
            + ", ".join("{{%s}}" % t for t in sorted(unknown_seen))
        )
        if lenient:
            log(f"  ! WARN {msg}")
        else:
            raise FillError(msg)


# ---------------------------------------------------------------------------
# Step 4 — verify the finished site
# ---------------------------------------------------------------------------
def verify(out_dir: Path, content_files: set[str], lenient: bool) -> None:
    problems: list[str] = []

    # 4a. No leftover tokens and no leftover AI-GENERATE markers, anywhere in
    #     the text files of the output (we scan all *.html/*.js/*.css/*.svg).
    scan_exts = {".html", ".js", ".css", ".svg", ".json", ".txt", ".md"}
    leftover_tokens: dict[str, list[str]] = {}
    leftover_markers: list[str] = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in scan_exts:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(out_dir))
        toks = sorted(set(TOKEN_RE.findall(body)))
        if toks:
            leftover_tokens[rel] = toks
        if "AI-GENERATE" in body:
            leftover_markers.append(rel)

    if leftover_tokens:
        for rel, toks in leftover_tokens.items():
            problems.append(
                f"{rel}: {len(toks)} unresolved token(s): "
                + ", ".join("{{%s}}" % t for t in toks)
            )
    if leftover_markers:
        problems.append("AI-GENERATE marker(s) still present in: " + ", ".join(leftover_markers))

    # 4b. JS syntax check (best-effort; only if `node` is on PATH).
    node = shutil.which("node")
    if node:
        for rel_file in sorted(content_files):
            if not rel_file.endswith(".js"):
                continue
            jpath = out_dir / rel_file
            res = subprocess.run(
                [node, "--check", str(jpath)],
                capture_output=True, text=True,
            )
            if res.returncode != 0:
                problems.append(f"node --check failed for {rel_file}: {res.stderr.strip()}")
            else:
                log(f"  · node --check OK: {rel_file}")
    else:
        log("  · (node not found — skipping JS syntax check)")

    # Report
    token_leak = sum(len(v) for v in leftover_tokens.values())
    log("")
    log("  VERIFY ─────────────────────────────")
    log(f"    {{{{token}}}} leaks remaining : {token_leak}")
    log(f"    AI-GENERATE markers left  : {len(leftover_markers)}")
    log(f"    JS syntax check           : {'OK' if node and not any('node --check' in p for p in problems) else ('skipped' if not node else 'FAILED')}")
    log("  ─────────────────────────────────────")

    if problems:
        joined = "\n    - ".join(problems)
        msg = f"Verification found {len(problems)} problem(s):\n    - {joined}"
        if lenient:
            log(f"  ! WARN {msg}")
        else:
            raise FillError(msg)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(template: Path, practice_path: Path, generated_path: Path,
        out: Path, lenient: bool) -> int:
    log("Website-fill engine")
    log(f"  template  : {template}")
    log(f"  practice  : {practice_path}")
    log(f"  generated : {generated_path}")
    log(f"  output    : {out}")
    log("")

    practice = load_json(practice_path, "practice.json")
    generated = load_json(generated_path, "generated.json")
    tokens = build_token_map(practice)
    log(f"  · loaded {len(tokens)} data token(s) + "
        f"{len(generated.get('blocks', {}))} AI-GENERATE block(s)")

    log("[1/4] Copying template ...")
    copy_template(template, out)

    log("[2/4] Resolving AI-GENERATE blocks ...")
    touched = apply_generated_blocks(out, generated, lenient)

    log("[3/4] Substituting {{tokens}} ...")
    content_files = set(CONTENT_FILES) | touched
    substitute_tokens(out, content_files, tokens, lenient)
    scrub_banners(out, content_files)

    log("[4/4] Verifying finished site ...")
    verify(out, content_files, lenient)

    log("")
    log(f"DONE — finished site written to: {out}")
    log(f"Preview: python3 -m http.server --directory '{out}' 8731  →  http://127.0.0.1:8731/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fill a website template from practice.json + generated.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--template", type=Path, default=DEFAULTS["template"],
                        help="Template directory (read-only; never modified).")
    parser.add_argument("--practice", type=Path, default=DEFAULTS["practice"],
                        help="Path to practice.json (the data tokens).")
    parser.add_argument("--generated", type=Path, default=DEFAULTS["generated"],
                        help="Path to generated.json (resolved AI-GENERATE blocks).")
    parser.add_argument("--out", type=Path, default=DEFAULTS["out"],
                        help="Output directory for the finished site.")
    parser.add_argument("--lenient", action="store_true",
                        help="Downgrade hard errors (missing find / token leaks) to warnings.")
    args = parser.parse_args(argv)

    try:
        return run(args.template.resolve(), args.practice.resolve(),
                   args.generated.resolve(), args.out.resolve(), args.lenient)
    except FillError as exc:
        log("")
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
