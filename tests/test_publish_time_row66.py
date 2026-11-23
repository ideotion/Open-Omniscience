"""The publication TIME survives extraction (field report 2026-11-14 section 5.5, open-on-main row 66).

htmldate's default output is the day, so every structured time the page stated was cut to midnight: ~94% of
stored publication times read T00:00:00. Extraction now asks for the time and the offset. A stated offset is
applied (the store keeps naive UTC, like ``created_at``); a page that states only a day keeps that day at
midnight, exactly as before, so nothing is invented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.ingest import extract as ex
from tests._app_engine import app_sqlite_engine

BODY = "<p>" + "A sentence of a real article body that runs long enough to be kept. " * 20 + "</p>"


def _page(head: str) -> str:
    return f"<html><head><title>T</title>{head}</head><body><article><h1>Title here</h1>{BODY}</article></body></html>"


@pytest.mark.parametrize("head,expected", [
    ('<meta property="article:published_time" content="2026-11-14T10:23:45+02:00">', datetime(2026, 11, 14, 8, 23, 45)),
    ('<meta property="article:published_time" content="2026-11-14T10:23:45Z">', datetime(2026, 11, 14, 10, 23, 45)),
    # a time just after local midnight is the previous UTC day: the moment, not the dateline, is stored
    ('<meta property="article:published_time" content="2026-11-14T00:30:00+02:00">', datetime(2026, 11, 13, 22, 30)),
    # a day with no time stays that day at midnight, as before
    ('<meta property="article:published_time" content="2026-11-14">', datetime(2026, 11, 14)),
])
def test_the_stated_time_is_kept(head, expected):
    doc = ex.extract_article(_page(head), url="https://example.com/news/a-story")
    assert doc is not None and doc.published_at == expected
    assert doc.published_at.tzinfo is None


def test_an_article_published_earlier_today_keeps_its_time():
    now = datetime.now(UTC).replace(microsecond=0)
    early = now - timedelta(seconds=1)  # a moment that is past, and later than midnight, today
    if early.date() != now.date() or (early.hour, early.minute, early.second) == (0, 0, 0):
        pytest.skip("the first second of the UTC day: no earlier moment today")
    head = f'<meta property="article:published_time" content="{early.strftime("%Y-%m-%dT%H:%M:%S")}+00:00">'
    doc = ex.extract_article(_page(head), url="https://example.com/news/today")
    assert doc is not None and doc.published_at == early.replace(tzinfo=None)


@pytest.mark.parametrize("hours_ahead", [5, 14])
def test_a_moment_stated_in_a_zone_ahead_of_the_machine_keeps_its_time(hours_ahead):
    # The upper bound is the machine's local end of today (htmldate's clock). A moment a second old,
    # written in a zone far ahead (at +14:00 its own date is often already tomorrow), is past, and kept.
    now = datetime.now(UTC).replace(microsecond=0)
    early = now - timedelta(seconds=1)
    stated = early.astimezone(timezone(timedelta(hours=hours_ahead)))
    head = f'<meta property="article:published_time" content="{stated.isoformat()}">'
    doc = ex.extract_article(_page(head), url="https://example.com/news/ahead")
    assert doc is not None and doc.published_at == early.replace(tzinfo=None), stated.isoformat()


def test_the_two_parse_path_keeps_the_time_too(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("metadata fault")

    monkeypatch.setattr(ex.trafilatura, "bare_extraction", boom)
    doc = ex.extract_article(_page('<meta property="article:published_time" content="2026-11-14T10:23:45+02:00">'),
                             url="https://example.com/news/a-story")
    assert doc is not None and doc.published_at == datetime(2026, 11, 14, 8, 23, 45)


@pytest.mark.parametrize("value,expected", [
    ("2026-11-14T10:23:45+0200", datetime(2026, 11, 14, 8, 23, 45)),
    ("2026-11-14T10:23:45", datetime(2026, 11, 14, 10, 23, 45)),  # no offset: kept as written
    ("2026-11-14", datetime(2026, 11, 14)),
    ("not a date", None),
    (None, None),
])
def test_parse_date_applies_only_a_stated_offset(value, expected):
    assert ex._parse_date(value) == expected


def test_the_extensive_search_flag_still_reaches_htmldate(monkeypatch):
    monkeypatch.setenv("OO_EXTENSIVE_DATE_SEARCH", "1")
    assert ex._date_params()["extensive_search"] is True
    monkeypatch.delenv("OO_EXTENSIVE_DATE_SEARCH")
    params = ex._date_params()
    assert params["extensive_search"] is False and params["outputformat"] == "%Y-%m-%dT%H:%M:%S%z"
    # The END of today, stated rather than left out: trafilatura 2.4.0 merges our dict over its own
    # defaults, so a missing key comes back as today's date (00:00) and today's times are lost.
    end = params["max_date"]
    assert (end.hour, end.minute, end.second) == (23, 59, 59) and end.date() == datetime.now().date()


def test_an_end_day_bound_keeps_that_days_timed_articles():
    from sqlalchemy.orm import Session

    from src.api.search_filters import published_until
    from src.database.models import Article, Base, Source

    engine = app_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        src = Source(name="S", domain="s.example", source_type="news", enabled=True)
        s.add(src)
        s.flush()
        for i, when in enumerate([datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 4, 0, 30)]):
            s.add(Article(url=f"http://x/{i}", canonical_url=f"http://x/{i}", content="c", hash=f"h{i}",
                          source_id=src.id, published_at=when, title="t"))
        s.commit()
        day = [a.published_at for a in s.query(Article).filter(published_until("2026-05-03"))]
        exact = [a.published_at for a in s.query(Article).filter(published_until("2026-05-03T12:00:00"))]
    assert day == [datetime(2026, 5, 3, 14, 0)]  # the whole day, not only its midnight
    assert exact == []  # a timestamp stays an exact bound
