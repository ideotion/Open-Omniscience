"""
Two-phase secure wipe — crypto-erase (instant) + optional full free-space scrub.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The panic-wipe feature exists for a journalist who must destroy a corpus *now* in
the face of an imminent seizure. The old implementation overwrote only the first
4 MiB of every file before unlinking, so most of a multi-GB corpus survived,
forensically recoverable (audit OO-02). This module replaces that with two honest
phases:

  1. ``quick_crypto_erase`` — the surgical quick pass. The store is SQLCipher
     encrypted by default and its key is derived from a random 16-byte salt kept
     in the first database page. Destroy that page and the key can NEVER be
     re-derived: the ciphertext body (however many GB) becomes permanent noise
     without touching it. Instant at any size, safe if interrupted. It also
     destroys the on-disk signing keys, ``anchors.db`` (encrypted or plaintext,
     matching the corpus since audit finding L1, 2026-07-17 -- either way a full
     overwrite destroys it), clears the in-memory passphrase, and removes the
     data dir.

  2. ``full_secure_erase`` — an OPTIONAL defence-in-depth pass. Because the quick
     pass already unlinked the files, this scrubs the freed ciphertext blocks by
     filling the volume's free space with random data (chunked, ``passes`` times).
     Honest about its limit: on SSD/flash/copy-on-write filesystems wear-levelling
     can retain blocks, so this is belt-and-braces on top of crypto-erase, never a
     stronger guarantee than it.

Both refuse to run without an explicit ``confirm``. Neither implies physical
erasure it cannot deliver — the real guarantee is the destroyed salt.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from pathlib import Path

_LOG = logging.getLogger(__name__)

# SQLCipher default scheme: the 16-byte random salt lives in the first page. The
# app applies no ``cipher_plaintext_header_size`` override (src/database/connect.py),
# so overwriting page 1 destroys the salt -> the PBKDF2 key is underivable forever.
_SQLCIPHER_PAGE1 = 4096

# Bound RAM/time for both the chunked full overwrite and the free-space scrub.
_CHUNK = 8 * 1024 * 1024

# The full-overwrite pass count is user-chosen from this set (Single/Triple/Octuple).
_ALLOWED_PASSES = (1, 3, 8)

# File names under the data dir (all resolved through the real resolvers for the
# default store; derived from the base dir when an explicit dir is passed).
_MAIN_DB = "open_omniscience.db"
_CUSTODY_DB = "custody_log.db"
_ANCHORS_DB = "anchors.db"
_DUCK_FILES = ("analytics.duckdb", ".oo_columnar_probe.duckdb")
_KEY_FILES = ("custody_ed25519.pem", "custody_ml_dsa_65.key")
_DB_SIDECARS = ("-wal", "-shm", "-journal")

_LIMIT_NOTE = (
    "The guarantee here is crypto-erase: the SQLCipher salt is destroyed, so the "
    "encrypted corpus is permanently unrecoverable regardless of storage medium. A "
    "byte-overwrite pass is defence-in-depth only — it does NOT guarantee "
    "unrecoverability on SSD/flash or copy-on-write filesystems (wear-levelling / "
    "snapshots may retain old blocks). For belt-and-braces on a plaintext store, use "
    "full-disk encryption (LUKS/Qubes/Tails) and destroy that key too."
)


def _overwrite(path: Path, *, head_bytes: int | None = None) -> bool:
    """Overwrite ``path`` in place with random data, then fsync. When ``head_bytes``
    is given only that prefix is overwritten (the crypto-erase salt-page case);
    otherwise the whole file is overwritten in bounded chunks (small files only —
    the big encrypted corpus is handled by its header, never rewritten). Returns
    whether every byte was actually written and fsynced -- callers must NOT report
    a destructive overwrite as done just because no exception reached them; a
    silent False here with the outcome still reported as success is exactly the
    false-confidence bug audit OO-02 exists to eliminate."""
    try:
        size = path.stat().st_size
        limit = size if head_bytes is None else min(size, head_bytes)
        with open(path, "r+b", buffering=0) as f:
            written = 0
            while written < limit:
                chunk = os.urandom(min(_CHUNK, limit - written))
                f.write(chunk)
                written += len(chunk)
            f.flush()
            os.fsync(f.fileno())
        return True
    except OSError:
        _LOG.warning("crypto-erase: overwrite failed for %s (NOT destroyed)", path)
        return False


def _shred(path: Path, *, head_bytes: int | None = None) -> tuple[bool, bool, bool]:
    """Overwrite then unlink ``path``. Returns ``(seen, overwritten, unlinked)``:
    ``seen`` is whether the file existed, ``overwritten`` whether the destructive
    write actually completed, ``unlinked`` whether the directory entry was removed.
    These are reported separately -- a failed overwrite followed by a successful
    unlink is NOT destruction, it's just deletion, and callers must not conflate
    the two when claiming a salt page or key file was destroyed."""
    try:
        if not path.exists():
            return (False, False, False)
    except OSError:
        return (False, False, False)
    overwritten = _overwrite(path, head_bytes=head_bytes)
    try:
        path.unlink()
        return (True, overwritten, True)
    except OSError:
        _LOG.warning("crypto-erase: could not unlink %s", path)
        return (True, overwritten, False)


def _resolve(data_dir: Path | None) -> dict:
    """Resolve every wipe target. For the default store (``data_dir is None``) the
    real resolvers are used so nothing is hardcoded; an explicit dir (tests/tools)
    derives the same layout from that base."""
    from src.paths import data_dir as _default_dir

    if data_dir is not None:
        base = Path(data_dir)
        return {
            "base": base,
            "main_db": base / _MAIN_DB,
            "keys_dir": base / "keys",
            "store_dir": base,
            "custody_db": base / _CUSTODY_DB,
            "anchors_db": base / _ANCHORS_DB,
        }
    base = _default_dir()
    from src.analytics.columnar import _store_dir
    from src.api.unlock import main_db_path
    from src.custody.signing import _keys_dir

    return {
        "base": base,
        "main_db": main_db_path(),  # honors DATABASE_URL; None on a non-SQLite backend
        "keys_dir": _keys_dir(),
        "store_dir": _store_dir(),
        "custody_db": base / _CUSTODY_DB,
        "anchors_db": base / _ANCHORS_DB,
    }


def quick_crypto_erase(confirm: bool = False, *, data_dir: Path | None = None) -> dict:
    """Instant crypto-erase then remove the data dir. Requires ``confirm=True``.

    Order: destroy the SQLCipher salt page of each encrypted DB (+ its WAL/SHM/
    journal sidecars), destroy the on-disk signing keys, overwrite the DuckDB cache
    header, fully overwrite the plaintext ``anchors.db``, clear the in-memory
    passphrase, then overwrite-and-unlink anything else under the data dir and
    ``rmtree`` it. Fast at any corpus size (the encrypted body is never rewritten —
    its key is gone). ``data_dir`` overrides the target (tests/tools)."""
    if not confirm:
        raise PermissionError("quick_crypto_erase requires confirm=True (this is irreversible)")

    from src.database.connect import is_encrypted_file

    paths = _resolve(data_dir)
    base: Path = paths["base"]
    seen = wiped = 0
    headers: list[str] = []
    keys_destroyed: list[str] = []
    # Files that existed but whose destructive overwrite itself failed (e.g. ENOSPC on a
    # CoW filesystem mid-write) -- unlink may still have succeeded, but that is deletion,
    # not destruction. Reported honestly rather than folded into "headers_destroyed" /
    # "keys_destroyed", which must only ever mean the overwrite actually completed.
    overwrite_failures: list[str] = []

    def _track(p: Path, *, head_bytes: int | None = None) -> tuple[bool, bool, bool]:
        s, overwritten, w = _shred(p, head_bytes=head_bytes)
        if s and not overwritten:
            overwrite_failures.append(str(p))
        return s, overwritten, w

    # Was the corpus actually encrypted? Determines whether crypto-erase is the real
    # guarantee (encrypted) or degrades to header-overwrite (plaintext store -> the
    # optional full pass matters more; surfaced so the UI can recommend it).
    main_db: Path | None = paths["main_db"]
    encrypted = is_encrypted_file(main_db) if main_db is not None else None

    # 1) Destroy the salt/header page of each encrypted DB and its sidecars. Head-only
    #    overwrite = instant even for a 100 GB corpus; the salt is what matters.
    for db in (main_db, paths["custody_db"]):
        if db is None:
            continue
        for suffix in ("", *_DB_SIDECARS):
            p = db if suffix == "" else db.with_name(db.name + suffix)
            s, overwritten, w = _shred(p, head_bytes=_SQLCIPHER_PAGE1)
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
            if s and overwritten and suffix == "":
                headers.append(db.name)

    # 2) Destroy on-disk key material (the scrypt wrap-salt lives inside these files).
    keys_dir: Path = paths["keys_dir"]
    for name in _KEY_FILES:
        s, overwritten, w = _track(keys_dir / name)
        seen += s
        wiped += w
        if s and overwritten:
            keys_destroyed.append(name)

    # 3) DuckDB cache header (its key has no per-file salt -> defence-in-depth; the real
    #    protection is clearing the passphrase in step 5 + the free-space scrub).
    store_dir: Path = paths["store_dir"]
    for name in _DUCK_FILES:
        _s, _overwritten, _w = _track(store_dir / name, head_bytes=_SQLCIPHER_PAGE1)
        seen += _s
        wiped += _w

    # 4) anchors.db now inherits the corpus's own encryption state (audit finding
    #    L1, 2026-07-17 -- it used to be always-plaintext regardless of the corpus).
    #    A full overwrite destroys it either way (it is small, so this is cheap
    #    even though a head-only pass would already crypto-erase it if encrypted).
    anchors_seen, _anchors_overwritten, anchors_wiped = _track(paths["anchors_db"])
    seen += anchors_seen
    wiped += anchors_wiped

    # 5) Clear the in-memory passphrase (never persisted) so the app holds no key. Only
    #    for the real default store — an explicit override dir must not mutate process
    #    state that belongs to a different (the live) corpus.
    passphrase_cleared = False
    if data_dir is None:
        from src.database.connect import set_passphrase

        set_passphrase(None)
        passphrase_cleared = True

    # 6) Overwrite + unlink everything else still under the data dir, then rmtree. The
    #    encrypted DBs/keys/anchors are already gone; remaining files are small side
    #    files, so a full overwrite here is cheap and complete (no 4 MiB cap — OO-02).
    if base.exists():
        for root, _dirs, names in os.walk(base):
            for name in names:
                _s, _overwritten, _w = _track(Path(root) / name)
                seen += _s
                wiped += _w
    with contextlib.suppress(OSError):
        shutil.rmtree(base, ignore_errors=True)

    if overwrite_failures:
        _LOG.error(
            "CRYPTO-ERASE: %d file(s) could NOT be overwritten (only unlinked, if that): %s",
            len(overwrite_failures), overwrite_failures,
        )
    _LOG.warning(
        "CRYPTO-ERASE executed on %s (encrypted=%s, %d/%d files, %d headers, %d keys, "
        "%d overwrite failures)",
        base, encrypted, wiped, seen, len(headers), len(keys_destroyed), len(overwrite_failures),
    )
    return {
        "phase": "crypto-erase",
        "data_dir": str(base),
        "files_seen": seen,
        "files_wiped": wiped,
        "headers_destroyed": headers,
        "keys_destroyed": keys_destroyed,
        "overwrite_failures": overwrite_failures,
        "passphrase_cleared": passphrase_cleared,
        "encrypted_corpus": encrypted,
        "removed": not base.exists(),
        "limit": _LIMIT_NOTE,
    }


def _fill_free_space(path: Path, cap: int | None) -> int:
    """Write random data to ``path`` until the volume is full (or ``cap`` bytes, a
    test-only bound), fsync, and return the bytes written. Best-effort."""
    written = 0
    try:
        with open(path, "wb", buffering=0) as f:
            while cap is None or written < cap:
                n = _CHUNK if cap is None else min(_CHUNK, cap - written)
                try:
                    f.write(os.urandom(n))
                except OSError:
                    break  # ENOSPC: the volume is full -> this pass is done
                written += n
            with contextlib.suppress(OSError):
                f.flush()
                os.fsync(f.fileno())
    except OSError:
        pass
    return written


def full_secure_erase(
    passes: int = 1, *, base_dir: Path | None = None, _cap_bytes: int | None = None
) -> dict:
    """Optional defence-in-depth free-space scrub of the corpus volume.

    Run AFTER ``quick_crypto_erase`` (which already unlinked the files): fills the
    volume's free space with random data ``passes`` times so the freed ciphertext
    blocks are overwritten. ``passes`` must be 1, 3, or 8 (Single/Triple/Octuple).
    ``base_dir`` chooses where the fill files land (defaults to the data dir, i.e.
    the corpus volume). ``_cap_bytes`` is a TEST-ONLY per-pass byte cap so the suite
    never has to fill a real disk."""
    if passes not in _ALLOWED_PASSES:
        raise ValueError(f"passes must be one of {_ALLOWED_PASSES}, got {passes!r}")

    if base_dir is not None:
        base = Path(base_dir)
    else:
        from src.paths import data_dir

        base = data_dir()  # recreated empty by the resolver if the quick pass removed it
    base.mkdir(parents=True, exist_ok=True)
    scrub_dir = base / ".oo_scrub"
    scrub_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for i in range(passes):
        fill = scrub_dir / f"scrub_{i}.bin"
        total += _fill_free_space(fill, _cap_bytes)
        with contextlib.suppress(OSError):
            fill.unlink()
    with contextlib.suppress(OSError):
        shutil.rmtree(scrub_dir, ignore_errors=True)

    _LOG.warning("SECURE-ERASE scrub on %s (%d passes, %d bytes total)", base, passes, total)
    return {
        "phase": "free-space-scrub",
        "data_dir": str(base),
        "passes": passes,
        "bytes_written": total,
        "limit": _LIMIT_NOTE,
    }
