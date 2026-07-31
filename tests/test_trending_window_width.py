"""
Pins the WIDTH of ``trending()``'s recent and baseline windows.

The 2026-07-31 fix: ``w_start`` was ``today - window_days``, so the recent window
spanned ``window_days + 1`` days while ``expected`` normalised the prior rate to
``window_days`` -- inflating every ``growth`` by (N+1)/N, i.e. 2x on the shipped
("24h", 1, 7) preset. It went unnoticed because every existing trending test places
its fixtures comfortably inside the window and asserts only that a term surfaces,
never how wide the window is.

These tests assert the width directly, with one mention per day so a count IS a
day count, and with fixtures placed exactly ON both boundaries.

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
_SPAN_DAYS = 120  # deep enough to cover the widest window + baseline used below


def _seed(tmp_path):
    """One mention of one term on each of the last ``_SPAN_DAYS`` days.

    ``count=1`` per day means a summed ``recent``/``prior`` is exactly the number of
    DAYS the window covered -- which is what makes width directly assertable.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tww.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    with Sess() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        s.add(Keyword(id=_TERM_ID, term="daily", normalized_term="daily", language="en"))
        s.commit()
        # keyword_mentions is UNIQUE on (keyword_id, article_id), so each day needs
        # its own article to carry that day's mention.
        for offset in range(_SPAN_DAYS):
            aid = offset + 1
            s.add(
                Article(
                    url=f"https://x.test/{aid}",
                    canonical_url=f"https://x.test/{aid}",
                    source_id=1,
                    title="t",
                    content="c",
                    hash=f"h{aid}",
                    language="en",
                    created_at=datetime.now(UTC),
                )
            )
            s.commit()
            s.add(
                KeywordMention(
                    keyword_id=_TERM_ID,
                    article_id=aid,
                    count=1,
                    observed_on=today - timedelta(days=offset),
                )
            )
            s.commit()
    return Sess


def _row(sess, **kw):
    out = q.trending(sess, min_recent=1, limit=50, **kw)
    return next(t for t in out["terms"] if t["normalized"] == "daily")


def test_recent_window_is_exactly_window_days_wide(tmp_path):
    """One mention/day => recent == window_days, for several widths.

    Before the fix this returned window_days + 1 for every N.
    """
    Sess = _seed(tmp_path)
    with Sess() as s:
        for n in (1, 3, 7, 30):
            row = _row(s, window_days=n, baseline_days=30)
            assert row["recent"] == n, f"window_days={n} covered {row['recent']} days, expected {n}"


def test_baseline_window_is_exactly_baseline_days_wide(tmp_path):
    """One mention/day => prior == baseline_days, and it abuts the recent window."""
    Sess = _seed(tmp_path)
    with Sess() as s:
        for n, b in ((1, 7), (7, 30), (30, 60)):
            row = _row(s, window_days=n, baseline_days=b)
            assert row["prior"] == b, f"baseline_days={b} covered {row['prior']} days, expected {b}"
            # abutting, not overlapping: the two windows together cover n + b days.
            assert row["recent"] + row["prior"] == n + b


def test_windows_do_not_overlap_or_gap_at_the_boundary(tmp_path):
    """A mention exactly ON each boundary lands in exactly one window.

    With window_days=7 the recent window is [today-6, today] and the baseline is
    [today-36, today-7]. So today-6 is the oldest RECENT day and today-7 is the
    newest PRIOR day; neither is double-counted nor dropped.
    """
    Sess = _seed(tmp_path)
    with Sess() as s:
        row = _row(s, window_days=7, baseline_days=30)
    # 7 recent days and 30 prior days, from a corpus with one mention every day:
    # any overlap would exceed these, any gap would fall short.
    assert row["recent"] == 7
    assert row["prior"] == 30


def test_growth_is_not_inflated_on_a_perfectly_flat_series(tmp_path):
    """A flat series must read growth ~1.0 -- the property the old width broke.

    Constant volume every day means the recent rate equals the prior rate, so
    expected == recent and growth == 1.0. The old N+1-wide recent window made this
    report 2.0 on the 24h preset: a flat corpus looked like it had doubled.
    """
    Sess = _seed(tmp_path)
    with Sess() as s:
        for n, b in ((1, 7), (7, 30), (30, 60)):
            row = _row(s, window_days=n, baseline_days=b)
            assert row["expected"] == float(n), f"expected {n} for a flat series, got {row}"
            assert row["growth"] == 1.0, f"flat series reported growth {row['growth']} at n={n}"
