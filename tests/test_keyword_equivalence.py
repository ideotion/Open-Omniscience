"""Cross-language keyword equivalence — ring merging into live analytics.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the honesty contract for src/analytics/equivalence.py + its wiring into
queries.py (top_terms / trending / associations): ring members collapse into ONE
concept, per-language counts stay visible (language_breakdown), the polysemy rule
(fr:main != en:main) is honoured via (effective-language, normalized) matching,
a user 'split' keeps a member out, and a lone present member is never "merged".
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import equivalence as E
from src.analytics import queries as q
from src.analytics.store import backfill_keyword_counters
from src.database.models import Article, Base, Keyword, KeywordMention, Source

# --- pure module: merge_equivalents / group_rows ----------------------------- #


def _lang(mapping):
    return lambda norm: mapping.get(norm)


def test_ring_members_merge_with_visible_per_language_counts():
    rows = [
        {"term": "election", "normalized": "election", "kind": "term", "mentions": 50, "articles": 30},
        {"term": "élection", "normalized": "élection", "kind": "term", "mentions": 20, "articles": 12},
        {"term": "wahl", "normalized": "wahl", "kind": "term", "mentions": 10, "articles": 8},
        {"term": "weather", "normalized": "weather", "kind": "term", "mentions": 5, "articles": 4},
    ]
    lang_of = _lang({"election": "en", "élection": "fr", "wahl": "de", "weather": "en"})
    merged = E.merge_equivalents(rows, lang_of=lang_of)
    rings = [m for m in merged if m.get("ring_id") == "election"]
    assert len(rings) == 1
    r = rings[0]
    assert r["mentions"] == 80  # summed
    assert r["articles"] == 30  # max member, not a double-counting sum
    assert r["language_breakdown"] == {"en": 50, "fr": 20, "de": 10}
    assert {m["normalized"] for m in r["members"]} == {"election", "élection", "wahl"}
    # non-member passes through untouched
    assert any(m["normalized"] == "weather" and "ring_id" not in m for m in merged)


def test_entity_acronym_rings_merge_across_scripts_case_insensitively():
    """2026-07-18 entity-families brief S3 (the "case seam"): entity keywords keep
    their normalized form UPPERCASE (WHO != who, USA != usa -- the 2026-06-16
    acronym ruling), while ring members are written lowercase in the curated config.
    ring_of/_norm already casefold BOTH sides at parse and lookup time, so an
    ALL-CAPS entity normalized form matches a lowercase ring member with NO special-
    case code needed. USA / США / EUA / ABD (the field export's fractured top-80
    rows) collapse into one grouped entity, provenance visible via
    language_breakdown; an unrelated entity (WHO) is never accidentally folded in."""
    rows = [
        {"term": "USA", "normalized": "USA", "kind": "entity", "mentions": 40, "articles": 22},
        {"term": "США", "normalized": "США", "kind": "entity", "mentions": 15, "articles": 9},
        {"term": "EUA", "normalized": "EUA", "kind": "entity", "mentions": 5, "articles": 4},
        {"term": "ABD", "normalized": "ABD", "kind": "entity", "mentions": 3, "articles": 2},
        {"term": "WHO", "normalized": "WHO", "kind": "entity", "mentions": 60, "articles": 30},
    ]
    lang_of = _lang({"USA": "en", "США": "ru", "EUA": "pt", "ABD": "tr", "WHO": "en"})
    merged = E.merge_equivalents(rows, lang_of=lang_of)
    rings = [m for m in merged if m.get("ring_id") == "united-states"]
    assert len(rings) == 1, merged
    r = rings[0]
    assert r["mentions"] == 40 + 15 + 5 + 3
    assert r["articles"] == 22  # max member, never a double-counting sum
    assert r["language_breakdown"] == {"en": 40, "ru": 15, "pt": 5, "tr": 3}
    assert {m["normalized"] for m in r["members"]} == {"USA", "США", "EUA", "ABD"}
    # WHO stays a distinct, unrelated entity -- never accidentally folded in
    assert any(m["normalized"] == "WHO" and "ring_id" not in m for m in merged)


def test_fsb_nba_nhl_entity_rings_present_and_case_insensitive():
    """The remaining §0-row-5 fractures (FSB/ФСБ, NBA/НБА, NHL/НХЛ) each merge too."""
    for rid, latin, cyr in (("fsb", "FSB", "ФСБ"), ("nba", "NBA", "НБА"), ("nhl", "NHL", "НХЛ")):
        rows = [
            {"term": latin, "normalized": latin, "kind": "entity", "mentions": 10, "articles": 6},
            {"term": cyr, "normalized": cyr, "kind": "entity", "mentions": 4, "articles": 3},
        ]
        lang_of = _lang({latin: "en", cyr: "ru"})
        merged = E.merge_equivalents(rows, lang_of=lang_of)
        rings = [m for m in merged if m.get("ring_id") == rid]
        assert len(rings) == 1, (rid, merged)
        assert rings[0]["mentions"] == 14


def test_polysemy_is_language_qualified_fr_main_vs_en_main():
    rows = [
        {"term": "hand", "normalized": "hand", "kind": "term", "mentions": 5},
        {"term": "main", "normalized": "main", "kind": "term", "mentions": 3},
    ]
    # fr:main is part of the 'hand' ring -> merges
    merged_fr = E.merge_equivalents(rows, lang_of=_lang({"hand": "en", "main": "fr"}))
    assert any(m.get("ring_id") == "hand" for m in merged_fr)
    # en:main is the English adjective -> NOT in the ring -> no merge (hand stays solo)
    merged_en = E.merge_equivalents(rows, lang_of=_lang({"hand": "en", "main": "en"}))
    assert all(m.get("ring_id") is None for m in merged_en)


def test_user_split_override_keeps_a_member_out_of_its_ring():
    rows = [
        {"term": "election", "normalized": "election", "kind": "term", "mentions": 50},
        {"term": "élection", "normalized": "élection", "kind": "term", "mentions": 20},
    ]
    lang_of = _lang({"election": "en", "élection": "fr"})
    # split: élection pinned to its own key -> stays out -> election left alone -> no merge
    overrides = {"élection": {"family_key": "élection"}}
    merged = E.merge_equivalents(rows, lang_of=lang_of, overrides=overrides)
    assert all(m.get("ring_id") is None for m in merged)


def test_lone_present_member_is_not_merged():
    rows = [{"term": "wahl", "normalized": "wahl", "kind": "term", "mentions": 10}]
    merged = E.merge_equivalents(rows, lang_of=_lang({"wahl": "de"}))
    assert merged[0].get("ring_id") is None  # only one ring member present


def test_disabled_or_missing_rings_is_a_noop(monkeypatch):
    monkeypatch.setenv("OO_KEYWORD_EQUIV", "0")
    E.load_rings.cache_clear()
    E._index.cache_clear()
    try:
        rows = [
            {"normalized": "election", "term": "election", "mentions": 1},
            {"normalized": "élection", "term": "élection", "mentions": 1},
        ]
        out = E.merge_equivalents(rows, lang_of=_lang({"election": "en", "élection": "fr"}))
        assert out == rows  # untouched
    finally:
        monkeypatch.delenv("OO_KEYWORD_EQUIV", raising=False)
        E.load_rings.cache_clear()
        E._index.cache_clear()


# --- integration: queries.py wiring on an in-memory corpus ------------------- #


def _kw(s, term, normalized, *, language, kind="term"):
    k = Keyword(
        term=term,
        normalized_term=normalized,
        language=language,
        frequency=0,
        is_entity=(kind != "term"),
        entity_type=(None if kind == "term" else kind),
    )
    s.add(k)
    s.flush()
    return k


def _corpus():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_election(s, *, fr_language="fr"):
    """3 en articles mention 'election', 2 fr articles mention 'élection'; a non-ring
    'weather' term too. ``fr_language`` lets a test seed the fr keyword with an
    unknown stored language to exercise the signature fallback."""
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    arts = []
    for i, lg in enumerate(["en", "en", "en", "fr", "fr"]):
        a = Article(
            url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}", source_id=1,
            title=f"t{i}", content="x", hash=f"h{i}", language=lg,
        )
        s.add(a)
        arts.append(a)
    s.flush()
    election = _kw(s, "election", "election", language="en")
    elec_fr = _kw(s, "élection", "élection", language=fr_language)
    weather = _kw(s, "weather", "weather", language="en")
    for a in arts[:3]:  # en articles -> election
        s.add(KeywordMention(keyword_id=election.id, article_id=a.id, count=4, observed_on=date.today()))
    for a in arts[3:]:  # fr articles -> élection
        s.add(KeywordMention(keyword_id=elec_fr.id, article_id=a.id, count=3, observed_on=date.today()))
    s.add(KeywordMention(keyword_id=weather.id, article_id=arts[0].id, count=1, observed_on=date.today()))
    s.commit()
    # top_terms now reads the denormalised Keyword counters (slice 2); populate them
    # from the seeded mentions exactly as index_article does in production.
    backfill_keyword_counters(s)


def test_top_terms_grouped_merges_cross_language_ring():
    Sess = _corpus()
    with Sess() as s:
        _seed_election(s)
        res = q.top_terms(s, group=True, limit=10)
        ring = [t for t in res["terms"] if t.get("ring_id") == "election"]
        assert len(ring) == 1, res["terms"]
        r = ring[0]
        assert r["mentions"] == 3 * 4 + 2 * 3  # en election (12) + fr élection (6)
        assert r["language_breakdown"] == {"en": 12, "fr": 6}
        assert res.get("rings_merged") is True and "caveat" in res
        # the non-ring term is still present and not ringed
        assert any(t["normalized"] == "weather" for t in res["terms"])


def test_top_terms_signature_fallback_when_language_unknown():
    # élection stored with UNKNOWN language; its mentions are all in fr articles,
    # so the dominant-signature join still places it in the ring.
    Sess = _corpus()
    with Sess() as s:
        _seed_election(s, fr_language=None)
        res = q.top_terms(s, group=True, limit=10)
        ring = [t for t in res["terms"] if t.get("ring_id") == "election"]
        assert len(ring) == 1
        assert ring[0]["language_breakdown"] == {"en": 12, "fr": 6}


def test_trending_windows_series_sums_ring_members():
    # the merged "ring:<id>" normalized doesn't resolve to a keyword, so the
    # per-term daily series must sum the members' own series.
    Sess = _corpus()
    with Sess() as s:
        _seed_election(s)
        res = q.trending_windows(s, limit=10, series_top=10)
        found = False
        for w in res["windows"]:
            ring = [t for t in w["terms"] if t.get("ring_id") == "election"]
            if ring:
                found = True
                assert sum(p["count"] for p in ring[0]["series"]) == 12 + 6
        assert found, "expected an election ring row in some window"


def test_associations_grouped_merges_ring_neighbours():
    Sess = _corpus()
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        arts = []
        for i, lg in enumerate(["en", "en", "fr", "fr"]):
            a = Article(
                url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}", source_id=1,
                title=f"t{i}", content="x", hash=f"h{i}", language=lg,
            )
            s.add(a)
            arts.append(a)
        s.flush()
        seed = _kw(s, "vote", "vote", language="en")
        election = _kw(s, "election", "election", language="en")
        elec_fr = _kw(s, "élection", "élection", language="fr")
        for a in arts:
            s.add(KeywordMention(keyword_id=seed.id, article_id=a.id, count=1, observed_on=date.today()))
        for a in arts[:2]:
            s.add(KeywordMention(keyword_id=election.id, article_id=a.id, count=1, observed_on=date.today()))
        for a in arts[2:]:
            s.add(KeywordMention(keyword_id=elec_fr.id, article_id=a.id, count=1, observed_on=date.today()))
        s.commit()
        res = q.associations(s, "vote", min_cooccur=1, group=True)
        ring = [p for p in res["pairs"] if p.get("ring_id") == "election"]
        assert len(ring) == 1, res["pairs"]
        assert set(ring[0]["language_breakdown"]) == {"en", "fr"}
        assert "per-language counts shown" in res["caveat"]
