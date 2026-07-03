"""Live-vs-rollup benchmark for the per-country source-coverage aggregation (D4, 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The choropleth map endpoint (``queries.source_country_counts``) re-scans the ARTICLES
table (per-country article count + mean tone) plus the sources and mention tables on EVERY
read. This tool BUILDS the ``source_coverage`` rollup in-memory over the operator's REAL
corpus and times the same per-country aggregation both ways — the live scan vs reading the
cached per-country rows — reporting the speedup AND a parity check (the counts must match
exactly, since both derive from the same GROUP BY), plus the rollup wrapped in the honesty
envelope ``{value, basis, as_of, method, n}``.

Honesty / safety (the diagnostics-channel contract): READ-ONLY, bounded, airplane-safe,
generated on click only, never transmitted. The one-time build cost is reported alongside
the per-read win so the amortization is honest. Counts + milliseconds only, never a score.
"""

from __future__ import annotations

import statistics
import time

from sqlalchemy.orm import Session


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


def run_source_coverage_benchmark(session: Session, *, repeats: int = 3) -> dict:
    """Build the source-coverage rollup in-memory over the live corpus and compare timings.

    Returns a self-describing payload: corpus context, the one-time build cost, a parity
    check, live-vs-rollup read timings with the speedup, and the rollup wrapped in the
    honesty envelope. Falls back honestly if duckdb is unavailable.
    """
    from sqlalchemy import func

    from src.analytics import columnar
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.envelope import Envelope
    from src.analytics.queries import source_country_counts
    from src.database.models import Article, Source

    repeats = max(1, min(int(repeats), 10))
    if not columnar.duckdb_available():
        return {"available": False,
                "reason": "duckdb not installed (the optional [columnar] extra)"}

    corpus = {
        "sources": int(session.query(func.count(Source.id)).scalar() or 0),
        "articles": int(session.query(func.count(Article.id)).scalar() or 0),
        "located_sources": int(
            session.query(func.count(Source.id))
            .filter(Source.country.isnot(None), func.trim(Source.country) != "")
            .scalar()
            or 0
        ),
    }

    con = columnar.connect(passphrase=None)  # offline -> in-memory (never a plaintext file)
    if con is None:
        return {"available": False, "reason": "columnar engine unavailable"}
    try:
        epoch = get_corpus_epoch(session)
        t0 = time.perf_counter()
        build = columnar.refresh_source_coverage(con, session, corpus_epoch=epoch)
        build_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        parity = columnar.source_coverage_parity(con, session)

        live_cold, live_med, live_n = _median_ms(
            lambda: source_country_counts(session)["by_country"], repeats
        )
        roll_cold, roll_med, roll_n = _median_ms(
            lambda: columnar.source_coverage_rows(con), repeats
        )
        speedup = round(live_med / roll_med, 1) if roll_med > 0 else None

        rows = columnar.source_coverage_rows(con)
        located = [r for r in rows if r["country"]]
        env = Envelope.estimated(
            value=located,
            as_of=build.get("as_of") or _now_iso(),
            method=(
                "Per-country coverage {sources, articles, keyword mentions, mean tone} "
                "cached in the derived source_coverage rollup; rebuilt on a corpus-epoch "
                "change (re-index/prune/restore) or when ingest advances the article/mention "
                "watermark. Counts only, no score; mean tone is VADER English-lexicon only "
                "(a country with no scored article reports null, never a fabricated zero)."
            ),
            n=corpus["located_sources"],
        )
    finally:
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
            "mode": build.get("mode"),
            "rows": build.get("rows"),
            "countries": build.get("countries"),
            "note": (
                "One-time cost: aggregates the per-country coverage once (SQLite native "
                "GROUP BY) and caches the small result. In a running app this is paid once "
                "in the background, then every map read is served from the cached rows."
            ),
        },
        "parity": parity,
        "read": {
            "live_median_ms": live_med,
            "rollup_median_ms": roll_med,
            "speedup_x": speedup,
            "live_cold_ms": live_cold,
            "rollup_cold_ms": roll_cold,
            "countries_live": live_n,
            "countries_rollup": roll_n,
        },
        "coverage": env.to_dict(),
        "method": (
            "live = the per-country choropleth aggregation over articles+sources+mentions "
            "(the map read); rollup = reading the cached source_coverage rows. Each timed "
            "'repeats' times (run 1 cold, the rest warm-median). speedup_x = live_median / "
            "rollup_median. parity.counts_match confirms the cache is byte-faithful. "
            "In-memory DuckDB; the persisted-store durability is the separate D1 step, but "
            "the per-read win shown here is real build-once-serve-many in a long process."
        ),
        "caveat": (
            "In-session warm-path numbers on your real corpus; timings vary with load and a "
            "concurrent scrape. Counts must match exactly (parity); mean tone is VADER "
            "English-only. Read-only; nothing is transmitted. Counts and milliseconds only, "
            "never a score."
        ),
    }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
