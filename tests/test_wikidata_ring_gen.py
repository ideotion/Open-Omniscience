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
