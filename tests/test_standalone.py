"""End-to-end, no network: the seeded engine + honesty gate run to completion on
the offline stub, AND the moat fires through the real workflow path when a model
emits a banned claim. This is the P0 acceptance proof in test form."""

from __future__ import annotations

import pytest

import providers
from gate import BrainError
from workflows.author import author_to_plan
from workflows.local_executor import one_call_baseline


# A model is just (system, user) -> text; these stand in for a live provider.
def clean_blog_model(system, user):
    return (
        "# Weekly blog\n\nA plainly worded post drawn from general knowledge, "
        "with each claim tagged [established] or [commonly described]. No statistics "
        "are invented and no source is named that cannot be verified."
    )


def banned_model(system, user):
    return "Our approach is clinically proven to cure anxiety — studies show 95% success."


def test_author_to_plan_returns_a_vetted_gated_graph():
    tmpl, plan = author_to_plan("draft a weekly blog workflow", "Acme Therapy", providers.StubModel())
    assert tmpl.name and tmpl.description
    assert len(plan) >= 2
    # Every assignee is a vetted office profile (the safety wall).
    from workflows.builder import VETTED_PROFILES
    for task in plan:
        assert task.payload.get("assignee") in VETTED_PROFILES
    # The final step is the human review gate.
    last = plan[-1]
    assert last.payload.get("assignee") == "reviewer"


def test_one_call_baseline_clean_passes_the_gate():
    brief = one_call_baseline("sleep hygiene basics", "Acme Therapy", clean_blog_model)
    assert "Weekly blog" in brief or "general knowledge" in brief


def test_moat_fires_through_the_workflow_path():
    # The gate is applied by the workflow layer on the model's real output —
    # a banned claim parks the run, it is NEVER auto-repaired or shipped.
    with pytest.raises(BrainError) as exc:
        one_call_baseline("anything", "Acme Therapy", banned_model)
    assert exc.value.category == "honesty"


def test_execute_plan_parks_a_banned_step():
    from workflows.builder import build_plan
    from workflows.local_executor import execute_plan

    tmpl, _ = author_to_plan("draft a weekly blog workflow", "Acme", providers.StubModel())
    plan = build_plan(tmpl, {}, allow_phi=False)
    run = execute_plan(plan, banned_model, template_name=tmpl.name)
    # Either the run parks at the human review (stub graph) or trips honesty on a
    # generated step — both are safe terminal states, neither ships a banned claim.
    assert run.status in ("honesty_failed", "needs_review")
    assert all(s.status != "done" or "clinically proven" not in s.output for s in run.steps)
