"""
Entity extractor — people and organizations, the third axis of space–time–WHO
(maintainer-ruled 2026-06-11). Treated as two SEPARATE classes by design: an
article about a person resists placement in space; an organization often
anchors to places differently — conflating them would blur both.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Explainable lexical heuristics, no NER model, bounded, snippet provenance,
every candidate marked deduced. Noisier than the date/location extractors by
nature — the notes say which rule fired so a human can judge.
"""

from __future__ import annotations

import re

_MAX_SCAN = 60_000

# Honorifics that PRECEDE a person's name (high-precision person signal).
_HONORIFIC = (
    r"(?:President|Prime Minister|Chancellor|Minister|Senator|Governor|Mayor|"
    r"Mr|Mrs|Ms|Dr|Sir|Dame|Pope|King|Queen|Prince|Princess|General|Colonel|"
    r"Président|Présidente|Premier ministre|Chancelier|Ministre|Sénateur|Maire|"
    r"M\.|Mme|Herr|Frau|Señor|Señora)"
)
_PERSON_HONORIFIC_RE = re.compile(
    rf"\b{_HONORIFIC}\s+([A-ZÀ-Þ][\w'’-]+(?:\s+[A-ZÀ-Þ][\w'’-]+)?)"
)
# "Firstname Lastname" shape: two TitleCase words preceded by a LOWERCASE-
# initial word (excludes sentence openers AND TitleCase runs like headlines).
_PERSON_SHAPE_RE = re.compile(
    r"\b[a-zà-þ][\w'’-]*[,;:]?\s+([A-ZÀ-Þ][a-zà-þ'’-]{2,})\s+([A-ZÀ-Þ][a-zà-þ'’-]{2,})\b"
)
# Organization tails (en/fr/de) + institutional heads.
_ORG_TAIL = (
    r"(?:Inc|Corp|Corporation|Ltd|LLC|PLC|SA|SE|AG|GmbH|SAS|SpA|NV|"
    r"Company|Group|Groupe|Bank|Banque|University|Université|Institute|Institut|"
    r"Ministry|Ministère|Agency|Agence|Authority|Commission|Committee|Comité|"
    r"Council|Conseil|Court|Cour|Police|Army|Armée|Parliament|Parlement|"
    r"Organization|Organisation|Association|Federation|Fédération|Union|Party|Parti)"
)
_ORG_RE = re.compile(
    rf"\b((?:[A-ZÀ-Þ][\w'’&.-]+\s+){{0,3}}{_ORG_TAIL})(?![\w-])"
)
# Standalone acronyms (UN, NATO, FIFA, OPEC…): 2–6 caps, must repeat to count.
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")
_ACRONYM_STOP = frozenset(
    "I A AN THE OK USA UK EU US AI IT TV PDF HTML HTTP HTTPS API URL CEO CFO "
    "GDP USD EUR GBP AM PM Q1 Q2 Q3 Q4 COVID".split()
)
# Leading determiners never belong to the canonical org name.
_DETERMINERS = frozenset("the le la les l' der die das el los las un une una".split())


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)].replace("\n", " ").strip()


def extract_entities(text: str, *, limit: int = 6) -> dict:
    """``{"people": [...], "organizations": [...]}`` — DEDUCED candidates.

    Each entry: ``{name, mentions, snippet, note}``, ordered by mentions.
    People and organizations are separate lists by design (the maintainer's
    space–time–who ruling): they answer different questions and anchor to
    space differently. A name claimed by the organization rules never doubles
    as a person.
    """
    if not text:
        return {"people": [], "organizations": []}
    text = text[:_MAX_SCAN]

    orgs: dict[str, dict] = {}
    for m in _ORG_RE.finditer(text):
        toks = m.group(1).split()
        while len(toks) > 1 and toks[0].lower() in _DETERMINERS:
            toks = toks[1:]  # "The Finance Ministry" -> "Finance Ministry"
        name = " ".join(toks)
        key = name.lower()
        if key in orgs:
            orgs[key]["mentions"] += 1
        else:
            orgs[key] = {
                "name": name,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced: capitalized phrase ending in an organization word",
            }
    acro_counts: dict[str, int] = {}
    acro_first: dict[str, re.Match] = {}
    for m in _ACRONYM_RE.finditer(text):
        a = m.group(1)
        if a in _ACRONYM_STOP:
            continue
        acro_counts[a] = acro_counts.get(a, 0) + 1
        acro_first.setdefault(a, m)
    for a, n in acro_counts.items():
        if n >= 2 and a.lower() not in orgs:  # repetition required: one-off caps stay out
            m = acro_first[a]
            orgs[a.lower()] = {
                "name": a,
                "mentions": n,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced: repeated acronym (organization assumed, unverified)",
            }

    org_words = {w.lower() for o in orgs.values() for w in o["name"].split()}
    people: dict[str, dict] = {}

    def _add_person(name: str, m: re.Match, note: str) -> None:
        name = " ".join(name.split())
        key = name.lower()
        if any(w.lower() in org_words for w in name.split()):
            return  # claimed by an organization — never double-classed
        if key in people:
            people[key]["mentions"] += 1
        else:
            people[key] = {
                "name": name,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": note,
            }

    for m in _PERSON_HONORIFIC_RE.finditer(text):
        _add_person(m.group(1), m, "deduced: name following an honorific/title")
    for m in _PERSON_SHAPE_RE.finditer(text):
        _add_person(
            f"{m.group(1)} {m.group(2)}", m,
            "deduced: mid-sentence Firstname-Lastname shape (weakest rule)",
        )

    rank = lambda d: sorted(d.values(), key=lambda e: -e["mentions"])[:limit]  # noqa: E731
    return {"people": rank(people), "organizations": rank(orgs)}
