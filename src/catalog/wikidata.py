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

from src.catalog.normalize import to_entry

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"


def build_query(country_code: str, type_qids: list[str], *, label_lang: str = "en", limit: int = 2000) -> str:
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
        "SELECT DISTINCT ?itemLabel ?website ?lang WHERE {\n"
        f'  ?country wdt:P297 "{cc}" .\n'
        "  ?item wdt:P17 ?country ;\n"
        "        wdt:P856 ?website ;\n"
        "        wdt:P31/wdt:P279* ?type .\n"
        f"  VALUES ?type {{ {values} }}\n"
        "  OPTIONAL { ?item wdt:P407 ?language . ?language wdt:P218 ?lang . }\n"
        f'  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{label_langs}" . }}\n'
        f"}}\nLIMIT {limit}"
    )


def parse_results(payload: dict, *, country_code: str, source_type: str, tags: list[str] | None = None) -> list[dict]:
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
            name=name, url=website, country=country_code, language=lang,
            source_type=source_type, tags=list(tags or []),
        )
        if entry is not None:
            out.append(entry)
    return out
