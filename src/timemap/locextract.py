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


# A name can only begin where a word begins, because every pattern above is
# ``\b<literal>\b`` and every name starts with a word character (asserted at index
# build time; one that does not is routed to the scan list instead of being dropped).
_WORD_RUN = re.compile(r"\w+")


@lru_cache(maxsize=1)
def _dispatch() -> tuple[list[tuple[int, re.Pattern, str, str]], dict[str, list[tuple[int, re.Pattern, str, str]]]]:
    """``(scan, index)`` — how each pattern is looked for, without changing WHAT is found.

    THE COST THIS REMOVES. Every pattern used to be run over the whole article
    independently, so the work was O(patterns x text): with the bundled 21-city sample
    that is ~160 scans and invisible, but the gazetteer ``build_city_gazetteer.py``
    generates carries thousands of cities, and at 4,500 the same article costs 4,661
    scans -- measured at 2,264 ms for a 5,000-word body, against ~48 ms for the whole
    when/where/who precompute at sample scale. Only installs that built the gazetteer
    ever paid it, which is why it survived.

    THE SPLIT, and why it is drawn where it is:

    * ``scan`` keeps the per-pattern ``finditer`` for the CASE-INSENSITIVE half -- the
      span guards and the country table. That half is a module constant of ~140 entries,
      so it does not scale with anything, and ``re.IGNORECASE`` does not agree with
      ``str.lower()`` in every case (``"İ".lower()`` is ``i`` + a combining dot, yet
      IGNORECASE matches ``İSTANBUL`` against ``istanbul``; ``ſ`` folds to ``s``
      for the engine and to itself for ``lower()``). Any token index over it would be a
      false-NEGATIVE hazard for exotic input, and buying ~92 ms of a 2,264 ms article at
      that price is a bad trade.
    * ``index`` covers the CASE-SENSITIVE half -- the cities, which is the half that
      scales. Case-sensitive means an EXACT token key, so the folding hazard above cannot
      arise at all: the key is a plain string comparison. It maps a name's leading word
      run to the patterns that begin with it, so a word in the text costs one dict lookup
      instead of thousands of scans.

    IDENTICAL RESULTS, not merely similar. The index only proposes CANDIDATES; each is
    confirmed by ``rx.match(text, pos)`` with the same compiled pattern the old loop used,
    and ``\b`` still sees the character before ``pos`` (verified, not assumed). The
    candidate set is provably the same: if a pattern matches at ``pos`` then the text's
    word run at ``pos`` equals the name's leading word run exactly -- the name either ends
    there (so ``\b`` forces a non-word character next) or continues with a non-word
    character of its own. Both halves' candidates are then merged and replayed in the
    ORIGINAL pattern order, so the longest-match-claims-the-span rule below decides
    exactly what it decided before.
    """
    scan: list[tuple[int, re.Pattern, str, str]] = []
    index: dict[str, list[tuple[int, re.Pattern, str, str]]] = {}
    for i, (rx, name, kind) in enumerate(_patterns()):
        head = _WORD_RUN.match(name)
        # Case-insensitive patterns, and any name that does not begin with a word
        # character, keep the whole-text scan. The second case does not arise in the
        # bundled data and is handled rather than assumed away: dropping such a name
        # would silently lose a place, which is the one outcome worse than being slow.
        if rx.flags & re.IGNORECASE or head is None or head.start() != 0:
            scan.append((i, rx, name, kind))
        else:
            index.setdefault(head.group(0), []).append((i, rx, name, kind))
    return scan, index


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

    # CANDIDATES FIRST, CLAIMS SECOND. The claim rule below is unchanged and still
    # decides everything; all that changed is how the candidates are found (see
    # ``_dispatch``). They are replayed in the original pattern order, so the longest
    # name still runs first and still wins the span.
    scan_pats, name_index = _dispatch()
    cands: list[tuple[int, int, int, str, str]] = []
    for i, rx, name, kind in scan_pats:
        for m in rx.finditer(text):
            cands.append((i, m.start(), m.end(), name, kind))
    for w in _WORD_RUN.finditer(text):
        bucket = name_index.get(w.group(0))
        if not bucket:
            continue
        pos = w.start()
        for i, rx, name, kind in bucket:
            # `confirmed`, not `hit`: `hit` is taken further down for the gazetteer
            # lookup's City, and a long function that reuses one name for two types is
            # how a later reader ends up holding the wrong one. mypy caught the collision.
            confirmed = rx.match(text, pos)  # anchored; \b still reads text[pos-1]
            if confirmed:
                cands.append((i, pos, confirmed.end(), name, kind))
    # (pattern order, then left-to-right) reproduces the old nested loop exactly: the
    # outer loop walked patterns longest-first and the inner one walked that pattern's
    # matches in text order.
    cands.sort(key=lambda c: (c[0], c[1]))

    for _i, start, end, name, kind in cands:
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
            "snippet": _snippet(text, start, end),
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
