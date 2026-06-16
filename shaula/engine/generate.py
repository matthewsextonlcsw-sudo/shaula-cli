#!/usr/bin/env python3
"""Deterministic, no-LLM site-content generator for the private-practice template.

Reads a practice's data (practice.json) + the neutral template placeholders
(template_blocks.json) and emits a generated.json that the proven fill.py engine
consumes. 23 of the 37 template blocks are kept verbatim (fill.py substitutes
their {{tokens}} and strips the AI-GENERATE markers itself); the other 14 are
resolved here from real data — including the deterministic personalization
blocks (hero headline, hero sub, pull quote) driven by the unboxing answers.

THE HONESTY CONTRACT (see citations.py for the long form):
  * Modalities resolve against a curated catalog with REAL foundational
    references. An unknown modality is OMITTED, never given a fabricated source.
  * The "how I work" method and the phased journey come from a generic,
    evidence-informed bank that makes no proprietary or efficacy claim — the
    honest floor when there is no LLM to author a signature method.
  * Every emitted string is run through an honesty linter that rejects
    percentages, "proven/guaranteed", "studies show", testimonials, "cure",
    "#1", etc. If any block trips it, NOTHING is written and we exit non-zero.

Output is intentionally NOT byte-identical to any golden fixture: the golden is
a structural reference (block ids, find strings, array arities); this engine
produces a different, honest, per-practice payload of the same shape.

Pure stdlib. Run: python3 engine/generate.py --practice <p.json> --out <out.json>
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import banned  # noqa: E402  — single source of truth for the banned-language gate
import citations as C  # noqa: E402


# --------------------------------------------------------------------------- #
# Honesty linter — the same banned-language gate described in citations.py.
# Applied to every emitted `replace`. A hit aborts the whole generation.
#
# The pattern list and the linter now live in engine/banned.py — the ONE
# definition every honesty surface (geo.py, svc/honesty.py, honesty_scan.py,
# the proof scripts) derives from, so they cannot silently drift. They are
# re-exported here UNCHANGED, so the long-standing `generate._BANNED` /
# `generate.lint` call sites — and the receipt's `list(_BANNED)` attestation —
# keep working byte-for-byte.
# --------------------------------------------------------------------------- #
_BANNED = banned.BANNED_PATTERNS
lint = banned.lint


# --------------------------------------------------------------------------- #
# Serialization helpers. Cells are HTML-escaped (& < > only; the strings land
# in HTML text via `${...}`) then JSON-quoted (valid JS string literals). The
# result is validated downstream by `node --check` inside fill.py.
# --------------------------------------------------------------------------- #
def j(s) -> str:
    return json.dumps(html.escape(str(s), quote=False), ensure_ascii=False)


def _row(cells: list) -> str:
    return "[" + ",".join(j(c) for c in cells) + "]"


def _emit_rows(find: str, rows: list[list]) -> str:
    """Multiline array block: reuse the template's own `\\n  ].map(<sig>)=>\\``
    tail verbatim (preserving the map callback signature the card body relies on)
    and swap only the array rows. Row indentation is detected from the find so
    8-space and 10-space blocks both round-trip."""
    m = re.search(r"\n([ \t]*)\]\.map", find)
    if not m:
        raise ValueError("not a multiline map block")
    closer = find[m.start():]                  # "\n  ].map(<sig>)=>`"
    body = find[len("${[\n"):m.start()]
    row_indent = re.match(r"[ \t]*", body).group(0)
    serial = [_row(r) for r in rows]
    return "${[\n" + row_indent + (",\n" + row_indent).join(serial) + closer


def _emit_inline(find: str, items: list[str]) -> str:
    """Inline string-array block: the find is a COMPLETE `${[...].map(..).join('')}`
    interpolation. Reuse everything from `].map` onward and swap the array."""
    i = find.index("].map")
    closer = find[i:]                          # "].map(<sig>)=>`...`).join('')}"
    return "${[" + ",".join(j(x) for x in items) + closer


def _emit_posts(posts: list[dict]) -> str:
    """blog_posts is a plain `const posts = [ {..}, .. ];` array, not a map."""
    lines = ["const posts = ["]
    for k, p in enumerate(posts):
        tail = "," if k < len(posts) - 1 else ""
        lines.append("  {")
        lines.append(f"    slug:{j(p['slug'])},")
        lines.append(f"    title:{j(p['title'])},")
        lines.append(f"    description:{j(p['description'])},")
        lines.append(
            f"    date:{j(p['date'])}, readingTime:{j(p['readingTime'])}, "
            f"tag:{j(p['tag'])}"
        )
        lines.append("  }" + tail)
    lines.append("];")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Small text utilities.
# --------------------------------------------------------------------------- #
_SMALL = {"and", "or", "of", "the", "a", "an", "for", "to", "in",
          "on", "with", "at", "by", "but", "nor", "vs"}


def smart_title(s: str) -> str:
    """Title-case but keep small words lowercase (except first) and preserve
    existing all-caps acronyms (EMDR, EAP, PTSD)."""
    words = (s or "").split()
    out = []
    for i, w in enumerate(words):
        if w.isupper() and len(w) > 1:
            out.append(w)
            continue
        lw = w.lower()
        if i > 0 and lw in _SMALL:
            out.append(lw)
        else:
            out.append("-".join(
                (p[:1].upper() + p[1:]) if p else p for p in lw.split("-")
            ))
    return " ".join(out)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _split_list(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]", s or "") if x.strip()]


def _max_weeks(s: str, default: int = 12) -> int:
    nums = [int(x) for x in re.findall(r"\d+", s or "")]
    weeks = max(nums) if nums else default
    # A 3-phase journey needs ≥1 week per phase; clamp the floor so a "0 weeks" /
    # "1 week" duration can't yield an inverted range like "Weeks · 1–0".
    return max(weeks, 3)


def _split_phases(total: int, n: int = 3):
    base, rem = divmod(total, n)
    sizes = [base + (1 if i < rem else 0) for i in range(n)]
    ranges, start = [], 1
    for sz in sizes:
        end = start + sz - 1
        ranges.append((sz, start, end))
        start = end + 1
    return ranges


def _is_oon(p: dict) -> bool:
    blob = " ".join([
        p.get("payment_model", ""), p.get("payment_model_short", ""),
        p.get("practice_model", ""),
    ]).lower()
    if "in-network" in blob or "in network" in blob:
        return False
    return "out" in blob  # out-of-network


# The generic floor pull quote — used ONLY when the therapist supplied no
# `pull_quote` line of their own (and recorded as an assumption by
# build_practice so the approval card flags it; UX audit SH-F4/SH-F5).
FLOOR_PULL_QUOTE = (
    "The work isn't about becoming someone new. It's about getting the "
    "obstacles out of the way of who you already are."
)


# --------------------------------------------------------------------------- #
# The 11 resolvers.
# --------------------------------------------------------------------------- #
def _career(p: dict) -> list[list]:
    """Prefer a structured `career` list; otherwise parse the `career_history`
    string. Descriptions are honest and role-derived — never a fabricated
    accomplishment."""
    career = p.get("career")
    if isinstance(career, list) and career:
        return [[c.get("years", ""), c.get("org", ""),
                 c.get("role", ""), c.get("desc", "")] for c in career]

    rows: list[list] = []
    for seg in re.split(r";", p.get("career_history", "")):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(\d{4})\s*[-–]\s*(\d{4}|present)\s+(.*)$", seg)
        if not m:
            continue
        start, end, rest = m.group(1), m.group(2), m.group(3).strip()
        role = ""
        pm = re.search(r"\(([^)]*)\)", rest)
        if pm:
            role = smart_title(pm.group(1).strip())
            rest = re.sub(r"\s*\([^)]*\)", "", rest).strip()
        is_founder = "found" in rest.lower()
        rest = re.sub(r"^founded\s+", "", rest, flags=re.I).strip()
        if is_founder:
            org = p.get("business_name", smart_title(rest))
            role = "Founder · Private Practice"
            years = f"{p.get('founded_date', start)} – present"
            desc = (f"Private practice serving {p.get('specialties', '')}. "
                    f"Licensed for {p.get('service_areas', '')}.")
        else:
            org = smart_title(rest)
            years = f"{start} – {end}"
            desc = (f"{role or 'Clinical'} work in {org.lower()}." if org
                    else "Clinical work in a community setting.")
        rows.append([years, org, role or "Clinician", desc])
    if not rows:
        # last-resort single honest row from founded_date + business_name
        rows = [[
            f"{p.get('founded_date', '')} – present",
            p.get("business_name", ""),
            "Founder · Private Practice",
            (f"Private practice serving {p.get('specialties', '')}. "
             f"Licensed for {p.get('service_areas', '')}."),
        ]]
    return rows


def _modalities(p: dict) -> list[list]:
    mods = C.resolve_modalities(p.get("modalities", ""))[:4]
    if not mods:
        raise SystemExit(
            "generate.py: no known modality resolved from "
            f"{p.get('modalities')!r} — refusing to emit a citation-free "
            "approach section."
        )
    return [[m["tag"], m["name"], m["what"], m["citation"]] for m in mods]


def _method_cards(_p: dict) -> list[list]:
    # short preview: letter, name, one-line subtitle
    return [[s[0], s[1], s[3]] for s in C.GENERIC_METHOD_STEPS]


def _method_steps(_p: dict) -> list[list]:
    # full: letter, name, num, subtitle, science, practice
    return [[s[0], s[1], s[2], s[3], s[4], s[5]] for s in C.GENERIC_METHOD_STEPS]


def _journey(p: dict) -> list[list]:
    weeks = _max_weeks(p.get("program_duration"))
    ranges = _split_phases(weeks, 3)
    rows = []
    for i, ((sz, a, b), (name, para)) in enumerate(
        zip(ranges, C.GENERIC_JOURNEY_PHASES)
    ):
        detail = f"Weeks · {a}–{b}" if a != b else f"Week · {a}"
        rows.append([f"Phase 0{i + 1}", str(sz), detail, name, para])
    return rows


def _populations(p: dict) -> list[str]:
    return [smart_title(x) for x in _split_list(p.get("populations", ""))][:6]


def _tags(p: dict) -> list[str]:
    specs = [smart_title(x) for x in _split_list(p.get("specialties", ""))]
    items = ["All"] + specs[:3] + ["Method", "Fees"]
    # de-dup preserving order, cap at 6
    seen, out = set(), []
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]


def _posts(p: dict) -> list[dict]:
    """The honest floor ships ZERO posts. No essay exists at build time, so no
    card may claim one: fabricated dates, invented reading times, and links to
    pages that 404 are exactly the dishonesty this engine refuses elsewhere.
    The template renders a truthful "first essays are on the way" state for an
    empty array, and publisher.publish_post prepends REAL entries (real title,
    today's date, reading time computed from the actual word count, a working
    href) as each approved essay goes live — so the section fills truthfully
    over time.
    """
    return []


def _faq(p: dict) -> list[list]:
    oon = _is_oon(p)
    fee = p.get("session_fee", "")
    length = p.get("session_length", "")
    superbill = p.get("superbill_policy", "")
    sliding = p.get("sliding_scale_policy", "")
    program = p.get("program_name", "")
    duration = p.get("program_duration", "")
    areas = p.get("service_areas", "")
    biz = p.get("business_name", "this practice")

    q1_a = f"Sessions are {fee} for a {length} session, paid at the time of service. "
    q1_a += (
        f"{biz} is out-of-network, so you pay directly and receive a superbill "
        "to submit for any out-of-network reimbursement your plan allows."
        if oon else
        f"{biz} is in-network with your plan, so you are responsible for your "
        "copay or coinsurance and any unmet deductible."
    )
    q2_a = (
        f"No — {biz} is out-of-network and does not bill insurance "
        f"directly. {superbill}"
        if oon else
        f"Yes — {biz} is in-network and bills your insurer directly; you "
        "pay only your plan's share."
    )
    q3_a = sliding or ("A limited number of reduced-fee slots are reserved each "
                       "year; ask during the consult whether one is open.")
    q4_a = (
        "It varies with your goals and history. "
        + (f"{program} is one structured path of about {duration}; "
           if program else "")
        + "some people want a focused course of work and others stay longer. "
          "We set the scope together and revisit it as we go."
    )
    q5_a = (
        f"Likely yes if you are an adult located in {areas} and ready for "
        "structured, evidence-based work. If your needs call for a higher level "
        "of care or a specialty outside this practice, I will say so and help "
        "you find the right referral."
    )
    return [
        ["What does your billing model mean for my wallet?", q1_a],
        ["Will you bill my insurance for me?", q2_a],
        ["Do you offer a sliding scale?", q3_a],
        ["How long do clients usually stay in therapy?", q4_a],
        ["Are you a good fit for me?", q5_a],
    ]


def _fees_why(p: dict) -> str:
    biz = p.get("business_name", "this practice")
    if _is_oon(p):
        prose = (
            f"{biz} is out-of-network on purpose: it keeps the clinical "
            "decisions — how often we meet, what we work on, how long it "
            "takes — between you and me rather than an insurer's review. A "
            "free consult is the most honest way to find out whether that "
            "trade-off, and this kind of work, is right for you."
        )
    else:
        prose = (
            f"{biz} is in-network to keep good therapy within reach of the "
            "people who need it. Billing runs through your plan so the cost is "
            "predictable, and a free consult is the best way to find out "
            "whether we are a fit before you commit."
        )
    return f'<p style="margin-top:18px;">{html.escape(prose, quote=False)}</p>'


def _states(p: dict) -> str:
    areas = [a.strip() for a in
             re.split(r"\s*(?:&|,|/|\band\b)\s*", p.get("service_areas", ""))
             if a.strip()]
    lines = [f"<option>{html.escape(a, quote=False)}</option>" for a in areas]
    lines.append("<option>Other</option>")
    return "\n          ".join(lines)


# ── Deterministic personalization (UX audit SH-F5) ──────────────────────────
# The unboxing answers drive the homepage's voice — no two practices ship the
# same hero/quote unless they typed the same answers. No LLM, no new claims:
# every word is the therapist's own input (tagline, populations, pull_quote)
# or the unchanged generic floor. All output re-lints like every block.

def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def _join_human(items: list[str]) -> str:
    """['a','b','c'] -> 'a, b, and c' (Oxford), ['a','b'] -> 'a and b'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _hero_headline(find: str, p: dict) -> str:
    """The therapist's own tagline as the hero H1 (their positioning line from
    the unboxing), with the closing words accented. No tagline -> the generic
    floor headline, verbatim."""
    tagline = (p.get("tagline") or "").strip()
    if not tagline:
        return find  # floor, byte-for-byte
    words = tagline.split()
    n_accent = 2 if len(words) >= 5 else 1
    head, tail = words[:-n_accent], words[-n_accent:]
    inner = (
        f'{_esc(" ".join(head))} <span class="accent">{_esc(" ".join(tail))}</span>'
        if head else f'<span class="accent">{_esc(" ".join(tail))}</span>'
    )
    return f'<h1 id="h1">{inner}</h1>'


def _hero_sub(p: dict) -> str:
    """Hero subhead naming who the practice actually serves (the populations
    answer), instead of the one-size 'adults at a turning point'. The shell
    tokens stay literal — fill.py substitutes them like every other block."""
    pops = [x.lower() for x in _split_list(p.get("populations", ""))][:3]
    audience = _join_human(pops) or "adults"
    return (
        '<p class="hero-sub">{{practice_model}} private psychotherapy with '
        "{{owner_name}}, {{credential}}. Evidence-based work for "
        f"{_esc(audience)}.</p>"
    )


def _pull_quote(p: dict) -> str:
    """The home-page quote attributed to the clinician. Their own line when
    supplied (survey `pull_quote`); otherwise the generic floor quote — which
    build_practice records in `_assumed` so the approval card flags it as
    'shown in your voice — confirm or edit' (SH-F4)."""
    quote = (p.get("pull_quote") or "").strip() or FLOOR_PULL_QUOTE
    return f'<blockquote>"{_esc(quote)}"</blockquote>'


RESOLVERS = {
    "hero_headline":      lambda f, p: _hero_headline(f, p),
    "hero_sub":           lambda f, p: _hero_sub(p),
    "pull_quote":         lambda f, p: _pull_quote(p),
    "method_intro_cards": lambda f, p: _emit_rows(f, _method_cards(p)),
    "career_timeline":    lambda f, p: _emit_rows(f, _career(p)),
    "modalities":         lambda f, p: _emit_rows(f, _modalities(p)),
    "method_steps":       lambda f, p: _emit_rows(f, _method_steps(p)),
    "journey_phases":     lambda f, p: _emit_rows(f, _journey(p)),
    "fees_faq":           lambda f, p: _emit_rows(f, _faq(p)),
    "populations_chips":  lambda f, p: _emit_inline(f, _populations(p)),
    "writing_tags":       lambda f, p: _emit_inline(f, _tags(p)),
    "blog_posts":         lambda f, p: _emit_posts(_posts(p)),
    "fees_why":           lambda f, p: _fees_why(p),
    "state_options":      lambda f, p: _states(p),
}


# --------------------------------------------------------------------------- #
# Structured refusal output (concierge-beta deliverable C).
# The engine already ENFORCES the honesty contract; this EMITS a machine-readable
# record of what it omitted/refused, so the honesty receipt is GENERATED from the
# build rather than hand-assembled. Pure data — NO PHI, only the provider's own
# listed modalities and the engine's standing policy.
# --------------------------------------------------------------------------- #
def refusals_manifest(practice: dict, *, lint_clean: bool = False) -> dict:
    """A structured record of what the honesty engine omitted / would refuse.

    ``lint_clean`` is an ATTESTATION the caller vouches for: ``generate()`` passes
    ``True`` only after every emitted block has cleared the banned-language gate
    (so nothing dishonest survived into the site). A standalone caller that has
    not run the gate gets the honest default ``False`` — we never claim a build
    is lint-clean unless it actually passed.

    Fields:
      * ``modalities_listed``          — what the provider typed, normalized.
      * ``modalities_shown``           — resolved + really-cited, capped at the 4
                                         the approach section displays.
      * ``modalities_dropped_unknown`` — listed but no real foundational citation
                                         in the catalog: OMITTED, never fabricated.
      * ``modalities_capped``          — resolved + cited, but beyond the 4-card cap.
      * ``method``                     — the no-LLM honest floor; never an invented
                                         signature method.
      * ``banned_language_enforced``   — the standing banned-claim patterns every
                                         emitted string is linted against.
    """
    detail = C.resolve_modalities_detail(practice.get("modalities", ""))
    resolved = detail["resolved"]
    shown, capped = resolved[:4], resolved[4:]
    return {
        "modalities_listed": detail["listed"],
        "modalities_shown": [m["name"] for m in shown],
        "modalities_dropped_unknown": detail["dropped"],
        "modalities_capped": [m["name"] for m in capped],
        "method": "generic-evidence-informed-floor",
        "signature_method": practice.get("signature_method_name", ""),
        "banned_language_enforced": list(_BANNED),
        "lint_clean": bool(lint_clean),
    }


# --------------------------------------------------------------------------- #
# Driver.
# --------------------------------------------------------------------------- #
def generate(practice: dict, template_blocks: dict, brain=None) -> dict:
    """Resolve every template block to honest per-practice content.

    ``brain`` is an OPTIONAL, caller-supplied enrichment seam (None by default —
    the verified deterministic floor; output is byte-identical to the no-brain
    build). When a brain object is supplied, prose-only blocks named in its
    ``BRAIN_BLOCKS`` get a model-authored rewrite — which is then re-linted here
    exactly like the floor, so a banned claim cannot survive even if the brain
    misbehaves. Any brain failure or rejection leaves the deterministic
    ``replace`` untouched.
    """
    blocks = template_blocks["blocks"]
    out_blocks: dict[str, dict] = {}
    violations: list[str] = []

    for bid, meta in blocks.items():
        find = meta["find"]
        if bid in RESOLVERS:
            replace = RESOLVERS[bid](find, practice)
        else:
            replace = find  # KEEP verbatim; fill.py fills tokens + strips markers
        # OPTIONAL enrichment seam — additive, behind the same honesty linter.
        if brain is not None and bid in getattr(brain, "BRAIN_BLOCKS", ()):
            try:
                enriched = brain.enrich_block(bid, practice, find)
            except Exception:
                enriched = None  # never let the seam break the deterministic build
            if enriched is not None:
                replace = enriched
        hits = lint(replace)  # re-lint REGARDLESS of source (floor or brain)
        if hits:
            violations.append(f"{bid}: {', '.join(hits)}")
        out_blocks[bid] = {"file": meta["file"], "find": find, "replace": replace}

    if violations:
        print("generate.py: HONESTY LINT FAILED — nothing written:",
              file=sys.stderr)
        for v in violations:
            print("  -", v, file=sys.stderr)
        raise SystemExit(2)

    return {
        "_comment": (
            "DETERMINISTIC, no-LLM generated content for the private-practice "
            "template. 23 blocks kept verbatim (fill.py substitutes {{tokens}} "
            "and strips AI-GENERATE markers); 14 resolved from practice data "
            "with real citations / honest generic floors — incl. the unboxing-"
            "driven personalization blocks (hero, pull quote). Honesty-linted. "
            "Consumed by engine/fill.py."
        ),
        "blocks": out_blocks,
        # Structured refusal record (concierge-beta deliverable C). Additive
        # metadata: fill.py consumes ONLY ["blocks"], so this never reaches the
        # site. Emitted here — AFTER the violations gate — so lint_clean is a
        # VERIFIED attestation (every block cleared the banned-language linter),
        # not a hope. The honesty receipt is generated from this.
        "_refusals": refusals_manifest(practice, lint_clean=True),
    }


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    ap = argparse.ArgumentParser(description="Deterministic site-content generator.")
    ap.add_argument("--practice",
                    default=os.path.join(repo, "fixtures", "cedar-sage", "practice.json"))
    ap.add_argument("--template-blocks",
                    default=os.path.join(here, "template_blocks.json"))
    ap.add_argument("--out",
                    default=os.path.join(here, "generated.gen.json"))
    args = ap.parse_args(argv)

    with open(args.practice, encoding="utf-8") as fh:
        practice = json.load(fh)
    with open(args.template_blocks, encoding="utf-8") as fh:
        template_blocks = json.load(fh)

    result = generate(practice, template_blocks)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    n_resolved = sum(1 for b in template_blocks["blocks"] if b in RESOLVERS)
    n_keep = len(template_blocks["blocks"]) - n_resolved
    print(f"generate.py OK — {len(result['blocks'])} blocks "
          f"({n_resolved} resolved, {n_keep} verbatim), honesty-clean → "
          f"{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
