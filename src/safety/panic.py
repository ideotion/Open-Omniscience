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
from pathlib import Path

# Re-exported for callers/tests that referenced the honest-limit note here.
from src.safety.crypto_erase import _LIMIT_NOTE  # noqa: F401

_LOG = logging.getLogger(__name__)

#: How long the wipe waits for settings saves already in flight before it goes ahead without holding new ones.
_PANIC_HOLD_S = 2.0
#: What a settings save made during the wipe is told: it is refused at once, never kept waiting behind an erase that can take hours.
_PANIC_REFUSED = "A panic wipe is erasing this app's data, so this was not saved — nothing was written."


def panic_wipe(data_dir: Path | None = None, *, confirm: bool = False) -> dict:
    """Instantly crypto-erase, then delete everything under the data dir. Requires
    ``confirm``. Returns the ``quick_crypto_erase`` summary (``files_seen`` /
    ``files_wiped`` / ``data_dir`` / ``limit`` preserved for existing callers)."""
    if not confirm:
        raise PermissionError("panic_wipe requires confirm=True (this is irreversible)")
    from src.config.kv_store import kv_invalidate
    from src.database.connect import invalidate_header_cache
    from src.safety.crypto_erase import quick_crypto_erase

    # Settings writes are HELD for the whole wipe (Lane E follow-up (a), the security reads): a save from another thread is refused
    # at once, in the wipe's own words, until the trailing invalidate below has run, so nothing commits into the file being erased
    # and a value read from the old file never lands in a fresh one. The wipe waits at most _PANIC_HOLD_S for a save already in
    # flight; when the hold cannot be taken (that save, another holder) it goes ahead without it, and the epoch bumps before and
    # after still refuse the saves made with ``expect_swap``. A save made AFTER the wipe (and its hold) has ended is a first run's,
    # and creates a fresh store like any first run.
    hold = contextlib.ExitStack()
    try:
        from src.config.kv_store import hold_writes

        hold.enter_context(hold_writes(_PANIC_HOLD_S, refused_text=_PANIC_REFUSED, wait_s=0.0))
    except Exception as exc:  # noqa: BLE001 - the wipe runs whatever the hold says
        from src.monitoring.secret_scrub import log_failure

        log_failure(_LOG, "panic wipe: settings writes could not be held, wiping without the hold", exc, level=logging.WARNING)
    with hold:
        # The store's swap epoch moves BEFORE the wipe too (Lane E follow-up (a)): a settings save made from state read in the old
        # file (the bulk queue's, with ``expect_swap``) that reaches its check from here on is refused instead of writing a fresh store
        # file where the wiped one was. The call after the wipe below still clears what was read meanwhile.
        kv_invalidate()
        try:
            return quick_crypto_erase(confirm=True, data_dir=data_dir)
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
