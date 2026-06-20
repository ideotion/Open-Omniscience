"""The A1 read-model seam (data-architecture Slice 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The seam (``src.analytics.readmodel``) is the ONE boundary the heavy whole-corpus
aggregate reads flow through, so Slice 4 can swap in a derived columnar store without
touching an endpoint. v1 must be a BYTE-IDENTICAL delegation to the live queries — and
the endpoints must actually route through it. Both are proven here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics import readmodel as rm
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The federal budget debate gripped the Senate chamber today.",
        "Senate leaders argued the federal budget late into the night.",
        "Climate policy and the federal budget collided in committee.",
    ]
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=t, hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def test_seam_delegates_byte_identically(db):
    # Each seam entry point returns EXACTLY what the live query returns (v1).
    assert rm.top_terms(db, days=None, country=None, kind=None, limit=20, group=True) == \
        q.top_terms(db, days=None, country=None, kind=None, limit=20, group=True)
    assert rm.trending(db, window_days=7, baseline_days=30, limit=20) == \
        q.trending(db, window_days=7, baseline_days=30, limit=20)
    assert rm.trending_windows(db, limit=10, series_top=0) == \
        q.trending_windows(db, limit=10, series_top=0)
    assert rm.associations(db, "budget", limit=20) == q.associations(db, "budget", limit=20)
    assert rm.source_country_counts(db) == q.source_country_counts(db)


def test_seam_covers_the_heavy_aggregates():
    # The documented boundary must expose every read Slice 4 will port.
    for name in (
        "top_terms", "trending", "trending_windows", "associations",
        "layered_graph", "article_graph", "source_country_counts",
    ):
        assert callable(getattr(rm, name)), f"seam missing {name}"


def test_top_endpoint_routes_through_the_seam(db, monkeypatch):
    # Patch the seam -> the sentinel must surface in the endpoint response, proving the
    # endpoint reads through readmodel (not queries directly). Cache off for determinism.
    monkeypatch.setenv("OO_INSIGHTS_CACHE_TTL", "0")
    import importlib

    import src.api.insights as I
    importlib.reload(I)

    sentinel = {"terms": [{"term": "SEAM_SENTINEL"}], "count": 1}
    monkeypatch.setattr(I.rm, "top_terms", lambda *a, **k: dict(sentinel))
    out = I.insights_top(
        days=None, country=None, kind=None, limit=20, group=True, target_lang=None, db=db
    )
    assert out["terms"] == [{"term": "SEAM_SENTINEL"}]
    # The Slice-2 envelope is still attached on top of the seam's result.
    assert "counts" in out and out["counts"]["basis"] in ("exact", "estimated")
    # Restore the module WITHOUT the cache-disabling env first, so a later test in the
    # same process (e.g. test_insights_cache) doesn't inherit a module reloaded with
    # _CACHE_TTL_S=0 (monkeypatch reverts the env only at teardown, after this body).
    monkeypatch.delenv("OO_INSIGHTS_CACHE_TTL", raising=False)
    importlib.reload(I)  # restore the real module for other tests
