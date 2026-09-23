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
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, DropIndex

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
    except Exception:  # noqa: BLE001 - an unreadable marker cannot prove the store is whole
        _LOG.warning("bulk-build marker unreadable; treating as OPEN", exc_info=True)
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
    from src.database.writer import write_lock

    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    payload = "\n".join([stamp, *sorted(planned)])
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
    from src.database.writer import write_lock

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
    with write_lock():
        conn = session.connection()
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


def _rebuild_missing(session: Session, planned: list[str]) -> list[str]:
    """Recreate every planned index the store is missing, ONE AT A TIME.

    Sequential and each in its own transaction on purpose: a single CREATE INDEX over a
    corpus-sized table is already a long write-locked operation, and batching several
    into one transaction would hold the gate for their sum while making a crash lose all
    of them instead of the one in flight.
    """
    from src.database.writer import write_lock

    created: list[str] = []
    for name in planned:
        index = _index_by_name(name)
        if index is None:
            _LOG.warning("bulk build cannot rebuild unknown index %s", name)
            continue
        with write_lock():
            conn = session.connection()
            if name in _existing_indexes(conn):
                continue
            conn.execute(CreateIndex(index))
            session.commit()
        created.append(name)
        _LOG.info("bulk build rebuilt %s (%d/%d)", name, len(created), len(planned))
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
        except Exception:  # noqa: BLE001 - the marker outliving us is the recovery path
            _LOG.warning("bulk build rebuild failed; marker left open for the heal", exc_info=True)


# --- the boot self-heal ----------------------------------------------------- #


def heal_bulk_build(engine: Engine) -> list[str]:
    """Finish an interrupted bulk build at boot. Returns the indexes created.

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
        created = _rebuild_missing(session, planned)
        conn = session.connection()
        if not [n for n in planned if n not in _existing_indexes(conn)]:
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
