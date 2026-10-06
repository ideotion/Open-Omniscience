"""The two article-list indexes, built once at start-up where the operator can see them (R128).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT AND WHY. The article list reads one whole row per candidate on two shapes, because no index
covers them: a language filter (``idx_article_language`` finds the rows, but the date the list orders
them by sits after each article's text) and a sort by title (the list orders ``title COLLATE NOCASE``,
which an index of another collation cannot serve). On a 40,000-article, 2 GB synthetic store, cold:
1,447 ms and 807 ms; with ``idx_article_language_published (language, published_at)`` and
``idx_article_title_nocase (title COLLATE NOCASE)``, 3 ms each, the plans ``SEARCH articles USING
COVERING INDEX`` and ``SCAN articles USING COVERING INDEX`` with no sort step. The maintainer ruled it
2026-10-06 (question 34, answer a): both indexes, built at the next start while the app is still
offline, with the progress shown in the task manager.

WHY NOT INSIDE ``init_db`` LIKE THE OTHER HOT INDEXES. A ``CREATE INDEX`` over a corpus-sized table
reads every row once and holds the write lock while it runs. Inside ``init_db`` that is minutes of
nothing on screen, in the call that opens the database, on exactly the machine (a big store, a slow
drive) where it is longest. So ``maintenance.DEFERRED_INDEXES`` leaves these two out of ``init_db`` and
this module builds them as a step of the boot sequence (``boot_sequence``, ``article-indexes``), after
the check of the data files and before the warm-up, as a background job the task manager lists.

THE REFUSALS, in the order they are asked:
  * the switch ``OO_ARTICLE_INDEXES=0``, a non-SQLite store, no ``articles`` table, or both indexes
    already there: nothing to do, and no job is started for it;
  * the corpus file is paused as damaged: nothing is written to a file the database called damaged
    (the notice for it is already on screen), so the step is DECLINED, and the next start asks again;
  * the free space: the build writes each index to the write-ahead log, then into the file, with the
    sorter's temporary copy beside them, so it needs about ``BYTES_PER_ARTICLE`` bytes per article free
    on the database's volume and on the temporary-file volume. A shortfall refuses the build and the
    job row says so with the numbers (a failed row, not a silence). A figure that cannot be read is
    NOT a refusal (the ``vacuum_preflight`` rule: an unreadable ``statvfs`` must not manufacture one);
    the build goes ahead and the report says it was not measured.

THE BUILD. One statement per index, each in its own transaction, under ``write_lock()``: every writer
that comes meanwhile queues in Python (waiting, not erroring on SQLite's busy timeout), readers pass
through WAL. One statement is all or nothing: a process that ends mid-build leaves no half index, and
the next start builds from the beginning. The progress is ``index N of M`` with the elapsed time the
task manager already shows, never a percentage or an ETA (a single statement reports neither).

HONEST LIMITS. The free-space figure is an estimate (title length varies; it is sized on titles twice
the synthetic store's); the report carries what was measured. The build is not cancellable (an opaque
statement), so the row offers no Cancel.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.jobs.background import BackgroundJob, Framed, JobContext, register_job

_LOG = logging.getLogger("database.article_indexes")

JOB_KIND = "article-indexes"
LABEL = "Building the article list's indexes"
FRAME_BUILDING = (
    "Building the indexes that keep the article list fast: {index} of {total}. "
    "One time only; saving new articles waits until it is done."
)

#: The names, in the order they are built (the language filter first: it is the slower read today).
NAMES: tuple[str, ...] = ("idx_article_language_published", "idx_article_title_nocase")

#: Free bytes asked per article, on each volume the build writes to. WHAT IT PROTECTS: a disk that
#: fills while the write-ahead log grows, which would fail every writer in the app, not only this
#: build. Measured on a 40,000-article store with titles of 38 characters on average: 38 and 46 bytes
#: an article (1.5 and 1.9 MB). A real title is twice that or more, so about 125 bytes an article for
#: the pair; the write-ahead copy, the copy in the file and the sorter's temporary copy are three of
#: them: about 375, rounded to 400.
BYTES_PER_ARTICLE = 400


def switch_on() -> bool:
    """``OO_ARTICLE_INDEXES=0`` leaves the two indexes unbuilt (the article list stays as it was)."""
    return os.getenv("OO_ARTICLE_INDEXES", "1") != "0"


_LOCK = threading.Lock()
_LAST: dict[str, Any] = {}


def _record(**fields: Any) -> None:
    with _LOCK:
        _LAST.update(fields)


def snapshot() -> dict:
    """What the last start-up step did, for the diagnostics bundle: the outcome, the indexes it built
    with the seconds each took, the rows and free space it measured, the seconds it waited for the
    writer gate. ``{}`` before the step has run. Counts and times only."""
    with _LOCK:
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _LAST.items()}


def _reset_for_tests() -> None:
    with _LOCK:
        _LAST.clear()


# --- what is there, what is missing ------------------------------------------------------------


def pending(engine: Engine) -> tuple[str, list[str]]:
    """``("work", missing)`` when there is something to build, else ``("skipped", [])`` (switch off,
    not SQLite, no ``articles`` table) or ``("present", [])`` (both are there). One read of the
    schema; never builds."""
    if engine.url.get_backend_name() != "sqlite" or not switch_on():
        return "skipped", []
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "articles" not in tables:
            return "skipped", []
        have = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    missing = [n for n in NAMES if n not in have]
    return ("work", missing) if missing else ("present", [])


def _free(where: str) -> int | None:
    try:
        return int(shutil.disk_usage(where).free)
    except OSError:
        return None


def preflight(engine: Engine, rows: int) -> dict:
    """Is there room for the build? ``rows`` is the largest article id (an upper bound on the count,
    read without touching a row). Both volumes the build writes to are measured. ``sufficient`` is
    ``None`` when no figure could be read: the caller goes ahead and says it was not measured."""
    needed = int(rows) * BYTES_PER_ARTICLE
    db_path = engine.url.database
    volumes = {
        "database": (os.path.dirname(os.path.abspath(db_path)) if db_path else None) or ".",
        "temp": tempfile.gettempdir(),
    }
    measured = {name: _free(path) for name, path in volumes.items()}
    readable = {k: v for k, v in measured.items() if v is not None}
    report: dict[str, Any] = {
        "needed_bytes": needed,
        "free_bytes": measured,
        "bytes_per_article": BYTES_PER_ARTICLE,
        "method": (
            "about 400 bytes per article free on the database's volume and on the temporary-file "
            "volume: each index goes to the write-ahead log, then into the file, with the sorter's "
            "temporary copy beside them"
        ),
    }
    if not readable:
        report["sufficient"] = None
        return report
    short = sorted(k for k, v in readable.items() if v < needed)
    report["sufficient"] = not short
    if short:
        worst = min(short, key=lambda k: readable[k])
        report["short_on"] = short
        report["detail"] = (
            f"the {worst} volume has {readable[worst]:,} bytes free and the article list's indexes "
            f"need about {needed:,} ({rows:,} articles at {BYTES_PER_ARTICLE} bytes each). Free some "
            "space and restart the app; until then the article list's language filter and sort by "
            "title stay slow."
        )
    return report


# --- the build ---------------------------------------------------------------------------------


def _refresh_stats(engine: Engine, names: list[str]) -> None:
    """The planner has no statistics for an index it has just been given, and ``PRAGMA optimize`` (run at
    boot, before these existed) analyses only what a query of ITS connection used, so it would not answer
    for them. Without figures an equality on the first key column is assumed to match about ten rows,
    which is wrong for a language and can win the planner over a better index. ``ANALYZE`` of just these
    indexes, bounded by ``analysis_limit`` (a sample, not a second full read). Best effort: the indexes
    are used with or without it."""
    from src.database.writer import write_lock

    try:
        with write_lock(), engine.begin() as conn:
            conn.execute(text("PRAGMA analysis_limit=1000"))
            for name in names:
                if name in NAMES:  # a module constant, never input
                    conn.execute(text(f"ANALYZE main.{name}"))  # noqa: S608  # nosec B608
    except Exception:  # noqa: BLE001 - statistics are an optimisation, never a reason to fail the build
        _LOG.warning("planner statistics after the article indexes failed", exc_info=True)


class Declined(RuntimeError):
    """Refused for a stated reason (the free space): the job row shows the reason as its error."""


def build_missing(engine: Engine, ctx: JobContext | None = None) -> dict:
    """Build whatever of :data:`NAMES` the store lacks, one statement each, and report. Returns the
    report (also kept for :func:`snapshot`); ``report["outcome"]`` is ``built``, ``present``,
    ``skipped`` or ``declined``. A failure of a statement is recorded as ``failed`` and re-raised."""
    from src.database import damage
    from src.database.maintenance import HOT_INDEXES
    from src.database.writer import write_lock

    report: dict[str, Any] = {"outcome": "skipped", "built": {}, "started_at": time.time()}
    _record(**report)
    try:
        state, missing = pending(engine)
        if state != "work":
            report["outcome"] = state
            return report
        report["missing"] = list(missing)
        if damage.registry.writes_paused(damage.FILE_CORPUS):
            report["outcome"] = "declined"
            report["reason"] = "the corpus file is paused as damaged; nothing is written to it"
            _LOG.warning("article-list indexes not built: %s", report["reason"])
            return report
        with engine.connect() as conn:
            rows = int(conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM articles")).scalar() or 0)
        report["rows_bound"] = rows
        room = preflight(engine, rows)
        report["preflight"] = room
        if room.get("sufficient") is False:
            report["outcome"] = "declined"
            report["reason"] = room["detail"]
            _LOG.warning("article-list indexes not built: %s", room["detail"])
            raise Declined(room["detail"])
        total = len(missing)
        built: dict[str, float] = report["built"]
        for i, name in enumerate(missing):
            if ctx is not None:
                ctx.set_progress(
                    done=i,
                    total=total,
                    detail=Framed(
                        FRAME_BUILDING.format(index=i + 1, total=total), FRAME_BUILDING,
                        index=i + 1, total=total,
                    ),
                )
            asked = time.monotonic()
            with write_lock():
                got = time.monotonic()
                with engine.begin() as conn:
                    conn.execute(text(HOT_INDEXES[name]))
            done = time.monotonic()
            built[name] = round(done - got, 2)
            report["gate_wait_s"] = round(report.get("gate_wait_s", 0.0) + (got - asked), 2)
            _record(**report)
            _LOG.info("article-list index %s built in %.1f s (%d of %d)", name, done - got, i + 1, total)
        if ctx is not None:
            ctx.set_progress(done=total, total=total)
        _refresh_stats(engine, list(built))
        report["outcome"] = "built"
        return report
    except Declined:
        raise
    except Exception:
        report["outcome"] = "failed"
        _LOG.warning("article-list index build failed", exc_info=True)
        raise
    finally:
        report["finished_at"] = time.time()
        _record(**report)


def _worker(ctx: JobContext, *, engine: Engine) -> dict:
    return build_missing(engine, ctx)


ARTICLE_INDEX_JOB = register_job(
    BackgroundJob(JOB_KIND, LABEL, _worker, is_writer=True, cancellable=False)
)


def run_now_and_wait(engine: Engine | None = None) -> str:
    """The boot step's call: build what is missing as a job the task manager lists, and wait for it.
    Returns ``built``, ``present``, ``skipped``, ``declined`` or ``failed``. A store with nothing to
    build never starts a job (no row flashes by)."""
    if engine is None:
        from src.database import session

        engine = session.engine
    state, _missing = pending(engine)
    if state != "work":
        _record(outcome=state, built={}, started_at=time.time(), finished_at=time.time())
        return state
    try:
        ARTICLE_INDEX_JOB.start(engine=engine)
    except RuntimeError:
        _LOG.info("article-list index build is already running; waiting for it")
    ARTICLE_INDEX_JOB.join()
    outcome = snapshot().get("outcome")
    if ARTICLE_INDEX_JOB.status()["state"] == "error" and outcome != "declined":
        return "failed"
    return str(outcome or "failed")
