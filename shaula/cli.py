"""cli — the ``shaula`` command-line entrypoint.

    shaula author    "<request>"  [--project P] [--provider G] [--model M] [--stub]
    shaula research  "<topic>"    [--project P] [--provider G] [--model M] [--stub]
    shaula workflow  <template.json> [-v k=val ...] [--allow-phi] [--stub]
    shaula setup
    shaula providers
    shaula doctor
    shaula version

``--stub`` runs fully offline with no key (proofs / CI). Every deliverable passes
the SAME honesty gate; a banned claim parks the run instead of shipping. The CLI
imports the shaula package first, so the path bootstrap is in place before the
engine/workflow modules load.
"""

from __future__ import annotations

import argparse
import sys

import shaula  # noqa: F401 — triggers the path bootstrap before the imports below

import providers
import settings
import honesty
from gate import BrainError


def _model(args) -> "providers.Model":
    return providers.resolve_model(
        getattr(args, "provider", None),
        model=getattr(args, "model", None),
        stub=getattr(args, "stub", False),
    )


def _narrate_brain_error(exc: BrainError) -> int:
    """Print an honesty refusal (the moat working) or a transport error, and
    return the process exit code."""
    if exc.category == "honesty":
        print("\n⛔ Honesty gate stopped this draft before it shipped.", file=sys.stderr)
        print(honesty.refusal_message(len(exc.explanations or [])), file=sys.stderr)
        for r in (exc.explanations or []):
            quote = (r.get("quote") or "").strip()
            line = f"   • {r.get('plain', 'a banned claim style')}"
            if quote:
                line += f'  — “{quote}”'
            print(line, file=sys.stderr)
        return 3
    print(f"\n✗ model/transport error [{exc.category}]: {exc.detail}", file=sys.stderr)
    return 4


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_author(args) -> int:
    from workflows.author import author_to_plan

    tmpl, plan = author_to_plan(args.request, args.project, _model(args))
    print(f"✓ workflow “{tmpl.name}” — {tmpl.description}")
    print(f"  {len(plan)} vetted step(s), honesty-gated, DAG-ordered:\n")
    for task in plan:
        p = task.payload
        deps = ", ".join(task.dep_refs) if task.dep_refs else "—"
        gate = "  ⟢ human review gate" if (p.get("triage") or p.get("assignee") == "reviewer") else ""
        print(f"  [{task.ref}] {p.get('title','')}")
        print(f"       assignee={p.get('assignee','')}  deps={deps}{gate}")
    print("\n(Every step's authored copy already passed the honesty linter. The final "
          "review is a human gate before anything is released.)")
    return 0


def cmd_research(args) -> int:
    from workflows.local_executor import one_call_baseline

    brief = one_call_baseline(args.topic, args.project, _model(args))
    print(brief)
    return 0


def cmd_workflow(args) -> int:
    from workflows.local_executor import run_template_file

    variables = {}
    for pair in args.var or []:
        if "=" not in pair:
            print(f"✗ bad -v {pair!r}; expected name=value", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        variables[k.strip()] = v
    run = run_template_file(args.template, variables, _model(args), allow_phi=args.allow_phi)
    print(f"✓ ran “{run.template}” → status={run.status} ({run.seconds:.2f}s)")
    for s in run.steps:
        print(f"  [{s.ref}] {s.title}  ({s.assignee}) → {s.status}")
    if run.status == "honesty_failed":
        print("\n⛔ A step tripped the honesty gate — the run parked (the moat working).",
              file=sys.stderr)
        for r in (run.honesty or {}).get("reasons", []):
            print(f"   • {r.get('plain','a banned claim style')}", file=sys.stderr)
        return 3
    if run.deliverable:
        print("\n--- deliverable (pre-human-review) ---\n")
        print(run.deliverable)
    if run.review_reason:
        print(f"\n⟢ parked for human review: {run.review_reason}")
    return 0


def cmd_setup(args) -> int:
    import setup_wizard
    setup_wizard.run()
    return 0


def cmd_providers(args) -> int:
    import os
    cfg = settings.load()
    chosen = cfg.get("provider") or "(unset → defaults to google)"
    print(f"configured provider: {chosen}   model: {cfg.get('model') or '(provider default)'}\n")
    key_env = {"google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
               "anthropic": ("ANTHROPIC_API_KEY",), "openai": ("OPENAI_API_KEY",)}
    for pid, label in providers.PROVIDERS.items():
        if pid == "stub":
            print(f"  {pid:9s} ready (offline, no key)        {label}")
            continue
        present = any(os.environ.get(v) for v in key_env.get(pid, ()))
        mark = "key ✓" if present else "no key"
        print(f"  {pid:9s} {mark:24s} {label}")
    print("\nBYO key: set the env var (or `shaula setup` to store one 0600 in ~/.shaula/.env).")
    return 0


def cmd_doctor(args) -> int:
    import os
    ok = True
    print("shaula doctor\n")
    print(f"  python           {sys.version.split()[0]}")
    print(f"  shaula           {shaula.__version__}")
    print(f"  config dir       {settings.home()}  "
          f"({'exists' if settings.home().exists() else 'not created yet'})")

    # Offline honesty-gate self-test — the moat must hold with zero network.
    from gate import lint_gate
    try:
        lint_gate("We offer compassionate, evidence-informed therapy.")
        gate_clean = True
    except BrainError:
        gate_clean = False
    gate_blocks = False
    try:
        lint_gate("Our therapy is clinically proven to cure anxiety.")
    except BrainError as e:
        gate_blocks = e.category == "honesty"
    gate_ok = gate_clean and gate_blocks
    ok = ok and gate_ok
    print(f"  honesty gate     {'✓ passes clean / blocks banned' if gate_ok else '✗ FAILED self-test'}")

    keys = {"GEMINI_API_KEY": "google", "GOOGLE_API_KEY": "google",
            "ANTHROPIC_API_KEY": "anthropic", "OPENAI_API_KEY": "openai"}
    present = sorted({prov for env, prov in keys.items() if os.environ.get(env)})
    print(f"  provider keys    {', '.join(present) if present else 'none set (use --stub, or shaula setup)'}")
    print(f"\n{'✓ healthy' if ok else '✗ problems found'} — offline runs work via --stub.")
    return 0 if ok else 1


def cmd_version(args) -> int:
    print(f"shaula {shaula.__version__}")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="shaula",
        description="shaula — a downloadable, honesty-gated research & workflow agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="store_true", help="print version and exit")
    sub = ap.add_subparsers(dest="cmd")

    def _model_flags(sp):
        sp.add_argument("--provider", choices=["google", "anthropic", "openai", "stub"],
                        help="override the configured provider")
        sp.add_argument("--model", help="override the model id")
        sp.add_argument("--stub", action="store_true",
                        help="run offline with the deterministic stub (no key, no network)")

    sp = sub.add_parser("author", help="draft a vetted, honesty-gated office workflow")
    sp.add_argument("request", help="plain-language description of the job")
    sp.add_argument("--project", default="your practice", help="practice / project name")
    _model_flags(sp)
    sp.set_defaults(func=cmd_author)

    sp = sub.add_parser("research", help="draft an honest, sourced background brief")
    sp.add_argument("topic", help="the topic to brief")
    sp.add_argument("--project", default="your practice", help="practice / project name")
    _model_flags(sp)
    sp.set_defaults(func=cmd_research)

    sp = sub.add_parser("workflow", help="run a workflow template file to a deliverable")
    sp.add_argument("template", help="path to a workflow template JSON")
    sp.add_argument("-v", "--var", action="append", default=[], help="variable name=value (repeatable)")
    sp.add_argument("--allow-phi", action="store_true", help="unlock PHI profiles (template must opt in too)")
    _model_flags(sp)
    sp.set_defaults(func=cmd_workflow)

    sub.add_parser("setup", help="first-run setup: provider + BAA disclosure").set_defaults(func=cmd_setup)
    sub.add_parser("providers", help="list providers and key status").set_defaults(func=cmd_providers)
    sub.add_parser("doctor", help="environment + offline honesty-gate self-test").set_defaults(func=cmd_doctor)
    sub.add_parser("version", help="print version").set_defaults(func=cmd_version)
    return ap


def main(argv=None) -> int:
    settings.load_env()  # populate provider keys from ~/.shaula/.env if present
    ap = build_parser()
    args = ap.parse_args(argv)
    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    try:
        return args.func(args)
    except BrainError as exc:
        return _narrate_brain_error(exc)
    except FileNotFoundError as exc:
        print(f"✗ file not found: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
