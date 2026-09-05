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

_CONFIGS = Path(__file__).resolve().parents[1] / "configs"
_SOURCES = _CONFIGS / "sources.yml"

# Every curated catalog the seeder reads, in its seeding order. Tag fragmentation is a
# whole-vocabulary problem, so the tag guards below span all of them, not just sources.yml.
_SEEDED_CATALOGS = (
    "sources.yml",
    "markets_sources.yml",
    "sources_spectrum.yml",
    "legal_sources.yml",
)


def _sources(path: Path | None = None) -> list[dict]:
    data = yaml.safe_load((path or _SOURCES).read_text(encoding="utf-8"))
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


def _stem(tag: str) -> str:
    return tag.replace("-", "").replace("_", "")[:5]


def test_no_entry_carries_two_morphological_variants_of_one_tag():
    # A tag drives a collection stratum and a filter, so `finance` beside `financial` is not
    # a second fact about the source -- it splits one stratum in two. This bites on a REVIEW
    # pass, where a proposal is naturally checked against the domain rather than against the
    # tags the entry already carries: three such pairs (`finance`/`financial`,
    # `health`/`healthcare`) were caught this way in the 2026-09-05 source-tag batch.
    #
    # HONEST LIMIT: this finds MORPHOLOGICAL variants only. A semantic synonym
    # (`academic` beside `education`) shares no stem and is invisible here -- that one still
    # needs a human reading the entry, and this guard must never be read as covering it.
    collisions: list[str] = []
    for name in _SEEDED_CATALOGS:
        path = _CONFIGS / name
        if not path.exists():  # a catalog may legitimately not ship
            continue
        for source in _sources(path):
            tags = list(source.get("tags") or [])
            for i, a in enumerate(tags):
                for b in tags[i + 1 :]:
                    if a == b:
                        continue
                    if _stem(a) == _stem(b) or a.startswith(b) or b.startswith(a):
                        who = source.get("domain") or source.get("name") or "?"
                        collisions.append(f"{name}:{who} carries both {a!r} and {b!r}")
    assert not collisions, (
        "tag variants split one stratum in two -- pick the form the catalog already uses: "
        + "; ".join(sorted(collisions))
    )


def test_the_variant_guard_can_actually_fail():
    # Anti-vacuity: the guard above passes over four real catalogs, so prove its predicate
    # discriminates rather than being satisfied by an empty comparison.
    assert _stem("finance") == _stem("financial")
    assert _stem("health") == _stem("healthcare")
    assert _stem("politics") != _stem("policy")  # a legitimate pair must NOT collide
    assert _stem("law") != _stem("case-law")


def test_wikidata_enrich_maps_to_canonical_types():
    # Cross-check: every source_type the Wikidata reconciler can emit is canonical.
    from src.catalog.wikidata_enrich import P31_SOURCE_TYPE

    bad = sorted(set(P31_SOURCE_TYPE.values()) - CANONICAL_SOURCE_TYPES)
    assert not bad, f"wikidata_enrich emits non-canonical source_type(s): {bad}"
