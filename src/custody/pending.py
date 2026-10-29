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
- A queue line that cannot be read (a write cut short by a full disk or a power cut, bytes that are not text, JSON that is
  not a record) is never read as a record, never glued to the next one (:func:`_append` closes a file that ends mid-line
  first), and never erased unseen: it is reported once per process by line number and byte length (never its text) and,
  when the queue is rewritten, kept byte for byte in ``data/custody_pending.unreadable`` (left in the queue instead if
  that file cannot be written). A file that cannot be READ is not an empty queue: it is left exactly as it is.
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
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure, record_text

_LOG = logging.getLogger(__name__)

PENDING_FILE = "custody_pending.jsonl"
#: Where a queue line that is not a usable record is kept, byte for byte, when the queue is rewritten (beside the queue,
#: same sensitivity: a line can hold a url).
UNREADABLE_FILE = "custody_pending.unreadable"
#: The largest integer a SQLite column holds, and so the largest ``article_id`` the drain's column read can bind: a larger one
#: raises ``OverflowError`` there and would stop every entry that has no hash from being written.
_SQLITE_MAX_INT = 2**63 - 1
#: ``(line number, byte length, crc32)`` of each unreadable line already reported by this process, so a queue read on every
#: pass logs it once. Pruned to the lines the file holds now, so it never outgrows the file.
_REPORTED_UNREADABLE: set[tuple[int, int, int]] = set()
_REPORT_LOCK = threading.Lock()
#: Guards the pending FILE: every append, every rewrite and every read of its bytes (so an append in progress is never read half
#: written), and only that. NOT re-entrant: :func:`read_pending`, :func:`pending_count` and :func:`_read_locked` take it, so they
#: must never be called while holding it (that is a hang, not an error; the tail of :func:`drain` calls :func:`_read_all`).
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


def _ends_mid_line(p: Path) -> bool:
    """Whether ``p`` holds bytes and does not end in a newline: a write that was cut short (a full disk, a power cut) left its tail."""
    try:
        with open(p, "rb") as fh:
            fh.seek(-1, os.SEEK_END)  # an empty file has no last byte (OSError), as a missing one has none
            return fh.read(1) != b"\n"
    except OSError:  # no file, an empty one, or one that cannot be read: nothing to close off
        return False


def _append_bytes(p: Path, data: bytes) -> None:
    """The one place this module appends to a file (the caller holds ``_LOCK``): the queue, and the file unreadable lines are set aside in."""
    with open(p, "ab") as fh:
        fh.write(data)


def _append(records: list[dict[str, Any]]) -> bool:
    """One append for any number of records; a file write, never a database one.

    A file that ends mid-line is closed with a newline first, so the cut-short text stays a line of its own and the record
    appended now is not glued onto it (both would be unreadable)."""
    if not records:
        return True
    try:
        with _LOCK:
            p = pending_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            lead = "\n" if _ends_mid_line(p) else ""
            _append_bytes(p, (lead + "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)).encode("utf-8"))
        return True
    except OSError as exc:
        log_failure(_LOG, f"custody: could not queue {len(records)} late entr(ies)", exc, level=logging.WARNING)
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


def _read_bytes() -> bytes:
    """The queue file's bytes, empty when it is not there; the caller holds ``_LOCK``. A file that is there and cannot be read
    raises ``OSError``, never reads as an empty queue (a rewrite from an "empty" read deletes every record still owed)."""
    try:
        return pending_path().read_bytes()
    except FileNotFoundError:
        return b""


def _parse(data: bytes) -> tuple[list[dict[str, Any]], list[tuple[int, bytes]]]:
    """``(records, unreadable)``: the usable records of the queue and, as ``(line number, bytes)``, every non-blank line that is
    not one (cut short, not JSON, not text, or JSON without a positive integer ``article_id`` a column can hold). The file is read
    as bytes so that a line that is not text is one unreadable line, not an error that stops the whole queue from being read."""
    out: list[dict[str, Any]] = []
    unreadable: list[tuple[int, bytes]] = []
    for number, raw in enumerate(data.split(b"\n"), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, RecursionError):  # a JSON error, bytes that are not text, or nesting too deep to parse
            rec = None
        aid = rec.get("article_id") if isinstance(rec, dict) else None
        # the writers store int(article_id) of a real row; a bool is an int to Python
        if isinstance(aid, int) and not isinstance(aid, bool) and 0 < aid <= _SQLITE_MAX_INT:
            out.append(rec)
        else:
            unreadable.append((number, raw))
    return out, unreadable


def _read_all() -> tuple[list[dict[str, Any]], list[tuple[int, bytes]]]:
    """:func:`_read_bytes` then :func:`_parse`, for a caller that holds ``_LOCK`` (the drain's final re-read, which must see the
    file it then replaces)."""
    return _parse(_read_bytes())


def _read_locked() -> tuple[list[dict[str, Any]], list[tuple[int, bytes]]]:
    """As :func:`_read_all` for a caller that does not hold ``_LOCK``: the lock is held for the bytes only, so a parse of a large
    queue never makes an ingest thread's :func:`note_failed` wait for it."""
    with _LOCK:
        data = _read_bytes()
    return _parse(data)


def _report_unreadable(unreadable: list[tuple[int, bytes]]) -> None:
    """One warning per unreadable line this process has not reported yet. It is handed the lines and passes on only their line
    number, byte length and crc32: the text of a line never reaches a log record."""
    keys = {(number, len(raw), zlib.crc32(raw)) for number, raw in unreadable}
    with _REPORT_LOCK:
        fresh = sorted(k for k in keys if k not in _REPORTED_UNREADABLE)
        _REPORTED_UNREADABLE.intersection_update(keys)
        _REPORTED_UNREADABLE.update(fresh)
    for number, size, _crc in fresh:
        _LOG.warning(
            "custody: line %d of the pending queue (%d bytes) is not a usable record and is not read; a drain that rewrites the "
            "queue keeps it, whole, in %s (its text is not logged)", number, size, UNREADABLE_FILE)


def read_pending() -> list[dict[str, Any]]:
    """The usable records of the queue, read under the file lock so that an append in progress is never read half written (and
    reported as an unreadable line). A file that cannot be read is logged and reads as no records here; the rewrite does not
    take that reading for an empty queue (:func:`drain`)."""
    try:
        records, unreadable = _read_locked()
    except OSError as exc:
        log_failure(_LOG, "custody: could not read the pending file", exc, level=logging.WARNING)
        return []
    _report_unreadable(unreadable)
    return records


def pending_count() -> int:
    return len(read_pending())


def _set_aside(unreadable: list[tuple[int, bytes]]) -> bool:
    """Append the unreadable lines, byte for byte, to :data:`UNREADABLE_FILE`; whether that was done."""
    side = pending_path().with_name(UNREADABLE_FILE)
    try:
        lead = b"\n" if _ends_mid_line(side) else b""  # a copy that stopped part way must not take the next one onto its line
        _append_bytes(side, lead + b"".join(raw + b"\n" for _number, raw in unreadable))
    except OSError as exc:
        log_failure(_LOG, f"custody: {len(unreadable)} unreadable line(s) of the pending queue could not be set aside", exc,
                    level=logging.WARNING)
        return False
    _LOG.warning("custody: set aside %d unreadable line(s) of the pending queue into %s (line(s) %s; byte length(s) %s; text not logged)",
                 len(unreadable), side.name, ", ".join(str(n) for n, _raw in unreadable),
                 ", ".join(str(len(raw)) for _n, raw in unreadable))
    return True


def _rewrite(items: list[dict[str, Any]], unreadable: list[tuple[int, bytes]] | None = None) -> None:
    """The queue file becomes ``items``. The unreadable lines it held are set aside first (:func:`_set_aside`); if that cannot be
    done they are written back into the queue, so no line is ever erased unseen."""
    p = pending_path()
    kept = unreadable if unreadable and not _set_aside(unreadable) else []
    if not items and not kept:
        try:
            p.unlink(missing_ok=True)
        except OSError as exc:
            log_failure(_LOG, "custody: could not remove the empty pending file", exc, level=logging.DEBUG)
        return
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_bytes("".join(json.dumps(i, separators=(",", ":")) + "\n" for i in items).encode("utf-8")
                    + b"".join(raw + b"\n" for _number, raw in kept))
    os.replace(tmp, p)


#: How long the late count waits for a writer's commit (milliseconds). It protects the request thread, which is a settings read,
#: from queueing behind ingest: past it the count is reported unread, with the reason, never waited out.
_LATE_READ_BUSY_MS = 3000


def _late_count_on(conn: Any) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM custody_entries WHERE action = 'ingest' AND metadata_json LIKE ?",
        (f"%{_LATE_NEEDLE}%",),
    ).fetchone()
    return int(row[0]) if row else 0


def late_reading() -> dict[str, Any]:
    """The late count, read WITHOUT a :class:`CustodyLog`: ``{"count", "reason", "computed_at"}``.

    A plain read-only connection: no signer (no key unwrap), no process-wide append lock (which every ingest ``record`` holds, and
    which a settings read queued behind: measured 3.5-6 s of a 9-12 s read with 50 workers on 2 cores), no table creation. It
    never writes, so a log that does not exist yet reads 0 and is NOT created by being asked about. ``count`` is ``None`` when
    the log could not be read, and ``reason`` then names the CLASS of the failure (never the driver's words); a count carries the
    moment its read ENDED, because nothing here caches it.

    The wait for a writer is bounded at :data:`_LATE_READ_BUSY_MS` on the OPEN too, not only on the statement: an encrypted log is
    read once per page-size candidate while it is opened, under the connection's own timeout, so a bound set only afterwards
    did not hold (measured: an exclusive writer held for 10 s made an encrypted read wait 10.2 s, not 3 s).

    A log that a crashed write left a hot rollback journal beside cannot be recovered by a read-only open, and the driver reports that
    as a failed open (``WrongPassphraseError`` on an encrypted file); ``reason`` then says a journal is present, instead of leaving the
    class name to blame the passphrase.
    """
    out: dict[str, Any] = {"count": None, "reason": None, "computed_at": None}
    conn = None
    path = None
    try:
        from src.database.connect import connect
        from src.paths import data_dir

        path = data_dir() / "custody_log.db"
        try:
            conn = connect(path, read_only=True, timeout=_LATE_READ_BUSY_MS / 1000.0)
        except FileNotFoundError:
            out["count"] = 0  # no log yet: nothing was recorded late
            return out
        conn.execute(f"PRAGMA busy_timeout={_LATE_READ_BUSY_MS}")
        # The table's absence is asked, not read off an error's words: a log file whose table is not made yet has no entries.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'custody_entries'").fetchone() is None:
            out["count"] = 0
        else:
            out["count"] = _late_count_on(conn)
    except Exception as exc:  # noqa: BLE001 - a count is a disclosure, never a failure
        out["reason"] = type(exc).__name__
        try:
            journal = path.with_name(path.name + "-journal") if path is not None else None
            if journal is not None and journal.exists() and journal.stat().st_size > 0:
                out["reason"] += "; a rollback journal is present beside the log (an interrupted write, recovered by the next ingest)"
        except OSError:
            pass
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
        out["computed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return out


def late_count(log: Any = None) -> int | None:
    """How many INGEST entries in the log were recorded late (None when unreadable).

    Without a ``log`` this is :func:`late_reading`'s count; with one, it reads through that log's connection."""
    if log is None:
        return late_reading()["count"]
    try:
        return _late_count_on(log.conn)
    except Exception:  # noqa: BLE001 - a count is a disclosure, never a failure
        return None


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


def _ids_missing_columns(todo: list[dict[str, Any]]) -> list[int]:
    """Article ids of the entries that carry no ``item_hash``. A helper and not a comprehension in :func:`drain`: a loop written under
    ``with lock:`` has a back-edge outside the ``with``'s exception-table entry on CPython 3.13 (see ``src/utils/interrupts.py``)."""
    return sorted({int(it["article_id"]) for it in todo if not it.get("item_hash")})


def _not_settled(pending: list[dict[str, Any]], done: set[Any]) -> list[dict[str, Any]]:
    """The entries whose key is not in ``done`` (a helper, for the reason :func:`_ids_missing_columns` gives)."""
    return [it for it in pending if _key(it) not in done]


def _ingests_at(log: Any, item_id: str, ingest: str) -> list[Any]:
    """The INGEST entries at ``item_id`` (a helper, for the reason :func:`_ids_missing_columns` gives)."""
    return [e for e in log.entries_for(item_id) if e.action == ingest]


def drain(*, limit: int = 50, session_factory: Any = None, log_factory: Any = None,
          prefs: Any = None) -> dict[str, Any]:
    """Record up to ``limit`` pending entries now, each marked late. An entry whose article
    already has an INGEST entry FOR THE SAME CONTENT HASH is dropped (it was written after
    all); one whose article is gone is dropped and counted (``article_gone``, whether or not an
    INGEST entry of some earlier article sits at its id); one whose columns cannot be read
    yet stays pending, and a failed read is tried ONCE per drain, never once per entry.

    An INGEST entry at the id for OTHER content does not settle the entry (R365): ids are not
    unique over time (``articles.id`` has no AUTOINCREMENT, so a deletion, or a restore's swap
    discarding the articles committed after its working copy, hands the same ids out again),
    while the log is append-only and keeps the entry of the article that held the id before.
    Such an entry is written, marked ``earlier_ingest_other_hash``. When the hash cannot be
    learned yet (no hash on the record and the rows cannot be read) an entry already at the id
    cannot be judged, so the owed one stays queued instead of being dropped as present.

    Two locks, so a slow drain never holds up a failing ingest: ``_DRAIN_LOCK`` lets one
    drain run at a time (two could otherwise both find an entry missing and both record
    it), while the file lock is held only to read the queue and, at the end, to remove
    what this drain settled -- re-reading first, so an entry queued meanwhile survives."""
    from src.custody.log import CustodyAction

    with _DRAIN_LOCK:
        try:
            first, first_unreadable = _read_locked()
        except OSError as exc:  # not an empty queue: nothing is recorded and the file is left as it is
            log_failure(_LOG, "custody: could not read the pending file; nothing was drained", exc, level=logging.WARNING)
            return {"recorded": 0, "already_present": 0, "article_gone": 0, "still_pending": 0,
                    "queue_read_error": type(exc).__name__}
        _report_unreadable(first_unreadable)
        todo = first[:limit]
        if not todo:
            return {"recorded": 0, "already_present": 0, "article_gone": 0, "still_pending": 0}
        settled: list[dict[str, Any]] = []
        recorded = already = gone = 0
        need = _ids_missing_columns(todo)
        read: dict[int, dict[str, Any]] | None = {}
        read_error: str | None = None
        if need:
            try:
                read = _columns_for(need, session_factory)
            except Exception as exc:  # noqa: BLE001 - those entries wait for the next drain
                read, read_error = None, record_text(exc, typed=True, limit=200)
                log_failure(_LOG, "custody: owed entries' columns could not be read yet", exc, level=logging.DEBUG)
        if prefs is None:
            # Only the actor name comes from here, so an unreadable setting (the settings
            # live in the same database whose pool may be the problem) costs the name,
            # never the entries.
            try:
                from src.custody.settings import load_settings

                prefs = load_settings()
            except Exception as exc:  # noqa: BLE001 - fall back to the pipeline's own actor name
                log_failure(_LOG, "custody: settings unreadable during a drain", exc, level=logging.DEBUG)
        actor = getattr(prefs, "default_actor", None) or "ingest-pipeline"
        if log_factory is None:
            from src.custody.log import CustodyLog as log_factory
        log = log_factory()
        try:
            for it in todo:
                aid = int(it["article_id"])
                item_id = f"article:{aid}"
                try:
                    other_hash_at_id = False
                    ingests = _ingests_at(log, item_id, CustodyAction.INGEST.value)
                    if ingests:
                        # The hash this entry is owed for: the record's own, else the stored row's (the read above;
                        # absent when the article is gone, or when the read failed -- ``read`` is then None).
                        want = it.get("item_hash") or ((read or {}).get(aid) or {}).get("item_hash")
                        if want:
                            if any(e.item_hash == want for e in ingests):
                                already += 1
                                settled.append(it)
                                continue
                            other_hash_at_id = True
                        # No hash to compare: the read failed (the entry stays queued, below, whoever is at the id) or
                        # the article is gone (counted gone, below), never "present".
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
                            **({"earlier_ingest_other_hash": True} if other_hash_at_id else {}),
                        },
                    )
                    recorded += 1
                    settled.append(it)
                except Exception as exc:  # noqa: BLE001 - this one waits for the next drain
                    log_failure(_LOG, f"custody: late entry for article {aid} still pending", exc, level=logging.DEBUG)
        finally:
            with contextlib.suppress(Exception):
                log.close()
        done = {_key(it) for it in settled}
        queue_error: str | None = None
        with _LOCK:
            try:
                records, unreadable = _read_all()
            except OSError as exc:  # not an empty queue: the file is left exactly as it is
                log_failure(_LOG, "custody: could not re-read the pending file; it is left as it is", exc, level=logging.WARNING)
                queue_error = type(exc).__name__
                remaining = _not_settled(todo, done)  # what this drain read; the file may hold more
            else:
                remaining = _not_settled(records, done)
                try:
                    _rewrite(remaining, unreadable)
                except OSError as exc:
                    log_failure(_LOG, "custody: could not rewrite the pending file", exc, level=logging.WARNING)
    out: dict[str, Any] = {"recorded": recorded, "already_present": already, "article_gone": gone,
                           "still_pending": len(remaining)}
    if read_error:
        out["read_error"] = read_error
    if queue_error:
        out["queue_read_error"] = queue_error  # still_pending is then a lower bound
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
