"""Reading and resolving the alternates a restore kept (R61, item 12, slice 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``metadata_alternates`` holds the OTHER value a restore brought for a deduced item the corpus
already had (``_capture_alternates`` in ``merge.py``). This module is the operator's side of it:
list the differences with both values and both provenance tags, and let the operator decide.
Nothing here runs on its own -- every mutation is one explicit call for one alternate (or one
restore batch), and none touches a row the operator did not point at.

The three actions:

* ``keep``    -- mark it seen; both values stay.
* ``discard`` -- delete the alternate; the local value stays (the imported one is gone).
* ``discard_batch`` -- discard every alternate one restore brought.

There is deliberately NO action that makes an imported value the one the app shows (the
maintainer's rule: imported data never prevails over local data). A "show this one instead"
swap was built and reviewed and taken out: doing it right needs identity-based resolution of
the local row plus a provenance rewrite, and it is a separate slice if the operator asks for it.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.backup.provenance import ALTERNATE_SPECS, PRODUCER_COLUMNS, provenance_tag


class AlternateError(Exception):
    """A refusal the API maps to a 4xx: the message is safe to show."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _columns(session: Any, table: str) -> set[str]:
    if table not in PRODUCER_COLUMNS:
        raise AlternateError(f"unknown table {table!r}", 400)
    return {r[1] for r in session.execute(text(f"PRAGMA table_info({table})"))}  # noqa: S608  # nosec B608 - table is a key of PRODUCER_COLUMNS, checked above


def _local_row_id(session: Any, table: str, identity: dict) -> int | None:
    """The id of the local row this alternate differs from, found by its IDENTITY.

    Never by the ``local_row_id`` the restore stored: those tables use plain integer keys that
    SQLite reuses after a delete, so a stored id can point at an unrelated row later. Where the
    corpus holds several rows for one identity (a local pass appends one per run), the newest is
    the one shown, as the readers do."""
    spec = ALTERNATE_SPECS.get(table)
    if spec is None or table not in PRODUCER_COLUMNS:
        return None
    joins = ""
    where: list[str] = []
    params: dict[str, Any] = {}
    if spec["scope"] == "article":
        joins = " JOIN articles a ON a.id = t.article_id"
        where.append("a.hash = :article_hash")
        params["article_hash"] = identity.get("article_hash")
    elif spec["scope"] == "law":
        joins = (
            " JOIN law_revisions r ON r.id = t.revision_id"
            " JOIN law_documents d ON d.id = r.document_id"
        )
        where.append("d.url = :document_url AND r.content_hash = :revision_content_hash")
        # An alternate recorded before the jurisdiction joined the identity has none: the newest
        # matching row is then the best available answer, never "gone".
        if identity.get("jurisdiction"):
            where.append("d.jurisdiction = :jurisdiction")
            params["jurisdiction"] = identity["jurisdiction"]
        params["document_url"] = identity.get("document_url")
        params["revision_content_hash"] = identity.get("revision_content_hash")
    for i, (name, column) in enumerate(spec["match"].items()):
        where.append(f"COALESCE(t.{column}, '') = COALESCE(:m{i}, '')")
        params[f"m{i}"] = identity.get(name)
    if not where:
        return None
    row = session.execute(
        text(f"SELECT t.id FROM {table} t{joins} WHERE " + " AND ".join(where) + " ORDER BY t.id DESC LIMIT 1"),  # noqa: S608  # nosec B608 - table is a key of ALTERNATE_SPECS and PRODUCER_COLUMNS, every column name is a literal from ALTERNATE_SPECS; the identity values are bound
        params,
    ).fetchone()
    return None if row is None else int(row[0])


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
    local_id = _local_row_id(session, r.table_name, identity)
    local = _local_values(session, r.table_name, local_id, list(imported))
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
            provenance_tag(session, r.table_name, local_id)
            if local is not None and local_id is not None else None
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
        .offset(max(0, offset)).limit(max(1, min(limit, 1000))).all()
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
            "holds; the machine's own value is what the app shows, and nothing here changes that"
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
