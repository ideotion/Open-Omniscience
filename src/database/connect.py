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
import logging
import os
import shutil
import sqlite3
import stat
import threading
import time
from pathlib import Path, PurePath, PureWindowsPath

from src.database import open_stats

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
    try:
        with store_reader(p) as fd:
            return os.pread(fd, 16, 0) != _SQLITE_MAGIC
    except OSError:
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
_hdr_lock = threading.Lock()
_hdr_pinned: set[str] = set()  # realpaths of stores kept open while reachable (:func:`pin_store`)
_GROUP_SUFFIXES = ("-wal", "-shm", "-journal")


@contextlib.contextmanager
def sqlite_opening():
    """Around every SQLite open of a file this process may also read from Python (R789): while one is in flight, no read of
    ours closes a descriptor, so a lock the new connection takes cannot be dropped by a close that raced its open."""
    global _hdr_opening
    counted = False
    try:
        with _hdr_lock:
            _hdr_opening += 1
            counted = True
        yield
    finally:
        with _hdr_lock:
            if counted:
                _hdr_opening -= 1
        _sweep()  # what reads during the open parked; the new connection's own files stay (they are foreign now)


def pin_store(path: Path | str) -> None:
    """Name a store whose descriptor of ours stays open for as long as the name leads to the same file (R789, the
    coordinator's fallback for the library): a close that could race an open of the library is then never made, whatever
    opener it is. The session registers the library file at import."""
    with contextlib.suppress(OSError), _hdr_lock:
        _hdr_pinned.add(os.path.realpath(path))


def _not_regular(mode: int) -> OSError:
    if stat.S_ISDIR(mode):
        return IsADirectoryError(errno.EISDIR, "is a directory")
    return OSError(errno.EINVAL, "not a regular file")


def _acquire(p: Path) -> tuple[tuple[int, int], int]:
    """A read-only descriptor on the regular file at ``p`` and its (device, inode), counted in use until :func:`_release`.
    Raises ``OSError`` as ``os.open`` does; ``IsADirectoryError`` for a directory, ``OSError`` for another non-regular file.
    The stat and the open run OUTSIDE ``_hdr_lock`` (a hung mount stalls this read, not every connect); a descriptor not
    yet recorded is foreign to other reads, which then keep theirs: the safe direction."""
    st = os.stat(p)
    if not stat.S_ISREG(st.st_mode):
        raise _not_regular(st.st_mode)  # refused before any open: no FIFO wait, no terminal, no device side effect
    key = (st.st_dev, st.st_ino)
    with _hdr_lock:
        if key in _hdr_fds:
            _hdr_names[key] = os.fspath(p)
            _hdr_uses[key] = _hdr_uses.get(key, 0) + 1
            return key, _hdr_fds[key][0]
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
    fd = os.open(p, flags)
    got = os.fstat(fd)  # should this raise, the descriptor stays open: closing one we cannot place could drop a lock
    if not stat.S_ISREG(got.st_mode):
        os.close(fd)  # the name now leads to a non-regular file, which no SQLite connection holds a lock on
        raise _not_regular(got.st_mode)
    key = (got.st_dev, got.st_ino)  # what was opened, even if the name moved since the stat
    with _hdr_lock:
        if key in _hdr_fds:
            _hdr_fds[key].append(fd)  # never closed here: another of ours is open on the file
        else:
            _hdr_fds[key] = [fd]
        _hdr_names[key] = os.fspath(p)
        _hdr_uses[key] = _hdr_uses.get(key, 0) + 1
        return key, _hdr_fds[key][0]


def _release(key: tuple[int, int]) -> None:
    with _hdr_lock:
        _hdr_uses[key] -= 1
    _sweep()


def _group_of(name: str) -> tuple[str, set[tuple[int, int]]]:
    """The realpath of the store ``name`` belongs to, and the (device, inode) of that store and its logs as they are now."""
    base = name
    for suf in _GROUP_SUFFIXES:
        if name.endswith(suf):
            base = name[: -len(suf)]
            break
    keys = set()
    for n in (base, *(base + s for s in _GROUP_SUFFIXES)):
        try:
            st = os.stat(n)
        except OSError:
            continue
        keys.add((st.st_dev, st.st_ino))
    try:
        real = os.path.realpath(base)
    except (OSError, ValueError):
        real = base
    return real, keys


def _foreign_fd_keys() -> set[tuple[int, int]] | None:
    """The (device, inode) of every descriptor of this process that is not one of ours; None if they cannot be listed.
    Lists ``/proc/self/fd`` or ``/dev/fd`` and ``fstat``s each: nothing is opened to find out."""
    ours = {fd for fds in _hdr_fds.values() for fd in fds}
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
            except OSError:
                continue
            keys.add((st.st_dev, st.st_ino))
        return keys
    return None


def _idle_names_locked() -> dict[tuple[int, int], str]:
    return {k: _hdr_names.get(k, "") for k in _hdr_fds if not _hdr_uses.get(k)}


def _sweep() -> None:
    """Close every descriptor of ours that no reader uses and that closing cannot hurt (see the block comment above).

    Two phases: the groups are resolved by name with no lock held (a stat may wait on a slow mount); then, under the lock,
    nothing may be opening, the process's descriptors are listed, and the close decision and the close are made together."""
    with _hdr_lock:
        if _hdr_opening:
            return
        idle = _idle_names_locked()
    if not idle:
        return
    groups = {k: _group_of(name) for k, name in idle.items()}
    with _hdr_lock:
        _close_free_locked(groups)


def _close_free_locked(groups: dict[tuple[int, int], tuple[str, set[tuple[int, int]]]]) -> None:
    if _hdr_opening or not groups:
        return
    foreign = _foreign_fd_keys()
    if foreign is None:
        return  # cannot tell: keep them all (a kept descriptor drops nothing)
    for key, (real, group) in groups.items():
        if key not in _hdr_fds or _hdr_uses.get(key):
            continue
        reachable = key in group  # the name still leads to this file
        if reachable and real in _hdr_pinned:
            continue  # the library: kept while it is the library (the coordinator's fallback)
        held = (group if reachable else set()) | {key}  # a replaced file is judged alone: its name now leads elsewhere
        if held & foreign:
            continue
        if any(_hdr_uses.get(k) for k in held if k != key):
            continue  # a reader of ours on the same group: the group's descriptors stay with it
        for fd in _hdr_fds.pop(key):
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
    see :func:`_connect` for why ``PRAGMA query_only`` is not that."""
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
    from src.database.fts_norm import register

    register(conn)
    return conn


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
    return dest_p


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


def _copy_from_held(src_p: Path, dest_p: Path, *, chunk: int = 8 * 1024 * 1024, use_sendfile: bool = True) -> None:
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
        _copy_fd(src_p, fd, dest_p, chunk=chunk, use_sendfile=use_sendfile)


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
    view = memoryview(data)
    while view:
        view = view[os.write(out, view) :]
    return len(data)


def _copy_fd(src_p: Path, fd: int, dest_p: Path, *, chunk: int, use_sendfile: bool) -> None:
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
            state = {"sendfile": getattr(os, "sendfile", None) if use_sendfile else None}
            done = 0
            while True:  # the guard-clause form: the back-edge stays inside the try (R163)
                if done >= size:
                    break
                done += _copy_chunk(fd, out, done, min(chunk, size - done), size, state)
            if os.fstat(fd).st_size != size:
                raise StoreCopyRefused("the store changed size during the copy; the copy was discarded")
            if not _same_file_at_path():
                raise StoreCopyRefused("the store at its path was replaced during the copy; the copy was discarded")
        finally:
            os.close(out)  # the destination, a new private file: closing it drops no lock anyone holds
    except BaseException:
        dest_p.unlink(missing_ok=True)
        raise


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
