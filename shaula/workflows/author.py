#!/usr/bin/env python3
"""author — therapist self-serve workflow authoring (plain language -> kanban + skill).

The therapist describes a job in their own words; Shaula drafts a WorkflowTemplate
whose steps are assigned ONLY to vetted office staff, runs it through the SAME
guardrails the hand-authored templates pass (``workflows.builder.validate`` —
assignee allow-list + PHI gate + honesty lint + acyclic DAG), and hands back a
kanban task-graph (``build_plan``) for the therapist to review and approve. It can
also draft a reusable SKILL pack — honest guidance CONTENT attached to a vetted
profile — for the job.

THE LINE WE DO NOT CROSS (builder.py's invariant, kept verbatim):
  Therapists COMPOSE vetted staff and author honest CONTENT. They CANNOT mint a new
  agent with new tools or powers. A drafted workflow is a PROPOSAL — a non-vetted
  assignee is REJECTED by validate(), never executed, and the workflow runs only
  after a human approval gate. A drafted skill is guidance text run through the real
  honesty gate — never a new capability with filesystem / network / tool access.

The generation model is pluggable (BYO key — Google / Anthropic / OpenAI — or the
offline ``--stub``). The model is UNTRUSTED — every byte it returns is validated by
builder.validate and the honesty gate before it can become a task or a skill. Pure
stdlib, no new deps.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Callable, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from workflows.builder import (  # noqa: E402
    PHI_PROFILES,
    VETTED_PROFILES,
    PlannedTask,
    WorkflowError,
    WorkflowTemplate,
    build_plan,
    load_template,
    validate,
)
from gate import BrainError, lint_gate  # noqa: E402 — the real honesty gate (svc-free)

Model = Callable[[str, str], str]

# The therapist composes the no-PHI office staff. PHI profiles live behind the
# EMR perimeter and are never offered to a self-serve author (build_plan would
# reject them anyway; constraining the generator just avoids wasted repairs).
AUTHORABLE_PROFILES: list[str] = sorted(VETTED_PROFILES - PHI_PROFILES)


class AuthoringError(ValueError):
    """A therapist-described workflow could not be turned into a vetted, honest
    task-graph (carries the specific guardrail violations for the UI)."""

    def __init__(self, message: str, violations: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.violations = violations or []


# --------------------------------------------------------------------------- #
# JSON extraction — the model is untrusted; never eval, only parse.
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ``` fences and
    surrounding prose). Raises AuthoringError if there is no parseable object."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise AuthoringError("model returned no JSON object")
    try:
        # strict=False: models routinely emit raw newlines/tabs inside string
        # values (a markdown body), which strict JSON forbids. Tolerate them.
        data = json.loads(s[start : end + 1], strict=False)
    except json.JSONDecodeError as exc:
        raise AuthoringError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthoringError("model JSON was not an object")
    return data


# --------------------------------------------------------------------------- #
# Workflow drafting
# --------------------------------------------------------------------------- #
_WF_SYSTEM = (
    "You are Shaula's workflow architect. You turn a therapist's plain-language "
    "request into a small, honest office workflow — a short chain of tasks, each "
    "assigned to one vetted staff member. Output ONLY a JSON object, no prose."
)


def _wf_prompt(description: str, project: str, extra: str = "") -> str:
    profiles = ", ".join(AUTHORABLE_PROFILES)
    return (
        f'Therapist request: "{description}"\n'
        f"Practice: {project}\n\n"
        "Return ONLY this JSON shape:\n"
        '{"name": "kebab-case-name", "description": "one honest sentence", '
        '"steps": [{"ref": "short_id", "title": "...", "assignee": "<profile>", '
        '"description": "what this staff member does", '
        '"dependencies": ["earlier_ref"], "requires_review": false}]}\n\n'
        "Hard rules:\n"
        f"- assignee MUST be one of: {profiles}. Use no other name.\n"
        "- 2 to 5 steps. Each ref unique. dependencies reference earlier refs only.\n"
        "- The FINAL step MUST be assignee \"reviewer\" with requires_review true "
        "(the honesty gate before anything reaches the clinician).\n"
        "- Write concrete titles/descriptions — NO {curly} placeholders.\n"
        "- HONEST ONLY: no fabricated statistics, no 'proven/guaranteed/clinically "
        "proven', no 'studies show', no testimonials, no 'cure/miracle', no "
        "'#1/best/world-class'. The office houses no PHI.\n"
        + (f"\nYour previous attempt failed validation:\n{extra}\nFix every issue." if extra else "")
    )


def draft_workflow(
    description: str,
    project: str,
    model: Model,
    *,
    max_repair: int = 1,
) -> WorkflowTemplate:
    """Plain-language request -> a VALIDATED WorkflowTemplate (vetted assignees,
    honest copy, acyclic). Retries up to ``max_repair`` times by feeding the
    guardrail violations back to the model. Raises AuthoringError if it still
    cannot produce a workflow that passes every guardrail — the safety wall."""
    last: Optional[Exception] = None
    extra = ""
    for _ in range(max_repair + 1):
        raw = model(_WF_SYSTEM, _wf_prompt(description, project, extra))
        try:
            tmpl = load_template(_extract_json(raw))
            validate(tmpl, allow_phi=False)  # assignee allow-list + PHI + honesty + DAG
            return tmpl
        except WorkflowError as exc:
            last = exc
            extra = "; ".join(exc.violations or [str(exc)])
        except AuthoringError as exc:
            last = exc
            extra = str(exc)
    raise AuthoringError(
        f"could not draft a valid workflow after {max_repair + 1} attempts: {last}",
        violations=getattr(last, "violations", []) or [str(last)],
    )


def author_to_plan(
    description: str,
    project: str,
    model: Model,
) -> tuple[WorkflowTemplate, list[PlannedTask]]:
    """Draft + plan in one call: returns the validated template and its
    ordered task-graph (the steps local_executor runs)."""
    tmpl = draft_workflow(description, project, model)
    return tmpl, build_plan(tmpl, {}, allow_phi=False)


# --------------------------------------------------------------------------- #
# Skill drafting — honest guidance CONTENT, never a new capability
# --------------------------------------------------------------------------- #
_SKILL_SYSTEM = (
    "You write Shaula SKILL packs: short, honest guidance a vetted staff member "
    "follows. A skill is CONTENT, never a new tool or power. Output ONLY JSON."
)


def _skill_prompt(purpose: str, project: str) -> str:
    return (
        f'Skill purpose: "{purpose}"\nPractice: {project}\n\n'
        'Return ONLY: {"name": "kebab-case", "description": "one sentence", '
        '"body": "markdown guidance: when to use, how to do it honestly, what to '
        'refuse"}\n\n'
        "HONEST ONLY: no fabricated statistics, no 'proven/guaranteed', no 'studies "
        "show', no testimonials, no 'cure/miracle', no '#1/best'. Name no client "
        "data. The skill guides a vetted staff member; it grants no new powers."
    )


def draft_skill(purpose: str, project: str, model: Model) -> dict:
    """Draft a SKILL pack and run its human-facing content through the REAL honesty
    gate. Raises BrainError('honesty') if the model smuggled a banned claim —
    never auto-repaired, exactly like every other Shaula output."""
    data = _extract_json(model(_SKILL_SYSTEM, _skill_prompt(purpose, project)))
    name = re.sub(r"[^a-z0-9-]+", "-", str(data.get("name", "")).lower()).strip("-")[:48]
    desc = str(data.get("description", "")).strip()[:300]
    body = str(data.get("body", "")).strip()
    if not name or not body:
        raise AuthoringError("skill draft missing name or body")
    lint_gate(desc + "\n\n" + body)  # the moat — raises BrainError on a banned claim
    return {"name": name, "description": desc, "body": body}
