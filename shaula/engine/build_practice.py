#!/usr/bin/env python3
"""build_practice — turn a short therapist *survey* into a full practice.json.

This is the porcelain↔plumbing bridge. A therapist answers ~15 human questions
in the dashboard; this module deterministically expands those answers into the
complete set of {{tokens}} the fill engine needs (53 canonical tokens + the
cosmetic `upload` marker), deriving and defaulting everything else.

Design rules (honest by construction):
  * NEVER fabricate a branded method. The no-LLM floor always ships a GENERIC
    method label (`method_name` neutral, `method_acronym` ""). A real signature
    method is an LLM-enrichment deliverable, not something the floor invents.
    (DECISIONS.md D5.)
  * NEVER invent license numbers, outcomes, or modalities. Unknown optional
    fields become "" (the template + resolvers omit them) — never a guess.
  * Crisis lines default to the US national 988 + Crisis Text Line — public,
    correct, life-safety. (Manifest: 988/911 hard-coded for US practices.)
  * Every produced value is run through the SAME banned-claim linter the rest
    of the engine uses (imported from generate.py — single source of truth). A
    dishonest operator input (e.g. a tagline with "proven, #1, 95%") raises
    HonestyError before any file is written.

The output is a plain dict / JSON object — identical in shape to the hand-authored
fixtures, so it flows straight through generate.py → fill.py → render_check.

CLI:
    build_practice.py --survey survey.json --out practice.json
    build_practice.py --demo                      # print a sample survey to stdout
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

# Canonical banned-claim linter (single source of truth).
_ENGINE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_ENGINE))
import generate as G  # noqa: E402


class HonestyError(ValueError):
    """Raised when survey input contains a banned marketing claim."""

    def __init__(self, problems: list[tuple[str, list[str]]]):
        self.problems = problems
        lines = [f"  {field}: {pats}" for field, pats in problems]
        super().__init__("dishonest claim(s) in survey input:\n" + "\n".join(lines))


# Credential short form → spelled-out form. Fallback: the operator-supplied
# credential_full, else the raw credential.
CREDENTIAL_MAP = {
    "LCSW": "Licensed Clinical Social Worker",
    "LICSW": "Licensed Independent Clinical Social Worker",
    "LISW": "Licensed Independent Social Worker",
    "LMSW": "Licensed Master Social Worker",
    "LCSW-C": "Licensed Certified Social Worker–Clinical",
    "LMFT": "Licensed Marriage and Family Therapist",
    "LCMFT": "Licensed Clinical Marriage and Family Therapist",
    "LPC": "Licensed Professional Counselor",
    "LPCC": "Licensed Professional Clinical Counselor",
    "LCPC": "Licensed Clinical Professional Counselor",
    "LMHC": "Licensed Mental Health Counselor",
    "LCMHC": "Licensed Clinical Mental Health Counselor",
    "LPC-MH": "Licensed Professional Counselor–Mental Health",
    "PsyD": "Licensed Psychologist",
    "PhD": "Licensed Psychologist",
    "LP": "Licensed Psychologist",
}

# Required survey keys — the minimum a therapist must answer.
REQUIRED = (
    "owner_name", "credential", "business_name", "specialties", "modalities",
    "location", "service_areas", "payment_model_type", "session_fee",
    "session_length", "phone", "email", "education", "founded_date",
    "license_state", "license_number", "license_year",
)

# ── The intake contract (UX audit SH-F9) ────────────────────────────────────
# Single source of truth shared by the 9-question unboxing (the apps), the
# svc's readiness endpoints, and this engine. The apps' INTAKE_QUESTIONS keys
# must stay a subset of this tuple; the svc derives `missingForWebsite` from
# REQUIRED − INTAKE_CORE − what derive_survey() can honestly fill.
INTAKE_CORE = (
    "owner_name", "credential", "business_name", "tagline", "specialties",
    "populations", "modalities", "location", "fee",
)

# Key aliases the apps may send (the 9-Q asks "Your session fee" as `fee`).
SURVEY_ALIASES = {"fee": "session_fee"}

# USPS state abbreviations → full names, for the honest service_areas /
# license_state derivations from "City, ST" locations. Public reference data.
_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}


def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")


def _first_word(s: str) -> str:
    parts = (s or "").strip().split()
    return parts[0] if parts else ""


def _nonempty(*vals) -> str:
    """First non-empty stripped value, else ''."""
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _location_state(location: str) -> tuple[str, str]:
    """('Denver, CO') -> ('CO', 'Colorado'); ('Colorado') -> ('', 'Colorado')
    when the whole string is a state name; else ('', '')."""
    loc = (location or "").strip()
    if "," in loc:
        tail = loc.rsplit(",", 1)[1].strip().upper()
        if tail in _STATE_NAMES:
            return tail, _STATE_NAMES[tail]
    for abbr, name in _STATE_NAMES.items():
        if loc.lower() == name.lower():
            return abbr, name
    return "", ""


# ── Derivation + readiness (UX audit SH-F9, marked per SH-F4) ────────────────
# The 9-question unboxing collects fewer facts than REQUIRED demands. What can
# be derived HONESTLY is derived here — explicitly, once, and every derivation
# is returned as a marked assumption so the approval flow can say "Shaula assumed
# these — confirm or edit". What cannot be honestly derived (a phone number, an
# email, a license number) is reported by missing_for_website() so the apps
# fail fast at intake, never mid-run with a cryptic category.

def derive_survey(survey: dict) -> tuple[dict, list[dict]]:
    """Alias + derive the REQUIRED gap fields from the 9-Q answers.

    Returns ``(derived_survey, assumptions)`` where each assumption is
    ``{"field", "label", "value", "from"}``. NEVER invents identity facts:
    license numbers, contact details, education, and dates are left missing.
    """
    out = dict(survey or {})
    assumptions: list[dict] = []

    for alias, target in SURVEY_ALIASES.items():
        if not _nonempty(out.get(target)) and _nonempty(out.get(alias)):
            out[target] = _nonempty(out.get(alias))  # the therapist's own answer — not an assumption

    abbr, state_name = _location_state(out.get("location", ""))
    if not _nonempty(out.get("service_areas")) and state_name:
        out["service_areas"] = state_name
        assumptions.append({
            "field": "service_areas", "label": "Telehealth coverage",
            "value": state_name, "from": "your location",
        })
    if not _nonempty(out.get("license_state")) and abbr:
        out["license_state"] = abbr
        assumptions.append({
            "field": "license_state", "label": "License state",
            "value": abbr, "from": "your location",
        })
    if not _nonempty(out.get("payment_model_type")):
        out["payment_model_type"] = "out-of-network"
        assumptions.append({
            "field": "payment_model_type", "label": "Billing model",
            "value": "Out-of-network (private pay)", "from": "default",
        })
    if not _nonempty(out.get("session_length")):
        out["session_length"] = "50-minute"
        assumptions.append({
            "field": "session_length", "label": "Session length",
            "value": "50-minute", "from": "default",
        })
    return out, assumptions


def missing_for_website(survey: dict) -> list[str]:
    """REQUIRED fields still missing AFTER honest derivation — the readiness
    contract the svc returns at intake so the first run can never die on a
    surprise ValueError (SH-F9: fail at intake, never at run)."""
    derived, _ = derive_survey(survey or {})
    return [k for k in REQUIRED if not _nonempty(derived.get(k))]


# Commitment fields (UX audit SH-F4): when the survey omits these, the engine
# fills a default that READS as the practice's stated policy. Every default
# used is recorded as an assumption ("Shaula assumed these — confirm or edit")
# and surfaced on the website-launch approval card. The defaults themselves
# are the most non-committal honest copy that still renders a coherent page.
COMMITMENT_LABELS = {
    "program_duration": "Program length",
    "cadence": "Session cadence",
    "cancellation_policy": "Cancellation policy",
    "superbill_policy": "Superbill policy",
    "sliding_scale_policy": "Sliding scale",
    "consult_length": "Free-consult length",
    "response_time": "Reply time",
    "availability_status": "Availability note",
    "pull_quote": "Home-page quote (shown in your voice)",
}

# Honest, non-committal defaults — these replace the old fabricated business
# facts ("reduced-fee slots are reserved each year", "Now welcoming new
# clients") with copy that promises only what is true by construction.
DEFAULT_SLIDING_SCALE = "Ask during the consult about current fee options."
DEFAULT_AVAILABILITY = "Accepting consult requests"


def _commitment_assumptions(derived_survey: dict) -> list[dict]:
    """The commitment defaults that WOULD apply to this (derived) survey —
    one list both build_practice and survey_readiness compose from, so the
    approval card and the built site can never disagree (SH-F4)."""
    g = derived_survey.get
    is_in_network = _nonempty(g("payment_model_type")).lower().startswith("in")
    defaults = {
        "program_duration": "12 to 16 weeks",
        "cadence": "Weekly",
        "cancellation_policy": "24-hour cancellation policy",
        "superbill_policy": (
            "In-network claims are filed directly with your insurer; an "
            "itemized superbill is available on request."
            if is_in_network else
            "Monthly superbill provided on request for out-of-network reimbursement"
        ),
        "sliding_scale_policy": DEFAULT_SLIDING_SCALE,
        "consult_length": "20-minute",
        "response_time": "within two business days",
        "availability_status": DEFAULT_AVAILABILITY,
        "pull_quote": G.FLOOR_PULL_QUOTE,
    }
    return [
        {
            "field": field,
            "label": COMMITMENT_LABELS[field],
            "value": default,
            "from": "default",
        }
        for field, default in defaults.items()
        if not _nonempty(g(field))
    ]


def survey_readiness(survey: dict) -> dict:
    """The full intake contract in one call: what is still missing for a
    website build, and which facts Shaula would assume if built right now.
    Pure — no build, no I/O. The svc returns this verbatim at intake."""
    derived, derivations = derive_survey(survey or {})
    missing = [k for k in REQUIRED if not _nonempty(derived.get(k))]
    return {
        "missing": missing,
        "assumed": derivations + _commitment_assumptions(derived),
    }


def ai_disclosure(survey: dict) -> str:
    """The AI-involvement disclosure line for published output (site footer +
    essay pages). ON BY DEFAULT — transparency is a first-class feature, not a
    buried setting. The therapist can override the text (`ai_disclosure_text`)
    or turn it off (`ai_disclosure: "off"`). A custom text that trips the
    banned-claim linter falls back to the honest default line rather than
    shipping; the default is lint-clean by construction.

    Single source of truth: the site build (build_practice) and the essay
    publisher (svc/runner → publisher) both compose through this function, so
    the two surfaces can never disagree.
    """
    mode = str(survey.get("ai_disclosure", "")).strip().lower()
    if mode in ("off", "none", "false", "0"):
        return ""
    owner = _nonempty(survey.get("owner_name"))
    cred = _nonempty(survey.get("credential"))
    who = f"{owner}, {cred}" if owner and cred else (owner or "the clinician")
    default = (
        f"Created with AI assistance from Shaula. Reviewed and approved by "
        f"{who} before publication."
    )
    custom = _nonempty(survey.get("ai_disclosure_text"))
    if custom and not G.lint(custom):
        return custom
    return default


def build_practice(survey: dict, *, year: int | None = None) -> dict:
    """Expand a survey dict into a complete practice (token) dict.

    The survey is first passed through ``derive_survey`` (alias the 9-Q keys,
    honestly derive the derivable gap fields — SH-F9), and every derivation or
    commitment default used is recorded in the returned dict's ``_assumed``
    list so the approval flow can surface "Shaula assumed these — confirm or
    edit" (SH-F4). Identity facts are never invented.

    Raises HonestyError if any produced value contains a banned claim, and
    ValueError if a required survey field is missing.
    """
    survey, derivations = derive_survey(survey)
    missing = [k for k in REQUIRED if not _nonempty(survey.get(k))]
    if missing:
        raise ValueError(f"survey missing required field(s): {', '.join(missing)}")

    g = survey.get  # shorthand
    year = year or datetime.datetime.now().year

    credential = _nonempty(g("credential"))
    credential_full = _nonempty(
        g("credential_full"), CREDENTIAL_MAP.get(credential), credential
    )

    # Billing model — in-network vs out-of-network. Aligns with generate.py
    # _is_oon (which keys off the literal substring "in-network").
    is_in_network = _nonempty(g("payment_model_type")).lower().startswith("in")
    plans = _nonempty(g("plans"))  # optional: "Aetna & Cigna"
    if is_in_network:
        practice_model = "In-network"
        payment_model = (
            f"In-network with {plans}" if plans else "In-network with major plans"
        )
        payment_model_short = "in-network"
        superbill_policy = _nonempty(
            g("superbill_policy"),
            "In-network claims are filed directly with your insurer; an "
            "itemized superbill is available on request.",
        )
    else:
        practice_model = "Out-of-network"
        payment_model = _nonempty(g("payment_model"), "Out-of-network, no insurance billed")
        payment_model_short = "out-of-network"
        superbill_policy = _nonempty(
            g("superbill_policy"),
            "Monthly superbill provided on request for out-of-network reimbursement",
        )

    # Office address (all optional — telehealth-only practices omit).
    address_line1 = _nonempty(g("address_line1"))
    address_line2 = _nonempty(g("address_line2"))
    address_full = ", ".join([p for p in (address_line1, address_line2) if p])

    # Licenses + footer credential lines.
    lic_state = _nonempty(g("license_state"))
    lic_num = _nonempty(g("license_number"))
    lic_year = _nonempty(g("license_year"))
    license_1_label = f"{lic_state} License"
    license_1_value = f"{lic_num} — {lic_year}" if lic_year else lic_num

    lic2_state = _nonempty(g("license_2_state"))
    lic2_num = _nonempty(g("license_2_number"))
    lic2_year = _nonempty(g("license_2_year"))
    if lic2_state and lic2_num:
        license_2_label = f"{lic2_state} License"
        license_2_value = f"{lic2_num} — {lic2_year}" if lic2_year else lic2_num
        credential_line_2 = f"{lic2_state} {credential} · {lic2_num}"
    else:
        license_2_label = license_2_value = credential_line_2 = ""

    credential_line_1 = f"{lic_state} {credential} · {lic_num}"
    credential_line_3 = _nonempty(g("credential_line_3"))  # e.g. "MSW · Smith · 2014"

    session_fee = _nonempty(g("session_fee"))

    practice = {
        "_comment": (
            "Generated by build_practice from a therapist survey. Synthetic/"
            "operator-supplied data only — no PHI."
        ),
        # identity
        "owner_name": _nonempty(g("owner_name")),
        "owner_first_name": _nonempty(g("owner_first_name"), _first_word(g("owner_name"))),
        "credential": credential,
        "credential_full": credential_full,
        "business_name": _nonempty(g("business_name")),
        "tagline": _nonempty(g("tagline")),
        # billing
        "practice_model": practice_model,
        "payment_model": payment_model,
        "payment_model_short": payment_model_short,
        # clinical
        "specialties": _nonempty(g("specialties")),
        "populations": _nonempty(g("populations"), "adults"),
        "modalities": _nonempty(g("modalities")),
        "outcome_measures": _nonempty(g("outcome_measures")),
        # method — GENERIC by design (D5). Never a branded acronym from the floor.
        "method_name": _nonempty(g("method_name"), "How the work works"),
        "method_acronym": "",
        "signature_method_name": _nonempty(
            g("signature_method_name"),
            "None — the no-LLM floor presents a generic, evidence-informed "
            "process; a branded method would be authored only with LLM enrichment.",
        ),
        "program_name": _nonempty(g("program_name"), "The Work"),
        "program_duration": _nonempty(g("program_duration"), "12 to 16 weeks"),
        # location
        "location": _nonempty(g("location")),
        "service_areas": _nonempty(g("service_areas")),
        "office_detail": _nonempty(g("office_detail")),
        "address_line1": address_line1,
        "address_line2": address_line2,
        "address_full": address_full,
        # contact
        "phone": _nonempty(g("phone")),
        "email": _nonempty(g("email")),
        "education": _nonempty(g("education")),
        "founded_date": _nonempty(g("founded_date")),
        # licenses
        "license_1_label": license_1_label,
        "license_1_value": license_1_value,
        "license_2_label": license_2_label,
        "license_2_value": license_2_value,
        "credential_line_1": credential_line_1,
        "credential_line_2": credential_line_2,
        "credential_line_3": credential_line_3,
        # fees
        "session_fee": session_fee,
        "session_fee_amount": _digits(session_fee),
        "session_length": _nonempty(g("session_length")),
        "cadence": _nonempty(g("cadence"), "Weekly"),
        "cancellation_policy": _nonempty(g("cancellation_policy"), "24-hour cancellation policy"),
        "superbill_policy": superbill_policy,
        # Honest non-committal defaults (SH-F4): never fabricate a reduced-fee
        # program or an open-caseload claim the therapist did not make.
        "sliding_scale_policy": _nonempty(g("sliding_scale_policy"), DEFAULT_SLIDING_SCALE),
        "consult_length": _nonempty(g("consult_length"), "20-minute"),
        "response_time": _nonempty(g("response_time"), "within two business days"),
        "availability_status": _nonempty(g("availability_status"), DEFAULT_AVAILABILITY),
        "location_field_label": _nonempty(g("location_field_label"), "State"),
        # personalization (SH-F5): the therapist's own line, rendered as the
        # home-page pull quote; empty -> the generic floor quote (flagged below).
        "pull_quote": _nonempty(g("pull_quote")),
        # crisis (US national defaults — public, correct, life-safety)
        "crisis_line_1_label": _nonempty(g("crisis_line_1_label"), "Crisis Text Line"),
        "crisis_line_1_number": _nonempty(g("crisis_line_1_number"), "Text HOME to 741741"),
        "crisis_line_2_label": _nonempty(g("crisis_line_2_label"), "988 Suicide & Crisis Lifeline"),
        "crisis_line_2_number": _nonempty(g("crisis_line_2_number"), "Call or text 988"),
        # misc
        "hero_video_alt": _nonempty(g("hero_video_alt"), "Two hawks in flight at sunrise"),
        "current_year": _nonempty(g("current_year"), str(year)),
        "background_summary": _nonempty(g("background_summary")),
        "career_history": _nonempty(g("career_history")),
        "upload": "upload",
        # transparency: AI-involvement disclosure, ON by default (see helper).
        "ai_disclosure": ai_disclosure(survey),
        # inquiry delivery: the contact form POSTs here. Composed by
        # pipeline.build_site once the slug is known (needs the svc's public
        # origin + the site slug). Empty = the template renders its honest
        # direct-contact fallback instead of a form — NEVER a dead-end form.
        "inquiry_endpoint": "",
    }

    # Optional structured career array passes straight through if supplied.
    if isinstance(survey.get("career"), list) and survey["career"]:
        practice["career"] = survey["career"]

    # The assumption record (SH-F4/SH-F9): every derivation + every commitment
    # default used in THIS build, for the approval card's "Shaula assumed
    # these — confirm or edit". Underscore key = metadata, never shipped copy
    # (skipped by the lint loop below and by scripts/honesty_scan.py alike).
    practice["_assumed"] = derivations + _commitment_assumptions(survey)

    # Honesty gate: lint every produced string against the canonical banned list.
    problems = []
    for k, v in practice.items():
        if k.startswith("_") or not isinstance(v, str):
            continue
        bad = G.lint(v)
        if bad:
            problems.append((k, bad))
    if problems:
        raise HonestyError(problems)

    return practice


DEMO_SURVEY = {
    "owner_name": "Maya Restrepo",
    "credential": "LPC",
    "business_name": "North Star Counseling",
    "tagline": "Therapy for the overextended.",
    "specialties": "burnout, anxiety, perfectionism",
    "populations": "adults, graduate students, healthcare workers",
    "modalities": "CBT, ACT, mindfulness-based",
    "location": "Denver, CO",
    "service_areas": "Colorado",
    "payment_model_type": "out-of-network",
    "session_fee": "$175",
    "session_length": "50-minute",
    "phone": "303-555-0166",
    "email": "hello@northstarcounseling.com",
    "education": "MA in Clinical Mental Health Counseling, University of Denver, 2014",
    "founded_date": "2018",
    "license_state": "CO",
    "license_number": "#LPC.0000000 (placeholder)",
    "license_year": "2016",
    "credential_line_3": "MA · University of Denver · 2014",
    "outcome_measures": "GAD-7 and PHQ-9",
    "career_history": (
        "2014-2017 community counseling center (staff counselor); "
        "2017-2018 university student wellness center (counselor); "
        "2018-present founded North Star Counseling"
    ),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Expand a therapist survey into a practice.json")
    ap.add_argument("--survey", help="path to survey.json")
    ap.add_argument("--out", help="path to write practice.json (default: stdout)")
    ap.add_argument("--demo", action="store_true", help="print a sample survey and exit")
    args = ap.parse_args(argv)

    if args.demo:
        print(json.dumps(DEMO_SURVEY, indent=2, ensure_ascii=False))
        return 0

    if not args.survey:
        ap.error("--survey is required (or use --demo)")

    survey = json.loads(pathlib.Path(args.survey).read_text(encoding="utf-8"))
    try:
        practice = build_practice(survey)
    except HonestyError as e:
        print(f"build_practice: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"build_practice: {e}", file=sys.stderr)
        return 2

    out = json.dumps(practice, indent=2, ensure_ascii=False)
    if args.out:
        pathlib.Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"build_practice OK — wrote {len(practice)} tokens → {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
