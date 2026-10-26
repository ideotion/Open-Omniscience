"""The write-back at the end of the process: the log goes into the database BEFORE the pool is disposed, from a connection of its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THE DISPOSAL ALONE DOES NOT DO IT. SQLite writes the ``-wal`` back into the database, and removes it, when the LAST connection on
the file closes. ``Engine.dispose()`` closes the connections that are IN the pool; one a thread still has checked out stays open, so with a
single straggler nothing is written back and nothing says so (``dispose_engine`` returns the pool's count for that reason). A busy
collector is exactly that case: the scheduler's stop gives up after 10 s while a pass is mid-fetch or mid-write, and on a small machine
most pooled connections are checked out at any instant. MEASURED (17 Oct 2026, SQLite 3.45.1 and sqlcipher3, the app's own engine,
``connect()`` and ``dispose_engine()``, a reader pinning a 300 MiB log): every connection back in the pool, log gone; one connection still
checked out, idle or inside a read, 100 % of the log left, plain and encrypted. The next open then pays the write-back: 90.8 s of the
92.1 s unlock after the 10-10 session of the field, 1.41 GB of log, on a session the sentinel called ``clean``.

WHAT THIS DOES. One ``PRAGMA wal_checkpoint(TRUNCATE)`` through ``execute`` (which releases the GIL, where sqlcipher3's ``close()`` holds it
for the whole checkpoint it runs on the last connection) from a connection opened here, with the busy timeout at 0 first, so it NEVER waits
for a reader. MEASURED, same harness: a straggler that is idle, the log is emptied in 2.24 s (300 MiB, encrypted). A straggler INSIDE a read
gives one of two answers, and which one depends on where the reader's snapshot lies (26 Oct 2026, plain store, SQLite 3.45.1):

* its snapshot is OLDER than every frame (the reader began before the writes): nothing is safe to copy, ``(busy 1, n, 3)`` comes back at
  once (214 MB of log, 0.00 s) and the log is as it was;
* its snapshot is NEWER than the frames (a pass that began its read after the writes, the common shape): TRUNCATE first copies every frame
  the reader does not need and only then finds the reader, so the whole write-back runs (``(1, n, n)``, 214 MB in 1.1 to 1.4 s) and the
  answer is still ``busy``. The file keeps its size, and its contents are in the database. The reader's close as the LAST connection then
  has nothing left to copy and removes the log (107 MB: 0.07 s against the step's 0.68 s); a kill before that close leaves the log, and the
  next open's recovery is expected to copy it again (not measured). ``copied_all`` tells the two apart and the record carries it.

``busy`` is therefore "a reader, a writer or another checkpoint held the log", not "a reader held it and nothing was written": a writer
caught mid-write, or a storage-guard drain still running on the checkpoint lock, gives it too (the last number of the answer is then -1,
the checkpoint lock being what was busy). The answer is recorded either way (``storage_events`` ``checkpoint`` / ``shutdown``, and the
facts the sentinel carries, ``forensics.dispose_facts``): a log that is left is a recorded fact, and a ``clean`` sentinel never stands for a
clean log.

NO TIME CAP (ruled 17 Oct, D1): the step takes as long as the write-back (about 90 s for 1.4 GB on the field disk), because the next open
pays the same time anyway and a kill in the middle is safe, SQLite recovers from the start and it is never worse than skipping except for
the wait at exit. NO WAIT FOR A STRAGGLER (D2): a connection inside a read leaves the log (or, with a recent snapshot, leaves it written
back and not truncated) and the record says so; a wait would be a number invented before the first bundle says how often that happens.

THE CONNECTION IS NOT THE POOL'S. A checkout would wait ``pool_timeout`` behind the very workers that are the reason for the step; this one
is opened by the connection factory, which the unlock path's verify connection already uses, and closed here. It is opened only for a store
this process opened (``locked_state``): a locked or fresh store has no connection of ours and no log of ours, and opening it would create a
file or fail with the typed key absent.

THE SWAP LOCK IS HELD ACROSS THE WHOLE STEP (open, checkpoint, close), by ``library_generation.connecting()``. That lock exists so that no
connection to the file is being opened while a restore or repair swaps it in, and this connection is raw: the pool's stamp never reaches it
and nothing refuses it. Without the lock a swap could land during the step (a restore runs on the import-queue thread, which the lifespan
never stops), and this connection's close, as the last on the OLD file, would remove the ``-wal`` and ``-shm`` BY NAME, names that by then
belong to the new file. With it a swap that arrives mid-step waits for the step up to its own bound and then refuses with ``LibraryBusy``
and the file unswitched (honest on a process that is going down), and a step that arrives mid-swap waits for the swap, which D1 allows.

NEVER RAISES an ``Exception``: the disposal that follows must run whatever this did. Failures are named by class (R140: an engine's words
can quote what it was handed).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("database.shutdown_checkpoint")


def _wal_bytes(db: Path) -> int | None:
    """The ``-wal``'s size now: ``0`` when there is no such file (SQLite removes it when it is written back), ``None`` when it cannot be
    read."""
    try:
        return Path(str(db) + "-wal").stat().st_size
    except FileNotFoundError:
        return 0
    except OSError:
        return None


def _store_path() -> tuple[Path | None, str | None]:
    """The database file the pool's connections are opened on (``session.DB_FILE``, the creator's own string: not SQLAlchemy's decoded
    ``engine.url.database``, which drops a ``?`` suffix and un-escapes ``%``), or ``None`` and the reason code."""
    from src.database.session import DB_FILE

    if DB_FILE is None:
        return None, "not sqlite"
    if not DB_FILE or DB_FILE == ":memory:":
        return None, "no file"
    return Path(DB_FILE), None


def checkpoint_before_dispose(path: Path | str | None = None) -> dict[str, Any]:
    """Write the log back into the database without waiting for anyone, and say what happened.

    ``outcome`` is ``done`` (the TRUNCATE ran and nothing held the log), ``busy`` (a reader, a writer or another checkpoint held it: see
    ``copied_all``), ``failed`` (``error`` is the exception class) or ``skipped`` (``why`` is a short code: ``not sqlite``, ``no file``,
    ``locked``, ``fresh``). ``truncate`` is the three numbers the PRAGMA answered (busy, log frames, checkpointed; the last two are -1
    when the checkpoint lock itself was busy); ``copied_all`` is, for ``busy``, whether every frame of the log was written back anyway
    (the reader's snapshot was newer than the frames) and ``None`` otherwise. ``wal_bytes_before`` / ``wal_bytes_after`` are the file's size
    around the step, ``None`` when unreadable. ``path`` defaults to the engine's file; ``wal_path`` is the log of the file the step looked
    at, so the facts that follow read the same one."""
    out: dict[str, Any] = {
        "outcome": "skipped",
        "seconds": None,
        "truncate": None,
        "copied_all": None,
        "wal_bytes_before": None,
        "wal_bytes_after": None,
        "wal_path": None,
    }
    began = time.monotonic()
    try:
        from src.database import library_generation
        from src.database.connect import connect, locked_state
        from src.monitoring import storage_events

        db: Path | None
        why: str | None
        db, why = (Path(path), None) if path is not None else _store_path()
        if db is not None:
            out["wal_path"] = str(db) + "-wal"
        if db is None:
            out["why"] = why
        elif not db.exists():
            out["why"] = "no file"
        elif (state := locked_state(db)) not in ("unlocked-plaintext", "unlocked-encrypted"):
            out["why"] = state  # "locked" or "fresh": this process never opened it
        else:
            out["wal_bytes_before"] = _wal_bytes(db)
            with library_generation.connecting():
                conn = connect(db, check_same_thread=False)
                try:
                    conn.execute("PRAGMA busy_timeout = 0")
                    step = time.monotonic()
                    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    out["seconds"] = round(time.monotonic() - step, 3)
                finally:
                    try:
                        conn.close()
                    except Exception as exc:  # noqa: BLE001 - the answer below stands; a failed close is not the checkpoint's
                        log_failure(_LOG, "shutdown checkpoint: closing its connection failed", exc, level=logging.DEBUG)
            out["wal_bytes_after"] = _wal_bytes(db)
            if row is not None:
                out["truncate"] = [int(x) for x in row]
            busy = row is not None and int(row[0]) != 0
            out["outcome"] = "busy" if busy else "done"
            if row is not None and busy:
                out["copied_all"] = int(row[1]) > 0 and int(row[2]) >= int(row[1])
        try:
            storage_events.note_checkpoint(
                "shutdown",
                truncate=out["truncate"],
                seconds=out["seconds"],
                wal_before=out["wal_bytes_before"],
                wal_after=out["wal_bytes_after"],
                outcome="skipped" if out["outcome"] == "skipped" else "done",
                extra={"why": out["why"]} if out.get("why") else None,
            )
        except Exception as exc:  # noqa: BLE001 - the journal never decides the shutdown
            log_failure(_LOG, "shutdown checkpoint: could not record it in the storage journal", exc, level=logging.DEBUG)
    except Exception as exc:  # noqa: BLE001 - the disposal that follows runs whatever this did
        out["outcome"] = "failed"
        out["error"] = type(exc).__name__
        out["seconds"] = out["seconds"] if out["seconds"] is not None else round(time.monotonic() - began, 3)
        _LOG.warning("the log could not be written back before the engine was disposed (%s); the last connection's close will try", out["error"])
        try:
            from src.monitoring import storage_events

            storage_events.note_checkpoint(
                "shutdown", seconds=out["seconds"], wal_before=out["wal_bytes_before"], outcome="failed", error=out["error"]
            )
        except Exception as exc2:  # noqa: BLE001
            log_failure(_LOG, "shutdown checkpoint: could not record its failure in the storage journal", exc2, level=logging.DEBUG)
    return out
