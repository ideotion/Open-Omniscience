"""
Reconcile existing catalog domains against Wikidata to fill ``source_type``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Only 2% of catalog sources carry a ``source_type`` today. Wikidata (CC0) records
the *kind* of an organisation as ``instance of`` (P31) — newspaper, news agency,
magazine, public broadcaster, scientific journal, … — which maps deterministically
onto our controlled ``source_type`` vocabulary. This module is the PURE layer:
it builds the API queries and parses the JSON, with an anti-fabrication gate baked
in — a candidate entity is accepted ONLY when its official website (P856) resolves
to the same registrable domain as the catalog source. A name search that lands on
the wrong entity therefore yields nothing rather than a wrong type.

The actual HTTP lives in scripts/enrich_sources_wikidata.py (Wikidata is egress-
restricted in the sandbox/CI, so the fetch runs on a networked machine — same as
build_world_news_catalog.py and generate_wikidata_rings.py). This stays
unit-testable with no network.

What it deliberately does NOT infer: political lean (Wikidata has none),
fine-grained topics (subject/genre QIDs need label resolution and map noisily —
left to the corpus-fingerprint and LLM strategies), and country/language (the
ccTLD pass + catalog already cover these). Scope = the deterministic win.
"""

from __future__ import annotations

import urllib.parse

from src.catalog.normalize import registrable_domain

_API = "https://www.wikidata.org/w/api.php"

# P31 (instance of) QID -> our controlled source_type. Subclasses are NOT expanded
# here (the API gives the direct P31 values); the common direct types are listed.
#
# DISCIPLINE (no fabricated data): every QID below is either already verified in
# the repo's own configs/catalog_query.yml, or a stable, well-known Wikidata class
# (Q5633421 scientific journal). The three marked "(verify)" mirror catalog_query's
# own tentative entries. To EXTEND this map, confirm the class QID on wikidata.org
# during the networked run before adding it — a wrong QID->type pair would mislabel
# a correctly-matched entity (the domain gate guards the entity, not the mapping).
P31_SOURCE_TYPE: dict[str, str] = {
    "Q11032": "news",            # newspaper
    "Q1110794": "news",          # daily newspaper
    "Q1153191": "news",          # online newspaper
    "Q192283": "wire-agency",    # news agency
    "Q41298": "magazine",        # magazine
    "Q1002697": "magazine",      # periodical (magazines etc.)
    "Q1616075": "broadcaster",   # television station
    "Q14350": "broadcaster",     # radio station
    "Q15265344": "broadcaster",  # broadcaster
    "Q5633421": "scientific-journal",  # scientific journal (stable class)
    "Q327333": "government-primary",   # government agency        (verify)
    "Q1530022": "religious",     # religious organization        (verify)
    "Q13414953": "religious",    # religious denomination        (verify)
}

# P31 QIDs that ALSO imply an ownership tag (funding/control), conservative set.
P31_OWNERSHIP: dict[str, str] = {
    "Q192283": "wire-agency",    # news agency
}


def wbsearch_url(name: str, lang: str = "en", limit: int = 5) -> str:
    """Search Wikidata for an outlet by name (a few candidates to disambiguate)."""
    qs = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": name, "language": lang,
         "format": "json", "limit": limit, "type": "item"}
    )
    return f"{_API}?{qs}"


def wbentities_url(qids: list[str]) -> str:
    """Fetch claims for one or more QIDs (P31 + P856 are what we read)."""
    qs = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": "|".join(qids), "props": "claims",
         "format": "json"}
    )
    return f"{_API}?{qs}"


def parse_search_qids(payload: dict) -> list[str]:
    """All candidate QIDs from a wbsearchentities response, in rank order."""
    return [r.get("id") for r in (payload.get("search") or []) if r.get("id")]


def _claim_values(entity: dict, prop: str) -> list:
    out = []
    for c in (entity.get("claims") or {}).get(prop, []) or []:
        dv = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if dv is not None:
            out.append(dv)
    return out


def entity_domains(entity: dict) -> set[str]:
    """Registrable domains of the entity's official websites (P856)."""
    out: set[str] = set()
    for v in _claim_values(entity, "P856"):
        url = v if isinstance(v, str) else None
        d = registrable_domain(url)
        if d:
            out.add(d)
    return out


def entity_p31(entity: dict) -> list[str]:
    """The entity's ``instance of`` (P31) QIDs."""
    out: list[str] = []
    for v in _claim_values(entity, "P31"):
        qid = v.get("id") if isinstance(v, dict) else None
        if qid:
            out.append(qid)
    return out


def reconcile(payload: dict, qid: str, *, expected_domain: str) -> dict | None:
    """Enrichment for ``qid`` from a wbgetentities payload, or None.

    Returns None unless the entity's official website matches ``expected_domain``
    (the anti-fabrication gate) AND at least one P31 maps to a source_type.
    """
    entity = (payload.get("entities") or {}).get(qid) or {}
    dom = registrable_domain(expected_domain)
    if not dom or dom not in entity_domains(entity):
        return None  # wrong entity (or no website to verify) — never guess
    p31 = entity_p31(entity)
    source_type = next((P31_SOURCE_TYPE[q] for q in p31 if q in P31_SOURCE_TYPE), None)
    if not source_type:
        return None  # known entity but not a media type we map — leave untouched
    row: dict = {
        "domain": dom,
        "source_type": source_type,
        "confidence": "high",
        "note": f"wikidata:{qid}",
    }
    ownership = next((P31_OWNERSHIP[q] for q in p31 if q in P31_OWNERSHIP), None)
    if ownership:
        row["ownership"] = ownership
    return row
