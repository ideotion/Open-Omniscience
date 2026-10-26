"""A source is identified by ``(domain, feed_key)``: the schema step (row J, S05-10).

``sources.domain`` was UNIQUE, which made one registrable domain hold exactly one feed and left 475 catalogue
entries (BBC's language services, DW's, the lean-tagged spectrum catalogue) unregisterable. The key becomes
``UNIQUE (domain, feed_key)`` -- ``domain`` stays part of the identity (52 feeds are already carried by several
domains' separate rows, so a key on the feed alone could not be installed on a real store without merging rows).

SQLite cannot drop a UNIQUE constraint, so this is a table rebuild, and the rebuild is the dangerous part:
``articles``, ``source_metadata``, ``source_group_association`` and others reference ``sources.id``, several with
``ON DELETE CASCADE``, and the app keeps ``PRAGMA foreign_keys=ON``. A ``DROP TABLE sources`` with enforcement ON
deletes the children of every row (SQLite performs an implicit ``DELETE FROM`` first), which is every article of
the corpus. So the rebuild is SQLite's documented twelve-step procedure -- enforcement OFF *outside* a transaction
(inside one the pragma is silently ignored, so the step reads it back and refuses if it did not take), one
transaction around create, copy, drop, rename and index creation, the same ``id`` on every row, and a check that
the id set is identical before anything is dropped. A child can only dangle if a parent id moved; the ids do not.

``ensure_source_composite_key`` is the boot self-heal (additive column and backfill first, then the rebuild) and
``upgrade_sources_to_composite_key`` is what the Alembic revision calls, so a staged copy and a live store take
the same path.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateIndex, CreateTable

from src.database.feed_key import feed_key
from src.database.models import SOURCE_OUTLET_ID_TRIGGERS, Source
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

_NEW = "sources_composite_new"
_SOURCES = cast(Table, Source.__table__)  # the declarative ``__table__`` is typed as a bare FromClause; it is this Table
_OLD_DOMAIN_INDEX = "idx_source_domain"


class SourceIdentityRefused(RuntimeError):
    """The rebuild did not run, and nothing was changed. The text names what was checked; never a row's content."""


def source_identity_state(conn: Connection) -> str:
    """``composite`` (UNIQUE on exactly domain+feed_key), ``legacy`` (UNIQUE on domain alone),
    ``absent`` (no sources table) or ``unreadable`` (neither unique shape can be told)."""
    if conn.dialect.name != "sqlite":
        return "unreadable"
    if not conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'").fetchone():
        return "absent"
    shapes: set[tuple[str, ...]] = set()
    for row in conn.exec_driver_sql("PRAGMA index_list(sources)").fetchall():
        name, unique = row[1], row[2]
        if not unique:
            continue
        cols = tuple(r[2] for r in conn.exec_driver_sql(f'PRAGMA index_info("{name}")').fetchall())  # nosec B608 - an index name read from sqlite_master
        shapes.add(cols)
    if ("domain", "feed_key") in shapes and ("domain",) not in shapes:
        return "composite"
    if ("domain",) in shapes:
        return "legacy"
    return "unreadable"


def composite_key_active(conn: Connection) -> bool:
    """Whether the store can hold several sources of one domain. A caller that creates a second feed of a domain
    must ask; a store the rebuild has not reached keeps today's one-feed-per-domain behaviour."""
    return source_identity_state(conn) == "composite"


def _columns(conn: Connection, table: str) -> list[str]:
    return [r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()]  # nosec B608 - a fixed table name


def add_feed_key_column(conn: Connection) -> bool:
    """Additive and always safe: the column, then every row's key from its own ``rss_url``. True if it was added."""
    if "feed_key" in _columns(conn, "sources"):
        return False
    conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN feed_key VARCHAR(500) NOT NULL DEFAULT ''")
    return True


def _owns_the_transaction(conn: Connection) -> bool:
    """True when this code may BEGIN and COMMIT on ``conn``: the DRIVER is in true autocommit with no transaction open (the boot
    path, where every UPDATE would otherwise be its own commit: 10.5 s encrypted for the 6,400 sources of the shipped catalogue,
    0.47 s in one). In any other mode the caller owns the commit: pysqlite opens its implicit transaction at the first DML, which
    is the caller's, so nothing is begun or committed here. The driver's ``in_transaction`` alone is not the test: pysqlite sets
    it only at the first DML, so a caller inside a SQLAlchemy ``engine.begin()`` that has only read would be taken for idle and
    have its work committed under it (the independent read's L2); a caller in that state is not in autocommit."""
    dbapi = conn.connection.dbapi_connection
    return not getattr(dbapi, "in_transaction", False) and (
        getattr(dbapi, "isolation_level", "") is None or getattr(dbapi, "autocommit", None) is True
    )


def backfill_feed_keys(conn: Connection) -> int:
    """Set every row's ``feed_key`` from its ``rss_url``; returns the rows whose key changed."""
    rows = conn.exec_driver_sql("SELECT id, rss_url, feed_key FROM sources").fetchall()
    changed = [(feed_key(r[1]), r[0]) for r in rows if (r[2] or "") != feed_key(r[1])]
    if not changed:
        return 0
    own = _owns_the_transaction(conn)
    if own:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        for key, sid in changed:
            conn.exec_driver_sql("UPDATE sources SET feed_key = ? WHERE id = ?", (key, sid))
    except BaseException:
        if own:
            conn.exec_driver_sql("ROLLBACK")
        raise
    if own:
        conn.exec_driver_sql("COMMIT")
    return len(changed)


def _names_not_in(names: list[str], other: list[str]) -> list[str]:
    """``[n for n in names if n not in other]``. A function of its own because a comprehension is inlined into its caller on CPython 3.13 and the
    back-edge of its filter-skip then sits outside the exception table of the ``try`` in ``upgrade_sources_to_composite_key`` (R205): an
    interrupt there would skip the ``finally`` that turns foreign-key enforcement back on."""
    return [n for n in names if n not in other]


def _names_in(names: list[str], other: list[str]) -> list[str]:
    """``[n for n in names if n in other]``, for the same reason as :func:`_names_not_in`."""
    return [n for n in names if n in other]


def _required_columns_without_default(new_table: Table, old_cols: list[str]) -> list[str]:
    """The columns the new table needs that the old one lacks and that have no default, for the same reason as :func:`_names_not_in`."""
    return [c.name for c in new_table.columns
            if c.name not in old_cols and not c.nullable and c.server_default is None and c.default is None]


def _refuse_if_unfit(new_table: Table, cols: list[str]) -> None:
    """Refuse, naming it, a ``sources`` whose columns the rebuild cannot carry: one this build does not know (copying only the shared
    columns would drop it silently, and local data never gives way, R100) or one the new table needs and ``cols`` lacks."""
    unknown = _names_not_in(cols, [c.name for c in new_table.columns])
    if unknown:
        raise SourceIdentityRefused(f"sources holds columns this build does not know: {', '.join(unknown)}; not dropping them")
    missing = _required_columns_without_default(new_table, cols)
    if missing:
        raise SourceIdentityRefused(f"sources lacks columns the new table needs with no default: {', '.join(missing)}")


def _extra_schema_objects(conn: Connection) -> list[tuple[str, str]]:
    """The indexes and triggers of ``sources`` the model does not declare, to be recreated after the rebuild, for the same reason as
    :func:`_names_not_in`."""
    return [
        (n, s) for n, s in conn.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name='sources' AND sql IS NOT NULL"
            " AND type IN ('index','trigger')").fetchall()
        if n not in {ix.name for ix in _SOURCES.indexes}
    ]


def upgrade_sources_to_composite_key(conn: Connection, *, commit_open_transaction: bool = False) -> dict[str, Any]:
    """Rebuild ``sources`` with ``UNIQUE (domain, feed_key)``. ``conn`` must have no transaction open: it is refused,
    never committed on the caller's behalf, unless ``commit_open_transaction`` -- which only the Alembic revision
    passes: an earlier revision in the same chain may have run DML (Python's sqlite3 opens a transaction for it and
    SQLite's DDL is not transactional there), and committing that work first is what lets a restore of an old backup
    reach this step at all. Returns ``{"state", "rows_before", "rows_after"}``; raises :class:`SourceIdentityRefused`
    (nothing changed) rather than risk the children of ``sources``."""
    state = source_identity_state(conn)
    if state == "absent":
        return {"state": "absent", "rows_before": 0, "rows_after": 0}
    if state == "composite":
        n: int = conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one()
        return {"state": "composite", "rows_before": n, "rows_after": n}
    if state != "legacy":
        raise SourceIdentityRefused("the unique key of sources is neither the old nor the new shape; not touching it")

    dbapi = conn.connection.dbapi_connection
    if dbapi is None:
        raise SourceIdentityRefused("the connection holds no driver connection; not rebuilding sources")
    if getattr(dbapi, "in_transaction", False) and commit_open_transaction:
        dbapi.commit()
    if getattr(dbapi, "in_transaction", False):
        # Not ours to commit, and inside it the pragma below is a silent no-op.
        raise SourceIdentityRefused("a transaction is already open on this connection; not rebuilding sources")
    # Every refusal that can be decided from the schema is decided HERE, before anything is changed: the view is still in place, the
    # pragma untouched, and a refused store is exactly as it was found. ``feed_key`` is added below, so it is counted as present now.
    new_table = _SOURCES.to_metadata(MetaData(), name=_NEW)
    new_cols = [c.name for c in new_table.columns]
    _refuse_if_unfit(new_table, [*_columns(conn, "sources"), "feed_key"])
    extra = _extra_schema_objects(conn)
    dbapi.create_function("oo_feed_key", 1, feed_key, deterministic=True)
    # Python's sqlite3 opens a transaction on its own before a DML statement; the rebuild owns its BEGIN/COMMIT,
    # so statements run in true autocommit for its duration and the connection's mode is put back after.
    prior_isolation = dbapi.isolation_level
    dbapi.isolation_level = None

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        # Inside a transaction the pragma is a silent no-op, and a DROP TABLE under enforcement cascades.
        dbapi.isolation_level = prior_isolation
        raise SourceIdentityRefused("foreign-key enforcement could not be turned off; not rebuilding sources")
    began = False
    try:
        add_feed_key_column(conn)
        backfill_feed_keys(conn)
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        began = True
        # The read that decides what is copied, taken under the write lock: another writer's ALTER cannot land between it and the
        # copy, so a column added meanwhile (a second process, an older build) is refused here, not left out of the copy. It must also
        # follow the column being added above. A refusal rolls the transaction back like any other failure.
        old_cols = _columns(conn, "sources")
        _refuse_if_unfit(new_table, old_cols)
        copy = _names_in(new_cols, old_cols)
        # Inside the transaction, so that every failure from here on rolls the view back with the rest; a refused or failed rebuild used to
        # leave ``keyword_mentions_all`` dropped for the life of the process (the caller recreates it only after a success).
        conn.exec_driver_sql("DROP VIEW IF EXISTS keyword_mentions_all")
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {_NEW}")
        conn.exec_driver_sql(str(CreateTable(new_table).compile(dialect=conn.dialect)))
        cols = ", ".join(f'"{c}"' for c in copy)
        conn.exec_driver_sql(f'INSERT INTO {_NEW} ({cols}) SELECT {cols} FROM sources ORDER BY id')  # nosec B608 - column names come from the ORM table
        before: int = conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one()
        after: int = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {_NEW}").scalar_one()  # nosec B608 - a fixed name
        lost: int = conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM sources o WHERE NOT EXISTS (SELECT 1 FROM {_NEW} n WHERE n.id = o.id)"  # nosec B608 - a fixed name
        ).scalar_one()
        if before != after or lost:
            raise SourceIdentityRefused(f"the copy did not carry every row ({after} of {before}, {lost} ids missing)")
        conn.exec_driver_sql("DROP TABLE sources")
        conn.exec_driver_sql(f"ALTER TABLE {_NEW} RENAME TO sources")
        for ix in _SOURCES.indexes:
            conn.exec_driver_sql(str(CreateIndex(ix).compile(dialect=conn.dialect)))
        for _name, sql in extra:
            conn.exec_driver_sql(sql)
        conn.exec_driver_sql("COMMIT")
        began = False
    except BaseException:
        # ``in_transaction`` as well as ``began``: after a COMMIT that an interrupt followed there is nothing to roll back, and a ROLLBACK
        # answering "no transaction is active" would replace the interrupt with an OperationalError that boot swallows. An interrupt
        # inside a statement makes SQLAlchemy invalidate the connection (the driver one is closed, which rolls back): there is
        # nothing left to ask, and asking would replace the interrupt with a ProgrammingError.
        if began and not conn.invalidated and dbapi.in_transaction:
            conn.exec_driver_sql("ROLLBACK")
        raise
    finally:
        if not conn.invalidated:
            if began and dbapi.in_transaction:
                # The ROLLBACK above never reached the driver (an interrupt landed first). Leaving it open is not neutral: setting
                # ``isolation_level`` below COMMITS an open transaction on Python 3.13, which would commit a half-finished rebuild.
                dbapi.execute("ROLLBACK")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            dbapi.isolation_level = prior_isolation
    return {"state": "rebuilt", "rows_before": before, "rows_after": after}


def ensure_source_composite_key(engine: Engine) -> dict[str, Any]:
    """Boot self-heal: bring ``sources`` to the composite key. Never raises into boot; a refusal is logged by
    class and the store keeps one feed per domain (``composite_key_active`` says so) until it is fixed."""
    if engine.url.get_backend_name() != "sqlite":
        return {"state": "skipped"}
    try:
        with engine.connect() as probe:
            state = source_identity_state(probe)
        if state in {"absent", "composite"}:
            return {"state": state}
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # Additive and always safe, and done BEFORE the rebuild can refuse: the model reads ``feed_key`` whatever
            # the rebuild decides, so a refused store must still have the column or every query on sources fails.
            add_feed_key_column(conn)
            backfill_feed_keys(conn)
            result = upgrade_sources_to_composite_key(conn)
        from src.database.derived_views import ensure_derived_views

        ensure_derived_views(engine)
        _LOG.info("sources now keyed on (domain, feed): %s rows kept", result.get("rows_after"))
        return result
    except Exception as exc:  # noqa: BLE001 - the boot must go on; the verdict is returned and logged by class
        log_failure(_LOG, "could not move the sources key to (domain, feed)", exc, level=logging.WARNING)
        return {"state": "refused", "error": type(exc).__name__}


_OUTLET_STALE_SQL = (
    "SELECT COUNT(*) FROM sources s WHERE s.outlet_id IS NOT (SELECT MIN(x.id) FROM sources x WHERE x.domain = s.domain)"
)
_OUTLET_HEAL_SQL = (
    "UPDATE sources SET outlet_id = (SELECT MIN(x.id) FROM sources x WHERE x.domain = sources.domain)"
    " WHERE outlet_id IS NOT (SELECT MIN(x.id) FROM sources x WHERE x.domain = sources.domain)"
)


def _trigger_body_matches(stored: str | None, wanted: str) -> bool:
    """Whether the ``CREATE TRIGGER`` text SQLite kept for a trigger is the one this build would make. SQLite stores the statement as written
    minus ``IF NOT EXISTS``, so both sides are compared with whitespace collapsed and that phrase taken out of ``wanted``. Case is kept: the
    body is built by this module and a case-only edit is a change like any other. An unreadable (NULL) stored text does not match."""
    if not stored:
        return False
    normalised = " ".join(wanted.split()).replace("CREATE TRIGGER IF NOT EXISTS ", "CREATE TRIGGER ", 1)
    return " ".join(stored.split()) == normalised


def install_source_outlet_id(conn: Connection) -> dict[str, Any]:
    """R177: the integer ``sources.outlet_id`` and the three triggers that keep it right, on ``conn``.

    Additive and idempotent, and the only schema work the outlet integer needs: ``ADD COLUMN`` (nothing is rebuilt), the
    triggers (``CREATE TRIGGER IF NOT EXISTS``), and ONE ``UPDATE`` that corrects the rows that are wrong -- all of them on
    a store that never had the column, none on a steady boot (the count that finds nothing to do). Its cost scales with the ``sources`` table, never with
    the articles or the mentions: encrypted, alone, median of 7, a steady boot costs 4 ms at 7,000 sources, 65 ms at 70,000 and
    2.0 s at 700,000, and the first install (column, triggers, back-fill) 42 ms, 0.53 s and 8.1 s
    (``plan-row-j/outlet-id-plan-2026-10-17``). Writes ``outlet_id`` and nothing else: no verdict, no catalogue-owned field and no operator edit is
    touched (R100, R167). Returns ``{"added", "triggers", "healed"}`` (``triggers`` counts the triggers WRITTEN: made new, or replaced because the body an older build wrote differs from this build's); ``{"state": "absent"}`` with no sources table."""
    if conn.dialect.name != "sqlite":
        return {"state": "skipped"}
    if not conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'").fetchone():
        return {"state": "absent"}
    added = False
    if "outlet_id" not in _columns(conn, "sources"):
        conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN outlet_id INTEGER")
        added = True
    # The three triggers and the heal are ONE transaction when this code owns it (the boot path runs in autocommit, where each
    # statement would be its own commit): a refusal part-way (SQLITE_BUSY from another process, a full disk) must not leave two
    # triggers and no heal, because a store with some triggers keeps non-NULL values that nothing then corrects, and
    # ``outlets_unhealed`` looks only at NULL rows (the independent read's F1). All or none: none leaves every row NULL, which
    # the gates read exactly. The ADD COLUMN stays outside, in its own commit, since rolling it back would fail every ``Source`` query.
    own = _owns_the_transaction(conn)
    if own:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        have = {
            r[0]: r[1]
            for r in conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='sources'").fetchall()
        }
        made = 0
        for name, sql in SOURCE_OUTLET_ID_TRIGGERS.items():
            if name in have:
                if _trigger_body_matches(have[name], sql):
                    continue
                # a trigger of this name from an older build: ``IF NOT EXISTS`` can never replace it, so a changed body would reach new
                # installs only (audit 0.5.0 item 14). Dropped and re-made inside the same transaction as the heal below, so no write
                # sees the table with a missing trigger; the rows it wrote keep their values and the heal corrects any that are wrong.
                conn.exec_driver_sql(f'DROP TRIGGER "{name}"')  # nosec B608 - a name from SOURCE_OUTLET_ID_TRIGGERS, not input
            conn.exec_driver_sql(sql)
            made += 1
        stale: int = conn.exec_driver_sql(_OUTLET_STALE_SQL).scalar_one()
        if stale:
            conn.exec_driver_sql(_OUTLET_HEAL_SQL)
    except BaseException:
        if own:
            conn.exec_driver_sql("ROLLBACK")
        raise
    if own:
        conn.exec_driver_sql("COMMIT")
    return {"added": added, "triggers": made, "healed": stale}


def ensure_source_outlet_id(engine: Engine) -> dict[str, Any]:
    """Boot self-heal for the outlet integer (R177). Never raises into boot: a refusal is logged by class. If the ADD COLUMN
    itself is refused, every ORM query on ``Source`` fails with "no such column" (as for any self-healed column); if only the
    triggers or the heal are refused, rows stay NULL and a gate reads them exactly (``outlets_unhealed``, then the lowest id of
    the row's own domain) until a later boot corrects them. Runs AFTER ``ensure_source_composite_key``: that rebuild replays any
    trigger the old table held, and this step then finds nothing to add."""
    if engine.url.get_backend_name() != "sqlite":
        return {"state": "skipped"}
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            result = install_source_outlet_id(conn)
        if result.get("added") or result.get("triggers") or result.get("healed"):
            _LOG.info("sources.outlet_id: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001 - the boot must go on; the verdict is returned and logged by class
        log_failure(_LOG, "could not set up sources.outlet_id", exc, level=logging.WARNING)
        return {"state": "refused", "error": type(exc).__name__}
