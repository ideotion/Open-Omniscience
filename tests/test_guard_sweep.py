"""
S2.4 — the P1.2 guard-coverage sweep: corpus-scaled reads outside heavy.py are now
behind the admission cap + single-flight + statement deadline (guarded_read /
_deadlined). These pin: the wrap is transparent on success, the omnibar DEGRADES
(never 429/503) under load, and the wiring is present.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.fixture(autouse=True)
def _reset_heavy():
    from src.api import heavy

    heavy._reset_for_tests()
    yield
    heavy._reset_for_tests()


# --------------------------------------------------------------------------- #
# Transparent-on-success: a guarded endpoint returns the same shape it always did
# --------------------------------------------------------------------------- #


def test_link_stats_is_correct_through_the_guard():
    from src.api import link_analysis
    from src.database.models import Article, ArticleLink, Source
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as db:
        src = Source(name="lg", domain="lg.example", language="en", enabled=False)
        db.add(src)
        db.flush()
        a = Article(url="https://lg.example/1", canonical_url="https://lg.example/1",
                    source_id=src.id, title="t", content="body", hash="lg-h1")
        db.add(a)
        db.flush()
        db.add_all([
            ArticleLink(article_id=a.id, url="https://o.example/x",
                        normalized_url="https://o.example/x", link_type="external"),
            ArticleLink(article_id=a.id, url="https://o.example/y",
                        normalized_url="https://o.example/y", link_type="external"),
        ])
        db.commit()
        out = link_analysis.stats(db=db)
        assert out["external_links"] == 2
        assert out["distinct_links"] == 2
        assert out["articles_with_links"] == 1


def test_omni_returns_groups_through_the_guard():
    from src.api import search_omni
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as db:
        out = search_omni.omni(q="climate policy", db=db)
    assert out["q"] == "climate policy"
    assert isinstance(out["groups"], list)
    assert "degraded" not in out  # a healthy call is never the degraded payload


# --------------------------------------------------------------------------- #
# The omnibar DEGRADES (never a 429/503) under load — it must never blank
# --------------------------------------------------------------------------- #


def test_omni_degrades_gracefully_when_busy(monkeypatch):
    from src.api import heavy, search_omni
    from src.database.session import init_db, session_scope

    init_db()

    def _busy(key, compute):
        raise heavy.HeavyBusy("at capacity")

    monkeypatch.setattr(heavy, "run_heavy", _busy)
    with session_scope() as db:
        out = search_omni.omni(q="anything", db=db)
    # Honest degraded payload, still a 200-shaped dict — never a raised 429.
    assert out["degraded"]
    assert out["groups"] == []
    assert out["q"] == "anything"


def test_omni_degrades_gracefully_on_timeout(monkeypatch):
    from src.api import heavy, search_omni
    from src.database.maintenance import StatementTimeout
    from src.database.session import init_db, session_scope

    init_db()

    def _slow(key, compute):
        raise StatementTimeout("deadline")

    monkeypatch.setattr(heavy, "run_heavy", _slow)
    with session_scope() as db:
        out = search_omni.omni(q="anything", db=db)
    assert out["degraded"]
    assert out["groups"] == []


# --------------------------------------------------------------------------- #
# Wiring guards: the swept endpoints compose the guard (never assert side-by-side)
# --------------------------------------------------------------------------- #


def test_insights_raw_endpoints_are_now_deadlined():
    from src.api import insights

    for name in (
        "insights_who",
        "insights_where",
        "insights_convergences",
        "insights_ring_countries",
        "insights_ring_stats",
        "insights_source_laundering",
        "insights_recycled_claims",
        "insights_reading_diet_by_type",
        "keywords_by_tag",
    ):
        src = inspect.getsource(getattr(insights, name))
        assert "_deadlined(" in src, f"{name} is not guarded by _deadlined"


def test_insights_manipulation_cards_upgraded_from_cache_only_to_deadlined():
    from src.api import insights

    for name in (
        "insights_headline_body_mismatch",
        "insights_manufactured_emergence",
        "insights_flooded_topics",
        "insights_copypasta",
        "insights_source_types",
        "insights_map_coverage",
    ):
        src = inspect.getsource(getattr(insights, name))
        assert "_deadlined(" in src, f"{name} still cache-only (no admission cap/deadline)"


def test_link_analysis_and_omni_are_guarded():
    from src.api import link_analysis, search_omni

    for fn in (link_analysis.stats, link_analysis.top_cited, link_analysis.articles_by_link,
               link_analysis._citation_graph):
        assert "guarded_read(" in inspect.getsource(fn), f"{fn.__name__} not guarded"
    assert "guarded_read(" in inspect.getsource(search_omni.omni)
