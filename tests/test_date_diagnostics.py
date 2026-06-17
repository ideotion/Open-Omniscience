"""Tests for the date-extraction diagnostics tool (the maintainer↔dev channel).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.timemap import datediag

TODAY = date(2026, 6, 9)


# ----------------------------- pure core --------------------------------- #


def test_recall_probe_finds_the_kinds_and_dedups_overlaps():
    probe = datediag.recall_probe(
        "On 11/06/2026 and in 1945, the réunion was hier; 2026年9月15日 on Tuesday."
    )
    kinds = {h["kind"] for h in probe}
    assert {"numeric", "bare_year", "relative", "cjk_date", "weekday"} <= kinds
    # the 2026 inside 11/06/2026 must NOT also be reported as a bare year
    years = [h for h in probe if h["kind"] == "bare_year"]
    assert {h["match"] for h in years} == {"1945"}


def test_recall_probe_empty_and_ordering():
    assert datediag.recall_probe("") == []
    probe = datediag.recall_probe("First 1999 then March 2020.")
    # ordered by position in the text
    assert [h["match"] for h in probe][:1] == ["1999"]


def test_analyze_article_pairs_extractor_with_probe():
    # An explicit date the extractor catches, plus a bare year it skips by design.
    a = datediag.analyze_article(
        "The treaty of 11 September 2001; see also 1648.", language="en", today=TODAY
    )
    assert any(c["date"] == "2001-09-11" for c in a["extracted"])
    assert a["probe_by_kind"].get("bare_year", 0) >= 1
    # bare years are NOT actionable, so a single explicit date leaves no gap
    assert a["actionable_gap"] == 0


def test_analyze_article_surfaces_a_real_miss():
    # Valid CJK 年月日 dates now extract; an INVALID one (month 13) is still date-like
    # text the extractor (correctly) does not extract -> a real probe/extractor gap the
    # diagnostics surface.
    a = datediag.analyze_article("会议将于 2025年13月 举行。", language="zh", today=TODAY)
    assert a["n_extracted"] == 0
    assert a["probe_by_kind"].get("cjk_date", 0) == 1
    assert a["actionable_gap"] == 1


def test_base_language():
    assert datediag.base_language("en-US") == "en"
    assert datediag.base_language("FR") == "fr"
    assert datediag.base_language(None) == "?"


# ----------------------------- the endpoint ------------------------------ #


def _client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dd.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add_all(
            [
                Article(  # explicit date -> extracted
                    url="https://wire.test/1", canonical_url="https://wire.test/1", source_id=1,
                    title="Explicit", hash="h1", language="en",
                    content="The attacks of 11 September 2001 still echo.",
                    published_at=datetime(2024, 6, 1, tzinfo=UTC), created_at=datetime.now(UTC),
                ),
                Article(  # an INVALID CJK date (month 13): date-like but not extracted -> a real miss
                    url="https://wire.test/2", canonical_url="https://wire.test/2", source_id=1,
                    title="CJK", hash="h2", language="zh",
                    content="会议将于 2025年13月 在北京举行。",
                    published_at=datetime(2024, 6, 2, tzinfo=UTC), created_at=datetime.now(UTC),
                ),
                Article(  # only bare years -> date-like but nothing extracted
                    url="https://wire.test/3", canonical_url="https://wire.test/3", source_id=1,
                    title="Bare years", hash="h3", language="en",
                    content="The treaty of 1648 reshaped Europe; revisited in 2020.",
                    published_at=datetime(2024, 6, 3, tzinfo=UTC), created_at=datetime.now(UTC),
                ),
            ]
        )
        s.commit()

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


def test_date_diagnostics_endpoint(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/dates")
            assert r.status_code == 200, r.text
            data = r.json()["data"]
            corpus = data["corpus"]
            assert corpus["scanned"] == 3
            assert corpus["articles_with_extracted_dates"] == 1  # only the explicit one
            assert corpus["articles_with_datelike_text_but_no_extraction"] == 2  # cjk + bare years
            # the vocabulary-gap signal: zh has no month table, en does
            assert data["per_language"]["zh"]["in_month_vocab"] is False
            assert data["per_language"]["en"]["in_month_vocab"] is True
            # the probe surfaced both a bare year and a CJK date corpus-wide
            assert data["date_like_text_by_kind"].get("cjk_date", 0) >= 1
            assert data["date_like_text_by_kind"].get("bare_year", 0) >= 1
            # sample is worst-actionable-miss first -> the CJK article tops it
            assert data["sample"][0]["title"] == "CJK"
            assert data["sample"][0]["actionable_gap"] >= 1
            # every sampled record carries both sides + what is actually stored
            row = data["sample"][0]
            assert "extracted" in row and "date_like_in_text" in row and "stored_tags" in row
            assert row["content_excerpt"]
    finally:
        app.dependency_overrides.clear()


def test_date_diagnostics_carries_no_scores(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            blob = json.dumps(client.get("/api/diagnostics/dates").json())
            assert "_score" not in blob and '"score"' not in blob
    finally:
        app.dependency_overrides.clear()
