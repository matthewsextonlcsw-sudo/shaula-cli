# Shaula workflows — the no-code workflow builder

Turn a small JSON **template** (a DAG of tasks, each assigned to one of the
vetted staff profiles) into a validated, honesty-linted, dependency-ordered
**task-graph**, then run it to a deliverable — fully in-process, no network, no
external services.

Two pure steps:

- **`builder.build_plan`** — load → validate → topo-sort → ordered task payloads.
- **`local_executor`** — run that plan against a pluggable model to a deliverable
  (the final step is always a human-review gate).

## The guardrails (the whole point)

A user-built workflow is **composition of vetted parts, never new blast radius**.
Four gates, all enforced in `builder.py`, all unit-tested with **zero network**:

1. **Assignee allow-list** — every step must target one of the vetted profiles
   (`VETTED_PROFILES`). An unknown assignee is rejected. You compose the existing
   staff; you cannot summon a new agent with new powers.
2. **PHI gate** — the PHI-touching profiles are refused unless the template sets
   `allow_phi: true` **and** the caller passes `--allow-phi`; and any PHI step
   must run in a caller-owned `dir:` workspace, never ephemeral scratch. Default
   is **no-PHI-only**.
3. **Honesty lint** — every template-authored string (post variable
   substitution) is run through the **same** linter that guards the site
   generator (`engine/generate.py:lint`). A banned claim — fabricated stats,
   "proven/guaranteed", "studies show", testimonials, "cure", "#1", … — aborts
   the build before anything runs. Each task body is then prefixed with the
   honesty + house-nothing preamble (trusted boilerplate, never itself linted).
4. **Acyclic** — dependencies form a DAG; a cycle, a dangling ref, or a duplicate
   ref is rejected up front (Kahn topological sort).

The domain logic (load / validate / topo-sort / plan) is pure stdlib and has no
I/O, so the entire guardrail surface is unit-testable with no network and no key.

## Template schema

```jsonc
{
  "name": "weekly-blog",                 // required
  "description": "…",
  "variables": ["topic", "project"],     // names that may appear as {token}s
  "allow_phi": false,                    // must be true to use a PHI profile
  "default_workspace_kind": "scratch",   // "scratch" | "dir"
  "default_workspace_path": null,        // required (a real dir) for PHI work
  "tenant": "cedar-sage",                // optional isolation key (stamped on every task)
  "steps": [
    {
      "ref": "brief",                    // required, unique within the template
      "title": "Blog brief: {topic}",    // required
      "assignee": "blog",                // required, must be a vetted profile
      "description": "…",                // becomes the task body (after the preamble)
      "dependencies": ["other_ref"],     // refs this step waits on (the DAG edges)
      "priority": "medium",              // low | medium | high | urgent
      "workspace_kind": "dir",           // optional per-step override of the default
      "workspace_path": "/Volumes/…",    // required if this step touches PHI
      "requires_review": true,           // appends a human-review note to the body
      "tags": ["geo"],                   // optional, recorded in the body footer
      "triage": true,                    // optional — flag for human approval before it runs
      "max_runtime_seconds": 600         // optional — per-task runtime cap (positive int)
    }
  ]
}
```

Each step becomes one task payload: `title`, `(preamble + description) → body`,
`assignee`, `priority → int (low0/med1/high2/urgent3)`, `workspace_kind/path`,
`dependencies → parents` (resolved parents-first in topo order), `tags`,
`triage`, `max_runtime_seconds`, and the template `tenant` (stamped on every
task). `build_plan` returns these in dependency order; `local_executor` runs
them.

## CLI

```bash
# Run a template to a deliverable (offline with the stub, or with a BYO key):
shaula workflow workflows/templates/weekly-blog.json \
    -v topic="Sleep and anxiety" -v project=cedar-sage --stub

# Drop --stub to use your configured provider; --allow-phi unlocks PHI profiles
# (the template must also set allow_phi: true).
```

`shaula author "<plain-language job>"` drafts a template + plan for you; `shaula
workflow <file>` runs an existing template. Both pass the honesty gate, and the
final step is always a human-review gate before anything is released.

## Adding a template

Drop a new `*.json` in `workflows/templates/`, keep every assignee in the vetted
profiles, keep claims honest (the linter will catch you), and prefer an explicit
`reviewer` step for anything that gets published or sent. Reference templates
ship in `workflows/templates/` (e.g. `weekly-blog.json`, `growth-engine.json`,
`distribution-engine.json`).

## Tests

The builder's guardrails are exercised by the top-level suite (`pytest` at the
repo root) — the assignee allow-list, the PHI gate, honesty lint (pre- and
post-substitution), cycle / dangling / duplicate rejection, variable
substitution, priority mapping, and preamble injection — all offline, no key.
