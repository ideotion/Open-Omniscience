"""
In-app scaling BENCHMARK: a repeatable, local, on-click timing of the heavy
read paths against the operator's REAL corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-asked 2026-06-19 ("add a benchmark so we can live test this; include
detailed benchmark logs I'll pass on to you"): the data-architecture scaling work
this session (denormalised keyword counters, the de-N+1 associations/graph, the
read-model seam, the columnar engine) was verified BYTE-IDENTICAL but never proven
FAST at decade scale on a 2-core / 6 GB machine. This is the instrument that proves
(or disproves) it on the operator's own hardware and corpus, and hands back a
self-describing log.

Honesty / safety (the maintainer↔developer diagnostics-channel contract):
- READ-ONLY: it never writes. It REPORTS the keyword-counter freshness envelope; it
  does NOT reconcile (a write that would change the very thing being measured).
- BOUNDED: every case calls a bounded query-layer function — the same one the UI
  calls — so the numbers reflect real interactive cost, not a synthetic worst case.
- AIRPLANE-SAFE: pure DB reads, no network; runnable fully offline.
- ISOLATED: every case is wrapped — one failing/absent case never aborts the run.
- SELF-DESCRIBING: the log carries the corpus size, the counter freshness, the
  columnar engine mode and the host facts, so a number is interpretable when it
  comes back to me without the machine in front of me.
- generated ON CLICK only; nothing is transmitted.

The headline cases are flagged ``optimized_this_session`` — those are the exact paths
the scaling work touched (Home grouped top-terms + super-groups via the denormalised
counters; associations / mind-map graph via the de-N+1). The rest are the broader hot
reads, included so the whole UI's behaviour at the operator's scale is visible in one
file.
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, text
from sqlalchemy.orm import Session

# How many times each case runs. Run 1 is the COLD path (may pay for SQLite page-cache
# warming); the warm aggregate over runs 2..N is reported separately so a one-off cold
# spike is not mistaken for the steady-state cost.
_DEFAULT_REPEATS = 3

# Cheap shape measure per result — NOT a correctness check, just "how many rows did
# this hot view return", so a fast number on an empty result is not read as a win.
_SIZE_KEYS = (
    "terms", "pairs", "nodes", "supergroups", "rows", "series", "windows",
    "countries", "cities", "who", "where", "framing", "members", "places",
    "entities", "results",
)


@dataclass
class _Case:
    key: str
    label: str
    fn: Callable[[], object]
    optimized: bool = False  # touched by the data-architecture scaling work this session
    heavy: bool = False      # heavier / optional path (e.g. VADER framing) — may be slow/absent
    note: str = ""


def _result_size(result: object) -> int | None:
    """Best-effort row count of a query result, for honest interpretation (never a score)."""
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for k in _SIZE_KEYS:
            v = result.get(k)
            if isinstance(v, list):
                return len(v)
    return None


def _top_term(session: Session) -> tuple[str | None, int]:
    """The busiest keyword (highest maintained mention_count) — the heaviest, most
    representative term to stress associations / the mind-map graph. None on an empty
    corpus (the dependent cases are then skipped honestly, never run on a fake term)."""
    from src.database.models import Keyword

    row = (
        session.query(Keyword.term, Keyword.mention_count)
        .filter(Keyword.mention_count > 0)
        .order_by(Keyword.mention_count.desc())
        .first()
    )
    return (str(row[0]), int(row[1])) if row else (None, 0)


def _time_case(case: _Case, repeats: int) -> dict:
    """Run one case ``repeats`` times, capturing per-run ms + cold/warm aggregates.
    Wrapped: a failing or unavailable case reports its error and never aborts the run."""
    runs: list[float] = []
    size: int | None = None
    for i in range(repeats):
        t0 = time.perf_counter()
        try:
            out = case.fn()
        except Exception as exc:  # noqa: BLE001 - report failures honestly, per case
            err_row: dict = {
                "case": case.key, "label": case.label,
                "optimized_this_session": case.optimized, "heavy": case.heavy,
                "ok": False, "error": str(exc)[:200],
            }
            if case.note:
                err_row["note"] = case.note
            if runs:  # we got at least one timing before it failed — keep it
                err_row["runs_ms"] = [round(r, 1) for r in runs]
            return err_row
        runs.append((time.perf_counter() - t0) * 1000.0)
        if i == 0:
            size = _result_size(out)

    row: dict = {
        "case": case.key, "label": case.label,
        "optimized_this_session": case.optimized, "heavy": case.heavy,
        "ok": True,
        "runs_ms": [round(r, 1) for r in runs],
        "result_size": size,
        "cold_ms": round(runs[0], 1),
        "min_ms": round(min(runs), 1),
        "median_ms": round(statistics.median(runs), 1),
        "max_ms": round(max(runs), 1),
    }
    warm = runs[1:]
    if warm:
        row["warm_min_ms"] = round(min(warm), 1)
        row["warm_median_ms"] = round(statistics.median(warm), 1)
        row["warm_max_ms"] = round(max(warm), 1)
    if case.note:
        row["note"] = case.note
    return row


def _build_cases(session: Session) -> list[_Case]:
    """The benchmark set: this session's optimized paths first, then the broader hot reads.

    Imports are LOCAL (lazy) — like the /performance endpoint — to avoid any import cycle
    with the API layer and to keep importing this module cheap."""
    from src.analytics import queries as q
    from src.database.fts import search_ids

    term, _mentions = _top_term(session)

    cases: list[_Case] = [
        _Case(
            "top_terms_grouped",
            "Home top keywords, grouped (denormalised counter path)",
            lambda: q.top_terms(session, group=True, limit=50),
            optimized=True,
            note="Slice 2: reads Keyword.mention_count / article_count (indexed), "
                 "not the keyword_mentions GROUP-BY join that dragged article pages "
                 "through the SQLCipher codec.",
        ),
        _Case(
            "supergroups",
            "Insights super-groups totals (counter path)",
            # Endpoint fn called directly with explicit args (the FastAPI Query/Depends
            # defaults are only used by the framework's resolver).
            lambda: _supergroups(session),
            optimized=True,
            note="The 132 s -> fast fix: member keyword ids are resolved first, then the "
                 "counters are read for THOSE ids only (no whole-corpus mention scan).",
        ),
    ]
    if term:
        cases += [
            _Case(
                "associations",
                f"Associations / PMI for the busiest keyword ({term!r})",
                lambda: q.associations(session, term, group=True),
                optimized=True,
                note="The 76 s -> fast fix: n_b comes from the maintained article_count "
                     "counter (or one grouped query when windowed), and the co-keyword "
                     "rows are batch-loaded — no per-pair N+1.",
            ),
            _Case(
                "layered_graph_keyword",
                f"Keyword mind-map graph for {term!r} (inherits associations ~6x)",
                lambda: q.layered_graph(session, level="keyword", term=term),
                optimized=True,
            ),
            _Case(
                "fts_search",
                f"Full-text search for the busiest keyword ({term!r})",
                lambda: search_ids(session, term),
            ),
        ]
    cases += [
        _Case("layered_graph_family", "Mind-map graph, family level",
              lambda: q.layered_graph(session, level="family")),
        _Case("layered_graph_supergroup", "Mind-map graph, super-group level",
              lambda: q.layered_graph(session, level="supergroup")),
        _Case("trending", "Trending keywords (7d vs 30d baseline)",
              lambda: q.trending(session)),
        _Case("trending_windows", "Trending across 24h / 7d / 30d (the Home poll)",
              lambda: q.trending_windows(session, series_top=5)),
        _Case("source_country_counts", "Map coverage: sources/articles/keywords/tone per country",
              lambda: q.source_country_counts(session)),
        _Case("map_data", "Top keywords per country & city (the map)",
              lambda: q.map_data(session)),
        _Case("who_aggregate", "When/Where/Who: WHO roll-up",
              lambda: q.who_aggregate(session)),
        _Case("where_aggregate", "When/Where/Who: WHERE roll-up",
              lambda: q.where_aggregate(session)),
        _Case(
            "framing", "Framing across outlets (VADER; the [analysis] extra)",
            lambda: _framing(session),
            heavy=True,
            note="Heavy and OPTIONAL: needs the [analysis] extra (VADER). If absent it "
                 "reports an error here rather than failing the run.",
        ),
    ]
    return cases


def _supergroups(session: Session) -> object:
    from src.api.insights import list_supergroups

    return list_supergroups(target_lang=None, db=session)


def _framing(session: Session) -> object:
    from src.api.framing import framing

    return framing(query=None, limit=200, db=session)


def _host() -> dict:
    from src.api import system as _system

    try:
        import psutil

        total_ram = int(psutil.virtual_memory().total)
    except Exception:  # noqa: BLE001 - honest null, never a guess
        total_ram = None
    vitals = _system._process_vitals()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "total_ram_bytes": total_ram,
        "process_rss_bytes": vitals.get("rss_bytes"),
        "uptime_s": round(time.time() - _system._BOOT_TS, 1),
    }


def _store_and_corpus(session: Session) -> tuple[dict, dict]:
    from src.database.connect import locked_state
    from src.database.models import Article, Keyword, Source
    from src.database.session import engine
    from src.paths import data_dir

    db_file = data_dir() / "open_omniscience.db"
    store: dict = {
        "db_bytes": db_file.stat().st_size if db_file.exists() else None,
        "at_rest_state": locked_state(db_file),
    }
    if engine.url.get_backend_name() == "sqlite":
        with engine.connect() as conn:
            for pragma in (
                "page_size", "page_count", "freelist_count",
                "journal_mode", "cache_size", "mmap_size",
            ):
                store[pragma] = conn.execute(text(f"PRAGMA {pragma}")).scalar()

    corpus = {
        "articles": int(session.query(func.count(Article.id)).scalar() or 0),
        "sources": int(session.query(func.count(Source.id)).scalar() or 0),
        "keywords": int(session.query(func.count(Keyword.id)).scalar() or 0),
        "keyword_mentions": int(
            session.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() or 0
        ),
    }
    return store, corpus


def _scaling_context(session: Session) -> dict:
    """The state of the very machinery this benchmark exists to measure: the keyword-
    counter freshness (are the counters the cases read currently EXACT or possibly
    drifted?) and the columnar engine mode (persisted-encrypted vs in-memory)."""
    from src.analytics.store import counter_envelope

    ctx: dict = {}
    try:
        ctx["keyword_counters"] = counter_envelope(session).to_dict()
    except Exception as exc:  # noqa: BLE001
        ctx["keyword_counters"] = {"error": str(exc)[:160]}
    try:
        from src.analytics import columnar
        from src.database.connect import get_passphrase

        ctx["columnar"] = columnar.status(get_passphrase())
    except Exception as exc:  # noqa: BLE001
        ctx["columnar"] = {"error": str(exc)[:160]}
    term, mentions = _top_term(session)
    ctx["busiest_keyword"] = {"term": term, "mention_count": mentions}
    return ctx


def run_benchmark(session: Session, *, repeats: int = _DEFAULT_REPEATS) -> dict:
    """Run the full benchmark and return the payload (the caller wraps it in the export
    envelope). Read-only, bounded, airplane-safe; each case isolated."""
    repeats = max(1, min(int(repeats), 10))
    started = time.time()
    wall0 = time.perf_counter()

    # Context gathering is best-effort: an environment quirk (an odd engine, a missing
    # store file) must degrade to an honest error note, never abort the timing — the
    # cases are the point.
    try:
        host = _host()
    except Exception as exc:  # noqa: BLE001
        host = {"error": str(exc)[:160]}
    try:
        store, corpus = _store_and_corpus(session)
    except Exception as exc:  # noqa: BLE001
        store, corpus = {"error": str(exc)[:160]}, {"error": str(exc)[:160]}
    scaling = _scaling_context(session)

    results = [_time_case(c, repeats) for c in _build_cases(session)]
    total_wall_ms = round((time.perf_counter() - wall0) * 1000, 1)

    ok = [r for r in results if r.get("ok")]
    slowest = max(
        ok, key=lambda r: r.get("median_ms", 0.0), default=None
    )
    summary = {
        "cases_run": len(results),
        "cases_ok": len(ok),
        "cases_failed": len(results) - len(ok),
        "total_wall_ms": total_wall_ms,
        "slowest_case": (slowest or {}).get("case"),
        "slowest_median_ms": (slowest or {}).get("median_ms"),
    }

    return {
        "started_at": _iso(started),
        "repeats": repeats,
        "host": host,
        "store": store,
        "corpus": corpus,
        "scaling_context": scaling,
        "summary": summary,
        "results": results,
        "method": (
            "Each case calls a bounded query-layer function (the same one the UI calls) "
            f"{repeats} time(s) against the live corpus, in-process. runs_ms lists every "
            "run; run 1 is the COLD path (may warm the SQLite page cache), and "
            "warm_*_ms aggregates runs 2..N (the steady-state cost). result_size is the "
            "row count of the view (so a fast number on an empty result is not read as a "
            "win). optimized_this_session flags the exact paths the scaling work touched "
            "(grouped top-terms + super-groups via the denormalised counters; "
            "associations + the mind-map graph via the de-N+1). Read scaling_context to "
            "see whether the counters were EXACT (reconciled) or estimated, and whether "
            "the columnar engine is persisted or in-memory, when these numbers were taken."
        ),
        "caveat": (
            "In-session, warm-path numbers: OS and SQLite caches reflect your real use, "
            "so these are the interactive cost, not a cold-boot worst case. Timings vary "
            "with what else the machine is doing (a scrape pass contends for the single "
            "encrypted writer). Read-only — the benchmark does NOT reconcile the counters, "
            "so it measures their CURRENT freshness (see scaling_context). Bounded, local, "
            "never transmitted. Counts and milliseconds only, never a score."
        ),
    }


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")
