"""providers — pluggable model adapters behind one ``Callable[[str, str], str]`` seam.

The engine's model seam is a plain ``Model = Callable[[system, user], assistant_text]``
(see ``workflows/author.py`` and ``workflows/local_executor.py``). Every provider
here is just an adapter to that shape, so swapping Google ↔ Anthropic ↔ OpenAI ↔
an offline stub is a one-line config change and never touches the engine or the
honesty gate.

Design rules:
  * BYO key, multiple providers. Keys come from the environment (or ``~/.shaula``);
    shaula never ships or brokers a key. No provider is bundled or required.
  * Providers are PURE TRANSPORTS. They return the model's raw text. The honesty
    gate (``gate.lint_gate``) is applied by the workflow layer that consumes the
    output — exactly once, in one place — so a banned claim is refused the same
    way regardless of which provider produced it. Providers never auto-repair.
  * Core stays dependency-free. ``httpx`` / ``google-auth`` are imported lazily
    inside the adapter that needs them; a missing extra raises a friendly install
    hint, and the offline ``StubModel`` needs nothing at all.

No PHI by construction: prompts are business / research / marketing text.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

from gate import BrainError

# A model is any callable (system, user) -> assistant_text.
Model = Callable[[str, str], str]

# Provider id -> human label. The order is the recommendation order in setup.
PROVIDERS: dict[str, str] = {
    "google": "Google (Gemini / Vertex) — recommended default",
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "stub": "Offline stub (no network, no key — for proofs & CI)",
}

# Built-in default model per provider (override via --model, env, or ~/.shaula).
DEFAULT_MODELS: dict[str, str] = {
    "google": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}

# Vendor compliance / BAA pages surfaced by the setup wizard (advisory links —
# shaula asserts nothing about a vendor's terms; the user attests).
COMPLIANCE_PAGES: dict[str, str] = {
    "google": "https://cloud.google.com/security/compliance/hipaa",
    "anthropic": "https://www.anthropic.com/legal/commercial-terms",
    "openai": "https://openai.com/policies/business-terms/",
}

_DEFAULT_TIMEOUT = 90.0
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.5


def _require_httpx():
    """Lazily import httpx with a friendly install hint (keeps core zero-dep)."""
    try:
        import httpx  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via install hint
        raise BrainError(
            "missing_dep",
            "this provider needs httpx — install it with "
            "`pip install \"shaula[all]\"` (or shaula[google|anthropic|openai])",
        ) from exc
    return httpx


# --------------------------------------------------------------------------- #
# Offline stub — deterministic, zero network, zero key. SYNTHETIC ONLY.
# --------------------------------------------------------------------------- #
class StubModel:
    """A deterministic offline model for proofs, CI, and ``--stub`` runs.

    It inspects the system prompt to return a structurally valid reply for each
    workflow shape, so a full ``shaula author``/``research`` run completes with
    no network and no key — proving the engine + honesty gate end to end. Its
    output is honest by construction (it trips no banned-language rule); a test
    that needs the gate to FIRE passes its own banned-text lambda instead.
    """

    name = "stub"

    def __call__(self, system: str, user: str) -> str:
        s = (system or "").lower()
        if "workflow architect" in s:
            return self._workflow_json()
        if "skill pack" in s or "skill packs" in s:
            return self._skill_json()
        return self._research_brief(user)

    @staticmethod
    def _workflow_json() -> str:
        return json.dumps({
            "name": "research-brief-workflow",
            "description": "Draft an honest, sourced research brief for the practice.",
            "steps": [
                {"ref": "gather", "title": "Gather background",
                 "assignee": "strategist",
                 "description": "Collect publicly available background relevant to the request.",
                 "dependencies": [], "requires_review": False},
                {"ref": "draft", "title": "Write the brief",
                 "assignee": "blog",
                 "description": "Write a clear, plainly worded brief from the gathered background.",
                 "dependencies": ["gather"], "requires_review": False},
                {"ref": "review", "title": "Honesty review",
                 "assignee": "reviewer",
                 "description": "Check the brief against the house honesty rules before release.",
                 "dependencies": ["draft"], "requires_review": True},
            ],
        })

    @staticmethod
    def _skill_json() -> str:
        return json.dumps({
            "name": "honest-intake-summary",
            "description": "How to summarize an intake honestly without overclaiming.",
            "body": (
                "## When to use\nWhen summarizing a new client intake for the practice.\n\n"
                "## How to do it honestly\nState only what the intake records. Attribute "
                "every claim to its source. If a detail is unknown, say it is unknown.\n\n"
                "## What to refuse\nDo not infer outcomes, add encouragement that reads as "
                "a promise, or describe any approach as guaranteed."
            ),
        })

    @staticmethod
    def _research_brief(user: str) -> str:
        topic = "the requested topic"
        # Cheap topic echo so the stub output is recognizably about the ask,
        # while staying honest (no statistics, no efficacy language).
        for marker in ('on "', 'about "'):
            if marker in user:
                topic = user.split(marker, 1)[1].split('"', 1)[0] or topic
                break
        return (
            f"# Background brief: {topic}\n\n"
            "**Summary.** This is an honest, plainly worded background brief drawn from "
            "general knowledge only; it cites no source it cannot name.\n\n"
            "## Key points\n"
            "- A widely described consideration relevant to the topic [commonly described].\n"
            "- A point that would need a named source before it could be stated as fact "
            "[unverified].\n\n"
            "## Considerations to weigh\n"
            "- Framed as a consideration, not a recommendation; the licensed clinician decides.\n\n"
            "## Open questions\n- What specific sources should be verified before use?\n\n"
            "_Informational background only — not clinical advice._"
        )


# --------------------------------------------------------------------------- #
# Cloud providers — BYO key. Lazy httpx; raise BrainError on transport failure.
# --------------------------------------------------------------------------- #
class GoogleModel:
    """Google Gemini. BYO API key (``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``) via the
    Generative Language endpoint, or — when no key is set — Application Default
    Credentials against Vertex AI (the path the Shaula engine used in prod).
    """

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        project: Optional[str] = None,
        location: Optional[str] = None,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_output_tokens: int = _DEFAULT_MAX_TOKENS,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model or os.environ.get("SHAULA_GOOGLE_MODEL", DEFAULT_MODELS["google"])
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.project = project or os.environ.get("SHAULA_VERTEX_PROJECT")
        self.location = location or os.environ.get("SHAULA_VERTEX_LOCATION", "us-central1")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.name = "google"

    def __call__(self, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if self.api_key:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent?key={self.api_key}"
            )
            headers = {"content-type": "application/json"}
        else:
            # Vertex via ADC. Requires a Google Cloud project.
            if not self.project:
                raise BrainError(
                    "google_auth",
                    "no GEMINI_API_KEY/GOOGLE_API_KEY set and no SHAULA_VERTEX_PROJECT "
                    "for Application Default Credentials — set one of them",
                )
            token = self._adc_token()
            url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/projects/"
                f"{self.project}/locations/{self.location}/publishers/google/"
                f"models/{self.model}:generateContent"
            )
            headers = {"content-type": "application/json", "Authorization": f"Bearer {token}"}

        httpx = _require_httpx()
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise BrainError("google_network", str(exc)[:200]) from exc
        if resp.status_code != 200:
            raise BrainError("google_http", f"status {resp.status_code}")
        try:
            data = resp.json()
            text = "".join(
                p.get("text", "")
                for p in data["candidates"][0]["content"]["parts"]
            ).strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise BrainError("google_malformed", str(exc)[:200]) from exc
        if not text:
            raise BrainError("google_empty")
        return text

    @staticmethod
    def _adc_token() -> str:
        try:
            import google.auth  # noqa: PLC0415
            import google.auth.transport.requests  # noqa: PLC0415
        except ModuleNotFoundError as exc:
            raise BrainError(
                "missing_dep",
                "Vertex (ADC) mode needs google-auth — `pip install \"shaula[google]\"` "
                "or set GEMINI_API_KEY to use the API-key path instead",
            ) from exc
        try:
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            return creds.token or ""
        except Exception as exc:  # noqa: BLE001
            raise BrainError("google_auth", str(exc)[:200]) from exc


class AnthropicModel:
    """Anthropic Claude via the Messages API. BYO ``ANTHROPIC_API_KEY``."""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = _DEFAULT_TEMPERATURE,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model or os.environ.get("SHAULA_ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"])
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.name = "anthropic"

    def __call__(self, system: str, user: str) -> str:
        if not self.api_key:
            raise BrainError("anthropic_auth", "ANTHROPIC_API_KEY is not set")
        httpx = _require_httpx()
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=body, timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise BrainError("anthropic_network", str(exc)[:200]) from exc
        if resp.status_code != 200:
            raise BrainError("anthropic_http", f"status {resp.status_code}")
        try:
            data = resp.json()
            text = "".join(
                blk.get("text", "") for blk in data["content"] if blk.get("type") == "text"
            ).strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise BrainError("anthropic_malformed", str(exc)[:200]) from exc
        if not text:
            raise BrainError("anthropic_empty")
        return text


class OpenAIModel:
    """OpenAI GPT via Chat Completions. BYO ``OPENAI_API_KEY``."""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = _DEFAULT_TEMPERATURE,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model or os.environ.get("SHAULA_OPENAI_MODEL", DEFAULT_MODELS["openai"])
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.name = "openai"

    def __call__(self, system: str, user: str) -> str:
        if not self.api_key:
            raise BrainError("openai_auth", "OPENAI_API_KEY is not set")
        httpx = _require_httpx()
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        try:
            resp = httpx.post(
                self.base_url + "/chat/completions",
                headers=headers, json=body, timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise BrainError("openai_network", str(exc)[:200]) from exc
        if resp.status_code != 200:
            raise BrainError("openai_http", f"status {resp.status_code}")
        try:
            data = resp.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise BrainError("openai_malformed", str(exc)[:200]) from exc
        if not text:
            raise BrainError("openai_empty")
        return text


_ADAPTERS = {
    "google": GoogleModel,
    "anthropic": AnthropicModel,
    "openai": OpenAIModel,
    "stub": StubModel,
}


def resolve_model(
    provider: Optional[str] = None,
    *,
    model: Optional[str] = None,
    stub: bool = False,
) -> Model:
    """Return a ready ``Model`` callable for ``provider`` (or the configured one).

    Precedence: explicit ``--stub`` flag → explicit ``provider`` arg →
    ``SHAULA_PROVIDER`` env → ``~/.shaula`` config → ``"google"`` default.
    Construction never makes a network call; a missing key surfaces only when the
    model is invoked (so ``shaula providers`` can list everything safely).
    """
    if stub:
        return StubModel()
    if provider is None:
        provider = os.environ.get("SHAULA_PROVIDER")
    if provider is None:
        # Local import avoids a settings<->providers import cycle at module load.
        import settings  # noqa: PLC0415
        provider = settings.load().get("provider")
    provider = (provider or "google").lower()
    if provider not in _ADAPTERS:
        raise BrainError(
            "no_provider",
            f"unknown provider {provider!r}; choose one of {', '.join(_ADAPTERS)}",
        )
    adapter = _ADAPTERS[provider]
    return adapter(model) if provider != "stub" else adapter()
