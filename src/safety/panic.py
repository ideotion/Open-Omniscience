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
