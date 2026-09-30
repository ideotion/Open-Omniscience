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
* ``discard`` -- delete the alternate; the value shown stays (the other one is gone).
* ``discard_batch`` -- discard every alternate one restore brought.
* ``swap``    -- the operator's explicit choice to show the restore's value instead. NEVER
  automatic: a restore itself changes nothing that is shown (the maintainer's rule: imported
  data does not prevail over local data on its own). It is a swap, not an overwrite -- the row
  takes the alternate's values and the alternate takes the row's, each with its own provenance
  tag, so nothing is lost and swapping again puts it back. The record then carries the status
  ``swapped``: it holds the value that WAS shown, so a batch discard leaves it alone and a
  single discard asks for an explicit confirmation.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.backup.provenance import (
    ALTERNATE_SPECS,
    KEYED_TABLES,
    PRODUCER_COLUMNS,
    producer_extra_columns,
    provenance_tag,
)


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
    """The ``rowid`` of the local row this alternate differs from, found by its IDENTITY.

    ``rowid`` rather than ``id``: it is the same number for a table with an integer key and it
    exists for the text-keyed ones (places, Wikidata items) that have no ``id`` to read.

    Never by the ``local_row_id`` the restore stored: those tables use plain integer keys that
    SQLite reuses after a delete, so a stored id can point at an unrelated row later. Where the
    corpus holds several rows for one identity (a local pass appends one per run), the newest is
    the one shown, as the readers do. ``rowid`` (not ``id``) so a table keyed by text works too."""
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
    # Newest first in the READERS' order: by the row's own stamp, then by rowid.
    stamp = producer_extra_columns(table).get("produced_at")
    order = (f"COALESCE(t.{stamp}, '') DESC, " if stamp and stamp in _columns(session, table) else "") + "t.rowid DESC"
    row = session.execute(
        text(f"SELECT t.rowid FROM {table} t{joins} WHERE " + " AND ".join(where) + f" ORDER BY {order} LIMIT 1"),  # noqa: S608  # nosec B608 - table is a key of ALTERNATE_SPECS and PRODUCER_COLUMNS, every column name is a literal from ALTERNATE_SPECS or PRODUCER_COLUMNS; the identity values are bound
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
        text(f"SELECT {', '.join(cols)} FROM {table} WHERE rowid = :id"),  # noqa: S608  # nosec B608 - table is validated and the column names are intersected with the table's own columns above
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
        "swapped": r.status == "swapped",
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

    ``status`` is ``pending`` (not yet looked at, plus the swapped ones, which the operator
    must keep seeing: what they show is the restore's value), ``kept`` or ``all``. Counts are
    counts."""
    from src.database.models import MergeBatch, MetadataAlternate

    q = session.query(MetadataAlternate)
    if status == "pending":
        q = q.filter(MetadataAlternate.status.in_(("pending", "swapped")))
    elif status == "kept":
        q = q.filter(MetadataAlternate.status == "kept")
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
            "swapped": counts[b.id].get("swapped", 0),
        })
    return {
        "status": status,
        "total": total,
        "batches": batches,
        "items": [_item(session, r) for r in rows],
        "method": (
            "each item is a value a restore brought that differs from the one this machine "
            "holds; the app shows this machine's value unless the operator chose the restore's, and "
            "nothing here changes what is shown by itself"
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
    if alt.status == "swapped":
        raise AlternateError("this one holds the value shown before a swap: swap back or discard it", 409)
    alt.status = "kept"
    session.commit()
    return {"id": alt_id, "status": "kept"}


def discard(session: Any, alt_id: int, *, confirm: bool = False) -> dict:
    alt = _get(session, alt_id)
    if alt.status == "swapped" and not confirm:
        # It is the only copy of the value that was shown before the swap.
        raise AlternateError(
            "this holds the value that was shown before a swap; discarding it loses that value", 409
        )
    session.delete(alt)
    session.commit()
    return {"id": alt_id, "discarded": True}


def discard_batch(session: Any, batch_id: int) -> dict:
    """Discard every alternate one restore brought, except the swapped ones: each of those is the
    only copy of a value that was shown before a swap, and is discarded one at a time, on purpose."""
    n = session.execute(
        text("DELETE FROM metadata_alternates WHERE batch_id = :b AND status != 'swapped'"),
        {"b": int(batch_id)},
    ).rowcount
    left = session.execute(
        text("SELECT COUNT(*) FROM metadata_alternates WHERE batch_id = :b AND status = 'swapped'"),
        {"b": int(batch_id)},
    ).scalar()
    session.commit()
    return {"batch_id": batch_id, "discarded": int(n or 0), "left_swapped": int(left or 0)}


def _notnull(session: Any, table: str) -> set[str]:
    if table not in PRODUCER_COLUMNS:
        raise AlternateError(f"unknown table {table!r}", 400)
    return {r[1] for r in session.execute(text(f"PRAGMA table_info({table})")) if r[3]}  # noqa: S608  # nosec B608 - table is a key of PRODUCER_COLUMNS, checked above


#: Rows a reader ranks TOGETHER with a given row, beyond the scope's own parent: the readers
#: pick the newest of a group by its stamp, across models and prompt versions.
_SIBLINGS: dict[str, list[str]] = {
    "article_analyses": ["article_id", "kind"],
    "ai_keyword": ["article_id", "kind", "term"],
    "article_mentioned_dates": ["article_id", "mentioned_on", "precision"],
    "article_title_translations": ["article_id", "target_lang"],
    "keyword_translations": ["term", "target_lang"],
    "law_revision_summaries": ["revision_id"],
}


def _refuse_if_a_newer_sibling_would_take_over(
    session: Any, table: str, local_id: int, stamp_col: str | None, sets: dict
) -> None:
    """A swap moves the row's own stamp to the adopted value's. Readers show the NEWEST row of
    a group, so if that stamp is older than a sibling the row currently outranks, the app would
    start showing the sibling and the swap would not do what it says. Refuse, and say why."""
    group = _SIBLINGS.get(table)
    if not group or stamp_col is None or stamp_col not in sets or sets[stamp_col] is None:
        return
    cur = session.execute(
        text(f"SELECT {stamp_col} FROM {table} WHERE rowid = :id"), {"id": local_id}  # noqa: S608  # nosec B608 - table is a validated key, stamp_col a module literal
    ).scalar()
    if cur is None or str(sets[stamp_col]) >= str(cur):
        return
    same = " AND ".join(f"{c} IS (SELECT {c} FROM {table} WHERE rowid = :id)" for c in group)  # nosec B608 - module literals
    n = session.execute(
        text(
            f"SELECT COUNT(*) FROM {table} WHERE rowid != :id AND {same}"  # noqa: S608  # nosec B608 - table and columns are module literals; values are bound
            f" AND {stamp_col} > :new AND {stamp_col} <= :cur"
        ),
        {"id": local_id, "new": sets[stamp_col], "cur": cur},
    ).scalar()
    if n:
        raise AlternateError(
            "another result on this machine is newer than the restore's value, so the app would "
            "keep showing that one; swapping would not make the restore's value the one shown", 409
        )


def _scalars(values: dict) -> bool:
    return all(v is None or isinstance(v, (str, int, float, bool)) for v in values.values())


def swap(session: Any, alt_id: int) -> dict:
    """Show the alternate's value and keep the one that was shown as the alternate.

    Everything happens in ONE transaction, or nothing does. The local row is found by the
    alternate's IDENTITY, at this moment (never by an id stored earlier). Only the columns the
    table's own ``ALTERNATE_SPECS`` entry names as shown are ever written, whatever the stored
    JSON says: it came from a backup file. The tag stays true because the row's producer
    columns (its ``created_at``/``prompt_text``, ``as_of``/``fetched_at`` for the keyed tables)
    move with the values, and ``merged_rows`` is rewritten so the row's arrival is the batch the
    adopted value came from (or none, when the adopted value was made here)."""
    alt = _get(session, alt_id)
    table = alt.table_name
    spec = ALTERNATE_SPECS.get(table)
    if spec is None or table not in PRODUCER_COLUMNS:
        raise AlternateError(f"unknown table {table!r}", 400)
    identity, imported, prov = json.loads(alt.identity), json.loads(alt.fields), json.loads(alt.provenance)
    if not (isinstance(identity, dict) and isinstance(imported, dict) and isinstance(prov, dict)
            and _scalars(imported)):
        raise AlternateError("this difference is not well-formed and cannot be swapped", 400)
    local_id = _local_row_id(session, table, identity)
    if local_id is None:
        raise AlternateError("the row this differs from is gone, so there is nothing to swap with", 409)
    have = _columns(session, table)
    names = [c for c in spec["shown"] if c in imported and c in have]
    if not names:
        raise AlternateError("nothing in this difference can be swapped", 400)
    # The row's own values, as the SAME SQL a capture uses writes them: byte-identical JSON is
    # what keeps a later restore of the same backup from recording this difference again.
    before_json = session.execute(
        text(
            "SELECT json_object(" + ", ".join(f"'{c}', {c}" for c in names)  # noqa: S608  # nosec B608 - every name is a shown column of this table's own spec, intersected with its real columns
            + f") FROM {table} WHERE rowid = :id"
        ),
        {"id": local_id},
    ).scalar()
    before_tag = provenance_tag(session, table, local_id)
    if before_json is None or before_tag is None:
        raise AlternateError("the row this differs from is gone, so there is nothing to swap with", 409)
    sets = {c: imported[c] for c in names}
    notnull = _notnull(session, table)
    stamp_col = producer_extra_columns(table).get("produced_at")
    for field, column in producer_extra_columns(table).items():
        if column in have and column not in sets:
            value = prov.get(field)
            if value is None and column in notnull:
                raise AlternateError("this difference does not say when it was produced, so it cannot be swapped", 400)
            sets[column] = value      # a value with no prompt must not keep the local prompt beside it
    _refuse_if_a_newer_sibling_would_take_over(session, table, local_id, stamp_col, sets)
    key_col = KEYED_TABLES.get(table)
    key_val = (
        session.execute(text(f"SELECT {key_col} FROM {table} WHERE rowid = :id"), {"id": local_id}).scalar()  # noqa: S608  # nosec B608 - table is a validated key of ALTERNATE_SPECS and key_col a module literal from KEYED_TABLES
        if key_col else None
    )
    try:
        arrived_raw = (prov.get("arrived") or {}).get("batch")
        arrived = None if arrived_raw is None else int(arrived_raw)
    except (TypeError, ValueError, AttributeError):
        raise AlternateError("this difference's provenance is not well-formed", 400) from None
    try:
        session.execute(
            text(
                f"UPDATE {table} SET " + ", ".join(f"{c} = :v{i}" for i, c in enumerate(sets))  # noqa: S608  # nosec B608 - table is a validated key of ALTERNATE_SPECS; every column is a name from that table's own spec or PRODUCER_COLUMNS, intersected with its real columns; values are bound
                + " WHERE rowid = :id"
            ),
            {**{f"v{i}": v for i, v in enumerate(sets.values())}, "id": local_id},
        )
        # A text-keyed table is found by its KEY only (its rowid may have been renumbered, so
        # a row_id match could belong to another row); an integer-keyed one by its id.
        if key_col:
            session.execute(
                text("DELETE FROM merged_rows WHERE table_name = :t AND row_key = :k"),
                {"t": table, "k": None if key_val is None else str(key_val)},
            )
        else:
            session.execute(
                text("DELETE FROM merged_rows WHERE table_name = :t AND row_id = :id"),
                {"t": table, "id": local_id},
            )
        exists = arrived is not None and session.execute(
            text("SELECT 1 FROM merge_batches WHERE id = :b"), {"b": arrived}
        ).fetchone()
        if exists:
            slot = local_id
            if key_col and session.execute(
                text("SELECT 1 FROM merged_rows WHERE batch_id = :b AND table_name = :t AND row_id = :id"),
                {"b": arrived, "t": table, "id": local_id},
            ).fetchone():
                # The rowid is another row's leftover (a text-keyed table's rowids can be
                # renumbered) and the primary key includes it. This row is found by its KEY,
                # so any free number will do; a negative one can never be a real rowid.
                slot = int(session.execute(
                    text("SELECT MIN(MIN(row_id), 0) - 1 FROM merged_rows WHERE batch_id = :b AND table_name = :t"),
                    {"b": arrived, "t": table},
                ).scalar())
            session.execute(
                text("INSERT INTO merged_rows (batch_id, table_name, row_id, row_key) VALUES (:b, :t, :id, :k)"),
                {"b": arrived, "t": table, "id": slot, "k": None if key_val is None else str(key_val)},
            )
        # The alternate now holds the row's old values under the row's old tag; the tag it had
        # (a carried one keeps its chain) rides inside it, and comes back verbatim on the swap
        # back. ``origin`` is the record's own and never changes: a restore de-duplicates on it.
        if alt.status == "swapped":
            out = prov.get("swapped_out")
            back = out.get("provenance") if isinstance(out, dict) else None
            new_prov = back if isinstance(back, dict) else before_tag
        else:
            new_prov = {**before_tag, "swapped_out": {"provenance": prov}}
        alt.fields = before_json
        alt.provenance = json.dumps(new_prov)
        alt.local_row_id = local_id
        alt.status = "pending" if alt.status == "swapped" else "swapped"
        session.commit()
    except AlternateError:
        session.rollback()
        raise
    except Exception as exc:  # driver-agnostic: sqlite3 and sqlcipher3 raise different classes
        session.rollback()
        raise AlternateError(f"could not apply that swap: {exc}", 409) from exc
    return {"id": alt_id, "status": alt.status, "shown": "restore" if alt.status == "swapped" else "machine"}
