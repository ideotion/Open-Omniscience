"""The provenance tag on deduced metadata: format ``oo.prov/1`` (R61, item 12).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's rule (2026-09-29): every deduced metadatum travels with provenance details.
The producer half of a tag already lives on the row itself (``model``, ``prompt_version``,
``prompt_text``, ``extractor``, ``created_at``); the arrival half lives in ``merged_rows`` and
``merge_batches``. No column is added to any domain table. This module is the ONE place that
turns those into a tag, in SQL (for the restore, which builds tags for rows still sitting in the
staged corpus) and in Python (for a reader that has a local row id), so the two cannot drift.

The tag, a JSON object::

    {"v": 1,
     "kind": "model" | "extractor" | "human",
     "producer": "<model name | extractor name | 'user'>",
     "version": "<prompt version | null>",
     "prompt_text": "<the verbatim prompt | null>",
     "produced_at": "<the row's created_at | null>",
     "origin": "local" | "<origin fingerprint of the backup the row arrived in>",
     "arrived": null | {"batch": <merge_batches.id>, "at": "<imported_at>", "app_version": "<x.y.z>"}}

An unknown field is ``null`` -- never guessed, never omitted. ``origin`` is the IMMEDIATE backup
(a row that hopped A to B to C says B); the producer fields still say what A's model and prompt
were, because they travel on the row. Row C attaches exactly this to places.
"""

from __future__ import annotations

import json
from typing import Any

TAG_VERSION = 1

#: Per deduced table, the SQL expression (over an alias placeholder ``{a}``) for each producer
#: field. ``NULL`` where the table does not record it. Table names here are module literals.
PRODUCER_COLUMNS: dict[str, dict[str, str]] = {
    "article_analyses": {
        "kind": "'model'", "producer": "{a}.model", "version": "{a}.prompt_version",
        "prompt_text": "{a}.prompt_text", "produced_at": "{a}.created_at",
    },
    "ai_keyword": {
        "kind": "'model'", "producer": "{a}.model", "version": "{a}.prompt_version",
        "prompt_text": "NULL", "produced_at": "{a}.created_at",
    },
    "keyword_translations": {
        "kind": "'model'", "producer": "{a}.model", "version": "{a}.prompt_version",
        "prompt_text": "NULL", "produced_at": "{a}.created_at",
    },
    "article_title_translations": {
        "kind": "'model'", "producer": "{a}.model", "version": "{a}.prompt_version",
        "prompt_text": "NULL", "produced_at": "{a}.created_at",
    },
    "law_revision_summaries": {
        "kind": "'model'", "producer": "{a}.model", "version": "{a}.prompt_version",
        "prompt_text": "{a}.prompt_text", "produced_at": "{a}.created_at",
    },
    # A confirm or reject is the operator's own judgement, whatever extractor proposed the date.
    "article_mentioned_dates": {
        "kind": "CASE WHEN {a}.status IN ('confirmed', 'rejected') THEN 'human' ELSE 'extractor' END",
        "producer": "CASE WHEN {a}.status IN ('confirmed', 'rejected') THEN 'user' ELSE {a}.extractor END",
        "version": "NULL", "prompt_text": "NULL", "produced_at": "{a}.created_at",
    },
}


#: What a restore compares and keeps for each deduced table (R61). ``differs`` decides whether
#: an incoming row CONTRADICTS a local one; ``shown`` is what is stored and displayed;
#: ``match`` maps each identity field to the column that holds it (how a carried alternate finds
#: its local row again); ``scope`` says how the identity reaches the row's parent: ``article``
#: (``article_hash`` -> ``article_id``), ``law`` (``jurisdiction`` + ``document_url`` +
#: ``revision_content_hash`` -> ``revision_id``) or ``none``. ONE definition, read by the capture in ``merge.py``, by the
#: carry of alternates between machines, and pinned against each other by the tests.
ALTERNATE_SPECS: dict[str, dict[str, Any]] = {
    "article_analyses": {
        "scope": "article", "differs": ["result"], "shown": ["result"],
        "match": {"kind": "kind", "model": "model", "prompt_version": "prompt_version"},
    },
    "article_mentioned_dates": {
        "scope": "article", "differs": ["status"],
        "shown": ["status", "confidence", "extractor", "snippet"],
        "match": {"mentioned_on": "mentioned_on", "precision": "precision"},
    },
    "ai_keyword": {
        "scope": "article", "differs": ["confirmed"],
        "shown": ["confirmed", "evidence", "prompt_version", "language"],
        "match": {"kind": "kind", "term": "term", "model": "model"},
    },
    "keyword_translations": {
        "scope": "none", "differs": ["text"], "shown": ["text"],
        "match": {"term": "term", "source_lang": "source_lang", "target_lang": "target_lang",
                  "model": "model", "prompt_version": "prompt_version"},
    },
    "article_title_translations": {
        "scope": "article", "differs": ["title", "summary"],
        "shown": ["title", "summary", "source_lang"],
        "match": {"target_lang": "target_lang", "model": "model", "prompt_version": "prompt_version"},
    },
    "law_revision_summaries": {
        "scope": "law", "differs": ["summary"], "shown": ["summary", "prompt_version"],
        "match": {"model": "model"},
    },
}


def producer_tag_sql(table: str, alias: str, *, origin: str, batch: str, at: str, app_version: str) -> str:
    """SQL producing the tag JSON for a row of ``table`` aliased ``alias``.

    ``origin``, ``batch``, ``at`` and ``app_version`` are SQL expressions (named parameters or
    columns) for the arrival half. Raises ``KeyError`` for a table with no producer mapping, so a
    new deduced table cannot be captured without saying who produced it."""
    cols = PRODUCER_COLUMNS[table]
    f = {k: v.format(a=alias) for k, v in cols.items()}
    return (
        f"json_object('v', {TAG_VERSION}, 'kind', {f['kind']}, 'producer', {f['producer']},"
        f" 'version', {f['version']}, 'prompt_text', {f['prompt_text']},"
        f" 'produced_at', {f['produced_at']}, 'origin', {origin},"
        f" 'arrived', json_object('batch', {batch}, 'at', {at}, 'app_version', {app_version}))"
    )


def provenance_tag(session: Any, table: str, row_id: int) -> dict | None:
    """The tag of ONE local deduced row, or None when the row does not exist.

    A row with no ``merged_rows`` entry was produced here: ``origin`` is ``"local"`` and
    ``arrived`` is null."""
    from sqlalchemy import text

    sel = producer_tag_sql(
        table, "r", origin="COALESCE(b.origin_fingerprint, 'local')",
        batch="b.id", at="b.imported_at", app_version="b.app_version",
    )
    row = session.execute(
        text(
            f"SELECT {sel} FROM {table} r"  # noqa: S608  # nosec B608 - table is validated as a key of PRODUCER_COLUMNS by producer_tag_sql above, never input
            " LEFT JOIN merged_rows m ON m.table_name = :t AND m.row_id = r.rowid"
            " LEFT JOIN merge_batches b ON b.id = m.batch_id WHERE r.rowid = :id"
            " ORDER BY b.id LIMIT 1"
        ),
        {"t": table, "id": int(row_id)},
    ).fetchone()
    if row is None:
        return None
    tag = json.loads(row[0])
    if tag["arrived"]["batch"] is None:
        tag["arrived"] = None
    return tag
