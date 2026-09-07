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
    """The committed configs/keyword_rings_generated.yml (Wikidata batches, vetted
    2026-06-20 then 2026-07-23) parses, every ring has >=2 members, carries a QID,
    and none of the mis-resolved rings dropped in either vetting pass (journals/
    bands/films/place-names/homographs/Wikidata meta-classes/too-narrow drift) has
    crept back in."""
    path = Path(__file__).resolve().parents[1] / "configs" / "keyword_rings_generated.yml"
    data = yaml.safe_load(path.read_text("utf-8"))
    assert data.get("generated_as_of")
    raw = data["rings"]
    assert len(raw) >= 680  # the war/conflict/pandemic/IP/finance/labour/tech batch
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
        # 2026-06-20 batch
        "warsaw", "the-police", "taxon", "wii", "metabolism", "nuclear-fusion",
        "stem-cells", "the-library", "massachusetts", "sun-microsystems",
        "indian-national-congress", "country-music", "version-edition-or-translation",
        "village-in-india", "geonames", "cornwall", "farmington",
        # 2026-07-23 batch (the 4 true id/qid duplicates of an existing ring --
        # guest-house/psychiatric-hospital/irreligion/marketing -- are NOT listed
        # here: those ids legitimately exist in the file for their ORIGINAL
        # correct sense, only the duplicate re-resolutions were discarded)
        "massacre", "desalination", "repatriation-of-cultural-property-to-korea",
        "antimicrobial-resistance-and-infection-control", "ethnic-cleansing",
        "unesco-world-heritage-site-buffer-zone",
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


# --------------------------------------------------------------------------- #
#  --refresh: re-read already-vetted QIDs, propose ONLY the additions
#  (the 2026-07-20 ring-lifecycle ruling; built 2026-09-07)
# --------------------------------------------------------------------------- #

_RING_ON_FILE = [
    {"id": "public-election", "qid": "Q40231", "members": ["en:election", "de:Wahl"]},
]


def _refresh_getter(entities: dict, *, calls: list | None = None):
    """A wbgetentities double. ``entities`` maps QID -> its entity block (or the literal
    ``{"missing": ""}`` Wikidata returns for a deleted id); a QID absent from the mapping
    is absent from the RESPONSE, which is how a truncated batch is simulated."""

    def getter(url: str) -> bytes:
        if calls is not None:
            calls.append(url)
        ids = url.split("ids=", 1)[1].split("&", 1)[0]
        asked = [i for i in ids.replace("%7C", "|").split("|") if i]
        return json.dumps({"entities": {q: entities[q] for q in asked if q in entities}}).encode()

    return getter


def _ent(labels=None, aliases=None):
    return {"labels": labels or {}, "aliases": aliases or {}}


def test_refresh_proposes_only_the_members_wikidata_has_gained():
    getter = _refresh_getter({"Q40231": _ent(
        labels={"en": {"value": "election"}, "de": {"value": "Wahl"}, "fr": {"value": "élection"}},
        aliases={"en": [{"value": "elections"}]},
    )})
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["checked"] == 1 and out["unchanged"] == 0
    assert len(out["additions"]) == 1
    add = out["additions"][0]
    assert add["id"] == "public-election" and add["qid"] == "Q40231"
    # only the NEW ones: en:election and de:Wahl are already on file
    assert set(add["new_members"]) == {"fr:élection", "en:elections"}


def test_refresh_reports_nothing_new_as_unchanged():
    getter = _refresh_getter({"Q40231": _ent(
        labels={"en": {"value": "election"}, "de": {"value": "Wahl"}}
    )})
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["additions"] == [] and out["unchanged"] == 1


def test_refresh_never_proposes_a_pure_recasing_as_an_addition():
    """NEGATIVE SPACE. Upstream re-cases "Wahl" -> "wahl"; the app compares casefolded,
    so it already HAS that member. Proposing it would be a fabricated finding in a tool
    whose entire output is findings — and it is what a raw string diff would do."""
    getter = _refresh_getter({"Q40231": _ent(
        labels={"en": {"value": "ELECTION"}, "de": {"value": "wahl"}}
    )})
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["additions"] == [], out["additions"]
    assert out["unchanged"] == 1


def test_refresh_member_key_agrees_with_the_app_normalisation():
    """The script duplicates equivalence's normalisation so it stays runnable without an
    app checkout; this pins the two together, because a drift makes the recasing case
    above start proposing members the app already has."""
    from src.analytics.equivalence import _norm

    for raw in ("de:Wahl", "fr:  élection  ", "EN:Election", "ru:Совет Министров"):
        lang, term = raw.split(":", 1)
        assert G._member_key(raw) == (lang.strip().casefold(), _norm(term))
    assert G._member_key("no-colon-here") is None
    assert G._member_key("en:") is None


def test_refresh_reports_a_deleted_qid_as_unresolved_not_as_unchanged():
    """NEGATIVE SPACE. An id Wikidata says is missing means the ring's IDENTITY is now
    wrong (an upstream merge or deletion) — the single most important thing a refresh
    can find. Folding it into 'unchanged' would hide it behind a clean bill of health."""
    getter = _refresh_getter({"Q40231": {"missing": ""}})
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["additions"] == [] and out["unchanged"] == 0
    assert len(out["unresolved"]) == 1
    assert out["unresolved"][0]["qid"] == "Q40231"
    assert "missing" in out["unresolved"][0]["reason"]


def test_refresh_reports_a_labelless_entity_as_unresolved_with_its_own_reason():
    """NEGATIVE SPACE. The item exists but now carries no label or alias in the 12
    languages — a different fact from 'deleted', and equally not 'unchanged'."""
    getter = _refresh_getter({"Q40231": _ent(labels={"sv": {"value": "val"}})})
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["unchanged"] == 0 and out["additions"] == []
    assert len(out["unresolved"]) == 1
    reason = out["unresolved"][0]["reason"]
    assert "no label" in reason and "missing" not in reason  # the two reasons stay distinct


def test_refresh_refetches_singly_rather_than_calling_a_truncated_batch_deleted():
    """NEGATIVE SPACE, and the reason batching is safe: a QID absent from a BATCH
    response is a fact about the response, not about the item. Reading it as 'deleted'
    would manufacture upstream drift out of a short reply."""
    asked_sets: list[list[str]] = []

    def getter(url: str) -> bytes:
        ids = url.split("ids=", 1)[1].split("&", 1)[0].replace("%7C", "|")
        asked = [i for i in ids.split("|") if i]
        asked_sets.append(asked)
        # Q1 is silently dropped from any MULTI-id reply; asked alone it answers fine.
        ents = {
            q: _ent(labels={"en": {"value": "a" if q == "Q1" else "b"}})
            for q in asked
            if not (q == "Q1" and len(asked) > 1)
        }
        return json.dumps({"entities": ents}).encode()

    rings = [
        {"id": "one", "qid": "Q1", "members": ["en:a", "de:x"]},
        {"id": "two", "qid": "Q2", "members": ["en:b", "de:y"]},
    ]
    out = G.refresh_rings(rings, getter=getter, sleep=0, log=lambda m: None)
    assert out["unresolved"] == [], out["unresolved"]  # NOT reported as deleted
    assert out["unchanged"] == 2 and out["errors"] == [] and out["additions"] == []
    assert asked_sets[0] == ["Q1", "Q2"]      # the batch went out as a batch
    assert ["Q1"] in asked_sets[1:]           # and Q1 was then re-asked ALONE


def test_refresh_records_a_failed_fetch_as_not_checked_never_as_unchanged():
    """NEGATIVE SPACE. 'we looked and nothing was new' and 'we could not look' are
    different facts; a refresh whose network flaked must not report a clean result."""

    def getter(url: str) -> bytes:
        raise OSError("connection reset")

    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert out["unchanged"] == 0 and out["additions"] == [] and out["unresolved"] == []
    assert len(out["errors"]) == 1 and out["errors"][0]["qid"] == "Q40231"


def test_refresh_buckets_partition_the_checked_rings_exactly():
    """Anti-vacuity: every checked ring lands in exactly one bucket, so a ring can
    never be dropped on the floor and read as 'nothing to report'."""
    rings = [
        {"id": "gains", "qid": "Q1", "members": ["en:a", "de:x"]},
        {"id": "same", "qid": "Q2", "members": ["en:b", "de:y"]},
        {"id": "gone", "qid": "Q3", "members": ["en:c", "de:z"]},
    ]
    getter = _refresh_getter({
        "Q1": _ent(labels={"en": {"value": "a"}, "fr": {"value": "aa"}}),
        "Q2": _ent(labels={"en": {"value": "b"}, "de": {"value": "y"}}),
        "Q3": {"missing": ""},
    })
    out = G.refresh_rings(rings, getter=getter, sleep=0, log=lambda m: None)
    total = out["unchanged"] + len(out["additions"]) + len(out["unresolved"]) + len(out["errors"])
    assert total == out["checked"] == 3
    assert [a["id"] for a in out["additions"]] == ["gains"]
    assert [u["id"] for u in out["unresolved"]] == ["gone"]


def test_refresh_never_removes_a_member_wikidata_dropped():
    """Rings are never pruned: a label upstream has dropped still serves the history
    already in the corpus. The refresh has no 'removals' channel at all."""
    getter = _refresh_getter({"Q40231": _ent(labels={"en": {"value": "election"}})})  # de:Wahl gone
    out = G.refresh_rings(_RING_ON_FILE, getter=getter, sleep=0, log=lambda m: None)
    assert "removals" not in out and "removed" not in out
    assert out["unchanged"] == 1 and out["additions"] == []


def test_refresh_batches_several_qids_into_one_request():
    calls: list[str] = []
    rings = [{"id": f"r{i}", "qid": f"Q{i}", "members": ["en:x", "de:y"]} for i in range(5)]
    getter = _refresh_getter(
        {f"Q{i}": _ent(labels={"en": {"value": "x"}, "de": {"value": "y"}}) for i in range(5)},
        calls=calls,
    )
    G.refresh_rings(rings, getter=getter, sleep=0, log=lambda m: None)
    assert len(calls) == 1  # one wbgetentities call, not five
    assert "%7C" in calls[0] or "|" in calls[0]  # the ids were joined


def test_load_ring_file_surfaces_rings_without_a_qid_rather_than_dropping_them(tmp_path):
    p = tmp_path / "rings.yml"
    p.write_text(
        'rings:\n'
        '  - id: has-qid\n    qid: Q1\n    members: ["en:a", "de:b"]\n'
        '  - id: no-qid\n    members: ["en:c", "de:d"]\n',
        encoding="utf-8",
    )
    rings, no_qid = G.load_ring_file(p)
    assert [r["id"] for r in rings] == ["has-qid"]
    assert no_qid == ["no-qid"]  # reported, so it cannot stay silently un-refreshed


def test_the_additions_artifact_is_never_loadable_as_a_ring_file():
    """It carries `ring_additions:`, never `rings:` — equivalence.load_rings merges by
    id and the last file wins, so a partial ring under `rings:` would REPLACE the full
    one with the handful of members listed here."""
    result = {
        "checked": 2, "unchanged": 1,
        "additions": [{"id": "public-election", "qid": "Q40231", "new_members": ["fr:élection"]}],
        "unresolved": [{"id": "gone", "qid": "Q9", "reason": "missing upstream"}],
        "errors": [],
    }
    text = G.emit_additions_yaml(result, "2026-09", "configs/keyword_rings_generated.yml", ["no-qid"])
    data = yaml.safe_load(text)
    assert "rings" not in data and "ring_additions" in data
    assert _parse_rings(data) == []  # the app would read zero rings from it
    assert data["ring_additions"][0]["new_members"] == ["fr:élection"]
    assert data["unresolved"][0]["qid"] == "Q9"
    assert data["rings_without_a_qid"] == 1 and data["without_a_qid"] == ["no-qid"]
    assert data["members_proposed"] == 1 and data["not_checked_count"] == 0


def test_a_seed_run_refuses_to_replace_an_existing_ring_file(tmp_path):
    """The recorded footgun: every write is a full replacement and -o defaults to the
    LIVE vetted file, so an ordinary seed run could delete hundreds of vetted rings with
    no error. The refusal fires BEFORE any network call."""
    out = tmp_path / "rings.yml"
    out.write_text("rings:\n  - id: keep-me\n    qid: Q1\n    members: [\"en:a\", \"de:b\"]\n",
                   encoding="utf-8")
    before = out.read_bytes()
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("election\n", encoding="utf-8")

    assert G.main(["--seeds", str(seeds), "-o", str(out)]) == 2
    assert out.read_bytes() == before  # untouched

    # --force is the deliberate way through; an empty file is not a refusal either.
    empty = tmp_path / "fresh.yml"
    empty.touch()
    assert G._refuse_overwrite(empty, force=False) is None
    assert G._refuse_overwrite(out, force=True) is None
    assert G._refuse_overwrite(tmp_path / "nope.yml", force=False) is None


def test_refresh_cli_refuses_an_unnamed_or_self_targeting_output(tmp_path):
    src = tmp_path / "rings.yml"
    src.write_text("rings:\n  - id: a\n    qid: Q1\n    members: [\"en:a\", \"de:b\"]\n",
                   encoding="utf-8")
    before = src.read_bytes()
    assert G.main(["--refresh", str(src)]) == 2                      # no -o
    assert G.main(["--refresh", str(src), "-o", str(src)]) == 2      # writes over its input
    assert G.main(["--refresh", str(src), "--seeds", str(src), "-o", str(tmp_path / "x")]) == 2
    assert src.read_bytes() == before


def test_the_additions_artifact_survives_an_id_a_human_typed():
    """Ids come back out of a HAND-EDITED file, not from _slug(), so one carrying a colon
    would emit a document that no longer parses — and the whole artifact would be lost
    for a run that had already spent its Wikidata calls."""
    result = {
        "checked": 1, "unchanged": 0,
        "additions": [{"id": "odd: id", "qid": "Q1", "new_members": ['en:a "quoted" one']}],
        "unresolved": [], "errors": [],
    }
    data = yaml.safe_load(G.emit_additions_yaml(result, "2026-09", "src: file", []))
    assert data["ring_additions"][0]["id"] == "odd: id"
    assert data["ring_additions"][0]["new_members"] == ['en:a "quoted" one']
    assert data["source_file"] == "src: file"
