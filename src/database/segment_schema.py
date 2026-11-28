"""The schema a split-corpus segment file is made with (R826 stage 3b, row 409).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A segment holds the per-article tables (R826 §2): ``articles``, ``keyword_mentions``, the date, place and people rows
(``article_mentioned_dates``, ``article_mentioned_places``, ``article_entities``) and the two stamp tables, with the
article search index and the title index over its own ``articles``. Everything else stays in the shared file.

THE STATEMENTS ARE DERIVED, NEVER TYPED. Each table and index comes from the app's own models (``src.database.models``)
compiled for SQLite, the hot indexes from ``maintenance.HOT_INDEXES``, the two search indexes from ``fts._FTS_DDL`` and
``fts_title._ddl``. A segment therefore has the same columns, defaults and indexes as the shared file's tables, and the
opener's exact-schema check (``segment_open.check_schema``) compares against what these statements make.

FOREIGN KEYS ACROSS FILES ARE DROPPED (no transaction spans two files, R826 §2). A reference from a segment to the shared
file (``articles.source_id`` -> ``sources``, ``keyword_mentions.keyword_id`` -> ``keywords``) cannot be a constraint in
SQLite; :data:`SHARED_REFERENCES` lists every such column, and ``segment_write.insert_rows`` enforces it in code: the
shared row must exist (committed before the segment rows that use it) or the segment write is refused. References inside
the segment (``article_id`` -> ``articles``) stay constraints.

THE DELETE SIDE IS NOT COVERED YET. A shared-file delete (a source removed, a keyword pruned) cascades only inside the
shared file and meets no constraint from segment rows, so it could leave segment rows naming nothing. Writes stay off
(the off switch in ``segment_open``) until those delete paths look through every segment (stage 4): a condition on turning them on,
not something this module can enforce.
"""

from __future__ import annotations

import functools

#: The per-article tables a segment holds, in creation order (``articles`` first: the others reference it).
SEGMENT_TABLES: tuple[str, ...] = (
    "articles",
    "keyword_mentions",
    "article_mentioned_dates",
    "article_mentioned_places",
    "article_entities",
    "article_index_stamps",
    "article_www_stamps",
)

#: Every column of a segment table that names a row of the SHARED file, and that row's table. Enforced in code by
#: ``segment_write.insert_rows``, since a constraint cannot span two files. A test pins this list against the models: a new
#: foreign key to a shared table fails it until it is listed here.
SHARED_REFERENCES: dict[tuple[str, str], str] = {
    ("articles", "source_id"): "sources",
    ("keyword_mentions", "keyword_id"): "keywords",
    ("keyword_mentions", "source_id"): "sources",
    ("articles", "top_keyword_id"): "keywords",
}


@functools.cache
def segment_table_ddl() -> tuple[str, ...]:
    """The table and index statements for :data:`SEGMENT_TABLES`, from the models, with every foreign key to a table outside
    the segment dropped. Cached: the models do not change while the process runs."""
    from sqlalchemy import MetaData
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.schema import CreateIndex, CreateTable

    from src.database.maintenance import HOT_INDEXES
    from src.database.models import Base

    md = MetaData()
    for name in SEGMENT_TABLES:
        Base.metadata.tables[name].to_metadata(md)
    for name in SEGMENT_TABLES:
        table = md.tables[name]
        for fk in list(table.foreign_key_constraints):
            if fk.elements[0].target_fullname.split(".")[0] not in SEGMENT_TABLES:
                table.constraints.discard(fk)
                for col in fk.columns:
                    col.foreign_keys.clear()
    dialect = sqlite.dialect()
    out: list[str] = []
    for name in SEGMENT_TABLES:
        table = md.tables[name]
        out.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        for index in sorted(table.indexes, key=lambda i: str(i.name)):
            out.append(str(CreateIndex(index).compile(dialect=dialect)).strip())
    for sql in HOT_INDEXES.values():
        text = str(sql)
        target = text.split(" ON ", 1)[1].split("(", 1)[0].strip() if " ON " in text else ""
        if target in SEGMENT_TABLES:
            out.append(text.strip())
    return tuple(out)


@functools.cache
def segment_search_ddl() -> tuple[str, ...]:
    """The article search index (``article_fts`` and its sync triggers) and the title index, as the shared file makes them."""
    from src.database import fts, fts_title

    return tuple(str(s).strip() for s in (*fts._FTS_DDL, *fts_title._ddl()))


def _deferred_in_bulk(sql: str) -> bool:
    """A statement a bulk load runs only when it seals the segment: a non-unique index (maintained per row otherwise) or one
    of the article search index's sync triggers (each runs the text transform per row; the seal indexes every article once
    instead, ``fts.rebuild_index``). The unique indexes stay from the start: they are constraints, not speed (the same rule
    as ``analytics.bulk_build``), so a load can never insert a row they would refuse."""
    from src.database import fts

    head = " ".join(sql.split()).upper()
    if head.startswith("CREATE INDEX "):
        return True
    return any(head.startswith(f"CREATE TRIGGER IF NOT EXISTS {t.upper()} ") for t in fts._FTS_TRIGGERS)


def bulk_split(ddl: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``ddl`` (``segment_open.segment_ddl``, in order) split into what a bulk-loaded segment is made with and what its seal
    adds, each in the original order, so the sealed file's schema is exactly the one every segment is made with."""
    now = tuple(s for s in ddl if not _deferred_in_bulk(s))
    later = tuple(s for s in ddl if _deferred_in_bulk(s))
    return now, later
