"""Shaula workflows — no-code template → validated, ordered task-graph.

Public surface:
  load_template / load_template_file  — dict|file → WorkflowTemplate
  validate                            — guardrail check (raises WorkflowError)
  build_plan                          — ordered, network-free task payloads
  VETTED_PROFILES / PHI_PROFILES      — the allow-list + PHI gate
  WorkflowError                       — carries `.violations`

Building a plan is pure and network-free; running it is the local executor's
job (``workflows.local_executor``).
"""

from .builder import (  # noqa: F401
    HONESTY_PREAMBLE,
    PHI_PROFILES,
    PRIORITY_MAP,
    VETTED_PROFILES,
    BoardSpec,
    PlannedTask,
    WorkflowError,
    WorkflowStep,
    WorkflowTemplate,
    build_plan,
    load_template,
    load_template_file,
    topo_sort,
    validate,
)

__all__ = [
    "HONESTY_PREAMBLE",
    "PHI_PROFILES",
    "PRIORITY_MAP",
    "VETTED_PROFILES",
    "BoardSpec",
    "PlannedTask",
    "WorkflowError",
    "WorkflowStep",
    "WorkflowTemplate",
    "build_plan",
    "load_template",
    "load_template_file",
    "topo_sort",
    "validate",
]
