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
    # Longer names that CONTAIN a shorter one. Present so the longest-match rule below
    # has something to win with: without "northern ireland" in the table, the only
    # thing that could match inside it was "ireland", and a UK Act was filed under the
    # Republic of Ireland (field feedback 2026-08-07, item 3 — a geographic fabrication,
    # not noise). Same shape for the two Sudans, separate states since 2011, and the two
    # Congos, which the bare name cannot tell apart.
    "northern ireland": "gb", "republic of ireland": "ie",
    "south sudan": "ss", "soudan du sud": "ss",
    "democratic republic of the congo": "cd", "république démocratique du congo": "cd",
    "republic of the congo": "cg", "république du congo": "cg",
}

# Phrases that CLAIM their span without asserting any country — the honest half of the
# longest-match rule. "South China Sea" contains "China" and is not China; a body of
# water attributed to one of several claimants is a loaded fabrication, not a rounding
# error. Likewise a place inside one country named after another. Each entry below was
# REPRODUCED mis-resolving before it was added; none is speculative.
#
# Deliberately NOT here: "Georgia", which is genuinely ambiguous between the country and
# the US state. There is no evidence in the text to decide it, so it keeps resolving to
# the country and keeps its "deduced, not confirmed" note. Inventing a rule for it would
# be guessing with extra steps.
_SPAN_GUARDS: tuple[str, ...] = (
    "south china sea", "east china sea", "sea of japan", "gulf of mexico",
    "new mexico", "little italy",
)

_MAX_SCAN = 60_000  # characters of text scanned (bounded, like every scan)


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str, str]]:
    """[(compiled pattern, canonical name, kind)] for guards + countries + cities.

    Ordered by name length DESCENDING across all three kinds, because the caller claims
    each match's character span and skips anything overlapping an existing claim — so
    whichever pattern runs first wins the span. Longest-first is what makes "Northern
    Ireland" beat "Ireland" and "New York" beat "York".
    """
    pats: list[tuple[re.Pattern, str, str]] = []
    for name in _SPAN_GUARDS:
        pats.append((re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), name, "guard"))
    for name in _COUNTRY_NAMES:
        pats.append((re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), name, "country"))
    from src.catalog.cities import load_cities

    for c in load_cities():
        pats.append((re.compile(rf"\b{re.escape(c.name)}\b"), c.name, "city"))  # case-sensitive
    pats.sort(key=lambda p: len(p[1]), reverse=True)
    return pats


def _display_name(iso2: str) -> str:
    """The canonical English name for a country code, so every surface form that
    matched ("uk", "britain", "united kingdom") renders as one place.

    Falls back to the code itself if the shared catalog does not know it — degrade
    loudly rather than mask an unknown code behind a fabricated name.
    """
    from src.catalog.countries import country_display_name

    return country_display_name(iso2) or iso2.upper()


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

    LONGEST MATCH WINS, and a matched span is CONSUMED. Every pattern used to be run
    independently over the whole text, so a shorter name nested inside a longer one
    matched too: "Northern Ireland" yielded Ireland (ie) inside a United Kingdom Act,
    "South Sudan" yielded Sudan, "South China Sea" yielded China. Those are wrong
    countries, not noisy ones — a reader cannot tell a fabricated attribution from a
    real one. Patterns now run longest-first and claim their characters, so nothing
    nested inside an already-matched name can match.
    """
    if not text:
        return []
    text = text[:_MAX_SCAN]
    # One byte per character; a match is skipped when any of its characters is already
    # spoken for. Cheap, and O(len(name)) per check rather than O(matches so far).
    claimed = bytearray(len(text))
    # cached_index() rather than build_index(load_cities()): the latter re-read and
    # re-parsed the whole gazetteer YAML on EVERY call, i.e. once per article
    # through the re-index. Measured at 50,000 cities: 17 seconds. Per article.
    from src.catalog.cities import cached_index, lookup

    index = cached_index()
    found: dict[str, dict] = {}
    for rx, name, kind in _patterns():
        for m in rx.finditer(text):
            start, end = m.start(), m.end()
            if any(claimed[start:end]):
                continue  # nested inside a longer name that already won this span
            claimed[start:end] = b"\x01" * (end - start)
            if kind == "guard":
                # The span is spent and nothing is asserted. A sea is not a country,
                # and a place named after one is not that one.
                continue
            # CANONICALISE a country by its ISO code, not by the surface form that
            # happened to match. The same field report showed "Uk (gb)", "United Kingdom
            # (gb)" and "Britain (gb)" as three separate places in one document; they are
            # one country mentioned three ways, and summing them is both truer and what a
            # reader expects. Cities keep their gazetteer name as the key — two cities can
            # legitimately share a name, and collapsing those would lose a real distinction.
            iso2 = _COUNTRY_NAMES[name] if kind == "country" else None
            key = f"country:{iso2}" if iso2 else f"{kind}:{name.lower()}"
            if key in found:
                found[key]["mentions"] += 1
                continue
            entry: dict = {
                "name": _display_name(iso2) if iso2 else name,
                "kind": kind,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced from the text — a name match, not a confirmed event site",
            }
            if kind == "country":
                entry["country"] = iso2
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
