"""
Cross-process lock and atomic replace for the files several servers share (R176).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: a file the server appends to, trims or rewrites (a journal, a ledger, a state file) was protected only by a lock inside ONE process, and about sixty of them
were rewritten through one fixed ``<name>.tmp``. Two servers on one data folder (R176 allows that) could lose an appended line to the other's trim, or leave a
half file when both wrote the one temp name.

Now a writer takes :func:`file_lock` on ``<name>.lock`` (a sidecar that is never deleted, so there is no stale-lock case: the kernel releases the lock when the
holder ends by any means) and replaces the file through :func:`atomic_replace` (a temp named for the process and the thread, flushed, then ``os.replace``). An
append takes the lock SHARED (appends of one line do not tear on the filesystems measured, and a trim waits for them); a trim or a read-modify-write takes it
EXCLUSIVE.

What it does not do: it does not stop two servers doing the same JOB twice, or fighting over one job's state; the database write gates stay per process (R176).
Where the filesystem cannot lock (some network and FUSE mounts) the section runs UNLOCKED with a unique temp and ONE warning that names the file and says so.
Windows (``msvcrt.locking``, exclusive only, polled with ``LK_NBLCK`` because ``LK_LOCK`` has a hidden ten-second give-up) was written from its documentation and
never run here. There is no fixed timeout: a wait ends when the holder lets go; :func:`stats` reports the longest wait and hold seen per file name so a test can
pin them.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

#: How long a waiter sleeps between two non-blocking attempts at the operating-system lock, in seconds. It is a poll interval, not a limit: a wait has no end
#: but the holder letting go. 50 ms keeps a waiter's cost under a thousandth of a core.
_POLL_S = 0.05
_SIDECAR = ".lock"

_UNLOCKED_WARNED: set[str] = set()
_STATS: dict[str, dict[str, float]] = {}
_REGISTRY_LOCK = threading.Lock()


@dataclass
class _Local:
    """What this process knows of one lock file: how many hold it and in which mode."""

    cond: threading.Condition
    readers: int = 0
    writer: int | None = None  # thread ident of the exclusive holder
    reader_threads: set[int] | None = None


_LOCALS: dict[str, _Local] = {}


@dataclass
class Held:
    """What :func:`file_lock` yields: whether the operating-system lock is really held. ``reason`` says why not."""

    locked: bool
    reason: str | None = None


def _local(key: str) -> _Local:
    with _REGISTRY_LOCK:
        got = _LOCALS.get(key)
        if got is None:
            got = _Local(cond=threading.Condition(threading.RLock()), reader_threads=set())
            _LOCALS[key] = got
        return got


def _contended(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK)


def _try_os_lock(fd: int, shared: bool) -> None:
    """One non-blocking attempt. Raises a contention ``OSError`` when another process holds it, any other ``OSError`` when the filesystem cannot lock."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]  # exclusive only: a "shared" section is exclusive here
    else:
        import fcntl

        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)


def _release_os_lock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _warn_unlocked(path: Path, why: str) -> None:
    """One warning per file NAME. The name only, never the folder: a path can carry a user name, and the warning must carry nothing else."""
    name = path.name
    with _REGISTRY_LOCK:
        if name in _UNLOCKED_WARNED:
            return
        _UNLOCKED_WARNED.add(name)
    # To stderr, not through ``logging``: the journal's own handler writes THIS file, so a warning about it would re-enter the section that raised it.
    with contextlib.suppress(Exception):
        sys.stderr.write(f"file lock: {name} runs UNLOCKED ({why}); a second server on this folder could lose a line to it\n")
        sys.stderr.flush()


def _note(name: str, field: str, seconds: float) -> None:
    with _REGISTRY_LOCK:
        row = _STATS.setdefault(name, {"max_wait_s": 0.0, "max_hold_s": 0.0})
        if seconds > row[field]:
            row[field] = seconds


def stats() -> dict[str, dict[str, float]]:
    """The longest wait and the longest hold seen per file name since the process began (seconds). Absent until a lock on that file was taken."""
    with _REGISTRY_LOCK:
        return {k: dict(v) for k, v in _STATS.items()}


@contextlib.contextmanager
def file_lock(path: Path, *, shared: bool = False) -> Iterator[Held]:
    """Hold ``<path>.lock`` for the body: exclusive by default, shared with ``shared=True`` (appends). Not re-entrant: taking it again in the same thread raises
    ``RuntimeError`` rather than deadlocking.

    Everything that can fail is inside the ``try`` that releases, so an interrupt at any line leaves nothing held."""
    path = Path(path)
    sidecar = path.with_name(path.name + _SIDECAR)
    key = str(sidecar)
    me = threading.get_ident()
    loc = _local(key)
    fd: int | None = None
    held = Held(locked=False, reason="not taken")
    in_local = False
    began = time.monotonic()
    got_at = began
    try:
        with loc.cond:
            while True:
                if loc.writer == me or (loc.reader_threads is not None and me in loc.reader_threads):
                    raise RuntimeError("file_lock is not re-entrant: this thread already holds it")
                if loc.writer is None and (shared or loc.readers == 0):
                    break
                loc.cond.wait(_POLL_S)
            if shared:
                loc.readers += 1
                assert loc.reader_threads is not None
                loc.reader_threads.add(me)
            else:
                loc.writer = me
            in_local = True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(sidecar, os.O_RDWR | os.O_CREAT, 0o600)  # not inheritable (PEP 446)
        except OSError as exc:
            held = Held(locked=False, reason=f"the lock file could not be opened ({type(exc).__name__})")
            _warn_unlocked(path, held.reason or "")
        if fd is not None:
            while True:
                try:
                    _try_os_lock(fd, shared)
                    held = Held(locked=True)
                    break
                except OSError as exc:
                    if not _contended(exc):
                        held = Held(locked=False, reason=f"the filesystem could not lock ({type(exc).__name__})")
                        _warn_unlocked(path, held.reason or "")
                        break
                time.sleep(_POLL_S)
        got_at = time.monotonic()
        _note(path.name, "max_wait_s", got_at - began)
        yield held
    finally:
        _note(path.name, "max_hold_s", time.monotonic() - got_at)
        if fd is not None:
            if held.locked:
                with contextlib.suppress(OSError):
                    _release_os_lock(fd)
            with contextlib.suppress(OSError):
                os.close(fd)
        if in_local:
            with loc.cond:
                if shared:
                    loc.readers -= 1
                    assert loc.reader_threads is not None
                    loc.reader_threads.discard(me)
                else:
                    loc.writer = None
                loc.cond.notify_all()


def temp_name(path: Path) -> Path:
    """``<name>.tmp.<pid>.<thread>``: no two writers share one, and the owner can be told from the name."""
    return path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")


def sweep_dead_temps(path: Path) -> None:
    """Remove ``<name>.tmp.<pid>.<thread>`` left by a process that no longer runs. Where that cannot be told (no psutil) nothing is removed."""
    try:
        import psutil

        for old in path.parent.glob(path.name + ".tmp.*"):
            pid = old.name.rsplit(".tmp.", 1)[1].split(".")[0]
            if pid.isdigit() and int(pid) != os.getpid() and not psutil.pid_exists(int(pid)):
                old.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001, S110 - a sweep never breaks the writer
        pass


def atomic_replace(path: Path, data: str | bytes, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    """Write ``data`` to a unique temp beside ``path``, flush it, and move it over ``path``. The caller holds :func:`file_lock` when the new content depends on
    the old. A failure leaves the old file whole and removes the temp."""
    path = Path(path)
    tmp = temp_name(path)
    try:
        fh = tmp.open("wb") if isinstance(data, bytes) else tmp.open("w", encoding=encoding, newline=newline)
        with fh as f:
            f.write(data)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    sweep_dead_temps(path)


def locked_append(path: Path, text: str, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    """Append ``text`` under a SHARED lock (a trim holds it exclusive, so no append lands between the trim's read and its swap)."""
    path = Path(path)
    with file_lock(path, shared=True), path.open("a", encoding=encoding, newline=newline) as f:
        f.write(text)
