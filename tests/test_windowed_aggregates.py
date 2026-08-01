"""
Explicit period windows on top_terms / trending / trending_windows.

Until 2026-08-01 all three anchored their window to ``date.today()`` with no upper
bound, so a CLOSED period could not be asked about at all and the same question
re-asked tomorrow returned a different answer. ``end`` (an EXCLUSIVE upper bound)
makes a result reproducible.

Two properties matter and are both pinned here:

  1. with ``end=None`` every caller sees BYTE-IDENTICAL results to before, because
     the entire shipped surface (Home, Insights, the producers) passes no window;
  2. with ``end`` set the window is EXACTLY [end - N, end), half-open, so
     consecutive periods tile with no gap and no double-counted boundary day.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_TERM_ID = 1
_SPAN = 200


def _seed(tmp_path):
    """One mention per day for the last _SPAN days, count=1.

    A summed count is therefore exactly a DAY COUNT, which is what lets these tests
    assert window width rather than merely that a term surfaced.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'win.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    with Sess() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        s.add(Keyword(id=_TERM_ID, term="daily", normalized_term="daily", language="en"))
        s.commit()
        for offset in range(_SPAN):
            aid = offset + 1
            s.add(Article(
                url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
                source_id=1, title="t", content="c", hash=f"h{aid}", language="en",
                created_at=datetime.now(UTC),
            ))
            s.commit()
            s.add(KeywordMention(
                keyword_id=_TERM_ID, article_id=aid, count=1,
                observed_on=today - timedelta(days=offset),
            ))
            s.commit()
    return Sess


def _trend_row(sess, **kw):
    out = q.trending(sess, min_recent=1, limit=50, **kw)
    return next(t for t in out["terms"] if t["normalized"] == "daily")


# -- property 1: the default path is unchanged ------------------------------ #


def test_trending_default_is_byte_identical_to_passing_end_of_today(tmp_path):
    """end=None must mean exactly 'the window ending after today'.

    If these two ever diverge, every shipped caller silently changed.
    """
    Sess = _seed(tmp_path)
    tomorrow = date.today() + timedelta(days=1)
    with Sess() as s:
        for n, b in ((1, 7), (7, 30), (30, 90)):
            default = q.trending(s, window_days=n, baseline_days=b, min_recent=1, limit=50)
            explicit = q.trending(
                s, window_days=n, baseline_days=b, min_recent=1, limit=50, end=tomorrow
            )
            assert default["terms"] == explicit["terms"], f"diverged at window_days={n}"


def test_top_terms_default_window_is_unchanged(tmp_path):
    """The legacy inclusive-of-today width is deliberately preserved.

    top_terms is an ordering with no rate, so its extra day costs no correctness --
    unlike trending, where the same extra day inflated a published ratio. Narrowing
    it would silently change what Home and Insights list, so it is left alone.
    """
    Sess = _seed(tmp_path)
    with Sess() as s:
        row = next(t for t in q.top_terms(s, days=7, limit=50)["terms"]
                   if t["normalized"] == "daily")
    assert row["mentions"] == 8  # [today-7 .. today] inclusive == 8 calendar days


# -- property 2: an explicit window is exact and half-open ------------------- #


def test_explicit_window_is_exactly_n_days(tmp_path):
    Sess = _seed(tmp_path)
    tomorrow = date.today() + timedelta(days=1)
    with Sess() as s:
        for n in (1, 3, 7, 30):
            row = _trend_row(s, window_days=n, baseline_days=30, end=tomorrow)
            assert row["recent"] == n, f"window_days={n} covered {row['recent']} days"


def test_top_terms_explicit_window_is_exactly_days_wide(tmp_path):
    """The explicit path is exact even though the legacy path is a day generous."""
    Sess = _seed(tmp_path)
    tomorrow = date.today() + timedelta(days=1)
    with Sess() as s:
        row = next(t for t in q.top_terms(s, days=7, limit=50, end=tomorrow)["terms"]
                   if t["normalized"] == "daily")
    assert row["mentions"] == 7


def test_a_closed_past_period_is_answerable_and_reproducible(tmp_path):
    """The whole point: ask about a week that has already ended, twice, and agree."""
    Sess = _seed(tmp_path)
    week_end = date.today() - timedelta(days=20)  # a closed period, well in the past
    with Sess() as s:
        a = _trend_row(s, window_days=7, baseline_days=30, end=week_end)
        b = _trend_row(s, window_days=7, baseline_days=30, end=week_end)
    assert a["recent"] == 7
    assert a == b, "the same closed period must answer identically"


def test_consecutive_periods_tile_with_no_gap_and_no_overlap(tmp_path):
    """Two adjacent weeks cover 14 distinct days between them.

    An inclusive upper bound would double-count the boundary day (15); a gap would
    fall short (13). This is why the window is half-open.
    """
    Sess = _seed(tmp_path)
    later_end = date.today() - timedelta(days=10)
    earlier_end = later_end - timedelta(days=7)
    with Sess() as s:
        later = _trend_row(s, window_days=7, baseline_days=30, end=later_end)
        earlier = _trend_row(s, window_days=7, baseline_days=30, end=earlier_end)
    assert later["recent"] + earlier["recent"] == 14


def test_baseline_abuts_the_window_and_does_not_overlap_it(tmp_path):
    Sess = _seed(tmp_path)
    end = date.today() - timedelta(days=5)
    with Sess() as s:
        row = _trend_row(s, window_days=7, baseline_days=30, end=end)
    assert row["recent"] == 7
    assert row["prior"] == 30
    assert row["recent"] + row["prior"] == 37  # contiguous, counted once each


def test_a_flat_series_reads_growth_one_in_a_closed_period(tmp_path):
    """Constant volume => recent rate == prior rate => growth 1.0, at any anchor."""
    Sess = _seed(tmp_path)
    with Sess() as s:
        for offset in (0, 12, 40):
            end = date.today() + timedelta(days=1) - timedelta(days=offset)
            row = _trend_row(s, window_days=7, baseline_days=30, end=end)
            assert row["growth"] == 1.0, f"anchor -{offset}d reported {row['growth']}"


# -- trending_windows passes both through ------------------------------------ #


def test_trending_windows_threads_end_through_every_preset(tmp_path):
    Sess = _seed(tmp_path)
    end = date.today() - timedelta(days=15)
    with Sess() as s:
        out = q.trending_windows(s, limit=20, end=end)
    by_label = {w["label"]: w for w in out["windows"]}
    assert set(by_label) == {"24h", "7d", "30d"}
    for label, expected in (("24h", 1), ("7d", 7), ("30d", 30)):
        row = next(t for t in by_label[label]["terms"] if t["normalized"] == "daily")
        assert row["recent"] == expected, f"{label} covered {row['recent']} days"


def test_trending_windows_accepts_other_cadences(tmp_path):
    """A periodic document needs cadences the shipped preset table does not carry."""
    Sess = _seed(tmp_path)
    end = date.today() + timedelta(days=1)
    with Sess() as s:
        out = q.trending_windows(
            s, limit=20, end=end,
            window_presets=(("weekly", 7, 30), ("monthly", 30, 90)),
        )
    assert [w["label"] for w in out["windows"]] == ["weekly", "monthly"]
    for label, expected in (("weekly", 7), ("monthly", 30)):
        w = next(x for x in out["windows"] if x["label"] == label)
        row = next(t for t in w["terms"] if t["normalized"] == "daily")
        assert row["recent"] == expected


def test_trending_windows_default_presets_are_unchanged(tmp_path):
    Sess = _seed(tmp_path)
    with Sess() as s:
        out = q.trending_windows(s, limit=20)
    assert [(w["label"], w["window_days"], w["baseline_days"]) for w in out["windows"]] == [
        ("24h", 1, 7), ("7d", 7, 30), ("30d", 30, 90)
    ]
