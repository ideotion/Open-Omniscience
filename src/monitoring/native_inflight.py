"""Which native code was running when the process died: a 128-byte memory-mapped counter file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Six of the ten SIGABRTs left no trace, and three of the four traces open with a thread Python did not create. Nothing
recorded WHICH native library was executing. A debugger on the user's machine is not available, and ``abort()`` leaves no chance to
run Python. A plain write into a memory-mapped file is different: it is an ordinary store into the kernel's page cache, so it
survives ``abort()``, ``SIGKILL`` and an out-of-memory kill, and the next boot can read what the last store said.

WHAT IS RECORDED. A few call sites that enter native code (``dns`` and ``connect`` in the socket guard; ``lxml`` and ``duckdb`` are
wired by the modules that own those calls) bracket the call with :func:`native_call`. The file holds, per slot, how many such
calls were IN FLIGHT at the last write and how many were ever entered, plus the pid, the machine boot id and the time of the last
write. Only counts: no host, URL, statement or text is written, so there is nothing to scrub.

WHAT IT IS NOT. A count at the LAST WRITE before the process ended, so a LOWER BOUND on what was running (a call that began after
the last store is not in it, and a store is skipped when the file could not be opened). It says which wired slots had a call open,
not which thread aborted. "No wired slot in flight" is its own outcome and says the abort ran in code nobody has wired (SQLite,
numpy, OpenSSL internals, ...): it is not an absence of data. The file is the PREVIOUS session's only when its pid and boot id
match that session's; a file from another pid or boot is reported as such and its counts are never shown.

NEVER RAISES, never blocks a call: if the file cannot be created or mapped the context manager is a no-op and the report says
``unavailable``.
"""

from __future__ import annotations

import contextlib
import mmap
import os
import struct
import threading
import time
from struct import (
    error as _StructError,  # a bare name: the record-sink scan reads ``struct.error`` as a log-call attribute it cannot read
)
from typing import Any

#: Slot names, by position. A slot is added by appending, never by reordering (the file is read by the next build). ``None`` is a
#: reserved slot. Four are wired today by their owners; the rest are spare.
SLOTS: tuple[str | None, ...] = ("dns", "connect", "lxml", "duckdb", None, None, None, None)

FILE_NAME = "native_inflight.bin"
_MAGIC = b"OONIF001"
_VERSION = 1
_BOOT_LEN = 36
#: magic 8 | version u32 | pid u32 | boot id 36 | last write u64 (epoch seconds) | per slot: in flight u32, entered u32
_HEAD = struct.Struct(f"<8sII{_BOOT_LEN}sQ")
_SLOT = struct.Struct("<II")
SIZE = 128
assert _HEAD.size + len(SLOTS) * _SLOT.size <= SIZE

#: How much of the session-forensics headroom this report may use, in serialised bytes WITH its ``"native_in_flight":`` key (a worst case is
#: pinned by a test): 181 measured with all four slots at their largest, the as-of time and ``boot_unchecked``.
REPORT_BYTES_BUDGET = 181

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"map": None, "file": None, "failed": False, "previous": None, "captured": False}


def _path() -> str:
    from src.paths import data_dir

    return str(data_dir() / "diagnostics" / FILE_NAME)


def _boot_id() -> str:
    try:
        from src.monitoring.session_history import machine_boot_id

        return machine_boot_id() or ""
    except Exception:  # noqa: BLE001 - an unknown boot is recorded as empty, and compared as unknown
        return ""


def _capture_previous(path: str) -> None:
    """Keep the bytes the PREVIOUS process left, once, before this process truncates the file."""
    if _STATE["captured"]:
        return
    _STATE["captured"] = True
    try:
        with open(path, "rb") as fh:
            _STATE["previous"] = fh.read(SIZE)
    except FileNotFoundError:
        _STATE["previous"] = None
    except OSError:
        _STATE["previous"] = b""  # a file that is there and cannot be read is "unreadable", not "absent"


def _open_locked() -> mmap.mmap | None:
    if _STATE["map"] is not None or _STATE["failed"]:
        return _STATE["map"]
    try:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _capture_previous(path)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.ftruncate(fd, SIZE)
            mm = mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)
        mm[:] = b"\x00" * SIZE
        _HEAD.pack_into(mm, 0, _MAGIC, _VERSION, os.getpid(), _boot_id().encode("ascii", "replace")[:_BOOT_LEN], int(time.time()))
        _STATE["map"] = mm
        return mm
    except (OSError, ValueError, _StructError):
        _STATE["failed"] = True
        return None


def _bump(slot: int, delta: int) -> None:
    with _LOCK:
        mm = _open_locked()
        if mm is None:
            return
        off = _HEAD.size + slot * _SLOT.size
        flight, entered = _SLOT.unpack_from(mm, off)
        if delta > 0:
            entered = (entered + 1) & 0xFFFFFFFF
        flight = max(0, flight + delta) & 0xFFFFFFFF
        _SLOT.pack_into(mm, off, flight, entered)
        struct.pack_into("<Q", mm, _HEAD.size - 8, int(time.time()))


class native_call(contextlib.AbstractContextManager):  # noqa: N801 - used as a bare context manager at call sites
    """``with native_call("dns"): ...`` brackets a call into native code. Never raises, never swallows the body's exception."""

    __slots__ = ("_slot",)

    def __init__(self, name: str) -> None:
        try:
            self._slot = SLOTS.index(name)
        except ValueError:
            self._slot = -1

    def __enter__(self) -> None:
        if self._slot >= 0:
            with contextlib.suppress(Exception):
                _bump(self._slot, 1)

    def __exit__(self, *exc: object) -> None:
        if self._slot >= 0:
            with contextlib.suppress(Exception):
                _bump(self._slot, -1)


def start() -> None:
    """Called once at boot: keep the previous process's bytes, then open this process's file. Without this the file is made by the first
    wired call, and a session that died before entering one would leave NO file, which reads the same as a build that wires nothing:
    "no wired call was ever entered" is an outcome only if the file exists from the start. Never raises."""
    with _LOCK, contextlib.suppress(Exception):
        _open_locked()


def capture_previous_now() -> None:
    """Preserve the previous process's file before anything of this process's can replace it. Called at boot; also done by the
    first :func:`native_call`, so the order of the two cannot lose it."""
    with _LOCK, contextlib.suppress(Exception):
        _capture_previous(_path())


def read_record(raw: bytes | None) -> dict[str, Any] | None:
    """Decode one file's bytes; None when it is absent, short, or not this format/version."""
    if not raw or len(raw) < _HEAD.size + len(SLOTS) * _SLOT.size:
        return None
    try:
        magic, version, pid, boot, wrote = _HEAD.unpack_from(raw, 0)
        if magic != _MAGIC or version != _VERSION:
            return None
        slots = [_SLOT.unpack_from(raw, _HEAD.size + i * _SLOT.size) for i in range(len(SLOTS))]
    except _StructError:
        return None
    return {"pid": pid, "boot": boot.rstrip(b"\x00").decode("ascii", "replace"), "wrote": wrote, "slots": slots}


_PREVIOUS: Any = object()


def report(pid: int | None, boot_id: str | None, raw: Any = _PREVIOUS) -> dict[str, Any]:
    """What the previous session's file says, as a small dict whose ``result`` names the outcome:

    * ``in-flight``: native calls were open at the last write; ``counts`` has the non-zero slots (a lower bound).
    * ``none-in-flight``: the file was written and no wired slot had a call open; ``calls_entered`` is how many were ever entered.
    * ``no-calls-recorded``: the file is this session's and no wired slot was ever entered (nothing ran through them, or they are
      not wired in that build).
    * ``other-session`` / ``unreadable`` / ``absent`` / ``unavailable``: nothing about the session is claimed.
    ``as_of`` is the time of the last write (UTC, seconds)."""
    if raw is _PREVIOUS:
        raw = _STATE["previous"]
        if raw is None and not _STATE["captured"]:
            capture_previous_now()
            raw = _STATE["previous"]
    if raw is None:
        return {"result": "absent"}
    rec = read_record(raw)
    if rec is None:
        return {"result": "unreadable"}
    if not isinstance(pid, int) or isinstance(pid, bool) or rec["pid"] != pid:
        return {"result": "other-session", "why": "pid differs"}
    boot_known = bool(boot_id) and bool(rec["boot"])
    if boot_known and rec["boot"] != boot_id:
        return {"result": "other-session", "why": "boot differs"}
    out: dict[str, Any] = {}
    flight = {SLOTS[i]: s[0] for i, s in enumerate(rec["slots"]) if SLOTS[i] and s[0]}
    entered = sum(s[1] for i, s in enumerate(rec["slots"]) if SLOTS[i])
    from datetime import UTC, datetime

    try:
        as_of = datetime.fromtimestamp(rec["wrote"], tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        as_of = None
    if flight:
        out = {"result": "in-flight", "counts": flight}
    elif entered:
        out = {"result": "none-in-flight", "calls_entered": entered}
    else:
        out = {"result": "no-calls-recorded"}
    out["as_of"] = as_of
    if not boot_known:
        out["boot_unchecked"] = True
    return out


def _reset_for_tests() -> None:
    with _LOCK:
        mm = _STATE["map"]
        if mm is not None:
            with contextlib.suppress(Exception):
                mm.close()
        _STATE.update({"map": None, "file": None, "failed": False, "previous": None, "captured": False})
