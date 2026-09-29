"""The READ seam over the derived keyword rows (segmented-index step 0, ruling R96).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/design/SEGMENTED_DERIVED_INDEX_2026-09-24.md`` §3.3 / §5 step 0: every READER of
the derived tables goes through one view, so that when the derived rows are split into a
head and sealed segments (steps 1-4) the readers change in ONE place instead of in
fifteen. Today the view covers exactly the current table, so it is behaviour-neutral by
construction; the point of building it first is that a rename behind a view is provable
(the differential test in ``tests/test_derived_read_seam.py`` reads the same rows both
ways) while a rename of ~500 references is not.

WHAT THIS MODULE OWNS
  * :data:`MENTIONS_VIEW` -- the SQL view, ``keyword_mentions_all``, over ``keyword_mentions``;
  * :func:`ensure_derived_views` -- creates it, or re-creates it when the table's column set
    has moved on. Called from ``init_db`` (the boot path every install takes, alembic or
    not), and from an ``after_create`` listener so a ``Base.metadata.create_all`` database
    (every test, every fresh install) has it too. Idempotent; one ``sqlite_master`` read
    when nothing changed;
  * :class:`KeywordMentionRead` -- a READ-ONLY ORM mapping of the view, on a metadata of its
    own so ``create_all`` never mistakes it for a table.

WRITERS STAY ON THE TABLE. ``index_article``, the merge, the bulk build and the prune write
``keyword_mentions``; a write through the view is refused by SQLite. That is the design's
"head": today's table is the one mutable segment.

WHY THE VIEW LISTS ITS COLUMNS. ``SELECT *`` in a view is expanded when the view is created,
so it would silently hold the old column set after a migration adds one -- and a later
column drop or rename (row B's country-code migration touches this very table) fails while
a view names the column. Listing the columns from the model keeps the view and the table in
step, and :func:`ensure_derived_views` re-creates it when they part. A migration that
DROPS or RENAMES a ``keyword_mentions`` column must drop the view first; the next boot
re-creates it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import DDL, Column, Table, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped

from src.database.models import KeywordMention

_LOG = logging.getLogger(__name__)

MENTIONS_VIEW = "keyword_mentions_all"


def _column_names() -> list[str]:
    return [c.name for c in KeywordMention.__table__.columns]


def mentions_view_sql() -> str:
    """The exact ``CREATE VIEW`` for the current column set (also what a stale view is
    compared against, whitespace-insensitively)."""
    cols = ", ".join(_column_names())
    return f"CREATE VIEW {MENTIONS_VIEW} AS SELECT {cols} FROM {KeywordMention.__tablename__}"


def _norm(sql: str | None) -> str:
    return " ".join((sql or "").split()).lower()


def ensure_derived_views(bind: Engine | Connection) -> str:
    """Create ``keyword_mentions_all``, or re-create it when its column list is stale.

    Returns ``"ok"`` (already current), ``"created"``, ``"recreated"`` or ``"skipped"``
    (not SQLite, or the base table does not exist yet). Never raises: a failure here must
    not stop the app booting, and is logged."""
    try:
        conn_ctx = bind.begin() if isinstance(bind, Engine) else _NullCtx(bind)
        with conn_ctx as conn:
            if conn.dialect.name != "sqlite":
                return "skipped"
            rows = conn.execute(
                text("SELECT type, name, sql FROM sqlite_master WHERE name IN (:t, :v)"),
                {"t": KeywordMention.__tablename__, "v": MENTIONS_VIEW},
            ).fetchall()
            have = {str(r[1]): (str(r[0]), r[2]) for r in rows}
            if KeywordMention.__tablename__ not in have:
                return "skipped"
            want = mentions_view_sql()
            current = have.get(MENTIONS_VIEW)
            if current and current[0] == "view" and _norm(current[1]) == _norm(want):
                return "ok"
            if current:
                conn.execute(text(f"DROP VIEW IF EXISTS {MENTIONS_VIEW}"))
            conn.execute(text(want))
            return "recreated" if current else "created"
    except Exception:  # noqa: BLE001 - a read seam must never stop the app booting
        _LOG.warning("could not ensure the derived-row views", exc_info=True)
        return "skipped"


class _NullCtx:
    """Use an already-open Connection as-is (the caller owns its transaction)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def __enter__(self) -> Connection:
        return self._conn

    def __exit__(self, *exc: object) -> None:
        return None


# A ``create_all`` database (every test, every fresh install) gets the view the moment its
# table is created; the ``IF NOT EXISTS`` form makes a second listener call harmless. Existing
# databases are covered by ``ensure_derived_views`` at boot.
event.listen(
    KeywordMention.__table__,
    "after_create",
    DDL(mentions_view_sql().replace("CREATE VIEW", "CREATE VIEW IF NOT EXISTS", 1)).execute_if(
        dialect="sqlite"
    ),
)


class ReadBase(DeclarativeBase):
    """A declarative base with a metadata of its own: a view must never be in
    ``Base.metadata``, or ``create_all`` would try to make a TABLE of the same name."""


_mentions_read_table = Table(
    MENTIONS_VIEW,
    ReadBase.metadata,
    *[Column(c.name, c.type, primary_key=c.primary_key) for c in KeywordMention.__table__.columns],
)


class KeywordMentionRead(ReadBase):
    """READ-ONLY mapping of ``keyword_mentions_all``. Same column names and types as
    :class:`src.database.models.KeywordMention`, so a reader changes its import and
    nothing else. Never ``add()`` one: SQLite refuses a write to a view."""

    __table__ = _mentions_read_table

    # Typed handles for the checker; the columns themselves come from ``__table__`` above and
    # ``tests/test_derived_read_seam.py`` holds this list equal to ``KeywordMention``'s.
    id: Mapped[int]
    keyword_id: Mapped[int]
    article_id: Mapped[int]
    count: Mapped[int]
    first_offset: Mapped[int | None]
    observed_on: Mapped[date | None]
    country: Mapped[str | None]
    city: Mapped[str | None]
    language: Mapped[str | None]
    source_id: Mapped[int | None]
    extractor: Mapped[str | None]
    created_at: Mapped[datetime | None]
