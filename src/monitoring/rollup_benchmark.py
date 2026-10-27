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

import contextlib
import statistics
import time
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Day windows to compare (None = all history). These mirror what the UI actually asks for:
# the 7d/30d trending windows plus a wider lens.
_WINDOWS = (7, 30, 90, None)

#: "No bound": the live side counts every row (the pre-2026-10-16 behaviour, kept for a caller on a quiet corpus).
_UNBOUNDED = object()


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


def _live_windowed(session: Session, start, *, scan_bound=_UNBOUNDED):
    """The live windowed per-keyword aggregation — the freeze source (SUM(count),
    COUNT(DISTINCT article_id) grouped over the mention scan). Same shape the rollup serves.

    ``scan_bound``: the boundary the rollup build stopped at (``build_keyword_daily`` returns it). The build
    leaves out every row committed after it, on purpose, so a live side that keeps counting them on a corpus
    the scrape is still writing to differs from the rollup by exactly the new rows; bounded, it compares like
    with like (the 2026-10-16 run: 8,814 "mismatches", every one a row newer than the build)."""
    clause = "observed_on IS NOT NULL"
    params: dict = {}
    if scan_bound is not _UNBOUNDED:
        from src.analytics.columnar import live_bound_clause

        bound_sql, bound_params = live_bound_clause(scan_bound)
        clause += " AND " + bound_sql
        params.update(bound_params)
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

    DECLINES (``declined: true``, the verdict's ``reason`` and ``source``, nothing built) when a start-time guard of the served rollup build
    refuses it -- an import's exclusive window, the boot warm-up, the memory guard, a stop or failure hold, a killed earlier build, an unaffordable
    start -- or when a rollup build is already running. The benchmark builds the same whole-corpus in-memory rollup the serve does (R278, #1310).
    The per-batch memory-guard poll inside the build is the serve's alone; the DuckDB limit of the budget bounds this build.
    """
    from src.analytics import columnar

    repeats = max(1, min(int(repeats), 10))
    if not columnar.duckdb_available():
        return {"available": False,
                "reason": "duckdb not installed (the optional [columnar] extra)"}

    # -- the same start-time guards the served build meets (R278, #1310) ---------------------------------------- #
    # This builds the whole-corpus rollup in memory, the build that crashed the app in #1310; it met no verdict. Now it meets the ones the serve's
    # build meets, judged as the in-memory build it is, and it holds the build lock so a served build cannot run beside it.
    from src.analytics import rollup_serve

    with rollup_serve.benchmark_slot() as held:
        if not held:
            return {"available": False, "declined": True, "reason": "build-running", "source": "build-lock",
                    "note": "A rollup build is running; the benchmark builds one too and never runs beside it. Try again when it has finished."}
        return _run_guarded(session, repeats, columnar)


def _run_guarded(session: Session, repeats: int, columnar) -> dict:
    from src.analytics import rollup_marker, rollup_serve

    with rollup_serve.inmemory_view():
        skip, source = rollup_serve.first_start_decline()
    if skip:
        # Declined, not failed: nothing was built. The record is the verdict's own (its reason, readings and detail), with the verdict named.
        return {"available": False, "declined": True, "reason": skip.get("reason") or "declined", "source": source, "detail": skip,
                "note": "Not run: the same check that stops the served rollup build refused it. Nothing was built."}
    # The in-progress marker, as the served build writes it: a benchmark that is killed (the #1310 end) leaves the record the next start's
    # last-build verdict reads, and another server's served build sees a benchmark running. ``begin`` refuses when another process's build runs.
    r = rollup_serve._readings()
    snap = columnar.budget_snapshot()  # read ONCE: the marker, the connection and the build live on this reading (R147)
    if not rollup_marker.begin(rss_mb=r["rss_mb"], avail_mb=r["avail_mb"], limit_mb=snap["duckdb_limit_mb"]):
        return {"available": False, "declined": True, "reason": rollup_marker.ELSEWHERE, "source": "last-build",
                "note": "Not run: another server's rollup build is running. Nothing was built."}
    try:
        return _run_built(session, repeats, columnar, snap)
    finally:
        rollup_marker.clear()  # ended by a path Python saw: a marker left behind means a kill


def _marker_progress(stage: str, rows_done: int) -> None:
    """The build's per-batch hook for a benchmark: keep the marker's stage and peak current. It is NOT the memory-guard poll (the serve's alone, R280)."""
    from src.analytics import rollup_marker, rollup_serve

    r = rollup_serve._readings()
    rollup_marker.progress(stage, rows_done, rss_mb=r["rss_mb"], avail_mb=r["avail_mb"])


def _run_built(session: Session, repeats: int, columnar, snap: dict) -> dict:
    from src.analytics import rollup_serve

    # -- corpus context (so the numbers are interpretable) ------------------------------- #
    from sqlalchemy import func

    from src.database.models import Article, Keyword

    corpus = {
        "articles": int(session.query(func.count(Article.id)).scalar() or 0),
        "keywords": int(session.query(func.count(Keyword.id)).scalar() or 0),
        "keyword_mentions": int(
            session.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() or 0
        ),
    }

    # -- the one-time build (this is the amortized cost) --------------------------------- #
    # The offload folder is the serve's rule (none for an encrypted corpus; a folder of this connection's own otherwise): left to DuckDB's default it
    # would write derived data beside the working directory in the clear once the build reached its limit.
    spill = rollup_serve._spill_setting()
    try:
        con = columnar.connect(passphrase=None, spill=spill, snapshot=snap)  # offline -> in-memory (never a plaintext file)
    except BaseException:
        rollup_serve._remove_spill(spill)
        raise
    if con is None:
        rollup_serve._remove_spill(spill)
        return {"available": False, "reason": "columnar engine unavailable"}
    try:
        return _measure(session, repeats, columnar, snap, con, corpus)
    finally:
        with contextlib.suppress(Exception):
            con.close()
        rollup_serve._remove_spill(spill)  # after the close: DuckDB holds its files open until then


def _measure(session: Session, repeats: int, columnar, snap: dict, con, corpus: dict) -> dict:
    t0 = time.perf_counter()
    build = columnar.build_keyword_daily(con, session, on_batch=_marker_progress, snapshot=snap)
    build_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    # -- parity: is the rollup faithful on THIS corpus? ---------------------------------- #
    scan_bound = build.get("scan_bound")
    parity = columnar.keyword_daily_parity(con, session, scan_bound=scan_bound)

    # -- per-window: live mention scan vs rollup sum ------------------------------------- #
    today = date.today()
    windows = []
    for w in _WINDOWS:
        start = (today - timedelta(days=w)) if w else None
        # TIMED on the shape the app serves (no bound predicate: with ix_mention_created_id present the extra clause can
        # change the plan, and a speedup measured against a different query is not the speedup a user gets) ...
        live_cold, live_med, _ = _median_ms(lambda s=start: _live_windowed(session, s), repeats)
        # ... and COUNTED once on the bounded shape, because the parity check compares like with like.
        live_n = len(_live_windowed(session, start, scan_bound=scan_bound))
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
            # the direction, so a mismatch that remains reads as one: live minus rollup (negative = the rollup
            # holds keywords the bounded live window no longer does)
            "keywords_live_minus_rollup": (live_n - roll_n) if live_n is not None and roll_n is not None else None,
        })

    return {
        "available": True,
        "repeats": repeats,
        "corpus": corpus,
        "build": {
            "build_ms": build_ms,
            "keyword_daily_rows": build.get("keyword_daily_rows"),
            "streamed_mentions": build.get("streamed_mentions"),
            "scan_bound": None if scan_bound is None else str(scan_bound),
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
            "same keywords. The keyword counts (and the parity) stop at the build's scan_bound (a row a concurrent scrape committed "
            "after the build began is not counted on either side) and every mismatch records its direction; the live TIMING is "
            "of the unbounded query the app serves. In-memory DuckDB; the persisted-store durability is a separate "
            "packaging step (D1), but the per-query speedup shown here is real in a "
            "long-running process."
        ),
        "caveat": (
            "In-session warm-path numbers on your real corpus; timings vary with load and a "
            "concurrent scrape. mentions counts are exact; the distinct-article count is the "
            "disclosed upper bound (equal today under the unique keyword+article index — see "
            "parity.distinct_over_count_total). Read-only; nothing is transmitted. Counts and "
            "milliseconds only, never a score."
        ),
    }
