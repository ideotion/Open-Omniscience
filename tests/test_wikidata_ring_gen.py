"""Wikidata ring generator (scripts/generate_wikidata_rings.py) + the equivalence
merge of curated + generated ring files (Step 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The generator's parse is PURE and offline-tested with Wikidata-API-shaped fixtures
(only fetch_json touches the network). equivalence.load_rings reads the curated file
(now incl. the 2026-06-17 expansion) AND a generated file, curated winning on a
collision.
"""

import importlib.util
import json
from pathlib import Path

import yaml

from src.analytics.equivalence import _parse_rings

_ROOT = Path(__file__).resolve().parents[1]


def _load_gen():
    path = _ROOT / "scripts" / "generate_wikidata_rings.py"
    spec = importlib.util.spec_from_file_location("generate_wikidata_rings", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load_gen()

_SEARCH = {"search": [{"id": "Q40231", "label": "election"}]}
_ENTITY = {
    "entities": {
        "Q40231": {
            "labels": {"en": {"value": "election"}, "fr": {"value": "élection"}, "de": {"value": "Wahl"}},
            "aliases": {"en": [{"value": "elections"}], "fr": [{"value": "élections"}]},
        }
    }
}


def test_parse_search_returns_first_qid():
    assert G.parse_search(_SEARCH) == "Q40231"
    assert G.parse_search({"search": []}) is None


def test_parse_entity_collects_labels_and_aliases():
    lt = G.parse_entity(_ENTITY, "Q40231")
    assert lt["en"] == ["election", "elections"]  # label + alias (synonym)
    assert lt["fr"] == ["élection", "élections"]
    assert lt["de"] == ["Wahl"]
    assert "es" not in lt  # no label/alias for es -> absent, never invented


def test_build_ring_needs_two_languages():
    ring = G.build_ring("election", "Q40231", {"en": ["election", "elections"], "fr": ["élection"], "de": ["Wahl"]})
    assert ring["id"] == "election" and ring["qid"] == "Q40231"
    assert {"en:election", "en:elections", "fr:élection", "de:Wahl"} <= set(ring["members"])
    assert G.build_ring("x", "Q1", {"en": ["x"]}) is None  # single language -> no ring


def test_generate_with_injected_getter_then_emit_roundtrips():
    def getter(url: str) -> bytes:
        return json.dumps(_SEARCH if "wbsearchentities" in url else _ENTITY).encode()

    rings = G.generate(["election"], getter=getter, sleep=0)
    assert len(rings) == 1 and rings[0]["qid"] == "Q40231"
    parsed = _parse_rings(yaml.safe_load(G.emit_yaml(rings, "2026-06")))
    assert any(r.id == "election" for r in parsed)


def test_generated_acronym_alias_roundtrips_case_insensitively():
    """2026-07-18 entity-families brief S3.3: the wbgetentities payload the generator
    ALREADY fetches carries per-language ALIASES (parse_entity collects them
    unmodified, in their real Wikidata casing — confirmed above for "Wahl"), so an
    entity's acronym alias (USA, alongside the "United States" label) flows straight
    through generate() -> emit_yaml() -> _parse_rings the SAME as any other ring — no
    special-case code, no lowercasing step, needed anywhere in this pipeline. This is
    the proof for the GENERATOR side of the "case seam" (equivalence.ring_of's own
    docstring/test proves the runtime lookup side)."""
    search = {"search": [{"id": "Q30", "label": "United States"}]}
    entity = {
        "entities": {
            "Q30": {
                "labels": {"en": {"value": "United States"}, "ru": {"value": "Соединённые Штаты Америки"}},
                "aliases": {
                    "en": [{"value": "USA"}, {"value": "US"}],
                    "ru": [{"value": "США"}],
                },
            }
        }
    }

    def getter(url: str) -> bytes:
        return json.dumps(search if "wbsearchentities" in url else entity).encode()

    rings = G.generate(["united states"], getter=getter, sleep=0)
    assert len(rings) == 1
    assert "en:USA" in rings[0]["members"] and "ru:США" in rings[0]["members"]

    # _parse_rings is the SAME pure function equivalence.load_rings uses on the real
    # config files -- casefolds every member at parse time regardless of script, so
    # the lookup index built from it (mirroring equivalence._index) matches an
    # UPPERCASE entity normalized form directly.
    parsed = _parse_rings(yaml.safe_load(G.emit_yaml(rings, "2026-07")))
    by_lang_term = {(lang, term): r.id for r in parsed for lang, term in r.members}
    ring = next(r for r in parsed if ("en", "usa") in r.members)
    assert by_lang_term[("en", "usa")] == ring.id
    assert by_lang_term[("ru", "сша")] == ring.id  # a Cyrillic acronym alias, same treatment


def test_equivalence_loads_the_curated_expansion():
    from src.analytics.equivalence import load_rings

    ids = {r.id for r in load_rings()}
    assert {"government", "president", "inflation", "climate", "election"} <= ids


def test_equivalence_merges_a_generated_file_curated_wins(tmp_path, monkeypatch):
    from src.analytics import equivalence as eq

    gen = tmp_path / "gen.yml"
    # one net-new ring + one that collides with a curated id (curated must win)
    gen.write_text(
        'rings:\n'
        '  - id: zzz_generated\n    members: ["en:zzz", "fr:zzz"]\n'
        '  - id: war\n    members: ["en:bogus", "fr:bogus"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(eq, "_GENERATED_PATH", gen)
    eq.load_rings.cache_clear()
    eq._index.cache_clear()
    try:
        rings = {r.id: r for r in eq.load_rings()}
        assert "zzz_generated" in rings  # generated ring is merged in
        assert ("en", "war") in rings["war"].members  # curated 'war' won, not the bogus generated one
    finally:
        eq.load_rings.cache_clear()
        eq._index.cache_clear()


def test_shipped_generated_file_is_clean_and_vetted():
    """The committed configs/keyword_rings_generated.yml (Wikidata batch, vetted
    2026-06-20) parses, every ring has >=2 members, carries a QID, and none of the
    35 mis-resolved rings dropped in vetting (journals/bands/films/place-names/
    homographs/Wikidata meta-classes) has crept back in."""
    path = Path(__file__).resolve().parents[1] / "configs" / "keyword_rings_generated.yml"
    data = yaml.safe_load(path.read_text("utf-8"))
    assert data.get("generated_as_of")
    raw = data["rings"]
    assert len(raw) >= 500  # the breadth expansion
    ids = {str(r["id"]) for r in raw}
    assert len(ids) == len(raw)  # no duplicate ids
    for r in raw:
        assert str(r.get("qid", "")).startswith("Q")  # auditable provenance

    rings = _parse_rings(data)
    assert all(len(r.members) >= 2 for r in rings)

    # Supergroups brief S4.2 config lint: every member label is well-formed
    # ("lang:term", both parts non-empty after stripping) -- a malformed label
    # would silently fail to match any keyword (an honest gap masquerading as a
    # populated ring).
    for r in rings:
        for lang, term in r.members:
            assert lang.strip() and len(lang.strip()) <= 3, f"{r.id}: bad lang code {lang!r}"
            assert term.strip(), f"{r.id}: empty term for lang {lang!r}"

    dropped = {
        "warsaw", "the-police", "taxon", "wii", "metabolism", "nuclear-fusion",
        "stem-cells", "the-library", "massachusetts", "sun-microsystems",
        "indian-national-congress", "country-music", "version-edition-or-translation",
        "village-in-india", "geonames", "cornwall", "farmington",
    }
    assert dropped.isdisjoint(ids), dropped & ids

    # core concept rings survive and translate cross-language
    from src.analytics.equivalence import translate_term

    assert translate_term("fr", "élection", "de") == "wahl"
    assert translate_term("en", "vaccine", "ar") == "لقاح"


def test_wbsearch_url_searches_in_the_seed_language():
    assert "language=ar" in G.wbsearch_url("حصار", "ar")
    assert "language=en" in G.wbsearch_url("blockade")  # default


def test_generate_accepts_term_lang_pairs(tmp_path):
    seen = {}

    def getter(url: str) -> bytes:
        if "wbsearchentities" in url:
            seen["lang"] = "language=ar" in url
            return json.dumps(_SEARCH).encode()
        return json.dumps(_ENTITY).encode()

    rings = G.generate([("حصار", "ar")], getter=getter, sleep=0)
    assert len(rings) == 1 and seen["lang"]  # searched Wikidata in Arabic


def test_from_log_prefers_ring_gap_digest_cross_language(tmp_path):
    import argparse

    log = {
        "data": {
            "ring_candidates": {
                "by_language": {
                    "en": {"candidates": [
                        {"normalized": "supply chain", "articles": 40},
                        {"normalized": "quantum sensor", "articles": 20},
                    ]},
                    "ar": {"candidates": [{"normalized": "حصار", "articles": 35}]},
                }
            },
            # legacy full list — MUST be ignored when the gap digest is present
            "keywords": [{"language": "en", "kind": "term",
                          "normalized": "already-have-this", "articles": 9999}],
        }
    }
    p = tmp_path / "log.json"
    p.write_text(json.dumps(log), encoding="utf-8")
    args = argparse.Namespace(seeds=None, from_log=str(p), top=10)
    seeds = G.load_seeds(args)

    assert ("already-have-this", "en") not in seeds  # legacy ignored — gap-targeted
    assert ("حصار", "ar") in seeds  # cross-language gap seeded
    # ordered by article spread across languages: 40, 35, 20
    assert seeds[:3] == [("supply chain", "en"), ("حصار", "ar"), ("quantum sensor", "en")]


def test_from_log_falls_back_to_keywords_for_old_logs(tmp_path):
    import argparse

    log = {"data": {"keywords": [
        {"language": "en", "kind": "term", "normalized": "inflation", "articles": 50},
        {"language": "en", "kind": "entity", "normalized": "NATO", "articles": 99},  # entity skipped
        {"language": "fr", "kind": "term", "normalized": "grève", "articles": 30},   # non-en skipped
    ]}}
    p = tmp_path / "old.json"
    p.write_text(json.dumps(log), encoding="utf-8")
    args = argparse.Namespace(seeds=None, from_log=str(p), top=10)
    seeds = G.load_seeds(args)
    assert seeds == [("inflation", "en")]  # legacy path: English terms only
