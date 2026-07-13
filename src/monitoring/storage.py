"""Storage composition — what the on-disk gigabytes actually ARE (P1.5, SCALE_ROADMAP).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-07-09 field event grew the data folder to ~130 GB with an 11.7 GB database and
~120 GB of unidentified growth. Session forensics (:mod:`src.monitoring.forensics`) names
the FILES; this module names the INSIDE of the database file — per-table and per-index
byte totals via SQLite's ``dbstat`` virtual table — so the growth conversation ("which
table is the 11.7 GB? how much is mentions vs articles vs FTS shadow tables vs indexes?")
runs on measured numbers, and the P0.1 backup / P1.5 retention rulings are informed by
what the bytes actually are.

HONESTY + SAFETY:
  * counts/bytes only — never a score, never a recommendation;
  * READ-ONLY (dbstat walks btree pages; it writes nothing);
  * degrade, never 500: ``dbstat`` needs the SQLITE_ENABLE_DBSTAT_VTAB compile flag —
    absent (some SQLCipher builds), the report says ``{"available": false, reason}``
    honestly; a deadline abort reports itself the same way (the walk visits every page of
    the file, which through the SQLCipher codec can exceed the statement deadline on a
    very large corpus — stated in the caveat, never a hang).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.maintenance import StatementTimeout, statement_deadline

_LOG = logging.getLogger(__name__)

_METHOD = (
    "SQLite dbstat virtual table: per-btree page and byte totals, indexes grouped under "
    "their table (FTS/shadow tables appear under their own names). Bytes are on-disk "
    "pages including per-btree free space; the -wal/-shm files are NOT inside the main "
    "file (see session forensics for the file-level inventory). Counts/bytes only, "
    "no score."
)
_CAVEAT = (
    "dbstat walks the whole file's page structure through the SQLCipher codec — on a "
    "very large corpus this is a deliberate, on-demand measurement (bounded by the "
    "statement deadline; an abort is reported, never a hang)."
)


def _rows(session: Session, sql: str) -> list:
    return list(session.execute(text(sql)))


def _pragma(session: Session, name: str) -> int | None:
    try:
        # `name` is a module-internal constant pragma name, never user input.
        row = session.execute(text(f"PRAGMA {name}")).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return None


def storage_composition(session: Session) -> dict[str, Any]:
    """Per-table / per-index byte composition of the live SQLite store.

    Returns ``{"available": false, "reason": …}`` (plus whatever PRAGMA-level facts were
    readable) when dbstat is unavailable, the backend is not SQLite, or the deadline
    aborts the walk — an honest degrade block, never an exception to the caller."""
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "sqlite":
        return {
            "available": False,
            "dialect": dialect,
            "reason": "storage composition is implemented for SQLite (the app's store).",
        }

    out: dict[str, Any] = {"available": True, "dialect": dialect}
    # File-level page facts (cheap PRAGMAs — readable even where dbstat is not).
    page_size = _pragma(session, "page_size")
    page_count = _pragma(session, "page_count")
    freelist = _pragma(session, "freelist_count")
    out["page_size"] = page_size
    out["page_count"] = page_count
    out["freelist_pages"] = freelist
    # DB-10 instrument: is the freelist even RECLAIMABLE without a full VACUUM? auto_vacuum
    # (0 none / 1 full / 2 incremental) is a CREATE-time seam — a corpus created with 'none'
    # can only reclaim via a full VACUUM (rewrites the whole file), infeasible at scale.
    av = _pragma(session, "auto_vacuum")
    out["auto_vacuum"] = {0: "none", 1: "full", 2: "incremental"}.get(av) if av is not None else None
    # WAL VISIBILITY (STORAGE_5TB_PLAN §3 Phase-A: "surface WAL size … so an unbounded -wal is
    # VISIBLE"). journal_size_limit is the resting ceiling we set (session.py); wal_bytes is the
    # -wal file's ACTUAL size right now (a -wal much larger than the limit ⇒ a checkpoint is not
    # completing — the classic reader-starvation hazard, now diagnosable). Both degrade to None.
    jsl = _pragma(session, "journal_size_limit")
    out["journal_size_limit"] = jsl if (jsl is not None and jsl >= 0) else None
    try:
        main_db = None
        for row in _rows(session, "PRAGMA database_list"):
            if len(row) >= 3 and str(row[1]) == "main" and row[2]:
                main_db = str(row[2])
                break
        if main_db:
            wal = Path(main_db + "-wal")
            out["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
            if out.get("journal_size_limit") and out["wal_bytes"] > 4 * out["journal_size_limit"]:
                out["wal_note"] = (
                    "the -wal is much larger than journal_size_limit — a checkpoint may be "
                    "starved (a long-lived reader blocks it), the workload's known WAL-growth "
                    "hazard. The inter-pass TRUNCATE checkpoint should reclaim it when writers idle."
                )
    except Exception:  # noqa: BLE001 - WAL visibility is best-effort; never break the diagnostic
        pass
    if page_size and page_count is not None:
        out["db_bytes"] = page_size * page_count
    if page_size and freelist is not None:
        out["free_bytes"] = page_size * freelist  # reclaimable only via (in)cremental vacuum
        if out.get("auto_vacuum") == "none":
            out["free_bytes_note"] = (
                "auto_vacuum=none: these freelist bytes are reclaimable ONLY by a full VACUUM "
                "(rewrites the whole file, ~2x disk, exclusive writer) — infeasible at scale. See "
                "docs/design/DB10_RETENTION_VACUUM_MEMO.md (the irreversible CREATE-time seam ruling)."
            )

    # name -> (type, parent table) so indexes/shadow btrees group under their table.
    try:
        master = {
            str(name): (str(typ), str(tbl))
            for name, typ, tbl in _rows(
                session, "SELECT name, type, tbl_name FROM sqlite_master WHERE name IS NOT NULL"
            )
        }
    except Exception as exc:  # noqa: BLE001
        out["available"] = False
        out["reason"] = f"sqlite_master unreadable: {str(exc)[:200]}"
        return out

    # The dbstat walk itself — aggregated form first (one row per btree; far fewer rows),
    # the GROUP BY fallback for older SQLite, and an honest unavailable block otherwise.
    per_btree: dict[str, tuple[int, int]] = {}
    try:
        with statement_deadline(session):
            try:
                rows = _rows(
                    session, "SELECT name, pageno, pgsize FROM dbstat('main', 1)"
                )
                per_btree = {str(n): (int(p or 0), int(b or 0)) for n, p, b in rows}
            except StatementTimeout:
                raise
            except Exception:  # noqa: BLE001 - aggregated form unsupported -> GROUP BY
                rows = _rows(
                    session,
                    "SELECT name, COUNT(*) AS pages, SUM(pgsize) AS bytes "
                    "FROM dbstat GROUP BY name",
                )
                per_btree = {str(n): (int(p or 0), int(b or 0)) for n, p, b in rows}
    except StatementTimeout as exc:
        out["available"] = False
        out["reason"] = (
            f"aborted by the statement deadline ({exc}); the page walk exceeds the "
            "deadline on this corpus — the PRAGMA-level totals above still stand."
        )
        out["method"] = _METHOD
        out["caveat"] = _CAVEAT
        return out
    except Exception as exc:  # noqa: BLE001 - dbstat not compiled in -> honest unavailable
        out["available"] = False
        out["reason"] = (
            "dbstat virtual table unavailable (needs the SQLITE_ENABLE_DBSTAT_VTAB "
            f"compile flag in this SQLite/SQLCipher build): {str(exc)[:200]}"
        )
        out["method"] = _METHOD
        out["caveat"] = _CAVEAT
        return out

    # Group: every index btree under its parent table; shadow/system btrees keep their
    # own names (their sqlite_master tbl_name points at themselves or their FTS parent).
    tables: dict[str, dict[str, Any]] = {}
    for name, (pages, nbytes) in per_btree.items():
        typ, parent = master.get(name, ("unknown", name))
        if typ == "index":
            t = tables.setdefault(
                parent, {"name": parent, "bytes": 0, "pages": 0, "indexes": []}
            )
            t["indexes"].append({"name": name, "bytes": nbytes, "pages": pages})
        else:
            t = tables.setdefault(name, {"name": name, "bytes": 0, "pages": 0, "indexes": []})
            t["bytes"] += nbytes
            t["pages"] += pages
    report = []
    for t in tables.values():
        idx_bytes = sum(i["bytes"] for i in t["indexes"])
        t["indexes"].sort(key=lambda i: -i["bytes"])
        t["index_bytes"] = idx_bytes
        t["total_bytes"] = t["bytes"] + idx_bytes
        report.append(t)
    report.sort(key=lambda t: -t["total_bytes"])
    out["tables"] = report
    out["measured_bytes"] = sum(t["total_bytes"] for t in report)
    out["method"] = _METHOD
    out["caveat"] = _CAVEAT
    return out
