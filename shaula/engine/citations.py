"""Curated clinical reference + content banks for the deterministic site generator.

THE HONESTY CONTRACT (read before editing):
  * Every modality listed here carries a REAL foundational reference. If a
    practice names a modality that is not in MODALITIES, the generator OMITS it
    rather than inventing a citation. Never add an entry with a fabricated or
    guessed source.
  * The `what` blurbs describe what a modality does in plain language. They make
    no efficacy promises ("proven", "guaranteed", percentages, testimonials).
    The honesty linter in generate.py will reject those words on sight, so keep
    this file clean too.
  * The generic METHOD_STEPS / JOURNEY_PHASES banks are the no-LLM floor: a
    sound, general, evidence-informed therapeutic arc (regulate -> notice ->
    understand -> practice -> integrate -> sustain) that is TRUE for essentially
    any talk-therapy practice. They deliberately do NOT claim to be a named,
    proprietary method. A bespoke "GROUND Method" page requires an LLM to author
    the signature clinical content; without one we present an honest general
    framework. This limitation is documented in DECISIONS.md.

Pure stdlib. Importable; also runnable (`python3 citations.py`) for a self-test.
"""

from __future__ import annotations

import re
import unicodedata


# --------------------------------------------------------------------------- #
# Modality catalog. Key = normalized slug. Each entry:
#   tag      short badge code shown on the card (<=5 chars typical)
#   name     full display name (raw '&' allowed; serializer HTML-escapes once)
#   what     1-2 plain-language sentences: what it does, when it helps
#   citation real foundational reference "Author — Title (Year)"
# Citations are seminal primary sources, verified from training knowledge.
# --------------------------------------------------------------------------- #
MODALITIES: dict[str, dict[str, str]] = {
    "cbt": {
        "tag": "CBT",
        "name": "Cognitive Behavioral Therapy",
        "what": "Maps the loop between thoughts, feelings, and behavior, then tests the beliefs that keep a problem running so they lose their grip. Practical, structured, and well-suited to anxiety, depression, and panic.",
        "citation": "Beck — Cognitive Therapy and the Emotional Disorders (1976)",
    },
    "act": {
        "tag": "ACT",
        "name": "Acceptance & Commitment Therapy",
        "what": "Builds room to feel hard things without being run by them, and points action toward what you actually value. Helps when the fight against a feeling has become its own problem.",
        "citation": "Hayes, Strosahl & Wilson — Acceptance and Commitment Therapy (1999)",
    },
    "emdr": {
        "tag": "EMDR",
        "name": "Eye Movement Desensitization & Reprocessing",
        "what": "A structured, eight-phase approach that helps the brain reprocess stuck traumatic memories so they stop firing in the present. Strong evidence base for PTSD and single-incident trauma.",
        "citation": "Shapiro — Eye Movement Desensitization and Reprocessing (1995)",
    },
    "mi": {
        "tag": "MI",
        "name": "Motivational Interviewing",
        "what": "A collaborative way of working through ambivalence, so change comes from your own reasons rather than outside pressure. Useful at the start of a hard transition.",
        "citation": "Miller & Rollnick — Motivational Interviewing (1991)",
    },
    "dbt": {
        "tag": "DBT",
        "name": "Dialectical Behavior Therapy",
        "what": "Pairs acceptance with concrete skills for tolerating distress, regulating emotion, and steadying relationships. Built for intense emotions that feel like they take the wheel.",
        "citation": "Linehan — Cognitive-Behavioral Treatment of Borderline Personality Disorder (1993)",
    },
    "gottman": {
        "tag": "Gottman",
        "name": "Gottman Method Couples Therapy",
        "what": "Uses decades of relationship research to map what helps couples and what erodes them, then rebuilds friendship, conflict repair, and shared meaning. Assessment-driven and practical.",
        "citation": "Gottman & Silver — The Seven Principles for Making Marriage Work (1999)",
    },
    "eft": {
        "tag": "EFT",
        "name": "Emotionally Focused Therapy",
        "what": "Treats the bond itself as the client, helping partners surface the softer feelings under conflict and reach for each other instead of bracing. A leading evidence-based couples approach.",
        "citation": "Greenberg & Johnson — Emotionally Focused Therapy for Couples (1988)",
    },
    "ifs": {
        "tag": "IFS",
        "name": "Internal Family Systems",
        "what": "Works with the different 'parts' of you — the protector, the wounded one, the critic — so they can step back and let a calmer, core self lead. Gentle with trauma and inner conflict.",
        "citation": "Schwartz — Internal Family Systems Therapy (1995)",
    },
    "mbct": {
        "tag": "MBCT",
        "name": "Mindfulness-Based Cognitive Therapy",
        "what": "Blends mindfulness practice with cognitive therapy to interrupt the spirals that pull people back into depression. Built as relapse prevention for recurrent low mood.",
        "citation": "Segal, Williams & Teasdale — Mindfulness-Based Cognitive Therapy for Depression (2002)",
    },
    "mbsr": {
        "tag": "MBSR",
        "name": "Mindfulness-Based Stress Reduction",
        "what": "An eight-week training in mindfulness and body awareness for working with stress, chronic pain, and reactivity. Skills-based and structured.",
        "citation": "Kabat-Zinn — Full Catastrophe Living (1990)",
    },
    "cpt": {
        "tag": "CPT",
        "name": "Cognitive Processing Therapy",
        "what": "A focused trauma protocol that helps you examine and update the stuck beliefs a trauma leaves behind — about safety, trust, and self-blame. Well-supported for PTSD.",
        "citation": "Resick & Schnicke — Cognitive Processing Therapy for Rape Victims (1993)",
    },
    "pe": {
        "tag": "PE",
        "name": "Prolonged Exposure",
        "what": "Gradually and safely approaches trauma memories and avoided situations so they lose their power. One of the most established treatments for PTSD.",
        "citation": "Foa & Rothbaum — Treating the Trauma of Rape (1998)",
    },
    "sfbt": {
        "tag": "SFBT",
        "name": "Solution-Focused Brief Therapy",
        "what": "Starts from what is already working and the future you want, building concrete next steps rather than excavating the past. Pragmatic and often short-term.",
        "citation": "de Shazer — Keys to Solution in Brief Therapy (1985)",
    },
    "narrative": {
        "tag": "NT",
        "name": "Narrative Therapy",
        "what": "Separates you from the problem and helps you re-author the story you live by, drawing out the strengths the problem-saturated version leaves out.",
        "citation": "White & Epston — Narrative Means to Therapeutic Ends (1990)",
    },
    "se": {
        "tag": "SE",
        "name": "Somatic Experiencing",
        "what": "Works with the body's stored survival responses, helping a nervous system complete and discharge what got frozen during overwhelm. Body-based and slow-paced.",
        "citation": "Levine — Waking the Tiger (1997)",
    },
    "pct": {
        "tag": "PCT",
        "name": "Person-Centered Therapy",
        "what": "Trusts that, given genuine empathy and unconditional regard, people move toward their own growth. The relationship itself is the active ingredient.",
        "citation": "Rogers — Client-Centered Therapy (1951)",
    },
    "psychodynamic": {
        "tag": "PDT",
        "name": "Psychodynamic Therapy",
        "what": "Explores how early relationships and out-of-awareness patterns shape present struggles, using the therapy relationship itself as a place to notice and change them.",
        "citation": "Shedler — The Efficacy of Psychodynamic Psychotherapy (2010)",
    },
    "play": {
        "tag": "Play",
        "name": "Play Therapy",
        "what": "Meets children in their own language — play — to help them express and work through what they cannot yet put into words. Developmentally matched for younger clients.",
        "citation": "Landreth — Play Therapy: The Art of the Relationship (1991)",
    },
    "ipt": {
        "tag": "IPT",
        "name": "Interpersonal Psychotherapy",
        "what": "A time-limited approach that links mood to specific relationship stressors — loss, role change, conflict — and works them directly. Well-supported for depression.",
        "citation": "Klerman, Weissman, Rounsaville & Chevron — Interpersonal Psychotherapy of Depression (1984)",
    },
    "tfcbt": {
        "tag": "TF-CBT",
        "name": "Trauma-Focused Cognitive Behavioral Therapy",
        "what": "A structured, family-involved model for children and teens after trauma, pairing coping skills with a carefully paced trauma narrative. Strong evidence base for youth.",
        "citation": "Cohen, Mannarino & Deblinger — Treating Trauma and Traumatic Grief in Children and Adolescents (2006)",
    },
}

# Aliases -> canonical slug. Lets a therapist type the common name or the
# acronym and still resolve. Anything not here normalizes by slug and, if still
# unmatched, is OMITTED by the generator (never fabricated).
_ALIASES: dict[str, str] = {
    "cognitive behavioral therapy": "cbt",
    "cognitive behavioural therapy": "cbt",
    "cognitive behaviour therapy": "cbt",
    "cognitive behavior therapy": "cbt",
    "cbt": "cbt",
    "acceptance and commitment therapy": "act",
    "acceptance & commitment therapy": "act",
    "act": "act",
    "eye movement desensitization and reprocessing": "emdr",
    "eye movement desensitization & reprocessing": "emdr",
    "emdr": "emdr",
    "motivational interviewing": "mi",
    "mi": "mi",
    "dialectical behavior therapy": "dbt",
    "dialectical behaviour therapy": "dbt",
    "dbt": "dbt",
    "gottman method": "gottman",
    "gottman method couples therapy": "gottman",
    "gottman": "gottman",
    "emotionally focused therapy": "eft",
    "emotion focused therapy": "eft",
    "emotion-focused therapy": "eft",
    "eft": "eft",
    "internal family systems": "ifs",
    "internal family systems therapy": "ifs",
    "ifs": "ifs",
    "parts work": "ifs",
    "mindfulness based cognitive therapy": "mbct",
    "mindfulness-based cognitive therapy": "mbct",
    "mbct": "mbct",
    "mindfulness based stress reduction": "mbsr",
    "mindfulness-based stress reduction": "mbsr",
    "mbsr": "mbsr",
    "cognitive processing therapy": "cpt",
    "cpt": "cpt",
    "prolonged exposure": "pe",
    "prolonged exposure therapy": "pe",
    "pe": "pe",
    "solution focused brief therapy": "sfbt",
    "solution-focused brief therapy": "sfbt",
    "solution focused therapy": "sfbt",
    "sfbt": "sfbt",
    "sft": "sfbt",
    "narrative therapy": "narrative",
    "narrative": "narrative",
    "somatic experiencing": "se",
    "somatic therapy": "se",
    "se": "se",
    "person centered therapy": "pct",
    "person-centered therapy": "pct",
    "client centered therapy": "pct",
    "client-centered therapy": "pct",
    "rogerian": "pct",
    "pct": "pct",
    "psychodynamic therapy": "psychodynamic",
    "psychodynamic": "psychodynamic",
    "psychoanalytic": "psychodynamic",
    "play therapy": "play",
    "play": "play",
    "interpersonal psychotherapy": "ipt",
    "interpersonal therapy": "ipt",
    "ipt": "ipt",
    "trauma focused cbt": "tfcbt",
    "trauma-focused cbt": "tfcbt",
    "trauma focused cognitive behavioral therapy": "tfcbt",
    "tf-cbt": "tfcbt",
    "tfcbt": "tfcbt",
}


def _slugify(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def resolve_modality(name: str) -> dict[str, str] | None:
    """Return the catalog entry for a modality name/acronym, or None if unknown.

    None means OMIT — the caller must not emit a card without a real citation.
    """
    raw = (name or "").strip()
    if not raw:
        return None
    slug = _slugify(raw)
    compact = slug.replace(" ", "")
    key = _ALIASES.get(slug) or _ALIASES.get(compact)
    if key is None and slug in MODALITIES:
        key = slug
    if key is None:
        # fall back to a known badge code (e.g. "NT" -> narrative, "PDT" -> psychodynamic)
        key = _TAG_TO_SLUG.get(compact)
    if key is None:
        return None
    return MODALITIES[key]


# Badge-code lookup so a therapist can type the short tag (e.g. "NT", "PDT").
_TAG_TO_SLUG: dict[str, str] = {
    m["tag"].lower().replace("-", "").replace(" ", ""): slug
    for slug, m in MODALITIES.items()
}


def _split_modality_names(csv_or_list) -> list[str]:
    """Normalize a comma/slash/semicolon string OR a list into clean name tokens."""
    if isinstance(csv_or_list, str):
        return [p.strip() for p in re.split(r"[,/;]", csv_or_list) if p.strip()]
    return [str(p).strip() for p in (csv_or_list or []) if str(p).strip()]


def resolve_modalities_detail(csv_or_list) -> dict:
    """Resolve modality names AND report what could not be honestly resolved.

    Returns::

        {
          "listed":   [name, ...],   # the input, normalized to clean tokens
          "resolved": [entry, ...],  # order-preserved, de-duplicated catalog hits
          "dropped":  [name, ...],   # input names with NO real foundational
                                     # citation in the catalog — OMITTED, never
                                     # given a fabricated source (the refusal)
        }

    This is the machine-readable companion to ``resolve_modalities``: the engine
    already ENFORCES omit-not-fabricate; this lets the honesty receipt EMIT a
    record of exactly which listed modalities were dropped. A duplicate of an
    already-resolved modality is collapsed silently (a repeat, not a refusal);
    only genuinely-unknown names land in ``dropped``.
    """
    names = _split_modality_names(csv_or_list)
    resolved: list[dict[str, str]] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for n in names:
        entry = resolve_modality(n)
        if entry is None:
            dropped.append(n)
            continue
        if entry["tag"] in seen:
            continue  # duplicate of an already-resolved modality — not a refusal
        seen.add(entry["tag"])
        resolved.append(entry)
    return {"listed": names, "resolved": resolved, "dropped": dropped}


def resolve_modalities(csv_or_list) -> list[dict[str, str]]:
    """Resolve a comma string or list of modality names to known catalog entries.

    Preserves input order, de-duplicates, drops unknowns (omit-not-fabricate).
    Thin wrapper over ``resolve_modalities_detail`` (single source of truth) so
    the resolved list and the dropped record can never disagree.
    """
    return resolve_modalities_detail(csv_or_list)["resolved"]


# Set of all real citations, for the honesty linter to validate against.
KNOWN_CITATIONS: set[str] = {m["citation"] for m in MODALITIES.values()}


# --------------------------------------------------------------------------- #
# Generic, no-LLM "how I work" method bank (the honest floor).
# 6 steps: regulate -> notice -> understand -> practice -> integrate -> sustain.
# Each: (letter, name, num, subtitle, science, practice_line).
# Honest, general, makes no proprietary or efficacy claim. Passes the linter.
# --------------------------------------------------------------------------- #
GENERIC_METHOD_STEPS: list[tuple[str, str, str, str, str, str]] = [
    ("S", "Settle", "01", "Steady the body before the mind",
     "When something hard hits, the body shifts into a stress response and the "
     "thinking brain goes partly offline. The first move is to help your nervous "
     "system register that it is safe enough to work, using the breath and the "
     "senses. You cannot reason your way out of a state you have not first calmed.",
     "Try slow exhales — in for four, out for six — for two minutes, and name "
     "five things you can see and four you can touch."),
    ("N", "Notice", "02", "Name the pattern, not a verdict",
     "Reactions that run on autopilot feel like plain fact. Noticing means "
     "catching the pattern as it happens and naming it without turning it into a "
     "character flaw. Putting words to an internal state reliably takes some of "
     "the heat out of it.",
     "When you feel the surge, finish this on paper: \"Here is the part of me "
     "that is trying to help by ____.\""),
    ("U", "Understand", "03", "Trace where it learned to protect you",
     "Patterns are rarely random; most were useful somewhere, often long ago. "
     "Understanding connects a present reaction to the history that trained it. "
     "Context turns \"what is wrong with me\" into \"this makes sense, and it can "
     "change.\"",
     "Ask of the reaction: when did this first become a useful thing to do, and "
     "is that still true now?"),
    ("P", "Practice", "04", "Build a different response on purpose",
     "Insight alone rarely changes a habit. Once the body is steadier and the "
     "pattern is clear, we rehearse a specific alternative — a small, concrete "
     "move that fits what you actually value rather than the old reflex.",
     "Name one small action this week that the calmer, wiser version of you "
     "would take, and schedule it."),
    ("I", "Integrate", "05", "Carry it into real situations",
     "A new response is fragile until it has been tried under real conditions. "
     "Integrating means using the skill on ordinary days — not just in session — "
     "so it is available on the hard ones, the way any skill consolidates through "
     "use.",
     "Pick one routine situation this week and run the new response there, while "
     "the stakes are low."),
    ("S", "Sustain", "06", "Make the change durable",
     "Lasting change is less about intensity and more about repetition and "
     "review. Sustaining means noticing what is holding, adjusting what is not, "
     "and keeping the practice going long enough that it becomes the default.",
     "At week's end, note one moment the new response showed up on its own — "
     "that is the change taking root."),
]

# Generic 3-phase journey bank (the honest floor when there is no signature
# program). Each: (name, paragraph). Week ranges are computed by the generator
# from the practice's stated program duration.
GENERIC_JOURNEY_PHASES: list[tuple[str, str]] = [
    ("Foundation",
     "Assessment, history, and getting the most disruptive symptom under enough "
     "control to do the work. We build the working alliance, agree on what we are "
     "tracking, and establish a baseline so progress is something we can both see."),
    ("Core work",
     "The main work of change: identifying the patterns that have been running "
     "the show, tracing where they came from, and practicing different responses. "
     "The pace is set by you, and we revisit the measures as we go."),
    ("Consolidation",
     "Rehearsal under real conditions, relapse prevention, and a plan for "
     "autonomy. We re-measure, name what has shifted, and make sure you leave "
     "with the structure you came in needing — steadier than you started."),
]


# --------------------------------------------------------------------------- #
# Crisis-line defaults (US national, always safe to show). The template ships
# 988 logic separately; these populate the two configurable crisis_line slots.
# --------------------------------------------------------------------------- #
CRISIS_LINES_US = {
    "crisis_line_1_label": "988 Suicide & Crisis Lifeline",
    "crisis_line_1_number": "Call or text 988",
    "crisis_line_2_label": "Crisis Text Line",
    "crisis_line_2_number": "Text HOME to 741741",
}


# --------------------------------------------------------------------------- #
# Credential full-name map (abbrev -> full). Used by build_practice.py.
# --------------------------------------------------------------------------- #
CREDENTIAL_FULL = {
    "LCSW": "Licensed Clinical Social Worker",
    "LICSW": "Licensed Independent Clinical Social Worker",
    "LCSW-C": "Licensed Certified Social Worker–Clinical",
    "LMSW": "Licensed Master Social Worker",
    "LISW": "Licensed Independent Social Worker",
    "LPC": "Licensed Professional Counselor",
    "LPCC": "Licensed Professional Clinical Counselor",
    "LCPC": "Licensed Clinical Professional Counselor",
    "LMHC": "Licensed Mental Health Counselor",
    "LMFT": "Licensed Marriage and Family Therapist",
    "LCMFT": "Licensed Clinical Marriage and Family Therapist",
    "PsyD": "Doctor of Psychology",
    "PhD": "Licensed Psychologist",
    "LP": "Licensed Psychologist",
    "PMHNP": "Psychiatric Mental Health Nurse Practitioner",
}


if __name__ == "__main__":
    # Self-test: prove resolution, omission, and bank integrity.
    import json
    import sys

    failures = []

    # 1) every modality resolves by its own name + tag
    for slug, m in MODALITIES.items():
        if resolve_modality(m["name"]) is None:
            failures.append(f"name did not resolve: {m['name']}")
        if resolve_modality(m["tag"]) is None:
            failures.append(f"tag did not resolve: {m['tag']}")

    # 2) unknown modality is OMITTED, not fabricated
    for unknown in ("Reiki", "Astrology Therapy", "Quantum Healing", ""):
        if resolve_modality(unknown) is not None:
            failures.append(f"fabricated a citation for unknown: {unknown!r}")

    # 3) csv resolution dedups + drops unknowns
    got = resolve_modalities("CBT, cbt, EMDR, Reiki, Gottman Method")
    tags = [g["tag"] for g in got]
    if tags != ["CBT", "EMDR", "Gottman"]:
        failures.append(f"csv resolve wrong: {tags}")

    # 4) banks are the right shape
    if len(GENERIC_METHOD_STEPS) != 6:
        failures.append("GENERIC_METHOD_STEPS must have 6 steps")
    if len(GENERIC_JOURNEY_PHASES) != 3:
        failures.append("GENERIC_JOURNEY_PHASES must have 3 phases")
    if len(KNOWN_CITATIONS) != len(MODALITIES):
        failures.append("KNOWN_CITATIONS count mismatch")

    # 5) no banned efficacy language hiding in our own banks
    banned = ("proven", "guaranteed", "studies show", "100%", "cure ")
    blob = json.dumps(
        [MODALITIES, GENERIC_METHOD_STEPS, GENERIC_JOURNEY_PHASES]
    ).lower()
    for b in banned:
        if b in blob:
            failures.append(f"banned phrase in banks: {b!r}")

    if failures:
        print("CITATIONS SELF-TEST FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(
        f"citations.py OK — {len(MODALITIES)} modalities, "
        f"{len(_ALIASES)} aliases, generic method/journey banks intact, "
        f"no banned language."
    )
