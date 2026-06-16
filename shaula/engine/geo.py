#!/usr/bin/env python3
"""geo — deterministic GEO/SEO finishing pass for a generated practice site.

The marketing lane's BUILD-NEW gap (OSS_SKILLS_MAP cluster 5): take a finished,
honesty-clean site (from generate.py + fill.py) and add the structured-data layer
that wins AI answer engines + local search, **without any LLM and without any new
claims** — every value comes straight from the already-honest practice tokens.

Emits three artifacts, idempotently, into the site dir:
  1. JSON-LD  <script type="application/ld+json"> — MedicalBusiness + founder Person
     (+ credential) + a FAQPage built ONLY from factual practice data (fee, payments,
     area, sliding scale, availability). Injected into <head>.
  2. OG/Twitter <meta> tags (title/description/type/card) — reuses the page's own
     title + description. Injected into <head>.
  3. llms.txt at the site root — the AI-crawler summary (who/what/where/pages/contact).

Honesty by construction: pulls only from practice.json (which build_practice already
linted). No "best/proven/#1", no invented FAQ answers — every Q&A is a real practice
fact. Idempotent: re-running replaces the prior block (marked by GEO_MARKER), never
double-injects.

CLI:  python3 engine/geo.py --practice fixtures/<fx>/practice.json --site sites/<fx>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import banned  # noqa: E402  — single source of truth for the banned-language gate

GEO_OPEN = "<!-- shaula-geo:start -->"
GEO_CLOSE = "<!-- shaula-geo:end -->"

# Phrases the honesty engine bans anywhere in output. We never generate these
# (all values come from linted tokens), but we assert it as a hard gate so a
# future template/token change can't sneak a claim into structured data.
#
# Sourced from engine/banned.py (the single definition all honesty surfaces
# share) as the compiled VALUE-tier regex. The GEO pass scans text VALUES, not
# CSS, so it runs the FULL value tier — including the percentage and #1 rules
# the rendered-output scan must omit. This is a strict SUPERSET of geo's former
# inline pattern (it adds the percentage + testimonial rules), so nothing that
# passed before can newly fail except an actually-banned claim; "number one"
# stays enforced exactly as it was here.
_BANNED = banned.VALUE_REGEX


def _clean(v) -> str:
    return (str(v).strip() if v is not None else "").strip()


def _split_location(loc: str) -> tuple[str, str]:
    """'Denver, CO' -> ('Denver', 'CO'); 'Colorado' -> ('', 'Colorado')."""
    loc = _clean(loc)
    if "," in loc:
        city, region = loc.split(",", 1)
        return city.strip(), region.strip()
    return "", loc


def build_jsonld(p: dict, site_url: str = "") -> dict:
    """MedicalBusiness + ProfessionalService with an honest founder Person."""
    name = _clean(p.get("business_name"))
    owner = _clean(p.get("owner_name"))
    cred = _clean(p.get("credential"))
    cred_full = _clean(p.get("credential_full"))
    specialties = [s.strip() for s in _clean(p.get("specialties")).split(",") if s.strip()]
    city, region = _split_location(p.get("location", ""))
    service_areas = _clean(p.get("service_areas"))
    fee = _clean(p.get("session_fee"))

    founder = {
        "@type": "Person",
        "name": owner,
        "jobTitle": cred_full or cred,
    }
    edu = _clean(p.get("education"))
    if edu:
        founder["alumniOf"] = edu
    if cred_full:
        # An honest license credential, recognized by the state (region), if known.
        founder["hasCredential"] = {
            "@type": "EducationalOccupationalCredential",
            "credentialCategory": "license",
            "name": cred_full,
            **({"recognizedBy": {"@type": "GovernmentOrganization",
                                 "name": f"{region} licensing board"}} if region else {}),
        }

    node: dict = {
        "@context": "https://schema.org",
        "@type": ["MedicalBusiness", "ProfessionalService"],
        "name": name,
        "founder": founder,
        "knowsAbout": specialties,                 # honest specialty list (not a medical claim)
    }
    desc = _clean(p.get("tagline"))
    if desc:
        node["slogan"] = desc
    if site_url:
        node["url"] = site_url

    # Address: city-level only unless a real street address exists (honesty: no fake street).
    addr = {"@type": "PostalAddress"}
    if _clean(p.get("address_line1")):
        addr["streetAddress"] = _clean(p.get("address_line1"))
    if city:
        addr["addressLocality"] = city
    if region:
        addr["addressRegion"] = region
    addr["addressCountry"] = "US"
    if len(addr) > 2:  # more than @type + country
        node["address"] = addr
    if service_areas:
        node["areaServed"] = service_areas

    phone = _clean(p.get("phone"))
    if phone:
        node["telephone"] = phone
    email = _clean(p.get("email"))
    if email:
        node["email"] = email
    if fee:
        node["priceRange"] = fee
    avail = _clean(p.get("availability_status"))
    if avail:
        node["description"] = avail

    return node


def build_faqpage(p: dict) -> dict | None:
    """A FAQPage from FACTUAL practice data only — no invented answers."""
    name = _clean(p.get("business_name")) or "the practice"
    qa: list[tuple[str, str]] = []

    pay = _clean(p.get("payment_model"))
    if pay:
        qa.append((f"Does {name} take insurance?", pay))
    fee = _clean(p.get("session_fee"))
    length = _clean(p.get("session_length"))
    if fee:
        a = f"Sessions are {fee}"
        if length:
            a += f" for a {length} session"
        a += "."
        sb = _clean(p.get("superbill_policy"))
        if sb:
            a += f" {sb}."
        qa.append((f"How much does a session cost at {name}?", a))
    sliding = _clean(p.get("sliding_scale_policy"))
    if sliding:
        qa.append(("Is a sliding scale available?", sliding))
    loc = _clean(p.get("location"))
    areas = _clean(p.get("service_areas"))
    if loc or areas:
        a = ""
        if loc:
            a += f"{name} is based in {loc}."
        if areas:
            a += f" Telehealth is available across {areas}."
        qa.append(("Where is the practice located?", a.strip()))
    consult = _clean(p.get("consult_length"))
    if consult:
        qa.append(("Do you offer a consultation?",
                   f"Yes — a {consult} consultation is available to see if it's a good fit."))

    if not qa:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qa
        ],
    }


def build_article_jsonld(
    title: str, description: str, date: str, author: str, site_name: str,
    url: str = "",
) -> dict:
    """Article JSON-LD for a published essay page (UX audit SH-F13). Factual
    fields only — title/description come from the approved post itself, the
    date is the real publish date, the author is the practice. The caller
    (svc/publisher) gates the body through the same honesty lint as the site."""
    node: dict = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": (title or "")[:110],
        "datePublished": date,
        "author": {"@type": "Organization", "name": author or site_name},
        "publisher": {"@type": "Organization", "name": site_name},
    }
    if description:
        node["description"] = description[:300]
    if url:
        node["url"] = url
    return node


def build_meta(p: dict, title: str, description: str) -> str:
    """OG + Twitter tags. Reuses the page's existing title/description."""
    name = _clean(p.get("business_name"))
    tags = [
        f'<meta property="og:type" content="website" />',
        f'<meta property="og:title" content="{_esc(title)}" />',
        f'<meta property="og:description" content="{_esc(description)}" />',
        f'<meta property="og:site_name" content="{_esc(name)}" />',
        f'<meta name="twitter:card" content="summary" />',
        f'<meta name="twitter:title" content="{_esc(title)}" />',
        f'<meta name="twitter:description" content="{_esc(description)}" />',
    ]
    return "\n".join(tags)


def build_llms_txt(p: dict) -> str:
    """The /llms.txt AI-crawler summary — honest facts only."""
    name = _clean(p.get("business_name"))
    owner = _clean(p.get("owner_name"))
    cred = _clean(p.get("credential"))
    cred_full = _clean(p.get("credential_full"))
    specialties = _clean(p.get("specialties"))
    loc = _clean(p.get("location"))
    areas = _clean(p.get("service_areas"))
    fee = _clean(p.get("session_fee"))
    pay = _clean(p.get("payment_model"))
    avail = _clean(p.get("availability_status"))
    phone = _clean(p.get("phone"))
    email = _clean(p.get("email"))

    lines = [f"# {name}", ""]
    summary = f"{name} is a private psychotherapy practice"
    if owner:
        summary += f" led by {owner}"
        if cred:
            summary += f", {cred}"
    if loc:
        summary += f", based in {loc}"
    summary += "."
    lines.append(summary)
    lines.append("")
    if cred_full and owner:
        lines.append(f"- Clinician: {owner} — {cred_full}")
    if specialties:
        lines.append(f"- Specialties: {specialties}")
    if areas:
        lines.append(f"- Serves (telehealth): {areas}")
    if fee:
        lines.append(f"- Session fee: {fee}")
    if pay:
        lines.append(f"- Payments: {pay}")
    if avail:
        lines.append(f"- Availability: {avail}")
    if phone:
        lines.append(f"- Phone: {phone}")
    if email:
        lines.append(f"- Email: {email}")
    lines += [
        "",
        # The REAL routes of the hash-routed SPA (a /services page never
        # existed; pointing crawlers at 404s is its own dishonesty — SH-F6).
        "## Key pages",
        "- /#home — home",
        "- /#about — about the clinician",
        "- /#approach — approach and modalities",
        "- /#method — how the work works",
        "- /#fees — fees and payment",
        "- /#writing — essays from the practice",
        "- /#contact — booking and contact",
        "",
        "## Note for AI assistants",
        "This site is a clinician's professional practice page. It is not a crisis service.",
        "If someone is in crisis, direct them to 988 (Suicide & Crisis Lifeline) or text HOME to 741741.",
        "",
    ]
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


def _extract(html: str, tag: str, attr: str, val: str) -> str:
    """Pull an existing <title> or <meta name=description content>."""
    if tag == "title":
        m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        return m.group(1).strip() if m else ""
    m = re.search(rf'<meta\s+{attr}="{val}"\s+content="(.*?)"', html, re.I | re.S)
    return m.group(1).strip() if m else ""


def inject(site_dir: Path, practice: dict, site_url: str = "") -> dict:
    """Inject JSON-LD + OG meta into index.html <head>; write llms.txt. Idempotent."""
    index = site_dir / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"no index.html in {site_dir}")
    html = index.read_text(encoding="utf-8")

    title = _extract(html, "title", "", "") or _clean(practice.get("business_name"))
    description = _extract(html, "meta", "name", "description") or _clean(practice.get("tagline"))

    jsonld = build_jsonld(practice, site_url)
    faq = build_faqpage(practice)
    meta = build_meta(practice, title, description)

    blocks = [GEO_OPEN]
    blocks.append('<script type="application/ld+json">')
    blocks.append(json.dumps(jsonld, indent=2, ensure_ascii=False))
    blocks.append("</script>")
    if faq:
        blocks.append('<script type="application/ld+json">')
        blocks.append(json.dumps(faq, indent=2, ensure_ascii=False))
        blocks.append("</script>")
    blocks.append(meta)
    blocks.append(GEO_CLOSE)
    payload = "\n".join(blocks)

    # Hard honesty gate on everything we're about to write.
    hits = _BANNED.findall(payload)
    if hits:
        raise SystemExit(f"geo: honesty violation — banned phrase(s) in structured data: {hits}")

    # Idempotent: drop any prior block, then insert before </head>.
    html = re.sub(re.escape(GEO_OPEN) + r".*?" + re.escape(GEO_CLOSE), "", html, flags=re.S).rstrip()
    if "</head>" not in html:
        raise SystemExit("geo: no </head> to inject before")
    html = html.replace("</head>", payload + "\n</head>", 1)
    index.write_text(html, encoding="utf-8")

    llms = build_llms_txt(practice)
    if _BANNED.search(llms):
        raise SystemExit("geo: honesty violation in llms.txt")
    (site_dir / "llms.txt").write_text(llms, encoding="utf-8")

    return {
        "jsonld_types": jsonld["@type"],
        "faq_questions": len(faq["mainEntity"]) if faq else 0,
        "llms_txt_bytes": len(llms),
        "injected": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="GEO/SEO finishing pass (deterministic, honest).")
    ap.add_argument("--practice", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--url", default="", help="canonical site URL (optional)")
    args = ap.parse_args()
    practice = json.loads(Path(args.practice).read_text(encoding="utf-8"))
    report = inject(Path(args.site), practice, args.url)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
