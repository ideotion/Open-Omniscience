"""The live-vs-rollup windowed benchmark (scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the benchmark instrument: it builds the rollup over the corpus, reports a faithful
parity check + per-window live-vs-rollup timings, stays read-only, and carries no score.
(The SPEEDUP itself only appears at real corpus scale — on a tiny fixture the live scan of
a few rows beats the rollup's fixed overhead; that's honest, so the test asserts the SHAPE
and PARITY, not a speedup magnitude.)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source
from src.monitoring.rollup_benchmark import run_rollup_benchmark

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

_BANNED = ("score", "rating", "rank", "trust", "credibility", "verdict", "quality_score")


def _no_score(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert str(k).lower() not in _BANNED, f"score-like key {path}.{k}"
            _no_score(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_score(v, f"{path}[{i}]")


@pytest.fixture()
def session():
    e = create_engine("sqlite:///:memory:", future=True,
                      connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    for i in range(6):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content="The federal budget gripped the Senate; climate and drought too.",
            hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2024, 3, 1 + i, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def test_benchmark_shape_parity_and_windows(session):
    out = run_rollup_benchmark(session, repeats=2)
    assert out["available"] is True
    # self-describing context + a real one-time build cost
    assert out["corpus"]["keyword_mentions"] > 0
    assert out["build"]["build_ms"] >= 0 and out["build"]["keyword_daily_rows"] > 0
    # faithful on this corpus: mentions exact, distinct gap zero (unique-constraint)
    assert out["parity"]["mentions_exact"] is True
    assert out["parity"]["distinct_gap_total"] == 0
    # every window compared, both sides cover the same keywords, timings present
    assert len(out["windows"]) == 4
    for w in out["windows"]:
        assert w["counts_match"] is True, f"live/rollup keyword sets differ for {w['window_days']}"
        assert w["live_median_ms"] >= 0 and w["rollup_median_ms"] >= 0


def test_benchmark_is_read_only(session):
    from sqlalchemy import func, text
    from src.database.models import Keyword

    arts = session.query(func.count(Article.id)).scalar()
    ments = session.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar()
    kws = session.query(func.count(Keyword.id)).scalar()
    run_rollup_benchmark(session, repeats=1)
    assert session.query(func.count(Article.id)).scalar() == arts
    assert session.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() == ments
    assert session.query(func.count(Keyword.id)).scalar() == kws


def test_benchmark_carries_no_score(session):
    _no_score(run_rollup_benchmark(session, repeats=1), "rollup_benchmark")
