"""Home must not stay empty when the corpus has grown (P0-3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-06-22: Home showed "No Leads yet" on a 7,800-article corpus,
because the briefing cache is refreshed only by the scheduler post-pass and the
app boots in airplane mode (scheduler idle) — so a cache built when the corpus
was tiny left Home empty forever. get_briefing now recomputes when the corpus has
grown materially since the cache was generated, bounded so a stable corpus always
reads the cache instantly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.briefing import service
from src.database.models import Article, Base, Source


@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.commit()
    now = datetime.now(UTC)
    for i in range(12):  # "election" trends -> a rising Lead is produced
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title=f"Story {i}", hash=f"h{i}", language="en",
            content="The election dominated the election news as election coverage spread.",
            published_at=now - timedelta(days=i % 4), created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr")
    return s


def _write_cache(cards: list, article_count) -> None:
    payload = {
        "version": service.CACHE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "cards": cards,
    }
    if article_count is not None:
        payload["article_count"] = article_count
    service._cache_path().write_text(json.dumps(payload), "utf-8")


def test_is_cache_stale_logic(monkeypatch):
    monkeypatch.setattr(service, "_article_count", lambda _s: 7800)
    assert service._is_cache_stale(None, {"article_count": 500})  # 500 -> 7800: stale
    assert not service._is_cache_stale(None, {"article_count": 7790})  # +10 only: fresh
    # No recorded baseline: stale once if the corpus is non-trivial.
    assert service._is_cache_stale(None, {})
    monkeypatch.setattr(service, "_article_count", lambda _s: 5)
    assert not service._is_cache_stale(None, {})  # tiny corpus: don't churn


def test_get_briefing_recomputes_a_stale_cache(corpus, monkeypatch):
    """A cache generated when the corpus was tiny (empty cards) must be recomputed
    once the corpus has grown — Home shows real Leads, not a stale empty feed."""
    # Pretend the corpus is large now, but the cache was built at 10 articles + 0 cards.
    monkeypatch.setattr(service, "_article_count", lambda _s: 1000)
    _write_cache(cards=[], article_count=10)
    view = service.get_briefing(corpus)
    assert view["buckets"], "a stale empty cache was served instead of recomputing"
    # The fresh cache records the new corpus size so it won't re-trigger.
    assert json.loads(service._cache_path().read_text())["article_count"] == 1000


def test_fresh_cache_is_served_without_recompute(corpus, monkeypatch):
    """A cache whose recorded size matches the corpus is served verbatim (instant) —
    a sentinel card survives, proving run_all did NOT run."""
    monkeypatch.setattr(service, "_article_count", lambda _s: 12)
    sentinel = {
        "id": "sentinel", "type": "x", "title": "SENTINEL", "summary": "s",
        "bucket": "rising", "method": "m", "caveat": "c",
    }
    _write_cache(cards=[sentinel], article_count=12)

    called = {"n": 0}
    real = service.refresh_briefing
    monkeypatch.setattr(service, "refresh_briefing", lambda s: called.__setitem__("n", 1) or real(s))

    view = service.get_briefing(corpus)
    assert called["n"] == 0, "a fresh cache must not be recomputed"
    assert any(c["id"] == "sentinel" for c in view["cards"])
