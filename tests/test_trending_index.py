"""The time-windowed trending aggregation uses a covering index (perf brief §3.E).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``trending()._counts`` runs ``SELECT keyword_id, SUM(count) WHERE observed_on IN
[lo,hi) GROUP BY keyword_id`` — the #1 perf hotspot (polled from Home). The
``ix_mention_date_keyword`` covering index turns it into an index-only range scan
(no per-row heap page = no SQLCipher decrypt). Zero drift: it is an index, always
correct, so this asserts the PLAN changes while RESULTS do not.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from src.database.models import Base, KeywordMention

# The exact shape trending()._counts emits (no country filter — the Home path).
_COUNTS_SQL = (
    "SELECT keyword_id, SUM(count) FROM keyword_mentions "
    "WHERE observed_on >= :lo AND observed_on < :hi GROUP BY keyword_id"
)


def _engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(conn, n=4000):
    today = date.today()
    rows = [
        {
            "keyword_id": random.randint(1, 300),
            "article_id": i,
            "count": random.randint(1, 5),
            "observed_on": (today - timedelta(days=random.randint(0, 60))).isoformat(),
        }
        for i in range(n)
    ]
    conn.execute(
        text(
            "INSERT INTO keyword_mentions(keyword_id, article_id, count, observed_on) "
            "VALUES(:keyword_id, :article_id, :count, :observed_on)"
        ),
        rows,
    )


def _params():
    today = date.today()
    return {"lo": (today - timedelta(days=7)).isoformat(), "hi": (today + timedelta(days=1)).isoformat()}


def test_index_is_created_from_the_model():
    eng = _engine()
    with eng.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert "ix_mention_date_keyword" in names


def test_trending_counts_query_uses_the_covering_index():
    eng = _engine()
    with eng.begin() as conn:
        _seed(conn)
        conn.execute(text("ANALYZE"))
        plan = "\n".join(
            str(r) for r in conn.execute(text("EXPLAIN QUERY PLAN " + _COUNTS_SQL), _params())
        )
    assert "USING COVERING INDEX ix_mention_date_keyword" in plan, plan


def test_index_does_not_change_results():
    eng = _engine()
    with eng.begin() as conn:
        _seed(conn)
        with_index = sorted(conn.execute(text(_COUNTS_SQL), _params()).all())
        conn.execute(text("DROP INDEX ix_mention_date_keyword"))
        without_index = sorted(conn.execute(text(_COUNTS_SQL), _params()).all())
    assert with_index == without_index and with_index  # identical and non-empty


def test_ensure_hot_indexes_self_heals_the_new_index():
    from src.database.maintenance import ensure_hot_indexes

    eng = _engine()
    with eng.begin() as conn:
        conn.execute(text("DROP INDEX ix_mention_date_keyword"))
    created = ensure_hot_indexes(eng)
    assert "ix_mention_date_keyword" in created
    assert ensure_hot_indexes(eng) == []  # idempotent


def test_migration_matches_model_index():
    """Drift guard: the alembic migration creates exactly the model's index columns."""
    from pathlib import Path

    cols = None
    for idx in KeywordMention.__table_args__:
        if getattr(idx, "name", "") == "ix_mention_date_keyword":
            cols = [c.name for c in idx.columns]
    assert cols == ["observed_on", "keyword_id", "count"]
    mig = Path(
        "migrations/versions/b4c5d6e7f8a9_mention_date_keyword_index.py"
    ).read_text(encoding="utf-8")
    for col in cols:
        assert col in mig
