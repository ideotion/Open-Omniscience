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

import contextlib
import errno
import hashlib
import logging
import os
import shutil
import sqlite3
import stat
import sys
import threading
import time
from pathlib import Path, PurePath, PureWindowsPath

if os.name != "nt":
    import fcntl

from src.database import open_stats, store_pins

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

# DB-10 §1b — RULED, TWICE OVER. Merging PR #749 was the ratification under the
# §4.1.5 self-labeling convention (the §1a precedent), and the maintainer then made
# it EXPLICIT on 2026-08-13: "Let's consider this as finished" (0.3 gate row 6,
# recorded in docs/ledger/OPEN_QUEUE.md). Evidence: 2026-07-19/20 on real 3 GB and
# 22 GB encrypted corpora — warm p50 index-window queries -34%/-50%, and the one
# shape 4K won at 3 GB INVERTS at 22 GB, so it was a cache-fit artifact.
#
# THIS COMMENT USED TO READ "FIRM recommendation", AND THAT COST A REAL DECISION
# (2026-09-07): a session reading it concluded the default was unratified, put
# "ratify 16384" to the maintainer as ruling V1-7, and spent a maintainer decision
# re-ratifying something already settled three weeks earlier — because it trusted a
# code comment about a RULING'S STATUS instead of the ledger that records rulings.
# The comment is the artifact that went stale, so it is corrected here rather than
# only in the ledger. GENERAL FORM: a comment may state the EVIDENCE for a decision;
# whether the decision was TAKEN is the ledger's to say, and a comment that answers
# that question will eventually answer it wrongly.
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
# 512..65536). This was the same domain the DB-10 page-size A/B bench probed;
# that bench was removed on 2026-07-31 (Settings review ruling 6) once its job
# was done — the 16384 default below IS its result — so the domain is stated
# here rather than by reference. An adversarial-review finding (2026-07-23):
# probing ONLY
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


def _guard_the_key() -> None:
    """What this process does before it holds a passphrase or hands one to the engine (2026-10-06): hold its core dumps to
    nothing and put every log handler behind the passphrase filter (``secret_scrub.guard_process``; ``src.monitoring.core_guard``
    explains the limit and what it cannot cover). The net under every entry point that forgot to say so first, and it is called
    at EVERY place this module hands a key to the engine (the store's key, the encrypt tool's ``ATTACH ... KEY``) and where a
    process first holds one (the environment at import, ``set_passphrase``): a key typed into a request is given to the engine
    before it is held, so "when it is held" is too late for a server that was not started by ``_serve`` (the uvicorn command
    line), and for a command line tool that reads one. Never raises and never blocks an open: where the guard cannot be engaged
    the boot record says so, and a store that will not open helps no one."""
    with contextlib.suppress(Exception):
        from src.monitoring.secret_scrub import guard_process

        guard_process()


_passphrase: str | None = os.environ.get("OO_DB_PASSPHRASE") or None
if _passphrase:
    _guard_the_key()
# The passphrases this process was started with leave its environment now, before anything starts a child: a process started by
# ``exec`` with the parent's environment (the standard library's resource tracker, the forkserver) holds a copy no code of ours
# has run in to guard. The app reads them from the scrub module from here on (``env_secret``), and a child that must have one is
# handed it by name.
#: The class of a failure to import the scrub module or to take (never its text); the boot record names it (``env_take``).
_TAKE_FAILED: str | None = None
try:
    from src.monitoring.secret_scrub import take_from_environment

    take_from_environment()
except Exception as _take_exc:  # noqa: BLE001 - never blocks an open; the class is recorded
    _TAKE_FAILED = type(_take_exc).__name__


class DatabaseLockedError(RuntimeError):
    """The store is encrypted (or must be created encrypted) and no passphrase
    has been provided yet. The app serves only the unlock flow in this state."""


class WrongPassphraseError(RuntimeError):
    """The provided passphrase does not open this database (loud, typed)."""


class StoreHeldError(WrongPassphraseError):
    """Row 154: another connection held the file, so the passphrase was never checked. A ``WrongPassphraseError`` for every
    caller that only needs "it did not open"; a caller that answers the person catches this first, by its class, and says
    "in use, try again" instead of "wrong passphrase". The busy error is chained as its cause."""


def set_passphrase(p: str | None) -> None:
    global _passphrase, _key_generation
    if p:
        _guard_the_key()  # before the process holds the key, not after
    with _lock:
        _passphrase = p or None
        _key_generation += 1
    try:  # a store that was locked may read now: do not serve the held failure of the old key
        from src.config.kv_store import clear_failures, forget_stores

        clear_failures()
        if p:
            forget_stores()  # a key is actually set (unlock, create): the store seen before is not this one
    except Exception:  # noqa: BLE001, S110 - never a reason for the key to be refused
        pass
    # The scrub keeps ONE cache entry: the passphrases it last took out of a text and the shapes it made of them. A failed
    # unlock or create and the crypto-erase clear the session's passphrase here, so they clear that copy too (a core dump is in
    # the rule). Outside the lock, and never a reason for the call to fail.
    try:
        from src.monitoring.secret_scrub import forget_held

        forget_held()
    except Exception:  # noqa: BLE001 - the passphrase is set; a copy that could not be dropped is replaced by the next scrub
        pass


def get_passphrase() -> str | None:
    with _lock:
        return _passphrase


#: Moves on EVERY ``set_passphrase`` (a set or a clear), so a holder of something opened with the key can tell whether the key it
#: was opened with is still the one held: the same passphrase set again after a clear is a new generation (open-on-main row 85).
_key_generation = 0


def key_generation() -> int:
    with _lock:
        return _key_generation


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
    """True = ciphertext header, False = plaintext SQLite, None = missing/empty.

    R789 (row 310): on POSIX this never CLOSES a descriptor on the file. Closing any descriptor on a file drops every
    fcntl lock the process holds on it, SQLite's included, and this runs on every :func:`connect`: measured, one plain
    ``open``/``close`` here let another process take a store this process still had a connection on (the country
    migration took it under a running app, whose next write left an alpha-3 marker over alpha-2 rows; in some runs two
    writers on one WAL zeroed the header). The header is read with ``pread`` on a descriptor kept per file
    (:func:`store_reader`). Windows has no such locks and a held descriptor would block ``os.replace`` there, so it reads
    as it always did."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    if st.st_size == 0:
        return None
    if os.name == "nt":
        try:
            with open(p, "rb") as fh:
                return fh.read(16) != _SQLITE_MAGIC
        except OSError:
            return None
    for _attempt in range(3):
        try:
            with store_reader(p) as fd:
                head = os.pread(fd, 16, 0)
                after = os.fstat(fd)
            if (after.st_dev, after.st_ino) == (st.st_dev, st.st_ino):
                return head != _SQLITE_MAGIC
            # Row 335: the number led to another file by the end of the read (a close elsewhere freed it and an open took
            # it), or the name was replaced. Bytes of the file the name leads to NOW are its answer; any other file's are not.
            st = p.stat()
        except OSError:
            return None
        if st.st_size == 0:
            return None
        if (after.st_dev, after.st_ino) == (st.st_dev, st.st_ino):
            return head != _SQLITE_MAGIC
    # Three reads, none of the file the name leads to: the answer an unreadable file has always had ("could not read").
    # Never a verdict from another file's bytes, and never a made-up True: callers act on True (an encrypt skips the store
    # as "already encrypted", an erase skips the whole-file rewrite a plaintext body needs).
    return None


# --- R789: header reads that never drop a lock ----------------------------------------------------------------- #
#
# A Python read of a file SQLite may have open here takes a read-only descriptor through :func:`_acquire` and gives it
# back through :func:`_release`. The descriptor is CLOSED at the release only when closing it can drop nothing: no other
# descriptor of this process is open on the file or on the other files of its SQLite group (``X``, ``X-wal``, ``X-shm``,
# ``X-journal``: a connection on ``X`` opens its logs lazily, so a log with no descriptor yet is still "held" while ``X``
# has one), no SQLite open is in flight in this process (:func:`sqlite_opening`, entered by :func:`connect` and the other
# places that open a store), and no other reader of ours is using it. Otherwise it is PARKED, reused by the next read of
# the same file, and closed by a later release once the group is free. So a file SQLite holds is never closed under it,
# and a file it does not hold (a backup member, an export, a candidate on a removable drive) is not kept open. The decision
# and the close happen under ``_hdr_lock``, and a SQLite open counts itself in under the same lock before it opens, so a
# connection cannot appear between the check and the close. Descriptors are opened ``O_CLOEXEC`` and ``O_NONBLOCK`` (a FIFO
# at a store path never blocks while the lock is held) and only for regular files.
_hdr_fds: dict[tuple[int, int], list[int]] = {}  # every descriptor of ours on a file; the first is the one read
_hdr_names: dict[tuple[int, int], str] = {}  # the name the file was read by, for its group
_hdr_uses: dict[tuple[int, int], int] = {}  # readers of ours using it now
_hdr_opening = 0  # SQLite opens in flight in this process
_hdr_lock = threading.RLock()  # re-entrant: the audit hook below may run while this thread holds it
_sweep_lock = threading.Lock()  # one sweep at a time: only a sweep closes, so a listing it made stays true for it
_hdr_gen = 0  # bumped by every SQLite open that starts in this process (counted or audited)
_audit_pending: dict[int, list[float]] = {}  # thread -> start times of stdlib sqlite3 opens not yet returned
_AUDIT_STALE_S = 60.0  # an open that never reported its handle (it raised) stops counting after this
_GROUP_SUFFIXES = ("-wal", "-shm", "-journal")
_hdr_forgotten: list[tuple[tuple[int, int], int]] = []  # (key, number) of records forgotten since the last sweep (row 335)


@contextlib.contextmanager
def sqlite_opening():
    """Around every SQLite open (sqlcipher3's above all, which the interpreter does not audit) of a file this process may
    also read from Python (R789): while one is in flight, no read of ours closes a descriptor, and one that started during a
    sweep makes that sweep close nothing, so a lock the new connection takes cannot be dropped by a close that raced it."""
    global _hdr_opening, _hdr_gen
    counted = False
    try:
        with _hdr_lock:
            _hdr_opening += 1
            _hdr_gen += 1
            counted = True
        yield
    finally:
        with _hdr_lock:
            if counted:
                _hdr_opening -= 1
        _sweep()  # what reads during the open parked; the new connection's own files stay (they are foreign now)


def _sqlite_audit(event: str, args) -> None:
    """Every stdlib ``sqlite3.connect`` anywhere in the process counts as an open in flight from before it opens the file
    until its handle exists (the interpreter's ``sqlite3.connect`` and ``sqlite3.connect/handle`` audit events), so an
    opener nobody wrapped in :func:`sqlite_opening` is covered too. One that raises never reports a handle: it stops
    counting after ``_AUDIT_STALE_S`` (an open itself takes no lock and does not wait on one)."""
    if event == "sqlite3.connect":
        global _hdr_gen
        with _hdr_lock:
            _hdr_gen += 1
            _audit_pending.setdefault(threading.get_ident(), []).append(time.monotonic())
    elif event == "sqlite3.connect/handle":
        with _hdr_lock:
            pending = _audit_pending.get(threading.get_ident())
            if pending:
                pending.pop()


def _opening_now_locked() -> bool:
    if _hdr_opening:
        return True
    cutoff = time.monotonic() - _AUDIT_STALE_S
    for tid in list(_audit_pending):
        live = [t for t in _audit_pending[tid] if t > cutoff]
        if live:
            _audit_pending[tid] = live
            return True
        del _audit_pending[tid]
    return False


if os.name != "nt":
    sys.addaudithook(_sqlite_audit)


def pin_store(path: Path | str) -> None:
    """See :func:`src.database.store_pins.pin_store` (the session names the library there, without importing this module)."""
    store_pins.pin_store(path)


def _not_regular(mode: int) -> OSError:
    if stat.S_ISDIR(mode):
        return IsADirectoryError(errno.EISDIR, "is a directory")
    return OSError(errno.EINVAL, "not a regular file")


def _still_ours_locked(fd: int, key: tuple[int, int]) -> bool:
    """Whether the recorded descriptor ``fd`` is still the one this module opened on ``key`` (row 335). Call under ``_hdr_lock``,
    in the same hold as the reuse or the close it permits.

    A number is only a number: a double close anywhere in the process (a library, another component) frees it, and the next
    open of any file takes it, a SQLite connection's above all. Closing it then drops that connection's locks; reading it
    reads another file. Ours is a regular file on ``key`` opened read-only with ``O_NONBLOCK``, which SQLite never sets, and
    without ``O_NOFOLLOW``, which SQLite sets, as do this repository's other non-blocking readers except
    ``regular_file`` with ``follow_links=True`` (sealed and backup files, never a store's group: the (device, inode) half
    keeps those apart). A descriptor that fails any part, or that
    ``fstat`` or ``fcntl`` cannot answer for, is not ours: never closed, never read.

    STATED LIMITS: the ``fstat`` runs under ``_hdr_lock`` (the ruling: the check and the use in one hold), and a sweep checks
    EVERY record (a stale record of any file may be the number a connection on the store being closed now holds), so a stalled
    network mount or a pulled drive holding any parked descriptor stalls the opens that wait for the lock with it. An
    ``fstat`` or ``fcntl`` error, even a passing one, forgets the record without closing it (the ruling: fail closed), so a
    flaky mount can leave descriptors open. On macOS ``F_GETFL`` does not report ``O_NOFOLLOW``, so there the flags half tells
    ours from SQLite's (``O_NONBLOCK``) but not from this repository's other non-blocking readers; the (device, inode) half
    still holds, and a sweep closes a number only while no connection holds the store's group, so no lock is dropped. A number freed and reused WHILE
    a reader of ours is using it (between :func:`_acquire` and :func:`_release`) cannot be seen by any check here; the header
    read checks the file again after reading (:func:`is_encrypted_file`)."""
    if os.name == "nt":
        return False  # no descriptor is ever recorded on Windows (its readers return early); never reach the absent fcntl
    try:
        st = os.fstat(fd)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    except OSError:
        return False
    return (
        (st.st_dev, st.st_ino) == key
        and (flags & os.O_ACCMODE) == os.O_RDONLY
        and bool(flags & getattr(os, "O_NONBLOCK", 0))
        and not flags & getattr(os, "O_NOFOLLOW", 0)
    )


def _forget_fd_locked(key: tuple[int, int], fd: int) -> None:
    """Drop ``fd`` from the record of ``key`` WITHOUT closing it: it is no longer ours (row 335). The number and the key go to
    :data:`_hdr_forgotten`, so a sweep that listed the process's descriptors before this (leaving the number out as ours)
    still counts what the number now leads to as foreign."""
    _hdr_forgotten.append((key, fd))
    fds = _hdr_fds.get(key)
    if fds is None:
        return
    while fd in fds:
        fds.remove(fd)
    if not fds:
        del _hdr_fds[key]
        if not _hdr_uses.get(key):
            _hdr_names.pop(key, None)
            _hdr_uses.pop(key, None)


def _validate_ours_locked() -> tuple[set[tuple[int, int]], bool]:
    """Check every recorded descriptor (row 335) and forget each one that is no longer ours. Returns the (device, inode) the
    sweep must count as foreign, and whether a number could not be placed (then this sweep closes nothing: what sits on it
    may be a connection's).

    Foreign: the file each forgotten number was recorded on (fail closed: it counts as held for this sweep), and the file it
    now leads to. That covers the numbers forgotten here and every number a reader forgot since the last sweep
    (:data:`_hdr_forgotten`), which this sweep's listing may have left out as ours."""
    for key, fds in list(_hdr_fds.items()):
        for fd in list(fds):
            if not _still_ours_locked(fd, key):
                _forget_fd_locked(key, fd)
    now_foreign: set[tuple[int, int]] = set()
    unplaced = False
    forgotten = list(_hdr_forgotten)
    _hdr_forgotten.clear()
    for key, fd in forgotten:
        now_foreign.add(key)
        try:
            st = os.fstat(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                unplaced = True  # something is there and cannot be read: keep everything
            continue
        now_foreign.add((st.st_dev, st.st_ino))
    return now_foreign, unplaced


def _acquire(p: Path) -> tuple[tuple[int, int], int]:
    """A read-only descriptor on the regular file at ``p`` and its (device, inode), counted in use until :func:`_release`.
    Raises ``OSError`` as ``os.open`` does; ``IsADirectoryError`` for a directory, ``OSError`` for another non-regular file.
    The stat and the open run OUTSIDE ``_hdr_lock`` (a hung mount stalls this read, not every connect); a descriptor not
    yet recorded is foreign to other reads, which then keep theirs: the safe direction."""
    name = os.path.abspath(p)  # before any open: a later chdir must not change which files the name means
    st = os.stat(name)
    if not stat.S_ISREG(st.st_mode):
        raise _not_regular(st.st_mode)  # refused before any open: no FIFO wait, no terminal, no device side effect
    key = (st.st_dev, st.st_ino)
    with _hdr_lock:
        fd = next((n for n in _hdr_fds.get(key, ()) if _still_ours_locked(n, key)), -1)
        for stale in list(_hdr_fds.get(key, ())):
            if stale == fd:
                continue
            _forget_fd_locked(key, stale)  # row 335: a stale number is never handed to a read, and never closed
        if fd >= 0:
            _hdr_names[key] = name
            _hdr_uses[key] = _hdr_uses.get(key, 0) + 1
            return key, fd
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
    fd = os.open(name, flags)
    got = os.fstat(fd)  # should this raise, the descriptor stays open: closing one we cannot place could drop a lock
    if not stat.S_ISREG(got.st_mode):
        os.close(fd)  # the name now leads to a non-regular file, which no SQLite connection holds a lock on
        raise _not_regular(got.st_mode)
    key = (got.st_dev, got.st_ino)  # what was opened, even if the name moved since the stat
    with _hdr_lock:
        for other, fds in list(_hdr_fds.items()):
            if fd not in fds:
                continue
            _forget_fd_locked(other, fd)  # row 335: a record of this number from before a foreign close is stale
        if key in _hdr_fds:
            _hdr_fds[key].append(fd)  # never closed here: another of ours is open on the file
        else:
            _hdr_fds[key] = [fd]
        _hdr_names[key] = name
        _hdr_uses[key] = _hdr_uses.get(key, 0) + 1
        return key, fd  # the one just opened: an older number recorded for the key was not checked in this hold (row 335)


def _release(key: tuple[int, int]) -> None:
    with _hdr_lock:
        _hdr_uses[key] -= 1
        if not _hdr_uses[key] and key not in _hdr_fds:  # its record was forgotten while in use (row 335): drop the rest
            _hdr_uses.pop(key, None)
            _hdr_names.pop(key, None)
    _sweep()


def _base_of(name: str) -> str:
    for suf in _GROUP_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def _group_of(name: str) -> tuple[str, set[tuple[int, int]], bool]:
    """The realpath of the store ``name`` belongs to, the (device, inode) of that store and its logs as they are now, and
    whether any of them could not be read for a reason other than its absence (a network mount's EIO, ESTALE): then the
    group is not known and the descriptor is kept."""
    base = _base_of(name)
    keys = set()
    uncertain = False
    for n in (base, *(base + s for s in _GROUP_SUFFIXES)):
        try:
            st = os.stat(n)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            uncertain = True  # a member that cannot be read may be the one a connection holds: keep
            continue
        keys.add((st.st_dev, st.st_ino))
    try:
        real = os.path.realpath(base)
    except (OSError, ValueError):
        real = base
    return real, keys, uncertain


def _foreign_fd_keys(ours: set[int]) -> set[tuple[int, int]] | None:
    """The (device, inode) of every descriptor of this process not in ``ours``; None if they cannot be listed. Lists
    ``/proc/self/fd`` or ``/dev/fd`` and ``fstat``s each: nothing is opened to find out."""
    for d in ("/proc/self/fd", "/dev/fd"):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        keys = set()
        for name in names:
            try:
                n = int(name)
            except ValueError:
                continue
            if n in ours:
                continue
            try:
                st = os.fstat(n)
            except OSError as exc:
                if exc.errno == errno.EBADF:
                    continue  # closed since the listing (the listing's own descriptor among them)
                return None  # a descriptor that cannot be read (EIO, ESTALE) may be a connection's: keep everything
            keys.add((st.st_dev, st.st_ino))
        return keys
    return None


def _idle_names_locked() -> dict[tuple[int, int], str]:
    return {k: _hdr_names.get(k, "") for k in _hdr_fds if not _hdr_uses.get(k)}


def _ours_locked() -> set[int]:
    return {fd for fds in _hdr_fds.values() for fd in fds}


def _sweep() -> None:
    """Close every descriptor of ours that no reader uses and that closing cannot hurt (see the block comment above).

    Three steps, so no stat, listing or open waits while ``_hdr_lock`` is held: under the lock, nothing may be opening,
    and the open generation is noted; with no lock, the process's descriptors are listed and the groups resolved by name;
    under the lock again, if any SQLite open started since the note (counted or audited) or one is in flight, nothing is
    closed; otherwise the decision and the close are made. The close itself stays under the lock: deciding and closing
    must be one step against any open, so a close that a stalled mount holds up holds up opens with it. A descriptor any
    connection made before the note is in the listing; one made after it changed the generation. A descriptor that cannot
    be read, or a group member that cannot be stat'ed for a reason other than its absence, keeps everything. Sweeps run
    one at a time (``_sweep_lock``), and only a sweep closes, so the descriptor numbers listed stay what they were.

    What this costs: a descriptor whose sweep was skipped (another sweep running, an open in flight) stays open until a
    later read of ours sweeps, so a file deleted meanwhile keeps its disk space until then or until the process exits. The
    audit hook sees this interpreter only; nothing here runs SQLite in a subinterpreter."""
    if not _sweep_lock.acquire(blocking=False):
        return  # another sweep is running; what this release parked waits for the next one
    try:
        with _hdr_lock:
            if _opening_now_locked():
                return
            gen = _hdr_gen
            idle = _idle_names_locked()
            ours = _ours_locked()
        if not idle:
            return
        foreign = _foreign_fd_keys(ours)
        if foreign is None:
            return  # cannot tell: keep them all (a kept descriptor drops nothing)
        groups = {k: _group_of(name) for k, name in idle.items()}
        with _hdr_lock:
            if _hdr_gen != gen or _opening_now_locked():
                return
            # Row 335: the listing left out every number recorded as ours. One a foreign close freed and an open reused is not
            # ours any more: it is forgotten, and what it now leads to (a connection's file, perhaps) counts as foreign.
            now_foreign, unplaced = _validate_ours_locked()
            if unplaced:
                return
            _close_free_locked(groups, foreign | now_foreign)
    finally:
        _sweep_lock.release()


def _close_free_locked(
    groups: dict[tuple[int, int], tuple[str, set[tuple[int, int]], bool]], foreign: set[tuple[int, int]]
) -> None:
    for key, (real, group, uncertain) in groups.items():
        if key not in _hdr_fds or _hdr_uses.get(key) or uncertain:
            continue
        reachable = key in group  # the name still leads to this file
        if reachable and real in store_pins.PINNED:
            continue  # the library: kept while it is the library (the coordinator's fallback)
        if reachable:
            # The store and its logs as the name finds them now, and any older file of ours recorded under the same store
            # name (a connection may still have it open and would open its logs by name).
            base = _base_of(_hdr_names.get(key, ""))
            held = group | {k for k, n in _hdr_names.items() if k in _hdr_fds and _base_of(n) == base} | {key}
        else:
            held = {key}  # a replaced file is judged alone: its name now leads elsewhere, and so would a lazy log open
        if held & foreign:
            continue
        if any(_hdr_uses.get(k) for k in held if k != key):
            continue  # a reader of ours on the same group: the group's descriptors stay with it
        for fd in _hdr_fds.pop(key):
            if not _still_ours_locked(fd, key):
                continue  # row 335: not ours any more (checked under this same hold): forgotten, never closed
            with contextlib.suppress(OSError):
                os.close(fd)
        _hdr_names.pop(key, None)
        _hdr_uses.pop(key, None)


@contextlib.contextmanager
def store_reader(path: Path | str):
    """A read-only descriptor on ``path`` whose use never drops this process's locks on it (R789), for every Python read of
    a file SQLite may have open here: the store, its ``-wal``/``-shm``, a snapshot being written.

    On POSIX the descriptor may be SHARED with other readers of the same file: read it only at explicit offsets
    (:func:`read_at`, ``os.sendfile`` with an offset), never with ``read``/``lseek``, which move a shared position. It is
    closed after the block only when nothing of this process holds the file (see :func:`_acquire`). On Windows (no fcntl
    locks) it is a private descriptor, closed on exit. Raises ``OSError`` as ``os.open`` does."""
    if os.name == "nt":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            yield fd
        finally:
            os.close(fd)
        return
    key, fd = _acquire(Path(path))
    try:
        yield fd
    finally:
        _release(key)


class _HeldFile:
    """A read-only file object over a :func:`store_reader` descriptor with a position of its OWN (``read``, ``seek``,
    ``tell``, ``fileno``), so code written for ``open(path, "rb")`` reads the store without closing a descriptor SQLite's
    locks depend on (R789). ``close`` gives the descriptor back (``on_close``); it never closes one SQLite needs."""

    def __init__(self, fd: int, on_close=None) -> None:
        self._fd = fd
        self._pos = 0
        self._on_close = on_close
        self.closed = False

    def fileno(self) -> int:
        return self._fd

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            parts = []
            while True:  # one pread returns at most about 2 GiB on Linux: read to the end as a file object does
                data = read_at(self._fd, 1 << 30, self._pos)
                if not data:
                    break
                parts.append(data)
                self._pos += len(data)
            return b"".join(parts)
        data = read_at(self._fd, n, self._pos)
        self._pos += len(data)
        return data

    def readinto(self, buf) -> int:
        data = self.read(len(buf))
        buf[: len(data)] = data
        return len(data)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            self._pos = offset
        elif whence == os.SEEK_CUR:
            self._pos += offset
        elif whence == os.SEEK_END:
            self._pos = os.fstat(self._fd).st_size + offset
        else:
            raise ValueError(f"whence {whence!r}")
        return self._pos

    def tell(self) -> int:
        return self._pos

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            if self._on_close is not None:
                self._on_close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def open_held(path: Path | str, mode: str = "rb", buffering: int = 0):
    """A drop-in for ``open(path, "rb", buffering=0)`` on a file SQLite may have open in this process (R789): on POSIX a
    :class:`_HeldFile` whose ``close`` never closes a descriptor SQLite's locks depend on; on Windows the ordinary ``open``.
    Close it (a ``with`` block): until then the descriptor counts as in use."""
    if mode != "rb":
        raise ValueError("open_held reads only")
    if os.name == "nt":
        return open(path, "rb", buffering=buffering)  # noqa: SIM115 - the caller's ``with`` closes it
    key, fd = _acquire(Path(path))
    return _HeldFile(fd, on_close=lambda: _release(key))


@contextlib.contextmanager
def store_file(path: Path | str):
    """``open(path, "rb")`` for a file SQLite may have open in this process (R789): a :class:`_HeldFile` over
    :func:`store_reader`, so leaving the block never closes a descriptor SQLite's locks depend on, on POSIX."""
    with store_reader(path) as fd:
        yield _HeldFile(fd)


def read_at(fd: int, n: int, offset: int) -> bytes:
    """``n`` bytes at ``offset`` (fewer at the end of the file) without moving the descriptor's position where the platform
    can (``os.pread``); Windows, whose descriptor from :func:`store_reader` is private, seeks then reads."""
    if hasattr(os, "pread"):
        return os.pread(fd, n, offset)
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, n)


def _sql_literal_escape(value: str) -> str:
    """SQL string-literal escaping: double embedded single quotes so ``value``
    stays a correct literal instead of breaking out of its surrounding quotes.
    Neither PRAGMA nor ``sqlcipher_export`` accepts a bound parameter for the
    strings they take, so this is the interpolation-site defense used
    wherever this module builds one of those statements (the passphrase in
    ``_apply_key``/the two ATTACH ... KEY sites, and ``_export``'s alias)."""
    return value.replace("'", "''")


def _apply_key(conn, key: str) -> None:
    # A key with a lone surrogate in it cannot be written into a statement, and the error the driver raises for it names the
    # character and its place in the key: refused first with fixed words (``secret_scrub.passphrase_bytes``).
    from src.monitoring.secret_scrub import passphrase_bytes

    _guard_the_key()  # the key is about to go to the engine, and a process that was only handed it has not held it yet
    passphrase_bytes(key)
    cur = conn.cursor()
    try:
        # The key never reaches any log.
        cur.execute(f"PRAGMA key = '{_sql_literal_escape(key)}'")
    finally:
        cur.close()


def _read_only_uri(p: PurePath) -> str:
    """The ``mode=ro`` URI of an ABSOLUTE path, in any of the forms a Windows data directory takes. ``as_uri`` writes a UNC path with
    the server as the URI's authority (``file://nas/share/x``), and SQLite refuses a URI authority other than ``localhost``: it wants
    the empty authority and the path ``//nas/share/x`` (``file:////nas/share/x``). The extended prefixes (``\\\\?\\D:\\x``,
    ``\\\\?\\UNC\\nas\\share\\x``) are written without the prefix first, which ``as_uri`` turns into a nonsense authority."""
    if isinstance(p, PureWindowsPath):
        text = str(p)
        if text.upper().startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith(("\\\\?\\", "\\\\.\\")):
            text = text[4:]
        uri = PureWindowsPath(text).as_uri()
        if not uri.startswith("file:///"):
            uri = "file:////" + uri[len("file://"):]
    else:
        uri = p.as_uri()
    return uri + "?mode=ro"


def _read_only_target(p: Path) -> str:
    """The URI of ``p`` opened ``mode=ro`` (``uri=True`` goes with it). The path is made absolute and
    percent-encoded by ``as_uri``, so a space or a ``?`` in a directory name is not read as URI syntax."""
    return _read_only_uri(p.resolve())


#: SQLite's primary "busy" and "locked" result codes (an extended code, such as SQLITE_BUSY_SNAPSHOT, is masked to its primary).
_HELD_CODES = (5, 6)


def held_by_another(exc: BaseException | None) -> bool:
    """True when an open failed because another connection holds a lock on the file (row 154): a fact about the file now, never
    about the key or the page size, so no other candidate can open it either."""
    code = getattr(exc, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 0xFF) in _HELD_CODES


def _try_open_encrypted(
    p: Path, key: str, check_same_thread: bool, timeout: float, page_size, *, last_error=None, read_only: bool = False
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
    never lost even though this function itself never raises. ``read_only`` opens the file ``mode=ro`` (see
    :func:`connect`)."""
    from sqlcipher3 import dbapi2 as sqc

    conn = None
    try:
        if read_only:
            conn = sqc.connect(_read_only_target(p), uri=True, check_same_thread=check_same_thread, timeout=timeout)
        else:
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


def _connect(
    path: Path | str,
    *,
    key: str | None = None,
    create_encrypted: bool | None = None,
    check_same_thread: bool = True,
    timeout: float = 30.0,
    cipher_page_size: int | None = None,
    read_only: bool = False,
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

    ``timeout`` is the WHOLE wait for a store another connection holds (row 154): the page-size walk below stops at the first
    busy or locked candidate, where it once waited ``timeout`` at each of up to nine.

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

    ``read_only`` opens an EXISTING file ``mode=ro``: the connection cannot write the file, its log or the
    key, and it never creates one (a missing or empty file raises ``FileNotFoundError``). It exists because
    ``PRAGMA query_only`` does NOT make a connection harmless: the LAST connection on a file that closes
    checkpoints a leftover ``-wal`` into the file and deletes it, with the right key and with a wrong one
    (measured on a real encrypted store: 65 KB of log folded into the file by a read that closed, a wrong
    key included), and that destroys the leftover log a crash left for whoever reads it next. A read-only
    connection leaves the file and its log as they were (the ``-shm`` beside them is the log's index in shared
    memory, rebuilt by any reader; it may create an empty ``-wal`` and a ``-shm`` beside a file that had none,
    which the next read-write open takes over). The
    price: it needs a directory its process can write to, for those two files, and where it cannot have
    them the open fails and reads as a wrong key.
    """
    p = Path(path)
    state = is_encrypted_file(p)
    use_key = key if key is not None else get_passphrase()
    if read_only and state is None:
        raise FileNotFoundError(f"{p.name} does not exist or is empty: a read-only open never creates a file")

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
        first_error: list = []
        past_page_one: list = []
        held: BaseException | None = None
        for candidate in candidates:
            # Each attempt pays one key derivation: counted for the pass summary (``open_stats``; numbers only, it is
            # handed the path and whether the file opened, never the key or the exception).
            counted = open_stats.begin()
            conn = _try_open_encrypted(
                p, use_key, check_same_thread, timeout, candidate, last_error=last_error, read_only=read_only
            )
            open_stats.end(counted, p, conn is not None)
            if conn is not None:
                winning_candidate = candidate
                break
            if last_error:
                if not first_error:
                    first_error = list(last_error)
                if not past_page_one and getattr(last_error[0], "sqlite_errorcode", None) not in (None, 26):
                    past_page_one = list(last_error)
                if held_by_another(last_error[0]):
                    held = last_error[0]
                    # Row 154: the file is locked by another connection, which no page size changes: every later candidate
                    # would wait out its own busy timeout and pay its own key derivation to fail the same way. It raises
                    # StoreHeldError, chained from this busy error even when an earlier candidate failed another way: the
                    # at-rest status reads it as busy and the unlock routes as "in use" (409), never as a wrong passphrase.
                    # The trade: a lock released after the first busy timeout is not waited out again by the next
                    # candidate (30 s at the default timeout, nine of them before).
                    break
        if conn is None and held is not None:
            raise StoreHeldError(
                f"another program is using {p.name} right now, so the passphrase could not be checked"
            ) from held
        if conn is None:
            # Chained from the error of the candidate that got PAST page 1 (any code but 26, the HMAC check every wrong
            # page size and every wrong passphrase fails on), else the first candidate's: the LAST candidate is the
            # undeclared default size, whose failure is always code 26, so a damaged schema page under the right key and
            # size read as a wrong passphrase. The first candidate is the right size only when it is cached for the path;
            # a file nothing opened yet in this process reaches its size later in the list.
            cause = (past_page_one or first_error or [None])[0]
            raise WrongPassphraseError(
                f"the passphrase does not open {p.name} (or the file is damaged)"
            ) from cause
        if cipher_page_size is None:
            with _lock:
                _last_good_page_size[str(p.resolve())] = winning_candidate
        return conn

    if state is False:
        if read_only:
            return sqlite3.connect(
                _read_only_target(p), uri=True, check_same_thread=check_same_thread, timeout=timeout
            )
        return sqlite3.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)

    # Fresh file. Decide its at-rest fate EXPLICITLY (never by accident):
    # an explicit caller key outranks the ambient plaintext opt-out; the
    # opt-out outranks the process passphrase; no decision = locked.
    if key:
        if not have_driver():  # pragma: no cover
            raise DatabaseLockedError("sqlcipher3 driver unavailable; cannot create encrypted DB")
        from sqlcipher3 import dbapi2 as sqc

        conn = sqc.connect(str(p), check_same_thread=check_same_thread, timeout=timeout)
        try:
            _apply_key(conn, key)
            # ORDER MATTERS (empirically verified, DB-10 §1b, 2026-07-17): on a fresh
            # SQLCipher connection cipher_page_size MUST be set BEFORE auto_vacuum —
            # setting auto_vacuum first corrupts page 1's HMAC once the schema is
            # written, and the store then fails to reopen AT ALL, not merely at the
            # wrong size. This was proven by the page-size A/B bench's own
            # rebuild_at_pragmas; the bench was removed on 2026-07-31 (Settings review
            # ruling 6) after delivering its verdict, so the ordering fact is recorded
            # here — it is load-bearing for every encrypted store this factory creates.
            page_size = cipher_page_size if cipher_page_size is not None else _FRESH_PAGE_SIZE
            conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
            conn.execute(f"PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        except BaseException:
            # An engine that refuses the key or a page setting must not leave its connection open; a close that fails too
            # must not replace the error being raised.
            with contextlib.suppress(Exception):
                conn.close()
            raise
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
        try:
            _apply_key(conn, use_key)
            # Same ordering requirement as the explicit-key branch above.
            page_size = cipher_page_size if cipher_page_size is not None else _FRESH_PAGE_SIZE
            conn.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
            conn.execute(f"PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        except BaseException:
            # An engine that refuses the key or a page setting must not leave its connection open; a close that fails too
            # must not replace the error being raised.
            with contextlib.suppress(Exception):
                conn.close()
            raise
        return conn
    raise DatabaseLockedError(
        f"{p.name} does not exist yet: choose a passphrase (encrypted by default) "
        "or set OO_DB_PLAINTEXT=1 explicitly"
    )


def connect(
    path: Path | str,
    *,
    key: str | None = None,
    create_encrypted: bool | None = None,
    check_same_thread: bool = True,
    timeout: float = 30.0,
    cipher_page_size: int | None = None,
    read_only: bool = False,
):
    """Open ``path`` (see :func:`_connect` for the driver and key rules) with the search
    index's transform functions registered.

    The article index's sync triggers call them (Q506/Q507, ``src/database/fts_norm.py``),
    so a raw connection without them could not write ``articles`` -- the merge's working
    copy is written through exactly this factory.

    ``read_only=True`` opens an existing file ``mode=ro`` and writes nothing, its leftover log included:
    see :func:`_connect` for why ``PRAGMA query_only`` is not that.

    R802: a store in a folder an erase in this process has started on is never opened (``DataFolderErased``): an open of a missing file
    would make a fresh store in the folder being erased, and one that is there is the erase's to destroy."""
    from src.paths import refuse_if_erased, sqlite_target

    _target = sqlite_target(str(path))  # a "file:" URI is read the way SQLite reads it, never let through as a name
    if _target is not None:
        refuse_if_erased(_target)
    _IN_FACTORY.depth = getattr(_IN_FACTORY, "depth", 0) + 1
    try:
        with sqlite_opening():  # R789: no Python read closes a descriptor while this open may be taking a lock
            conn = _connect(
                path,
                key=key,
                create_encrypted=create_encrypted,
                check_same_thread=check_same_thread,
                timeout=timeout,
                cipher_page_size=cipher_page_size,
                read_only=read_only,
            )
    finally:
        _IN_FACTORY.depth -= 1
    from src.database.fts_norm import register

    register(conn)
    _watch_this_connection(path, conn)
    return conn


# --- R827 R7(a): which tables a restore wrote into its working copy ----------------------- #
#
# The import checks a working copy at an intermediate checkpoint with ``PRAGMA quick_check(<table>)`` on the
# tables it WROTE rather than a walk of the whole file (the full walk runs before the run's final activation).
# The write set is taken from SQLite's own authorizer on every connection this factory opens to a watched
# path, so a write through any helper is seen, not only the merge's. It errs toward too many tables: a write
# fired by a trigger counts, a virtual table's write counts its shadow tables (the caller adds them), and
# anything that changes the schema of a table or an index, or rewrites the file (REINDEX, writable_schema,
# incremental_vacuum), or a callback that fails, records ``"*"``: unknown, so the whole file is checked.

#: The write set of a watched path: table names, plus "*" when it cannot be known.
WRITE_SET_UNKNOWN = "*"
_WRITE_WATCH: dict[str, set[str]] = {}
_WRITE_WATCH_LOCK = threading.Lock()
_FILE_WIDE_PRAGMAS = frozenset({"writable_schema", "incremental_vacuum", "schema_version"})


def _watch_key(path: Path | str) -> str | None:
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError, ValueError):
        return None


#: The connect() factory's own opens (the recorder is installed on them): the audit hook below leaves them alone.
_IN_FACTORY = threading.local()


def _unrecorded_open(event: str, args: tuple) -> None:
    """``sys.addaudithook`` for CPython's ``sqlite3.connect`` event: an open of a WATCHED file that did not come through
    :func:`connect` has no recorder, so whatever it writes is unseen and the set becomes unknown. Read-only opens
    (``mode=ro``) cannot write and are left alone. Returns at once when nothing is watched; never raises (an audit
    hook that raises would fail the caller's open)."""
    if event != "sqlite3.connect" or not _WRITE_WATCH or getattr(_IN_FACTORY, "depth", 0):
        return
    try:
        name = args[0] if args else None
        if isinstance(name, bytes):
            name = os.fsdecode(name)
        if not isinstance(name, (str, os.PathLike)):
            return
        name = os.fspath(name)
        if name.startswith("file:") and "mode=ro" in name.partition("?")[2]:
            return
        from src.paths import sqlite_target

        target = sqlite_target(name)
        key = _watch_key(target) if target else None
        with _WRITE_WATCH_LOCK:
            seen = _WRITE_WATCH.get(key) if key is not None else None
        if seen is not None:
            seen.add(WRITE_SET_UNKNOWN)
    except Exception:  # noqa: BLE001 - when this cannot tell, every watched set becomes unknown: the whole file is checked
        with _WRITE_WATCH_LOCK:
            for seen in _WRITE_WATCH.values():
                seen.add(WRITE_SET_UNKNOWN)


_AUDIT_HOOK_ADDED = False


def _add_audit_hook_once() -> None:
    global _AUDIT_HOOK_ADDED
    with _WRITE_WATCH_LOCK:
        if _AUDIT_HOOK_ADDED:
            return
        _AUDIT_HOOK_ADDED = True
    sys.addaudithook(_unrecorded_open)


def _another_process_holds(path: Path | str) -> bool | None:
    """Whether ANOTHER process holds a POSIX lock on ``path`` or its ``-wal``/``-shm`` right now: every SQLite connection
    in WAL mode does, for as long as it is open. Read from ``/proc/locks`` by inode, so this process opens no descriptor
    on the files (closing one would drop its own SQLite locks, R789). None where it cannot be told (no ``/proc/locks``:
    every system but Linux). Only a yes or no comes out; no process id is kept."""
    try:
        raw = Path("/proc/locks").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    ids: set[tuple[int, int, int]] = set()
    for suffix in ("", "-wal", "-shm"):
        try:
            st = os.stat(f"{path}{suffix}")
        except FileNotFoundError:
            continue
        except OSError:
            return None
        ids.add((os.major(st.st_dev), os.minor(st.st_dev), st.st_ino))
    return _foreign_lock_in(raw, ids, os.getpid())


def _foreign_lock_in(raw: str, ids: set[tuple[int, int, int]], me: int) -> bool | None:
    """``/proc/locks`` lines: ``N: KIND MODE TYPE PID MAJ:MIN:INODE START END`` (a ``->`` blocked waiter adds one field)."""
    for line in raw.splitlines():
        parts = line.replace("->", " ").split()
        try:
            at = next(i for i, part in enumerate(parts) if part.count(":") == 2)
            pid = int(parts[at - 1])
            maj, mnr, ino = parts[at].split(":")
            key = (int(maj, 16), int(mnr, 16), int(ino))
        except (StopIteration, ValueError, IndexError):
            continue  # a line not in this shape names no file of ours
        if key in ids and pid != me:
            return True
    return False


def watch_writes(path: Path | str) -> set[str]:
    """Start recording which tables of ``path`` the connections this process opens write; returns the live set
    (shared by every later call for the same path until :func:`unwatch_writes`)."""
    _add_audit_hook_once()
    key = _watch_key(path)
    if key is None:
        return {WRITE_SET_UNKNOWN}
    with _WRITE_WATCH_LOCK:
        return _WRITE_WATCH.setdefault(key, set())


def watched_writes(path: Path | str) -> set[str] | None:
    """The write set recorded for ``path`` so far, or None when it is not watched (unknown).

    The set is a proof only while every writer of the file was recorded (Plan, row 408 R7a: fail safe by default).
    Writes from this process through :func:`connect` are; an open of the file through the standard driver anywhere
    else in this process makes the set unknown (:func:`_unrecorded_open`); and another process holding the file open
    now, or a system where that cannot be told, makes it unknown here. A process that reports its own tables adds them
    to the set :func:`watch_writes` returns (or adds :data:`WRITE_SET_UNKNOWN`)."""
    key = _watch_key(path)
    with _WRITE_WATCH_LOCK:
        got = _WRITE_WATCH.get(key) if key is not None else None
    if got is None:
        return None
    _note_foreign_holder(path, got)
    with _WRITE_WATCH_LOCK:
        return set(got)


def _note_foreign_holder(path: Path | str, seen: set[str]) -> None:
    try:
        held = _another_process_holds(path)
    except Exception:  # noqa: BLE001 - could not be told: unknown
        held = None
    if held is not False:
        with _WRITE_WATCH_LOCK:
            seen.add(WRITE_SET_UNKNOWN)


def unwatch_writes(path: Path | str) -> None:
    key = _watch_key(path)
    if key is not None:
        with _WRITE_WATCH_LOCK:
            _WRITE_WATCH.pop(key, None)


def _watch_this_connection(path: Path | str, conn) -> None:
    if not _WRITE_WATCH:
        return
    key = _watch_key(path)
    with _WRITE_WATCH_LOCK:
        seen = _WRITE_WATCH.get(key) if key is not None else None
    if seen is None:
        return
    _note_foreign_holder(path, seen)  # sampled at every open as well as at the check, so a holder that leaves early is seen
    # The authorizer's action codes are SQLite's own C constants, the same numbers in every driver (sqlite3, sqlcipher3).
    import sqlite3 as _s

    ok = _s.SQLITE_OK
    writes = {_s.SQLITE_INSERT, _s.SQLITE_UPDATE, _s.SQLITE_DELETE}
    triggers = {_s.SQLITE_CREATE_TRIGGER, _s.SQLITE_DROP_TRIGGER}
    file_wide = {
        _s.SQLITE_CREATE_TABLE, _s.SQLITE_DROP_TABLE, _s.SQLITE_CREATE_INDEX, _s.SQLITE_DROP_INDEX,
        _s.SQLITE_ALTER_TABLE, _s.SQLITE_CREATE_VTABLE, _s.SQLITE_DROP_VTABLE, _s.SQLITE_REINDEX,
    }
    pragma = _s.SQLITE_PRAGMA

    def _record(action, arg1, arg2, db, _trigger):  # names only: a PRAGMA's value (a key, say) is never kept
        try:
            if db not in (None, "main"):
                return ok
            if action in writes and arg1:
                seen.add(str(arg1))
            elif action in triggers:
                seen.add("sqlite_master")  # the schema itself is checked; the tables keep their pages
            elif action in file_wide:
                seen.add(WRITE_SET_UNKNOWN)
            elif action == pragma and arg2 is not None and str(arg1 or "").lower() in _FILE_WIDE_PRAGMAS:
                seen.add(WRITE_SET_UNKNOWN)
        except Exception:  # noqa: BLE001 - recording never refuses a statement; it makes the set unknown instead
            seen.add(WRITE_SET_UNKNOWN)
        return ok

    try:
        conn.set_authorizer(_record)
    except Exception:  # noqa: BLE001 - a connection that cannot record makes the set unknown: the whole file is checked
        seen.add(WRITE_SET_UNKNOWN)


def state_for_header(header: bool | None) -> str:
    """The lock-state DECISION, given the file's header reading.

    Split out of :func:`locked_state` so the middleware can reach it with a
    CACHED header (S3.6) without a second copy of the decision -- two
    implementations of one rule drift, and this one decides whether the app
    answers at all. The passphrase/plaintext inputs are read LIVE here, so only
    the file read is ever cached; unlocking changes the answer immediately.
    """
    if header is False:
        return "unlocked-plaintext"
    if header is True:
        return "unlocked-encrypted" if get_passphrase() else "locked"
    if plaintext_mode() or get_passphrase():
        return "unlocked-plaintext" if plaintext_mode() else "unlocked-encrypted"
    return "fresh"


def locked_state(path: Path | str) -> str:
    """One word for the boot machine + doctor: unlocked-plaintext |
    unlocked-encrypted | locked | fresh. Reads the header every call -- callers
    pass arbitrary paths (staged artifacts, backup members), so this one is
    deliberately uncached; :func:`main_header_state` is the hot-path variant."""
    return state_for_header(is_encrypted_file(path))


# --- S3.6: the header read, off the request path --------------------------- #
#
# The lock middleware runs for EVERY request -- every API call and every static
# asset -- and reached is_encrypted_file, i.e. exists() + stat() + open() +
# read(16) on the live store. MEASURED here: 19 us per call page-cached, 95 us
# with the page evicted before each call (4.9x) on a healthy disk. Small either
# way, and it is blocking file I/O on the EVENT LOOP that the answer does not
# need: the header changes only when the store file itself is created, replaced
# or wiped, and every one of those paths is ours.
#
# So the header is cached with BOTH belts the brief asks for: explicit
# invalidation from each mutator (enumerated at the call sites), and a short TTL
# so a path someone forgets to enumerate self-heals in seconds rather than
# never. The passphrase is NOT cached -- see state_for_header.
# Three separate variables rather than one dict[str, object]: the three values
# have three different types, and a heterogeneous dict would only be readable
# through casts -- which is how a cache starts returning the wrong field.
_HEADER_TTL_S = 5.0
_header_path: str | None = None
_header_value: bool | None = None
_header_at: float = 0.0
_header_lock = threading.Lock()


def invalidate_header_cache() -> None:
    """Forget the cached store header. Call from EVERY path that creates,
    replaces or removes the live database file."""
    global _header_path
    with _header_lock:
        _header_path = None


def main_header_state(path: Path | str) -> bool | None:
    """:func:`is_encrypted_file` for the live store, cached (see above)."""
    global _header_path, _header_value, _header_at
    key = str(path)
    now = time.monotonic()
    with _header_lock:
        if _header_path == key and (now - _header_at) < _HEADER_TTL_S:
            return _header_value
    header = is_encrypted_file(path)
    with _header_lock:
        _header_path, _header_value, _header_at = key, header, now
    return header


def attach(conn, path: Path | str, alias: str) -> None:
    """ATTACH a PLAINTEXT database (staged artifact members are plaintext by
    design). On a SQLCipher connection the empty KEY clause is mandatory or the
    attached DB would inherit the main key; stdlib sqlite3 has no KEY clause."""
    with sqlite_opening():  # R789: an ATTACH opens a file the audit hook does not see
        if _is_sqlcipher_conn(conn):
            conn.execute(f'ATTACH DATABASE ? AS "{alias}" KEY \'\'', (str(path),))
        else:
            conn.execute(f'ATTACH DATABASE ? AS "{alias}"', (str(path),))


def _is_sqlcipher_conn(conn) -> bool:
    return "sqlcipher" in type(conn).__module__


def _export(conn, alias: str) -> None:
    # Every real caller passes a fixed module-level literal ("snap"/"enc") for
    # the ATTACHed alias it just created — the assertion makes a future caller
    # that derives ``alias`` from anything else (a filename, a table name) fail
    # loudly here rather than silently opening a single-quote breakout inside
    # sqlcipher_export's string argument; _sql_literal_escape is the belt
    # underneath that suspenders, so a legitimately quote-containing value
    # (should this ever loosen) still produces a correct, safe literal.
    assert alias.isalnum(), f"_export alias must be alphanumeric, got {alias!r}"
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT sqlcipher_export('{_sql_literal_escape(alias)}')")
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


#: R794: the one sentence said when a plaintext copy failed part-way and its unfinished file could not be removed. It names the
#: path (the operator must find it) and nothing else: no key, no driver text. Translated x12 through ``ooServerText``.
SNAPSHOT_LEFT_ON_DISK = (
    'A plaintext copy of the store did not finish, and the unfinished file could not be removed: an incomplete plaintext copy may '
    'still be on disk at "{path}". It is not a usable snapshot; check that file and delete it yourself.'
)
class SnapshotLeftOnDisk(OSError):
    """R794: a plaintext copy failed part-way and the unfinished file it made could not be removed. The message is
    :data:`SNAPSHOT_LEFT_ON_DISK` with the path; raised with no cause or context, so no driver text travels with it and the
    words reach the operator whole (``http_detail`` keeps only the class of a chain that holds a driver's error)."""

    def __init__(self, path: Path) -> None:
        super().__init__(SNAPSHOT_LEFT_ON_DISK.format(path=path))
        self.path = path


#: R799: said when the private folder was moved during the copy and its files could not be removed (no handle on it could be held,
#: as on Windows, or removing through the handle failed). Translated x12 through ``ooServerText``.
SNAPSHOT_FOLDER_MOVED = (
    "A plaintext copy of the store did not finish, and its private folder was moved during the copy, so the unfinished file could "
    'not be removed: an incomplete plaintext copy may still be on disk, in the folder that was at "{path}". It is not a usable '
    "snapshot; find that folder, check it and delete it yourself."
)


class SnapshotFolderMoved(SnapshotLeftOnDisk):
    """R799: :class:`SnapshotLeftOnDisk` for a private folder moved during the copy whose files could not be removed."""

    def __init__(self, path: Path) -> None:
        OSError.__init__(self, SNAPSHOT_FOLDER_MOVED.format(path=path))
        self.path = path


def _make_new(dest_p: Path) -> tuple[int, int]:
    """Create ``dest_p`` as a new, empty regular file (never through a link, never over a file already there) and return its
    device and inode: the identity :func:`_remove_made` removes by, so a failure removes the file this call made and nothing
    else. An empty file opens as a new database; the descriptor is closed before SQLite opens the name."""
    fd = os.open(dest_p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    return st.st_dev, st.st_ino


def _still_made(dest_p: Path, made: tuple[int, int]) -> bool:
    """Whether ``dest_p`` is still the regular file :func:`_make_new` created (the name not followed)."""
    try:
        st = os.lstat(dest_p)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) == made


#: R799: every plaintext snapshot is written inside a fresh private folder with this name start, made beside its destination (so the
#: finished file is moved into place on the same file system) and removed whole on any failure. A folder left by a crash is removed at
#: the next snapshot in that folder and at start, only under the conditions :func:`sweep_snapshot_leftovers` lists.
SNAPSHOT_WORK_PREFIX = ".oo-snapshot-"
#: A leftover touched more recently than this may belong to a copy still running in another process: left for a later sweep.
_LEFTOVER_QUIET_S = 15 * 60
_active_work: set[str] = set()  # this process's private folders while their copy runs: never swept
_active_lock = threading.Lock()


def _dir_identity(path: Path) -> tuple[int, int] | None:
    """Device and inode of ``path`` when it is a real folder (the name not followed), else ``None``."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if stat.S_ISDIR(st.st_mode) else None


def _open_dir(work: Path, ident: tuple[int, int] | None) -> int | None:
    """A descriptor of the private folder ``work`` just made, held for the whole copy so its files are removed through it wherever
    the folder has been moved to; ``None`` where the platform cannot hold one (Windows) or the folder is not the one made."""
    if ident is None or os.unlink not in os.supports_dir_fd or not hasattr(os, "O_DIRECTORY"):
        return None
    try:
        fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != ident:
        os.close(fd)
        return None
    return fd


def _empty_held(work: Path, ident: tuple[int, int], fd: int) -> bool:
    """Empty the private folder through the descriptor held since it was made (R799, the coordinator's R794 condition): its files go
    wherever the folder now sits, even renamed away mid-copy. The emptied folder is then removed by name only while the name still
    holds it; an empty folder left elsewhere holds no copy. Returns whether no file of the copy is left. Never raises."""
    try:
        for name in os.listdir(fd):
            with contextlib.suppress(OSError):  # one entry that fails never keeps the others; what stays is said below
                os.unlink(name, dir_fd=fd)  # never follows; a sub-folder (never made here) fails, and the copy is said to be left
        if os.listdir(fd):
            return False
    except OSError:
        return False
    if _dir_identity(work) == ident:
        with contextlib.suppress(OSError):
            os.rmdir(work)
    return True


def _empty_and_remove(work: Path, ident: tuple[int, int], fd: int | None = None) -> bool:
    """Remove ``work`` and the files in it while it is still the folder ``ident`` names, never through a link: each entry is
    unlinked by name (an unlink never follows a link) and a sub-folder is never entered. Relative to a descriptor of the folder
    where the platform allows it, so a folder swapped for a link mid-way is not walked. With ``fd`` (the descriptor held since the
    folder was made) the files go through it wherever the folder now sits. Returns whether no file of it is left. Never raises."""
    if fd is not None:
        return _empty_held(work, ident, fd)
    try:
        if _dir_identity(work) != ident:
            return False
        if os.unlink in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
            fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                st = os.fstat(fd)
                if (st.st_dev, st.st_ino) != ident:
                    return False
                for name in os.listdir(fd):
                    os.unlink(name, dir_fd=fd)  # a sub-folder (never made here) fails, and the folder stays: said by the caller
            finally:
                os.close(fd)
        else:  # Windows: by name, the folder's identity checked again before each entry and each entry not followed
            for name in os.listdir(work):
                entry = work / name
                if _dir_identity(work) != ident or stat.S_ISDIR(os.lstat(entry).st_mode):
                    return False
                os.unlink(entry)
        if _dir_identity(work) != ident:
            return False
        os.rmdir(work)
        return True
    except OSError:
        # a name that vanished mid-walk may be the folder moved away with the copy still in it: never said to be removed
        return False


def _place(inner: Path, dest_p: Path) -> None:
    """Give the finished copy its name. The name is checked without following it and is never replaced: a hard link fails if
    anything (a file, a link) holds the name; where hard links are not available (some removable drives) the name is checked
    again and the file renamed, a rename that replaces a link replaces the link itself and never writes through it."""
    if os.path.lexists(dest_p):
        raise FileExistsError(errno.EEXIST, "the snapshot's name was taken during the copy")
    if os.name != "nt":
        try:
            os.link(inner, dest_p, follow_symlinks=False)
        except FileExistsError:
            raise
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK):
                raise
        else:
            return  # the private name goes with its folder: the caller records the placement first
        if os.path.lexists(dest_p):
            raise FileExistsError(errno.EEXIST, "the snapshot's name was taken during the copy")
    os.rename(inner, dest_p)  # Windows refuses an existing name


def _masked_place(name: str, *, in_data: bool = True) -> str:
    """A private folder's place for the log (R736): its folder as a role (the data folder, or ``...`` elsewhere), its own name
    masked. No user name or home folder is written."""
    from src.database.address_mask import masked_path

    return ("<data>/" if in_data else ".../") + masked_path(name)


def sweep_snapshot_leftovers(folder: Path | str) -> int:
    """Remove the private folders a crashed snapshot left in ``folder`` (R799). A folder is removed ONLY when it is a real folder
    (not a link), owned by the user running the app, carries :data:`SNAPSHOT_WORK_PREFIX`, sits directly inside the data folder (or
    a folder inside it), is not this process's running copy, and nothing in it changed for :data:`_LEFTOVER_QUIET_S`. Anything else
    with the prefix is left as it is and named in the log, masked. Where the owner cannot be read (Windows), nothing is removed.
    Returns how many were removed. Never raises."""
    removed = 0
    try:
        from src.paths import data_dir

        root = Path(os.path.realpath(data_dir()))
        here = Path(os.path.realpath(folder))
        if here != root and root not in here.parents:
            return 0
        entries = [e.name for e in os.scandir(here) if e.name.startswith(SNAPSHOT_WORK_PREFIX)]
    except Exception:  # noqa: BLE001 - a sweep never stops a snapshot or the start
        return 0
    for name in entries:
        path = here / name
        try:
            with _active_lock:
                if os.path.realpath(path) in _active_work:
                    continue
            st = os.lstat(path)
            why = None
            if not stat.S_ISDIR(st.st_mode):
                why = "not a folder"
            elif not hasattr(os, "getuid"):
                why = "its owner cannot be checked on this system"
            elif st.st_uid != os.getuid():
                why = "owned by another user"
            else:
                newest = max([st.st_mtime] + [os.lstat(path / n).st_mtime for n in os.listdir(path)])
                if time.time() - newest < _LEFTOVER_QUIET_S:
                    why = "changed recently (a copy may still be running)"
            if why is None and _empty_and_remove(path, (st.st_dev, st.st_ino)):
                removed += 1
                _LOG.info("removed a snapshot folder a stopped copy left: %s", _masked_place(name))
                continue
            _LOG.warning("a snapshot folder was left as it is (%s): %s", why or "it could not be removed", _masked_place(name))
        except Exception:  # noqa: BLE001 - one entry never stops the others
            _LOG.warning("a snapshot folder was left as it is (it could not be read): %s", _masked_place(name))
    return removed


def snapshot_to_plaintext(src: Path | str, dest: Path | str) -> Path:
    """Consistent PLAINTEXT snapshot of ``src`` (artifact members; the artifact's
    own envelope is the at-rest protection there).

    R794: a name this returns is always a WHOLE copy. R799: the copy is written inside a fresh private folder made beside ``dest``
    (``mkdtemp``: a new, unpredictable name made atomically; mode 0700, owner-only on POSIX; on Windows, with the Python 3.13 this app
    requires, an access list limited to the owner, SYSTEM and Administrators) and is given
    its name only once finished, the name checked without following it and never replaced (:func:`_place`). On any failure the
    whole private folder is removed, never through a link; if that removal fails, :class:`SnapshotLeftOnDisk` names the path that
    may still hold an incomplete plaintext copy (an interrupt is raised again as it was, carrying that path, with the path logged
    as an error). It narrows where plaintext can land; it does not make that impossible for a program running as the same user."""
    src_p, dest_p = Path(src), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    sweep_snapshot_leftovers(dest_p.parent)
    import tempfile

    work = Path(tempfile.mkdtemp(prefix=SNAPSHOT_WORK_PREFIX, dir=dest_p.parent))
    with _active_lock:
        _active_work.add(os.path.realpath(work))  # the sweep compares real paths: a data folder reached through a link still matches
    ident = _dir_identity(work)
    held = _open_dir(work, ident)  # POSIX: the folder's files are removed through this, wherever it is moved to
    inner = work / dest_p.name
    made: tuple[int, int] | None = None
    placed = False
    try:
        try:
            if ident is None:
                raise OSError("the snapshot's private folder is not a folder")
            made = _make_new(inner)
            _snapshot_into(src_p, inner)
            if _dir_identity(work) != ident or not _still_made(inner, made):
                # SQLite opens by NAME: a folder or file replaced between their making and that open means the copy went
                # elsewhere, so it is never given the snapshot's name.
                raise OSError("the snapshot's private folder or file was replaced during the copy")
            try:
                _place(inner, dest_p)
            finally:
                # Recorded whatever happened after the link or rename: a name that holds this copy is removed with it on a failure.
                placed = _still_made(dest_p, made)
            if not placed:
                raise OSError("the snapshot's name no longer holds the file this copy made")
        except BaseException as failed:
            left, moved = _undo(work, ident, dest_p if placed else None, made, held)
            if left is None:
                raise
            # the error itself names the whole path for the operator (R794); the log line keeps it masked (R736)
            _LOG.error(
                "a plaintext copy failed (%s) and its unfinished file could not be removed: %s",
                type(failed).__name__,
                _masked_place(left.name, in_data=False),
            )
            if not isinstance(failed, Exception):
                # an interrupt, an exit: passed on as it is, carrying the path, so no caller removes that name again by itself
                with contextlib.suppress(Exception):
                    failed.oo_snapshot_left = left  # type: ignore[attr-defined]
                raise
        else:
            if ident is not None and not _empty_and_remove(work, ident, held):
                # the copy is whole under its name; the empty (or second-name) folder goes at the next sweep
                _LOG.warning("a finished snapshot's private folder could not be removed yet: %s", _masked_place(work.name, in_data=False))
            return dest_p
    finally:
        with _active_lock:
            _active_work.discard(os.path.realpath(work))
        if held is not None:
            with contextlib.suppress(OSError):
                os.close(held)
    # outside the handler: no cause, no context, no driver text
    raise SnapshotFolderMoved(left) if moved else SnapshotLeftOnDisk(left)


def _undo(
    work: Path, ident: tuple[int, int] | None, placed: Path | None, made: tuple[int, int] | None, held: int | None
) -> tuple[Path | None, bool]:
    """After a failure: the name given to the copy (only while it still holds that file, never through a link) and the whole private
    folder go, through the held descriptor where there is one. Returns a path that may still hold an incomplete plaintext copy (or
    ``None``) and whether the folder was moved, so that path no longer holds it. Never raises."""
    if placed is not None and made is not None:
        try:
            st = os.lstat(placed)
            if stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) == made:
                os.unlink(placed)
            else:
                return placed, False
        except FileNotFoundError:
            pass
        except OSError:
            return placed, False
    if ident is None:
        return (work if os.path.lexists(work) else None), False
    if _empty_and_remove(work, ident, held):
        return None, False
    return work, _dir_identity(work) != ident  # moved: the copy is wherever the folder went, so the message says so


def _snapshot_into(src_p: Path, dest_p: Path) -> None:
    if is_encrypted_file(src_p):
        conn = connect(src_p, check_same_thread=False)
        try:
            conn.execute("ATTACH DATABASE ? AS snap KEY ''", (str(dest_p),))
            _export(conn, "snap")
            conn.execute("DETACH DATABASE snap")
        finally:
            conn.close()
        return
    with sqlite_opening():  # R789: the live store, opened outside connect()
        src_conn = sqlite3.connect(str(src_p))
    try:
        dst_conn = sqlite3.connect(str(dest_p))
        try:
            src_conn.backup(dst_conn)  # online backup API: WAL-safe, page-consistent
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def reencrypt_plain_to(src_plain: Path | str, dest: Path | str, key: str) -> Path:
    """Copy a PLAINTEXT database into a new ENCRYPTED file under ``key``
    (sqlcipher_export; the encrypt tool -- the replace-restore path that once shared it was
    removed 2026-06-13)."""
    if not have_driver():  # pragma: no cover - core dependency
        raise DatabaseLockedError("sqlcipher3 driver unavailable")
    from sqlcipher3 import dbapi2 as sqc

    from src.monitoring.secret_scrub import passphrase_bytes

    # The source is plaintext, so no ``_apply_key`` has looked at this key yet: the process is guarded here, as there, and the
    # key goes into the ATTACH statement as text that the driver encodes by itself, so a lone surrogate fails there with the
    # character, its place in the statement and the statement (with the key in it) held. Refused first, with fixed words.
    _guard_the_key()
    passphrase_bytes(key)
    src_p, dest_p = Path(src_plain), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    with sqlite_opening():  # R789: sqlcipher3 opens are not audited
        conn = sqc.connect(str(src_p))  # a plaintext file opens with no key
    try:
        conn.execute(f"ATTACH DATABASE ? AS enc KEY '{_sql_literal_escape(key)}'", (str(dest_p),))
        _match_source_pragmas(conn, "enc")
        _export(conn, "enc")
        conn.execute("DETACH DATABASE enc")
    finally:
        conn.close()
    return dest_p


def copy_at_current_settings(src: Path | str, dest: Path | str, *, should_stop=None) -> Path:
    """Copy ``src`` into a NEW file at the settings a new store is created with today (R702: DB-10's rebuild at new settings).

    The one place a snapshot does NOT keep the source's framing: where :func:`snapshot_preserving` declares the source's own
    ``page_size``/``auto_vacuum`` on the target (``_match_source_pragmas``), this declares :data:`_FRESH_PAGE_SIZE` and
    :data:`_FRESH_AUTO_VACUUM`, in that order (the fresh-file branches of :func:`connect` say why), and keeps the encryption state:
    an encrypted store is copied under the same key, a plaintext one stays plaintext. VACUUM cannot do this: it never changes
    SQLCipher's page size, it cannot change ``page_size`` in WAL mode, and at 16 KiB with ``temp_store=FILE`` it wrote a corrupt
    encrypted store (``maintenance.VACUUM_RAM_FACTOR``). ``sqlcipher_export`` writes straight into the attached file.

    ``should_stop`` (a no-argument callable) interrupts the copy (``sqlcipher_export`` is one statement, aborted within the
    watcher's quarter second); :class:`SnapshotStopped` is raised. The partial file is removed on a stop and on any failure, so a
    name this returns is always a whole copy."""
    src_p, dest_p = Path(src), Path(dest)
    dest_p.unlink(missing_ok=True)
    encrypted = is_encrypted_file(src_p)
    if encrypted is None:
        raise FileNotFoundError(f"{src_p.name} is missing or empty")
    attach_args: tuple[str, ...]
    if encrypted:
        key = get_passphrase()
        if not key:
            raise DatabaseLockedError(f"{src_p.name} is encrypted: cannot copy it while locked")
        conn = connect(src_p, check_same_thread=False)
        # the key is BOUND, never in the statement's text (ATTACH takes an expression for KEY)
        attach, attach_args, size_pragma = "ATTACH DATABASE ? AS rebuilt KEY ?", (str(dest_p), key), "cipher_page_size"
    else:
        from sqlcipher3 import dbapi2 as sqc

        with sqlite_opening():  # R789: sqlcipher3 opens are not audited
            conn = sqc.connect(str(src_p), check_same_thread=False)  # a plaintext file opens with no key
        attach, attach_args, size_pragma = "ATTACH DATABASE ? AS rebuilt KEY ''", (str(dest_p),), "page_size"
    try:
        conn.execute("PRAGMA temp_store = MEMORY")  # a sorter or temp table spilled to disk would be plaintext, whatever the build
        conn.execute(attach, attach_args)
        conn.execute(f"PRAGMA rebuilt.{size_pragma} = {int(_FRESH_PAGE_SIZE)}")
        conn.execute(f"PRAGMA rebuilt.auto_vacuum = {int(_FRESH_AUTO_VACUUM)}")
        if should_stop is None:
            _export(conn, "rebuilt")
        else:
            if should_stop():  # a stop already given: the watcher looks only every 0.25 s, and a small copy is done by then
                raise SnapshotStopped("the copy was stopped")
            with _interrupt_when(conn, should_stop) as fired:
                try:
                    _export(conn, "rebuilt")
                except Exception:
                    if fired[0]:
                        raise SnapshotStopped("the copy was stopped") from None
                    raise
        conn.execute("DETACH DATABASE rebuilt")
    except BaseException:
        with contextlib.suppress(Exception):
            conn.close()
        for side in ("", "-journal", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                Path(str(dest_p) + side).unlink()  # never leave a partial copy to be mistaken for one
        raise
    conn.close()
    return dest_p


def _note_snapshot_checkpoint(row, seconds: float) -> None:
    """Put the snapshot's TRUNCATE in the storage-events journal (a lazy import: this module sits under everything else, and the
    journal must never be the reason a snapshot fails). Never raises."""
    try:
        from src.monitoring import storage_events

        storage_events.note_checkpoint("snapshot", truncate=row, seconds=seconds)
    except Exception:  # noqa: BLE001 - best effort by contract
        pass


def _quiesced_file_copy(src_p: Path, dest_p: Path) -> bool:
    """Try to snapshot an encrypted store by COPYING ITS BYTES. Returns whether it ran.

    IMPORT-SPEED FIX (field report 2026-07-30, "a week for 130 GB"). The ordinary
    snapshot path re-encrypts the whole corpus row by row through the SQLCipher codec
    (``sqlcipher_export``); a restore takes TWO whole-corpus snapshots (the merge's
    working copy and the pre-restore safety net), so an N-backup import queue pays 2N
    of them over a corpus that grows with every item. A byte copy does ZERO codec work,
    is a kernel-side ``copy_file_range``/``sendfile`` on Linux, and is BIT-IDENTICAL --
    which also makes it strictly safer on the property ``_match_source_pragmas`` exists
    to protect (it cannot get ``page_size``/``auto_vacuum`` wrong, because it does not
    re-create anything). Measured here on a 0.52 GB encrypted store: 9.6 s for
    ``sqlcipher_export`` vs 2.3 s for the copy.

    THE PRECONDITION IS THE WHOLE POINT: copying a live WAL-mode database file while a
    writer is active yields a TORN copy. So this runs only when both halves of a proof
    hold, and REFUSES (returning False, caller falls back to the codec path) otherwise:

      1. the process-wide single-writer gate is HELD for the whole checkpoint+copy, so
         no ORM or raw-SQL write in this process can land mid-copy, and
      2. ``wal_checkpoint(TRUNCATE)`` reports it actually drained (busy == 0) AND the
         ``-wal`` file is genuinely 0 bytes afterwards -- i.e. every committed page is
         in the main file and nothing is left only in the log.

    A busy checkpoint means some reader still holds a snapshot the WAL must serve; that
    is a legitimate state, not an error, so it degrades to the slow-but-always-correct
    path rather than copying something it cannot prove complete. Never a silent torn
    copy: the failure direction is "slower", never "wrong".

    ...WHICH IS WHY THE GATE IS CHECKED, NOT ASSUMED. ``write_lock()`` is a documented
    NO-OP when ``OO_WRITE_GATE=0``, so on that escape hatch precondition 1 would be
    silently false and this would copy a file nothing was holding still -- a guard named
    for a safety property that does not enforce it. With the gate off there is no way to
    prove the source is quiescent, so the honest answer is to refuse and let the codec
    path (which is consistent by construction, being a read transaction) do the work."""
    from src.database.writer import gate_enabled, write_lock

    if not gate_enabled():
        return False
    with write_lock():
        conn = connect(src_p, check_same_thread=False)
        try:
            began = time.monotonic()
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            _note_snapshot_checkpoint(row, time.monotonic() - began)
        finally:
            conn.close()
        if not row or int(row[0]) != 0:
            return False  # busy: a reader still needs the log — fall back, never guess
        wal = src_p.with_name(src_p.name + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            return False
        if os.name == "nt":
            shutil.copyfile(src_p, dest_p)
        else:
            _copy_from_held(src_p, dest_p)
        # A snapshot is a lone file: any -wal/-shm the destination inherited from a
        # previous life would be read as ITS log and corrupt the read.
        for suffix in ("-wal", "-shm"):
            dest_p.with_name(dest_p.name + suffix).unlink(missing_ok=True)
    # Prove the copy opens under the same key before reporting success (page-1 HMAC;
    # microseconds, not proportional to corpus size).
    connect(dest_p, check_same_thread=False).close()
    return True


class StoreCopyRefused(OSError):
    """A byte copy of the store was refused before or during the copy; the reason is the message, the partial is gone."""


def _copy_from_held(
    src_p: Path, dest_p: Path, *, chunk: int = 8 * 1024 * 1024, use_sendfile: bool = True, digest: object = None
) -> None:
    """Byte-copy the live store from the descriptor kept for it (R789): ``shutil.copyfile`` opened and CLOSED the store,
    and on POSIX that close dropped every lock this process held on it, so after every restore and stream backup another
    process could take or write the store under the running app.

    Called under the write gate with the checkpoint drained and the ``-wal`` empty (the caller's preconditions, unchanged).
    The kept descriptor must be the file now at ``src_p`` (device and inode, the name not followed if it is a link), or the
    copy is refused: a stale or replaced file is never copied. The size is read once from the descriptor and exactly that
    many bytes are copied; a short read, or a size that changes during the copy, fails it and removes the partial."""
    try:
        os.stat(src_p, follow_symlinks=False)
    except OSError as exc:
        raise StoreCopyRefused(f"the store could not be found at its path ({type(exc).__name__})") from None
    with store_reader(src_p) as fd:  # in use for the whole copy: no other read of ours closes it meanwhile
        _copy_fd(src_p, fd, dest_p, chunk=chunk, use_sendfile=use_sendfile, digest=digest)


def _copy_chunk(fd: int, out: int, done: int, want: int, size: int, state: dict) -> int:
    """One chunk of :func:`_copy_fd` at offset ``done``; returns the bytes written (0 when ``sendfile`` just gave way to the
    pread loop). A loop body of its own, so the copy loop's back-edge stays inside the ``try`` around it (R163)."""
    sendfile = state["sendfile"]
    if sendfile is not None:
        try:
            n = sendfile(out, fd, done, want)  # an explicit offset: the shared position is not moved
        except OSError:
            state["sendfile"] = None  # not supported for this pair of files here: the pread loop does it
            return 0
        if n == 0:
            raise StoreCopyRefused(f"the store ended after {done} of {size} bytes during the copy")
        return n
    data = read_at(fd, want, done)
    if not data:
        raise StoreCopyRefused(f"the store ended after {done} of {size} bytes during the copy")
    digest = state.get("digest")
    if digest is not None:
        digest.update(data)  # the source's bytes as read, in order: the pread loop only (sendfile never surfaces them)
    view = memoryview(data)
    while view:
        view = view[os.write(out, view) :]
    return len(data)


class _DigestBeside:
    """Feed a hash on its own thread while the copy loop goes on reading and writing (R830: the safety net's sha256 is
    taken while copying, and on one thread it nearly doubled the copy's time on ext4). ``hashlib`` releases the GIL
    for large updates, as ``pread``/``write`` do, so the two overlap. Chunks are handed over in order through a
    bounded queue (at most ``depth`` chunks held), so the hash is of exactly the bytes read, in the order written.
    :meth:`close` waits for the hash to take every chunk and raises :class:`StoreCopyRefused` when the hash failed on its
    thread (fixed words: the hash's own error is never carried)."""

    def __init__(self, digest: object, depth: int = 4) -> None:
        import queue

        self._digest = digest
        self._q: queue.Queue = queue.Queue(maxsize=depth)
        self._failed = False
        self._thread = threading.Thread(target=self._run, name="oo-copy-digest", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:  # the guard-clause form (R163)
            data = self._q.get()
            if data is None:
                return
            if not self._failed:
                try:
                    self._digest.update(data)  # type: ignore[attr-defined]
                except BaseException:  # noqa: BLE001 - said on the copying thread by update()/close()
                    self._failed = True

    def _raise_if_failed(self) -> None:
        if self._failed:
            raise StoreCopyRefused("the sha256 of the copy could not be taken; the copy was discarded")

    def update(self, data: bytes) -> None:
        self._raise_if_failed()
        self._q.put(data)

    def close(self) -> None:
        self._q.put(None)
        self._thread.join()
        self._raise_if_failed()


def _copy_fd(src_p: Path, fd: int, dest_p: Path, *, chunk: int, use_sendfile: bool, digest: object = None) -> None:
    def _same_file_at_path() -> bool:
        try:
            now = os.stat(src_p, follow_symlinks=False)
        except OSError:
            return False
        held = os.fstat(fd)
        return (held.st_dev, held.st_ino) == (now.st_dev, now.st_ino)

    if not _same_file_at_path():
        raise StoreCopyRefused("the store at its path is not the file this process holds; nothing was copied")
    size = os.fstat(fd).st_size
    # A new file only (the caller removed any old one), never through a link: 0o666 less the umask, as shutil.copyfile made it.
    out = os.open(dest_p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o666)
    try:
        try:
            beside = _DigestBeside(digest) if digest is not None else None
            state = {
                "sendfile": getattr(os, "sendfile", None) if use_sendfile and digest is None else None,
                "digest": beside,
            }
            done = 0
            try:
                while True:  # the guard-clause form: the back-edge stays inside the try (R163)
                    if done >= size:
                        break
                    done += _copy_chunk(fd, out, done, min(chunk, size - done), size, state)
            finally:
                if beside is not None:
                    beside.close()  # every chunk hashed before the copy is reported done (or its failure raised)
            if os.fstat(fd).st_size != size:
                raise StoreCopyRefused("the store changed size during the copy; the copy was discarded")
            if not _same_file_at_path():
                raise StoreCopyRefused("the store at its path was replaced during the copy; the copy was discarded")
        finally:
            os.close(out)  # the destination, a new private file: closing it drops no lock anyone holds
    except BaseException:
        dest_p.unlink(missing_ok=True)
        raise


def _sha256_of_file(path: Path, *, chunk: int = 8 * 1024 * 1024, should_stop=None) -> tuple[int, str]:
    """``(bytes read, sha256 hex)`` of a file this process just wrote, read back from disk, never through a link.

    ``should_stop`` (optional, checked between chunks) ends the read early with :class:`StoreCopyRefused`."""
    h = hashlib.sha256()
    n = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        while True:  # the guard-clause form: the back-edge stays inside the try (R163)
            if should_stop is not None and should_stop():
                raise StoreCopyRefused("the read-back of the safety copy was stopped before it finished")
            data = os.read(fd, chunk)
            if not data:
                break
            h.update(data)
            n += len(data)
    finally:
        os.close(fd)
    return n, h.hexdigest()


def verified_store_copy(src_p: Path, dest_p: Path, *, read_back: bool = True) -> dict | None:
    """A byte copy of the encrypted store, VERIFIED WHOLE before it is trusted: R827 R5/R6(a), R830.

    The import's safety net, the copy that is never written to. Same proof as
    :func:`_quiesced_file_copy` (the write gate held, the checkpoint drained, an empty ``-wal``) and, under
    that SAME gate hold, the source's sha256 is taken from the bytes as they are copied. The copy is then
    flushed to disk (fsync), its size compared with the source's, and it is opened under the same key: the
    cheap checks. With ``read_back`` (the default) the copy is also read back from disk and hashed here, and
    kept only when the hash equals the source's. A mismatch removes it and raises :class:`StoreCopyRefused`;
    nothing is written to the source either way.

    ``read_back=False`` is for a caller that runs :func:`store_copy_reads_back` itself, off the critical path,
    and refuses before using the copy for anything that cannot be undone (R830: the import runs it beside the
    merge and refuses before the swap). The returned dict then says ``"read_back": False`` -- the copy is not
    yet verified whole, and must not be reported as verified until that check has passed.

    Returns ``{"bytes": n, "sha256": hex, "read_back": bool}``, or None when the store is plaintext or the proof
    cannot be made (the caller then takes its copies the way it did before)."""
    from src.database.writer import gate_enabled, write_lock

    src_p, dest_p = Path(src_p), Path(dest_p)
    if not is_encrypted_file(src_p) or not gate_enabled():
        return None
    if not get_passphrase():
        raise DatabaseLockedError(f"{src_p.name} is encrypted: cannot snapshot while locked")
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    with write_lock():
        conn = connect(src_p, check_same_thread=False)
        try:
            began = time.monotonic()
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            _note_snapshot_checkpoint(row, time.monotonic() - began)
        finally:
            conn.close()
        if not row or int(row[0]) != 0:
            return None
        wal = src_p.with_name(src_p.name + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            return None
        source = hashlib.sha256()
        _copy_from_held(src_p, dest_p, use_sendfile=False, digest=source)
        for suffix in ("-wal", "-shm"):
            dest_p.with_name(dest_p.name + suffix).unlink(missing_ok=True)
        try:
            with store_reader(src_p) as fd:
                src_bytes = os.fstat(fd).st_size
            _fsync_file(dest_p)  # on disk before anything relies on it (R830)
            _fsync_dir(dest_p.parent)  # and its name too, so a power cut after the swap cannot lose the net's entry
            copy_bytes = os.stat(dest_p, follow_symlinks=False).st_size
            if copy_bytes != src_bytes:
                raise StoreCopyRefused(
                    "the safety copy does not match the corpus it was copied from (size); it was removed"
                )
            if read_back:
                store_copy_reads_back(dest_p, {"bytes": src_bytes, "sha256": source.hexdigest()})
        except BaseException:
            dest_p.unlink(missing_ok=True)
            raise
    try:
        connect(dest_p, check_same_thread=False).close()  # opens under the same key (page-1 HMAC)
    except BaseException:
        dest_p.unlink(missing_ok=True)
        raise
    return {"bytes": copy_bytes, "sha256": source.hexdigest(), "read_back": bool(read_back)}


def _fsync_file(path: Path) -> None:
    """Flush a file this process just wrote to the disk, opened without following a link."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Flush a directory's entries (POSIX); where a directory cannot be opened for that (Windows), nothing is done."""
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def store_copy_reads_back(dest_p: Path, facts: dict, *, should_stop=None) -> None:
    """Read a copy made by :func:`verified_store_copy` back from disk and compare it with the source's size and
    sha256 (``facts``, as that call returned them). Raises :class:`StoreCopyRefused` when they differ, or when
    ``should_stop`` ends the read first; never removes or changes the copy itself (the caller decides)."""
    n, h = _sha256_of_file(Path(dest_p), should_stop=should_stop)
    if n != int(facts["bytes"]) or h != str(facts["sha256"]):
        raise StoreCopyRefused("the safety copy does not match the corpus it was copied from (size or sha256)")


def clone_file(src_p: Path, dest_p: Path, *, chunk: int = 64 * 1024 * 1024) -> None:
    """Copy a file this process owns (never the live store) to a NEW file, sharing extents where the
    filesystem can (``copy_file_range`` reflinks on Btrfs and XFS; elsewhere it is an in-kernel copy).
    A short copy removes the partial and raises :class:`StoreCopyRefused`."""
    src_p, dest_p = Path(src_p), Path(dest_p)
    dest_p.unlink(missing_ok=True)
    flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(src_p, os.O_RDONLY | getattr(os, "O_BINARY", 0) | flags)
    try:
        size = os.fstat(fd).st_size
        out = os.open(dest_p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | flags, 0o666)
        try:
            try:
                cfr = getattr(os, "copy_file_range", None)
                done = 0
                while True:  # the guard-clause form: the back-edge stays inside the try (R163)
                    if done >= size:
                        break
                    want = min(chunk, size - done)
                    n = 0
                    if cfr is not None:
                        try:
                            n = cfr(fd, out, want, done, done)
                        except OSError:
                            cfr = None
                    if cfr is None:
                        data = read_at(fd, want, done)
                        n = _write_all(out, data)
                    if n == 0:
                        raise StoreCopyRefused(f"the copy ended after {done} of {size} bytes")
                    done += n
            finally:
                os.close(out)
        except BaseException:
            dest_p.unlink(missing_ok=True)
            raise
    finally:
        os.close(fd)


def _write_all(out: int, data: bytes) -> int:
    """Write all of ``data`` to ``out``; returns its length. Its own scope, outside the caller's ``try`` (R163)."""
    view = memoryview(data)
    while view:
        view = view[os.write(out, view) :]
    return len(data)


def snapshot_open_connection(conn, dest: Path | str) -> Path:
    """Consistent snapshot of the database ``conn`` is ALREADY open on, taken through that connection and KEEPING
    its encryption state (an encrypted corpus stays ciphertext under the same key).

    :func:`snapshot_preserving` opens the file itself, which a caller holding the file EXCLUSIVELY (the country-form
    migration, ``PRAGMA locking_mode=EXCLUSIVE``) cannot let it do: a second connection is refused, which is the point of
    the lock. This takes the copy through the connection that holds it."""
    dest_p = Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    try:
        if _is_sqlcipher_conn(conn):
            key = get_passphrase()
            if not key:
                raise DatabaseLockedError("the store is encrypted: cannot snapshot without its passphrase")
            # The key is BOUND (ATTACH ... KEY takes an expression), so no passphrase is ever spliced into the statement text.
            conn.execute("ATTACH DATABASE ? AS snap KEY ?", (str(dest_p), key))
            _match_source_pragmas(conn, "snap")
            _export(conn, "snap")
            conn.execute("DETACH DATABASE snap")
        else:
            dst = sqlite3.connect(str(dest_p))
            try:
                conn.backup(dst)
            finally:
                dst.close()
    except BaseException:
        dest_p.unlink(missing_ok=True)  # never leave a partial copy to be mistaken for one
        raise
    return dest_p


class SnapshotStopped(Exception):
    """A snapshot was interrupted because its caller's ``should_stop`` turned true. The partial
    copy has been removed."""


@contextlib.contextmanager
def _interrupt_when(conn, should_stop):
    """Watch ``should_stop`` from a daemon thread and call ``conn.interrupt()`` the moment it turns
    true (``sqlite3_interrupt`` is thread-safe and aborts a running statement, which is what
    ``sqlcipher_export`` is). Yields a one-element list that holds True once it fired."""
    fired = [False]
    done = threading.Event()

    def watch() -> None:
        while not done.wait(0.25):
            try:
                if should_stop():
                    fired[0] = True
                    conn.interrupt()
                    return
            except Exception:  # noqa: BLE001 - a broken callback must never kill the copy
                return

    t = threading.Thread(target=watch, name="oo-snapshot-stop-watch", daemon=True)
    t.start()
    try:
        yield fired
    finally:
        done.set()
        t.join(1.0)


def snapshot_preserving(
    src: Path | str,
    dest: Path | str,
    *,
    allow_file_copy: bool = False,
    should_stop=None,
) -> Path:
    """Consistent snapshot KEEPING the source's encryption state — working
    copies and pre-restore safety nets must never silently change the corpus's
    at-rest protection (an encrypted corpus stays ciphertext on disk).

    ``allow_file_copy`` opts into the byte-copy fast path (see
    :func:`_quiesced_file_copy` for the proof it demands and the failure direction).
    It is OPT-IN rather than automatic because the fast path holds the single-writer
    gate for the whole copy: that is free during an import (which owns the machine and
    has collection paused) and rude during ordinary operation, so the caller — who
    knows which it is — decides.

    ``should_stop`` (optional, a no-argument callable) lets the caller cancel a long copy:
    an ENCRYPTED copy is one statement and is interrupted within about a second (the partial
    file is removed and :class:`SnapshotStopped` raised). A PLAINTEXT copy uses SQLite's backup
    API in one step, which ``interrupt()`` cannot abort (measured) and which must stay one
    step: stepping it in chunks restarts it whenever another connection commits. So a stop
    takes effect when a plaintext copy ends, and the caller polls it then."""
    src_p, dest_p = Path(src), Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.unlink(missing_ok=True)
    if not is_encrypted_file(src_p):
        return snapshot_to_plaintext(src_p, dest_p)
    key = get_passphrase()
    if not key:
        raise DatabaseLockedError(f"{src_p.name} is encrypted: cannot snapshot while locked")
    if allow_file_copy:
        try:
            if _quiesced_file_copy(src_p, dest_p):
                return dest_p
        except Exception as exc:  # noqa: BLE001 - the codec path below is always correct
            # Imported here: this module must import without it (the env-take child in test_env_passphrase_taken).
            from src.monitoring.secret_scrub import log_failure

            log_failure(_LOG, "the quiesced file-copy snapshot failed; falling back to sqlcipher_export", exc, key, level=logging.WARNING)
        dest_p.unlink(missing_ok=True)  # never let a partial copy be mistaken for one
    conn = connect(src_p, check_same_thread=False)
    try:
        conn.execute(f"ATTACH DATABASE ? AS snap KEY '{_sql_literal_escape(key)}'", (str(dest_p),))
        _match_source_pragmas(conn, "snap")
        if should_stop is None:
            _export(conn, "snap")
        else:
            with _interrupt_when(conn, should_stop) as fired:
                try:
                    _export(conn, "snap")
                except Exception:
                    if fired[0]:
                        raise SnapshotStopped("the snapshot was stopped") from None
                    raise
        conn.execute("DETACH DATABASE snap")
    except SnapshotStopped:
        conn.close()
        dest_p.unlink(missing_ok=True)  # never leave a partial copy to be mistaken for one
        raise
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return dest_p
