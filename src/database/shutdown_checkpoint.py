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
for a reader. MEASURED, same harness: a straggler that is idle, the log is emptied in 2.24 s (300 MiB, encrypted); a straggler inside a
read, ``(busy 1, ...)`` comes back at once and the log is left as it was. The answer is recorded either way (``storage_events``
``checkpoint`` / ``shutdown``, and the facts the sentinel carries, ``forensics.dispose_facts``): a log that is left is a recorded fact, and
a ``clean`` sentinel never stands for a clean log.

NO TIME CAP (ruled 17 Oct, D1): the step takes as long as the write-back (about 90 s for 1.4 GB on the field disk), because the next open
pays the same time anyway and a kill in the middle is safe, SQLite recovers from the start and it is never worse than skipping except for
the wait at exit. NO WAIT FOR A STRAGGLER (D2): a connection inside a read leaves the log and the record says so; a wait would be a number
invented before the first bundle says how often that happens.

THE CONNECTION IS NOT THE POOL'S. A checkout would wait ``pool_timeout`` behind the very workers that are the reason for the step, and its
open would take a shared level of the library lock; this one is opened by the connection factory, which the unlock path's verify
connection already uses, and closed here. It is opened only for a store this process opened (``locked_state``): a locked or fresh store has
no connection of ours and no log of ours, and opening it would create a file or fail with the typed key absent.

NEVER RAISES an ``Exception``: the disposal that follows must run whatever this did. Failures are named by class (R140: an engine's words can
quote what it was handed).
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


def _store_path() -> Path | None:
    """The engine's database file, or ``None`` when it has none (an in-memory URL)."""
    from src.database.session import engine

    name = engine.url.database
    if not name or name == ":memory:":
        return None
    return Path(name)


def checkpoint_before_dispose(path: Path | str | None = None) -> dict[str, Any]:
    """Write the log back into the database without waiting for anyone, and say what happened.

    ``outcome`` is ``done`` (the TRUNCATE ran and no reader held the log), ``busy`` (a reader held it: the log is as it was),
    ``failed`` (``error`` is the exception class) or ``skipped`` (``why``). ``truncate`` is the three numbers the PRAGMA answered
    (busy, log frames, checkpointed); ``wal_bytes_before`` / ``wal_bytes_after`` are the file's size around the step, ``None`` when
    unreadable. ``path`` defaults to the engine's file."""
    out: dict[str, Any] = {"outcome": "skipped", "seconds": None, "truncate": None, "wal_bytes_before": None, "wal_bytes_after": None}
    began = time.monotonic()
    try:
        from src.database.connect import connect, locked_state
        from src.monitoring import storage_events

        db = Path(path) if path is not None else _store_path()
        if db is None:
            out["why"] = "the engine has no database file"
        elif not db.exists():
            out["why"] = "there is no database file"
        elif (state := locked_state(db)) not in ("unlocked-plaintext", "unlocked-encrypted"):
            out["why"] = f"the store is {state}: this process never opened it"
        else:
            out["wal_bytes_before"] = _wal_bytes(db)
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
            out["outcome"] = "busy" if row is not None and int(row[0]) != 0 else "done"
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
