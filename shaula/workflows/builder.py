#!/usr/bin/env python3
"""Shaula workflow builder — a JSON template → a validated, ordered task-graph.

The no-code workflow layer. A user (or Shaula acting on their behalf) describes a
multi-step job as a small JSON template — a DAG of tasks, each assigned to one of
the vetted staff profiles — and this module turns it into an ordered, honesty-
linted task-graph (``build_plan``) that the local executor then runs.

It ports quentintou/agent-board's template→task mechanism (MIT) into a pure,
network-free builder: load → validate → topo-sort → plan.

The guardrails are the whole point. A user-built workflow is *composition* of
vetted parts, never new blast radius:

  1. ASSIGNEE ALLOW-LIST — every step must target one of the vetted profiles
     (VETTED_PROFILES). An unknown assignee is rejected. Users compose the
     existing staff; they cannot summon a new agent with new powers.
  2. PHI GATE — the PHI-touching profiles are refused unless the template
     explicitly opts in (`allow_phi: true`) AND the caller passes allow_phi=True;
     and any PHI step must run in the caller's own `dir:` workspace, never
     ephemeral scratch. Default is no-PHI-only.
  3. HONESTY LINT — every template-authored string (post-variable-substitution)
     is run through the SAME linter that guards the site generator
     (engine/generate.py:lint). A banned claim — fabricated stats, "proven/
     guaranteed", "studies show", testimonials, "cure", "#1", … — aborts the
     build before anything runs. Each task body is then prefixed with the
     honesty + house-nothing preamble (trusted boilerplate, itself never linted).
  4. ACYCLIC — dependencies form a DAG; a cycle, a dangling ref, or a duplicate
     ref is rejected up front (Kahn topological sort).

Scope: load the template, enforce the guardrails, and produce an ordered
task-graph (``build_plan``). Per step it covers every safe task field, incl.
``triage`` (human approval before running) and ``max_runtime_seconds`` (a
per-task runtime cap), plus a template-level ``tenant`` (per-caller isolation).
Running the resulting plan is the local executor's job, not this module's.

Architecture: pure-stdlib, zero network — load / validate / topo-sort / plan, so
the entire guardrail surface is unit-testable with no I/O.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

# Import the ONE honesty linter (single source of truth). engine/generate.py
# self-bootstraps its own sibling import (citations) on import, and is guarded
# by `if __name__ == "__main__"`, so importing it here is side-effect-safe.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from engine.generate import lint as _honesty_lint  # noqa: E402


# --------------------------------------------------------------------------- #
# Vetted ground truth (verified against profiles/ + docs/HARNESS.md). The
# strategist + distributor content-engine roles (OpenGrowth growth-engine /
# distribution-engine) added 2026-06-07.
# --------------------------------------------------------------------------- #
VETTED_PROFILES: frozenset[str] = frozenset({
    "analytics", "biller", "blog", "clinical-admin", "customer-service",
    "distributor", "frontdesk", "marketer", "orchestrator", "reviewer",
    "sarah", "scribe", "strategist", "website", "workspace",
})

# The six profiles that may touch PHI (HARNESS.md staff table). Work assigned to
# any of these is gated: explicit opt-in + a practice-owned dir workspace.
PHI_PROFILES: frozenset[str] = frozenset({
    "workspace", "frontdesk", "customer-service", "scribe", "biller",
    "clinical-admin",
})

# agent-board uses string priorities; the task body's priority is an int.
PRIORITY_MAP: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "urgent": 3}

# Prepended to every emitted task body. TRUSTED boilerplate — deliberately NOT
# run through the honesty linter (it names the banned phrases as negatives).
HONESTY_PREAMBLE: str = (
    "[SHAULA HOUSE RULES — non-negotiable]\n"
    "- Honesty engine: no fabricated statistics or percentages; no "
    '"proven / guaranteed / clinically proven"; no "studies show / research '
    'proves"; no invented testimonials; no "cure / miracle"; no '
    '"#1 / best therapist / world-class". If you lack a real source, say so '
    "and omit the claim.\n"
    "- House-nothing: store no PHI outside the practice's own Google. This "
    "office houses nothing.\n"
    "- Run the office, not the therapy: never handle a clinical crisis; defer "
    "every clinical decision to the licensed clinician.\n"
    "\n---\n\n"
)

_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class WorkflowError(ValueError):
    """Raised on any template / instantiation guardrail violation.

    Carries an optional list of individual `violations` so callers (CLI, UI)
    can show every problem at once rather than one-at-a-time.
    """

    def __init__(self, message: str, violations: Optional[list[str]] = None):
        super().__init__(message)
        self.violations = violations or []


# --------------------------------------------------------------------------- #
# Domain model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorkflowStep:
    ref: str
    title: str
    assignee: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    priority: str = "medium"
    skills: tuple[str, ...] = ()
    workspace_kind: Optional[str] = None       # overrides the template default
    workspace_path: Optional[str] = None
    requires_review: bool = False
    tags: tuple[str, ...] = ()
    triage: bool = False                        # land in triage (human-gate) first
    max_runtime_seconds: Optional[int] = None   # per-task runtime cap


@dataclass(frozen=True)
class BoardSpec:
    """A kanban board this workflow lives on. `slug` is the directory key;
    the rest is display metadata. POST /boards is idempotent on slug."""
    slug: str
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


@dataclass(frozen=True)
class WorkflowTemplate:
    name: str
    description: str
    steps: tuple[WorkflowStep, ...]
    variables: tuple[str, ...] = ()            # declared variable names
    allow_phi: bool = False
    default_workspace_kind: str = "scratch"
    default_workspace_path: Optional[str] = None
    tenant: Optional[str] = None               # per-practice isolation key
    board: Optional[BoardSpec] = None          # the board to create/target


# --------------------------------------------------------------------------- #
# Loading (dict → dataclass). Strict: unknown shapes fail loudly.
# --------------------------------------------------------------------------- #
def _as_str_tuple(value: Any, fieldname: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise WorkflowError(f"{fieldname} must be a list of strings")
    return tuple(value)


def load_template(data: dict) -> WorkflowTemplate:
    """Parse a JSON-loaded dict into a WorkflowTemplate. Raises WorkflowError."""
    if not isinstance(data, dict):
        raise WorkflowError("template must be a JSON object")
    for required in ("name", "steps"):
        if required not in data:
            raise WorkflowError(f"template missing required field: {required!r}")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowError("template.steps must be a non-empty list")

    steps: list[WorkflowStep] = []
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            raise WorkflowError(f"step[{i}] must be an object")
        for required in ("ref", "title", "assignee"):
            if not s.get(required):
                raise WorkflowError(f"step[{i}] missing required field: {required!r}")
        steps.append(WorkflowStep(
            ref=s["ref"],
            title=s["title"],
            assignee=s["assignee"],
            description=s.get("description", ""),
            dependencies=_as_str_tuple(s.get("dependencies"), f"step[{i}].dependencies"),
            priority=s.get("priority", "medium"),
            skills=_as_str_tuple(s.get("skills"), f"step[{i}].skills"),
            workspace_kind=s.get("workspace_kind"),
            workspace_path=s.get("workspace_path"),
            requires_review=bool(s.get("requires_review", False)),
            tags=_as_str_tuple(s.get("tags"), f"step[{i}].tags"),
            triage=bool(s.get("triage", False)),
            max_runtime_seconds=s.get("max_runtime_seconds"),
        ))

    raw_board = data.get("board")
    board: Optional[BoardSpec] = None
    if raw_board is not None:
        if not isinstance(raw_board, dict) or not raw_board.get("slug"):
            raise WorkflowError("template.board must be an object with a 'slug'")
        board = BoardSpec(
            slug=raw_board["slug"],
            name=raw_board.get("name"),
            description=raw_board.get("description"),
            icon=raw_board.get("icon"),
            color=raw_board.get("color"),
        )

    tenant = data.get("tenant")
    if tenant is not None and not isinstance(tenant, str):
        raise WorkflowError("template.tenant must be a string")

    return WorkflowTemplate(
        name=data["name"],
        description=data.get("description", ""),
        steps=tuple(steps),
        variables=_as_str_tuple(data.get("variables"), "template.variables"),
        allow_phi=bool(data.get("allow_phi", False)),
        default_workspace_kind=data.get("default_workspace_kind", "scratch"),
        default_workspace_path=data.get("default_workspace_path"),
        tenant=tenant,
        board=board,
    )


def load_template_file(path: str) -> WorkflowTemplate:
    with open(path, encoding="utf-8") as fh:
        return load_template(json.load(fh))


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _effective_workspace(step: WorkflowStep, tmpl: WorkflowTemplate) -> tuple[str, Optional[str]]:
    kind = step.workspace_kind or tmpl.default_workspace_kind
    path = step.workspace_path or tmpl.default_workspace_path
    return kind, path


def topo_sort(steps: tuple[WorkflowStep, ...]) -> list[WorkflowStep]:
    """Kahn topological sort. Deterministic: preserves input order among ready
    nodes. Raises WorkflowError on a cycle (reporting the stuck refs)."""
    by_ref = {s.ref: s for s in steps}
    indeg = {s.ref: 0 for s in steps}
    children: dict[str, list[str]] = {s.ref: [] for s in steps}
    for s in steps:
        for dep in s.dependencies:
            if dep not in by_ref:
                continue  # dangling ref — validate() reports it; not a cycle
            indeg[s.ref] += 1
            children[dep].append(s.ref)

    ready = [s.ref for s in steps if indeg[s.ref] == 0]  # input order
    order: list[str] = []
    while ready:
        ref = ready.pop(0)
        order.append(ref)
        for child in children[ref]:
            indeg[child] -= 1
            if indeg[child] == 0:
                ready.append(child)

    if len(order) != len(steps):
        stuck = sorted(r for r in indeg if r not in order)
        raise WorkflowError(
            "dependency cycle detected among steps: " + ", ".join(stuck),
            violations=[f"cycle involves: {', '.join(stuck)}"],
        )
    return [by_ref[r] for r in order]


def _substitute(text: str, variables: dict[str, str], unknown: set[str]) -> str:
    """Replace {tokens} from `variables`; record any unknown token name."""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in variables:
            return str(variables[name])
        unknown.add(name)
        return m.group(0)
    return _TOKEN_RE.sub(repl, text)


# --------------------------------------------------------------------------- #
# Validation — every guardrail, all violations collected
# --------------------------------------------------------------------------- #
def validate(tmpl: WorkflowTemplate, *, allow_phi: bool = False) -> None:
    """Structural + policy validation (no variable substitution, no network).
    Raises WorkflowError listing every violation found."""
    v: list[str] = []

    # Unique refs.
    seen: set[str] = set()
    for s in tmpl.steps:
        if s.ref in seen:
            v.append(f"duplicate step ref: {s.ref!r}")
        seen.add(s.ref)

    # Assignee allow-list.
    for s in tmpl.steps:
        if s.assignee not in VETTED_PROFILES:
            v.append(
                f"step {s.ref!r}: assignee {s.assignee!r} is not a vetted "
                f"profile (allowed: {', '.join(sorted(VETTED_PROFILES))})"
            )

    # Priority vocabulary.
    for s in tmpl.steps:
        if s.priority not in PRIORITY_MAP:
            v.append(
                f"step {s.ref!r}: priority {s.priority!r} invalid "
                f"(use one of {', '.join(PRIORITY_MAP)})"
            )

    # Runtime cap, if set, must be a positive integer.
    for s in tmpl.steps:
        mrs = s.max_runtime_seconds
        if mrs is not None and (not isinstance(mrs, int) or isinstance(mrs, bool) or mrs <= 0):
            v.append(
                f"step {s.ref!r}: max_runtime_seconds must be a positive integer "
                f"(got {mrs!r})"
            )

    # Dependency refs must exist.
    for s in tmpl.steps:
        for dep in s.dependencies:
            if dep not in seen:
                v.append(f"step {s.ref!r}: depends on unknown ref {dep!r}")

    # PHI gate.
    phi_steps = [s for s in tmpl.steps if s.assignee in PHI_PROFILES]
    if phi_steps:
        if not (tmpl.allow_phi and allow_phi):
            names = ", ".join(f"{s.ref}→{s.assignee}" for s in phi_steps)
            v.append(
                "PHI-touching steps present (" + names + ") but PHI is not "
                "enabled. A PHI workflow requires `allow_phi: true` in the "
                "template AND allow_phi=True at instantiation."
            )
        for s in phi_steps:
            kind, path = _effective_workspace(s, tmpl)
            if kind != "dir" or not path:
                v.append(
                    f"step {s.ref!r} ({s.assignee}) handles PHI and must run in "
                    "a practice-owned dir workspace (workspace_kind=\"dir\" + "
                    "workspace_path), never ephemeral scratch."
                )

    # Honesty lint on raw authored strings (fast pre-substitution pass; the
    # authoritative post-substitution lint runs in build_plan).
    for s in tmpl.steps:
        for label, text in (("title", s.title), ("description", s.description)):
            hits = _honesty_lint(text)
            if hits:
                v.append(f"step {s.ref!r} {label}: banned language {hits}")

    # Cycle / dangling structure (only meaningful once refs validated).
    try:
        topo_sort(tmpl.steps)
    except WorkflowError as e:
        v.extend(e.violations or [str(e)])

    if v:
        raise WorkflowError(
            f"template {tmpl.name!r} failed validation ({len(v)} issue(s))",
            violations=v,
        )


# --------------------------------------------------------------------------- #
# Planning — template (+ variables) → ordered, network-free task payloads
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlannedTask:
    ref: str
    dep_refs: tuple[str, ...]
    payload: dict[str, Any]          # CreateTaskBody-shaped, minus `parents`


def build_plan(
    tmpl: WorkflowTemplate,
    variables: Optional[dict[str, str]] = None,
    *,
    allow_phi: bool = False,
    instance_key: Optional[str] = None,
) -> list[PlannedTask]:
    """Validate, substitute variables, topo-sort, and produce the ordered list
    of task payloads. `parents` is intentionally absent — the emitter resolves
    dep refs to real ids at create time (parents-first, guaranteed by order)."""
    variables = variables or {}
    validate(tmpl, allow_phi=allow_phi)

    # All declared variables must be supplied.
    missing = [name for name in tmpl.variables if name not in variables]
    if missing:
        raise WorkflowError(
            f"missing required variable(s): {', '.join(missing)}",
            violations=[f"variable {m!r} not provided" for m in missing],
        )

    unknown: set[str] = set()
    ordered = topo_sort(tmpl.steps)
    plan: list[PlannedTask] = []
    lint_hits: list[str] = []

    for s in ordered:
        title = _substitute(s.title, variables, unknown)
        desc = _substitute(s.description, variables, unknown)

        # Authoritative honesty lint on the FINAL authored strings (post
        # substitution — a variable could smuggle in a banned claim). The
        # trusted preamble is added AFTER linting and is never itself linted.
        for label, text in (("title", title), ("description", desc)):
            hits = _honesty_lint(text)
            if hits:
                lint_hits.append(f"step {s.ref!r} {label}: banned language {hits}")

        body_parts = [desc] if desc else []
        if s.requires_review:
            body_parts.append(
                "[REQUIRES HUMAN REVIEW — do not publish or send this output "
                "until the licensed clinician (or a human reviewer) approves it.]"
            )
        if s.tags:
            body_parts.append(f"[tags: {', '.join(s.tags)}]")
        authored = "\n\n".join(body_parts).strip()
        body = HONESTY_PREAMBLE + authored if authored else HONESTY_PREAMBLE.rstrip()

        kind, path = _effective_workspace(s, tmpl)
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "assignee": s.assignee,
            "priority": PRIORITY_MAP[s.priority],
            "workspace_kind": kind,
        }
        if path:
            payload["workspace_path"] = path
        if s.skills:
            payload["skills"] = list(s.skills)
        if s.triage:
            payload["triage"] = True
        if s.max_runtime_seconds:
            payload["max_runtime_seconds"] = s.max_runtime_seconds
        if tmpl.tenant:
            payload["tenant"] = tmpl.tenant
        if instance_key:
            payload["idempotency_key"] = f"{instance_key}:{s.ref}"

        plan.append(PlannedTask(ref=s.ref, dep_refs=s.dependencies, payload=payload))

    problems: list[str] = []
    if unknown:
        problems.extend(f"unknown variable token {{{u}}}" for u in sorted(unknown))
    problems.extend(lint_hits)
    if problems:
        raise WorkflowError(
            f"template {tmpl.name!r} failed at plan time ({len(problems)} issue(s))",
            violations=problems,
        )
    return plan

