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
