#!/usr/bin/env bash
# ============================================================================
# shaula installer — macOS / Linux
# ============================================================================
# A downloadable, honesty-gated research & workflow agent. BYO model key.
#
# Quick install (when the repo is published):
#   curl -fsSL https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.sh | bash
#
# From a local checkout:
#   ./scripts/install.sh                 # installs from this checkout, no clone
#
# Options (also work after `bash -s --` when piped):
#   --dir DIR        where to clone/use the code     (default ~/.shaula/src)
#   --bin DIR        where to put the `shaula` shim   (default ~/.local/bin)
#   --ref REF        git ref/branch/tag to install    (default main)
#   --core-only      skip provider extras (httpx/google-auth); --stub still works
#   --no-venv        install into the active environment instead of a venv
#   --skip-setup     don't run the interactive `shaula setup` afterwards
#   -h, --help       show this help
#
# Clone-bootstrap: git-clone + uv/venv, symlink a shim onto your PATH.
# CLI-only — ZERO code-signing certs needed (desktop binaries are a later phase).
# ============================================================================

set -euo pipefail

# Environment hygiene: a leaked PYTHONPATH/PYTHONHOME can shadow the install with
# a different checkout and make a fresh install look broken. Drop them.
if [ -n "${PYTHONPATH:-}" ]; then unset PYTHONPATH; fi
if [ -n "${PYTHONHOME:-}" ]; then unset PYTHONHOME; fi
# Keep uv from reading another project's config when invoked oddly.
export UV_NO_CONFIG=1

# --- output helpers --------------------------------------------------------- #
if [ -t 1 ]; then
    BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
else
    BOLD=''; GREEN=''; YELLOW=''; RED=''; CYAN=''; NC=''
fi
say()  { printf "%b\n" "${CYAN}›${NC} $*"; }
ok()   { printf "%b\n" "${GREEN}✓${NC} $*"; }
warn() { printf "%b\n" "${YELLOW}⚠${NC} $*" >&2; }
die()  { printf "%b\n" "${RED}✗ $*${NC}" >&2; exit 1; }

# --- configuration ---------------------------------------------------------- #
REPO_URL="${SHAULA_REPO:-https://github.com/matthewsextonlcsw-sudo/shaula-cli.git}"
SHAULA_HOME="${SHAULA_HOME:-$HOME/.shaula}"
INSTALL_DIR="${SHAULA_INSTALL_DIR:-$SHAULA_HOME/src}"
BIN_DIR="${SHAULA_BIN_DIR:-$HOME/.local/bin}"
REF="main"
EXTRAS="[all]"
USE_VENV=true
RUN_SETUP=true
PY_MIN_MAJOR=3
PY_MIN_MINOR=9

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)        INSTALL_DIR="$2"; shift 2 ;;
        --bin)        BIN_DIR="$2"; shift 2 ;;
        --ref)        REF="$2"; shift 2 ;;
        --core-only)  EXTRAS=""; shift ;;
        --no-venv)    USE_VENV=false; shift ;;
        --skip-setup) RUN_SETUP=false; shift ;;
        -h|--help)    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            die "unknown option: $1 (try --help)" ;;
    esac
done

[ -t 0 ] && INTERACTIVE=true || INTERACTIVE=false

# --- python discovery ------------------------------------------------------- #
# Prefer uv (fast, manages its own Python); fall back to a system python3.
HAVE_UV=false
if command -v uv >/dev/null 2>&1; then HAVE_UV=true; fi

find_python() {
    local c
    for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
        if command -v "$c" >/dev/null 2>&1; then
            if "$c" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($PY_MIN_MAJOR,$PY_MIN_MINOR) else 1)" 2>/dev/null; then
                echo "$c"; return 0
            fi
        fi
    done
    return 1
}

# --- resolve the source tree ------------------------------------------------ #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
LOCAL_ROOT=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../pyproject.toml" ] \
   && grep -q '^name = "shaula"' "$SCRIPT_DIR/../pyproject.toml" 2>/dev/null; then
    LOCAL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [ -n "$LOCAL_ROOT" ]; then
    INSTALL_DIR="$LOCAL_ROOT"
    say "Installing from local checkout: ${BOLD}$INSTALL_DIR${NC}"
else
    command -v git >/dev/null 2>&1 || die "git is required to clone shaula"
    if [ -d "$INSTALL_DIR/.git" ]; then
        say "Updating existing checkout at $INSTALL_DIR"
        git -C "$INSTALL_DIR" fetch --quiet origin "$REF" || die "git fetch failed"
        git -C "$INSTALL_DIR" checkout --quiet "$REF"
        git -C "$INSTALL_DIR" pull --quiet --ff-only origin "$REF" || true
    else
        say "Cloning $REPO_URL → $INSTALL_DIR"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --quiet --branch "$REF" --depth 1 "$REPO_URL" "$INSTALL_DIR" \
            || die "git clone failed (is the repo published yet?)"
    fi
    ok "Source ready at $INSTALL_DIR"
fi

# --- install --------------------------------------------------------------- #
SPEC=".${EXTRAS}"
VENV_DIR="$SHAULA_HOME/venv"
SHAULA_EXEC=""

if [ "$USE_VENV" = true ]; then
    if [ "$HAVE_UV" = true ]; then
        say "Creating virtual environment with uv → $VENV_DIR"
        uv venv "$VENV_DIR" >/dev/null
        say "Installing shaula$EXTRAS"
        ( cd "$INSTALL_DIR" && uv pip install --python "$VENV_DIR/bin/python" "$SPEC" >/dev/null )
    else
        PY="$(find_python)" || die "need Python >= $PY_MIN_MAJOR.$PY_MIN_MINOR (or install uv)"
        say "Creating virtual environment with $PY → $VENV_DIR"
        "$PY" -m venv "$VENV_DIR"
        say "Installing shaula$EXTRAS"
        "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null
        ( cd "$INSTALL_DIR" && "$VENV_DIR/bin/python" -m pip install --quiet "$SPEC" )
    fi
    SHAULA_EXEC="$VENV_DIR/bin/shaula"
else
    PY="$(find_python)" || die "need Python >= $PY_MIN_MAJOR.$PY_MIN_MINOR"
    say "Installing shaula$EXTRAS into the active environment"
    ( cd "$INSTALL_DIR" && "$PY" -m pip install --user "$SPEC" )
    SHAULA_EXEC="$("$PY" -c 'import sysconfig,os;print(os.path.join(sysconfig.get_path("scripts",f"{os.name}_user"),"shaula"))' 2>/dev/null || true)"
fi

[ -x "$SHAULA_EXEC" ] || die "install finished but the shaula entry point was not found at $SHAULA_EXEC"
ok "Installed: $SHAULA_EXEC"

# --- shim ------------------------------------------------------------------- #
mkdir -p "$BIN_DIR"
ln -sf "$SHAULA_EXEC" "$BIN_DIR/shaula"
ok "Linked $BIN_DIR/shaula → $SHAULA_EXEC"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH. Add it:"
       printf "      %b\n" "${BOLD}export PATH=\"$BIN_DIR:\$PATH\"${NC}" ;;
esac

# --- verify (offline, no key) ---------------------------------------------- #
say "Verifying the install (offline honesty-gate self-test)…"
if "$SHAULA_EXEC" doctor >/dev/null 2>&1; then
    ok "shaula doctor passed — the honesty gate holds with no network."
else
    warn "shaula doctor reported problems; run '$BIN_DIR/shaula doctor' to see them."
fi

# --- setup ------------------------------------------------------------------ #
if [ "$RUN_SETUP" = true ] && [ "$INTERACTIVE" = true ]; then
    echo
    "$SHAULA_EXEC" setup || warn "setup skipped/failed — re-run anytime with 'shaula setup'."
fi

echo
ok "${BOLD}shaula is installed.${NC}"
cat <<EOF

  Try it offline (no key needed):
      shaula research "sleep hygiene basics" --stub
      shaula author   "draft a weekly blog workflow" --stub

  Bring your own key when ready:
      shaula setup          # pick a provider (Google / Anthropic / OpenAI) + compliance
      shaula providers      # see which keys are detected

  The honesty gate is always on: a banned, unverifiable claim parks the run
  instead of shipping. Core functions are no-PHI by construction.
EOF
