"""The two article-list indexes, built once at start-up where the operator can see them (R128).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT AND WHY. The article list reads one whole row per candidate on two shapes, because no index
covers them: a language filter (``idx_article_language`` finds the rows, but the date the list orders
them by sits after each article's text) and a sort by title (the list orders ``title COLLATE NOCASE``,
which an index of another collation cannot serve). On a 40,000-article, 2 GB synthetic store, cold, the page query took
1,284 ms and 807 ms; with ``idx_article_language_published (language, published_at)`` and
``idx_article_title_nocase (title COLLATE NOCASE)``, 3 ms each, the plans ``SEARCH articles USING
COVERING INDEX`` and ``SCAN articles USING COVERING INDEX`` with no sort step. The count behind a
language filter still reads each matching row (the index does not carry ``quarantined``): 773 -> 180 ms on
a 200,000-article store, so the list is faster, not instant. The maintainer ruled it
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
  * two starts in a row that ended while this build was running (the kernel's out-of-memory kill, a power
    cut, an app ended abruptly): the build is not tried a third time until the app is updated. The attempt is
    recorded BEFORE the first statement and cleared when the build ends however it ends; an orderly quit
    gives it back (``stop``). See ``MAX_UNFINISHED_STARTS`` for what the 2 protects;
  * the free space: the build writes each index to the write-ahead log, then into the file, so it needs
    about ``BYTES_PER_ARTICLE`` bytes per article free on the database's volume. A shortfall refuses the
    build and the job row says so with the numbers (a failed row carrying the keyed ``FRAME_NO_ROOM``
    detail, not a silence);
  * the memory: the sorter of ``CREATE INDEX`` holds every key in RAM (about ``RAM_BYTES_PER_ARTICLE`` bytes
    an article for the larger index), so the build is declined when the machine has less AVAILABLE memory
    than that estimate plus the floor the memory guard keeps free (``FRAME_NO_MEMORY``). It is NOT moved to
    a temporary file to avoid the question: every connection of the app sets ``temp_store=MEMORY`` and that
    is load-bearing here. Measured 2026-10-06 on the bundled SQLCipher, an encrypted store with
    ``temp_store=FILE``: the sorter's spill file holds the titles IN THE CLEAR (the marker string was found in
    it; so did the b-tree of a ``SELECT DISTINCT``: what SQLCipher keys is the main and attached databases,
    never a temporary or ephemeral one). A spill of that kind is what the at-rest encryption exists to
    prevent, so the cost of this build is memory, and memory is what is gated. The same setting is NOT a way
    to give VACUUM's rebuild a file either: at the app's 16 KiB page size a VACUUM with ``temp_store=FILE``
    wrote a corrupt store (see the open queue), which is why ``maintenance.vacuum_database`` keeps the pooled
    connection;
  * a figure that cannot be read (free space, available memory) is NOT a refusal (the ``vacuum_preflight``
    rule: an unreadable ``statvfs`` must not manufacture one); the build goes ahead and the report says it
    was not measured.

THE BUILD. One statement per index, each in its own transaction, under ``write_lock()``: every writer
that comes meanwhile queues in Python (waiting, not erroring on SQLite's busy timeout), readers pass
through WAL. One statement is all or nothing: a process that ends mid-build leaves no half index, and
the next start builds from the beginning. The progress is ``index N of M``; the task manager also prints
a percentage of those two statements (not of time: the title index is the larger half) and never an ETA
(a single statement reports no progress of its own).

HONEST LIMITS. Both figures are estimates (title length varies; they are sized on titles twice the
synthetic store's) and the report carries what was measured. A memory estimate that turns out too small is
not caught by the gate: the build is one opaque statement, and the memory guard it relies on pauses
COLLECTION, not a statement already running. What the attempt record adds is that a build that DOES bring
the process down is not repeated at every start. The report also carries the process's peak resident set
before and after, labelled as the high-water mark it is (it never goes down, so a build that fits under an
earlier peak adds nothing to it). The build is not cancellable (an opaque statement), so the row offers no
Cancel.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import shutil
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.jobs.background import BackgroundJob, Framed, JobContext, register_job

_LOG = logging.getLogger("database.article_indexes")

JOB_KIND = "article-indexes"
LABEL = "Building the article list's indexes"
FRAME_BUILDING = (
    "Building the indexes that keep the article list fast: {index} of {total}. "
    "One time only; anything the app saves waits until it is done."
)
#: What a refusal for space shows on the job's row (keyed x12; the numbers are whole MB and the article count,
#: an upper bound: it is the largest id).
FRAME_NO_ROOM = (
    "The article list's indexes were not built: the volume your data file is on has {free} MB free and they "
    "need about {needed} MB (up to {rows} articles). Free some space and restart the app; until then the "
    "language filter and the sort by title stay slow."
)
#: What a refusal for memory shows (the sort holds its keys in RAM; same numbers: MB available, MB wanted
#: INCLUDING the memory guard's floor, which the words say, and the article count).
FRAME_NO_MEMORY = (
    "The article list's indexes were not built: they need about {needed} MB of free memory (sorting up to {rows} "
    "titles, plus the memory the app always keeps free) and this computer has {free} MB. Close other programs and "
    "restart the app; until then the language filter and the sort by title stay slow."
)
#: What the refusal after two unfinished starts shows (see :data:`MAX_UNFINISHED_STARTS`, which the word "two" states).
FRAME_UNFINISHED = (
    "The article list's indexes were not built: two starts in a row ended while they were being built (the "
    "computer ran out of memory or power, or the app was ended abruptly), so they are not tried again until "
    "the app is updated. The language filter and the sort by title stay slow."
)

#: The names, in the order they are built (the language filter first: it is the slower read today).
NAMES: tuple[str, ...] = ("idx_article_language_published", "idx_article_title_nocase")

#: Free bytes asked per article on the database's volume. WHAT IT PROTECTS: a disk that fills while the
#: write-ahead log grows, which would fail every writer in the app, not only this build. Measured on a
#: 40,000-article store with titles of 38 characters on average: 38 and 46 bytes an article (1.5 and
#: 1.9 MB). A real title is twice that or more, so about 125 bytes an article for the pair; the
#: write-ahead copy and the copy in the file are two of them: about 250, asked as 400 for titles longer
#: than the ones measured.
BYTES_PER_ARTICLE = 400

#: RAM the sort of the LARGER index holds per article (the title index; the two are built one after the
#: other, so it is the peak), under ``temp_store=MEMORY``. Measured 2026-10-06 on an encrypted store: 600,000
#: titles of 76 Latin characters: +73.3 MiB resident = 128 bytes an article; 300,000 titles of 76 Devanagari
#: characters (224 bytes in UTF-8): +77.8 MiB = 272 bytes. The cost is about the title's bytes in UTF-8 plus 50,
#: so a script of three bytes a character is more than twice a Latin one. 300 covers a title of that kind at 76
#: characters; a Latin corpus is asked for about two and a third times what it holds, on purpose: the asymmetry
#: is that a refusal costs a slow article list until memory is freed, and an out-of-memory kill during the build
#: ends the whole app at start-up. NOT in the estimate: the page cache (``cache_mb`` of the connection, bounded
#: and already inside the process) and anything another program takes while the sort runs. WHAT IT PROTECTS: a machine that has less than this
#: much memory free (plus the memory guard's floor) is not asked to hold the sort.
RAM_BYTES_PER_ARTICLE = 300

#: How many starts in a row may begin this build and end without it ending before it is no longer tried (until
#: the app is updated: the record carries the version). WHAT THE 2 PROTECTS: a build that itself brings the
#: process down (the out-of-memory kill, the first thing the rollup's in-memory build did on the machines that
#: crashed) must not become a boot loop that never reaches collection. One unfinished start is not enough to
#: stop: a power cut or a quit by the operator ends a build too, and the second try costs only the minutes it
#: takes; a third would be the loop.
MAX_UNFINISHED_STARTS = 2

#: The record of the attempt, in the data folder: counts, the version and a time only.
ATTEMPT_FILE = "article-indexes-attempt.json"


def switch_on() -> bool:
    """``OO_ARTICLE_INDEXES=0`` leaves the two indexes unbuilt (the article list stays as it was)."""
    return os.getenv("OO_ARTICLE_INDEXES", "1") != "0"


_LOCK = threading.Lock()
_LAST: dict[str, Any] = {}
_ARMED = False  # this process wrote the attempt record and the build has not ended (guarded by _LOCK)


def _record(**fields: Any) -> None:
    """Keep a COPY of what the build knows so far: the build goes on changing its own report (the ``built``
    dict gains a key per index), and a snapshot taken meanwhile must never iterate a dict the worker is
    changing."""
    with _LOCK:
        _LAST.update(copy.deepcopy(fields))


def _replace(**fields: Any) -> None:
    """Start the state again: a run in the same process must not carry the earlier run's reason, preflight or
    missing list, whichever path it takes."""
    with _LOCK:
        _LAST.clear()
        _LAST.update(copy.deepcopy(fields))


def snapshot() -> dict:
    """What the last start-up step did, for the diagnostics bundle: the outcome, the indexes it built
    with the seconds each took, the rows and free space it measured, the seconds it waited for the
    writer gate. ``{}`` before the step has run. Counts and times only. A copy at every depth: the
    caller never shares a dict with the module's state."""
    with _LOCK:
        return copy.deepcopy(_LAST)


def _reset_for_tests() -> None:
    global _ARMED
    with _LOCK:
        _LAST.clear()
        _ARMED = False


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


def _available_ram_bytes() -> int | None:
    """The memory the machine has free now, read through the memory guard's own reader (psutil) so the build and
    the guard cannot disagree about the machine. ``None`` where nothing could be read (no psutil, a sandbox)."""
    try:
        from src.scheduler.memguard import _psutil_readings

        mb = _psutil_readings().get("mem_avail_mb")
        return int(float(mb) * 1024 * 1024) if mb is not None else None
    except Exception:  # noqa: BLE001 - an unreadable figure is not a refusal
        return None


#: The floor when the guard's own cannot be read: its default (``OO_MEM_GUARD_AVAIL_MB``).
_FLOOR_FALLBACK_BYTES = 256 * 1024 * 1024


def _floor_bytes() -> int:
    """The memory the guard keeps free: below it the guard pauses collection, so a build that would take the
    machine under it is one the guard would be stopping anyway."""
    try:
        from src.scheduler.memguard import memory_guard

        return int(float(memory_guard.avail_floor_mb) * 1024 * 1024)
    except Exception:  # noqa: BLE001
        return _FLOOR_FALLBACK_BYTES


def _peak_rss_mb() -> float | None:
    """The process's peak resident set, the high-water mark the kernel keeps (MiB). ``None`` where the platform
    keeps none (Windows has no ``resource`` module)."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError, ValueError):
        return None
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)  # macOS counts bytes, Linux KiB


def preflight(engine: Engine, rows: int) -> dict:
    """Is there room for the build? ``rows`` is the largest article id (an upper bound on the count, read
    without touching a row). Two things are measured: the free space on the database's volume, and the
    memory available against what the sort holds (``RAM_BYTES_PER_ARTICLE``) plus the memory guard's
    floor. ``sufficient`` is ``None`` when no figure of either could be read: the caller goes ahead and says
    it was not measured. ``short_on`` names what fell short (``database``, ``memory``)."""
    needed = int(rows) * BYTES_PER_ARTICLE
    ram_needed = int(rows) * RAM_BYTES_PER_ARTICLE
    floor = _floor_bytes()
    db_path = engine.url.database
    volumes = {"database": (os.path.dirname(os.path.abspath(db_path)) if db_path else None) or "."}
    measured = {name: _free(path) for name, path in volumes.items()}
    readable = {k: v for k, v in measured.items() if v is not None}
    available = _available_ram_bytes()
    report: dict[str, Any] = {
        "needed_bytes": needed,
        "free_bytes": measured,
        "bytes_per_article": BYTES_PER_ARTICLE,
        "ram_estimate_bytes": ram_needed,
        "ram_floor_bytes": floor,
        "ram_available_bytes": available,
        "method": (
            f"about {BYTES_PER_ARTICLE} bytes per article free on the database's volume: each index goes to "
            "the write-ahead log, then into the file. The sort of each is held in memory, about "
            f"{RAM_BYTES_PER_ARTICLE} bytes per article for the larger index, and the build is declined when "
            "less than that plus the memory guard's floor is available; it never uses a temporary file "
            "(on an encrypted store its sort would write the titles to it in the clear)"
        ),
    }
    if not readable and available is None:
        report["sufficient"] = None
        return report
    short = sorted(k for k, v in readable.items() if v < needed)
    if available is not None and available < ram_needed + floor:
        short.append("memory")
    report["sufficient"] = not short
    if short:
        report["short_on"] = short
        parts = []
        if "database" in short:
            parts.append(
                f"the database volume has {readable['database']:,} bytes free and the article list's indexes "
                f"need about {needed:,} (up to {rows:,} articles at {BYTES_PER_ARTICLE} bytes each). Free some "
                "space and restart the app."
            )
        if "memory" in short:
            parts.append(
                f"the machine has {available:,} bytes of memory available and sorting the titles of up to "
                f"{rows:,} articles needs about {ram_needed:,} (at {RAM_BYTES_PER_ARTICLE} bytes each) on top "
                f"of the {floor:,} the memory guard keeps free. Close other programs and restart the app."
            )
        report["detail"] = (
            " ".join(parts) + " Until then the article list's language filter and sort by title stay slow."
        )
    return report


# --- the record of an attempt ------------------------------------------------------------------


def _marker_path() -> Path:
    from src.paths import data_dir

    return data_dir() / ATTEMPT_FILE


def _unfinished_starts() -> int:
    """How many starts in a row began the build and did not see it end. 0 when there is no record, when it
    was written by another version of the app (an update may have fixed what stopped it), and when it cannot
    be read: an unreadable record is not a reason to refuse."""
    from src import __version__

    try:
        doc = json.loads(_marker_path().read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != __version__:
            return 0
        return max(0, int(doc.get("attempts") or 0))
    except (OSError, ValueError, TypeError, ArithmeticError):  # ArithmeticError: ``1e400`` is an infinity, and ``int`` of one overflows
        return 0


def _write_marker(attempts: int, **facts: Any) -> bool:
    """Atomic: write a sibling and rename. Counts, the version and times only; never a title, a path or a
    value. ``False`` when the drive cannot take it (the build goes ahead: a record that cannot be kept is
    said in the report, not a reason to refuse)."""
    from src import __version__

    doc = {
        "schema": 1,
        "version": __version__,
        "attempts": int(attempts),
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **facts,
    }
    try:
        path = _marker_path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        _LOG.warning("article-list index build: the attempt could not be recorded (%s)", type(exc).__name__)
        return False


def _arm(attempts: int, **facts: Any) -> bool:
    global _ARMED
    ok = _write_marker(attempts, **facts)
    with _LOCK:
        _ARMED = ok
    return ok


def _disarm() -> None:
    """The build ended however it ended: the record is cleared (a failure is a failed row, tried again at the
    next start; only a start that never saw the end leaves the record behind)."""
    global _ARMED
    with _LOCK:
        _ARMED = False
    with contextlib.suppress(OSError):
        _marker_path().unlink()


def stop() -> None:
    """Shutdown (the app is being quit in order): give the attempt back. A quit is not a build that brought the
    process down, and quitting twice in a long build must not stop it from being built. Never raises."""
    global _ARMED
    try:
        with _LOCK:
            armed, _ARMED = _ARMED, False
        if not armed:
            return
        left = _unfinished_starts() - 1
        if left <= 0:
            with contextlib.suppress(OSError):
                _marker_path().unlink()
        else:
            _write_marker(left, gave_back=True)
    except Exception as exc:  # noqa: BLE001 - best-effort shutdown
        _LOG.debug("article-list index build: could not give an attempt back (%s)", type(exc).__name__)


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
        # The connection first, then the gate; the commit is inside the gate, as ``engine.begin()`` under ``write_lock()`` had it.
        with engine.connect() as conn, write_lock():
            conn.execute(text("PRAGMA analysis_limit=1000"))
            for name in names:
                if name in NAMES:  # a module constant, never input
                    conn.execute(text(f"ANALYZE main.{name}"))  # noqa: S608  # nosec B608
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - statistics are an optimisation, never a reason to fail the build
        # The TYPE only, never the text or a traceback: an engine's or a driver's message (and the error it was raised from)
        # can carry a statement, and a keyed connection's can carry the passphrase; a record's ``exc_info`` rides the bundle.
        _LOG.warning("planner statistics after the article indexes failed (%s)", type(exc).__name__)


class Declined(RuntimeError):
    """Refused for a stated reason (too little free space or memory, two starts in a row that ended mid-build):
    the job row shows it as a failed row carrying the keyed detail. The next start asks again, except after
    the unfinished starts, which wait for an update."""


def build_missing(engine: Engine, ctx: JobContext | None = None) -> dict:
    """Build whatever of :data:`NAMES` the store lacks, one statement each, and report. Returns the
    report (also kept for :func:`snapshot`); ``report["outcome"]`` is ``built``, ``present``,
    ``skipped`` or ``declined``. A failure of a statement is recorded as ``failed`` and re-raised."""
    from src.database import damage
    from src.database.maintenance import HOT_INDEXES
    from src.database.writer import write_lock

    report: dict[str, Any] = {"outcome": "skipped", "built": {}, "started_at": time.time()}
    _replace(**report)
    armed = False
    began = False  # the build itself ran (or tried to): the peak after is worth reading even when the record could not be kept
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
        prior = _unfinished_starts()
        report["unfinished_starts"] = prior
        if prior >= MAX_UNFINISHED_STARTS:
            report["outcome"] = "declined"
            report["reason"] = (
                f"{prior} starts in a row ended while the indexes were being built, so they are not tried "
                "again until the app is updated"
            )
            _LOG.warning("article-list indexes not built: %s", report["reason"])
            if ctx is not None:
                ctx.set_progress(done=0, total=len(missing), detail=Framed(FRAME_UNFINISHED, FRAME_UNFINISHED))
            raise Declined(report["reason"])
        with engine.connect() as conn:
            rows = int(conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM articles")).scalar() or 0)
        report["rows_bound"] = rows
        room = preflight(engine, rows)
        report["preflight"] = room
        if room.get("sufficient") is False:
            report["outcome"] = "declined"
            report["reason"] = room["detail"]
            _LOG.warning("article-list indexes not built: %s", room["detail"])
            if ctx is not None:
                # The row's error is an English string no renderer draws for this kind; the detail is the keyed
                # frame both task managers do (it survives into the error state). When both fell short the space
                # is shown first: it is the one a restart does not cure.
                if "database" in room["short_on"]:
                    free_mb = int(room["free_bytes"]["database"] // 1_000_000)
                    need_mb = -(-int(room["needed_bytes"]) // 1_000_000)  # rounded UP: what is asked is at least this
                    frame = FRAME_NO_ROOM
                else:
                    free_mb = int(room["ram_available_bytes"] // 1_000_000)
                    need_mb = -(-(int(room["ram_estimate_bytes"]) + int(room["ram_floor_bytes"])) // 1_000_000)
                    frame = FRAME_NO_MEMORY
                ctx.set_progress(
                    done=0,
                    total=len(missing),
                    detail=Framed(
                        frame.format(free=free_mb, needed=need_mb, rows=rows), frame,
                        free=free_mb, needed=need_mb, rows=rows,
                    ),
                )
            raise Declined(room["detail"])
        armed = report["attempt_recorded"] = _arm(
            prior + 1,
            rows_bound=rows,
            ram_available_mb=None if room.get("ram_available_bytes") is None else round(room["ram_available_bytes"] / 1048576),
        )
        began = True
        report["peak_rss_mb_before"] = _peak_rss_mb()
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
            with engine.connect() as conn:  # the connection first, then the gate; "asked" below is the gate's wait alone
                asked = time.monotonic()
                with write_lock():
                    got = time.monotonic()
                    conn.execute(text(HOT_INDEXES[name]))
                    conn.commit()
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
    except Exception as exc:
        report["outcome"] = "failed"
        # The TYPE only (see ``_refresh_stats``): the exception is re-raised to the job runner, which keeps its own record of it.
        _LOG.warning("article-list index build failed (%s)", type(exc).__name__)
        raise
    finally:
        report["finished_at"] = time.time()
        if began:
            report["peak_rss_mb_after"] = _peak_rss_mb()
            report["peak_rss_note"] = (
                "the process's peak resident set (a high-water mark: it never goes down, so a build that fits "
                "under an earlier peak adds nothing to it)"
            )
        if armed:
            _disarm()
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
        _replace(outcome=state, built={}, started_at=time.time(), finished_at=time.time())
        return state
    try:
        ARTICLE_INDEX_JOB.start(engine=engine)
    except RuntimeError:
        if ARTICLE_INDEX_JOB.status().get("state") != "running":
            # Not "already running": the worker thread could not be started (``start`` gave the state back).
            _LOG.warning("article-list index build could not start its worker thread")
            return "failed"
        _LOG.info("article-list index build is already running; waiting for it")
    ARTICLE_INDEX_JOB.join()
    outcome = snapshot().get("outcome")
    if ARTICLE_INDEX_JOB.status()["state"] == "error" and outcome != "declined":
        return "failed"
    return str(outcome or "failed")
