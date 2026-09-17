"""The PURE Wikidata-ring core: URLs in, rings out. No sockets, no database.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

**WHY THIS IS A MODULE AND NOT TWO COPIES.** These builders and parsers were written
inside ``scripts/generate_wikidata_rings.py``, where they were the only consumer. ``S6``
gives them a second one -- the in-app, consented ring load (Q406 = b) -- and a ring URL
shape copied into ``src/`` is exactly the drift ``equivalence.shipped_rings_paths`` was
made public to prevent ("a second copy of these two paths in ``src/backup/`` is how a
file gets added here and forgotten there"). So the core moved HERE and the script
imports it: one definition of what a ring request looks like, one parser, one ring
shape, and the script's own suite goes on proving it.

**IT IS NOT ``src/catalog/wikidata_enrich.py``, DELIBERATELY.** That module has
functions with two of the same NAMES (``wbsearch_url``, ``wbentities_url``) and a
different job: it asks for ``props=claims`` to read P31/P856 and type a news source,
where this asks for ``props=labels|aliases`` in twelve languages to build a ring. Fusing
them would mean a props argument threaded through two unrelated features so that one
line could be shared -- a coupling, not a deduplication. They are named here so the next
reader finds this paragraph instead of "fixing" it.

Nothing in this module opens a socket. The caller supplies the fetch, which is what lets
the script use stdlib ``urllib`` on a networked machine and the in-app job use the
kill-switch-aware ``guarded_session`` -- two transports, one set of meanings.
"""

from __future__ import annotations

import urllib.parse

#: The app's UI languages = the pre-translation scope. ``zh``/``ja`` are included for
#: completeness though their keyword extraction is segmentation-limited today.
LANGS: tuple[str, ...] = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

API_ENDPOINT = "https://www.wikidata.org/w/api.php"

#: R8, 2026-09-12: "automated Wikidata downloads respect <= 1 request per 10 seconds."
#: The number lives here because both consumers owe it and a rate two callers each hold
#: their own copy of is a rate one of them will quietly relax.
POLITE_SLEEP_S = 10.0


def wbsearch_url(term: str, lang: str = "en") -> str:
    """Search Wikidata for one concept, IN ITS OWN LANGUAGE.

    The search language matters and the ring language does not depend on it: a concept
    prominent only in ar/zh/ru resolves to a QID when searched in that language, and
    :func:`wbentities_url` then pulls labels for all twelve regardless. Searching
    everything in English is how a ring table comes out anglicised.
    """
    qs = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": term, "language": lang,
         "format": "json", "limit": 1, "type": "item"}
    )
    return f"{API_ENDPOINT}?{qs}"


def wbentities_url(qid: str, langs: tuple[str, ...] = LANGS) -> str:
    """Labels AND aliases for one item in ``langs`` -- the translations and the synonyms."""
    qs = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": qid, "props": "labels|aliases",
         "languages": "|".join(langs), "format": "json"}
    )
    return f"{API_ENDPOINT}?{qs}"


def parse_search(payload: dict) -> str | None:
    """The first search result's QID, or None."""
    results = payload.get("search") or []
    return results[0].get("id") if results else None


def parse_entity(payload: dict, qid: str, langs: tuple[str, ...] = LANGS) -> dict[str, list[str]]:
    """``{lang: [label, *aliases]}`` for the languages present (label + synonyms)."""
    ent = (payload.get("entities") or {}).get(qid) or {}
    labels = ent.get("labels") or {}
    aliases = ent.get("aliases") or {}
    out: dict[str, list[str]] = {}
    for lang in langs:
        terms: list[str] = []
        lab = (labels.get(lang) or {}).get("value")
        if lab:
            terms.append(lab)
        for al in aliases.get(lang, []) or []:
            if al.get("value"):
                terms.append(al["value"])
        seen: set[str] = set()
        uniq: list[str] = []
        for t in terms:
            k = t.casefold()
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        if uniq:
            out[lang] = uniq
    return out


def slug(s: str) -> str:
    """A ring id from a label: lowercase alphanumerics, single hyphens."""
    return "-".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def build_ring(seed: str, qid: str, lang_terms: dict[str, list[str]]) -> dict | None:
    """A ring ``{id, qid, members:["lang:term", ...]}``, or None if fewer than 2 languages.

    The refusal is the point: a one-language ring merges nothing, so writing it would add
    a row that asserts a cross-language equivalence it does not have.
    """
    members = [f"{lang}:{t}" for lang, terms in lang_terms.items() for t in terms]
    if len({m.split(":", 1)[0] for m in members}) < 2:
        return None
    en = lang_terms.get("en") or [seed]
    return {"id": slug(en[0]) or qid.lower(), "qid": qid, "members": members}
