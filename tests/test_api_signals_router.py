"""The /api/signals router: FDR self-test + flood/bury exploration endpoints.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The statistics live in src.stats.fdr and src.analytics.concentration (tested there);
this pins the ROUTER surface — that the three signal endpoints exist, that the FDR
self-test endpoint returns the passing log, and that the flood/bury endpoints delegate
end-to-end (fire on a real corpus, stay honest on a tiny one, carry method+caveat, and
never expose a score). The endpoint functions are called directly with an in-memory
Session (the crypto-free pattern); the full TestClient path is CI-only.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.signals import router, signals_bury, signals_fdr_selftest, signals_flood
from src.database.models import Base, Keyword, KeywordMention, Source

TODAY = date.today()
WHEN = TODAY - timedelta(days=5)          # inside the 30-day bury window
RECENT = TODAY - timedelta(days=2)        # inside the 7-day flood window
PRIOR = TODAY - timedelta(days=30)        # inside the flood baseline (7..91 days ago)

_AID = [10_000]


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


def _source(db, sid, name):
    db.add(Source(id=sid, name=name, domain=f"{name}.test"))


def _keyword(db, kid, term):
    db.add(Keyword(id=kid, term=term, normalized_term=term))


def _km(db, source_id, keyword_id, observed, n):
    """``n`` distinct articles for a (source, keyword) at ``observed`` (km rows only —
    neither concentration function reads the Article table)."""
    for _ in range(n):
        _AID[0] += 1
        db.add(KeywordMention(
            source_id=source_id, keyword_id=keyword_id, article_id=_AID[0],
            count=1, observed_on=observed,
        ))


# --------------------------------------------------------------------------- #
# Router surface
# --------------------------------------------------------------------------- #

def test_router_exposes_the_three_signal_routes():
    routes = {r.path: r.methods for r in router.routes}
    assert routes.get("/api/signals/fdr-selftest") == {"GET"}
    assert routes.get("/api/signals/bury") == {"GET"}
    assert routes.get("/api/signals/flood") == {"GET"}


def test_fdr_selftest_endpoint_returns_the_passing_log():
    resp = signals_fdr_selftest(download=False)
    log = json.loads(resp.body)
    assert log["schema"] == "oo-fdr-selftest-1"
    assert log["all_passed"] is True and log["n_cases"] == 10


def test_fdr_selftest_endpoint_download_sets_attachment_header():
    resp = signals_fdr_selftest(download=True)
    assert "attachment" in resp.headers.get("content-disposition", "")


# --------------------------------------------------------------------------- #
# Bury endpoint (item 5 — the inverse of the flood card)
# --------------------------------------------------------------------------- #

def _seed_bury(db):
    _keyword(db, 1, "climate")   # the broad topic
    _keyword(db, 2, "sports")    # the target's niche beat
    for sid in range(1, 7):      # six sources cover climate heavily -> broad topic
        _source(db, sid, f"broad{sid}")
        _km(db, sid, 1, WHEN, 20)
    _source(db, 7, "target")     # active but covers the broad topic ZERO -> the gap
    _km(db, 7, 2, WHEN, 30)
    db.commit()


def test_bury_endpoint_fires_and_delegates(db):
    _seed_bury(db)
    out = signals_bury(window_days=30, fdr_q=0.05, z_min=3.0, max_items=12, db=db)
    assert out["count"] >= 1
    hit = next(i for i in out["items"] if i["source"] == "target")
    assert hit["term"] == "climate"
    assert hit["source_share"] < hit["corpus_share"]   # the source is BELOW the corpus
    assert hit["gap_zscore"] <= -3.0                   # cleared the effect gate
    assert hit["fdr_qvalue"] is not None and hit["fdr_qvalue"] <= 0.05  # survived FDR
    assert out["method"] and out["caveat"]
    # No score-shaped key on any surfaced item.
    for it in out["items"]:
        assert not any(k.lower() == "score" or k.lower().endswith("_score") for k in it)


def test_bury_breadth_is_distinct_sources_not_article_count(db):
    # Same topic ARTICLE COUNT (120), different SOURCE count. Breadth is measured by
    # distinct sources, so 120 articles from 4 sources is NOT "broad" (no finding), while
    # 120 from 5 sources is (the under-covering target surfaces). Proves the independence
    # measure is distinct sources, never article volume.
    _keyword(db, 1, "climate")
    _keyword(db, 2, "sports")
    for sid in range(1, 5):          # 4 sources x 30 = 120 climate articles, only 4 sources
        _source(db, sid, f"few{sid}")
        _km(db, sid, 1, WHEN, 30)
    _source(db, 9, "target")
    _km(db, 9, 2, WHEN, 25)
    db.commit()
    out = signals_bury(window_days=30, fdr_q=0.05, z_min=3.0, max_items=12, db=db)
    assert out["count"] == 0                            # 120 articles / 4 sources is not broad
    assert "note" in out

    # Add a FIFTH source covering climate (same 120-ish article scale) -> now broad -> fires.
    _source(db, 5, "few5")
    _km(db, 5, 1, WHEN, 30)
    db.commit()
    out2 = signals_bury(window_days=30, fdr_q=0.05, z_min=3.0, max_items=12, db=db)
    assert any(i["source"] == "target" for i in out2["items"])


# --------------------------------------------------------------------------- #
# Flood endpoint
# --------------------------------------------------------------------------- #

def _seed_flood(db):
    _source(db, 1, "flooder")
    _keyword(db, 1, "scandal")   # the flooded topic
    _keyword(db, 99, "filler")
    # Recently ALL about the topic (10/10), historically rare (1/12) -> a real jump.
    _km(db, 1, 1, RECENT, 10)
    _km(db, 1, 1, PRIOR, 1)
    _km(db, 1, 99, PRIOR, 11)
    db.commit()


def test_flood_endpoint_fires_and_delegates(db):
    _seed_flood(db)
    out = signals_flood(recent_days=7, baseline_days=84, z_min=2.5, min_share=0.25,
                        max_items=12, db=db)
    assert out["count"] >= 1
    it = out["items"][0]
    assert it["term"] == "scandal" and it["source"] == "flooder"
    assert it["share_now"] > it["baseline_share"] and it["share_zscore"] >= 2.5
    assert out["method"] and out["caveat"]
    for it in out["items"]:
        assert not any(k.lower() == "score" or k.lower().endswith("_score") for k in it)


# --------------------------------------------------------------------------- #
# Honest empty states
# --------------------------------------------------------------------------- #

def test_empty_corpus_is_honest_for_both_endpoints(db):
    bury = signals_bury(window_days=30, fdr_q=0.05, z_min=3.0, max_items=12, db=db)
    assert bury["count"] == 0 and bury["items"] == []
    assert bury["caveat"] and bury["method"] and "note" in bury

    flood = signals_flood(recent_days=7, baseline_days=84, z_min=2.5, min_share=0.25,
                          max_items=12, db=db)
    assert flood["count"] == 0 and flood["items"] == []
    assert flood["caveat"] and flood["method"]
