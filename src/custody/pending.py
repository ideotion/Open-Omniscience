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
  past of an append-only log. The stored columns it needs are read in ONE query per
  :data:`_READ_CHUNK` entries, never one per entry.
- :func:`drain_owed` is the automatic repayment, called at the END OF A COLLECTION PASS
  and never on the per-article path: the read a drain needs competes for the very pool
  whose exhaustion created the debt, and one ingest must never wait out a pool timeout
  to pay for another's.
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
#: Guards every read-modify-write of the pending FILE, and only that.
_LOCK = threading.Lock()
#: One drain at a time: two could otherwise both find an entry missing and both record it.
_DRAIN_LOCK = threading.Lock()
#: The marker every late entry carries in its (signed) metadata, and the substring the
#: late count looks for in ``metadata_json`` (written with ``sort_keys=True``).
LATE_KEY = "late"
_LATE_NEEDLE = '"late": true'
#: Stored-row columns are read this many ids per query (well under SQLite's bound-
#: parameter limit on every version the app supports).
_READ_CHUNK = 500
#: How many owed entries one collection pass writes, at most. The field debt was 8 to 19
#: entries per day or two; a bounded tail keeps a pass's end predictable when it is larger.
DRAIN_PER_PASS = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def pending_path() -> Path:
    from src.paths import data_dir

    return data_dir() / PENDING_FILE


def _append(records: list[dict[str, Any]]) -> bool:
    """One append for any number of records; a file write, never a database one."""
    if not records:
        return True
    try:
        with _LOCK:
            p = pending_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
        return True
    except OSError:
        _LOG.warning("custody: could not queue %d late entr(ies)", len(records), exc_info=True)
        return False


def _record(article_id: int, *, item_hash: str | None = None, url: str | None = None,
            canonical_url: str | None = None, source_id: int | None = None,
            error: str = "", found_by: str = "ingest failure") -> dict[str, Any]:
    return {
        "article_id": int(article_id), "item_hash": item_hash, "url": url,
        "canonical_url": canonical_url, "source_id": source_id,
        "failed_at": _now_iso(), "error": str(error or "")[:300], "found_by": found_by,
    }


def note_failed(article_id: int, *, item_hash: str | None = None, url: str | None = None,
                canonical_url: str | None = None, source_id: int | None = None,
                error: str = "", found_by: str = "ingest failure") -> bool:
    """Queue one entry that could not be written. A file append, never a database write;
    returns whether it was queued."""
    return _append([_record(article_id, item_hash=item_hash, url=url, canonical_url=canonical_url,
                            source_id=source_id, error=error, found_by=found_by)])


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


def _columns_for(ids: list[int], session_factory: Any = None) -> dict[int, dict[str, Any]]:
    """The stored rows' columns, read now: ONE query per :data:`_READ_CHUNK` ids. An id
    absent from the result no longer exists; raises when the database cannot be read
    (every entry that needed the read then stays pending)."""
    from sqlalchemy import select

    from src.database.models import Article

    if session_factory is None:
        from src.database.session import session_scope as session_factory
    out: dict[int, dict[str, Any]] = {}
    with session_factory() as db:
        for i in range(0, len(ids), _READ_CHUNK):
            chunk = ids[i:i + _READ_CHUNK]
            for row in db.execute(
                select(Article.id, Article.hash, Article.url, Article.canonical_url, Article.source_id)
                .where(Article.id.in_(chunk))
            ):
                out[int(row[0])] = {"item_hash": row[1], "url": row[2], "canonical_url": row[3],
                                    "source_id": row[4]}
    return out


def _key(rec: dict[str, Any]) -> str:
    return json.dumps(rec, sort_keys=True, separators=(",", ":"))


def drain(*, limit: int = 50, session_factory: Any = None, log_factory: Any = None,
          prefs: Any = None) -> dict[str, Any]:
    """Record up to ``limit`` pending entries now, each marked late. An entry whose article
    already has an INGEST entry is dropped (it was written after all); one whose article is
    gone is dropped and counted; one whose columns cannot be read yet stays pending, and a
    failed read is tried ONCE per drain, never once per entry.

    Two locks, so a slow drain never holds up a failing ingest: ``_DRAIN_LOCK`` lets one
    drain run at a time (two could otherwise both find an entry missing and both record
    it), while the file lock is held only to read the queue and, at the end, to remove
    what this drain settled -- re-reading first, so an entry queued meanwhile survives."""
    from src.custody.log import CustodyAction

    with _DRAIN_LOCK:
        with _LOCK:
            todo = read_pending()[:limit]
        if not todo:
            return {"recorded": 0, "already_present": 0, "article_gone": 0, "still_pending": 0}
        settled: list[dict[str, Any]] = []
        recorded = already = gone = 0
        need = sorted({int(it["article_id"]) for it in todo if not it.get("item_hash")})
        read: dict[int, dict[str, Any]] | None = {}
        read_error: str | None = None
        if need:
            try:
                read = _columns_for(need, session_factory)
            except Exception as exc:  # noqa: BLE001 - those entries wait for the next drain
                read, read_error = None, f"{type(exc).__name__}: {exc}"[:200]
                _LOG.debug("custody: owed entries' columns could not be read yet", exc_info=True)
        if prefs is None:
            # Only the actor name comes from here, so an unreadable setting (the settings
            # live in the same database whose pool may be the problem) costs the name,
            # never the entries.
            try:
                from src.custody.settings import load_settings

                prefs = load_settings()
            except Exception:  # noqa: BLE001 - fall back to the pipeline's own actor name
                _LOG.debug("custody: settings unreadable during a drain", exc_info=True)
        actor = getattr(prefs, "default_actor", None) or "ingest-pipeline"
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
                        settled.append(it)
                        continue
                    cols = {k: it.get(k) for k in ("item_hash", "url", "canonical_url", "source_id")}
                    if not cols.get("item_hash"):
                        if read is None:
                            continue  # stays queued: its columns could not be read
                        fresh = read.get(aid)
                        if fresh is None:
                            gone += 1
                            settled.append(it)
                            continue
                        cols.update(fresh)
                    log.record(
                        item_id, str(cols["item_hash"]), CustodyAction.INGEST,
                        actor=actor,
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
                    settled.append(it)
                except Exception:  # noqa: BLE001 - this one waits for the next drain
                    _LOG.debug("custody: late entry for article %s still pending", aid, exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                log.close()
        done = {_key(it) for it in settled}
        with _LOCK:
            remaining = [it for it in read_pending() if _key(it) not in done]
            try:
                _rewrite(remaining)
            except OSError:
                _LOG.warning("custody: could not rewrite the pending file", exc_info=True)
    out: dict[str, Any] = {"recorded": recorded, "already_present": already, "article_gone": gone,
                           "still_pending": len(remaining)}
    if read_error:
        out["read_error"] = read_error
    return out


def drain_owed(*, limit: int = DRAIN_PER_PASS, session_factory: Any = None,
               log_factory: Any = None) -> dict[str, Any] | None:
    """The automatic repayment, for the END OF A COLLECTION PASS: write what earlier
    failures owe, while automatic custody logging is still on. None when nothing is owed
    (a file read, no database) or when the operator has since switched auto-log off --
    then the entries wait for the Chain of custody tab, which is the operator's act."""
    if not pending_count():
        return None
    from src.custody.settings import load_settings

    prefs = load_settings()
    if not prefs.auto_log_on_ingest:
        return None
    return drain(limit=limit, session_factory=session_factory, log_factory=log_factory, prefs=prefs)


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
    """Queue the articles a gap scan found, to be recorded late. The operator's act; one
    append for the whole list."""
    recs = [_record(int(aid), error="no ingest entry was found for this article by the gap scan",
                    found_by="gap scan") for aid in article_ids]
    return len(recs) if _append(recs) else 0
