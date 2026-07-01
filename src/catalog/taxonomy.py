"""
Controlled vocabularies for source metadata — the single source of truth.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The catalog's ``source_type`` had drifted (defined differently across
catalog_query.yml, the live sources.yml, the stats/law modules, and the research
scaffold) and geographic/linguistic codes had leaked into the topical ``tags``
list. This module pins the canonical sets so a CI guard
(tests/test_source_taxonomy.py) can catch drift and regressions, and so the
enrichment tooling shares one definition.

Adding a value is a deliberate taxonomy decision — extend the set here (ideally
with a maintainer ruling), never work around the guard.
"""

from __future__ import annotations

# ``source_type`` = the MEDIUM/genre (exactly one per source). Union of what is in
# active use plus the enrichment strategy's canonical set. Grouped for clarity.
CANONICAL_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        # general news media
        "news", "wire-agency", "magazine", "broadcaster", "investigative",
        # research / reference
        "academic-research", "scientific-journal", "think-tank",
        # institutional / civic
        "government-primary", "igo", "ngo-civil-society", "fact-checker",
        "data-portal", "religious",
        # other channels
        "blog", "financial-data",
        # ingest-channel provenance (asserted by construction — the ingest path
        # knows the channel; content-provenance S1). A newsletter is a CHANNEL,
        # never a credibility judgement; this fixes newsletters mislabeled "news".
        "newsletter",
        # legacy values already present in the live catalog / assigned by code
        # (kept valid so the guard does not fail on shipped data; prefer the
        # canonical names above for new entries):
        "scientific", "financial", "technology", "geopolitical", "legal",
        "statistics", "institution", "ip",
    }
)

# ``ownership`` = funding/control (carried as a tag, per sources_spectrum.yml).
OWNERSHIP_TAGS: frozenset[str] = frozenset(
    {
        "independent", "state-owned", "public-broadcaster", "state-media",
        "corporate", "party-affiliated", "nonprofit", "cooperative", "wire-agency",
    }
)

# ``lean`` = political slant (a tag; reputational + contestable, set sparingly).
LEAN_TAGS: frozenset[str] = frozenset(
    {"lean-left", "lean-center-left", "center", "lean-center-right", "lean-right"}
)
