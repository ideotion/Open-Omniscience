"""
Build and parse Wikidata SPARQL queries for sources by country.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Wikidata is CC0, machine-readable, and has structured ``official website`` (P856),
``country`` (P17 / ISO code P297) and ``language`` (P407) for news organisations
and public institutions — an honest, attributable, refreshable backbone for a
worldwide catalog. We query **per country code** (keyed on P297) so each request
is small and naturally yields per-country coverage, instead of one giant query
that would time out.

This module is pure: it only *builds* query strings and *parses* the JSON the
query service returns. The actual HTTP call lives in the generator/CLI so this
stays unit-testable with no network.
"""

from __future__ import annotations

from src.catalog.countries import to_iso3
from src.catalog.normalize import to_entry

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"


def build_query(
    country_code: str, type_qids: list[str], *, label_lang: str = "en", limit: int = 2000
) -> str:
    """Return a SPARQL query for entities of the given ``type_qids`` in one country.

    ``type_qids`` are Wikidata item ids (e.g. ``Q11032`` newspaper). Subtypes are
    included via ``wdt:P31/wdt:P279*``. Only entities with an official website are
    selected (no website -> nothing to ingest).
    """
    cc = country_code.strip().upper()
    values = " ".join(f"wd:{q}" for q in type_qids if q)
    # Label language falls back to English so unlabelled-in-locale items still get a name.
    label_langs = f"{label_lang},en" if label_lang != "en" else "en"
    return (
        # `?iso3` is P298, the ISO 3166-1 ALPHA-3 code, fetched as a CROSS-CHECK of
        # this app's own alpha-2 -> alpha-3 table (ruling Q311 = a). It is OPTIONAL
        # because not every country item carries P298, and an absent value must read
        # as "Wikidata did not say" rather than as a disagreement. Nothing downstream
        # is keyed on it: the query still selects on P297, so adding it cannot change
        # which rows come back.
        "SELECT DISTINCT ?itemLabel ?website ?lang ?iso3 WHERE {\n"
        f'  ?country wdt:P297 "{cc}" .\n'
        "  OPTIONAL { ?country wdt:P298 ?iso3 . }\n"
        "  ?item wdt:P17 ?country ;\n"
        "        wdt:P856 ?website ;\n"
        "        wdt:P31/wdt:P279* ?type .\n"
        f"  VALUES ?type {{ {values} }}\n"
        "  OPTIONAL { ?item wdt:P407 ?language . ?language wdt:P218 ?lang . }\n"
        f'  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{label_langs}" . }}\n'
        f"}}\nLIMIT {limit}"
    )


def parse_results(
    payload: dict, *, country_code: str, source_type: str, tags: list[str] | None = None
) -> list[dict]:
    """Turn a WDQS JSON response into normalised catalog entries.

    Robust to missing optional bindings; entries without a usable domain (or that
    resolve to a social host) are dropped by :func:`to_entry`.
    """
    bindings = (payload or {}).get("results", {}).get("bindings", [])
    out: list[dict] = []
    for b in bindings:
        name = (b.get("itemLabel") or {}).get("value")
        website = (b.get("website") or {}).get("value")
        lang = (b.get("lang") or {}).get("value")
        entry = to_entry(
            name=name,
            url=website,
            country=country_code,
            language=lang,
            source_type=source_type,
            tags=list(tags or []),
        )
        if entry is not None:
            out.append(entry)
    return out


def iso3_crosscheck(payload: dict, *, country_code: str) -> dict[str, object]:
    """Compare Wikidata's P298 against this app's own alpha-3 for one country.

    Ruling Q311 = a asks for P298 "as a cross-check", and a cross-check that SILENTLY
    CORRECTS is not a cross-check -- it is a second, unreviewed source of truth for
    the table `src/catalog/countries.py` ships. So this REPORTS and never repairs:
    the caller logs the line, a human decides, and `ISO3_TO_ISO2` changes in a commit
    somebody reviewed.

    Three outcomes, kept apart because collapsing any two loses a fact:

    * ``"agree"``    -- both said the same code.
    * ``"disagree"`` -- both spoke and said different codes. The finding.
    * ``"absent"``   -- Wikidata returned no P298 for this country (the property is
      OPTIONAL and genuinely missing on some items), or we have no alpha-3 for the
      code. An absence is NOT a disagreement; reading it as one would manufacture
      upstream drift out of a short answer, and the row would then be the loudest
      thing in a log about countries nobody has a problem with.

    Reads the FIRST P298 binding present. Every row of one country's result set
    carries the same `?iso3` (it is bound off `?country`, which the query pins to a
    single item), so scanning further would re-read one fact N times.
    """
    bindings = (payload or {}).get("results", {}).get("bindings", [])
    theirs: str | None = None
    for b in bindings:
        got = (b.get("iso3") or {}).get("value")
        if got:
            theirs = str(got).strip().upper()
            break
    ours = to_iso3(country_code)
    if theirs is None or ours is None:
        return {
            "country": (country_code or "").strip().upper(),
            "verdict": "absent",
            "ours": ours,
            "theirs": theirs,
            "note": (
                "Wikidata returned no P298 for this country"
                if theirs is None
                else "this app has no alpha-3 for this code"
            ),
        }
    return {
        "country": (country_code or "").strip().upper(),
        "verdict": "agree" if theirs == ours else "disagree",
        "ours": ours,
        "theirs": theirs,
        "note": (
            ""
            if theirs == ours
            else (
                f"Wikidata P298 says {theirs} where this app's table says {ours}; "
                "reported, never auto-applied -- edit ISO3_TO_ISO2 deliberately"
            )
        ),
    }
