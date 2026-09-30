"""Reading and resolving the alternates a restore kept (R61, item 12, slice 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``metadata_alternates`` holds the OTHER value a restore brought for a deduced item the corpus
already had (``_capture_alternates`` in ``merge.py``). This module is the operator's side of it:
list the differences with both values and both provenance tags, and let the operator decide.
Nothing here runs on its own -- every mutation is one explicit call for one alternate (or one
restore batch), and none touches a row the operator did not point at.

The four actions:

* ``keep``    -- mark it seen; both values stay.
* ``discard`` -- delete the alternate; the local value stays (the imported one is gone).
* ``adopt``   -- the imported value becomes the local row's value and the value it replaced
  becomes the alternate, so nothing is lost and the choice can be reversed by adopting again.
  The only way an imported value ever becomes the shown one.
* ``discard_batch`` -- discard every alternate one restore brought.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.backup.provenance import PRODUCER_COLUMNS, provenance_tag

#: Columns an ``adopt`` may never write, whatever the stored fields say.
_NEVER_WRITTEN = frozenset({"id", "article_id", "revision_id", "created_at"})


class AlternateError(Exception):
    """A refusal the API maps to a 4xx: the message is safe to show."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _columns(session: Any, table: str) -> set[str]:
    if table not in PRODUCER_COLUMNS:
        raise AlternateError(f"unknown table {table!r}", 400)
    return {r[1] for r in session.execute(text(f"PRAGMA table_info({table})"))}  # noqa: S608  # nosec B608 - table is a key of PRODUCER_COLUMNS, checked above


def _local_values(session: Any, table: str, row_id: int | None, names: list[str]) -> dict | None:
    if row_id is None or not names:
        return None
    cols = [c for c in names if c in _columns(session, table)]
    if not cols:
        return None
    row = session.execute(
        text(f"SELECT {', '.join(cols)} FROM {table} WHERE id = :id"),  # noqa: S608  # nosec B608 - table is validated and the column names are intersected with the table's own columns above
        {"id": row_id},
    ).fetchone()
    return None if row is None else dict(zip(cols, row, strict=True))


def _article_of(session: Any, identity: dict) -> dict | None:
    h = identity.get("article_hash")
    if not h:
        return None
    row = session.execute(
        text("SELECT id, title FROM articles WHERE hash = :h"), {"h": h}
    ).fetchone()
    return None if row is None else {"id": row[0], "title": row[1]}


def _item(session: Any, r: Any) -> dict:
    identity = json.loads(r.identity)
    imported = json.loads(r.fields)
    local = _local_values(session, r.table_name, r.local_row_id, list(imported))
    differing = [k for k, v in imported.items() if local is None or local.get(k) != v]
    return {
        "id": r.id,
        "batch_id": r.batch_id,
        "table": r.table_name,
        "identity": identity,
        "article": _article_of(session, identity),
        "status": r.status,
        "imported": imported,
        "imported_provenance": json.loads(r.provenance),
        "local": local,
        "local_provenance": (
            provenance_tag(session, r.table_name, r.local_row_id) if local is not None else None
        ),
        "differing": differing,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_alternates(
    session: Any, *, status: str = "pending", limit: int = 50, offset: int = 0
) -> dict:
    """The differences, newest restore first, with per-restore counts.

    ``status`` is ``pending`` (not yet looked at), ``kept`` or ``all``. Counts are counts."""
    from src.database.models import MergeBatch, MetadataAlternate

    q = session.query(MetadataAlternate)
    if status in ("pending", "kept"):
        q = q.filter(MetadataAlternate.status == status)
    total = q.count()
    rows = (
        q.order_by(MetadataAlternate.batch_id.desc(), MetadataAlternate.id)
        .offset(max(0, offset)).limit(max(1, min(limit, 200))).all()
    )
    counts: dict[int, dict[str, int]] = {}
    for bid, st, n in session.execute(
        text("SELECT batch_id, status, COUNT(*) FROM metadata_alternates GROUP BY batch_id, status")
    ):
        counts.setdefault(int(bid), {})[st] = int(n)
    batches = []
    for b in session.query(MergeBatch).filter(MergeBatch.id.in_(list(counts))).order_by(
        MergeBatch.id.desc()
    ):
        batches.append({
            "id": b.id,
            "imported_at": b.imported_at.isoformat() if b.imported_at else None,
            "origin": b.origin_fingerprint,
            "app_version": b.app_version,
            "pending": counts[b.id].get("pending", 0),
            "kept": counts[b.id].get("kept", 0),
        })
    return {
        "status": status,
        "total": total,
        "batches": batches,
        "items": [_item(session, r) for r in rows],
        "method": (
            "each item is a value a restore brought that differs from the one this machine "
            "holds; the machine's own value is what the app shows until you choose otherwise"
        ),
    }


def _get(session: Any, alt_id: int) -> Any:
    from src.database.models import MetadataAlternate

    alt = session.get(MetadataAlternate, alt_id)
    if alt is None:
        raise AlternateError("no such alternate", 404)
    return alt


def keep(session: Any, alt_id: int) -> dict:
    alt = _get(session, alt_id)
    alt.status = "kept"
    session.commit()
    return {"id": alt_id, "status": "kept"}


def discard(session: Any, alt_id: int) -> dict:
    alt = _get(session, alt_id)
    session.delete(alt)
    session.commit()
    return {"id": alt_id, "discarded": True}


def discard_batch(session: Any, batch_id: int) -> dict:
    n = session.execute(
        text("DELETE FROM metadata_alternates WHERE batch_id = :b"), {"b": int(batch_id)}
    ).rowcount
    session.commit()
    return {"batch_id": batch_id, "discarded": int(n or 0)}


def adopt(session: Any, alt_id: int) -> dict:
    """Make the imported value the local row's value; the replaced value becomes the alternate.

    Refused when the local row no longer exists (nothing to replace) or names a column the
    table does not have. The swap is one transaction."""
    alt = _get(session, alt_id)
    table = alt.table_name
    imported = json.loads(alt.fields)
    have = _columns(session, table)
    cols = [c for c in imported if c in have and c not in _NEVER_WRITTEN]
    if not cols:
        raise AlternateError("nothing in this alternate can be applied", 400)
    before = _local_values(session, table, alt.local_row_id, cols)
    if before is None:
        raise AlternateError("the local row this differs from is gone", 409)
    tag_before = provenance_tag(session, table, alt.local_row_id)
    session.execute(
        text(
            f"UPDATE {table} SET " + ", ".join(f"{c} = :v_{i}" for i, c in enumerate(cols))  # noqa: S608  # nosec B608 - table is a key of PRODUCER_COLUMNS and cols are intersected with the table's own columns; values are bound
            + " WHERE id = :id"
        ),
        {**{f"v_{i}": imported[c] for i, c in enumerate(cols)}, "id": alt.local_row_id},
    )
    # The row now says what the backup said, so it must say where that came from: an arrival
    # record for the batch, exactly like a row the restore itself inserted.
    session.execute(
        text(
            "INSERT OR IGNORE INTO merged_rows (batch_id, table_name, row_id)"
            " VALUES (:b, :t, :r)"
        ),
        {"b": alt.batch_id, "t": table, "r": alt.local_row_id},
    )
    alt.fields = json.dumps(before, ensure_ascii=False)
    alt.provenance = json.dumps(tag_before, ensure_ascii=False)
    alt.origin = (tag_before or {}).get("origin") or "local"
    alt.status = "kept"
    session.commit()
    return {"id": alt_id, "adopted": True, "columns": cols}
