# Shaula

**The downloadable AI office — part of [VibeCheck](https://vibecheck.luxury), runs on your machine. Honesty-gated. Bring your own model key.**

Shaula drafts honest office workflows and sourced research briefs — and refuses to ship a claim it can't stand behind. A banned, unverifiable marketing claim (a fabricated statistic, a "clinically proven cure," a "#1 best") doesn't get quietly rewritten; it **parks the run** for a human. That gate is the whole point.

It installs like a real tool — a `shaula` command on your PATH — and runs **fully offline with no key at all** via a deterministic stub, so you can prove the honesty gate before you ever spend a token.

```bash
shaula research "sleep hygiene basics" --stub      # offline, no key
shaula author   "draft a weekly blog workflow" --stub
```

> Shaula is also the AI inside VibeCheck. This is the standalone, self-hosted edition: same honesty engine, your machine, your key. It carries **none** of VibeCheck's or the EMR's proprietary capabilities — it is a clean, public, MIT-licensed tool.

---

## Why Shaula

- **The honesty gate is the moat.** Every deliverable passes one linter for unsourced statistics, efficacy claims, guarantees, superlatives, and "studies show" appeals. It is a **hard stop, never an auto-repair** — a banned claim raises, the run parks, a human decides. One gate, one place, applied identically no matter which model produced the text.
- **Bring your own key, any major provider.** Google (recommended default), Anthropic, or OpenAI — each is a thin adapter behind a single `Callable[[str, str], str]` seam. Swapping providers is a one-line config change. Shaula ships and brokers **no** key.
- **No-PHI by construction.** Core functions (authoring, research, workflow generation) operate on business and marketing topics and never touch client data. PHI-capable connectors are a separate, opt-in tier (see *Compliance*).
- **Zero-dependency core.** The stub path and the honesty gate need nothing but the Python standard library. `httpx` (and `google-auth` for Vertex) are pulled in only when you actually call a cloud provider.
- **Runs offline for real.** `--stub` is a first-class mode: deterministic output, no network, no key — used for CI, demos, and proving the gate.

---

## Install

### Quick install (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.sh | bash
```

The installer clones the repo, creates an isolated virtual environment (using [uv](https://github.com/astral-sh/uv) if present, otherwise `python -m venv`), installs Shaula with all three provider adapters, links a `shaula` shim into `~/.local/bin`, and runs the offline self-test. CLI-only — **no code-signing certificates required.**

Useful flags: `--core-only` (skip provider extras; `--stub` still works), `--no-venv`, `--skip-setup`, `--dir DIR`, `--ref REF`.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/matthewsextonlcsw-sudo/shaula-cli/main/scripts/install.ps1 | iex
```

### From a checkout

```bash
git clone https://github.com/matthewsextonlcsw-sudo/shaula-cli.git
cd shaula-cli
./scripts/install.sh          # installs from this checkout, no re-clone
# or, for development:
pip install -e ".[dev]"
```

---

## Quickstart

```bash
shaula setup                  # pick a provider + work through the compliance disclosure
shaula providers              # show which provider keys are detected

# Offline (no key) — great for trying it and for CI:
shaula research "caffeine and sleep" --stub
shaula author   "a weekly newsletter workflow" --stub

# With a key (BYO):
export GEMINI_API_KEY=...      # or ANTHROPIC_API_KEY / OPENAI_API_KEY
shaula research "caffeine and sleep"
shaula author   "a weekly newsletter workflow"

# Run a workflow template to a deliverable:
shaula workflow path/to/template.json -v topic="sleep hygiene"

shaula doctor                  # environment + offline honesty-gate self-test
```

`shaula author` returns a **vetted, DAG-ordered task graph** whose final step is always a human review gate. `shaula research` returns an honest background brief with every claim tagged and a verification checklist. Both pass the honesty gate before you see them.

---

## Bring your own key

| Provider  | Key env var                          | Default model        |
|-----------|--------------------------------------|----------------------|
| Google    | `GEMINI_API_KEY` / `GOOGLE_API_KEY`  | `gemini-2.5-flash`   |
| Anthropic | `ANTHROPIC_API_KEY`                  | `claude-sonnet-4-6`  |
| OpenAI    | `OPENAI_API_KEY`                     | `gpt-4o`             |

Set the env var directly, or run `shaula setup` to store one (mode `0600`) in `~/.shaula/.env`. Google additionally supports Application Default Credentials against Vertex AI when no API key is set. Override the model per-run with `--model`, or the provider with `--provider`.

---

## Compliance — recommend, disclose, let you choose

Shaula is built for regulated settings, and its stance is explicit and **never paternalistic**:

- It **recommends** a Business Associate Agreement (BAA) when you enable anything that can carry protected health information.
- It **discloses** which functions are PHI-capable. Core authoring/research/workflow functions are **no-PHI by construction**; email and messaging connectors are the PHI-capable tier and are **off until you turn them on**.
- It **never hard-blocks.** Enabling a PHI-capable function without a BAA is allowed — Shaula warns, links the vendor's compliance page, records a **dated acknowledgment**, and proceeds. Your practice, your call.
- A BAA is **your attestation**, recorded with a date — never an assertion Shaula makes about a vendor's terms. There is no API to auto-verify a vendor BAA, so Shaula never pretends to.

Underneath all of that, the no-PHI-by-construction engine wall remains as belt-and-suspenders.

> Shaula does not provide legal advice. You are responsible for your own HIPAA compliance and for any BAAs with the providers you choose.

---

## How it's built

```
shaula/
├── __init__.py        # the one path bootstrap (makes the engine importable)
├── cli.py             # the `shaula` command (author / research / workflow / setup / doctor)
├── gate.py            # the honesty gate: lint_gate + BrainError — the moat, transport-free
├── providers.py       # Google / Anthropic / OpenAI / Stub adapters behind one seam
├── settings.py        # ~/.shaula config, BYO-key handling, dated BAA attestations
├── setup_wizard.py    # first-run provider + compliance disclosure flow
├── honesty.py         # the Reviewer's plain-words narration of a refusal
├── engine/            # the deterministic generation engine (honest by construction)
└── workflows/         # the vetted workflow builder, templates, and local executor
```

The seams are deliberate: **providers** are pure transports (they return raw text and never judge it), the **gate** is applied exactly once by the workflow layer, and the **engine** never learns which provider produced a byte. That is what lets a banned claim be refused identically across every model. Everything runs locally — no external service, no backend to call home to.

---

## Development

```bash
pip install -e ".[dev]"
pytest                         # the full suite, offline, no key
shaula doctor                  # offline gate self-test
```

The test suite proves the gate three ways: directly, through the workflow execution path on real model output, and at the CLI boundary (a banned claim exits non-zero with a narrated refusal). All of it runs with no network and no key.

---

## Roadmap

- **P0 — engine as a local runnable.** ✅ CLI, offline stub, honesty gate, provider seam, tests.
- **P1 — installers + setup wizard.** ✅ `install.sh` / `install.ps1`, BYO-key + compliance flow.
- **P2 — release pipeline.** ✅ `scripts/release.py` (test-gated build; publish is a human gate). CLI ships with **zero certificates**.
- **P3 — desktop app + code-signing.** Electron build, notarization (gated on certs).
- **P4 — landing + distribution from vibecheck.luxury.** See `web/index.html`.

---

## License

MIT — see [LICENSE](LICENSE).
