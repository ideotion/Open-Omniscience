"""Row 459 (R853): each article chart says how many of ITS articles have no date of their own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R853's conditions, each pinned here:

1. ``n`` and ``feed_dated`` are counted over exactly what the chart shows: the same keyword, window, country and
   quarantine/screening slice, never a corpus-wide figure under a filtered chart.
2. ``n`` that cannot be computed reads "not counted" (``n`` None), never 0 and never silence; ``n`` = 0 draws nothing.
3. The kind decides the words: "drawn at the day the app collected them" (keyword-index charts) or "left out" (charts
   and figures read off ``published_at``).
4. A trending card whose sparkline includes collection-dated articles carries the mark.
6. Nothing plotted changes: a caller that does not ask for the block gets the payload it had.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics import undated as u
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, Source
from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
_BODY = (
    "Flooding displaced thousands across the northern delta region. "
    "Officials said the flooding would continue. "
) * 6


@pytest.fixture()
def db():
    eng = app_sqlite_engine(":memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


def _seed(db):
    """Five articles on one keyword: dated; undated; undated with a feed date; undated but quarantined; and one
    undated article collected on a later day (another bucket)."""
    src = Source(name="d.example", domain="d.example")
    db.add(src)
    db.flush()

    def art(key, **kw):
        a = Article(source_id=src.id, url=f"https://d.example/{key}", canonical_url=f"https://d.example/{key}",
                    title=f"Delta flooding {key}", content=_BODY + key, hash=f"h-{key}", **kw)
        db.add(a)
        return a

    arts = {
        "dated": art("dated", published_at=DAY, created_at=DAY),
        "undated": art("undated", published_at=None, created_at=DAY),
        "feed": art("feed", published_at=None, created_at=DAY, feed_entry_published_at=datetime(2026, 6, 14, 22, 0)),
        "quarantined": art("quarantined", published_at=None, created_at=DAY, quarantined=True),
        "later": art("later", published_at=None, created_at=LATER),
    }
    db.flush()
    for a in arts.values():
        index_article(db, a, extractor=BaselineExtractor())
    db.commit()
    return arts


def _term(db) -> str:
    kw = db.execute(select(Keyword).where(Keyword.normalized_term.like("%flood%"))).scalars().first()
    assert kw is not None
    return kw.normalized_term


def test_trend_counts_its_own_undated_articles_with_the_feed_split_and_per_bucket(db):
    _seed(db)
    out = q.trend(db, _term(db), bucket="week", undated=True)
    b = out["undated"]
    assert b["kind"] == u.KIND_COLLECTION
    # undated + feed + later; the quarantined one is not in the chart's points, so it is not counted either.
    assert b["n"] == 3 and b["feed_dated"] == 1 and b["feed_dated_reason"] is None
    weeks = {x["date"]: (x["n"], x["feed_dated"]) for x in b["by_bucket"]}
    assert weeks == {DAY.date().strftime("%G-W%V"): (2, 1), LATER.date().strftime("%G-W%V"): (1, 0)}
    # every bucket of the split is a bucket the chart draws
    assert set(weeks) <= {p["date"] for p in out["points"]}


def test_a_caller_that_does_not_ask_keeps_the_payload_it_had(db):
    _seed(db)
    assert "undated" not in q.trend(db, _term(db), bucket="week")


def test_the_country_filter_applies_to_the_count_as_to_the_points(db):
    _seed(db)
    out = q.trend(db, _term(db), bucket="week", country="zz", undated=True)
    assert out["points"] == [] and out["undated"]["n"] == 0


def test_over_the_cap_the_feed_split_is_not_counted_and_n_still_is(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(u, "FEED_COUNT_CAP", 1)
    b = q.trend(db, _term(db), bucket="week", undated=True)["undated"]
    assert b["n"] == 3 and b["feed_dated"] is None and b["feed_dated_reason"] == "over_cap"
    assert "by_bucket" not in b


def test_a_count_that_cannot_be_taken_is_not_counted_never_zero(db):
    _seed(db)
    broken = select(text("no_such_column FROM no_such_table"))
    for b in (u.undated_in_select(db, broken, kind=u.KIND_LEFT_OUT),
              u.undated_by_bucket(db, select(text("a, b FROM no_such_table")), kind=u.KIND_COLLECTION,
                                  bucket_key=str)):
        assert b["n"] is None and b["feed_dated"] is None and b["feed_dated_reason"] == "not_counted"


def test_the_conjunction_trend_counts_the_set_it_draws(db):
    from src.analytics.conjunction import conditional_trend

    arts = _seed(db)
    ids = [a.id for a in arts.values()]
    out = conditional_trend(db, ids, bucket="week", undated=True)
    assert out["undated"]["n"] == 3 and out["undated"]["feed_dated"] == 1
    assert "undated" not in conditional_trend(db, ids, bucket="week")
    only_dated = conditional_trend(db, [arts["dated"].id], bucket="week", undated=True)
    assert only_dated["undated"]["n"] == 0


def test_a_trending_card_counts_its_own_sparkline_window(db):
    _seed(db)
    term = _term(db)
    june = {"windows": [{"series_window": {"start": "2026-06-10", "end": "2026-06-20"},
                         "terms": [{"normalized": term, "series": []}, {"normalized": term}]}]}
    q.annotate_trending_undated(db, june)
    carded, plain = june["windows"][0]["terms"]
    assert carded["undated"]["n"] == 2 and carded["undated"]["feed_dated"] == 1
    assert "undated" not in plain  # a term without a sparkline draws no chart
    autumn = {"windows": [{"series_window": {"start": "2026-09-01", "end": "2026-09-05"},
                           "terms": [{"normalized": term, "series": []}]}]}
    q.annotate_trending_undated(db, autumn)
    assert autumn["windows"][0]["terms"][0]["undated"]["n"] == 1
    empty = {"windows": [{"series_window": {"start": "2025-01-01", "end": "2025-01-05"},
                          "terms": [{"normalized": term, "series": []}]}]}
    q.annotate_trending_undated(db, empty)
    assert empty["windows"][0]["terms"][0]["undated"]["n"] == 0


def test_a_trending_ring_card_counts_an_article_once_across_its_forms(db):
    _seed(db)
    term = _term(db)
    ring = {"windows": [{"series_window": {"start": "2026-06-10", "end": "2026-06-20"},
                         "terms": [{"ring_id": "r1", "members": [{"normalized": term}, {"normalized": term}],
                                    "series": []}]}]}
    q.annotate_trending_undated(db, ring)
    assert ring["windows"][0]["terms"][0]["undated"]["n"] == 2


def test_the_left_out_figures_count_under_their_own_filters(db):
    from src.api.monitoring import corpus_anomalies

    _seed(db)
    # the anomalies read every article (no quarantine filter), so the count does too
    b = corpus_anomalies(z_threshold=2.0, db=db)["undated"]
    assert b["kind"] == u.KIND_LEFT_OUT_FIGURE and b["n"] == 4 and b["feed_dated"] == 1
    # the whole-corpus correlation leaves quarantined and unscreened articles out, so the count does too
    from src.analytics.quarantine_scope import not_counted

    c = u.undated_in_select(db, select(Article.id).where(not_counted(Article.id)), kind=u.KIND_LEFT_OUT_FIGURE)
    assert c["n"] == 3


def test_the_undated_test_is_answered_from_the_publication_date_index(db):
    """``published_at`` sits after ``content`` in the record, so a row read would walk the content's overflow pages
    (the recorded codec trap); the undated set must come from ``idx_article_published_at`` alone."""
    sql = str(u.undated_ids_select().compile(compile_kwargs={"literal_binds": True}))
    plan = " ".join(str(r[-1]) for r in db.execute(text("EXPLAIN QUERY PLAN " + sql)))
    assert "idx_article_published_at" in plan and "COVERING INDEX" in plan, plan


# --- the page ---------------------------------------------------------------------------------------------------

_KEYS = [
    "Articles without a date of their own: {n}, drawn at the day the app collected them; with the feed's date: {m}",
    "Articles without a date of their own: {n}, drawn at the day the app collected them; feed dates not counted",
    "Articles without a date of their own: {n}, left out of this chart; with the feed's date: {m}",
    "Articles without a date of their own: {n}, left out of this chart; feed dates not counted",
    "Articles without a date of their own: {n}, left out of this figure; with the feed's date: {m}",
    "Articles without a date of their own: {n}, left out of this figure; feed dates not counted",
    "Articles without a date of their own: not counted",
    "◷ {n} by collection date",
    "◷ dates not counted",
]


def test_every_string_is_keyed_in_all_twelve_locales_with_its_placeholders():
    files = sorted((ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(files) == 12
    methods = [m for m in u.METHOD.values()]
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for key in _KEYS + methods:
            assert data.get(key), (f.name, key)
            assert f.stem == "en" or data[key] != key, (f.name, key)
            for ph in ("{n}", "{m}"):
                assert (ph in key) == (ph in data[key]), (f.name, key)


def test_the_page_methods_are_the_server_methods():
    core = (ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    for m in u.METHOD.values():
        assert f't("{m}")' in core


# Every surface R853 names draws the helper beside its chart.
_SURFACES = [
    ("app-corpus.js", r"ooUndatedLine\(tr\.undated"),  # Insights keyword trend, by the range drawn
    ("app-corpus.js", r"ooUndatedLine\(\(h\.last\.trend \|\| \{\}\)\.undated\)"),  # corpus algebra trend
    ("app-corpus.js", r"\$\{ooUndatedMark\(x\.undated\)\}"),  # Insights trending cards
    ("app-corpus.js", r"ooUndatedText\(x\.undated\)"),  # their enlarged chart
    ("app-home.js", r"\$\{ooUndatedMark\(x\.undated\)\}"),  # Home trending cards
    ("app-home.js", r"ooUndatedText\(x\.undated\)"),  # their enlarged chart
    ("app-analysis.js", r"_anTrendUndated\(\$\(\"an-trend-chart\"\), counts\)"),  # the analysis trend
    ("app-markets.js", r"ooUndatedLine\(d\.undated\)"),  # the price correlation
]


@pytest.mark.parametrize(("name", "pattern"), _SURFACES)
def test_each_surface_draws_the_line(name, pattern):
    src = (ROOT / "src" / "static" / name).read_text(encoding="utf-8")
    assert re.search(pattern, src), (name, pattern)


def test_the_endpoints_ask_for_the_block():
    ins = (ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert "undated=True" in ins and "conditional_trend(db, ids, bucket=bucket, undated=True)" in ins
    assert "q.annotate_trending_undated(db, rm.trending_windows(" in ins
    assert '"undated"' in (ROOT / "src" / "api" / "commodity.py").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_helpers_run_as_real_code():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "undated_counts_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

