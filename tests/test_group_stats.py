"""Group-level (cross-language ring) honest statistics (GROUPS amendment §C).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the group-level counterpart of the supergroups S1 fix: a group's headline
total is the deduped sum over its resolved (language-qualified) member keyword ids,
with the disclosure adapted to this level -- top-LANGUAGE dominance, never a
fabricated number on an unknown/unresolvable ring.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.group_stats import group_stats, resolve_group_keyword_ids
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_FORBIDDEN_SCORE_SUBSTRINGS = ("score", "ranking", "rating", "grade")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _ring():
    """A small two-language ring built directly, matching test_ring_country_split's
    convention -- so this test doesn't depend on the shipped catalog's exact
    contents (the loader/catalog itself is tested elsewhere)."""
    from src.analytics import equivalence

    return equivalence.Ring(id="testconcept", members=(("en", "alpha"), ("fr", "alpha")))


def _patch_ring(monkeypatch, ring):
    from src.analytics import equivalence

    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == ring.id else None)
    monkeypatch.setattr(
        equivalence,
        "ring_of",
        lambda lang, norm: ring.id if (lang and (lang, norm) in ring.members) else None,
    )


def _kw(s, term, language, n=0):
    src = s.query(Source).filter_by(domain="g.test").first()
    if src is None:
        src = Source(name="Src", domain="g.test")
        s.add(src)
        s.flush()
    kw = Keyword(
        term=term, normalized_term=term, language=language,
        frequency=0, is_entity=False, mention_count=0, article_count=0,
    )
    s.add(kw)
    s.flush()
    art = Article(
        url=f"https://g.test/{term}-{language}-{n}",
        canonical_url=f"https://g.test/{term}-{language}-{n}",
        source_id=src.id, title="t", content="x", hash=f"h-{term}-{language}-{n}",
    )
    s.add(art)
    s.flush()
    return kw, art, src


def _mention(s, kw, article, count, observed_on=None, source_id=None):
    s.add(
        KeywordMention(
            keyword_id=kw.id,
            article_id=article.id,
            count=count,
            observed_on=observed_on or date.today(),
            source_id=source_id if source_id is not None else article.source_id,
        )
    )


def _no_score_fields(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            assert not any(s in lk for s in _FORBIDDEN_SCORE_SUBSTRINGS), f"score-like key {path}.{k}"
            _no_score_fields(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _no_score_fields(v, f"{path}[{i}]")


def test_group_stats_unknown_ring_degrades_honestly(db):
    out = group_stats(db, "nope-not-a-ring-xyz")
    assert out["found"] is False
    assert "caveat" in out and out["caveat"]
    _no_score_fields(out)


def test_group_stats_totals_and_top_language_dominance(db, monkeypatch):
    ring = _ring()
    _patch_ring(monkeypatch, ring)

    kw_en, art_en, _ = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 10)
    kw_fr, art_fr, _ = _kw(db, "alpha", "fr", 2)
    _mention(db, kw_fr, art_fr, 5)
    db.commit()

    out = group_stats(db, "testconcept")
    assert out["found"] is True
    assert out["group_total"] == {"mentions": 15, "distinct_keywords": 2}
    assert out["dominance"] == {"language": "en", "mentions": 10, "share": round(10 / 15, 4)}
    assert out["languages"] == {"en": 10, "fr": 5}
    _no_score_fields(out)


def test_group_stats_no_resolvable_members_degrades_to_zeros_no_fabricated_dominance(
    db, monkeypatch
):
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    # No Keyword rows exist at all for "alpha" in either language.
    out = group_stats(db, "testconcept")
    assert out["found"] is True
    assert out["group_total"] == {"mentions": 0, "distinct_keywords": 0}
    assert out["dominance"] is None
    assert out["languages"] == {}


def test_group_stats_excludes_no_language_keywords(db, monkeypatch):
    """A keyword whose OWN stored language is None never joins the ring -- the
    same conservative exclusion ring_country_split enforces (never a guess)."""
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    kw, art, _ = _kw(db, "alpha", None, 1)
    _mention(db, kw, art, 40)
    db.commit()

    out = group_stats(db, "testconcept")
    assert out["group_total"]["mentions"] == 0
    assert resolve_group_keyword_ids(db, "testconcept") == set()


def test_group_stats_a_non_member_keyword_never_counts(db, monkeypatch):
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    kw_en, art_en, _ = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 3)
    kw_beta, art_beta, _ = _kw(db, "beta", "en", 2)  # not a ring member
    _mention(db, kw_beta, art_beta, 999)
    db.commit()

    out = group_stats(db, "testconcept")
    assert out["group_total"]["mentions"] == 3
    assert 999 not in out["languages"].values()


def test_group_stats_rate_reflects_the_window(db, monkeypatch):
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    today = date.today()
    kw_en, art_en, _ = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 20, observed_on=today)  # inside a 7-day window
    kw_fr, art_fr, _ = _kw(db, "alpha", "fr", 2)
    _mention(db, kw_fr, art_fr, 40, observed_on=today - timedelta(days=20))  # in the baseline only
    db.commit()

    out = group_stats(db, "testconcept", window_days=7, baseline_days=30)
    assert out["rate"]["recent"] == 20
    assert out["rate"]["prior"] == 40
    assert out["rate"]["window_days"] == 7 and out["rate"]["baseline_days"] == 30


def test_group_stats_series_is_bounded_by_series_days(db, monkeypatch):
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    today = date.today()
    kw_en, art_en, _ = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 7, observed_on=today)
    art_old = Article(
        url="https://g.test/alpha-en-old", canonical_url="https://g.test/alpha-en-old",
        source_id=art_en.source_id, title="t", content="x", hash="h-alpha-en-old",
    )
    db.add(art_old)
    db.flush()
    _mention(db, kw_en, art_old, 3, observed_on=today - timedelta(days=200))  # outside a 30d series
    db.commit()

    out = group_stats(db, "testconcept", series_days=30)
    dates = {p["date"] for p in out["series"]}
    assert today.isoformat() in dates
    assert all(p["count"] != 3 for p in out["series"])  # the 200-day-old point excluded


def test_group_stats_distinct_sources_counts_producing_sources(db, monkeypatch):
    ring = _ring()
    _patch_ring(monkeypatch, ring)
    kw_en, art_en, src_en = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 5, source_id=src_en.id)
    db.commit()

    out = group_stats(db, "testconcept")
    assert out["distinct_sources"] == 1


def test_ring_stats_endpoint_wires_the_deadline_guard_and_returns_the_payload(db, monkeypatch):
    """The /ring-stats endpoint (§C) composes the same _deadlined wiring the
    sibling /ring-countries endpoint uses, and returns group_stats' own payload
    unmodified for a healthy call."""
    from src.api.insights import insights_ring_stats

    ring = _ring()
    _patch_ring(monkeypatch, ring)
    kw_en, art_en, _ = _kw(db, "alpha", "en", 1)
    _mention(db, kw_en, art_en, 9)
    db.commit()

    out = insights_ring_stats(ring_id="testconcept", db=db)
    assert out["found"] is True
    assert out["group_total"]["mentions"] == 9
    assert "degraded" not in out  # a healthy call is never the degraded payload
