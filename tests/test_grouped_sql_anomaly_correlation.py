"""S9 — grouped-SQL rewrites of the corpus-anomaly + commodity-correlation daily counts.

Both endpoints used to materialise ONE ``published_at`` row per article and count by date in
Python (a field-scale freeze). They now GROUP BY the publish-day in SQL (an index-only scan,
O(days) rows). This pins the two contracts:

  * BYTE-PARITY — the grouped counts (and every downstream z-score / correlation input) equal
    the prior ``Counter(r[0].date() for r in rows)`` loop, because
    ``substr(published_at, 1, 10)`` == Python ``datetime.date()`` on the naive stored ISO
    string;
  * the grouped GROUP BY runs and the O(articles) row materialisation is gone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Source
from src.monitoring.anomaly import volume_anomalies

_HAS_SCIPY = importlib.util.find_spec("scipy") is not None

# 6 days, one clear spike on day 6 -> exactly one z-score anomaly (a non-vacuous golden).
_DAY_COUNTS = {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 20}


def _engine_with_corpus():
    # StaticPool: ONE shared in-memory connection, so the TestClient's request-handler
    # thread sees the same DB (+ tables) the fixture set up in the main thread.
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    aid = 0
    with Sess() as s:
        s.add(Source(name="S", domain="s.test"))
        s.flush()
        for day, c in _DAY_COUNTS.items():
            for _ in range(c):
                aid += 1
                # tz-aware UTC (as the real ingest paths + the existing fixtures store) and,
                # for one row, a naive datetime + a non-midnight time, to exercise both.
                tz = None if aid % 7 == 0 else UTC
                s.add(Article(
                    url=f"u{aid}", canonical_url=f"u{aid}", source_id=1, title="neodymium",
                    content="neodymium supply news", hash=f"{aid:064d}",
                    published_at=datetime(2026, 1, day, aid % 24, tzinfo=tz),
                ))
        # a NULL-published article must be ignored by both paths
        aid += 1
        s.add(Article(url=f"u{aid}", canonical_url=f"u{aid}", source_id=1, title="x",
                      content="x", hash=f"{aid:064d}", published_at=None))
        s.commit()
    return eng, Sess


def _reference_daily(Sess) -> dict[date, int]:
    """The pre-refactor Python loop = the golden."""
    with Sess() as s:
        rows = s.query(Article.published_at).filter(Article.published_at.isnot(None)).all()
    return dict(Counter(r[0].date() for r in rows))


def _grouped_daily(Sess) -> dict[date, int]:
    with Sess() as s:
        return {
            date.fromisoformat(d): int(c)
            for d, c in s.execute(
                text(
                    "SELECT substr(published_at, 1, 10) AS d, COUNT(*) AS c FROM articles"
                    " WHERE published_at IS NOT NULL GROUP BY substr(published_at, 1, 10)"
                )
            )
        }


def _client(Sess):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def test_grouped_daily_counts_match_the_python_loop_byte_for_byte():
    _eng, Sess = _engine_with_corpus()
    ref = _reference_daily(Sess)
    got = _grouped_daily(Sess)
    assert got == ref  # identical dict[date, int], NULL-pub row excluded on both paths
    assert got  # non-vacuous


def test_grouped_query_uses_an_index_no_bare_table_scan():
    _eng, Sess = _engine_with_corpus()
    with Sess() as s:
        plan = [
            r[-1]
            for r in s.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT substr(published_at, 1, 10) AS d, COUNT(*)"
                    " FROM articles WHERE published_at IS NOT NULL"
                    " GROUP BY substr(published_at, 1, 10)"
                )
            )
        ]
    # the articles table is reached via an index (covering), never a bare `SCAN articles`
    # without USING (the covering-index classification lesson).
    art_steps = [p for p in plan if "articles" in p.lower()]
    assert art_steps, plan
    assert all("using" in p.lower() for p in art_steps), plan
    assert not any(
        p.lower().startswith("scan") and "using" not in p.lower() for p in art_steps
    ), plan


def test_anomaly_endpoint_is_byte_identical_and_uses_grouped_sql():
    _eng, Sess = _engine_with_corpus()
    # the golden: the pre-refactor loop through volume_anomalies (unchanged pure fn)
    ref = volume_anomalies(_reference_daily(Sess), z_threshold=2.0)
    ref_dicts = [a.to_dict() for a in ref]
    assert ref_dicts and any(a["day"] == "2026-01-06" for a in ref_dicts)  # non-vacuous

    app, client = _client(Sess)
    seen: list[str] = []

    @event.listens_for(_eng, "before_cursor_execute")
    def _cap(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        seen.append(" ".join(statement.split()).lower())

    try:
        with client:
            r = client.get("/api/monitoring/anomalies", params={"z_threshold": 2.0})
        assert r.status_code == 200, r.text
        body = r.json()
    finally:
        event.remove(_eng, "before_cursor_execute", _cap)
        app.dependency_overrides.clear()

    assert body["anomalies"] == ref_dicts  # byte-identical
    assert body["days_observed"] == len(_reference_daily(Sess))
    # the grouped GROUP BY ran; the O(articles) published_at materialisation is gone.
    assert any("group by substr(published_at" in s for s in seen), seen
    assert not any("select articles.published_at from articles" in s for s in seen), seen


def test_correlation_grouped_counts_with_an_id_filter_match_the_loop():
    _eng, Sess = _engine_with_corpus()
    with Sess() as s:
        all_ids = [r[0] for r in s.execute(text("SELECT id FROM articles WHERE id % 2 = 0"))]
        # loop reference over the SAME id set
        rows = (
            s.query(Article.published_at)
            .filter(Article.published_at.isnot(None), Article.id.in_(all_ids))
            .all()
        )
        ref = dict(Counter(r[0].date() for r in rows))
        marks = ",".join(str(int(i)) for i in all_ids)
        got = {
            date.fromisoformat(d): int(c)
            for d, c in s.execute(
                text(
                    "SELECT substr(published_at, 1, 10) AS d, COUNT(*) AS c FROM articles"
                    f" WHERE published_at IS NOT NULL AND id IN ({marks})"
                    " GROUP BY substr(published_at, 1, 10)"
                )
            )
        }
    assert got == ref


@pytest.mark.skipif(not _HAS_SCIPY, reason="scipy (the [analysis] extra) not installed")
def test_correlate_price_with_counts_equals_the_list_wrapper():
    """The refactor moved ``Counter(article_dates)`` out of the core into the wrapper; the
    count-input entry point must be byte-identical to the list-input one on the same data."""
    from src.commodity.correlation import (
        correlate_price_with_counts,
        correlate_price_with_news,
    )

    pp = [
        (date(2026, 1, 1), 100.0), (date(2026, 1, 2), 101.0), (date(2026, 1, 3), 103.0),
        (date(2026, 1, 4), 106.0), (date(2026, 1, 5), 110.0),
    ]
    dates = ([date(2026, 1, 2)] + [date(2026, 1, 3)] * 2
             + [date(2026, 1, 4)] * 3 + [date(2026, 1, 5)] * 4)
    a = correlate_price_with_news(pp, dates)
    b = correlate_price_with_counts(pp, Counter(dates))
    assert a.to_dict() == b.to_dict()
    assert b.coefficient is not None  # exercised the real scipy path, not the gap branch
    # the insufficient-data branch (no scipy call) is equal too
    assert (
        correlate_price_with_news(pp, [date(2026, 1, 2)]).to_dict()
        == correlate_price_with_counts(pp, Counter([date(2026, 1, 2)])).to_dict()
    )
