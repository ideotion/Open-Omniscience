"""
Panic wipe — a deliberate, confirmed destruction of the local data directory.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

For a journalist who must remove the corpus, keys and caches *now* (e.g. an imminent
seizure). It delegates to the two-phase secure wipe in ``crypto_erase`` (audit OO-02):
the quick pass destroys the SQLCipher salt page, so the encrypted corpus is
permanently unrecoverable at ANY size (the old implementation overwrote only the first
4 MiB of each file, leaving most of a multi-GB corpus intact). It stays **honest about
the limit**: a byte-overwrite does not guarantee old blocks are gone on SSD/flash/CoW
media — the guarantee is the destroyed key. An optional full free-space scrub
(``crypto_erase.full_secure_erase``) is the defence-in-depth layer on top. Refuses to
run without an explicit confirmation.
"""

from __future__ import annotations

import threading
from pathlib import Path

# Re-exported for callers/tests that referenced the honest-limit note here.
from src.safety.crypto_erase import _LIMIT_NOTE  # noqa: F401


def panic_wipe(data_dir: Path | None = None, *, confirm: bool = False) -> dict:
    """Instantly crypto-erase, then delete everything under the data dir. Requires
    ``confirm``. Returns the ``quick_crypto_erase`` summary (``files_seen`` /
    ``files_wiped`` / ``data_dir`` / ``limit`` preserved for existing callers)."""
    if not confirm:
        raise PermissionError("panic_wipe requires confirm=True (this is irreversible)")
    from src.database.connect import invalidate_header_cache
    from src.safety.crypto_erase import quick_crypto_erase

    _close_database_now()
    try:
        return quick_crypto_erase(confirm=True, data_dir=data_dir, hold_for_rescrub=True)
    finally:
        # S3.6: the store file is gone. A cached header saying "plaintext" would
        # let the lock middleware answer requests for a corpus that no longer
        # exists -- in a `finally` because a partial wipe still removed it.
        from src.ingest import activate_kill_switch

        # A wipe takes the app offline for good, and that comes FIRST: the next settings read is a first run (defaults, which are
        # direct), and a process still running online must not rebuild a followed session (wiki, ORES, hazards, markets) from it.
        try:
            activate_kill_switch()
        finally:
            invalidate_header_cache()
            from src.config.kv_store import kv_invalidate

            kv_invalidate()  # the settings cache and the stores seen: a wiped store is not a vanished one
            from src.api import served_cache

            served_cache.invalidate()  # the served counts (and the status scans carried beside them) belong to the file that is gone
            _dispose_after_erase()


def _close_database_now() -> None:
    """Close the database to the writers that could recreate the store after the wipe, waiting on NOTHING (R689 follow-up (1)):
    collection is held and told to stop, every background job is asked to stop and refused from this instant (its next statement or
    commit raises), and so are the collector's own threads (the scheduler loop, its ``oo-collect`` workers, the briefing and
    housekeeping lanes), which the graceful stop leaves to their own joins. A wipe races a seizure, so no step joins a thread, and a
    step that fails never stops the wipe.

    NOT covered, stated: the import queue, the re-index managers, the backup threads and the request threads keep running and can
    still check out a connection; with the data folder removed by the erase, a new store has nowhere to go but is not refused here.
    A transaction already under way when the erase runs (a custody append, one of those threads) can still commit into the unlinked
    files; :func:`_dispose_after_erase` rewrites them again through descriptors the erase kept, and a commit later than its last pass
    is the window left. The pool is disposed AFTER the erase, never before: closing the last connection on a live file runs SQLite's
    write-back of its log, which can be hundreds of MiB, and that must not stand between the panic and the destroyed key."""
    try:
        from src.scheduler.runner import pause_for_exclusive_operation

        # The hold blocks "Run now"; the loop is signalled, never joined. It is never released, on purpose (R383's counted hold): the
        # corpus is gone and the app must be restarted, so nothing may start collection on this process again.
        pause_for_exclusive_operation(timeout=0.0)
        global _HOLDS_TAKEN
        _HOLDS_TAKEN += 1  # counted, so the test suite can give back exactly the holds a wipe took and no others
    except Exception:  # noqa: BLE001 - never stops the wipe  # nosec B110
        pass
    try:
        from src.database.after_shutdown import refuse_threads, stop_jobs_and_close

        stop_jobs_and_close(0.0)
        refuse_threads([(t, t.name) for t in threading.enumerate() if t.name.startswith(_COLLECTOR_THREADS)])
    except Exception:  # noqa: BLE001 - never stops the wipe  # nosec B110
        pass


#: How many collection holds the wipe has taken in this process (never released; read by the test suite's isolation).
_HOLDS_TAKEN = 0

#: The collector's own threads, refused by name on the panic path only (the graceful stop joins them).
_COLLECTOR_THREADS = ("oo-scheduler", "oo-collect", "oo-briefing-bg", "oo-housekeeping-lane")


# A custody append can hold its transaction open across an OpenTimestamps call of up to 10 s (src/custody/log.py), so
# the last pass over the unlinked files comes after that.
_LATE_RESCRUB_S = 15.0


def _dispose_after_erase() -> None:
    """Close the pool once the key is gone, then rewrite through the kept descriptors what a transaction already under way
    put back into the unlinked files (its commit writes page 1, salt included): once now, and once more after
    :data:`_LATE_RESCRUB_S` on a timer that never holds the wipe up. Never raises."""
    try:
        from src.database.session import dispose_engine

        dispose_engine()
    except Exception:  # noqa: BLE001 - the wipe is done; this is tidying  # nosec B110
        pass
    try:
        from src.safety.crypto_erase import rescrub_held

        if rescrub_held(close=False):
            late = threading.Timer(_LATE_RESCRUB_S, rescrub_held, kwargs={"close": True})
            late.name = "oo-panic-rescrub"
            late.daemon = True
            late.start()
    except Exception:  # noqa: BLE001 - never raises  # nosec B110
        pass
