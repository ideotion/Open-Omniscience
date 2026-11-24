"""The bulk-build index window (audit §9.2 item 5, ruling R23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS FOR. Every mention row written by ``index_article`` is maintained in the
primary key plus TEN secondary indexes on ``keyword_mentions``, and each when/where/who
row in up to three more. A corpus-sized re-index pays that per row. The bulk build drops
the droppable ones, loads, and rebuilds each index ONCE, sequentially -- which is the
audit's "step that changes the order of magnitude on this class of machine".

R23 PUTS IT ON THE LIVE STORE, not a working copy swapped in at twice the disk. That
decides the two hard problems this module exists to solve, and neither is the dropping:

**1. A CRASH MUST NOT COST AN INDEX.** Measured on this tree: of the 14 droppable
indexes, only FOUR are in ``maintenance.HOT_INDEXES``, the boot self-heal that recreates
missing hot indexes. The other TEN are created by ``create_all``/alembic, which never add
an index to an existing table -- so a process that died between the DROP and the rebuild
would leave them gone PERMANENTLY, with nothing in the tree to restore them, turning
every query that used them into a full scan over 27.7 GB, silently and forever. So this
module carries its own heal, and it is wired into the boot path.

**THE HEAL READS REALITY, NOT BOOKKEEPING.** The durable marker records the full set the
window MAY drop, once, before the first DROP -- never a running tally of what it did. The
heal then asks ``sqlite_master`` which of those are actually absent and creates those.
That is correct after a crash at ANY point, including between a DROP and its record,
which a tally is not. The one accounting rule left is the ordering: the marker is
committed BEFORE the first DROP, because a DROP with no marker is an index nobody knows
to restore.

**2. THE UNIQUE INDEXES ARE NEVER DROPPED**, and this is a correctness matter rather than
a caution. §9.2 item 5 says to drop "the ten secondary mention indexes and the seven
when/where/who indexes"; measured, those counts are right, but three of the seventeen are
UNIQUE -- ``ix_mention_keyword_article``, ``ix_amp_article_place`` and
``ix_ae_article_name_class``. They are not performance indexes, they are the constraints
that make "one mention row per (keyword, article)" true, and the bulk-insert path relies
on the collision they raise (pinned in tests/test_bulk_mention_insert.py). Dropping them
would let a load insert duplicates that no error reports and that the counters would then
faithfully double. Hence 14 droppable, not 17.

**THE DDL COMES FROM THE METADATA, NEVER A COPY.** ``CreateIndex`` compiles each index
from ``Base.metadata``, so the heal cannot drift from the models the way a second
hardcoded DDL table would. The measured failure this avoids is the one the repo already
knows: a hardcoded self-heal list that silently stopped matching the model.

NOT IN THIS MODULE, deliberately: the sorted-runs extraction and the load-in-key-order
half of item 5. Dropping indexes is worth having on its own, but a caller that DELETEs per
article (every current drain path does) MUST keep ``ix_mention_article`` or each delete
becomes a full scan -- which is why :func:`bulk_index_window` takes ``keep`` explicitly
rather than guessing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, DropIndex

from src.monitoring.secret_scrub import log_failure
from src.utils.interrupts import kept

_LOG = logging.getLogger(__name__)

# The ``derived_meta`` key. Its value is the ISO instant the window opened plus the
# newline-joined set it may have dropped -- flat text, because derived_meta.value is a
# String(255)-shaped key/value store and a JSON blob here would outgrow it.
BULK_BUILD_KEY = "bulk_build_open"

# The tables whose per-row index maintenance the bulk build exists to remove.
_MENTION_TABLE = "keyword_mentions"
_WWW_TABLES = ("article_mentioned_dates", "article_mentioned_places", "article_entities")

# The one index a per-article DELETE path cannot lose: index_article does
# `DELETE FROM keyword_mentions WHERE article_id = ?` once per article, which without
# this index is a full scan of the mention table PER ARTICLE -- a cure far worse than
# the disease. Callers that delete per article pass this in ``keep``.
ARTICLE_DELETE_INDEX = "ix_mention_article"


def _target_tables() -> tuple[str, ...]:
    return (_MENTION_TABLE, *_WWW_TABLES)


def droppable_indexes(*, keep: Iterable[str] = ()) -> list[str]:
    """The index names the bulk build may drop, sorted, UNIQUE ones excluded.

    Derived from the live metadata rather than listed, so a new index on these tables is
    covered the day it lands instead of the day someone remembers this file.
    """
    from src.database.models import Base

    keep = set(keep)
    out: list[str] = []
    for name, table in Base.metadata.tables.items():
        if name not in _target_tables():
            continue
        for index in table.indexes:
            if index.unique:
                continue  # a constraint, not a performance index -- see the module note
            if index.name in keep:
                continue
            out.append(str(index.name))
    return sorted(out)


def _index_by_name(name: str):
    from src.database.models import Base

    for table_name, table in Base.metadata.tables.items():
        if table_name not in _target_tables():
            continue
        for index in table.indexes:
            if index.name == name:
                return index
    return None


def _existing_indexes(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
    }


# --- the durable marker ----------------------------------------------------- #


def read_state(session: Session) -> dict | None:
    """``{"since": iso, "planned": [names]}`` while a bulk build is open, else ``None``.

    Degrades toward OPEN on an unreadable store: a read that failed cannot support the
    claim that no indexes are missing, and the cost of a false "open" is one redundant
    heal pass, against a false "closed" costing ten indexes nobody restores.
    """
    from src.database.models import DerivedMeta

    try:
        row = session.get(DerivedMeta, BULK_BUILD_KEY)
    except Exception as exc:  # noqa: BLE001 - an unreadable marker cannot prove the store is whole
        log_failure(_LOG, "bulk-build marker unreadable; treating as OPEN", exc, level=logging.WARNING)
        return {"since": "unknown", "planned": []}
    if row is None:
        return None
    parts = (row.value or "").split("\n")
    return {"since": parts[0] if parts else "", "planned": [p for p in parts[1:] if p]}


def open_state(session: Session, planned: Iterable[str], *, now=None) -> str:
    """Record the set this window MAY drop, and COMMIT before any DROP runs.

    The commit is the whole guarantee: an index dropped with no durable record of it is
    an index the heal will never look for.
    """
    from src.database.models import DerivedMeta
    from src.database.writer import connection_first, write_lock

    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    payload = "\n".join([stamp, *sorted(planned)])
    connection_first(session)  # the connection, then the gate (writer.connection_first)
    with write_lock():
        row = session.get(DerivedMeta, BULK_BUILD_KEY)
        if row is None:
            session.add(DerivedMeta(key=BULK_BUILD_KEY, value=payload))
        else:
            row.value = payload
        session.commit()
    return stamp


def close_state(session: Session) -> bool:
    """Clear the marker. Returns True when one was removed.

    Only :func:`_rebuild_missing` may call this, and only once every planned index is
    present -- the marker outliving a finished build costs a redundant heal, while
    clearing it early costs the indexes it was protecting.
    """
    from src.database.models import DerivedMeta
    from src.database.writer import connection_first, write_lock

    connection_first(session)
    with write_lock():
        row = session.get(DerivedMeta, BULK_BUILD_KEY)
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True


# --- the disclosure R23 requires -------------------------------------------- #


def rebuild_progress(session: Session) -> dict:
    """"Rebuilding, N of M" -- counted from the store, never from a tally.

    ``done``/``total`` describe the PLANNED set of this window: how many of the indexes
    it may have dropped are present again. A caller showing progress therefore shows a
    measured fact about the store, not a counter something remembered to increment.
    """
    state = read_state(session)
    if state is None:
        return {"rebuilding": False, "done": 0, "total": 0, "missing": [], "since": None}
    planned = list(state["planned"])
    conn = session.connection()
    existing = _existing_indexes(conn)
    missing = [n for n in planned if n not in existing]
    return {
        "rebuilding": True,
        "done": len(planned) - len(missing),
        "total": len(planned),
        "missing": missing,
        "since": state["since"],
    }


# --- dropping and rebuilding ------------------------------------------------ #


def _drop(session: Session, names: list[str]) -> list[str]:
    from src.database.writer import write_lock

    dropped: list[str] = []
    conn = session.connection()  # the connection first, then the gate (writer.connection_first)
    with write_lock():
        existing = _existing_indexes(conn)
        for name in names:
            if name not in existing:
                continue
            index = _index_by_name(name)
            if index is None:
                continue
            conn.execute(DropIndex(index))
            dropped.append(name)
        session.commit()
    if dropped:
        _LOG.info("bulk build dropped %d index(es): %s", len(dropped), ", ".join(dropped))
    return dropped


def _rebuild_missing(
    session: Session, planned: list[str], *, on_progress: Callable[[int, int], None] | None = None
) -> list[str]:
    """Recreate every planned index the store is missing, ONE AT A TIME.

    Sequential and each in its own transaction on purpose: a single CREATE INDEX over a
    corpus-sized table is already a long write-locked operation, and batching several
    into one transaction would hold the gate for their sum while making a crash lose all
    of them instead of the one in flight.

    THE SORT STAYS IN MEMORY (R825 point 4). A CREATE INDEX sorts every key of the table,
    and with ``temp_store=FILE`` SQLite spills that sort to temporary files that SQLCipher
    does NOT encrypt: measured on SQLCipher 4.20.0 community, an encrypted store's index
    build over 1.5 M rows of marker text left the marker in plaintext in 15 of 16 reads of
    the unlinked sorter files (up to 37 MB each), and none with ``temp_store=MEMORY``. Every
    app connection already sets MEMORY (src/database/session.py); it is set again here,
    on the connection that runs the build, so no future change to the connection defaults
    can send an index build's plaintext keys to disk. The caller that opens a window checks
    the memory first (:func:`drain_window_plan`).

    ``on_progress(present, total)`` is told after each index, counted from the store.
    """
    from src.database.writer import write_lock

    created: list[str] = []
    for name in planned:
        index = _index_by_name(name)
        if index is None:
            _LOG.warning("bulk build cannot rebuild unknown index %s", name)
            continue
        conn = session.connection()  # the connection first, then the gate: the commit below gave the last one back
        with write_lock():
            if name in _existing_indexes(conn):
                continue
            conn.exec_driver_sql("PRAGMA temp_store=MEMORY")
            conn.execute(CreateIndex(index))
            session.commit()
        created.append(name)
        _LOG.info("bulk build rebuilt %s (%d/%d)", name, len(created), len(planned))
        if on_progress is not None:
            try:
                present = _existing_indexes(session.connection())
                on_progress(sum(1 for n in planned if n in present), len(planned))
            except Exception as exc:  # noqa: BLE001 - a progress line never stops a rebuild
                _LOG.debug("bulk build progress report failed (%s)", type(exc).__name__)
    return created


@contextmanager
def bulk_index_window(
    session: Session, *, keep: Iterable[str] = (), reason: str = ""
) -> Iterator[list[str]]:
    """Drop the droppable indexes for the duration, then rebuild them.

    ``keep`` is explicit and has no safe default beyond "keep nothing extra": a caller
    that DELETEs per article MUST pass ``{ARTICLE_DELETE_INDEX}``, because without it each
    delete scans the whole mention table. Guessing that on the caller's behalf is how a
    performance change becomes a catastrophic one.

    The rebuild runs in a ``finally``, so an exception inside the window does not leave
    the store stripped. If the rebuild itself fails, the marker STAYS and the boot heal
    finishes the job -- the failure modes all converge on "an index is missing and
    something durable knows it".
    """
    planned = droppable_indexes(keep=keep)
    if not planned:
        yield []
        return
    open_state(session, planned, now=None)
    _LOG.info("bulk build window open (%s): %d index(es)", reason or "no reason given", len(planned))
    try:
        dropped = _drop(session, planned)
        yield dropped
    finally:
        try:
            _rebuild_missing(session, planned)
            conn = session.connection()
            if not [n for n in planned if n not in _existing_indexes(conn)]:
                close_state(session)
            else:
                _LOG.warning("bulk build left index(es) missing; the boot heal will finish them")
        except Exception as exc:  # noqa: BLE001 - the marker outliving us is the recovery path
            log_failure(_LOG, "bulk build rebuild failed; marker left open for the heal", exc, level=logging.WARNING)


# --- the boot self-heal ----------------------------------------------------- #


def heal_bulk_build(engine: Engine, *, inline: bool = True) -> list[str]:
    """Finish an interrupted bulk build. Returns the indexes created.

    ``inline=False`` (what ``init_db`` passes since R825 (b)) builds NOTHING: it reads the marker and logs
    what is owed, and the background heal (:func:`start_heal`, started by the boot sequence's re-index step)
    rebuilds it with its progress shown and its memory checked.

    This is the half that makes R23's live-store choice survivable. It exists because
    ``maintenance.ensure_hot_indexes`` covers only 4 of the 14 droppable indexes -- the
    other 10 are created by ``create_all``/alembic, neither of which adds an index to an
    existing table, so without this a crash mid-rebuild loses them for good.

    Idempotent and cheap when nothing is wrong: one ``derived_meta`` read, and no DDL at
    all unless an index the marker named is genuinely absent.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        state = read_state(session)
        if state is None:
            return []
        planned = list(state["planned"])
        if not planned:
            # An unreadable marker reports OPEN with no planned set; there is nothing to
            # create from that, and inventing the full droppable set could recreate an
            # index a future caller deliberately retired.
            _LOG.warning("bulk-build marker present but unusable; not inventing a plan")
            return []
        if not inline:
            from src.utils.interrupts import kept

            present = _existing_indexes(session.connection())
            missing = kept(planned, lambda n: n not in present)  # a frame of its own: init_db reaches this (tests/test_loop_heads_reach.py)
            _LOG.warning(
                "a bulk build is open: %d keyword index(es) owed, rebuilt in the background after the start-up checks",
                len(missing),
            )
            return []
        created = _rebuild_missing(session, planned)
        conn = session.connection()
        if not kept(planned, lambda n: n not in _existing_indexes(conn)):  # a frame of its own: src/utils/interrupts.py
            close_state(session)
        if created:
            _LOG.warning(
                "boot heal finished an interrupted bulk build: recreated %d index(es): %s",
                len(created),
                ", ".join(created),
            )
        return created
    finally:
        session.close()


# --- the post-import drain's span (R825, D46 (a)) and the background heal --- #
#
# R825 (2026-11-24, row 407, R824 step 2) gives the window its caller: ONE exclusive run of the
# post-import re-index drain (``backup_v2._reindex_resume_worker``), opened only when that run's
# backlog is a large enough share of the corpus, and only when the rebuild's sort fits in memory.
# Nothing else opens it: an update never rebuilds anything, and the window never opens outside the
# drain. A later segment seal (D47, R96) replaces it.
#
# THE HEAL MOVED OUT OF ``init_db`` (R825 (b)). The window's indexes are rebuilt in the background,
# by :data:`HEAL_JOB` (a task-manager job with "rebuilding the keyword indexes: N of M"), never as a
# CREATE INDEX inside the call that opens the database: reads stay correct while they are missing,
# because the unique indexes and ``ix_mention_article`` are never dropped, so a missing index makes a
# read slower and never different. The marker stays until every planned index is present.

#: What the drain keeps besides the unique indexes: ``index_article`` deletes and reads per article.
#: The when/where/who tables need nothing more: each has a unique constraint leading with
#: ``article_id`` (``uq_amd_article_date``, ``ix_amp_article_place``, ``ix_ae_article_name_class``).
DRAIN_KEEP: tuple[str, ...] = (ARTICLE_DELETE_INDEX,)

#: The share a drain run must add before the window opens: the mention rows its backlog will write (the
#: backlog articles at the corpus's own mentions per article) against the mention rows the store holds. MEASURED, see
#: ``scripts/bench_bulk_window.py`` and the PR of row 407: on an encrypted
#: store of 2,000,000 indexed mention rows (4 cores, 2026-11-24), adding N rows live against drop + insert +
#: rebuild took 20.1 s vs 30.6 s at N = 50k (2.5%), 31.2 vs 31.5 s at 80k (4%, the break-even), 39.8 vs 34.4 s
#: at 100k (5%), 123.7 vs 42.6 s at 300k (15%) and 418.9 vs 65.6 s at 1M (50%). 5% is the first measured
#: share the window WON, so below it the drain keeps the live indexes and claims no speed-up.
DRAIN_WINDOW_MIN_FRACTION: float = 0.05

#: Memory the sort of the widest dropped index holds per mention row, under ``temp_store=MEMORY``
#: (each index is built on its own, so the widest one is the peak). Measured: the
#: widest rebuild (``ix_mention_covering``) peaked 128 MB above its process's baseline at 2.05M rows, 142 MB at
#: 2.3M and 186 MB at 3M, the connection's 64 MiB page cache included, i.e. about 62 bytes a row in all and
#: about 41 bytes a row for the sort itself. 96 keeps more than twice the sort's measured need.
RAM_BYTES_PER_MENTION: int = 96

#: Free bytes asked per mention row on the database's volume for the rebuild: every dropped index
#: goes to the write-ahead log, then into the file. Measured: the
#: eight dropped mention indexes hold 165 bytes a row (the store VACUUMed with and without them, 300k and
#: 20k rows alike). A rebuild writes each index to the write-ahead log before the file, so 400 covers all of
#: them plus the largest one's log copy, with room.
DISK_BYTES_PER_MENTION: int = 400

#: Mentions per article when the corpus has none yet to measure it by (~98, measured on main for
#: REPORT-2: 2,000 synthetic 690-word articles).
MENTIONS_PER_ARTICLE_FALLBACK = 98

HEAL_JOB_KIND = "keyword-indexes"
HEAL_LABEL = "Rebuilding the keyword indexes"
#: The task-manager line while the indexes are rebuilt (keyed x12).
FRAME_REBUILDING = "rebuilding the keyword indexes: {index} of {total}"
#: The line when the rebuild waits, naming only what was short (keyed x12; whole MB).
_WAIT_TAIL = " Search stays correct but slower; the app tries again at its next start."
FRAME_WAITING_MEMORY = (
    "The keyword indexes were not rebuilt yet: there is not enough free memory ({free} MB free, about {needed} MB needed)."
    + _WAIT_TAIL
)
FRAME_WAITING_DISK = (
    "The keyword indexes were not rebuilt yet: there is not enough free disk space ({free} MB free, about {needed} MB needed)."
    + _WAIT_TAIL
)
FRAME_WAITING_BOTH = (
    "The keyword indexes were not rebuilt yet: there is not enough free memory ({ram_free} MB free, about {ram_needed} MB "
    "needed) and not enough free disk space ({disk_free} MB free, about {disk_needed} MB needed)." + _WAIT_TAIL
)
FRAMES_WAITING = (FRAME_WAITING_MEMORY, FRAME_WAITING_DISK, FRAME_WAITING_BOTH)


def mention_rows_bound(session: Session) -> int:
    """The largest mention id: an upper bound on the rows, read from the primary key without touching a row."""
    return int(session.execute(text("SELECT COALESCE(MAX(id), 0) FROM keyword_mentions")).scalar() or 0)


def rebuild_preflight(session: Session, rows: int) -> dict:
    """Is there room to rebuild the dropped indexes over ``rows`` mention rows? The same two readings as the
    article-list build (``database/article_indexes.preflight``): free space on the database's volume, and the
    memory available against the sort plus the memory guard's floor. ``sufficient`` is ``None`` when neither
    figure could be read. Never uses a temporary file (see :func:`_rebuild_missing`)."""
    import os

    from src.database.article_indexes import _available_ram_bytes, _floor_bytes, _free

    rows = max(0, int(rows))
    ram_needed = rows * RAM_BYTES_PER_MENTION
    disk_needed = rows * DISK_BYTES_PER_MENTION
    floor = _floor_bytes()
    db_path = getattr(getattr(session.get_bind(), "url", None), "database", None)
    free = _free((os.path.dirname(os.path.abspath(db_path)) if db_path else None) or ".")
    available = _available_ram_bytes()
    out: dict = {
        "rows": rows, "ram_needed_bytes": ram_needed, "ram_floor_bytes": floor, "ram_available_bytes": available,
        "disk_needed_bytes": disk_needed, "disk_free_bytes": free,
    }
    if free is None and available is None:
        out["sufficient"] = None
        return out
    short: list[str] = []
    if free is not None and free < disk_needed:
        short.append("database")
    if available is not None and available < ram_needed + floor:
        short.append("memory")
    out["sufficient"] = not short
    if short:
        out["short_on"] = short
    return out


def waiting_line(room: dict):
    """The task-manager line for a rebuild that waits: a ``Framed`` naming only the reading(s) that fell short,
    in whole MB (the need rounded up)."""
    from src.jobs.background import Framed

    short = set(room.get("short_on", []))

    def mb(b) -> int:
        return int(b or 0) // 1_000_000

    def up(b) -> int:
        return -(-int(b or 0) // 1_000_000)

    ram = {"free": mb(room.get("ram_available_bytes")), "needed": up(int(room.get("ram_needed_bytes") or 0) + int(room.get("ram_floor_bytes") or 0))}
    disk = {"free": mb(room.get("disk_free_bytes")), "needed": up(room.get("disk_needed_bytes"))}
    if short >= {"memory", "database"}:
        frame, values = FRAME_WAITING_BOTH, {
            "ram_free": ram["free"], "ram_needed": ram["needed"], "disk_free": disk["free"], "disk_needed": disk["needed"],
        }
    elif "database" in short:
        frame, values = FRAME_WAITING_DISK, disk
    else:
        frame, values = FRAME_WAITING_MEMORY, ram
    return Framed(frame.format(**values), frame, **values)


def drain_window_plan(session: Session, backlog_articles: int) -> dict:
    """Whether one drain run opens the window, and why (R825). ``open`` is True only when the mention rows
    the run's backlog will write are at least :data:`DRAIN_WINDOW_MIN_FRACTION` of the mention rows AND the rebuild's memory and
    space were READ and suffice: opening is optional, so an unknown figure declines it (the heal, which
    has no choice, goes ahead on an unknown)."""
    backlog = max(0, int(backlog_articles))
    out: dict = {"open": False, "backlog_articles": backlog, "min_fraction": DRAIN_WINDOW_MIN_FRACTION}
    if backlog == 0:
        out["reason"] = "no backlog"
        return out
    if read_state(session) is not None:
        out["reason"] = "a bulk build is already open"
        return out
    rows = mention_rows_bound(session)
    # The articles already indexed: every article but the backlog (counted from the articles, not the stamps,
    # which an install older than R24 lacks for most of its corpus and would make a small backlog look large).
    indexed = max(int(session.execute(text("SELECT COUNT(*) FROM articles")).scalar() or 0) - backlog, 0)
    per_article = (rows / indexed) if (rows and indexed) else MENTIONS_PER_ARTICLE_FALLBACK
    projected = int(backlog * per_article)
    # The projected new mention rows against the mention rows the store holds (the bench's N / E). None when it
    # holds none yet: the whole corpus is the backlog (and None, unlike inf, survives JSON).
    fraction = round(projected / rows, 4) if rows else None
    out.update(mention_rows_bound=rows, indexed_articles=indexed, fraction=fraction, projected_rows=projected)
    if fraction is not None and fraction < DRAIN_WINDOW_MIN_FRACTION:
        out["reason"] = "backlog below the break-even share"
        return out
    room = rebuild_preflight(session, rows + projected)
    out["preflight"] = room
    if room.get("ram_available_bytes") is None or room.get("disk_free_bytes") is None:
        # Opening is optional: BOTH readings must have been made (the heal, which has no choice, goes ahead on one).
        out["reason"] = "memory or disk not measured"
        return out
    if room.get("sufficient") is not True:
        out["reason"] = "not enough memory or disk"
        return out
    out["open"] = True
    out["reason"] = "open"
    return out


def open_window(session: Session, *, keep: Iterable[str] = DRAIN_KEEP, reason: str = "") -> list[str]:
    """Record the marker (committed first), then drop. Returns the planned set; the caller ends the window
    with :func:`finish_window`, or leaves it to the heal."""
    planned = droppable_indexes(keep=keep)
    if not planned:
        return []
    open_state(session, planned, now=None)
    _LOG.info("bulk build window open (%s): %d index(es)", reason or "no reason given", len(planned))
    _drop(session, planned)
    return planned


def finish_window(session: Session, *, on_progress: Callable[[int, int], None] | None = None) -> dict:
    """Rebuild whatever the open marker names and the store lacks, then clear the marker. Never raises.

    ``complete`` is True only when no marker is left. When the memory or the space for the sort is short,
    nothing is built, the marker stays (``waiting`` carries the figures) and the indexes are rebuilt later:
    an index is never claimed present that is not, and a sort is never sent to a temporary file."""
    try:
        state = read_state(session)
        if state is None:
            return {"complete": True, "created": []}
        planned = list(state["planned"])
        if not planned:
            return {"complete": False, "created": [], "reason": "marker present but unusable"}
        missing = [n for n in planned if n not in _existing_indexes(session.connection())]
        if missing:
            room = rebuild_preflight(session, mention_rows_bound(session))
            if room.get("sufficient") is False:
                _LOG.warning("keyword indexes not rebuilt yet: short on %s; the marker stays", ", ".join(room["short_on"]))
                return {"complete": False, "created": [], "missing": missing, "waiting": room}
            if on_progress is not None:
                on_progress(len(planned) - len(missing), len(planned))  # the line shows from the first index, not after it
        created = _rebuild_missing(session, planned, on_progress=on_progress)
        left = [n for n in planned if n not in _existing_indexes(session.connection())]
        if left:
            return {"complete": False, "created": created, "missing": left}
        close_state(session)
        return {"complete": True, "created": created}
    except Exception as exc:  # noqa: BLE001 - the marker outliving us is the recovery path
        log_failure(_LOG, "keyword index rebuild failed; the marker stays for the heal", exc, level=logging.WARNING)
        return {"complete": False, "created": [], "reason": type(exc).__name__}


def _storage_guard_engaged() -> bool:
    """The storage guard (R398) holds: a rebuild writes every index through the write-ahead log, so it waits, the marker
    kept, as the drain's batches do. An unreadable guard is not a reason to wait."""
    try:
        from src.scheduler.storage_guard import storage_guard

        return bool(storage_guard.engaged_now())
    except Exception:  # noqa: BLE001
        return False


def owed_waiting_line(engine: Engine | None = None):
    """The waiting line for an open window that NOTHING is rebuilding now, else None: read from the store and the
    same two readings each time, never remembered from a finished job (a finished job's row is not listed, so a
    line written only to it would vanish as it was written). For the task manager's own row. Never raises."""
    try:
        from src.jobs.background import get_job

        for kind in (HEAL_JOB_KIND, "reindex-resume"):
            job = get_job(kind)
            if job is not None and job.status().get("state") == "running":
                return None
        if engine is None:
            from src.database import session as _s

            engine = _s.engine
        from sqlalchemy.orm import sessionmaker

        s = sessionmaker(bind=engine, future=True)()
        try:
            state = read_state(s)
            if state is None or not state["planned"]:
                return None
            if not [n for n in state["planned"] if n not in _existing_indexes(s.connection())]:
                return None
            room = rebuild_preflight(s, mention_rows_bound(s))
        finally:
            s.close()
        return waiting_line(room) if room.get("sufficient") is False else None
    except Exception as exc:  # noqa: BLE001 - the task manager never fails for a row
        log_failure(_LOG, "could not read the keyword index window for the task manager", exc, level=logging.INFO)
        return None


def _heal_worker(ctx, **_kw) -> dict:
    from src.database.session import session_scope
    from src.jobs.background import Framed

    def _progress(done: int, total: int) -> None:
        ctx.set_progress(done=done, total=total, detail=Framed(
            FRAME_REBUILDING.format(index=min(done + 1, total), total=total), FRAME_REBUILDING,
            index=min(done + 1, total), total=total,
        ))

    from src.database.corpus_lease import corpus_lease

    # Under the corpus lease, as every corpus writer: a restore's swap waits for the rebuild rather than landing
    # under it (the restore also refuses while this job runs: it is a writer it may not stop).
    with corpus_lease(HEAL_JOB_KIND), session_scope() as session:
        state = read_state(session)
        if state is None:
            return {"complete": True, "created": []}
        if _storage_guard_engaged():
            return {"complete": False, "created": [], "reason": "storage guard engaged"}
        out = finish_window(session, on_progress=_progress)
    if out.get("waiting"):
        ctx.set_progress(detail=waiting_line(out["waiting"]))
    return out


def _heal_job():
    from src.jobs.background import BackgroundJob, register_job

    return register_job(BackgroundJob(HEAL_JOB_KIND, HEAL_LABEL, _heal_worker, is_writer=True, cancellable=False))


HEAL_JOB = _heal_job()


def start_heal(engine: Engine | None = None) -> str:
    """Start the background heal when a marker is open. Returns ``started``, ``running``, ``drain`` (the
    re-index drain runs and rebuilds them at its end), ``none`` (no marker) or ``failed``. Never raises, never builds in the calling thread."""
    try:
        if engine is None:
            from src.database import session as _s

            engine = _s.engine
        from sqlalchemy.orm import sessionmaker

        s = sessionmaker(bind=engine, future=True)()
        try:
            if read_state(s) is None:
                return "none"
        finally:
            s.close()
        if HEAL_JOB.status().get("state") == "running":
            return "running"
        from src.jobs.background import get_job

        drain = get_job("reindex-resume")
        if drain is not None and drain.status().get("state") == "running":
            # The drain rebuilds an open window's indexes at its own end (it adopts a marker it finds at its
            # start, and asks the store again at its end): two rebuilds at once would only contend.
            return "drain"
        HEAL_JOB.start()
        return "started"
    except Exception as exc:  # noqa: BLE001 - the marker stays; the next start asks again
        log_failure(_LOG, "could not start the keyword index heal", exc, level=logging.WARNING)
        return "failed"
