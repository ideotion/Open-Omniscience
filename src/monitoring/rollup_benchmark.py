"""Live-vs-rollup benchmark for the windowed keyword aggregations (scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The freeze this whole workstream targets: the WINDOWED keyword aggregations (Insights
trends, Home trending) sum ``keyword_mentions.count`` over an ``observed_on`` day range —
a scan of the multi-GB mentions table, each in-range row a SQLCipher page decrypt. This
tool BUILDS the ``keyword_daily`` rollup in-memory over the operator's REAL corpus and
times the same windowed aggregation both ways — the live mention scan vs summing the tiny
rollup — reporting the speedup AND a parity check, so the operator can see, on their own
data, exactly how much the rollup helps (and that it's faithful) before any of it is wired
into the hot path or the persisted store (D1) is bundled.

Honesty / safety (the diagnostics-channel contract): READ-ONLY, bounded, airplane-safe,
generated on click only, never transmitted. The one-time build cost is reported alongside
the per-query win so the amortization is honest (the rollup pays a build once, then each
windowed query is cheap). ``mentions`` counts are exact; the distinct-article count is the
disclosed upper bound (equal today under the unique (keyword_id, article_id) index).
Counts + milliseconds only, never a score.
"""

from __future__ import annotations

import statistics
import time
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Day windows to compare (None = all history). These mirror what the UI actually asks for:
# the 7d/30d trending windows plus a wider lens.
_WINDOWS = (7, 30, 90, None)


def _median_ms(fn, repeats: int) -> tuple[float, float, int | None]:
    """Run ``fn`` ``repeats`` times; return (cold_ms, warm_median_ms, result_size)."""
    runs: list[float] = []
    size: int | None = None
    for i in range(repeats):
        t0 = time.perf_counter()
        out = fn()
        runs.append((time.perf_counter() - t0) * 1000.0)
        if i == 0:
            size = len(out) if hasattr(out, "__len__") else None
    warm = runs[1:] or runs
    return round(runs[0], 1), round(statistics.median(warm), 1), size


def _live_windowed(session: Session, start):
    """The live windowed per-keyword aggregation — the freeze source (SUM(count),
    COUNT(DISTINCT article_id) grouped over the mention scan). Same shape the rollup serves."""
    clause = "observed_on IS NOT NULL"
    params: dict = {}
    if start is not None:
        clause += " AND observed_on >= :s"
        params["s"] = start
    return session.execute(text(
        "SELECT keyword_id, SUM(count), COUNT(DISTINCT article_id) FROM keyword_mentions "
        "WHERE " + clause + " GROUP BY keyword_id"  # nosec B608 - clause is a constant fragment; the value is a bound :param
    ), params).fetchall()


def run_rollup_benchmark(session: Session, *, repeats: int = 3) -> dict:
    """Build the rollup in-memory over the live corpus and compare windowed timings.

    Returns a self-describing payload: corpus context, the one-time build cost, a parity
    check, and per-window live-vs-rollup timings with the speedup. Falls back honestly if
    duckdb is unavailable.
    """
    from src.analytics import columnar

    repeats = max(1, min(int(repeats), 10))
    if not columnar.duckdb_available():
        return {"available": False,
                "reason": "duckdb not installed (the optional [columnar] extra)"}

    # -- corpus context (so the numbers are interpretable) ------------------------------- #
    from src.database.models import Article, Keyword

    from sqlalchemy import func

    corpus = {
        "articles": int(session.query(func.count(Article.id)).scalar() or 0),
        "keywords": int(session.query(func.count(Keyword.id)).scalar() or 0),
        "keyword_mentions": int(
            session.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() or 0
        ),
    }

    # -- the one-time build (this is the amortized cost) --------------------------------- #
    con = columnar.connect(passphrase=None)  # offline -> in-memory (never a plaintext file)
    if con is None:
        return {"available": False, "reason": "columnar engine unavailable"}
    t0 = time.perf_counter()
    build = columnar.build_keyword_daily(con, session)
    build_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    # -- parity: is the rollup faithful on THIS corpus? ---------------------------------- #
    parity = columnar.keyword_daily_parity(con, session)

    # -- per-window: live mention scan vs rollup sum ------------------------------------- #
    today = date.today()
    windows = []
    for w in _WINDOWS:
        start = (today - timedelta(days=w)) if w else None
        live_cold, live_med, live_n = _median_ms(lambda s=start: _live_windowed(session, s), repeats)
        roll_cold, roll_med, roll_n = _median_ms(
            lambda s=start: columnar.windowed_term_counts(con, start_day=s), repeats
        )
        speedup = round(live_med / roll_med, 1) if roll_med > 0 else None
        windows.append({
            "window_days": w,
            "live_median_ms": live_med,
            "rollup_median_ms": roll_med,
            "speedup_x": speedup,
            "live_cold_ms": live_cold,
            "rollup_cold_ms": roll_cold,
            "keywords_live": live_n,
            "keywords_rollup": roll_n,
            "counts_match": live_n == roll_n,
        })

    try:
        con.close()
    except Exception:  # noqa: BLE001
        pass

    return {
        "available": True,
        "repeats": repeats,
        "corpus": corpus,
        "build": {
            "build_ms": build_ms,
            "keyword_daily_rows": build.get("keyword_daily_rows"),
            "streamed_mentions": build.get("streamed_mentions"),
            "note": (
                "One-time cost: streams the mention rows out of the encrypted store once and "
                "groups them per day in DuckDB. In a running app this is paid once in the "
                "background, then every windowed query is served from the rollup."
            ),
        },
        "parity": parity,
        "windows": windows,
        "method": (
            "For each window: live = the windowed per-keyword aggregation over "
            "keyword_mentions (SUM(count), COUNT(DISTINCT article_id)) — the scan that "
            "freezes; rollup = summing the maintained keyword_daily rollup for the same "
            "window. Each timed 'repeats' times (run 1 cold, the rest warm-median). "
            "speedup_x = live_median / rollup_median. counts_match confirms both cover the "
            "same keywords. In-memory DuckDB; the persisted-store durability is a separate "
            "packaging step (D1), but the per-query speedup shown here is real in a "
            "long-running process."
        ),
        "caveat": (
            "In-session warm-path numbers on your real corpus; timings vary with load and a "
            "concurrent scrape. mentions counts are exact; the distinct-article count is the "
            "disclosed upper bound (equal today under the unique keyword+article index — see "
            "parity.distinct_gap_total). Read-only; nothing is transmitted. Counts and "
            "milliseconds only, never a score."
        ),
    }
