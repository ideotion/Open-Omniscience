"""The keyword write-cost diagnostic: what an indexed article costs the mentions tables.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The SQLCipher build the operator runs has no ``dbstat``, so D47 (b)'s deciding number (how
much of the file is the mentions table and its ten indexes) could never be taken. The module
estimates it from a sample and says so. This file proves the estimate against reality where
reality is available (a build WITH dbstat), and the refusals that keep it honest everywhere:
an unmeasurable window says why and never reads ``0``, an abort is reported and never a hang,
and no key is score-shaped.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import sessionmaker

from src.database.derived_views import ensure_derived_views
from src.database.maintenance import StatementTimeout
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.monitoring import keyword_write_cost as kwc
from src.monitoring.keyword_write_cost import keyword_write_cost


def _dbstat_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("SELECT COUNT(*) FROM dbstat").fetchone()
            return True
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - any failure = the build lacks the vtab
        return False


_HAS_DBSTAT = _dbstat_available()
_NOW = datetime(2026, 9, 30, 12, 0, 0)


def _seed(session, *, articles: int, per_article: int, created_at: datetime) -> None:
    session.add(Source(name="S", domain="x.test", country="fr"))
    session.flush()
    arts = [
        {
            "url": f"https://x.test/{i}", "canonical_url": f"https://x.test/{i}",
            "source_id": 1, "title": "T", "content": "c", "hash": f"h{i}", "language": "en",
            "created_at": created_at,
        }
        for i in range(1, articles + 1)
    ]
    session.execute(insert(Article), arts)
    kws = [
        {"term": f"k{i}", "normalized_term": f"k{i}", "language": "en"}
        for i in range(1, per_article + 1)
    ]
    session.execute(insert(Keyword), kws)
    rows = [
        {
            "keyword_id": k, "article_id": a, "count": 1 + (a + k) % 7, "first_offset": a * 3,
            "observed_on": date(2024, 1, 1 + a % 28), "country": "fr", "language": "en",
            "source_id": 1, "extractor": "baseline", "created_at": created_at,
        }
        for a in range(1, articles + 1)
        for k in range(1, per_article + 1)
    ]
    session.execute(insert(KeywordMention), rows)
    session.commit()


@pytest.fixture()
def make_db(tmp_path):
    made = []

    def _make(**kw):
        engine = create_engine(
            f"sqlite:///{tmp_path / f'w{len(made)}.db'}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        ensure_derived_views(engine)
        s = sessionmaker(bind=engine, future=True)()
        if kw:
            _seed(s, **kw)
        made.append(s)
        return s

    yield _make
    for s in made:
        s.close()


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_row_size_is_sampled_through_the_seam_and_names_its_method(make_db):
    s = make_db(articles=40, per_article=10, created_at=_NOW)
    out = keyword_write_cost(s, now=_NOW)
    assert out["available"] is True
    assert out["row_size"]["sampled"] == 400  # fewer rows than the sample: every one read
    cols = out["row_size"]["columns"]
    assert "id" not in cols  # the rowid alias is the key, not part of the record
    assert cols["country"] == 2.0 and cols["language"] == 2.0  # 'fr' / 'en' in UTF-8
    assert cols["observed_on"] == 10.0  # a date is stored as 'YYYY-MM-DD'
    assert cols["created_at"] == 26.0
    assert out["method"] and out["caveat"]
    assert out["rows"]["rows"] == 400 and "upper bound" in out["rows"]["rows_kind"]


def test_the_split_sizes_every_index_and_is_a_range_not_a_point(make_db):
    s = make_db(articles=40, per_article=10, created_at=_NOW)
    out = keyword_write_cost(s, now=_NOW)
    split = out["estimated_split"]
    names = {i["name"] for i in split["indexes"]}
    assert {"ix_mention_keyword_article", "ix_mention_covering", "ix_mention_created_id"} <= names
    assert split["index_count"] == len(split["indexes"]) >= 8
    for i in split["indexes"]:
        if i["estimated"]:
            assert 0 < i["bytes_low"] < i["bytes_high"]
    assert split["mentions_total_bytes_low"] < split["mentions_total_bytes_high"]
    assert split["rest_of_file_bytes_low"] <= split["rest_of_file_bytes_high"]


@pytest.mark.skipif(
    not _HAS_DBSTAT, reason="dbstat not compiled into this SQLite build (the check needs it)"
)
def test_the_estimate_brackets_what_dbstat_measures(make_db):
    """The reason to trust it: on a build that CAN measure, the estimate lands close."""
    s = make_db(articles=1500, per_article=12, created_at=_NOW)
    out = keyword_write_cost(s, now=_NOW)
    split = out["estimated_split"]
    measured = {
        str(n): int(b)
        for n, b in s.execute(text("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"))
    }
    real_table = measured["keyword_mentions"]
    est_table = split["table"]["bytes_low"]
    assert 0.5 * real_table <= est_table <= 1.6 * real_table, (est_table, real_table)
    real_idx = sum(b for n, b in measured.items() if n.startswith("ix_mention_"))
    est_low = sum(i.get("bytes_low", 0) for i in split["indexes"])
    est_high = sum(i.get("bytes_high", 0) for i in split["indexes"])
    # The measured index total sits inside the estimated range, widened by half either side
    # for the page reserve and the free space the model leaves out.
    assert 0.5 * est_low <= real_idx <= 1.5 * est_high, (est_low, est_high, real_idx)


def test_write_rate_counts_articles_and_names_the_window(make_db):
    s = make_db(articles=20, per_article=5, created_at=_NOW - timedelta(minutes=30))
    rate = keyword_write_cost(s, now=_NOW)["write_rate"]
    one = rate["last_1h"]
    assert one["articles"] == 20 and one["mentions"] == 100
    assert one["articles_per_hour"] == 20.0 and one["mentions_per_article"] == 5.0
    assert rate["last_6h"]["articles_per_hour"] == round(20 / 6, 1)


def test_an_empty_window_says_why_and_is_never_zero(make_db):
    s = make_db(articles=5, per_article=3, created_at=_NOW - timedelta(hours=20))
    rate = keyword_write_cost(s, now=_NOW)["write_rate"]
    for key in ("last_1h", "last_6h"):
        assert rate[key]["available"] is False
        assert "no rate to state" in rate[key]["reason"]
        assert "articles_per_hour" not in rate[key]


def test_an_empty_table_reports_it_without_a_split(make_db):
    s = make_db()
    out = keyword_write_cost(s, now=_NOW)
    assert out["available"] is True
    assert out["row_size"] == {"sampled": 0}
    assert "estimated_split" not in out


def test_a_deadline_abort_is_reported_never_raised(make_db, monkeypatch):
    s = make_db(articles=5, per_article=3, created_at=_NOW)

    @contextmanager
    def _abort(session, seconds=None):
        raise StatementTimeout("slow disk")
        yield  # pragma: no cover

    monkeypatch.setattr(kwc, "statement_deadline", _abort)
    out = keyword_write_cost(s, now=_NOW)
    assert out["available"] is False
    assert "slow disk" in out["reason"]


def test_the_report_has_no_score_shaped_keys(make_db):
    s = make_db(articles=10, per_article=4, created_at=_NOW)
    for k in _keys(keyword_write_cost(s, now=_NOW)):
        assert not any(w in k.lower() for w in ("score", "rating", "quality", "trust")), k


def test_a_second_backend_is_refused_not_guessed(make_db):
    s = make_db()

    class _Bind:
        class dialect:  # noqa: N801 - mimics the SQLAlchemy attribute
            name = "postgresql"

    monkey = s.get_bind
    s.get_bind = lambda *a, **k: _Bind  # type: ignore[method-assign]
    try:
        out = keyword_write_cost(s)
    finally:
        s.get_bind = monkey  # type: ignore[method-assign]
    assert out["available"] is False and "SQLite" in out["reason"]
