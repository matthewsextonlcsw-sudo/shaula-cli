#!/usr/bin/env python3
"""release — cut a shaula release (CLI-only, no code-signing certs).

A minimal release cutter for a stdlib CLI — no Electron build, no notarization,
no PyPI step. It:

  1. refuses to run on a dirty tree (unless ``--allow-dirty``);
  2. runs the test suite — a red suite blocks the release (the honesty gate must
     prove out every cut);
  3. bumps ``shaula.__version__`` (major/minor/patch or an explicit ``--set``);
  4. builds the sdist + wheel into ``dist/``;
  5. on ``--publish`` only: commits the bump, tags ``vX.Y.Z``, pushes, and creates
     a GitHub release via ``gh`` with the wheel, sdist, and installers attached.

SAFETY: ``--dry-run`` is the DEFAULT. Steps 1–4 are reversible (build artifacts);
step 5 is irreversible (push + public release) and runs ONLY with ``--publish``.
Publishing is a human gate — this script never pushes unless explicitly told to.

Usage:
    python scripts/release.py patch                 # dry run: test + build only
    python scripts/release.py minor --publish        # cut + push + GitHub release
    python scripts/release.py --set 1.0.0 --publish
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "shaula" / "__init__.py"
ASSET_GLOBS = ("scripts/install.sh", "scripts/install.ps1", "scripts/install.cmd")

_C = {"cyan": "\033[0;36m", "green": "\033[0;32m", "yellow": "\033[0;33m",
      "red": "\033[0;31m", "bold": "\033[1m", "off": "\033[0m"} if sys.stdout.isatty() \
    else {k: "" for k in ("cyan", "green", "yellow", "red", "bold", "off")}


def say(m): print(f"{_C['cyan']}›{_C['off']} {m}")
def ok(m): print(f"{_C['green']}✓{_C['off']} {m}")
def warn(m): print(f"{_C['yellow']}⚠{_C['off']} {m}", file=sys.stderr)
def die(m): print(f"{_C['red']}✗ {m}{_C['off']}", file=sys.stderr); raise SystemExit(1)


def run(cmd, *, capture=False, check=True):
    say(f"$ {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=ROOT, text=True,
                         capture_output=capture, check=False)
    if check and res.returncode != 0:
        if capture:
            sys.stderr.write(res.stdout or "")
            sys.stderr.write(res.stderr or "")
        die(f"command failed ({res.returncode}): {' '.join(cmd)}")
    return res


def read_version() -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"), re.M)
    if not m:
        die(f"could not find __version__ in {INIT}")
    return m.group(1)


def bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(new: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    text = re.sub(r'^(__version__\s*=\s*")[^"]+(")', rf"\g<1>{new}\g<2>", text, count=1, flags=re.M)
    INIT.write_text(text, encoding="utf-8")


def git_clean() -> bool:
    return not run(["git", "status", "--porcelain"], capture=True, check=False).stdout.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cut a shaula release (CLI-only, no certs).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("part", nargs="?", choices=["major", "minor", "patch"], default="patch",
                   help="which version part to bump (default: patch)")
    ap.add_argument("--set", dest="explicit", metavar="X.Y.Z", help="set an explicit version")
    ap.add_argument("--publish", action="store_true",
                    help="actually commit, tag, push, and create the GitHub release (IRREVERSIBLE)")
    ap.add_argument("--allow-dirty", action="store_true", help="permit a dirty working tree")
    ap.add_argument("--skip-tests", action="store_true", help="skip the test gate (not recommended)")
    args = ap.parse_args(argv)

    current = read_version()
    new = args.explicit or bump(current, args.part)
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        die(f"not a semver version: {new}")

    mode = f"{_C['bold']}PUBLISH{_C['off']}" if args.publish else f"{_C['bold']}dry-run{_C['off']}"
    say(f"shaula release — {current} → {_C['bold']}{new}{_C['off']}  [{mode}]")

    if not args.allow_dirty and not git_clean():
        die("working tree is dirty; commit/stash first or pass --allow-dirty")

    # 1. test gate — a red suite blocks the cut.
    if not args.skip_tests:
        say("Running the test suite (the cut is gated on green)…")
        run([sys.executable, "-m", "pytest", "-q"])
        ok("tests green")

    # 2. bump + build (reversible).
    write_version(new)
    ok(f"set __version__ = {new}")
    say("Building sdist + wheel…")
    run([sys.executable, "-m", "build"])
    artifacts = sorted(p.name for p in (ROOT / "dist").glob(f"*{new}*"))
    ok(f"built: {', '.join(artifacts) or '(nothing — check dist/)'}")

    tag = f"v{new}"
    if not args.publish:
        warn("DRY RUN — no git mutation, no push, no GitHub release.")
        print(f"\nWould, with --publish:\n"
              f"  git commit -am 'release: {tag}'\n"
              f"  git tag {tag}\n"
              f"  git push origin HEAD --tags\n"
              f"  gh release create {tag} dist/* {' '.join(ASSET_GLOBS)} "
              f"--title '{tag}' --generate-notes\n")
        # Leave the version bump in place for inspection; revert it so a dry run
        # is side-effect-free on tracked files.
        write_version(current)
        say(f"reverted __version__ back to {current} (dry run leaves no tracked change)")
        return 0

    # 3. publish (IRREVERSIBLE — only with --publish).
    run(["git", "commit", "-am", f"release: {tag}"])
    run(["git", "tag", tag])
    run(["git", "push", "origin", "HEAD", "--tags"])
    assets = [str(p) for p in (ROOT / "dist").glob("*")] + [a for a in ASSET_GLOBS if (ROOT / a).exists()]
    run(["gh", "release", "create", tag, *assets, "--title", tag, "--generate-notes"])
    ok(f"published {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
