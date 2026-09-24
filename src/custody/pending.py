"""Custody ingest entries that could not be written when their article was stored.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (CUST-1, field round 2026-09-24, ``docs/audit/16_…`` §3.4). Auto-log-on-ingest is
fail-open by design: a custody error must never cost the article. But nothing ever wrote
the entry afterwards, so the chain-of-custody log the operator had turned on carried
gaps that no surface reported -- 8, 13, 19 and 9 missing INGEST entries on four field
machines inside error logs covering only 16 to 48 hours, every one a pool timeout. The
article had been stored; reading its columns back after the commit needed a database
connection, and none was free.

WHAT THIS DOES
- :func:`note_failed` records the failure in a small append-only file,
  ``data/custody_pending.jsonl``, WITHOUT touching the database -- the failure it exists
  for is the database being unreachable.
- :func:`drain` records every pending entry it can, each MARKED LATE in its own signed
  metadata (``late: true``, when the article was stored, when the entry was finally
  written, and why it was late). The entry's position in the chain is its true position:
  it is appended now, and says so; nothing is back-dated and nothing is inserted into the
  past of an append-only log.
- :func:`gap_scan` finds stored articles with no INGEST entry since the log's first one,
  for the gaps from before this existed. It only COUNTS; queueing what it found is a
  separate, explicit act (:func:`queue_gaps`), because the app cannot tell a failure from
  a period when auto-log was switched off.

Nothing here touches the network. Every call degrades to a stated absence.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

PENDING_FILE = "custody_pending.jsonl"
_LOCK = threading.Lock()
#: The marker every late entry carries in its (signed) metadata, and the substring the
#: late count looks for in ``metadata_json`` (written with ``sort_keys=True``).
LATE_KEY = "late"
_LATE_NEEDLE = '"late": true'


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def pending_path() -> Path:
    from src.paths import data_dir

    return data_dir() / PENDING_FILE


def note_failed(article_id: int, *, item_hash: str | None = None, url: str | None = None,
                canonical_url: str | None = None, source_id: int | None = None,
                error: str = "", found_by: str = "ingest failure") -> bool:
    """Queue one entry that could not be written. A file append, never a database write;
    returns whether it was queued."""
    rec = {
        "article_id": int(article_id), "item_hash": item_hash, "url": url,
        "canonical_url": canonical_url, "source_id": source_id,
        "failed_at": _now_iso(), "error": str(error or "")[:300], "found_by": found_by,
    }
    try:
        with _LOCK:
            p = pending_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        return True
    except OSError:
        _LOG.warning("custody: could not queue the late entry for article %s", article_id, exc_info=True)
        return False


def read_pending() -> list[dict[str, Any]]:
    try:
        text = pending_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("article_id") is not None:
            out.append(rec)
    return out


def pending_count() -> int:
    return len(read_pending())


def _rewrite(items: list[dict[str, Any]]) -> None:
    p = pending_path()
    if not items:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            _LOG.debug("custody: could not remove the empty pending file", exc_info=True)
        return
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(i, separators=(",", ":")) + "\n" for i in items),
                   encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def late_count(log: Any = None) -> int | None:
    """How many INGEST entries in the log were recorded late (None when unreadable)."""
    own = log is None
    try:
        if own:
            from src.custody.log import CustodyLog

            log = CustodyLog()
        row = log.conn.execute(
            "SELECT COUNT(*) FROM custody_entries WHERE action = 'ingest' AND metadata_json LIKE ?",
            (f"%{_LATE_NEEDLE}%",),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 - a count is a disclosure, never a failure
        return None
    finally:
        if own and log is not None:
            with contextlib.suppress(Exception):
                log.close()


def _article_columns(article_id: int, session_factory: Any = None) -> dict[str, Any] | None:
    """The stored row's columns, read now. ``{}`` when the article no longer exists;
    raises when the database cannot be read (the entry then stays pending)."""
    from sqlalchemy import select

    from src.database.models import Article

    if session_factory is None:
        from src.database.session import session_scope as session_factory
    with session_factory() as db:
        row = db.execute(
            select(Article.hash, Article.url, Article.canonical_url, Article.source_id)
            .where(Article.id == int(article_id))
        ).first()
    if row is None:
        return {}
    return {"item_hash": row[0], "url": row[1], "canonical_url": row[2], "source_id": row[3]}


def drain(*, limit: int = 50, session_factory: Any = None, log_factory: Any = None) -> dict[str, Any]:
    """Record up to ``limit`` pending entries now, each marked late. An entry whose article
    already has an INGEST entry is dropped (it was written after all); one whose article is
    gone is dropped and counted; one whose columns cannot be read yet stays pending."""
    from src.custody.log import CustodyAction
    from src.custody.settings import load_settings

    with _LOCK:
        items = read_pending()
        if not items:
            return {"recorded": 0, "already_present": 0, "article_gone": 0, "still_pending": 0}
        todo, keep = items[:limit], items[limit:]
        recorded = already = gone = 0
        prefs = load_settings()
        if log_factory is None:
            from src.custody.log import CustodyLog as log_factory
        log = log_factory()
        try:
            for it in todo:
                aid = int(it["article_id"])
                item_id = f"article:{aid}"
                try:
                    if any(e.action == CustodyAction.INGEST.value for e in log.entries_for(item_id)):
                        already += 1
                        continue
                    cols = {k: it.get(k) for k in ("item_hash", "url", "canonical_url", "source_id")}
                    if not cols.get("item_hash"):
                        fresh = _article_columns(aid, session_factory)
                        if fresh == {}:
                            gone += 1
                            continue
                        assert fresh is not None
                        cols.update(fresh)
                    log.record(
                        item_id, str(cols["item_hash"]), CustodyAction.INGEST,
                        actor=prefs.default_actor or "ingest-pipeline",
                        metadata={
                            "url": cols.get("url"), "canonical_url": cols.get("canonical_url"),
                            "source_id": cols.get("source_id"),
                            LATE_KEY: True,
                            "stored_by": it.get("failed_at"),
                            "recorded_late_at": _now_iso(),
                            "late_reason": it.get("error") or it.get("found_by"),
                            "found_by": it.get("found_by"),
                        },
                    )
                    recorded += 1
                except Exception:  # noqa: BLE001 - this one waits for the next drain
                    _LOG.debug("custody: late entry for article %s still pending", aid, exc_info=True)
                    keep.append(it)
        finally:
            with contextlib.suppress(Exception):
                log.close()
        try:
            _rewrite(keep)
        except OSError:
            _LOG.warning("custody: could not rewrite the pending file", exc_info=True)
    return {"recorded": recorded, "already_present": already, "article_gone": gone, "still_pending": len(keep)}


def gap_scan(*, budget_s: float = 60.0, batch: int = 5000, session_factory: Any = None,
             log_factory: Any = None) -> dict[str, Any]:
    """Stored articles with no INGEST entry, from the log's first ingest entry on. Read-only
    and bounded by ``budget_s``: a scan that runs out says where it stopped."""
    from sqlalchemy import select

    from src.database.models import Article

    if log_factory is None:
        from src.custody.log import CustodyLog as log_factory
    log = log_factory()
    try:
        rows = log.conn.execute(
            "SELECT item_id FROM custody_entries WHERE action = 'ingest' AND item_id LIKE 'article:%'"
        ).fetchall()
    finally:
        with contextlib.suppress(Exception):
            log.close()
    logged: set[int] = set()
    for (item_id,) in rows:
        tail = str(item_id).split(":", 1)[-1]
        if tail.isdigit():
            logged.add(int(tail))
    queued = {int(i["article_id"]) for i in read_pending()}
    method = ("every article id at or after the custody log's first INGEST entry, compared "
              "with the log's INGEST entries; an article already queued to be recorded late "
              "is counted apart. The app cannot tell a failed write from a period when "
              "auto-log was switched off, so this counts and never records on its own.")
    if not logged:
        return {"since_article_id": None, "checked": 0, "missing": 0, "missing_sample": [],
                "already_queued": len(queued), "complete": True, "method": method,
                "note": "the custody log holds no ingest entry yet, so there is no start to measure gaps from"}
    first = min(logged)
    if session_factory is None:
        from src.database.session import session_scope as session_factory
    missing: list[int] = []
    already_queued = 0
    checked = 0
    last_id = first - 1
    complete = False
    t0 = time.monotonic()
    with session_factory() as db:
        while time.monotonic() - t0 < budget_s:
            ids = db.execute(
                select(Article.id).where(Article.id > last_id).order_by(Article.id).limit(batch)
            ).scalars().all()
            if not ids:
                complete = True
                break
            for i in ids:
                checked += 1
                if i in logged:
                    continue
                if i in queued:
                    already_queued += 1
                else:
                    missing.append(int(i))
            last_id = int(ids[-1])
    return {
        "since_article_id": first, "checked": checked, "missing": len(missing),
        "missing_ids": missing, "missing_sample": missing[:20], "already_queued": already_queued,
        "complete": complete, "scanned_up_to_id": last_id, "budget_s": budget_s, "method": method,
    }


def queue_gaps(article_ids: list[int]) -> int:
    """Queue the articles a gap scan found, to be recorded late. The operator's act."""
    n = 0
    for aid in article_ids:
        if note_failed(int(aid), error="no ingest entry was found for this article by the gap scan",
                       found_by="gap scan"):
            n += 1
    return n
