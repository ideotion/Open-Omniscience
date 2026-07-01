"""
Controlled-vocabulary guard for configs/sources.yml.

Locks the source-metadata taxonomy and prevents the leaked-code/territory-tag bug
class (fixed in the enrichment cleanup) from recurring on a future seeding pass.
Pure: needs only yaml + src.catalog (no DB / no [analysis] extra).
"""

from pathlib import Path

import yaml

from src.catalog.countries import normalize_country
from src.catalog.taxonomy import CANONICAL_SOURCE_TYPES, LEAN_TAGS

_SOURCES = Path(__file__).resolve().parents[1] / "configs" / "sources.yml"


def _sources() -> list[dict]:
    data = yaml.safe_load(_SOURCES.read_text(encoding="utf-8"))
    return data.get("sources") or []


def test_every_source_type_is_in_the_controlled_vocabulary():
    bad = sorted(
        {
            s.get("source_type")
            for s in _sources()
            if s.get("source_type") and s.get("source_type") not in CANONICAL_SOURCE_TYPES
        }
    )
    assert not bad, f"source_type values outside the canonical set: {bad}"


def test_lean_tags_are_valid():
    bad = sorted(
        {
            t
            for s in _sources()
            for t in (s.get("tags") or [])
            if t.startswith("lean-") and t not in LEAN_TAGS
        }
    )
    assert not bad, f"invalid lean-* tags: {bad}"


def test_no_country_or_territory_name_leaked_into_tags():
    # A full country/territory NAME belongs in the ``country`` field, never in the
    # topical tags. Only flag names longer than 3 chars so 2-letter topic homographs
    # of country CODES (ai=AI≠Anguilla, iq=IQ≠Iraq) are never false-positived.
    leaked: dict[str, str] = {}
    for s in _sources():
        for t in s.get("tags") or []:
            if len(t) > 3 and (normalize_country(t) or normalize_country(t.replace("-", " "))):
                leaked[t] = s.get("domain") or s.get("name") or "?"
    assert not leaked, f"country/territory names leaked into tags (move to country): {leaked}"


def test_wikidata_enrich_maps_to_canonical_types():
    # Cross-check: every source_type the Wikidata reconciler can emit is canonical.
    from src.catalog.wikidata_enrich import P31_SOURCE_TYPE

    bad = sorted(set(P31_SOURCE_TYPE.values()) - CANONICAL_SOURCE_TYPES)
    assert not bad, f"wikidata_enrich emits non-canonical source_type(s): {bad}"
