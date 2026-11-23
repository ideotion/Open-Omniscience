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
import contextvars
import errno
import itertools
import logging
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

from src.monitoring.secret_scrub import log_failure

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
# The cache, the sidecar that holds the salt its key is stretched with (``columnar._KDF_SIDECAR_SUFFIX``), the log the engine
# leaves beside the cache after an unclean end (ciphertext under the same key, so with the sidecar gone it is noise, but it is
# the store's own file) and the gate's probe.
_DUCK_FILES = ("analytics.duckdb", "analytics.duckdb.kdf", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb")
_KEY_FILES = ("custody_ed25519.pem", "custody_ml_dsa_65.key")

_LIMIT_NOTE = (
    "The guarantee here is crypto-erase: the SQLCipher salt is destroyed, so the "
    "encrypted corpus is permanently unrecoverable regardless of storage medium. A "
    "byte-overwrite pass is defence-in-depth only — it does NOT guarantee "
    "unrecoverability on SSD/flash or copy-on-write filesystems (wear-levelling / "
    "snapshots may retain old blocks). For belt-and-braces on a plaintext store, use "
    "full-disk encryption (LUKS/Qubes/Tails) and destroy that key too."
)


# R792: the note when another program had, or may have had, the database open -- the clean guarantee above is not claimed.
_LIMIT_NOTE_NOT_CLEAN = (
    "The salt was destroyed in every file this erase reached, but another program that had the database open may have "
    "written it back into files it still held; if so, the encrypted corpus may still be recoverable with the passphrase. "
    "A byte-overwrite pass is defence-in-depth only — it does NOT guarantee unrecoverability on SSD/flash or copy-on-write "
    "filesystems (wear-levelling / snapshots may retain old blocks)."
)


# R798: the note when a walk could not list a folder it was to erase -- the files in it were never checked.
_UNLISTED_SENTENCE = (
    "The erase could not list some of the folders it was to erase, so it could not check the files in them: the erase may be "
    "incomplete."
)
_LIMIT_NOTE_UNLISTED = (
    _UNLISTED_SENTENCE + " A byte-overwrite pass is defence-in-depth only — it does NOT guarantee unrecoverability on "
    "SSD/flash or copy-on-write filesystems (wear-levelling / snapshots may retain old blocks)."
)


# R802 (5): the note when the data folder the erase removed is there again when the erase ends -- something wrote into it after.
_FOLDER_BACK_SENTENCE = (
    "The data folder existed again when the erase ended, although the erase had removed it: something recreated it afterwards, "
    "so the erase may be incomplete."
)
_NOT_REMOVED_SENTENCE = (
    "The data folder itself could not be removed, so something may be left in it: check it and remove it by hand."
)
_DEFENCE_TAIL = (
    " A byte-overwrite pass is defence-in-depth only — it does NOT guarantee unrecoverability on "
    "SSD/flash or copy-on-write filesystems (wear-levelling / snapshots may retain old blocks)."
)


def settle_removed(report: dict) -> bool:
    """R802 (5): measure ``removed`` again, AFTER the erase's last log line, and say so truthfully. A data folder the erase removed whole
    that is there again makes ``removed`` False, sets ``folder_back`` and puts the "may be incomplete" sentence first in ``limit``.
    Logs nothing (a log line after the measure is what this measure is for). Returns ``removed``. Never raises."""
    try:
        if report.get("scope") != "data-folder" or not report.get("data_dir"):
            return bool(report.get("removed"))
        if report.get("folder_kept_foreign"):
            # R806: a folder kept on purpose for its keys is said as kept, never as "could not be removed"; anything else at its top
            # now (a removal that failed, or something written there after) is said as not removed, so "kept" never hides it.
            base = Path(report["data_dir"])
            if not _present(base):
                report["folder_kept_foreign"] = False  # gone since (the operator removed it): nothing is kept any more
                report["removed"] = True
                return True
            if _kind(base / "keys") == "absent":
                report["folder_kept_foreign"] = False  # its keys folder is gone since: not kept for it any more
                report["kept_items"] = 0
            failed: list[OSError] = []
            rest = sorted(e.name for e in _listing(base, failed.append) if e.name != "keys")
            if failed:
                rest = rest or ["?"]  # could not be listed: never read as "only keys is left"
            if rest:
                report["not_removed"] = sorted({*(report.get("not_removed") or []), *rest})
                limit = report.get("limit")
                if not isinstance(limit, str):
                    report["limit"] = _NOT_REMOVED_SENTENCE + _DEFENCE_TAIL
                elif not limit.startswith(_NOT_REMOVED_SENTENCE):
                    report["limit"] = _NOT_REMOVED_SENTENCE + " " + limit
            report["removed"] = False
            return False
        removed_before = bool(report.get("removed")) or bool(report.get("removed_at_rmtree"))
        removed = not _present(Path(report["data_dir"]))
        report["removed"] = removed
        if not removed and not removed_before:
            # The erase never removed it (a link as the data folder, an entry it could not delete): said as that, never "came back".
            limit = report.get("limit")
            if not isinstance(limit, str) or limit == _LIMIT_NOTE:
                report["limit"] = _NOT_REMOVED_SENTENCE + _DEFENCE_TAIL
            elif not limit.startswith(_NOT_REMOVED_SENTENCE):
                report["limit"] = _NOT_REMOVED_SENTENCE + " " + limit
        elif not removed:
            report["folder_back"] = True
            limit = report.get("limit")
            if not isinstance(limit, str) or limit == _LIMIT_NOTE:
                report["limit"] = _FOLDER_BACK_SENTENCE + _DEFENCE_TAIL
            elif not limit.startswith(_FOLDER_BACK_SENTENCE):
                report["limit"] = _FOLDER_BACK_SENTENCE + " " + limit
        return removed
    except Exception:  # noqa: BLE001 - an erase result is never lost to its own bookkeeping
        report["removed"] = False
        return False


def _latch(base: Path) -> None:
    """R802 (2): from here to the end of the process nothing in the app writes into ``base`` or makes it again (``src.paths.latch_erased``),
    set while the error journal's lock is held so a record being written lets its file and lock file go first."""
    try:
        from src.monitoring.errorlog import latch_for_erase

        latch_for_erase(base)
    except Exception:  # noqa: BLE001 - the latch is set whatever the journal could do
        from src.paths import latch_erased

        latch_erased(base)


def _latch_outside(paths: dict, base: Path) -> None:
    """R802: the stores an override put outside ``base`` (``DATABASE_URL``'s main file, ``OO_COLUMNAR_DIR``'s columnar files), each
    latched by its exact file and side files, so nothing in this process makes them again; their folder is never latched whole."""
    try:
        from src.paths import erased_folder_of, latch_erased

        files: list[Path] = []
        main = paths.get("main_db")
        if isinstance(main, Path):
            files += [main, *(Path(str(main) + s) for s in ("-wal", "-shm", "-journal"))]
        store = paths.get("store_dir")
        if isinstance(store, Path):
            files += [store / n for n in _DUCK_FILES]
        for f in files:
            if not erased_folder_of(f):
                latch_erased(f)
    except Exception:  # noqa: BLE001 - never blocks the erase; the folder's own latch is already set
        _LOG.warning("CRYPTO-ERASE: could not latch a store outside the data folder")


#: The data folder of the erase running in this context, so the log lines of the helpers it calls are masked against it too.
_ERASE_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar("_ERASE_ROOT", default=None)


def _masked(paths: list[str], root: Path | None = None) -> list[str]:
    """``paths`` for a log line (R734/R736): each as its role (``<data>/.../name``, ``<home>/.../name``, ``.../name``), and the
    whole list withheld when the masking itself fails, never written as given. ``root`` is the data folder of the erase: given,
    the masking never asks ``src.paths.data_dir``, which would make again the folder the erase has just removed."""
    try:
        from src.monitoring.path_tokens import tokenise_paths

        root = root if root is not None else _ERASE_ROOT.get()
        data_root = None if root is None else str(root)
        return [tokenise_paths(p, data_root=data_root) for p in paths]
    except Exception:  # noqa: BLE001 - a log line never carries a raw path
        return ["(path withheld)"] * len(paths)


def _overwrite(path: Path, *, head_bytes: int | None = None, zeros: bool = False) -> bool:
    """Overwrite ``path`` in place with random data, then fsync. When ``head_bytes``
    is given only that prefix is overwritten (the crypto-erase salt-page case);
    otherwise the whole file is overwritten in bounded chunks (small files only —
    the big encrypted corpus is handled by its header, never rewritten). Returns
    whether every byte was actually written and fsynced -- callers must NOT report
    a destructive overwrite as done just because no exception reached them; a
    silent False here with the outcome still reported as success is exactly the
    false-confidence bug audit OO-02 exists to eliminate.

    Writes ONLY a regular file at ``path`` itself: a symlink is never written through (its target may be anywhere,
    outside the data dir included) and a FIFO, socket or device is never opened to write (it would block or reach
    hardware); either is reported as not overwritten. ``O_NOFOLLOW`` where the platform has it, so a name swapped for
    a link between a check and the open is refused too; elsewhere the link check right before the open."""
    try:
        if path.is_symlink():
            raise OSError("a link is never written through")
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_BINARY", 0))
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError("not a regular file")
        except OSError:
            os.close(fd)
            raise
        size = st.st_size
        limit = size if head_bytes is None else min(size, head_bytes)
        with os.fdopen(fd, "r+b", buffering=0) as f:
            written = 0
            # ``while True: if not <wanted>: break``, not ``while <wanted>:``: the back-edge of the second sits outside the ``with``'s exception table
            # on CPython 3.13 (src/utils/interrupts.py; R161/R163)
            while True:
                if written >= limit:
                    break
                n = min(_CHUNK, limit - written)
                chunk = bytes(n) if zeros else os.urandom(n)
                f.write(chunk)
                written += len(chunk)
            f.flush()
            os.fsync(f.fileno())
        return True
    except OSError:
        _LOG.warning("crypto-erase: overwrite failed for %s (NOT destroyed)", _masked([str(path)])[0])
        return False


# Descriptors the erase keeps on the files it unlinked, as (fd, kind), one list per wipe (its GENERATION): a transaction
# already under way when the erase ran still holds the unlinked file and, on commit, writes page 1 -- salt included -- into it.
# ``kind`` is "whole" (a -wal or -journal, rewritten whole), "head" (a main file, its salt page) or "shm" (a log index, its
# head zeroed); ``cap`` bounds every later rewrite of it (its size when kept plus :data:`_HELD_GROWTH`), so a holder that grows
# the file it shares with the erase (a sparse ``ftruncate`` to hundreds of GiB) cannot make a rewrite fill the disk. Per wipe (row 36), so the late pass of one wipe closes its own descriptors and never a second wipe's, whose own
# late pass then comes its full delay after that second erase.
_HELD: dict[int, list[tuple[int, str, int]]] = {}
_HELD_LOCK = threading.Lock()
_GENERATIONS = itertools.count(1)

# R792. ANOTHER PROCESS holding the store (a second copy of the app, a tool with the database open). Its own descriptors keep
# the unlinked files alive and it can go on committing into them through the erase, putting page 1 -- salt included -- back on
# the disk: measured, a process writing in a loop through the erase left the salt in the log it still held in 5 runs of 5
# without kept descriptors and 1 of 5 with them. The erase never waits on such a process and never signals it. It finds it from
# the locks SQLite takes (every connection holds a shared lock on the main file and on the log index for as long as it is open
# in WAL mode), rewrites through its own kept descriptors while one is seen, for at most _HOLDER_BOUND_S, and says in its result
# when one was still there at the end, or when it could not tell.
#: How long the erase goes on rewriting while another process still holds the store (inline, after every key is destroyed; and
#: again in the panic wipe's late pass before its descriptors are let go). Measured: a rewrite pass of a few-MiB log and the
#: probe take milliseconds, so 2 s is ~20 passes; with no other holder the erase pays two probes per kept file (< 1 ms each) and
#: one more rewrite through them (R796), itself bounded by it.
_HOLDER_BOUND_S = 2.0
_HOLDER_STEP_S = 0.1
#: The erase result's ``other_holder``: no other process was seen holding the store; one was seen holding it at some point of the
#: erase (R796: even one that let go before the end);
#: or whether one did could not be told (Windows, a platform whose lock record is not read here, a probe that failed, a file
#: that could not be kept). Only "none" is a clean result.
HOLDER_NONE, HOLDER_HELD, HOLDER_UNKNOWN = "none", "held", "unknown"
# SQLite's lock bytes (os_unix.c): PENDING_BYTE 0x40000000, then RESERVED, then the 510-byte SHARED range, on the main file;
# the eight WAL locks from byte 120 and the "dead man switch" at 128 on the log index.
_MAIN_LOCKS = (0x40000000, 2 + 510)
_SHM_LOCKS = (120, 9)
#: How far a kept file may grow past its size when kept and still be rewritten whole (a holder's commits through the erase
#: append to the log; the app's own log is cut back to 64 MiB after a checkpoint).
_HELD_GROWTH = 256 * 1024 * 1024


def new_hold_generation() -> int:
    """A number of its own for one wipe's kept descriptors."""
    return next(_GENERATIONS)


def _hold(path: Path, *, whole: bool, generation: int = 0, kind: str | None = None) -> bool | None:
    """Keep a descriptor on ``path`` for :func:`rescrub_held`. POSIX only: on Windows an open descriptor would make the
    unlink fail. Returns True when kept, None when there is nothing to keep (no such file), False when an existing file
    could not be kept. Never raises."""
    if os.name != "posix":
        return False
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    except FileNotFoundError:
        return None
    except OSError:
        return False
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:  # a FIFO, socket or device is never kept to write to
        os.close(fd)
        return False
    kind = kind or ("whole" if whole else "head")
    try:
        cap = os.fstat(fd).st_size + _HELD_GROWTH
    except OSError:
        cap = _HELD_GROWTH
    # No lock: the erase waits on nothing, and a rescrub of an earlier wipe may hold it for a long rewrite. ``setdefault`` and a
    # list append are atomic, and a pass takes only the entries present when it starts, removing them from the front.
    _HELD.setdefault(generation, []).append((fd, kind, cap))
    return True


def _flock_layout() -> str | None:
    """The ``struct flock`` layout of this platform, or None where it is not read here (the result then says "could not tell")."""
    if sys.platform.startswith("linux"):
        return "hhqqi"  # l_type, l_whence, l_start, l_len, l_pid
    if sys.platform == "darwin":
        return "qqihh"  # l_start, l_len, l_pid, l_type, l_whence
    return None


def _flock(kind: int, start: int, length: int) -> bytes | None:
    layout = _flock_layout()
    if layout is None:
        return None
    if layout == "hhqqi":
        return struct.pack(layout, kind, os.SEEK_SET, start, length, 0)
    return struct.pack(layout, start, length, 0, kind, os.SEEK_SET)


def _other_holder(fd: int) -> bool | None:
    """Whether ANOTHER process holds a lock on the file behind ``fd``: one ``F_GETLK`` over the whole file (it never reports this
    process's own locks, and never changes any). None when it cannot be told. The other process's id is never read out: the
    answer is only yes or no."""
    try:
        import fcntl
    except ImportError:
        return None
    layout = _flock_layout()
    probe = _flock(fcntl.F_WRLCK, 0, 0)
    if layout is None or probe is None:
        return None
    try:
        got = fcntl.fcntl(fd, fcntl.F_GETLK, probe)
    except (OSError, ValueError):
        return None
    lock_type = struct.unpack(layout, got[: struct.calcsize(layout)])[0 if layout == "hhqqi" else 3]
    return lock_type != fcntl.F_UNLCK


def _shut_out(fd: int, kind: str) -> None:
    """R792 (2): one attempt, never waiting, to take SQLite's lock bytes on a kept main file or log index for writing, so a
    process that holds the file open but no lock on it yet (between two transactions) is refused when it next begins one. It
    fails, and the erase carries on, whenever another connection already holds those bytes: that case is what the probe and
    the bounded rewrite are for. POSIX locks belong to the PROCESS, not to the descriptor: closing ANY descriptor this process has
    on the file drops them (the erase's own overwrite of the path, this process's pool closing after the erase), so it is taken
    only through :func:`shut_out_held`, once every such open and close is over. Never raises."""
    try:
        import fcntl
    except ImportError:
        return
    start, length = _MAIN_LOCKS if kind == "head" else _SHM_LOCKS
    req = _flock(fcntl.F_WRLCK, start, length)
    if req is None:
        return
    with contextlib.suppress(OSError, ValueError):
        fcntl.fcntl(fd, fcntl.F_SETLK, req)


def shut_out_held(generation: int) -> None:
    """Take the lock bytes of every kept main file and log index of one wipe (see :func:`_shut_out`). Called after the erase has
    finished opening and closing those paths, and on the panic path after its pool is closed, or the close would undo it."""
    for fd, kind, _cap in list(_HELD.get(generation, ())):
        if kind in ("head", "shm"):
            _shut_out(fd, kind)


def _holder_state(entries: list[tuple[int, str, int]]) -> str:
    """One probe of every kept main file, log and log index: ``held`` when any shows another process's lock, ``unknown`` when
    any could not be asked, ``none`` otherwise."""
    if os.name != "posix" or _flock_layout() is None:
        return HOLDER_UNKNOWN
    unknown = False
    for fd, _kind, _cap in entries:
        seen = _other_holder(fd)
        if seen:
            return HOLDER_HELD
        unknown = unknown or seen is None
    return HOLDER_UNKNOWN if unknown else HOLDER_NONE


def settle_other_holders(generation: int, *, bound_s: float | None = None) -> str:
    """R792 (3): while another process still holds the erased store, rewrite through this wipe's kept descriptors every
    :data:`_HOLDER_STEP_S`, for at most ``bound_s`` (default :data:`_HOLDER_BOUND_S`). R796 (row 331), the rule the uninstall
    watcher keeps too (#2292; that detached script cannot import this module, so its copy is pinned to this one by
    ``tests/test_holder_rule_shared_row331.py``): one more rewrite, under a bound of its own, ALWAYS follows, whatever was
    found, and a holder seen at any point makes the result ``held`` even when it has let go by the end (a store file that
    existed but could not be kept already makes it ``unknown``, :func:`finish_holder_check`). Never sleeps when none is seen, never signals the other process, never raises."""
    bound = _HOLDER_BOUND_S if bound_s is None else bound_s
    try:
        entries = list(_HELD.get(generation, ()))
        state = _holder_state(entries)
        seen = state == HOLDER_HELD
        # R796, as the watcher keeps it: a probe that could not tell is never cleared by a later one that saw nothing (the file it
        # could not ask about may have been held by a program that let go since).
        ever_unknown = state == HOLDER_UNKNOWN
        if seen:
            deadline = time.monotonic() + bound
            while True:
                rescrub_held(close=False, generation=generation, deadline=deadline)
                if time.monotonic() >= deadline:
                    break
                time.sleep(_HOLDER_STEP_S)
                state = _holder_state(entries)
                ever_unknown = ever_unknown or state == HOLDER_UNKNOWN
                if state != HOLDER_HELD:
                    break
        # R796: always, whatever was found -- what a holder committed before it let go, or one no probe could see.
        rescrub_held(close=False, generation=generation, deadline=time.monotonic() + bound)
        state = _holder_state(entries)
        # R796: a holder seen at any point may have written behind the last rewrite before it let go: never "none".
        if seen or state == HOLDER_HELD:
            return HOLDER_HELD
        return HOLDER_UNKNOWN if ever_unknown or state == HOLDER_UNKNOWN else HOLDER_NONE
    except Exception:  # noqa: BLE001 - an erase result is never lost to its own bookkeeping
        return HOLDER_UNKNOWN


def rescrub_held(*, close: bool, generation: int | None = None, settle: bool = True, deadline: float | None = None) -> int:
    """Overwrite again, through the kept descriptors, the head of every unlinked main file and log index and the whole of
    every unlinked -wal and -journal; with ``close`` the descriptors are then let go. Only one wipe's with ``generation``,
    every wipe's without. A closing pass first goes on rewriting while another process still holds one of the files, within
    :data:`_HOLDER_BOUND_S` (R792: the hold is never let go while another holder is still seen inside the bound; ``settle``
    False skips that when the caller has just done it). Each file is rewritten up to its ``cap``; a ``deadline`` (a
    ``time.monotonic()`` value) stops a pass that runs past it. Returns how many were rewritten. Never raises: the wipe is done, this
    closes the window a late commit leaves."""
    if close and settle:
        gens = list(_HELD) if generation is None else [generation]
        for g in gens:
            if settle_other_holders(g) == HOLDER_HELD:
                # No path and no process id: the line says only what the erase could not finish (R734/R736).
                _LOG.warning("crypto-erase: another program still had the erased database open when its kept descriptors "
                             "were let go; the erase may be incomplete")
    done = 0
    # The lock is held for the whole rewrite, so a closing pass can never close a descriptor another pass is still writing
    # through (its number could already belong to an unrelated file). Never on a latency path: the wipe has returned.
    with _HELD_LOCK:
        gens = list(_HELD) if generation is None else [generation]
        taken = {g: len(_HELD.get(g, ())) for g in gens}
        held = [e for g in gens for e in _HELD.get(g, [])[: taken[g]]]
        if close:
            _forget_held(taken)
        done = _rewrite_held(held, close=close, deadline=deadline)
    return done


def _forget_held(taken: dict[int, int]) -> None:
    """Drop the first ``n`` entries of each generation a closing pass took (later appends stay), and an emptied generation."""
    for g, n in taken.items():
        kept = _HELD.get(g)
        if kept is None:
            continue
        del kept[:n]
        if not kept:
            _HELD.pop(g, None)


def held_count(generation: int | None = None) -> int:
    """How many descriptors :func:`rescrub_held` still holds: one wipe's with ``generation``, every wipe's without."""
    if generation is not None:
        return len(_HELD.get(generation, ()))
    return sum(len(v) for v in list(_HELD.values()))


def _rewrite_held(held: list[tuple[int, str, int]], *, close: bool, deadline: float | None = None) -> int:
    done = 0
    # The salt-bearing heads first, as the watcher's rewrite_kept does: a long log must not use the whole bound before a main
    # file's first page is reached.
    for fd, kind, cap in sorted(held, key=lambda e: e[1] == "whole"):
        try:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError  # not rewritten this pass; a closing pass still closes it below
            size = min(os.fstat(fd).st_size, cap)
            limit = size if kind == "whole" else min(size, _SQLCIPHER_PAGE1)
            os.lseek(fd, 0, os.SEEK_SET)
            written = 0
            while True:
                if written >= limit:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError
                n = min(_CHUNK, limit - written)
                # A log index's head is zeroed, never randomised (see pass 1 of the erase): a random frame count grows the
                # mapped file of a connection that reads it.
                written += os.write(fd, bytes(n) if kind == "shm" else os.urandom(n))
            os.fsync(fd)
            done += 1
        except TimeoutError:
            pass  # the bound ended this pass; the result says whether a holder was still there
        except OSError:
            _LOG.warning("crypto-erase: a held file could not be rewritten again")
        finally:
            if close:
                with contextlib.suppress(OSError):
                    os.close(fd)
    return done


def _absent(exc: OSError) -> bool:
    """Whether a failed look at a path says it is not there (rather than that it could not be looked at). A link that loops
    holds nothing to overwrite and is no folder the erase could not check (``Path.exists`` said "not there" too)."""
    return isinstance(exc, (FileNotFoundError, NotADirectoryError)) or exc.errno == errno.ELOOP


def _kind(p: Path, unreached=None) -> str:
    """What ``p`` is, never following a link: ``absent``, ``link`` (a junction too), ``dir``, ``file`` (regular), ``other`` (a FIFO,
    socket or device) or ``unreached``. R798: an entry that cannot be looked at (its folder can be listed but not searched, mode
    ``r--``) is ``unreached`` and handed to ``unreached``; it is never taken for a link, a file already handled or one that is not
    there."""
    try:
        st = os.lstat(p)
    except OSError as exc:
        if _absent(exc):
            return "absent"
        if unreached is not None:
            unreached(p)
        return "unreached"
    if stat.S_ISLNK(st.st_mode):
        return "link"
    if stat.S_ISDIR(st.st_mode):
        try:
            return "link" if os.path.isjunction(p) else "dir"  # a Windows junction, which os.walk would enter
        except OSError:
            return "link"
    return "file" if stat.S_ISREG(st.st_mode) else "other"


def _present(p: Path, unreached=None) -> bool:
    """Whether ``p`` is there, following a link (the store files step 1 reaches). One that cannot be looked at counts as there and
    is handed to ``unreached`` (R798): it is then reported as not overwritten, never passed over as missing."""
    try:
        os.stat(p)
        return True
    except OSError as exc:
        if _absent(exc):
            return False
        if unreached is not None:
            unreached(p)
        return True


def _real(db: Path) -> Path:
    try:
        return db.resolve() if db.is_symlink() else db
    except OSError:
        return db


def _key_files_lock() -> contextlib.AbstractContextManager:
    """The lock every key-file name change in this process takes (``src/custody/keyfile.py``); a no-op
    stand-in when that module cannot be imported, since an erase must never be blocked by bookkeeping."""
    try:
        from src.custody.keyfile import KEY_FILES_LOCK
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not take the key-file lock for the erase", exc, level=logging.WARNING)
        return contextlib.nullcontext()
    return KEY_FILES_LOCK


def _destroy_keys_folder(keys_dir: Path, track, keys_destroyed: list[str], unlisted=None, *, unreached=None) -> tuple[int, int]:
    """Step 2 and 2b of the quick erase in a ``keys`` folder that is the app's by its content (R806 (2)), ``(seen, wiped)``: the
    corpus signer's named key files, then everything else in it (the evidence key, a private copy in ``keys/.pending``), then the
    folder itself, so nothing can be added to it before the caller lets the key-file lock go. In shared scope, and for a ``keys``
    that holds anything the app did not write, :func:`_destroy_app_keys_in_foreign` is used instead: exact names only (R807 (3)).
    A function of its own with no handler, called inside the caller's ``with``: CPython 3.13 leaves a loop's back-edge outside the
    exception table of the block around it, so the loops live here (R163; tests/test_loop_heads_reach.py)."""
    seen = wiped = 0
    for name in _KEY_FILES:
        s, overwritten, w = track(keys_dir / name)
        seen += s
        wiped += w
        if s and overwritten:
            keys_destroyed.append(name)
    if _kind(keys_dir, unreached) == "dir":
        for root, dirs, names in os.walk(keys_dir, onerror=unlisted):
            dirs[:] = [d for d in dirs if _kind(Path(root, d), unreached) == "dir"]  # a link or a junction never entered
            for name in names:
                s, _overwritten, w = track(Path(root) / name)
                seen += s
                wiped += w
        shutil.rmtree(keys_dir, ignore_errors=True)
    return seen, wiped


def _destroy_app_keys_in_foreign(keys_dir: Path, track, keys_destroyed: list[str], unlisted=None, unreached=None) -> tuple[int, int]:
    """R806 (2): step 2 for a ``keys`` folder that is not the app's by its content (it holds something the app did not write), and
    R807 (3): for every ``keys`` in shared scope (a folder the app does not own), where ``keys`` is a common name. Only
    the app's own key files go, by their exact names (``data_scope.APP_KEY_NAMES``), and the private copies in a real ``.pending``
    folder, by their one name shape; everything else is left byte for byte, and neither folder is removed unless that left it
    empty. A ``keys`` that is a link, a junction or not a folder is never entered: nothing in it is the app's to reach."""
    from src.safety.data_scope import APP_KEY_NAMES, KEYS_PENDING, KEYS_PENDING_RE

    seen = wiped = 0
    if _kind(keys_dir, unreached) != "dir":
        return seen, wiped
    for name in (*_KEY_FILES, *sorted(APP_KEY_NAMES - set(_KEY_FILES))):  # the corpus signer's pair first, as in the app's own folder
        p = keys_dir / name
        if _kind(p, unreached) != "file":
            continue  # a link or a folder under one of the app's names was not written by the app: left, never followed
        s, overwritten, w = track(p)
        seen += s
        wiped += w
        if s and overwritten and name in _KEY_FILES:
            keys_destroyed.append(name)
    pending = keys_dir / KEYS_PENDING
    if _kind(pending, unreached) == "dir":
        for e in _listing(pending, unlisted):
            p = Path(e.path)
            if re.fullmatch(KEYS_PENDING_RE, e.name) and _kind(p, unreached) == "file":
                s, _overwritten, w = track(p)
                seen += s
                wiped += w
        with contextlib.suppress(OSError):
            pending.rmdir()  # only when empty
    with contextlib.suppress(OSError):
        keys_dir.rmdir()  # only when empty: what is left in it is not the app's to remove
    return seen, wiped


def _app_keys_left(keys_dir: Path) -> list[str]:
    """The app's own key files and private copies still in ``keys`` after step 2 (as ``keys/<the app's own name>``: never a name
    of the operator's), and ``keys/.pending`` itself when it is a link or a junction, which is never entered."""
    from src.safety.data_scope import APP_KEY_NAMES, KEYS_PENDING, KEYS_PENDING_RE

    if _kind(keys_dir) != "dir":
        return []
    left = [f"keys/{n}" for n in sorted(APP_KEY_NAMES) if _kind(keys_dir / n) == "file"]
    pending = keys_dir / KEYS_PENDING
    kind = _kind(pending)
    if kind == "link":
        left.append(f"keys/{KEYS_PENDING}")
    elif kind == "dir":
        left += [f"keys/{KEYS_PENDING}/{e.name}" for e in _listing(pending)
                 if re.fullmatch(KEYS_PENDING_RE, e.name) and _kind(Path(e.path)) == "file"]
    return left


def _kept_in_keys(keys_dir: Path) -> int:
    """How many entries a foreign ``keys`` folder still holds that the app did not write (1 for a ``keys`` that is a link or not a
    folder: that entry itself). A count only: names are never read out (R806 (4)). One that cannot be listed counts 0: what it
    holds is not known, and the erase says "could not check" for it (R798), never "holds items the app did not create"."""
    from src.safety.data_scope import APP_KEY_NAMES, KEYS_PENDING, KEYS_PENDING_RE

    kind = _kind(keys_dir)
    if kind == "absent":
        return 0
    if kind != "dir":
        return 1
    try:
        entries = list(os.scandir(keys_dir))
    except OSError:
        return 0  # could not be listed (R798): said as "could not check" (unlisted_folders), never as a count
    n = 0
    for e in entries:
        if e.name == KEYS_PENDING:
            if _kind(Path(e.path)) != "dir":
                n += 1
            else:
                n += sum(1 for f in _listing(Path(e.path)) if not (re.fullmatch(KEYS_PENDING_RE, f.name) and _kind(Path(f.path)) == "file"))
        elif e.name not in APP_KEY_NAMES:
            n += 1
        elif _kind(Path(e.path)) != "file":
            n += 1
    return n


def _shred(path: Path, *, head_bytes: int | None = None, zeros: bool = False, unreached=None) -> tuple[bool, bool, bool]:
    """Overwrite then unlink ``path``. Returns ``(seen, overwritten, unlinked)``:
    ``seen`` is whether the file existed, ``overwritten`` whether the destructive
    write actually completed, ``unlinked`` whether the directory entry was removed.
    These are reported separately -- a failed overwrite followed by a successful
    unlink is NOT destruction, it's just deletion, and callers must not conflate
    the two when claiming a salt page or key file was destroyed. A file that cannot be looked at counts as seen and is handed to
    ``unreached`` (R798): ``(True, False, ...)``, never "not there"."""
    if not _present(path, unreached):
        return (False, False, False)
    overwritten = _overwrite(path, head_bytes=head_bytes, zeros=zeros)
    try:
        path.unlink()
        return (True, overwritten, True)
    except OSError:
        _LOG.warning("crypto-erase: could not unlink %s", _masked([str(path)])[0])
        return (True, overwritten, False)


def _lane_dbs(base: Path) -> list[Path]:
    """Every versioned-source lane file under ``base``, present or not.

    WHY THESE ARE NOT "ANYTHING ELSE UNDER THE DATA DIR". Step 6 of the erase overwrites
    and unlinks whatever remains, and its own comment states the premise it rests on:
    *"remaining files are small side files, so a full overwrite here is cheap and
    complete"*. Q719 = a exists precisely because a lane may reach 100 GB. Left to step
    6, a lane would be FULLY rewritten — turning an operation whose whole promise is
    "instant at any corpus size" into an hours-long one, and quietly replacing the
    CRYPTO-erase guarantee (destroy the salt, the body is unreadable) with a DATA-erase
    that has to finish to be worth anything. Nothing would have caught it: no test
    asserts that the erase is fast.

    So lanes join step 1's head-shred, where the salt page is. Resolved from the lane
    REGISTRY rather than from a glob, so a lane kind added later is covered the day it
    is added, and a stray ``*.db`` an operator dropped in the folder is not mistaken for
    one of ours.
    """
    from src.versioned.lanes import all_lanes

    return [base / spec.filename for spec in all_lanes()]


def _resolve(data_dir: Path | None) -> dict:
    """Resolve every wipe target. For the default store (``data_dir is None``) the
    real resolvers are used so nothing is hardcoded; an explicit dir (tests/tools)
    derives the same layout from that base."""
    from src.paths import data_dir_path

    if data_dir is not None:
        base = Path(data_dir)
        return {
            "base": base,
            "main_db": base / _MAIN_DB,
            "keys_dir": base / "keys",
            "store_dir": base,
            "custody_db": base / _CUSTODY_DB,
            "anchors_db": base / _ANCHORS_DB,
            "lane_dbs": _lane_dbs(base),
        }
    from src.api.unlock import main_db_path

    # R806 (1): the erase never makes anything in the folder it erases, so every target is NAMED here, never made: the data folder
    # where src.paths.data_dir would answer (data_dir_path: no mkdir, the same precedence), the keys folder inside it (src.custody.
    # signing._keys_dir makes it; a missing one is nothing to erase) and the columnar store where src.analytics.columnar._store_dir
    # puts it (its OO_COLUMNAR_DIR override, else the data folder). A second erase in this process, of a folder the first one
    # latched (R802), resolves the same way.
    base = data_dir_path()
    override = os.getenv("OO_COLUMNAR_DIR")
    store_dir = Path(override) if override else base
    keys_dir = base / "keys"
    return {
        "base": base,
        "main_db": main_db_path(),  # honors DATABASE_URL; None on a non-SQLite backend
        "keys_dir": keys_dir,
        "store_dir": store_dir,
        "custody_db": base / _CUSTODY_DB,
        "anchors_db": base / _ANCHORS_DB,
        "lane_dbs": _lane_dbs(base),
    }


# The names the app gives a copy of one of its databases, kept beside it (row 29): a repair's salvage and damaged copies
# (src/database/repair.py), a rebuild's copy and the file it kept (src/database/rebuild.py, R702), an encryption's pre-encrypt snapshot and in-progress copy (src/database/encrypt_tool.py), and,
# in the data folder only, a retained pre-restore snapshot (src/backup/merge.py). Each with the side files the app gives it.
_STAMP = r"\d{8}T\d{6}Z"
_COPY_TAIL = r"(?:(?:\.partial)?(?:-wal|-shm|-journal)?|\.json)"
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _copy_patterns(folder: Path, base: Path, dbs: list[Path]) -> list[re.Pattern[str]]:
    pats = []
    for db in dbs:
        if db.parent != folder:
            continue
        stem, suffix = re.escape(db.stem), re.escape(db.suffix)
        pats.append(re.compile(rf"{stem}\.(?:salvage|damaged|rebuild|pre-rebuild)-{_STAMP}(?:-\d+)?{suffix}{_COPY_TAIL}"))
        pats.append(re.compile(rf"pre-encrypt-{_STAMP}-{re.escape(db.name)}{_COPY_TAIL}"))
        pats.append(re.compile(rf"{re.escape(db.name)}\.enc-{_STAMP}{_COPY_TAIL}"))
    if folder == base:
        pats.append(re.compile(rf"pre-restore-{_STAMP}\.db{_COPY_TAIL}"))
    return pats


def _listing(folder: Path, unlisted=None) -> list[os.DirEntry]:
    """The top-level entries of ``folder``, or none when it cannot be listed. ``list`` closes the scan as it ends it. A folder that
    is not there holds nothing; one that is there but cannot be listed is handed to ``unlisted`` (R798), never passed over in
    silence."""
    try:
        return list(os.scandir(folder))
    except FileNotFoundError:
        return []
    except OSError as exc:
        if unlisted is not None:
            unlisted(exc)
        return []


def _db_copies(folder: Path, base: Path, dbs: list[Path], unlisted=None) -> list[Path]:
    """The app's own copies of a database in ``folder``, by name; regular files only (a link is left to step 6)."""
    pats = _copy_patterns(folder, base, dbs)
    if not pats:
        return []
    out = []
    for entry in _listing(folder, unlisted):
        if not any(p.fullmatch(entry.name) for p in pats):
            continue
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        out.append(Path(entry.path))
    return out


def _copy_mode(p: Path, *, encrypted_store: bool) -> str:
    """How a copy is destroyed: ``whole`` (a log or a side file: the salt sits past the head, or there is no salt), ``zeros``
    (a -shm index: no page data), ``plain`` (a plaintext database: no salt to lose, so rewritten whole, later) or ``head``
    (an encrypted database: its salt is its first page). Only a copy of a store KNOWN to be encrypted is ever head-only: a
    damaged copy of a plaintext store can have a page 1 that no longer reads as SQLite and a plaintext body behind it. A
    head that cannot be read counts as plaintext: rewritten whole."""
    name = p.name
    if name.endswith(("-wal", "-journal", ".json")):
        return "whole"
    if name.endswith("-shm"):
        return "zeros"
    if name.startswith("pre-encrypt-") or not encrypted_store:
        return "plain"
    try:
        with open(p, "rb") as f:
            head = f.read(len(_SQLITE_MAGIC))
    except OSError:
        return "plain"
    return "plain" if head == _SQLITE_MAGIC else "head"


def _erase_roots(base: Path, *, app_only: bool, unlisted=None, unreached=None) -> list[Path]:
    """What steps 5b and 6 reach: the data folder whole, or, in a folder the app does not own (R711), each top-level entry the app
    owns there, by name."""
    if not _present(base, unreached):
        return []
    if not app_only:
        return [base]
    from src.safety.data_scope import is_app_owned, owned_spec

    spec = owned_spec(shared=True)  # the app's common names (models, cache, keys...) are left: they may be the operator's
    return sorted(Path(e.path) for e in _listing(base, unlisted) if is_app_owned(e.name, spec=spec))


def _files_under(roots: list[Path], base: Path, onerror, skip: Path | None = None, unreached=None):
    """Every file under ``roots``, never following a link or a junction below them. The data folder itself is entered even when it
    is a link (the operator put it there); a top-level entry that is a link is yielded as itself, so it is removed, never followed.
    A folder below that cannot be looked at is handed to ``unreached`` (R798), never dropped as if it were a link."""
    for root in roots:
        if root != base:
            kind = _kind(root, unreached)
            if kind == "unreached":
                continue
            if kind != "dir":
                yield root
                continue
        if skip is not None and root == skip:
            continue
        for top, dirs, names in os.walk(root, onerror=onerror):
            dirs[:] = [d for d in dirs if Path(top, d) != skip and _kind(Path(top, d), unreached) == "dir"]
            for name in names:
                if skip is not None and Path(top, name) == skip:
                    continue  # R806: a foreign keys entry that is a link to a file, or a file, is left too
                yield Path(top, name)


def _remove_app_folders(roots: list[Path]) -> None:
    """The app's own folders, once their files are destroyed; a top-level link of ours is removed, never followed."""
    for root in roots:
        kind = _kind(root)
        if kind == "link":
            with contextlib.suppress(OSError):
                root.unlink()
        elif kind == "dir":
            shutil.rmtree(root, ignore_errors=True)


def _left_entries(base: Path) -> dict[str, list[str]]:
    """What an app-only erase left at the top of the data folder, by name (never opened or read): ``others`` the app does not
    own, ``common`` the app's common names left because they may be the operator's, ``not_removed`` the app's own that a
    removal failed on (each also named in ``overwrite_failures`` when its overwrite failed)."""
    from src.safety.data_scope import is_app_owned, owned_spec

    full, shared = owned_spec(), owned_spec(shared=True)
    left: dict[str, list[str]] = {"others": [], "common": [], "not_removed": []}
    for name in sorted(e.name for e in _listing(base)):
        kind = "not_removed" if is_app_owned(name, spec=shared) else "common" if is_app_owned(name, spec=full) else "others"
        left[kind].append(name)
    return left


def quick_crypto_erase(
    confirm: bool = False, *, data_dir: Path | None = None, hold_for_rescrub: bool = False, hold_generation: int = 0,
    settle: bool = True,
) -> dict:
    """Instant crypto-erase then remove the data dir. Requires ``confirm=True``.

    Order: (1) in three passes, the salt page of each encrypted DB (main, custody, lanes) with its -shm head zeroed,
    then its WAL and journal whole (they hold copies of page 1), then the salt pages again, unlinked; (2) the on-disk
    keys; (3) the DuckDB cache header and key sidecar; (4) ``anchors.db`` whole; (5) the in-memory passphrase;
    (5a) the copies the app made of a database beside it, wherever it is (an encrypted one head-only, a plaintext one whole);
    (5b) the head of every other file under the data dir (encrypted snapshots and copies); (6) a full overwrite and
    unlink of everything left, then ``rmtree``. In a data folder the app does not own (R711), 5b and 6 reach only the app's
    own entries and the folder is kept (``scope`` in the report). No link is written through except the app's own databases. Fast at any corpus size (the encrypted body is never rewritten —
    its key is gone). ``data_dir`` overrides the target (tests/tools).

    ``hold_for_rescrub`` (the panic wipe, POSIX only) keeps a descriptor on every main file, -wal and -journal before
    it is unlinked, so :func:`rescrub_held` can destroy what a transaction already under way writes into the unlinked
    file after this returns (its commit puts page 1, salt included, back on the disk), under ``hold_generation`` (one wipe's own).
    Without it the erase keeps them only while it runs and lets them go before it returns.

    Either way (R792), once every key is destroyed the erase looks for ANOTHER process holding the store, goes on rewriting
    through the kept descriptors while one is seen (at most :data:`_HOLDER_BOUND_S`, never waiting when none is), and reports
    ``other_holder``: ``"none"``, ``"held"`` (one was seen holding the store during the erase, even if it let go before the end: the erase may be incomplete) or
    ``"unknown"`` (it could not tell; always so on Windows, where an open file cannot be found from here). Only "none" is a
    clean erase, and it means none was SEEN (a process holding no lock at that moment, or one on another machine sharing the
    folder over a network file system, is not). ``settle`` False (the panic wipe, which closes its pool and takes the app
    offline first) leaves that step to :func:`finish_holder_check`, which the caller then runs."""
    if not confirm:
        raise PermissionError("quick_crypto_erase requires confirm=True (this is irreversible)")
    own = not hold_for_rescrub
    generation = new_hold_generation() if own else hold_generation
    missed: list[str] = []
    root_token = _ERASE_ROOT.set(None)  # the erase sets its data folder; put back as it was when it ends
    from src.paths import erase_owned

    try:
        # R802: the erase latches its folder before it touches a byte; its own overwrites, on this thread, are the writes let through.
        with erase_owned():
            report = _quick_crypto_erase(data_dir=data_dir, generation=generation, missed=missed, close_own_pool=own)
            report["files_not_kept"] = len(missed)  # a count: the names are never reported
            if settle or own:
                finish_holder_check(report, generation)
        if settle or own:
            settle_removed(report)  # R802 (5): after the last log line of this erase
        return report
    finally:
        _ERASE_ROOT.reset(root_token)
        if own:
            rescrub_held(close=True, generation=generation, settle=False)


def finish_holder_check(report: dict, generation: int) -> str:
    """R792: take the kept files' lock bytes, go on rewriting while another process still holds the store (bounded), and set
    ``report["other_holder"]``; when it is not "none", ``report["limit"]`` says the corpus may still be recoverable instead of
    the clean guarantee. Returns the state. Never raises."""
    try:
        shut_out_held(generation)
        state = settle_other_holders(generation)
    except Exception:  # noqa: BLE001 - an erase result is never lost to its own bookkeeping
        state = HOLDER_UNKNOWN
    if report.get("files_not_kept") and state == HOLDER_NONE:
        state = HOLDER_UNKNOWN  # a file of the store that could not be kept could not be asked either
    # R805 (a): this process's own connections that the erase could not close count as a holder too: a lock the process holds
    # itself is never seen by the probe above (POSIX locks of one process do not conflict), so it is counted, not probed.
    own_open = report.get("own_connections_open", 0)
    if own_open is None and state == HOLDER_NONE:
        state = HOLDER_UNKNOWN
    elif own_open:
        state = HOLDER_HELD
    report["other_holder"] = state
    if state != HOLDER_NONE:
        report["limit"] = _LIMIT_NOTE_NOT_CLEAN + (" " + _UNLISTED_SENTENCE if report.get("unlisted_folders") else "")
        _LOG.warning("CRYPTO-ERASE: %s", "another program had the database open during the erase; the erase may be "
                     "incomplete" if state == HOLDER_HELD else "could not check whether another program had the database open")
    return state


def _close_own_pool() -> int | None:
    """R805 (a), for an erase outside the panic wipe (which closes the pool itself, after the key is gone): close this process's own
    pool on the store when that store is in the folder being erased (latched by now), before a byte is overwritten. Returns the
    connections still open after it (checked out by a thread: ``Engine.dispose`` cannot close those), ``None`` when that cannot be
    told, ``0`` when the store is elsewhere. Never raises."""
    try:
        from src.database import session
        from src.paths import erased_folder_of

        db_file = getattr(session, "DB_FILE", None)
        if not db_file or not erased_folder_of(db_file):
            return 0
        n = session.dispose_engine().get("checked_out")
        return n if isinstance(n, int) else None
    except Exception:  # noqa: BLE001 - not knowing is "unknown", never "none"
        return None


def _quick_crypto_erase(*, data_dir: Path | None, generation: int, missed: list[str], close_own_pool: bool = False) -> dict:
    """The erase itself (see :func:`quick_crypto_erase`); keeps its descriptors under ``generation`` and names in ``missed``
    each file of a store that existed but could not be kept."""

    from src.database.connect import is_encrypted_file

    paths = _resolve(data_dir)
    base: Path = paths["base"]
    _latch(base)  # R802: before a byte is touched; for the rest of the process
    _latch_outside(paths, base)  # a store the overrides put outside the folder is latched too (its exact files only)
    own_open = _close_own_pool() if close_own_pool else 0  # R805 (a): after the latch, so no new connection opens on the store
    _ERASE_ROOT.set(base)  # every log line of this erase is masked against its own data folder, never src.paths.data_dir
    # R711. Is the data folder the app's own? One the app did not choose that also holds other files (the operator's home folder, a
    # drive root, a mount point, a projects folder) is never walked whole or removed: steps 5b and 6 reach only the entries the app
    # owns there (src/safety/data_scope.py, by name, its common names such as "models" excepted), the keys folder keeps whatever is
    # not a key of the app's, and the report names every top-level entry left. Read before a byte is touched; bounded (the scan
    # stops at the first entry the app does not own). A scope that cannot be read is treated as shared: leaving an operator's file
    # is recoverable, destroying it is not.
    try:
        from src.safety.data_scope import folder_scope

        scope = folder_scope(base)
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not read the data folder's scope; erasing the app's own files only", exc, level=logging.WARNING)
        scope = {"broad": True, "reason": "unknown"}
    app_only = bool(scope["broad"])
    # R806 (2): in a folder of the app's own, ``keys`` is the app's by its CONTENT, never by its name: a real folder holding only the
    # names the app writes there (data_scope.keys_folder_state). One that holds anything else, or is a link, is "foreign": only the
    # app's key files in it go, the rest is left, and so is the data folder. One that cannot be listed is "could not check" (R798) and
    # is left the same way. (In a folder the app does not own, keys is a common name and already handled that way.) Read-only.
    keys_state = "absent"
    if not app_only:
        try:
            from src.safety.data_scope import keys_folder_state

            keys_state = keys_folder_state(paths["keys_dir"])
        except Exception:  # noqa: BLE001 - not knowing is "could not check", never "the app's"
            keys_state = "unlisted"
    keys_foreign = keys_state in ("foreign", "unlisted")
    seen = wiped = 0
    headers: list[str] = []
    keys_destroyed: list[str] = []
    # Files that existed but whose destructive overwrite itself failed (e.g. ENOSPC on a
    # CoW filesystem mid-write) -- unlink may still have succeeded, but that is deletion,
    # not destruction. Reported honestly rather than folded into "headers_destroyed" /
    # "keys_destroyed", which must only ever mean the overwrite actually completed.
    overwrite_failures: list[str] = []

    # R798: every folder a walk could not list, in every walk of this erase (the keys folder, the copies beside each database, the
    # app's own entries of a shared folder, steps 5b and 6). Any one of them makes the result "may be incomplete": the files in it
    # were never checked, so nothing here is called destroyed.
    unlisted_folders: list[str] = []

    def _unlisted(failed_listing) -> None:  # a folder a walk cannot list is named (its path only), never skipped in silence
        if isinstance(failed_listing, FileNotFoundError):
            return  # gone between the listing of its parent and its own: nothing in it to check
        name = str(getattr(failed_listing, "filename", None) or "an unlistable folder")
        overwrite_failures.append(name)
        unlisted_folders.append(name)

    def _unreached(p: Path) -> None:  # an entry that cannot be looked at: its folder could be listed, not searched (mode r--)
        overwrite_failures.append(str(p))
        unlisted_folders.append(str(p.parent))

    def _track(p: Path, *, head_bytes: int | None = None) -> tuple[bool, bool, bool]:
        s, overwritten, w = _shred(p, head_bytes=head_bytes, unreached=_unreached)
        if s and not overwritten:
            overwrite_failures.append(str(p))
        return s, overwritten, w

    # The columnar serves are the same kind of thing: a PERSISTED one keeps the cache's derived key inside DuckDB for the life of
    # the process and goes on answering from a file step 3 is about to overwrite. Closed here, before a byte is touched and
    # without waiting (an erase is not held up behind a refresh): a serve in use is named and closed as soon as it is free.
    try:
        from src.scheduler.release import close_serves_for_cleared_key

        _serves = close_serves_for_cleared_key()
        if _serves.get("busy"):
            _LOG.warning("a columnar serve was in use during the erase; it is closed as soon as it is free: %s", _serves["busy"])
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not close the columnar serves before the erase", exc, level=logging.WARNING)

    # Was the corpus actually encrypted? Determines whether crypto-erase is the real
    # guarantee (encrypted) or degrades to header-overwrite (plaintext store -> the
    # optional full pass matters more; surfaced so the UI can recommend it).
    main_db: Path | None = paths["main_db"]
    encrypted = is_encrypted_file(main_db) if main_db is not None else None

    # 1) Destroy the salt/header page of each encrypted DB, then its sidecars. Head-only
    #    on the main file = instant even for a 100 GB corpus; the salt is what matters.
    # The lane files join this loop rather than falling through to step 6: each is an
    # encrypted SQLCipher database with its OWN salt page, and head-only is what keeps
    # the erase instant at 100 GB (see ``_lane_dbs``).
    # R708. Every main file's salt page goes first, so no long WAL write delays them.
    # The sidecars follow, and the write-ahead log and the rollback journal are overwritten WHOLE: SQLCipher keeps the
    # 16-byte salt in plaintext at the start of page 1, and every committed change to page 1 leaves a copy of that page
    # in a WAL frame (or, in rollback mode, in the journal) at an offset far past this file's first 4 KiB. Measured on a
    # 20-commit WAL with checkpoints off: the salt sat in 21 places in the -wal, 20 of them beyond the 4 KiB the old
    # head-only pass destroyed, so the old erase left the salt readable for as long as the WAL's blocks survived. The
    # journal_size_limit (session.py) caps only the size the WAL is cut back to after a checkpoint, never its growth, so
    # this pass costs one sequential write of the WAL's size (usually a few MiB, at worst the hundreds of MiB a long
    # un-checkpointed write leaves) -- and it waits on nothing else. The -shm index
    # holds frame numbers and checksums, never page data, so its head is only zeroed (see pass 1).
    # THREE PASSES, so no checkpoint can carry the salt back into a file this step has already left. Pass 1 overwrites
    # the head of every -shm (its header gone, no connection trusts the log index again, so none checkpoints) and of
    # every main file, unlinking nothing. Pass 2 rewrites the -wal and -journal whole. Pass 3 overwrites the main and
    # -shm heads once more and unlinks them, catching a checkpoint that was already copying page 1 home during pass 2.
    # A database reached through a link (a corpus kept on another drive and linked into place) is erased where it really
    # is: these are the app's own files, the one place a link is followed. Every other file is never written through one.
    dbs = [_real(db) for db in (main_db, paths["custody_db"], *paths.get("lane_dbs", ())) if db is not None]
    head_ok: dict[Path, bool] = {}
    # The -shm head is written with ZEROS, never random bytes: it holds no page data, and a connection that rolls back
    # after the erase reads its frame count from that header and grows the mapped file toward it -- a random count grew
    # it toward 32 GiB in the security read; a zeroed header reads as "rebuild from the log", which is already noise.
    for db in dbs:
        for p in (db.with_name(db.name + "-shm"), db):
            if _present(p, _unreached):
                head_ok[p] = _overwrite(p, head_bytes=_SQLCIPHER_PAGE1, zeros=p != db)
    for db in dbs:
        for suffix in ("-wal", "-journal"):
            p = db.with_name(db.name + suffix)
            if _hold(p, whole=True, generation=generation) is False:
                missed.append(p.name)
            s, overwritten, w = _shred(p, unreached=_unreached)
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
    for db in dbs:
        for p in (db, db.with_name(db.name + "-shm")):
            if _hold(p, whole=False, generation=generation, kind="head" if p == db else "shm") is False:
                missed.append(p.name)
            s, overwritten, w = _shred(p, head_bytes=_SQLCIPHER_PAGE1, zeros=p != db, unreached=_unreached)
            overwritten = overwritten and head_ok.get(p, True)
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
            if s and overwritten and p == db:
                headers.append(db.name)

    # Only for a store known to be encrypted: a plaintext body has no salt to lose, and is rewritten whole by step 6.
    salt_gone = {os.path.realpath(db) for db in dbs if head_ok.get(db)} if encrypted is True else set()

    # Close every lane pool now that its salt is gone, and before step 5 drops the passphrase. A pooled SQLCipher connection holds
    # a derived key in memory and an open handle on its file: measured without the close, a connection this process already had
    # open went on serving PRE-ERASE rows from a file that had been randomised and unlinked, for as long as the process lived.
    # Not BEFORE step 1 (row 28): closing the last connection on a live file runs SQLite's write-back of its log, which for a
    # large lane is hundreds of MiB written while the salt is still on the disk. Closed here, the log index is zeroed and the log
    # is noise, so the close finds nothing to write back.
    try:
        from src.versioned.store import dispose_all as _dispose_lanes

        _dispose_lanes()
    except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
        log_failure(_LOG, "could not dispose the lane engines after their salt pages", exc, level=logging.WARNING)

    # 2) Destroy on-disk key material (the scrypt wrap-salt lives inside these files).
    # Under the lock every key-file change of THIS process takes (src/custody/keyfile.py KEY_FILES_LOCK), held
    # until the keys folder is gone: a wrap in place that waited finds its file gone and writes nothing, and a
    # creation that waited finds no folder (OPEN_QUEUE item 41(c)). Before it, a wrap that had checked the file
    # put the destroyed key back under its name after this step. Held for the keys folder only, never for the
    # rest of step 6, which rewrites everything left (a wiki dump can take hours) while a signing request waits.
    keys_dir: Path = paths["keys_dir"]
    # R806 (5) never follows a ``keys`` that is a link; the app's own signers write THROUGH one (signing.py makes its folder with
    # exist_ok), so the app's keys may be where it points and are not destroyed here: said, and the result is never clean.
    keys_link = _kind(keys_dir) == "link"
    if keys_state == "unlisted":
        _unlisted(OSError(errno.EACCES, "could not list the keys folder", str(keys_dir)))
    with _key_files_lock():
        if keys_foreign or app_only:  # R807 (3): in shared scope the app's key files are matched by exact name, never by suffix
            _s, _w = _destroy_app_keys_in_foreign(keys_dir, _track, keys_destroyed, _unlisted, _unreached)
        else:
            _s, _w = _destroy_keys_folder(keys_dir, _track, keys_destroyed, _unlisted, unreached=_unreached)
    seen += _s
    wiped += _w

    # 3) DuckDB cache header and its key-derivation sidecar (the cache's key is stretched from the passphrase and the
    #    salt in that sidecar, so with the sidecar destroyed the key is underivable even from the right passphrase;
    #    the cache is a derived copy, so this is defence-in-depth beside step 1 and the passphrase clearing in
    #    step 5 + the free-space scrub).
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

        try:
            set_passphrase(None)
        finally:
            # the store is gone by design, not vanished; this must never skip the overwrite below
            try:
                from src.config.kv_store import forget_stores

                forget_stores()
            except Exception:  # noqa: BLE001 - bookkeeping only; the wipe goes on
                pass
        passphrase_cleared = True
        # Again, now the key is gone: the close above ran while the key was still held, so a persisted refresh that read it before
        # then, or recorded its store meanwhile, would go on serving the erased corpus's rows under its key (open-on-main row 85).
        # Never waits, like the first.
        try:
            from src.scheduler.release import close_serves_for_cleared_key

            close_serves_for_cleared_key()
        except Exception as exc:  # noqa: BLE001 - an erase must never be blocked by bookkeeping
            log_failure(_LOG, "could not close the columnar serves after the key was cleared", exc, level=logging.WARNING)

    # 5a) Copies of an app database kept beside it under the app's own names (row 29): a retained pre-restore-<ts>.db snapshot,
    #    a repair's salvage and damaged copies, an encryption's in-progress copy. An encrypted one carries its database's salt in
    #    its first page, so its head goes now and it is unlinked, and step 6 never rewrites a corpus-sized body whole (hours).
    #    Looked for beside EVERY database, not only in the data folder: a corpus that DATABASE_URL keeps elsewhere has its copies
    #    there, where no walk of the data folder would reach them. A PLAINTEXT copy (the pre-encrypt snapshot by design, or any
    #    copy of a plaintext store) has no salt to lose: it is rewritten whole, after 5b, wherever it is.
    copies_destroyed: list[str] = []
    plain_copies: list[Path] = []
    for folder in dict.fromkeys([base, *(db.parent for db in dbs)]):
        for p in _db_copies(folder, base, dbs, _unlisted):
            mode = _copy_mode(p, encrypted_store=encrypted is True)
            if mode == "plain":
                plain_copies.append(p)
                continue
            s, overwritten, w = _shred(
                p, head_bytes=None if mode == "whole" else _SQLCIPHER_PAGE1, zeros=mode == "zeros", unreached=_unreached
            )
            seen += s
            wiped += w
            if s and not overwritten:
                overwrite_failures.append(str(p))
            elif s:
                copies_destroyed.append(p.name)

    # 5b) Every OTHER file the erase will reach gets the same treatment now, unlinking nothing, before the slow step 6.
    #    Encrypted copies of the corpus can live there under names no list here can keep up with, each with the corpus's
    #    salt in its first page, and step 6 alone (a full overwrite, hours at corpus size) would leave them readable if the
    #    erase were stopped before it got there. Fail toward shredding more: no file is told apart by its contents (an
    #    encrypted page is indistinguishable from noise), so every regular file's head goes, a -wal or -journal is rewritten
    #    whole and a -shm head is zeroed. It runs AFTER the keys, the cache, the anchors and the passphrase (a large folder
    #    costs one write and sync per file, and nothing may delay those). NOT covered by it, stated: PLAINTEXT staging (backup
    #    members, an extracted restore, a reassembling archive) has no salt to lose, and an encrypted member inside an archive
    #    sits past its head; both are destroyed only by step 6's full rewrite. A folder that cannot be listed is named as a
    #    failure. In a folder the app does not own, only the app's entries are reached.
    heads_elsewhere = 0
    roots = _erase_roots(base, app_only=app_only, unlisted=_unlisted, unreached=_unreached)
    for p in _files_under(roots, base, _unlisted, skip=paths["keys_dir"], unreached=_unreached):
        if _kind(p, _unreached) != "file":
            continue
        name = p.name
        whole = name.endswith(("-wal", "-journal"))
        if _overwrite(p, head_bytes=None if whole else _SQLCIPHER_PAGE1, zeros=name.endswith("-shm")):
            heads_elsewhere += 1
        else:
            overwrite_failures.append(str(p))

    # The plaintext copies found in 5a, rewritten whole and unlinked: in the data folder or beside a database kept elsewhere.
    for p in plain_copies:
        s, overwritten, w = _track(p)
        seen += s
        wiped += w
        if s and overwritten:
            copies_destroyed.append(p.name)

    # 6) Overwrite + unlink everything else still under the data dir, then rmtree. The
    #    encrypted DBs/keys/anchors are already gone; remaining files are small side
    #    files, so a full overwrite here is cheap and complete (no 4 MiB cap — OO-02).
    #    THIS STEP REWRITES EVERY BYTE OF EVERY FILE IT FINDS. A future LARGE file under the data dir (a blob
    #    store, a dump kept inside it) must not fall through to here: give it its own step above that destroys what
    #    keys it and then only unlinks it, or the erase -- whose point is an imminent seizure -- runs for hours.
    #    In a folder the app does not own (R711): only the app's entries, each folder of ours removed, the data folder itself kept.
    # A folder the first-launch step marked on a drive (R86): forget its id first, or the
    # next start would wait for a drive that was erased on purpose, and the watchdog would
    # read the folder vanishing below as a disconnection.
    with contextlib.suppress(Exception):
        from src.safety.data_volume import configured_folder, forget_volume_id

        chosen = configured_folder()
        if chosen is not None and chosen.resolve() == base.resolve():
            forget_volume_id()
    roots = _erase_roots(base, app_only=app_only, unlisted=_unlisted, unreached=_unreached)  # listed again: a file the app wrote since 5b is the app's too
    # R806: a foreign keys folder is left out of the walk (its app key files went in step 2), never followed when it is a link.
    for p in _files_under(roots, base, _unlisted, skip=keys_dir if keys_foreign else None, unreached=_unreached):  # never follows a symlinked folder or a junction
        kind = _kind(p, _unreached)
        if kind in ("absent", "unreached"):
            continue  # gone already, or named as not overwritten (R798)
        if kind != "file":
            # A link is removed, never written through: its target may be anywhere, outside the data dir included.
            # A FIFO, socket or device is removed too: opening one to write would block or reach hardware.
            with contextlib.suppress(OSError):
                p.unlink()
            continue
        if os.path.realpath(p) in salt_gone:
            # A database of an encrypted store whose salt page step 1 destroyed but could not unlink (on Windows a pool still
            # open holds it, and Windows keeps no descriptor for the late pass): its head is overwritten once more, for a
            # commit that put page 1 back since, and its body, noise already, is not rewritten whole (hours at corpus size).
            if not _overwrite(p, head_bytes=_SQLCIPHER_PAGE1):
                overwrite_failures.append(str(p))
            with contextlib.suppress(OSError):
                p.unlink()
            continue
        _s, _overwritten, _w = _track(p)
        seen += _s
        wiped += _w
    left: dict[str, list[str]] = {"others": [], "common": [], "not_removed": []}
    removed_at_rmtree = False
    kept_items = 0
    if app_only:
        _remove_app_folders(roots)
        left = _left_entries(base)
        kept_items = len(left["others"])
    elif keys_foreign and _kind(keys_dir) != "absent":
        # R806 (2): the data folder is kept because it holds items the app did not create (in keys); every other entry of it goes.
        _remove_app_folders([Path(e.path) for e in _listing(base, _unlisted) if Path(e.path) != keys_dir])
        kept_items = _kept_in_keys(keys_dir)
        # Kept ON PURPOSE for keys only: anything else still there is a removal that failed, said as that (never hidden by "kept").
        left["not_removed"] = sorted(e.name for e in _listing(base) if Path(e.path) != keys_dir)
    else:
        with contextlib.suppress(OSError):
            shutil.rmtree(base, ignore_errors=True)
        removed_at_rmtree = not _present(base)  # before any log line: one that makes it again then reads "came back", never "not removed"
    # Kept ON PURPOSE: in shared scope for the entries that are not the app's (R711), else for a keys folder that is not (R806).
    kept_foreign = _present(base) and (bool(kept_items) if app_only else keys_foreign and _kind(keys_dir) != "absent")
    # An app key or private copy still in a kept keys folder (its unlink failed), or a ``.pending`` that is a link the app's
    # copies may have gone through: never hidden by "kept", said as not removed (R806 / R807; the delta security reads).
    if kept_foreign or app_only:
        left["not_removed"] = sorted({*left["not_removed"], *_app_keys_left(keys_dir)})

    overwrite_failures[:] = list(dict.fromkeys(overwrite_failures))  # a file failing in two steps is named once
    unlisted_folders[:] = list(dict.fromkeys(unlisted_folders))  # 5b and 6 walk the same folders
    # The log names no path whole (R734/R736): each is written as its role, and one that cannot be read as such is withheld.
    if unlisted_folders:
        _LOG.error(
            "CRYPTO-ERASE: could not check %d folder(s) it could not list; the erase may be incomplete: %s",
            len(unlisted_folders),
            _masked(unlisted_folders, base),
        )
    if keys_link:
        _LOG.error("CRYPTO-ERASE: the keys folder is a link, which the erase never follows: the app's key files may be where it points "
                   "and were not destroyed; the erase may be incomplete")
    if overwrite_failures:
        _LOG.error(
            "CRYPTO-ERASE: %d file(s) could NOT be overwritten (only unlinked, if that): %s",
            len(overwrite_failures),
            _masked(overwrite_failures, base),
        )
    _LOG.warning(
        "CRYPTO-ERASE executed on %s (encrypted=%s, %d/%d files, %d headers, %d keys, "
        "%d overwrite failures)",
        _masked([str(base)], base)[0],
        encrypted,
        wiped,
        seen,
        len(headers),
        len(keys_destroyed),
        len(overwrite_failures),
    )
    return {
        "phase": "crypto-erase",
        "data_dir": str(base),
        "files_seen": seen,
        "files_wiped": wiped,
        "headers_destroyed": headers,
        "other_heads_destroyed": heads_elsewhere,
        "keys_destroyed": keys_destroyed,
        "overwrite_failures": overwrite_failures,
        "passphrase_cleared": passphrase_cleared,
        "encrypted_corpus": encrypted,
        "copies_destroyed": copies_destroyed,
        # R711: "data-folder" removes the folder whole; "app-only" reached only the app's own entries in a folder it does not
        # own. Names only, never read: ``left_untouched`` the entries that are not the app's, ``left_common_names`` the app's
        # common names left because they may be the operator's, ``not_removed`` the app's own whose removal failed.
        "scope": "app-only" if app_only else "data-folder",
        "scope_reason": scope["reason"],
        "left_untouched": left["others"],
        "left_common_names": left["common"],
        "not_removed": left["not_removed"],
        "removed": not _present(base),
        "removed_at_rmtree": removed_at_rmtree,
        # R806 (4): the folder was kept ON PURPOSE because it holds items the app did not create (a count, never their names), so
        # the report says "folder kept because it holds items the app did not create", never "could not be removed" or "destroyed".
        "keys_folder": keys_state,
        "folder_kept_foreign": kept_foreign,
        "kept_items": kept_items,
        "keys_link": keys_link,
        # R798: a count, the paths stay in overwrite_failures (this report, never a log); any one makes the result not clean.
        "unlisted_folders": len(unlisted_folders),
        # R805 (a): this process's own connections on the store still open when the erase ran (None: could not tell).
        "own_connections_open": own_open,
        "limit": (_NOT_REMOVED_SENTENCE + " " if kept_foreign and left["not_removed"] else "")
        + (_LIMIT_NOTE_UNLISTED if unlisted_folders else _LIMIT_NOTE),
    }


#: R797 / R805 (c)3: what the free-space scrub always leaves free, so it never fills to zero a drive the operator shares with other data.
_DISK_RESERVE = 64 * 1024 * 1024
#: The prefix of the scrub's private folder (also an app-owned name in ``data_scope``).
_SCRUB_PREFIX = ".oo_scrub_"


def _free_bytes(folder: Path) -> int | None:
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def _fill_free_space(path: Path, cap: int | None) -> int:
    """Write random data to ``path`` until the volume has only :data:`_DISK_RESERVE` free (or ``cap`` bytes, a
    test-only bound), fsync, and return the bytes written. Best-effort; a volume whose free space cannot be read is not written."""
    written = 0
    try:
        with open(path, "wb", buffering=0) as f:
            while cap is None or written < cap:
                n = _CHUNK if cap is None else min(_CHUNK, cap - written)
                free = _free_bytes(path.parent)
                if free is None:
                    break
                n = min(n, free - _DISK_RESERVE)  # R805 (c)3: never past the reserve
                if n <= 0:
                    break
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


def _is_real_dir(p: Path) -> bool:
    """A folder itself, never a link to one (lstat; a Windows junction is a link here too)."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    junction = getattr(os.path, "isjunction", None)
    return stat.S_ISDIR(st.st_mode) and not (junction is not None and junction(p))


def _real_own_folder(p: Path) -> bool:
    """R799's conditions: a real folder (never a link), this user's own where that can be asked."""
    if not _is_real_dir(p):
        return False
    getuid = getattr(os, "getuid", None)
    try:
        return getuid is None or os.lstat(p).st_uid == getuid()
    except OSError:
        return False


def _sweep_crash_left_scrubs(where: Path) -> None:
    """R805 (c)2: a scrub folder a crash left in ``where`` (app prefix, a real folder, this user's own) is removed; nothing else."""
    try:
        names = [e.name for e in os.scandir(where) if e.name.startswith(_SCRUB_PREFIX)]
    except OSError:
        return
    for name in names:
        p = where / name
        if _real_own_folder(p):
            shutil.rmtree(p, ignore_errors=True)


#: Why the free space was not overwritten (R805 (c)1/2; R798 style: "could not", never a success). The UI words each ×12.
SCRUB_NOT_DONE = ("other_drive", "drive_unread", "no_folder", "nothing_written")


def full_secure_erase(
    passes: int = 1, *, base_dir: Path | None = None, _cap_bytes: int | None = None
) -> dict:
    """Optional defence-in-depth free-space scrub of the corpus volume.

    Run AFTER ``quick_crypto_erase`` (which already unlinked the files): fills the
    volume's free space with random data ``passes`` times so the freed ciphertext
    blocks are overwritten, always leaving :data:`_DISK_RESERVE` free. ``passes`` must be 1, 3, or 8 (Single/Triple/Octuple).
    ``base_dir`` chooses where the fill files land (defaults to the data dir, i.e.
    the corpus volume). ``_cap_bytes`` is a TEST-ONLY per-pass byte cap so the suite
    never has to fill a real disk.

    R802/R805 (c): the erased data folder is never made again. The fill files go in a private folder (``mkdtemp``, mode 0700) made in
    the data folder while it is there (a folder the erase kept), else in the nearest folder above it that is there, and only on the
    drive that held the data folder (its device, read when the erase latched it); never through a link. When no such folder can be
    used, the free space is NOT overwritten and ``scrub_not_done`` says why. The private folder is removed on every way out, and a
    crash-left one only under R799's conditions. ``scrub_folder`` is the folder it was made in, shown to the operator."""
    if passes not in _ALLOWED_PASSES:
        raise ValueError(f"passes must be one of {_ALLOWED_PASSES}, got {passes!r}")

    from src.paths import data_dir_path, erase_owned, erased_device, erased_folder_of

    if base_dir is not None:
        base = Path(base_dir)
    else:
        from src.paths import data_dir

        # R802: the folder the panic erase latched is never made again, so it is named, not asked for.
        base = data_dir_path() if erased_folder_of(data_dir_path()) else data_dir()
    latched = erased_folder_of(base)
    if not latched:
        base.mkdir(parents=True, exist_ok=True)
    where = base
    while not where.is_dir() and where.parent != where:
        where = where.parent
    not_done: str | None = None
    if latched:
        dev = erased_device(base)
        try:
            here = os.stat(where).st_dev
        except OSError:
            here = None
        if dev is None or here is None:
            not_done = "drive_unread"
        elif here != dev:
            not_done = "other_drive"  # the data folder was a mount point: the folder above is another drive
    if not_done is None and not _is_real_dir(where):
        not_done = "no_folder"  # never through a link: the fill files would land wherever it leads
    total = 0
    scrub_dir: Path | None = None
    left_behind = False
    if not_done is None:
        with erase_owned() if latched else contextlib.nullcontext():  # the scrub's own private files, on this thread
            _sweep_crash_left_scrubs(where)
            try:
                scrub_dir = Path(tempfile.mkdtemp(prefix=_SCRUB_PREFIX, dir=where))
            except OSError:
                not_done = "no_folder"
            if scrub_dir is not None:
                try:
                    for i in range(passes):
                        fill = scrub_dir / f"scrub_{i}.bin"
                        total += _fill_free_space(fill, _cap_bytes)
                        with contextlib.suppress(OSError):
                            fill.unlink()
                finally:  # every way out, an interrupt included
                    shutil.rmtree(scrub_dir, ignore_errors=True)
                    left_behind = os.path.lexists(scrub_dir)
            if not_done is None and total == 0:
                not_done = "nothing_written"  # a full drive, a free space that could not be read, a fill file that could not be made

    _LOG.warning("SECURE-ERASE scrub on %s (%d passes, %d bytes total)", _masked([str(base)], base)[0], passes, total)
    return {
        "phase": "free-space-scrub",
        "data_dir": str(base),
        "passes": passes,
        "bytes_written": total,
        # R802: "data-folder", "above-data-folder" (the erased folder is not made again for the scrub) or "none".
        "scrub_location": "none" if scrub_dir is None else ("data-folder" if where == base else "above-data-folder"),
        # R805 (c)4: the folder the private scrub folder was made in, shown as a plain path (it may be outside the data folder).
        "scrub_folder": None if scrub_dir is None else str(where),
        # R805 (c)1: why the free space was not overwritten (one of SCRUB_NOT_DONE), never a scrubbed claim then.
        "scrub_not_done": not_done,
        # The private folder when it could not be removed (shown as a plain path, to remove by hand); None when it was.
        "scrub_folder_left": str(scrub_dir) if (scrub_dir is not None and left_behind) else None,
        "reserve_bytes": _DISK_RESERVE,
        "limit": _LIMIT_NOTE,
    }
