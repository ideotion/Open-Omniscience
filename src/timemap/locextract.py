"""
Location extractor — the spatial twin of the date extractor (maintainer-ruled
2026-06-11: time/place correlation per article).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Lexical, gazetteer-grounded, honest: a match is "this place NAME appears in the
text" — deduced, less reliable than source metadata, and always labelled so.
Cities come from the bundled gazetteer (coordinates included); countries from a
curated multilingual name table (coordinates only via their gazetteer stand-in
city, marked country-precision). Ambiguous city names prefer the article's
source country, else the most populous bearer — the choice is recorded.
No network, no NER model: explainable rules, snippet provenance, bounded.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Curated country names -> ISO alpha-2 (English + French + common native/short
# forms). Newsworthy-coverage oriented; extend batch-by-batch from field logs.
_COUNTRY_NAMES: dict[str, str] = {
    "united states": "us", "états-unis": "us", "etats-unis": "us", "usa": "us",
    "america": "us", "amérique": "us",
    "united kingdom": "gb", "royaume-uni": "gb", "britain": "gb", "uk": "gb",
    "france": "fr", "germany": "de", "allemagne": "de", "deutschland": "de",
    "spain": "es", "espagne": "es", "españa": "es", "italy": "it", "italie": "it",
    "italia": "it", "portugal": "pt", "netherlands": "nl", "pays-bas": "nl",
    "belgium": "be", "belgique": "be", "switzerland": "ch", "suisse": "ch",
    "austria": "at", "autriche": "at", "poland": "pl", "pologne": "pl",
    "ukraine": "ua", "russia": "ru", "russie": "ru", "belarus": "by",
    "china": "cn", "chine": "cn", "japan": "jp", "japon": "jp",
    "india": "in", "inde": "in", "pakistan": "pk", "bangladesh": "bd",
    "iran": "ir", "iraq": "iq", "irak": "iq", "israel": "il", "israël": "il",
    "palestine": "ps", "gaza": "ps", "lebanon": "lb", "liban": "lb",
    "syria": "sy", "syrie": "sy", "turkey": "tr", "turquie": "tr",
    "saudi arabia": "sa", "arabie saoudite": "sa", "qatar": "qa",
    "united arab emirates": "ae", "émirats arabes unis": "ae", "yemen": "ye",
    "egypt": "eg", "égypte": "eg", "libya": "ly", "libye": "ly",
    "algeria": "dz", "algérie": "dz", "morocco": "ma", "maroc": "ma",
    "tunisia": "tn", "tunisie": "tn", "nigeria": "ng", "ethiopia": "et",
    "kenya": "ke", "south africa": "za", "afrique du sud": "za",
    "congo": "cd", "sudan": "sd", "soudan": "sd", "mali": "ml", "niger": "ne",
    "canada": "ca", "mexico": "mx", "mexique": "mx", "brazil": "br",
    "brésil": "br", "brasil": "br", "argentina": "ar", "argentine": "ar",
    "chile": "cl", "chili": "cl", "colombia": "co", "colombie": "co",
    "venezuela": "ve", "peru": "pe", "pérou": "pe", "cuba": "cu", "haiti": "ht",
    "haïti": "ht", "australia": "au", "australie": "au",
    "new zealand": "nz", "nouvelle-zélande": "nz", "indonesia": "id",
    "indonésie": "id", "philippines": "ph", "vietnam": "vn", "viêt nam": "vn",
    "thailand": "th", "thaïlande": "th", "myanmar": "mm", "birmanie": "mm",
    "south korea": "kr", "corée du sud": "kr", "north korea": "kp",
    "corée du nord": "kp", "taiwan": "tw", "taïwan": "tw",
    "afghanistan": "af", "kazakhstan": "kz", "georgia": "ge", "géorgie": "ge",
    "armenia": "am", "arménie": "am", "azerbaijan": "az", "azerbaïdjan": "az",
    "greece": "gr", "grèce": "gr", "sweden": "se", "suède": "se",
    "norway": "no", "norvège": "no", "finland": "fi", "finlande": "fi",
    "denmark": "dk", "danemark": "dk", "ireland": "ie", "irlande": "ie",
    "hungary": "hu", "hongrie": "hu", "romania": "ro", "roumanie": "ro",
    "serbia": "rs", "serbie": "rs", "czechia": "cz", "tchéquie": "cz",
}

_MAX_SCAN = 60_000  # characters of text scanned (bounded, like every scan)


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str, str]]:
    """[(compiled pattern, canonical name, kind)] for countries + gazetteer cities."""
    pats: list[tuple[re.Pattern, str, str]] = []
    for name in sorted(_COUNTRY_NAMES, key=len, reverse=True):
        pats.append((re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), name, "country"))
    from src.catalog.cities import load_cities

    for c in load_cities():
        pats.append((re.compile(rf"\b{re.escape(c.name)}\b"), c.name, "city"))  # case-sensitive
    return pats


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)].replace("\n", " ").strip()


def extract_locations(
    text: str, *, source_country: str | None = None, limit: int = 6
) -> list[dict]:
    """Place names appearing in ``text`` — DEDUCED candidates with provenance.

    Returns up to ``limit`` of ``{name, country, kind, mentions, snippet, lat?, lon?,
    note}`` ordered by mention count. City matches are case-sensitive (capitalised
    as place names are) to dodge common-word collisions; country names match
    case-insensitively (Iran/IRAN/iran all refer to the country). An ambiguous
    city prefers the article's source country, else the most populous bearer —
    and says which rule decided.
    """
    if not text:
        return []
    text = text[:_MAX_SCAN]
    from src.catalog.cities import build_index, load_cities, lookup

    index = build_index(load_cities())
    found: dict[str, dict] = {}
    for rx, name, kind in _patterns():
        for m in rx.finditer(text):
            key = f"{kind}:{name.lower()}"
            if key in found:
                found[key]["mentions"] += 1
                continue
            entry: dict = {
                "name": name if kind == "city" else name.title(),
                "kind": kind,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced from the text — a name match, not a confirmed event site",
            }
            if kind == "country":
                entry["country"] = _COUNTRY_NAMES[name]
            else:
                hit = lookup(index, name, source_country)
                if hit:
                    entry["country"] = hit.country
                    entry["lat"], entry["lon"] = hit.lat, hit.lon
                    if source_country and hit.country == (source_country or "").lower():
                        entry["note"] += "; disambiguated by the source's country"
                    else:
                        entry["note"] += "; most-populous namesake assumed"
            found[key] = entry
    out = sorted(found.values(), key=lambda e: -e["mentions"])
    return out[:limit]
