"""Place canonicalization by country code (Leads-calibration S4.2 / convergence-amendment C2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A country-level place mention (``ArticleMentionedPlace.kind == "country"``) is stored
under whatever SURFACE STRING the source-language text used ("Allemagne"/"Deutschland",
2026-07-18 field export row 9; "United States"/"America"/"Usa", row 8) even though the
extractor (``src.timemap.locextract``) already resolves the SAME ISO-2 ``country`` code
for all of them. Clustering on the raw ``name`` string silently multiplies one real place
into several. This module gives every cluster-building producer (space-time convergence,
weather corroboration) ONE canonicalization: a country-level mention keys on its
resolved country CODE (never the free-text name it happened to be written in); a
city/region/other place keeps its own free-text identity, scoped under its country (so
the SAME city name in two different countries never collides, and a city stays distinct
from its own country-level mentions).

Display always goes through :func:`src.catalog.countries.country_display_name` (the
canonical English name, e.g. "United Kingdom" rather than a raw "Uk" from
``"uk".title()``) — never the raw surface string the extractor happened to see.
"""

from __future__ import annotations

# ArticleMentionedPlace.kind values that denote a COUNTRY-LEVEL mention (as opposed to a
# city/region/other sub-national place, which keeps its own free-text identity).
COUNTRY_KINDS = frozenset({"country"})


def place_identity(name: str | None, country: str | None, kind: str | None) -> tuple[str, str]:
    """(identity_key, display_name) for a place mention -- the ONE canonicalization every
    cluster-building producer shares.

    A country-level mention (``kind`` in :data:`COUNTRY_KINDS`) with a resolved country
    code canonicalizes to that CODE, so "United States"/"America"/"Usa" (and
    "Allemagne"/"Deutschland") collapse to the same identity; the display name is the
    canonical country full name. A city/region/other place keeps its own free-text
    identity, scoped under its country (``place:<cc>:<name>``, casefolded) — the SAME
    city name in two countries never collides. An unresolvable country code (or a
    country-kind mention that never got one) falls back to the free-text name — never
    invents a code.
    """
    from src.catalog.countries import country_display_name

    cc = (country or "").strip().lower()
    nm = " ".join((name or "").split())
    is_country_level = (kind or "").strip().lower() in COUNTRY_KINDS

    if is_country_level and cc:
        display = country_display_name(cc) or nm or cc.upper()
        return (f"country:{cc}", display)

    key_name = nm.casefold()
    display = nm or (country_display_name(cc) if cc else "") or "?"
    return (f"place:{cc}:{key_name}", display)
