"""
The ``event_imports`` store — the durable, encrypted home for imported calendar events (D1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (DB-reliability D1): imported calendar events lived in the loose
``calendar_feed_imports.json`` side-file — NOT transactional (a crash mid-rewrite can
truncate it), NOT in the encrypted store (cleartext beside a SQLCipher corpus), and ABSENT
from every backup (the backup snapshots the DB, not the side files). Moving them into a row
of the encrypted corpus DB fixes all three.

STATUS (Wave 4 J — conservative slice). This module is the durable table's read/write
primitive, wired as a DUAL-WRITE MIRROR: every save of the imports side-file
(:func:`src.events.feeds._save_json`) also calls :func:`sync_imports` here, so the DB is a
faithful encrypted mirror at all times — including after an additive restore, since the
side-file UNION-merge itself ends in that same save. The JSON side-file stays the READ
source of truth + the merge target, so behaviour is byte-unchanged and nothing regresses.
Promoting reads to :func:`load_imports` + a native UNION-merge (retiring the JSON) is the
deferred D1 follow-up.

Why a lazy raw connection instead of the shared ORM engine — identical rationale to
:mod:`src.config.kv_store`: the engine is a module singleton bound to ``data_dir()`` at
IMPORT time, but this store resolves the live SQLite file LAZILY on every call (so per-test
``OO_DATA_DIR`` isolation holds) and opens it through the ONE :func:`src.database.connect.connect`
factory (encryption handled identically to the corpus). Writes take the process-wide
single-writer gate. A non-SQLite ``DATABASE_URL`` is a no-op (the JSON stays authoritative).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

TABLE = "event_imports"


def _db_path() -> str | None:
    """Resolve the live SQLite file the lazy (current-``data_dir()``) way; ``None`` for a
    non-SQLite ``DATABASE_URL`` (the mirror is a no-op there — the JSON stays authoritative)."""
    url = os.getenv("DATABASE_URL", "")
    if url:
        if not url.startswith("sqlite"):
            return None
        return url.removeprefix("sqlite:///")
    from src.paths import data_dir

    return str(data_dir() / "open_omniscience.db")


def _open(path: str):
    from src.database.connect import connect

    conn = connect(path, check_same_thread=False, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:  # noqa: BLE001 - a pragma failure must never break the mirror
        pass
    return conn


def _ensure_table(conn) -> None:
    """Create ``event_imports`` if the file predates it / a fresh test DB never ran init_db.

    Matches the alembic migration + the ``EventImport`` model — the same self-heal belt
    :mod:`src.config.kv_store` uses for ``app_state``."""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} ("  # noqa: S608  # nosec B608 - {TABLE} is a fixed constant, never input
        "id INTEGER PRIMARY KEY, family_key TEXT NOT NULL, fingerprint TEXT NOT NULL, "
        "family_name TEXT, family_user INTEGER, imported_at TEXT, title TEXT, date TEXT, "
        "sources TEXT, uids TEXT, updated_at TEXT)"
    )
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ix_event_imports_family_fp "  # noqa: S608  # nosec B608 - constant DDL, no input
        f"ON {TABLE} (family_key, fingerprint)"
    )


def _json_list(raw) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return val if isinstance(val, list) else []


def _flatten(imports: dict) -> list[tuple]:
    """The imports dict → one row per event (a marker row per empty family, so family-level
    metadata is preserved). Row order matches the INSERT column list in :func:`sync_imports`."""
    now = datetime.now(UTC).isoformat()
    rows: list[tuple] = []
    for fam_key, bucket in (imports or {}).items():
        if not isinstance(fam_key, str) or not isinstance(bucket, dict):
            continue
        fam_name = bucket.get("name")
        fam_user = 1 if bucket.get("user") else 0
        imported_at = bucket.get("imported_at")
        events = bucket.get("events") or {}
        if not isinstance(events, dict) or not events:
            # Preserve a family with no events via a marker row (fingerprint "").
            rows.append((fam_key, "", fam_name, fam_user, imported_at, None, None, None, None, now))
            continue
        for fp, ev in events.items():
            if not isinstance(ev, dict):
                continue
            rows.append((
                fam_key, str(fp), fam_name, fam_user, imported_at,
                ev.get("title"), ev.get("date"),
                json.dumps(ev.get("sources") or [], ensure_ascii=False),
                json.dumps(ev.get("uids") or [], ensure_ascii=False),
                now,
            ))
    return rows


def sync_imports(imports: dict) -> dict:
    """Mirror the full imports dict into the DB (a transactional FULL replace under the write
    gate, so the table always equals the side-file). Best-effort by design — the JSON is
    authoritative, so a DB hiccup logs and returns ``{"synced": False}`` rather than raising
    (never break the user's calendar import over a mirror problem)."""
    path = _db_path()
    if path is None:
        return {"synced": False, "reason": "non-sqlite backend"}
    rows = _flatten(imports)
    from src.database.writer import write_lock

    try:
        with write_lock():
            conn = _open(path)
            try:
                _ensure_table(conn)
                conn.execute(f"DELETE FROM {TABLE}")  # noqa: S608  # nosec B608 - {TABLE} constant, no input
                if rows:
                    conn.executemany(
                        f"INSERT INTO {TABLE} (family_key, fingerprint, family_name, "  # noqa: S608  # nosec B608 - {TABLE} constant; values are bound params
                        "family_user, imported_at, title, date, sources, uids, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        rows,
                    )
                conn.commit()
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 - the mirror must never break the authoritative JSON write
        _LOG.warning("event_imports mirror sync failed; the JSON side-file is authoritative",
                     exc_info=True)
        return {"synced": False, "reason": "db error"}
    return {"synced": True, "rows": len(rows)}


def load_imports() -> dict:
    """Reconstruct the imports-dict shape from the DB table (for the eventual read-switchover
    + tests). Degrades to ``{}`` on any error (missing table / locked DB)."""
    path = _db_path()
    if path is None:
        return {}
    try:
        conn = _open(path)
        try:
            rows = conn.execute(
                f"SELECT family_key, fingerprint, family_name, family_user, imported_at, "  # noqa: S608  # nosec B608 - {TABLE} constant, no input
                f"title, date, sources, uids FROM {TABLE}"
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - a missing table / locked DB is a normal "no rows"
        _LOG.debug("event_imports load unavailable; caller falls back", exc_info=True)
        return {}
    out: dict = {}
    for fam_key, fp, fam_name, fam_user, imported_at, title, date_, sources, uids in rows:
        fam = out.setdefault(fam_key, {"name": fam_name or fam_key, "events": {}})
        if fam_user:
            fam["user"] = True
        if imported_at:
            fam["imported_at"] = imported_at
        if not fp:
            continue  # a family-marker row (no event)
        fam["events"][fp] = {
            "title": title,
            "date": date_,
            "sources": _json_list(sources),
            "uids": _json_list(uids),
        }
    return out


def count() -> int:
    """Number of stored event rows (marker rows for empty families included). 0 on error."""
    path = _db_path()
    if path is None:
        return 0
    try:
        conn = _open(path)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])  # noqa: S608  # nosec B608 - {TABLE} constant, no input
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - missing table / locked DB -> 0
        return 0
