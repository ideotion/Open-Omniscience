"""
The ONE SQLite connection factory: every database open in the app goes here.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design (docs/design/DB_RELIABILITY_02_DESIGN.md §4, maintainer-ruled):
the working database file is SQLCipher-encrypted BY DEFAULT, unlocked at app
start by THE passphrase — one stable secret, no recovery, no decryption
alternative (the maintainer's recorded rationale: the corpus is
reconstitutable from the web; a lost passphrase costs re-collection time,
not unique data — a premise that EXPIRES when newsletters ship).

Honesty rules implemented here:
  * Encryption state is a property of the FILE (header check), never an
    assumption. A plaintext file opens plaintext (with the state reported by
    doctor) — there is no lock screen over a plaintext file.
  * Wrong passphrases fail LOUDLY (SQLCipher's HMAC check) — never garbage.
  * Threat model, stated wherever this surfaces: an encrypted file protects
    a seized/off machine or a copied file. It cannot protect a compromised
    running session (the key lives in this process's memory after unlock).

Cross-key copies: SQLCipher's backup API only works between same-key
databases (verified empirically in the PR-E sandbox); crossing the boundary
requires ``sqlcipher_export``. The two snapshot helpers below are therefore
INTENTIONAL: ``snapshot_preserving`` for safety nets and working copies
(same encryption as the source — a restore must never silently decrypt the
corpus), ``snapshot_to_plaintext`` for portable artifact members (whose
protection is the artifact's own OOENC1 envelope).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

_LOG = logging.getLogger("database.connect")

_SQLITE_MAGIC = b"SQLite format 3\x00"

# DB-10 §1a (ruled 2026-07-17, "I agree with your proposal to change the
# auto_vacuum to incremental"): every NEW corpus is created with incremental
# auto-vacuum so free pages (deletes/re-indexes) can be reclaimed a little at a
# time (src/scheduler/maintenance.py's idle pass) instead of only via a full,
# blocking VACUUM. Must be set on the connection BEFORE any table exists —
# SQLite records the mode in the file header once the first object is created,
# and it is read back transparently on every later open (unlike page_size
# below, auto_vacuum carries NO reopen hazard). Existing stores are untouched
# (this only fires on the fresh-file branches of connect()).
_FRESH_AUTO_VACUUM = 2  # INCREMENTAL

_lock = threading.Lock()
_passphrase: str | None = os.environ.get("OO_DB_PASSPHRASE") or None


class DatabaseLockedError(RuntimeError):
    """The store is encrypted (or must be created encrypted) and no passphrase
    has been provided yet. The app serves only the unlock flow in this state."""


class WrongPassphraseError(RuntimeError):
    """The provided passphrase does not open this database (loud, typed)."""


def set_passphrase(p: str | None) -> None:
    global _passphrase
    with _lock:
        _passphrase = p or None


def get_passphrase() -> str | None:
    with _lock:
        return _passphrase


def plaintext_mode() -> bool:
    """Explicit plaintext opt-out (special setups, tests, CI). Never implied."""
    return os.environ.get("OO_DB_PLAINTEXT", "") == "1"


def have_driver() -> bool:
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:  # pragma: no cover - wheels ship for all 3 OSes
        return False


def is_encrypted_file(path: Path | str) -> bool | None:
    """True = ciphertext header, False = plaintext SQLite, None = missing/empty."""
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return None
        with open(p, "rb") as fh:
            return fh.read(16) != _SQLITE_MAGIC
    except OSError:
        return None


def _quote_key(key: str) -> str:
    # PRAGMA takes no bound parameters; single quotes are doubled (SQL string
    # literal escaping). The key never reaches any log.
    return key.replace("'", "''")


def _apply_key(conn, key: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA key = '{_quote_key(key)}'")
    finally:
        cur.close()


def _verify_readable(conn, path: Path) -> None:
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except Exception as exc:
        conn.close()
        raise WrongPassphraseError(
            f"the passphrase does not open {path.name} (or the file is damaged)"
        ) from exc


def connect(
    path: Path | str,
    *,
    key: str | None = None,
    create_encrypted: bool | None = None,
    check_same_thread: bool = True,
    timeout: float = 30.0,
    cipher_page_size: int | None = None,
):
    """Open ``path`` with the right driver and key for ITS state.

    - encrypted file  -> sqlcipher3 + key (argument, else the process passphrase);
                         no key available raises DatabaseLockedError; a wrong key
                         raises WrongPassphraseError.
    - plaintext file  -> stdlib sqlite3 (zero behaviour change for legacy data).
    - missing file    -> created ENCRYPTED when a key is available (the ruled
                         default), plaintext only under OO_DB_PLAINTEXT=1 or
                         create_encrypted=False; otherwise DatabaseLockedError
                         (the unlock/create flow supplies the passphrase first).
                         Every fresh file (encrypted or plaintext) is created
                         with ``auto_vacuum=INCREMENTAL`` (DB-10 §1a) before its
                         first table exists — a pre-ruling store is untouched.

    ``cipher_page_size``: SQLCipher decodes a database ONLY at the page size it
    was created with, and that size is NOT discoverable from the file — a store
    created at a non-default size reads as wrong-passphrase unless the opener
    declares the same size right after keying. Pass it when opening a store
    KNOWN to be built at a non-default size (the page-size bench's rebuilt
    targets). Applied only on the encrypted-open path; ignored for plaintext
    files (their page size is self-describing).
    """
    p = Path(path)
    state = is_encrypted_file(p)
    use_key = key if key is not None else get_passphrase()

    if state is True:
        if not have_driver():  # pragma: no cover - core dependency
            raise DatabaseLockedError(
                f"{p.name} is encrypted but the sqlcipher3 driver is unavailable"
            )
        if not use_key:
            raise DatabaseLockedError(f"{p.name} is encrypted: a passphrase is required")
        from sqlcipher3 import dbapi2 as sqc

        conn = sqc.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        _apply_key(conn, use_key)
        if cipher_page_size is not None:
            conn.execute(f"PRAGMA cipher_page_size = {int(cipher_page_size)}")
        _verify_readable(conn, p)
        return conn

    if state is False:
        return sqlite3.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)

    # Fresh file. Decide its at-rest fate EXPLICITLY (never by accident):
    # an explicit caller key outranks the ambient plaintext opt-out; the
    # opt-out outranks the process passphrase; no decision = locked.
    if key:
        if not have_driver():  # pragma: no cover
            raise DatabaseLockedError("sqlcipher3 driver unavailable; cannot create encrypted DB")
        from sqlcipher3 import dbapi2 as sqc

        conn = sqc.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        _apply_key(conn, key)
        conn.execute(f"PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        return conn
    if create_encrypted is False or (create_encrypted is None and plaintext_mode()):
        conn = sqlite3.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        conn.execute(f"PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        return conn
    if use_key:
        if not have_driver():  # pragma: no cover
            raise DatabaseLockedError("sqlcipher3 driver unavailable; cannot create encrypted DB")
        from sqlcipher3 import dbapi2 as sqc

        conn = sqc.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        _apply_key(conn, use_key)
        conn.execute(f"PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        return conn
    raise DatabaseLockedError(
        f"{p.name} does not exist yet: choose a passphrase (encrypted by default) "
        "or set OO_DB_PLAINTEXT=1 explicitly"
    )


def locked_state(path: Path | str) -> str:
    """One word for the boot machine + doctor: unlocked-plaintext |
    unlocked-encrypted | locked | fresh."""
    state = is_encrypted_file(path)
    if state is False:
        return "unlocked-plaintext"
    if state is True:
        return "unlocked-encrypted" if get_passphrase() else "locked"
    if plaintext_mode() or get_passphrase():
        return "unlocked-plaintext" if plaintext_mode() else "unlocked-encrypted"
    return "fresh"


def attach(conn, path: Path | str, alias: str) -> None:
    """ATTACH a PLAINTEXT database (staged artifact members are plaintext by
    design). On a SQLCipher connection the empty KEY clause is mandatory or the
    attached DB would inherit the main key; stdlib sqlite3 has no KEY clause."""
    if _is_sqlcipher_conn(conn):
        conn.execute(f'ATTACH DATABASE ? AS "{alias}" KEY \'\'', (str(path),))
    else:
        conn.execute(f'ATTACH DATABASE ? AS "{alias}"', (str(path),))


def _is_sqlcipher_conn(conn) -> bool:
    return "sqlcipher" in type(conn).__module__


def _export(conn, alias: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT sqlcipher_export('{alias}')")
    finally:
        cur.close()


def snapshot_to_plaintext(src: Path | str, dest: Path | str) -> Path:
    """Consistent PLAINTEXT snapshot of ``src`` (artifact members; the artifact's
    own envelope is the at-rest protection there)."""
    src_p, dest_p = Path(src), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    if is_encrypted_file(src_p):
        conn = connect(src_p, check_same_thread=False)
        try:
            conn.execute("ATTACH DATABASE ? AS snap KEY ''", (str(dest_p),))
            _export(conn, "snap")
            conn.execute("DETACH DATABASE snap")
        finally:
            conn.close()
        return dest_p
    src_conn = sqlite3.connect(str(src_p))
    try:
        dst_conn = sqlite3.connect(str(dest_p))
        try:
            src_conn.backup(dst_conn)  # online backup API: WAL-safe, page-consistent
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return dest_p


def reencrypt_plain_to(src_plain: Path | str, dest: Path | str, key: str) -> Path:
    """Copy a PLAINTEXT database into a new ENCRYPTED file under ``key``
    (sqlcipher_export; the encrypt tool and the replace-restore path)."""
    if not have_driver():  # pragma: no cover - core dependency
        raise DatabaseLockedError("sqlcipher3 driver unavailable")
    from sqlcipher3 import dbapi2 as sqc

    src_p, dest_p = Path(src_plain), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    conn = sqc.connect(str(src_p))  # a plaintext file opens with no key
    try:
        conn.execute(f"ATTACH DATABASE ? AS enc KEY '{_quote_key(key)}'", (str(dest_p),))
        _export(conn, "enc")
        conn.execute("DETACH DATABASE enc")
    finally:
        conn.close()
    return dest_p


def snapshot_preserving(src: Path | str, dest: Path | str) -> Path:
    """Consistent snapshot KEEPING the source's encryption state — working
    copies and pre-restore safety nets must never silently change the corpus's
    at-rest protection (an encrypted corpus stays ciphertext on disk)."""
    src_p, dest_p = Path(src), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    if not is_encrypted_file(src_p):
        return snapshot_to_plaintext(src_p, dest_p)
    key = get_passphrase()
    if not key:
        raise DatabaseLockedError(f"{src_p.name} is encrypted: cannot snapshot while locked")
    conn = connect(src_p, check_same_thread=False)
    try:
        conn.execute(f"ATTACH DATABASE ? AS snap KEY '{_quote_key(key)}'", (str(dest_p),))
        _export(conn, "snap")
        conn.execute("DETACH DATABASE snap")
    finally:
        conn.close()
    return dest_p
