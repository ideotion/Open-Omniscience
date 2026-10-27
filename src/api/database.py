"""
Database overview API: honest, read-only statistics about the unified store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Powers the "Database" management tab. Every number here is a real ``COUNT(*)``
or an on-disk byte size -- never an estimate dressed up as a fact
(PRODUCT_SYNTHESIS §3.5 "No fabricated numbers"). Counts are reported only for
tables that actually exist, so a core-only install (no analysis extra, no
commodity table yet) gets an honest, smaller picture rather than a crash.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import shutil
import signal
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api import served_cache
from src.database.session import engine, get_db
from src.monitoring.secret_scrub import http_detail
from src.utils.interrupts import kept_items

router = APIRouter(prefix="/api/database", tags=["database"])

# Count aggregations are full table scans in SQLite, and the Library storage view
# polls this endpoint every 4 s (Home every 15 s). They are served through
# :mod:`src.api.served_cache`: the last real counts are returned immediately with
# a visible as_of, and a recompute runs in the BACKGROUND. A poll never pays the
# scan.
#
# This REPLACES a cache keyed on (PRAGMA data_version, total_changes()) that was
# described as verified and, measured through these very functions, had a 0% hit
# rate on a pooled engine -- both probe components are per-connection, so every
# poll recomputed inline. served_cache's module docstring carries the numbers and
# the probe that replaced them.
_CACHE_TTL_S = 30


def _cached(key: str, compute, db: Session) -> dict:
    """Serve ``key`` from the shared background-refreshed cache.

    ``compute`` takes the Session to read from rather than closing over the
    request's: the background refresher re-runs the SAME callable on its own
    thread, over its own session, long after this request's session is closed.

    Keys are namespaced per module because the cache dict is process-global and
    shared with the other endpoints that use it -- an unprefixed "overview" or
    "stats" added on either side would silently serve the other's payload.
    """
    return served_cache.cached(f"db:{key}", compute, db, ttl_s=_CACHE_TTL_S)


# Human-facing label -> table name. Counted only if the table is present.
# Deliberately NOT shown (maintainer 2026-06-18): ``article_analyses`` (LLM
# summaries/translations — an internal artifact, not a corpus metric), and
# ``external_sources``/``source_groups`` (both empty, never-wired concepts —
# "external" is redundant since every source IS external, and source GROUPS
# duplicate source TAGS, the mechanism the app actually uses).
_COUNTED_TABLES: dict[str, str] = {
    "articles": "articles",
    "sources": "sources",
    "keywords": "keywords",
    "commodity_prices": "commodity_prices",
    "article_links": "article_links",
    "mentioned_dates": "article_mentioned_dates",
}


def _sqlite_file_bytes() -> dict | None:
    """Total on-disk size of the SQLite database (main + WAL + SHM), or None.

    Returns None for non-SQLite backends (or an in-memory DB), where a single
    file size is not a meaningful figure.
    """
    db_path = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or not db_path or db_path == ":memory:":
        return None
    main = Path(db_path)
    parts = {
        "main": main,
        "wal": main.with_name(main.name + "-wal"),
        "shm": main.with_name(main.name + "-shm"),
    }
    sizes = {k: (p.stat().st_size if p.exists() else 0) for k, p in parts.items()}
    return {
        "path": str(main),
        "bytes": sum(sizes.values()),
        "components": sizes,
    }


@router.get("/stats")
def database_stats(db: Session = Depends(get_db)) -> dict:
    """Real row counts per table plus backend/on-disk facts.

    Used by the Database management tab. Tables absent from this build are simply
    omitted from ``counts`` rather than reported as zero, so the UI never implies
    a feature exists when it does not. Cached briefly (computed_at/cache_ttl_s
    state the freshness window in the response).

    ``counts["sources"]`` is the flat table COUNT(*) -- kept for backward
    compatibility -- but it BLENDS actively-collecting sources with disabled
    discovery candidates awaiting review and enabled-but-not-yet-qualified
    sources. ``counts["sources_qualified"]`` (enabled AND status=qualified --
    exactly what ``select_sources`` admits to collection), ``sources_pending``
    (enabled AND status!=qualified) and ``sources_candidates`` (enabled=False)
    are the honest three-class PARTITION (2026-07-23 field-feedback S1.3; a
    first two-class cut did not sum back to the total -- amended after review):
    never show the flat figure alone where it could read as one number
    describing the corpus.
    """

    def _compute(db: Session) -> dict:
        from sqlalchemy import func, select, table, text

        present = set(inspect(engine).get_table_names())

        counts: dict[str, int] = {}
        for label, tbl in _COUNTED_TABLES.items():
            if tbl in present:
                # COUNT(*) over a table named from our own fixed map (never user input).
                counts[label] = int(
                    db.execute(select(func.count()).select_from(table(tbl))).scalar() or 0
                )

        # THREE-CLASS SOURCES SPLIT (2026-07-23 field-feedback S1.3, amended after
        # adversarial review): the flat "sources" COUNT(*) above blends enabled+
        # qualified/actively-collecting sources with disabled discovery/world-catalog
        # CANDIDATES awaiting review — exactly the figure a field export showed as
        # "~50k sources" against a ~5k-article corpus, read as an alarm rather than the
        # discovery funnel working as ruled. A first cut split into only two buckets
        # (qualified vs candidates), but those did NOT sum back to "sources" — an
        # enabled-but-not-yet-qualified source (e.g. a freshly-seeded catalog source
        # awaiting its first pass) was invisible in BOTH buckets. This is the honest
        # PARTITION — the three sum to the flat total by construction:
        #   sources_qualified  = enabled AND status=qualified (== select_sources' own
        #                        admission-gate filter -- what is ACTUALLY collecting)
        #   sources_pending    = enabled AND status!=qualified (awaiting an initial
        #                        judgment, or enabled but disqualified — not collecting
        #                        right now, but not a review-queue candidate either)
        #   sources_candidates = enabled=False (discovered, awaiting qualification review)
        if "sources" in present:
            from src.catalog.qualification import STATUS_QUALIFIED
            from src.database.models import Source

            counts["sources_qualified"] = int(
                db.query(func.count(Source.id))
                .filter(Source.enabled.is_(True), Source.status == STATUS_QUALIFIED)
                .scalar()
                or 0
            )
            counts["sources_pending"] = int(
                db.query(func.count(Source.id))
                .filter(Source.enabled.is_(True), Source.status != STATUS_QUALIFIED)
                .scalar()
                or 0
            )
            counts["sources_candidates"] = int(
                db.query(func.count(Source.id)).filter(Source.enabled.is_(False)).scalar() or 0
            )

        backend = engine.url.get_backend_name()
        from src.backup.sqlite_backup import is_sqlite

        reclaimable = None
        if backend == "sqlite":
            # Free pages only VACUUM returns to the filesystem — real PRAGMA
            # readings, shown next to the Settings compact tool.
            free_pages = int(db.execute(text("PRAGMA freelist_count")).scalar() or 0)
            page_size = int(db.execute(text("PRAGMA page_size")).scalar() or 0)
            reclaimable = free_pages * page_size

        return {
            "backend": backend,
            "url_summary": f"{backend}:///…/{Path(engine.url.database).name}"
            if engine.url.database and engine.url.database != ":memory:"
            else f"{backend} (in-memory)",
            "counts": counts,
            "file": _sqlite_file_bytes(),
            "reclaimable_bytes": reclaimable,
            "table_count": len(present),
            # Whether the backup/restore controls in the Settings tab apply here.
            "backup_supported": is_sqlite(),
        }

    return _cached("stats", _compute, db)


# The Library figures get their OWN longer interval: the single full
# keyword_mentions COUNT measured 43 s on the field corpus, so it must not ride
# the 4 s stats poll. Before S3.2 that was a plain time cache whose expiry
# recomputed INLINE -- so once a minute one poll still waited out the whole scan
# on the request thread. It now goes through served_cache like /stats: the last
# real figures are served immediately and the recompute happens in the
# background.
_FIGURES_TTL_S = 60

#: The statement deadline of the background keyword-mentions count, in seconds. It protects the pooled connection and the read
#: snapshot the count holds (an open read pins the WAL from checkpointing), not the request, which no longer waits on it. The
#: count measured 55 s and 182 s on the same 12 M-row field corpus under different load (diagnostics of 2026-10-16), so the
#: default is 300 s, 1.6 times the worst measured. ``OO_FIGURES_COUNT_DEADLINE_S`` changes it; 0 disables it.
_FIGURES_COUNT_DEADLINE_S = 300.0

#: How long a count that failed is NOT retried, in seconds: 900 s is three deadlines, so a corpus whose count cannot finish holds
#: a connection and a snapshot for at most one deadline in four, instead of one per poll. The failure is shown with this number.
_FIGURES_FAILURE_WINDOW_S = 900


#: A finished count is carried, not repeated, for this many times its own measured duration. It protects the collectors' CPU on a
#: 2-core box: the COUNT is one scan, so repeating it every ``factor x duration`` caps its duty cycle at ``1 / factor`` of one core
#: (10 -> at most 10 %; with the 55 s measured on the field corpus, one count per ~9 min). The cheap figures keep their own 60 s
#: interval; only the COUNT waits. The window is longer than ``_FIGURES_TTL_S`` only when the count is slower than 6 s.
_FIGURES_COUNT_DUTY_FACTOR = 10

_MENTIONS_LOCK = threading.Lock()
#: The last finished count: {"bind", "epoch", "count", "articles", "duration_s", "finished_at" (epoch s)}. In memory only, so after a
#: restart the first count runs at once and is measured again. Bound to the database it was counted over by the engine OBJECT (a
#: second engine never inherits it) AND by the corpus epoch AND by a generation that ``served_cache.invalidate()`` (a restore's
#: swap, a VACUUM, a panic wipe) bumps. The engine object alone says nothing: a swap keeps the one module-level engine while the
#: file under it is replaced (the trap ``source_country_rollup`` records), so a count taken over the old file would be carried as the
#: new one's for ten times its own duration. The epoch is 0 on any file never bumped, so in practice the generation is what covers a
#: swap; the epoch also separates two corpora a re-index, prune, fold or restore-merge has told apart.
_MENTIONS_MEMO: dict = {}
#: Bumped whenever the carried count is forgotten, so a count that was already running when the corpus was swapped does not store
#: its number afterwards (and its payload is not cached: ``__discard__``).
_MENTIONS_GENERATION = [0]


def _forget_mentions() -> None:
    """Forget the carried count. Run by ``served_cache.invalidate`` and by the tests: what was counted is about the file that was
    there before."""
    with _MENTIONS_LOCK:
        _MENTIONS_MEMO.clear()
        _MENTIONS_GENERATION[0] += 1


served_cache.on_invalidate(_forget_mentions)


def _figures_epoch(db: Session) -> int:
    from src.analytics.corpus_epoch import get_corpus_epoch

    return get_corpus_epoch(db)


def _now_s() -> float:
    return time.time()


def _carried_mentions(db: Session, epoch: int) -> dict | None:
    """The previous count, when it is still inside its cost-proportional window and was counted over this database; else None."""
    with _MENTIONS_LOCK:
        memo = dict(_MENTIONS_MEMO)
    if not memo:
        return None
    try:
        if db.get_bind() is not memo["bind"] or memo["epoch"] != epoch:
            return None
    except Exception:  # noqa: BLE001 - any doubt about the database -> count again
        return None
    window = _FIGURES_COUNT_DUTY_FACTOR * memo["duration_s"]
    return memo if _now_s() - memo["finished_at"] < window else None


def _remember_mentions(
    db: Session, epoch: int, generation: int, count: int, articles: int, duration_s: float,
) -> dict | None:
    try:
        bind = db.get_bind()
    except Exception:  # noqa: BLE001 - without a bind the count cannot be told apart from another database's
        return None
    memo = {
        "bind": bind, "epoch": epoch, "count": count, "articles": articles, "duration_s": duration_s, "finished_at": _now_s(),
    }
    with _MENTIONS_LOCK:
        if _MENTIONS_GENERATION[0] != generation:
            return None  # the carried count was forgotten while this one ran: it may be about the file that was swapped out
        _MENTIONS_MEMO.clear()
        _MENTIONS_MEMO.update(memo)
    return memo


#: The Library figure's public key for the whole-table mentions count. A name, not a table: the derived-read ratchet
#: (tests/test_derived_read_seam.py) counts the literal, so the key is spelled once and every write goes through this.
_COUNT_KEY = "keyword_mentions"


def _mentions_fields(memo: dict) -> dict:
    """The count's payload fields, with WHEN it was counted and how long it is carried: the ratio uses the article count of that
    moment, not today's, so the two figures describe the same instant."""
    return {
        _COUNT_KEY: memo["count"],
        "avg_keywords_per_article": round(memo["count"] / memo["articles"], 1) if memo["articles"] else None,
        "keyword_mentions_state": "counted",
        "keyword_mentions_computed_at": datetime.fromtimestamp(memo["finished_at"], UTC).isoformat(timespec="seconds"),
        "keyword_mentions_recount_after_s": int(_FIGURES_COUNT_DUTY_FACTOR * memo["duration_s"]),
    }


def _count_deadline_s() -> float:
    import os

    try:
        return float(os.environ.get("OO_FIGURES_COUNT_DEADLINE_S", _FIGURES_COUNT_DEADLINE_S))
    except ValueError:
        return _FIGURES_COUNT_DEADLINE_S


def _cheap_figures(db: Session, now: datetime) -> dict:
    """Everything in the Library figures except the keyword_mentions count: index-backed, so it is the part a request may compute."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from src.database.models import Article

    n = int(db.execute(select(func.count()).select_from(Article)).scalar() or 0)
    out: dict = {"articles": n}
    if not n:
        return out
    avg_wc = db.execute(select(func.avg(Article.word_count))).scalar()  # idx_article_word_count
    out["avg_word_count"] = round(float(avg_wc), 1) if avg_wc is not None else None
    first = db.execute(select(func.min(Article.created_at))).scalar()  # idx_article_created_at
    if first is not None:
        if first.tzinfo is None:
            first = first.replace(tzinfo=UTC)
        span_days = max((now - first).total_seconds() / 86400.0, 1.0 / 24)
        out["span_days"] = round(span_days, 2)
        out["articles_per_day"] = round(n / span_days, 1)  # lifetime average additions/day
    cutoff = now - timedelta(hours=24)  # producers.py's aware-UTC cutoff pattern
    recent = int(
        db.execute(
            select(func.count()).select_from(Article).where(Article.created_at >= cutoff)
        ).scalar()
        or 0
    )
    out["articles_last_24h"] = recent
    out["articles_per_hour_recent"] = round(recent / 24.0, 2)  # current rate over the last day
    return out


def _mentions_count(db: Session) -> int:
    from sqlalchemy import func, select

    from src.database.derived_views import KeywordMentionRead

    return int(db.execute(select(func.count()).select_from(KeywordMentionRead)).scalar() or 0)


def _compute_figures(db: Session, now: datetime) -> dict:
    """Averages + ingestion rate for the Library tab: the cheap part plus the whole-table mentions COUNT, inline.

    Counts only, no score. The COUNT is the one O(n) query, so the endpoint does not call this on the request thread (see
    :func:`_compute_figures_counted`); it stays the plain, complete computation the tests and any caller that wants it blocking use."""
    out = _cheap_figures(db, now)
    if not out["articles"]:
        return out
    n_mentions = _mentions_count(db)
    out[_COUNT_KEY] = n_mentions
    out["avg_keywords_per_article"] = round(n_mentions / out["articles"], 1)
    out["keyword_mentions_state"] = "counted"
    return out


def _failure_kind(exc_type: type, memory_short: type, statement_timeout: type) -> str:
    """The NAMED reason a count stopped: a memory stop (a subclass of the deadline abort, so every caller handles it) is not a
    time limit, and the guard's own numbers stay out of the figure. It is handed the exception's CLASS, never the exception: the
    kind is a name, and the exception's words stay where they were caught."""
    if issubclass(exc_type, memory_short):
        return "memory-short"
    return "statement-deadline" if issubclass(exc_type, statement_timeout) else exc_type.__name__


def _compute_figures_counted(db: Session, now: datetime) -> dict:
    """The background computation: the cheap part, then the COUNT under a statement deadline.

    A count that cannot finish is a NAMED failure, not a missing number and not a retry on the next poll: the payload carries
    ``keyword_mentions_state: "failed"`` with the kind (``statement-deadline``, ``memory-short`` or the exception's class), the deadline, when it
    happened and the window before it is tried again, and the entry stands for that window (``__ttl_s__``).

    COST-PROPORTIONAL RECOUNT: a finished count is carried, with ``keyword_mentions_computed_at``, for
    ``_FIGURES_COUNT_DUTY_FACTOR`` times its own measured duration, so a stale entry inside that window recomputes the cheap
    figures and starts no scan."""
    from src.database.maintenance import MemoryShort, StatementTimeout, statement_deadline

    with _MENTIONS_LOCK:
        generation = _MENTIONS_GENERATION[0]  # BEFORE the first read: an invalidate after this point makes every number below suspect
    out = _cheap_figures(db, now)
    if not out["articles"]:
        return out
    epoch = _figures_epoch(db)
    carried = _carried_mentions(db, epoch)
    if carried is not None:
        # Inside the window: refresh the cheap figures (they were just recomputed above) and carry the previous count, stamped
        # with when it was counted. A stale entry here starts NO scan.
        out.update(_mentions_fields(carried))
        return out
    deadline = _count_deadline_s()
    started = time.monotonic()
    try:
        with statement_deadline(db, deadline):
            n_mentions = _mentions_count(db)
    except Exception as exc:  # noqa: BLE001 - a failed count is recorded, never raised into a poller
        out.update(
            {
                _COUNT_KEY: None,
                "avg_keywords_per_article": None,
                "keyword_mentions_state": "failed",
                "keyword_mentions_failure": {
                    "kind": _failure_kind(type(exc), MemoryShort, StatementTimeout),
                    "deadline_s": deadline,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "retry_after_s": _FIGURES_FAILURE_WINDOW_S,
                },
            }
        )
        out["__ttl_s__"] = _FIGURES_FAILURE_WINDOW_S
        with _MENTIONS_LOCK:
            if _MENTIONS_GENERATION[0] != generation:
                out["__discard__"] = True  # the corpus was swapped while the count ran: a failure about the old file is not this one's
        with contextlib.suppress(Exception):
            db.rollback()  # the interrupted statement leaves the transaction unusable for the next caller of this session
        return out
    memo = _remember_mentions(db, epoch, generation, n_mentions, out["articles"], max(time.monotonic() - started, 0.001))
    if memo is None:
        out[_COUNT_KEY] = n_mentions
        out["avg_keywords_per_article"] = round(n_mentions / out["articles"], 1)
        out["keyword_mentions_state"] = "counted"
        out["keyword_mentions_computed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        out["__discard__"] = True  # not carried and not cached (no bind, or the corpus was swapped mid-count): counted over a file that may be gone
    else:
        out.update(_mentions_fields(memo))
    return out


def _figures_pending(db: Session) -> dict:
    """What a cold request is answered with while the count runs: the cheap part, exact now, and the count as NOT YET KNOWN."""
    out = _cheap_figures(db, datetime.now(UTC))
    if out["articles"]:
        out.update(
            {
                _COUNT_KEY: None,
                "avg_keywords_per_article": None,
                "keyword_mentions_state": "computing",
                "keyword_mentions_reason": "counting every keyword mention in the background; the other figures are exact now",
            }
        )
    return out


@router.get("/figures")
def library_figures(db: Session = Depends(get_db)) -> dict:
    """Computed Library figures: average article word count, average keyword mentions
    per article, and the ingestion RATE (lifetime average articles/day + the current
    articles/hour over the last 24 h). Served from the background-refreshed cache,
    so a poll never waits on the whole-table mentions count; ``as_of``/``cache_age_s``
    state the figures' real age.

    The FIRST call after boot used to compute that count inline (55 s on the field corpus, 2026-10-16): it now starts one
    background count and answers at once with the cheap figures, the mentions count null and ``keyword_mentions_state:
    "computing"`` (``pending_since`` says when it started). A count that passes its statement deadline is recorded as
    ``"failed"`` with its kind, deadline and retry window rather than retried on every poll."""

    # `now` is read INSIDE the compute rather than captured here: a background
    # rebuild runs minutes after the request that kicked it, and the 24 h window
    # must be measured from when the figures were actually computed.
    def _compute(session: Session) -> dict:
        return _compute_figures_counted(session, datetime.now(UTC))

    # Namespaced like every other key here: it does NOT go through _cached (the
    # figures carry their own longer interval), so the prefix has to be written
    # out, or this one key sits unprefixed in a dict shared with another module.
    return served_cache.cached("db:figures", _compute, db, ttl_s=_FIGURES_TTL_S, cold_payload=_figures_pending)


@router.get("/coverage")
def country_coverage(db: Session = Depends(get_db)) -> dict:
    """Summary of how many countries the catalog reaches, plus the gaps.

    Counts are computed from each source's country code (real data) against the
    ISO 3166-1 set, so coverage is measured, never asserted. ``missing`` lists
    country codes with no source; ``thin`` lists covered countries with very few.
    """
    from sqlalchemy import func

    from src.catalog.countries import country_display_name
    from src.catalog.coverage import (
        country_counts_from_session,
        coverage_report,
        regional_report,
    )
    from src.database.models import Source

    def _compute(db: Session) -> dict:
        counts = country_counts_from_session(db)
        report = coverage_report(counts)
        report["missing"] = report["missing"][:80]  # trim for the UI; details in /countries
        total_sources = int(db.query(func.count(Source.id)).scalar() or 0)
        report["regional"] = regional_report(counts, total_sources=total_sources)
        # Full display names for every code this response mentions (one conversion
        # layer, applied server-side; the UI never carries its own country table).
        mentioned = (
            set(report["missing"])
            | set(report["thin"])
            | set(report["extra_codes"])
            | set(report["special_codes"])
        )
        top = report["regional"]["top_country"]["code"]
        if top:
            mentioned.add(top)
        report["names"] = {c: country_display_name(c) for c in sorted(mentioned)}
        return report

    return _cached("coverage", _compute, db)


@router.get("/countries")
def sources_by_country(db: Session = Depends(get_db)) -> dict:
    """Per-country breakdown: source count, enabled count, and topic keywords.

    Topic keywords are the aggregated tags of the sources in each country — they
    show, at a glance, which subjects a country's sources cover (and by absence,
    which topics may be missing). Countries with no source are returned in
    ``missing`` so covered vs not-covered is explicit.

    2026-07-26 hardware diagnostics: this was a bare ``SCAN sources`` on every
    request (``tags`` isn't index-covered), the dominant server-cost item on all 7
    field instances (12-81% of uptime). Now served from an off-peak-refreshed
    in-memory rollup (:mod:`src.analytics.source_country_rollup`, mirrors
    ``reconcile_source_counters``) when warm; falls back to the identical live scan
    otherwise (cold start, a differently-bound session, or any rollup error) — the
    response is never wrong, only sometimes not-yet-warm.
    """
    from src.analytics import source_country_rollup

    def _compute(db: Session) -> dict:
        served = source_country_rollup.served(db)
        if served is not None:
            return served
        return source_country_rollup._live_sources_by_country(db)

    return _cached("countries", _compute, db)


@router.post("/vacuum")
def vacuum() -> dict:
    """Rebuild the database file (VACUUM) + refresh planner statistics.

    The Settings maintenance tool (performance batch 2026-06-12): reclaims the
    free pages that deletes leave behind and defragments the b-trees. Honest
    costs are part of the contract: the rebuild takes time proportional to the
    file and needs exclusive write access — if collection is writing, this
    returns 409 rather than queueing silently.

    SPACE AND MEMORY ARE CHECKED FIRST (DB-10 §2 carry-over, 2026-09-09; the
    memory half 2026-10-06). The UI already disclosed an estimated duration and
    confirmed; nothing checked whether the machine could hold the rebuild. VACUUM
    rewrites the pages in use into a second copy before swapping it in: the copy
    goes through the log into the file, so the database's volume needs about
    twice the pages in use free (plus the log's size), and the copy is HELD IN
    MEMORY (every connection of the app keeps its temporary data there), about
    1.25 times the pages in use on top of the floor the memory guard keeps free
    — and running out of either mid-rebuild is the worst moment to find that out
    (the memory case is the out-of-memory kill that ends the whole app). A
    measured shortfall of EITHER is refused with **507** and the real numbers
    (``short_on`` says which), kept DISTINCT from the 409 "something else is
    writing": collapsing two different refusals into one status is how an
    operator comes to fix the wrong thing. A figure that cannot be read is NOT a
    refusal — the vacuum proceeds, and the response names what was not checked.
    """
    from sqlalchemy.exc import OperationalError

    from src.database.maintenance import VacuumSpaceError, vacuum_database

    try:
        report = vacuum_database(engine)
    except VacuumSpaceError as exc:
        raise HTTPException(status_code=507, detail=exc.report["detail"]) from exc
    except OperationalError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "the database is busy (a collection pass or import is writing); "
                "stop it or retry when it finishes"
            ),
        ) from exc
    # A VACUUM rewrites the file wholesale through a raw connection that never
    # touches the write gate, so the `grants` probe cannot see it. Drop the
    # served counts by name rather than leaving them to a probe that is blind to
    # exactly this path (reclaimable_bytes is what changes here, and it is served
    # from the same "stats" entry).
    served_cache.invalidate()
    return report


#: A snapshot directory this old is a crashed server's. It is the line between "a download still in flight" and "a leftover":
#: another server on the same data folder (R176) may be streaming its own snapshot, and no download of one lasts a day (an
#: 11.7 GB file at 1 MB/s is about 3.3 hours), so a younger directory is never touched and an older one is removed. It also bounds
#: how long a claim whose response was never run can keep the endpoint busy.
_BACKUP_STALE_AFTER_S = 24 * 3600
_BACKUP_DIR_PREFIX = ".oo-backup-"
_BACKUP_LOCK = threading.Lock()
#: The download in flight in THIS process (not in another server on the same data folder, R176: each makes its own, and the
#: free-space gate is each one's own look at the volume): (its claim token, when it was claimed), or None. The token is what a
#: request holds: only the request whose token is recorded can free the claim, so a download that outlives its claim (taken over
#: after :data:`_BACKUP_STALE_AFTER_S`) cannot free the takeover's.
_backup_flight: tuple[object, float] | None = None
#: The snapshot directories this process has made and not yet removed, with the pid that made them (guarded by
#: :data:`_BACKUP_LOCK`). A process that STOPS while a worker thread is still writing a snapshot has no task left to remove the
#: directory when the thread ends, and two stops do that: uvicorn's second Ctrl+C closes the loop at once and the interpreter then
#: waits for the thread (removed by :func:`_remove_live_snapshot_dirs` at exit), and a SIGTERM that outlasts the graceful window
#: ends the process by the signal itself, which runs no exit hook (removed by :func:`install_stop_signal_cleanup`'s handler, just
#: before the signal does its work). A kill (SIGKILL, power) runs nothing; the sweeps cover that.
_live_snapshot_dirs: dict[Path, int] = {}


def _refuse_cross_site(request: Request) -> None:
    """403 unless this GET comes from the app's own page or from a caller that is not a browser.

    A browser cannot be stopped from sending a GET to a loopback address, and the response of this one is the whole corpus written
    out in plaintext, so the route has to refuse for itself the requests a page of another site makes (an ``<img src>`` or a
    ``fetch`` to ``http://127.0.0.1:PORT/api/database/backup`` costs the machine a full snapshot even where the browser then hides
    the answer). Every one of these must pass; what the refusal reads:

    * ``Host``: one of the names the app's DNS-rebinding guard serves (the loopback names and ``OO_ALLOWED_HOSTS``).
      A page on a name that an attacker rebinds to 127.0.0.1 is SAME-ORIGIN with itself, so the checks below pass for it and only
      this one stops it; the middleware stops it too, and the route does not depend on that.
    * ``Sec-Fetch-Site`` when the browser sends it: ``same-origin`` (the app's own page) and ``none`` (an address typed or a bookmark)
      pass; ``same-site`` (another port or host on this machine) and ``cross-site`` do not.
    * ``Origin``, else ``Referer``, when sent: judged by the POST middleware's own ``_foreign_origin`` (scheme-default ports
      normalised, so a proxy's ``Host: NAME:443`` with ``Origin: https://NAME`` is the same server; the hostname must be one the
      app serves; another port is another origin). ``Origin: null`` names no host and is refused.
    * Neither sent: a command line, a script or a navigation from this page, which carries no ``Referer`` under the app's own
      ``Referrer-Policy: no-referrer``. Allowed, as the middleware allows them for the state-changing methods. **The stated limit,
      in two forms:** a browser that does not send Fetch Metadata (Firefox before 90, Safari before 16.4, an old embedded webview),
      and any browser asked for a name that is not a "potentially trustworthy" address (an ``OO_ALLOWED_HOSTS`` name over plain
      HTTP: browsers attach Fetch Metadata only to loopback and HTTPS targets), send none of the three for
      ``<img src=... referrerpolicy="no-referrer">``, so that request is served: the page still cannot read the answer, but the
      machine writes the snapshot. The one-at-a-time slot and the free-space gate bound what that costs.
    """
    from src.api.main import _allowed_hosts, _foreign_origin, _host_without_port

    refusal = HTTPException(
        status_code=403,
        detail="Refused: the corpus snapshot is served to the app's own page, not to a request from another site or origin.",
    )
    if _host_without_port(request.headers.get("host", "")) not in _allowed_hosts():
        raise refusal
    site = request.headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in ("same-origin", "none"):
        raise refusal
    sent = request.headers.get("origin")
    if sent is None:
        sent = request.headers.get("referer")
    if sent is None:
        return
    if _foreign_origin(request, sent):
        raise refusal


def _claim_backup_slot() -> object:
    """One snapshot at a time in this process: 429 while another is being made or streamed. Returns the claim's token.

    A snapshot is a full copy of the corpus on the data volume, so two at once is twice the disk and twice the reads of a store
    the collector is writing into. The claim is released when the response ends, however it ends; a claim older than
    :data:`_BACKUP_STALE_AFTER_S` is taken over: a response that never ran, or one still streaming after a day, which the token
    keeps from freeing the takeover's claim. It is a per-process rule: two servers on one data folder (R176) can each hold one."""
    global _backup_flight
    token = object()
    with _BACKUP_LOCK:
        if _backup_flight is not None and (time.monotonic() - _backup_flight[1]) < _BACKUP_STALE_AFTER_S:
            raise HTTPException(
                status_code=429,
                detail="Another corpus snapshot is being made or downloaded; retry when it has finished.",
            )
        _backup_flight = (token, time.monotonic())
    return token


def _release_backup_slot(token: object, workdir: Path | None) -> None:
    """Remove the snapshot directory (if one was made) and free the claim ``token`` holds. Idempotent; never raises.

    The directory is this request's own and is removed whatever became of the claim; the claim is freed only if it is still this
    request's, so a download that was taken over (a day or more in flight) does not free the takeover's."""
    global _backup_flight
    if workdir is not None:
        shutil.rmtree(workdir, ignore_errors=True)
        from src.backup.stream_backup import unregister_active_staging

        unregister_active_staging(workdir)
    with _BACKUP_LOCK:
        if workdir is not None:
            _live_snapshot_dirs.pop(workdir, None)
        if _backup_flight is not None and _backup_flight[0] is token:
            _backup_flight = None


def _remove_live_snapshot_dirs() -> None:
    """At interpreter exit, remove the snapshot directories this process made and still holds (0.5.1 item 41). Never raises.

    Python joins its non-daemon threads BEFORE it runs the exit hooks, so a worker thread that was still writing a snapshot when a
    forced stop closed the loop has finished by now, and the file it wrote is what this removes. Only the pid that made a directory
    removes it: a forked child that inherited the table must not take its parent's live download."""
    me = os.getpid()
    with _BACKUP_LOCK:
        # kept_items, not a filtered comprehension: this runs as an exit hook and inside the SIGTERM handler, and a comprehension's back-edge
        # under a `with` is outside the lock's exception-table entry (src/utils/interrupts.py; tests/test_loop_heads_reach.py)
        mine = list(kept_items(_live_snapshot_dirs, lambda _path, pid: pid == me))
        for path in mine:
            del _live_snapshot_dirs[path]
    for path in mine:
        shutil.rmtree(path, ignore_errors=True)


atexit.register(_remove_live_snapshot_dirs)


def install_stop_signal_cleanup() -> list[str]:
    """Remove this process's snapshot directories before a SIGTERM ends it (0.5.1 item 41, the second half). Returns the names installed.

    uvicorn handles SIGTERM itself while it runs: it stops accepting, waits up to ``timeout_graceful_shutdown`` for the requests in
    flight and cancels what is left. Then, as it returns, it puts back the handlers it found and RAISES the signal again, so that the
    process ends the way a SIGTERM ends it. That is the in-app power button (``request_shutdown``), SIGHUP (routed onto SIGTERM by
    ``install_signal_handlers``) and a logout. The handler that is put back is whatever stood there when ``uvicorn.run`` began; with
    the default one the process dies on the spot, with no thread joined and no exit hook run, and a snapshot that was still being
    written (or finished and not yet read by a client that stopped) stays behind as a plaintext copy of the corpus (measured on the
    real app under a real uvicorn, 30 s window: rc -15, the whole file left).

    So this must run BEFORE ``uvicorn.run``: its handler removes the directories this process holds and then restores the default
    action and sends the signal to itself, which ends the process exactly as before (same exit status), only with the copy gone. A
    worker thread still writing into the removed directory writes to an unlinked file that the process's end frees. SIGINT needs
    nothing: uvicorn re-raises it as a ``KeyboardInterrupt`` and the interpreter then runs :func:`_remove_live_snapshot_dirs`.
    """
    installed: list[str] = []

    def _remove_then_die(signum, _frame):  # pragma: no cover - driven by a real signal; a real process pins it
        # A second SIGTERM must not run this handler again on top of itself: during the removal (seconds on some file systems) it would
        # find the table already emptied and kill the process with the directory still there, and while this one holds _BACKUP_LOCK
        # (not reentrant, and this is the main thread) it would block for good. Measured by the read of item 41.
        signal.signal(signum, signal.SIG_IGN)
        try:
            _remove_live_snapshot_dirs()
        finally:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGTERM, _remove_then_die)
        installed.append("SIGTERM")
    except (ValueError, OSError):  # not the main thread, or no such signal here
        pass
    return installed


def _sweep_stale_snapshots(data_dir: Path) -> None:
    """Remove the snapshot directories a crashed server left (older than :data:`_BACKUP_STALE_AFTER_S`). Never raises."""
    cutoff = time.time() - _BACKUP_STALE_AFTER_S
    try:
        names = os.listdir(data_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith(_BACKUP_DIR_PREFIX):
            continue
        path = data_dir / name
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


class _SnapshotResponse(FileResponse):
    """A file response that removes its snapshot directory when it ends, however it ends (sent, client gone, error, cancelled).

    The removal runs in a worker thread, shielded from the cancellation of the task (a server shutting down, a cancel scope
    around the response; a disconnected client is not relied on to cancel it, and on a stack that only drops the sends the file
    is read to its end first): deleting a corpus-sized file can take seconds on some file systems (btrfs, ZFS, a USB disk) and
    must neither stall the event loop nor be skipped."""

    def __init__(self, path: Path, workdir: Path, token: object, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self._workdir = workdir
        self._token = token

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # shielded: a cancelled task (shutdown, a cancel scope) must still get its directory removed and its claim freed
            await asyncio.shield(run_in_threadpool(_release_backup_slot, self._token, self._workdir))


@router.get("/backup")
def download_backup(request: Request) -> FileResponse:
    """Stream a consistent SQLite snapshot of the corpus as a download.

    Uses the online backup API, so the snapshot is valid even while the app is
    running. Refuses (HTTP 400) on non-SQLite backends rather than pretending.

    Audit 0.5.0, A-008. The snapshot is a PLAINTEXT copy of the whole corpus, so it is written where the corpus already lives, in a
    private directory (``.oo-backup-*``, owner-only) next to the database, not in the operating system's temporary directory
    (often a RAM disk, often world-listable, never covered by the data folder's own protections). It is refused for a request
    from another site (:func:`_refuse_cross_site`), made one at a time (:func:`_claim_backup_slot`), and not started when the
    data volume has less free space than the file and its log, the most a snapshot can write (507, with both figures; a figure
    that cannot be read is not a refusal, and the response says it was not checked). The directory is removed when the
    response ends (a process that is stopped while a snapshot is still being written removes it as it stops: at interpreter exit,
    :func:`_remove_live_snapshot_dirs`, and before a SIGTERM that outlasts the graceful window ends it, :func:`install_stop_signal_cleanup`),
    and a leftover from a crashed server older than a day is removed by the next request. A KILL (SIGKILL, the power) runs nothing, so
    the directory carries an owner marker (:func:`src.backup.stream_backup.write_owner_marker`): the boot sweep removes a dead
    owner's directory at the next start at once, and one with no marker only by the age rule.
    """
    from src.backup.sqlite_backup import BackupError, backup_to, live_db_path
    from src.database.connect import is_encrypted_file

    _refuse_cross_site(request)
    token = _claim_backup_slot()
    workdir: Path | None = None
    try:
        try:
            db_path = live_db_path()
        except BackupError as exc:
            raise HTTPException(status_code=400, detail=http_detail(exc)) from exc
        data_dir = db_path.parent
        _sweep_stale_snapshots(data_dir)
        space_checked = True
        # An encrypted store is refused by ``backup_to`` before it writes a byte, whatever the space; only a snapshot that will
        # really be written is measured against the volume.
        if not is_encrypted_file(db_path):
            needed = 0
            for part, may_be_absent in ((db_path, False), (Path(str(db_path) + "-wal"), True)):
                try:
                    needed += part.stat().st_size
                except FileNotFoundError:
                    # no log file is a log of zero bytes; a missing database file is a figure that is not known
                    space_checked = space_checked and may_be_absent
                except OSError:
                    space_checked = False  # a size that cannot be read leaves the figure short, and the response says so
            try:
                free = int(shutil.disk_usage(data_dir).free)
            except OSError:
                free, space_checked = None, False
            if free is not None and free < needed:
                raise HTTPException(
                    status_code=507,
                    detail=(
                        f"Not enough free space on the data volume for a snapshot: {free:,} bytes free, "
                        f"{'up to' if space_checked else 'at least'} {needed:,} needed (the database file and its log"
                        f"{'' if space_checked else ', one of whose sizes could not be read'}). "
                        "Free some space, or use the streaming backup in Settings."
                    ),
                )
        workdir = Path(tempfile.mkdtemp(prefix=_BACKUP_DIR_PREFIX, dir=data_dir))
        with _BACKUP_LOCK:
            _live_snapshot_dirs[workdir] = os.getpid()
        # Whose directory this is, for the boot sweep: a KILL (SIGKILL, power) runs no exit hook, and the leftover is a full plaintext
        # copy of the corpus. With the marker the next start removes a dead owner's directory at once; without it (the write is
        # best-effort) the sweep falls back to the 24 h age rule, as it always did (0.5.1 item 40).
        from src.backup.stream_backup import register_active_staging, write_owner_marker

        write_owner_marker(workdir)
        # And registered as a live job's staging, which the sweeps check BEFORE they read any marker: the verdict on a marker compares
        # process start times as wall-clock instants, and a clock step while a download is in flight would otherwise let this process's
        # own maintenance sweep take the directory from under its client (found by the read of item 40, measured).
        register_active_staging(workdir)
        snapshot = workdir / "snapshot.db"
        try:
            backup_to(snapshot)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail=http_detail(exc)) from exc
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return _SnapshotResponse(
            snapshot,
            workdir,
            token,
            media_type="application/x-sqlite3",
            filename=f"open-omniscience-backup-{ts}.db",
            headers=None if space_checked else {"X-OO-Free-Space-Check": "not-read"},
        )
    except BaseException:
        _release_backup_slot(token, workdir)
        raise


# NOTE: the destructive POST /api/database/restore (replace the live corpus with
# an uploaded SQLite file) was REMOVED on 2026-06-13 (maintainer ruling: restore
# is ADDITIVE-ONLY). Restoring goes exclusively through the merge engine at
# the additive merge engine, which complements the corpus and never overwrites it.
# Its endpoints are POST /api/backup/import-queue/start (the one import path) and
# POST /api/backup/legacy/restore (one single-file archive). The upload-based
# /api/backup/v2/restore/{preview,commit} this note used to name was consolidated
# away on 2026-09-16 (Q214 = a). (Backup CREATION — GET /api/database/backup — stays.)
