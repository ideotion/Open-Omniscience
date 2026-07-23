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

# DB-10 §1b (FIRM recommendation, evidence delivered 2026-07-19/20 on real
# 3 GB and 22 GB encrypted corpora: warm p50 index-window queries -34%/-50%,
# stability improves toward scale — see CLAUDE.md's §1b evidence entry).
# UNLIKE auto_vacuum, this carries a REAL reopen hazard: SQLCipher decodes a
# database ONLY at the page size it was created with, and that size is NOT
# discoverable from the file (the 2026-07-19 field incident — a correct
# passphrase read as wrong because the opener never redeclared a non-default
# size).
#
# DESIGN CHOICE (the brief's §4.1.2 option (b), verify-then-fallback probe —
# NOT a persisted marker (option (a))): building this, a persisted marker was
# tried FIRST and found UNSAFE in THIS codebase specifically — several
# existing internal mechanisms (snapshot_preserving/reencrypt_plain_to below,
# and likely others in backup/custody) create a FRESH encrypted file at a
# LIVE path via ATTACH + sqlcipher_export WITHOUT declaring cipher_page_size
# on the attached target, so they silently write the file back out at
# SQLCipher's compiled-in default — desyncing a path-keyed marker from the
# file's REAL on-disk size and reproducing the EXACT field incident this fix
# exists to prevent (empirically reproduced while building this: a live
# corpus reopened fine right after creation, then failed with "hmac check
# failed for pgno=1" after a merge-restore cycle silently rewrote it at a
# different size while a stale marker still said 16384). A probe that always
# re-verifies against the REAL file, every open, cannot go stale — it has no
# persisted state to desync. The cost is one extra page-1 HMAC check
# (microseconds, not proportional to corpus size) on a store NOT at the
# ruled default; every fresh store this factory creates from now on pays it
# exactly ZERO times (see the "state is True" branch below).
_FRESH_PAGE_SIZE = 16384

# The full set of page sizes SQLite/SQLCipher can validly use (powers of 2,
# 512..65536 — the same domain pagesize_bench.py's own _ALLOWED_PAGE_SIZES
# covers). An adversarial-review finding (2026-07-23): probing ONLY
# [16384, None] left any store at some OTHER legitimate size (e.g. one this
# factory's own snapshot/re-encrypt machinery faithfully PRESERVES via
# _match_source_pragmas below, for a corpus that predates this ruling at a
# non-4096 size) unopenable with no explicit cipher_page_size — reproducing
# this fix's own target bug for exactly that case (found via
# encrypt_tool.py's immediate post-encrypt self-verify, which passes no
# explicit size). Ordered by REAL-WORLD likelihood so the common cases stay
# cheap: the new ruled default, then the historical SQLite/SQLCipher
# compiled-in default, then the rest of the valid range. ``None`` (no PRAGMA
# at all — whatever THIS build's compiled-in default is) stays the final
# fallback for a build whose default isn't in this list.
_PAGE_SIZE_CANDIDATES: tuple[int, ...] = (16384, 4096, 8192, 32768, 2048, 1024, 512, 65536)

_lock = threading.Lock()
# In-process cache of the LAST candidate that successfully opened a given
# path (keyed by its resolved absolute path string) — pure performance, never
# a correctness dependency: every open still calls _try_open_encrypted and
# gets verified for real, so a stale/wrong cache entry just falls through to
# the full candidate list on its own (self-healing, same as the probe
# itself). Purely in-memory (dies with the process) — this is NOT the
# persisted marker design that was rejected above; it cannot desync ACROSS a
# restart, and _match_source_pragmas keeps a live path's real size constant
# for its whole existence, so it cannot desync WITHIN a process either. Caps
# the doubled-KDF cost the probe would otherwise pay on EVERY new pooled
# connection to a non-16384 store (SQLCipher's key derivation is
# deliberately expensive — ~173 ms, CLAUDE.md's rate-limiting-is-a-
# deliberate-omission entry).
_last_good_page_size: dict[str, int | None] = {}
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


def _try_open_encrypted(
    p: Path, key: str, check_same_thread: bool, timeout: float, page_size, *, last_error=None
):
    """One attempt: a FRESH sqlcipher3 connection, keyed, optionally declaring
    ``page_size``, verified readable. Returns the connection on success or
    ``None`` (closed) on ANY failure in that sequence — NEVER raises, so the
    caller can retry with a genuinely fresh connection at a different
    candidate size (empirically required: reusing one connection object
    after a failed HMAC check leaves the codec in a stuck error state — a
    same-connection retry fails even at the CORRECT size). The WHOLE
    sequence (connect, key, page-size pragma, verify) is guarded — not just
    the final read — so a transient failure on any of those steps (e.g. a
    momentary ``database is locked`` under this factory's own connection-pool
    concurrency) closes the connection cleanly instead of leaking it and
    surfacing a raw, untyped exception out of ``connect()``. If ``last_error``
    (a one-slot mutable list) is given, the raised exception is stashed there
    so the caller can chain it into a final ``from exc`` for debuggability —
    never lost even though this function itself never raises."""
    from sqlcipher3 import dbapi2 as sqc

    conn = None
    try:
        conn = sqc.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        _apply_key(conn, key)
        if page_size is not None:
            conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except Exception as exc:
        if conn is not None:
            conn.close()
        if last_error is not None:
            last_error[:] = [exc]
        return None


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
                         A fresh ENCRYPTED file is ALSO created at
                         ``cipher_page_size=16384`` (DB-10 §1b) unless the
                         caller passes an explicit ``cipher_page_size``.

    ``cipher_page_size``: SQLCipher decodes a database ONLY at the page size it
    was created with, and that size is NOT discoverable from the file — a store
    created at a non-default size reads as wrong-passphrase unless the opener
    declares the same size right after keying. An explicit value here ALWAYS
    wins (e.g. the page-size bench's rebuilt targets — no probing). Leave it
    ``None`` and ``connect()`` PROBES automatically: try every valid SQLite
    page size (``_PAGE_SIZE_CANDIDATES``, ruled default first, then the
    historical compiled-in default, then the rest of the valid range, then a
    final undeclared attempt) until one opens. This is what makes the app's
    NORMAL boot reopen path (``session.py``'s engine creator, unchanged) safe
    with ZERO call-site change: every fresh store this factory creates from
    now on matches the FIRST candidate, so the probe costs nothing there; an
    in-process cache (``_last_good_page_size``, never persisted) remembers
    the winning candidate per path so a REPEATED open of the same
    non-default store pays the (deliberately expensive, ~173 ms) key
    derivation only once per candidate tried, not on every pooled
    connection. Self-healing by construction — there is no persisted marker
    to go stale when something else silently rewrites the file at a
    different size (see the design-choice comment above
    ``_FRESH_PAGE_SIZE``); the cache is pure performance, never trusted
    blindly — a wrong/stale entry just falls through to the full probe.
    Ignored for plaintext files (their page size is self-describing; no
    reopen hazard).
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
        if cipher_page_size is not None:
            candidates: list[int | None] = [cipher_page_size]
        else:
            resolved = str(p.resolve())
            with _lock:
                cached = _last_good_page_size.get(resolved)
            # The cached hit (if any) goes FIRST — a repeated open of the
            # same path skips straight to the size that actually worked last
            # time. Deduped against the standard list so a match there is
            # never tried twice; the full list + final None always follows,
            # so a stale/wrong cache entry (the file genuinely changed) still
            # self-heals via the complete probe.
            ordered = [cached, *_PAGE_SIZE_CANDIDATES, None] if resolved in _last_good_page_size else [
                *_PAGE_SIZE_CANDIDATES,
                None,
            ]
            seen: set[int | None] = set()
            candidates = []
            for c in ordered:
                if c not in seen:
                    seen.add(c)
                    candidates.append(c)
        conn = None
        winning_candidate: int | None = None
        last_error: list = []
        for candidate in candidates:
            conn = _try_open_encrypted(
                p, use_key, check_same_thread, timeout, candidate, last_error=last_error
            )
            if conn is not None:
                winning_candidate = candidate
                break
        if conn is None:
            raise WrongPassphraseError(
                f"the passphrase does not open {p.name} (or the file is damaged)"
            ) from (last_error[0] if last_error else None)
        if cipher_page_size is None:
            with _lock:
                _last_good_page_size[str(p.resolve())] = winning_candidate
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
        # ORDER MATTERS (empirically verified): cipher_page_size MUST be set
        # BEFORE auto_vacuum on a fresh SQLCipher connection, matching
        # pagesize_bench.rebuild_at_pragmas' proven ordering exactly — setting
        # auto_vacuum first corrupts page 1's HMAC once the schema is written
        # (the store fails to reopen at all, not just at the wrong size).
        page_size = cipher_page_size if cipher_page_size is not None else _FRESH_PAGE_SIZE
        conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
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
        # Same ordering requirement as the explicit-key branch above.
        page_size = cipher_page_size if cipher_page_size is not None else _FRESH_PAGE_SIZE
        conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
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


def _match_source_pragmas(conn, alias: str) -> None:
    """Read the SOURCE connection's REAL ``page_size``/``auto_vacuum`` and
    declare the SAME values on the freshly-ATTACHed ``alias`` target, BEFORE
    ``sqlcipher_export`` creates its schema (an empty ATTACHed encrypted
    database otherwise defaults to SQLCipher's compiled-in page size,
    regardless of the source's real size — found empirically while building
    DB-10 §1b: a merge/restore cycle silently downgraded a fresh 16384-page
    corpus back to 4096 through exactly this gap, which connect()'s reopen
    probe survives [it never fails to open] but which would otherwise
    silently erase the §1b performance ruling on every corpus that goes
    through a routine snapshot/restore). This is the natural extension of
    this module's own stated principle — a snapshot/re-encrypt "must never
    silently change" the source's characteristics; that already covered the
    encryption state, this covers the page framing too. Order matters (see
    connect()'s fresh-file branches): cipher_page_size before auto_vacuum."""
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    auto_vacuum = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
    conn.execute(f"PRAGMA {alias}.cipher_page_size = {page_size}")
    conn.execute(f"PRAGMA {alias}.auto_vacuum = {auto_vacuum}")


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
        _match_source_pragmas(conn, "enc")
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
        _match_source_pragmas(conn, "snap")
        _export(conn, "snap")
        conn.execute("DETACH DATABASE snap")
    finally:
        conn.close()
    return dest_p
