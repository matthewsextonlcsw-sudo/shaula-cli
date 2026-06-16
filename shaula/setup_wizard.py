"""setup_wizard — first-run setup: pick a provider, then the BAA disclosure flow.

Run by ``shaula setup``. Two parts:

  1. Provider — choose Google (recommended) / Anthropic / OpenAI, confirm the key
     is present (or store it, 0600, in ``~/.shaula/.env``). BYO key always.
  2. Compliance — DISCLOSE which functions can carry PHI, RECOMMEND a BAA, and let
     the user choose. Enabling a PHI-capable function without an attested BAA is
     allowed: shaula warns, links the vendor's compliance page, records a dated
     acknowledgment, and proceeds. It never hard-blocks and never asserts anything
     about a vendor's terms — the BAA is the user's attestation.

The flow is driven through a small ``IO`` indirection so it is fully testable
(inject scripted answers) and so secrets are read without echo via ``getpass``.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Callable, Optional

import providers
import settings

# Which env var holds each provider's key (for presence checks + storage).
_KEY_ENV = {
    "google": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


@dataclass
class IO:
    """Indirection over stdin/stdout so the wizard is testable and secret-safe."""
    ask: Callable[[str], str] = input
    secret: Callable[[str], str] = getpass.getpass
    say: Callable[[str], None] = print


def _ask_choice(io: IO, prompt: str, options: list[str], default: str) -> str:
    """Ask until the answer is one of ``options`` (empty input → ``default``)."""
    opts = "/".join(o + ("*" if o == default else "") for o in options)
    while True:
        raw = io.ask(f"{prompt} [{opts}] ").strip().lower()
        if not raw:
            return default
        if raw in options:
            return raw
        io.say(f"  please choose one of: {', '.join(options)}")


def _yes(io: IO, prompt: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    raw = io.ask(f"{prompt} [{d}] ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def choose_provider(io: IO) -> str:
    """Provider selection + key presence/storage. Returns the chosen provider id."""
    import os  # local: only the wizard touches the live key vars

    io.say("\nModel provider — you bring your own key; shaula stores no key for you.")
    for pid, label in providers.PROVIDERS.items():
        if pid != "stub":
            io.say(f"  • {pid:9s} {label}")
    provider = _ask_choice(io, "Which provider?", ["google", "anthropic", "openai"], "google")

    env_var = _KEY_ENV[provider]
    if os.environ.get(env_var):
        io.say(f"  ✓ {env_var} found in your environment.")
    else:
        io.say(f"  {env_var} is not set.")
        if _yes(io, f"  Store a {provider} key now (saved 0600 to ~/.shaula/.env)?", default=False):
            key = io.secret(f"  Paste {env_var} (input hidden): ").strip()
            if key:
                settings.write_env_key(env_var, key)
                settings.load_env()
                io.say(f"  ✓ saved. (You can also just `export {env_var}=…` instead.)")
        else:
            io.say(f"  Skipped — set it later with `export {env_var}=…` "
                   "or re-run `shaula setup`.")

    model_default = providers.DEFAULT_MODELS[provider]
    model = io.ask(f"  Model [{model_default}] ").strip() or model_default
    settings.set_provider(provider, model)
    io.say(f"  ✓ provider = {provider}, model = {model}")
    return provider


def disclose_and_enable_phi(io: IO, provider: str) -> None:
    """The disclosure flow: show PHI exposure, recommend a BAA, let the user choose."""
    io.say("\nCompliance — what shaula can and cannot touch.")
    io.say("  Core functions are no-PHI by construction (the honesty engine wall):")
    for f in settings.FUNCTIONS:
        if not f["phi"]:
            io.say(f"    ✓ {f['name']:9s} {f['desc']}")

    io.say("\n  PHI-capable connectors are OFF until you turn them on:")
    for f in settings.FUNCTIONS:
        if f["phi"]:
            io.say(f"    ⚠ {f['name']:9s} {f['desc']}")

    compliance_url = providers.COMPLIANCE_PAGES.get(provider, "")
    io.say(
        "\n  Recommendation: if you enable a PHI-capable connector, have a Business "
        "Associate Agreement (BAA) in place with the services involved. shaula cannot "
        "verify a vendor's BAA — only you can attest to it."
    )
    if compliance_url:
        io.say(f"  {provider} compliance page: {compliance_url}")

    for f in settings.FUNCTIONS:
        if not f["phi"]:
            continue
        if not _yes(io, f"\n  Enable '{f['name']}' (can carry client PHI)?", default=False):
            io.say(f"  • '{f['name']}' left OFF.")
            continue
        # Enabled — warn, capture the attestation, proceed (never block).
        io.say(
            f"  ⚠ '{f['name']}' can carry client PHI. We recommend a BAA with the "
            f"services involved (e.g. your {provider} account / your email provider)."
        )
        vendor = io.ask("    Which service will carry it? (vendor name) ").strip() or provider
        has_baa = _yes(io, f"    Do you attest a BAA is in place with {vendor}?", default=False)
        note = io.ask("    Note (optional, recorded with the date): ").strip()
        settings.enable_function(f["name"])
        rec = settings.record_attestation(f["name"], vendor, baa=has_baa, note=note)
        last = rec["attestations"][-1]
        status = "BAA attested" if has_baa else "NO BAA attested — your choice, recorded"
        io.say(f"  ✓ '{f['name']}' enabled. {status} ({last['date']}, vendor={vendor}).")


def run(io: Optional[IO] = None) -> dict:
    """Full first-run setup. Returns the final config dict."""
    io = io or IO()
    io.say("shaula setup — provider + compliance. Nothing here is irreversible; "
           "re-run any time.")
    provider = choose_provider(io)
    disclose_and_enable_phi(io, provider)
    cfg = settings.load()
    io.say("\n✓ Setup complete. Try:  shaula research \"sleep hygiene basics\" --stub")
    return cfg
