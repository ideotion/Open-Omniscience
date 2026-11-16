"""The publication TIME survives extraction (field report 2026-11-14 section 5.5, open-on-main row 66).

htmldate's default output is the day, so every structured time the page stated was cut to midnight: ~94% of
stored publication times read T00:00:00. Extraction now asks for the time and the offset. A stated offset is
applied (the store keeps naive UTC, like ``created_at``); a page that states only a day keeps that day at
midnight, exactly as before, so nothing is invented.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.ingest import extract as ex

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
