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

import contextlib
import logging
import os
import sys
import threading
import time
from pathlib import Path

# Re-exported for callers/tests that referenced the honest-limit note here.
from src.safety.crypto_erase import _LIMIT_NOTE  # noqa: F401

_LOG = logging.getLogger(__name__)

#: How long the wipe waits for settings saves already in flight before it goes ahead without holding new ones.
_PANIC_HOLD_S = 2.0
#: What a settings save made during the wipe is told: it is refused at once, never kept waiting behind an erase that can take hours.
_PANIC_REFUSED = "A panic wipe is erasing this app's data, so this was not saved — nothing was written."

def panic_wipe(data_dir: Path | None = None, *, confirm: bool = False, off_drive_only: bool = False) -> dict:
    """Instantly crypto-erase, then delete everything under the data dir. Requires
    ``confirm``. Returns the ``quick_crypto_erase`` summary (``files_seen`` /
    ``files_wiped`` / ``data_dir`` / ``limit`` preserved for existing callers).

    A step of the tidying after a COMPLETED erase that fails is named in ``after_erase_failures`` and the report is still
    returned (row 35): before, an exception there made the endpoint answer 500 about an erase that had succeeded, and an
    operator racing a seizure was told the wipe failed when the key was already gone.

    ``off_drive_only`` (row 388, the panic CLI with its data drive not there): the operator agreed to erase only what is outside
    the drive, so a drive that is there again by the time the erase reads it is left whole (``drive_returned`` in the report)."""
    if not confirm:
        raise PermissionError("panic_wipe requires confirm=True (this is irreversible)")
    from src.paths import data_dir_path
    from src.safety.crypto_erase import (
        _drive_state,
        _latch,
        _pin_drive,
        finish_holder_check,
        finish_plaintext_rewrite,
        new_hold_generation,
        quick_crypto_erase,
    )

    _latch(Path(data_dir) if data_dir is not None else data_dir_path())  # R802: from the wipe's first step, not from the erase's
    # R812 (coordinator decision 1): the drive's state is read BEFORE the first close: a drive not there or not identifiable gets its
    # connections pinned, never closed (closing the last one deletes <db>-wal / -shm BY PATH, on whatever drive is there now). The
    # erase then takes the drive's identity and re-checks it before each of its own close points; a swap between this read and
    # that one is the window left for this close.
    if data_dir is None and _drive_state(data_dir_path()) in ("absent", "unidentified"):
        _pin_drive(data_dir_path())
    _close_database_now()
    generation = new_hold_generation()  # this wipe's own kept descriptors, closed by its own late pass (row 36)
    failed: list[str] = []
    # Settings writes are HELD from before the erase until after the tidying's settings_cache step (Lane E follow-up (a), the
    # security reads): a save from another thread is refused at once, in the wipe's own words, so nothing commits into the file
    # being erased and a value read from the old file never lands in a fresh one. The wipe waits at most _PANIC_HOLD_S for a save
    # already in flight; when the hold cannot be taken (that save, another holder) it goes ahead without it, and the epoch bumps
    # before the erase and in the tidying still refuse the saves made with ``expect_swap``. A save made AFTER the wipe has ended is
    # refused too (R802): the erase latched the data folder, and nothing in this process writes into it or makes it again until a restart.
    with _hold_settings_writes():
        try:
            # The store's swap epoch moves BEFORE the erase too: a save made from state read in the old file is refused from here.
            _settings_cache()
        except Exception as exc:  # noqa: BLE001 - never stops the wipe
            from src.monitoring.secret_scrub import log_failure

            log_failure(_LOG, "panic wipe: the settings cache could not be cleared before the erase", exc, level=logging.WARNING)
        erased = False  # the late pass is armed here only when the wipe stops before its last use of the kept descriptors
        try:
            report = quick_crypto_erase(confirm=True, data_dir=data_dir, hold_for_rescrub=True, hold_generation=generation,
                                        settle=False, off_drive_only=off_drive_only)
            erased = True
        finally:
            # In a `finally` because a partial wipe still removed the store.
            try:
                _tidy_after_erase(failed)
            except BaseException:
                erased = False
                raise
            finally:
                # whatever the tidying above did: the late-commit rewrite must still run. R813, stated: a drive found absent,
                # unidentified, changed or lost had its connections pinned by the erase, and this close skips them; a drive swapped
                # after the erase's last re-check and before this close is the window left for it (follow-up row 390).
                # The late pass is armed below, after the body rewrite and the holder check (both use the kept descriptors); here
                # only when the wipe is stopping on an exception, so that nothing below runs and the descriptors still go.
                try:
                    own_open = _dispose_after_erase(generation, arm_late=not erased)
                except BaseException:  # a Ctrl-C inside it: nothing below runs, so the late pass is armed here
                    _arm_late_rescrub(generation)
                    raise
    # R792: only now, with the app offline and this process's own pool closed (its close would undo the lock this takes), look
    # for ANOTHER process still holding the store and rewrite while it does, within the bound; the report says what was found.
    # R805 (a): this process's own connections a request thread still held when the pool was closed are a holder the probe cannot
    # see (one process's POSIX locks never conflict), so they are counted; not knowing is "unknown", never "none".
    try:
        report["own_connections_open"] = own_open
        from src.paths import erase_owned

        with erase_owned():  # the wipe's own rewrite through the descriptors it kept
            # R818 (b): a plaintext store's body is rewritten only now, its own pool disposed; not confirmed closed, it is left.
            finish_plaintext_rewrite(report, generation, own_open)
            finish_holder_check(report, generation)
    finally:
        _arm_late_rescrub(generation)
    if failed:
        report["after_erase_failures"] = failed
    from src.safety.crypto_erase import settle_removed

    settle_removed(report)  # R802 (5): measured after the wipe's last log line, and said truthfully
    return report


def _hold_settings_writes() -> contextlib.ExitStack:
    """The settings-write hold the wipe runs under, or an empty one when it cannot be taken: the wipe runs whatever the hold says."""
    hold = contextlib.ExitStack()
    try:
        from src.config.kv_store import hold_writes

        hold.enter_context(hold_writes(_PANIC_HOLD_S, refused_text=_PANIC_REFUSED, wait_s=0.0))
    except Exception as exc:  # noqa: BLE001 - the wipe runs whatever the hold says
        from src.monitoring.secret_scrub import log_failure

        log_failure(_LOG, "panic wipe: settings writes could not be held, wiping without the hold", exc, level=logging.WARNING)
    return hold


def _kill_switch() -> None:
    from src.ingest import activate_kill_switch

    activate_kill_switch()


def _header_cache() -> None:
    # S3.6: the store file is gone. A cached header saying "plaintext" would let the lock middleware answer requests for a
    # corpus that no longer exists.
    from src.database.connect import invalidate_header_cache

    invalidate_header_cache()


def _settings_cache() -> None:
    from src.config.kv_store import kv_invalidate

    kv_invalidate()  # the settings cache and the stores seen: a wiped store is not a vanished one


def _served_counts() -> None:
    from src.api import served_cache

    served_cache.invalidate()  # the served counts (and the status scans carried beside them) belong to the file that is gone


#: What follows an erase, in order, each named in the report when it fails. A wipe takes the app offline for good, and that
#: comes FIRST: the next settings read is a first run (defaults, which are direct), and a process still running online must
#: not rebuild a followed session (wiki, ORES, hazards, markets) from it.
_AFTER_ERASE = (("kill_switch", _kill_switch), ("header_cache", _header_cache), ("settings_cache", _settings_cache),
                ("served_counts", _served_counts))


def _tidy_after_erase(failed: list[str]) -> None:
    """Run every step of :data:`_AFTER_ERASE`; one that fails is logged (its text scrubbed), named in ``failed`` and never
    stops the next."""
    from src.monitoring.secret_scrub import log_failure

    for name, step in _AFTER_ERASE:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - the erase is done; the report says which step failed
            failed.append(name)
            log_failure(_LOG, f"after the erase, the {name} step failed", exc, level=logging.WARNING)


def _close_database_now() -> None:
    """Close the database to the writers that could recreate the store after the wipe, waiting on NOTHING (R689 follow-up (1)):
    collection is held and told to stop, every background job is asked to stop and refused from this instant (its next statement or
    commit raises), and so are the collector's own threads (the scheduler loop, its ``oo-collect`` workers, the briefing and
    housekeeping lanes), which the graceful stop leaves to their own joins. A wipe races a seizure, so no step joins a thread, and a
    step that fails never stops the wipe.

    NOT covered, stated: the import queue, the re-index managers, the backup threads and the request threads keep running and can
    still check out a connection; from the erase on, the store and the data folder are refused to every opener (R802, the erase's latch).
    A transaction already under way when the erase runs (a custody append, one of those threads) can still commit into the unlinked
    files; :func:`_dispose_after_erase` rewrites them again through descriptors the erase kept, and a commit later than its last pass
    is the window left. The pool is disposed AFTER the erase, never before: closing the last connection on a live file runs SQLite's
    write-back of its log, which can be hundreds of MiB, and that must not stand between the panic and the destroyed key."""
    try:
        from src.scheduler.runner import pause_for_exclusive_operation

        # The hold blocks "Run now"; the loop is signalled, never joined. It is never released, on purpose (R383's counted hold): the
        # corpus is gone and the app must be restarted, so nothing may start collection on this process again.
        claim: list[bool] = []
        pause_for_exclusive_operation(timeout=0.0, claim=claim)
        global _HOLDS_TAKEN
        _HOLDS_TAKEN += sum(claim)  # the holds really taken, so the test suite gives back exactly those and no others
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


def _dispose_own_pool() -> int | None:
    """Close this process's pool; its connections still checked out on the erased store, ``None`` when that cannot be told."""
    try:
        from src.database import session
        from src.paths import erased_folder_of

        n = session.dispose_engine().get("checked_out")
        db_file = getattr(session, "DB_FILE", None)
        # R805 (a): only a pool on the erased store is a holder of it; a pool on a store elsewhere is closed all the same and
        # counts 0 (the same rule as crypto_erase._close_own_pool), so its count never turns a clean wipe into "unknown".
        if db_file and not erased_folder_of(db_file):
            return 0
        return n if isinstance(n, int) else None
    except Exception:  # noqa: BLE001 - the wipe is done; this is tidying
        return None


def _dispose_after_erase(generation: int | None = None, *, arm_late: bool = True) -> int | None:
    """Close the pool once the key is gone, then rewrite through the kept descriptors what a transaction already under way
    put back into the unlinked files (its commit writes page 1, salt included): once now, and once more after
    :data:`_LATE_RESCRUB_S` on a timer that never holds the wipe up. Only this wipe's descriptors (``generation``), so a
    second wipe within the delay never shortens the first one's late pass, nor the first one's timer the second's. Never
    raises."""
    # Row 388: the database module never imported in this process (the panic CLI with its data drive not there) means no pool of
    # this process holds a store: none of its own connections is open.
    still_open = _dispose_own_pool() if "src.database.session" in sys.modules else 0
    try:
        from src.safety.crypto_erase import rescrub_held

        rescrub_held(close=False, generation=generation)
    except Exception:  # noqa: BLE001 - never raises  # nosec B110
        pass
    if arm_late:
        _arm_late_rescrub(generation)
    return still_open


def _arm_late_rescrub(generation: int | None) -> None:
    """The late pass: :data:`_LATE_RESCRUB_S` from now, rewrite once more through this wipe's kept descriptors and let them go.
    The panic wipe arms it only after its own last use of them (a plaintext store's body rewrite, which can take minutes, and the
    holder check, which probes them by descriptor), so it can never close them under either (row 392, security read). Never
    raises."""
    try:
        from src.safety.crypto_erase import held_count, rescrub_held

        if held_count(generation):  # even when the last pass rewrote nothing: the late pass is also the one that lets them go
            late = threading.Timer(_LATE_RESCRUB_S, rescrub_held, kwargs={"close": True, "generation": generation})
            late.name = "oo-panic-rescrub"
            late.daemon = True
            late.start()
    except Exception:  # noqa: BLE001 - never raises  # nosec B110
        pass


#: R813 row 389: how long after a panic result that keeps a drive's key in memory the app starts closing (the response is sent and
#: the page has drawn it first), and how long the graceful stop may take before the process ends without it.
PANIC_EXIT_DELAY_S = 3.0
PANIC_EXIT_HARD_AFTER_S = 60.0  # past the graceful stop (30 s uvicorn + 10 s scheduler join + 5 s job wait)


def _hard_exit() -> None:  # pragma: no cover - ends the process
    os._exit(1)  # non-zero: the stop was forced


def exit_after_panic(*, delay: float = PANIC_EXIT_DELAY_S, hard_after: float = PANIC_EXIT_HARD_AFTER_S,
                     _arm=None, _exit=_hard_exit) -> None:
    """R813 row 389: the panic wipe left the key to a data drive's data in this process's memory (its connections on a drive found
    absent, unidentified or changed are pinned, never closed: src/database/drive_pin.py), so the app closes itself rather than wait
    for the operator to. The graceful stop is the same one the power button takes (the pinned connections are skipped by every
    close on the way out); if the process is still running ``hard_after`` seconds later, it ends without it, the operating system
    then releasing the descriptors without SQLite's own close. Never raises."""
    from src.monitoring.secret_scrub import log_failure
    from src.safety.shutdown import _default_arm, _reap_worker_processes

    try:
        (_arm or _default_arm)(delay)
    except Exception as exc:  # noqa: BLE001 - the hard stop below still ends the process
        log_failure(_LOG, "panic: the graceful stop could not be armed", exc, level=logging.WARNING)

    def _watchdog() -> None:
        time.sleep(delay + hard_after)
        _LOG.warning("panic: the app did not stop within %.0f s; ending the process", delay + hard_after)
        _reap_worker_processes()
        _exit()

    try:
        threading.Thread(target=_watchdog, name="oo-panic-exit", daemon=True).start()
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "panic: the hard stop could not be armed", exc, level=logging.WARNING)
