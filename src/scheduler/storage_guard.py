"""The storage guard: pause collection LOUDLY before a pinned WAL or a full drive.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (field diagnostics of 16 instances, 2026-09-30, ranks 1, 2 and 6). The
corpus's ``-wal`` file reached 18.7 to 42.9 GB on six of sixteen machines against a 64 MiB
resting limit, the data drive filled on three of them, and the collector kept starting passes
on a drive that could not take them (one machine logged no successful pass for 35 hours, each
pass failing on the same full disk). Nothing on main capped the WAL or stopped before the disk
filled; the 64 MiB ``journal_size_limit`` only applies when a WAL RESET happens.

WHY A STOP, AND NOT A BETTER CHECKPOINT (measured, ``tests/test_wal_pin_facts.py``). A WAL is
reset only when no reader holds a snapshot taken while it had un-backfilled frames. While one
does, ``PRAGMA wal_checkpoint(PASSIVE)`` backfills only up to that reader's mark (97 of 7,554
frames in the bench), ``TRUNCATE`` comes back busy, and the file grows by APPENDING for as long
as writers write. Nothing inside the process can evict a foreign reader. Once the reader ends,
one ``TRUNCATE`` takes the file to zero. So the only lever that bounds the FILE is to stop
appending until the reader ends, and then reset. That is this guard; it mirrors the memory
guard (``memguard.py``): it pauses, loudly, resumably, and never touches the writer gate from
a worker.

It does not change the boundary checkpoint (PASSIVE then TRUNCATE at busy timeout 0) or
``wal_autocheckpoint``: the ledger defers replacing those (MEASURE FIRST) and this adds no
checkpoint of its own beyond the DRAIN below, which is the same call the boundary makes.

WHAT IT WATCHES, every few seconds, from two readings that touch no table:

* **WAL**: the size of the corpus ``-wal`` file. Engages when it stays at or above ``wal_high``.
* **DISK**: free bytes on the drive holding the corpus. Engages when they fall below
  ``disk_reserve``, or at once when a write fails with "disk is full" (ENOSPC).

WHAT EACH NUMBER PROTECTS (derived from the machine, never a constant of its own; the two
overrides exist for an operator who knows better):

* ``wal_high = min(clamp(10% of the corpus file, 512 MiB, 2 GiB), 10% of free disk)``
  (``OO_WAL_HIGH_MB`` overrides).
    - the 512 MiB floor protects NORMAL operation: SQLite's own autocheckpoint keeps a healthy
      WAL near 16 MiB, so this never fires on a machine whose WAL resets;
    - the 2 GiB ceiling protects the NEXT UNLOCK: boot recovers every frame the last session
      left, at the measured 5.0 to 39.2 s per GiB, so the ceiling costs 10 to 78 s there;
    - the 10%-of-corpus term scales a large corpus's allowance with it;
    - the 10%-of-free-disk term protects the DRIVE: a WAL is never allowed to take more than a
      tenth of what is left;
    - never below 128 MiB, so a tiny drive does not make the guard fire on a healthy WAL.
* ``disk_reserve = max(1 GiB, 2% of the drive)`` (``OO_DISK_RESERVE_MB`` overrides): the floor
  covers the writes still in flight while a pass winds down plus the pass-tail records; the
  percentage grows with the machine.
* RESUME has margin so it never flaps: the WAL at or below half of ``wal_high`` (a successful
  reset is zero), free disk at or above 1.5 x the reserve.
* ``trip_after`` = 2 consecutive samples, so one brushed reading (a big legitimate
  transaction in flight) cannot pause collection.

HONESTY BY CONSTRUCTION. Measured readings only: an unreadable figure is ``None`` and never
trips anything (and never reads as recovery). The state carries the numbers and the method. An
engaged guard says WHY in plain words and that it RESUMES BY ITSELF. It is not a security
feature and claims none.

NEVER BLOCKS. Consumers call :meth:`StorageGuard.admit` (a non-blocking read of the latch)
BEFORE taking on new work; in-flight work always finishes. The supervisor thread is the only
thing that samples the drive or drains the WAL, so no worker does I/O on the guard's behalf.

``OO_STORAGE_GUARD=0`` disables it entirely.
"""

from __future__ import annotations

import errno
import logging
import os
import threading
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("scheduler.storage_guard")

MIB = 1024 * 1024
GIB = 1024 * MIB

# --- what each number protects (see the module docstring) ---------------------------
WAL_FLOOR_BYTES = 512 * MIB
WAL_CEILING_BYTES = 2 * GIB
WAL_ABSOLUTE_MIN_BYTES = 128 * MIB
WAL_CORPUS_FRACTION = 0.10
WAL_FREE_FRACTION = 0.10
WAL_RESUME_FACTOR = 0.5
DISK_RESERVE_FLOOR_BYTES = 1 * GIB
DISK_RESERVE_FRACTION = 0.02
DISK_RESUME_FACTOR = 1.5
#: After a write FAILED for want of space, hold the stop at least this long even if the free
#: figure looks healthy (quota, inode exhaustion, a figure that lags the failure): otherwise a
#: drive that says "free" but refuses writes would flap at pass cadence.
ERROR_HOLD_S = 300.0
#: The in-memory history: one sample a minute for six hours. Process-scoped, never persisted
#: (the hourly ``disk_free_mib`` and ``wal_bytes`` gauges carry the long series).
HISTORY_EVERY_S = 60.0
HISTORY_KEEP = 360
#: Naming the holders is a stack capture; once a minute at most.
PIN_REPORT_EVERY_S = 60.0
DRAIN_EVERY_S = 10.0

PHASE_WAL = "paused-wal-pinned"
PHASE_DISK = "paused-low-disk"

#: The plain-words sentences, as frames the page fills with the numbers in its own
#: language (the pattern of ``estimate_method_i18n``). Each is also a locale key, x12.
FRAME_WAL = (
    "Collection is paused: the database's write-ahead log has grown to {size} (this "
    "machine's limit is {limit}) because something is holding a read open. Collection "
    "resumes by itself as soon as that read ends."
)
FRAME_DISK = (
    "Collection is paused: only {free} is free on the data drive (this machine's reserve is "
    "{reserve}). Collection resumes by itself once about {resume} is free. Free some space "
    "or move the data folder."
)


def _env_mb(name: str) -> int | None:
    try:
        v = int(float(os.getenv(name, "") or 0))
    except (TypeError, ValueError):
        return None
    return v * MIB if v > 0 else None


def wal_high_bytes(corpus_bytes: int | None, free_bytes: int | None) -> int:
    """The WAL size at which collection pauses, sized from THIS machine (see the docstring)."""
    override = _env_mb("OO_WAL_HIGH_MB")
    if override is not None:
        return override
    base = WAL_FLOOR_BYTES
    if corpus_bytes:
        base = int(min(max(corpus_bytes * WAL_CORPUS_FRACTION, WAL_FLOOR_BYTES), WAL_CEILING_BYTES))
    if free_bytes is not None:
        base = min(base, int(free_bytes * WAL_FREE_FRACTION))
    return max(base, WAL_ABSOLUTE_MIN_BYTES)


def disk_reserve_bytes(total_bytes: int | None) -> int:
    """The free space below which collection pauses, sized from THIS machine's drive."""
    override = _env_mb("OO_DISK_RESERVE_MB")
    if override is not None:
        return override
    if total_bytes:
        return int(max(DISK_RESERVE_FLOOR_BYTES, total_bytes * DISK_RESERVE_FRACTION))
    return DISK_RESERVE_FLOOR_BYTES


def is_disk_full(exc: BaseException | None) -> bool:
    """Whether an exception (or anything in its chain) is the drive running out of space.

    Walks ``__cause__``/``__context__`` and SQLAlchemy's ``.orig``: the failure surfaces as
    ``OperationalError: database or disk is full`` (SQLITE_FULL), ``OSError`` errno 28 from a
    plain file write, or a quota. A message match is deliberate for the SQLite driver, which
    raises its own ``OperationalError`` without an errno.
    """
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError) and cur.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
            return True
        msg = str(cur).lower()
        if (
            "database or disk is full" in msg
            or "no space left on device" in msg
            or "disk quota exceeded" in msg
        ):
            return True
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return False


def _si(n: float | int | None) -> str:
    """Decimal SI size for the English log line ("1.2 GB"); ``?`` when unreadable."""
    if n is None:
        return "?"
    n = float(n)
    for unit, step in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= step:
            return f"{n / step:.1f} {unit}" if n < 100 * step else f"{n / step:.0f} {unit}"
    return f"{n:.0f} B"


def read_storage() -> dict[str, Any]:
    """One measured reading of the corpus WAL, the corpus file and the drive.

    Stats only (no table, no connection, no lock), so it is safe on any thread and before
    an encrypted store is unlocked. Every figure that cannot be read is ``None``.
    """
    out: dict[str, Any] = {
        "wal_bytes": None,
        "corpus_bytes": None,
        "disk_free_bytes": None,
        "disk_total_bytes": None,
        "lane_wal_bytes": {},
    }
    try:
        from src.database.session import engine

        if engine.url.get_backend_name() != "sqlite":
            return out
        db_file = engine.url.database
        if not db_file or db_file == ":memory:":
            return out
        path = Path(db_file)
        try:
            out["wal_bytes"] = Path(str(db_file) + "-wal").stat().st_size
        except FileNotFoundError:
            out["wal_bytes"] = 0  # no -wal file on a real store IS a real zero
        except OSError:
            pass
        with suppress(OSError):
            out["corpus_bytes"] = path.stat().st_size
        try:
            for side in path.parent.glob("*-wal"):
                if side.name != path.name + "-wal":
                    out["lane_wal_bytes"][side.name] = side.stat().st_size
        except OSError:
            pass
        from src.config.hardware_reading import disk_bytes

        free, total = disk_bytes(path.parent)
        out["disk_free_bytes"], out["disk_total_bytes"] = free, total
    except Exception:  # noqa: BLE001 - a reading is best-effort, never a crash
        _LOG.debug("storage guard: could not read the drive", exc_info=True)
    return out


def _default_drain() -> dict | None:
    """The same call the pass boundary makes: PASSIVE then TRUNCATE through the write gate,
    the gate wait bounded, busy timeout zero. ``force`` skips only its cadence."""
    from src.scheduler.hygiene import checkpoint_wal

    return checkpoint_wal(force=True)


def _pin_report(drain: dict | None) -> dict[str, Any]:
    """Who holds the WAL, named, with a stack each: the data no bundle has had.

    ``pool_watch`` sees checkouts of the pooled engines; a read that is not a pooled
    checkout cannot be seen from here, and the report says so rather than implying it would.
    Never raises.
    """
    out: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "drain": drain,
        "holders": [],
        "instrument": "unattached",
    }
    try:
        from src.database import pool_watch

        if pool_watch.is_registered():
            out["instrument"] = "attached"
            rows = pool_watch.checked_out()
            out["checkouts"] = len(rows)
            top = rows[:8]
            stacks = pool_watch.stacks_for([r["ident"] for r in top if r.get("ident")])
            out["holders"] = [
                {
                    "thread": r["thread"],
                    "age_s": r["age_s"],
                    "stack": stacks.get(r["ident"], []) if r.get("ident") else [],
                }
                for r in top
            ]
    except Exception:  # noqa: BLE001
        out["instrument"] = "unreadable"
    try:
        from src.database.writer import write_gate_stats

        gate = write_gate_stats()
        out["write_gate"] = {"holder": gate.get("holder"), "held_for_s": gate.get("held_for_s")}
    except Exception:  # noqa: BLE001
        pass
    out["caveat"] = (
        "A read that is not a pooled connection checkout (a read-snapshot engine not yet "
        "watched, a cursor another thread left open on a connection it already returned) "
        "is invisible to this list; an empty list does not mean nobody is reading."
    )
    return out


class StorageGuard:
    """Two trip/resume latches (WAL, DISK) over measured readings, with hysteresis.

    Readings are pulled by the supervisor (:meth:`poll`) and pushed in tests
    (:meth:`observe`). ``readings_fn`` and ``drain_fn`` are injectable so tests drive the
    whole ladder deterministically, with a real SQLite file where the WAL matters.
    """

    def __init__(
        self,
        *,
        readings_fn=None,
        drain_fn=None,
        trip_after: int | None = None,
        resume_after: int | None = None,
        clock=time.monotonic,
    ) -> None:
        self._readings = readings_fn or read_storage
        self._drain = drain_fn or _default_drain
        self.trip_after = _env_int("OO_STORAGE_GUARD_TRIP_AFTER", 2) if trip_after is None else max(1, trip_after)
        self.resume_after = (
            _env_int("OO_STORAGE_GUARD_RESUME_AFTER", 2) if resume_after is None else max(1, resume_after)
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._wal = False
        self._disk = False
        self._wal_over = self._wal_under = 0
        self._disk_over = self._disk_under = 0
        self._since: str | None = None
        self._since_mono: float | None = None
        self._engagements = 0
        self._total_engaged_s = 0.0
        self._peak_wal_while_engaged = 0
        self._disk_full_events = 0
        self._last_disk_full: dict[str, Any] | None = None
        self._hold_until: float | None = None
        self._last: dict[str, Any] = {}
        self._thresholds: dict[str, Any] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_KEEP)
        self._last_hist_mono: float | None = None
        self._last_drain: dict[str, Any] | None = None
        self._last_drain_mono: float | None = None
        self._last_pin_report: dict[str, Any] | None = None
        self._last_pin_mono: float | None = None
        self._drains = 0

    def _reset_for_tests(self) -> None:
        """Back to the boot state (a process-global latch must not leak across tests)."""
        with self._lock:
            self._wal = self._disk = False
            self._wal_over = self._wal_under = self._disk_over = self._disk_under = 0
            self._since = self._since_mono = None
            self._engagements = self._drains = self._disk_full_events = 0
            self._total_engaged_s = 0.0
            self._peak_wal_while_engaged = 0
            self._last_disk_full = None
            self._hold_until = None
            self._last, self._thresholds = {}, {}
            self._history.clear()
            self._last_hist_mono = None
            self._last_drain = self._last_drain_mono = None
            self._last_pin_report = self._last_pin_mono = None

    # -- switches ------------------------------------------------------------------
    @staticmethod
    def enabled() -> bool:
        return os.getenv("OO_STORAGE_GUARD", "1") != "0"

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._wal or self._disk

    def kind(self) -> str | None:
        """``"disk"`` (the more severe, wins), ``"wal"`` or None."""
        with self._lock:
            return "disk" if self._disk else ("wal" if self._wal else None)

    def admit(self) -> str | None:
        """None = start the next unit of work; else ``"disk"`` or ``"wal"``.

        A non-blocking read of the latch: it samples nothing, takes no lock a worker could
        queue on for long, and never raises. Long background writers call it at a chunk
        boundary (the keyword boot recompute is the planned second consumer).
        """
        if not self.enabled():
            return None
        return self.kind()

    def phase(self) -> str | None:
        kind = self.kind()
        return PHASE_DISK if kind == "disk" else (PHASE_WAL if kind == "wal" else None)

    # -- the latches ---------------------------------------------------------------
    def observe(
        self,
        *,
        wal_bytes: int | None = None,
        corpus_bytes: int | None = None,
        disk_free_bytes: int | None = None,
        disk_total_bytes: int | None = None,
        lane_wal_bytes: dict | None = None,
    ) -> bool:
        """Feed one measured sample; returns the engaged state afterwards.

        A ``None`` figure carries no information: it advances neither the trip nor the
        resume counter (never a fabricated pressure OR a fabricated recovery).
        """
        if not self.enabled():
            return False
        high = wal_high_bytes(corpus_bytes, disk_free_bytes)
        reserve = disk_reserve_bytes(disk_total_bytes)
        wal_resume = int(high * WAL_RESUME_FACTOR)
        disk_resume = int(reserve * DISK_RESUME_FACTOR)
        now_mono = self._clock()
        tripped: list[str] = []
        released: list[str] = []
        with self._lock:
            self._last = {
                "wal_bytes": wal_bytes,
                "corpus_bytes": corpus_bytes,
                "disk_free_bytes": disk_free_bytes,
                "disk_total_bytes": disk_total_bytes,
                "lane_wal_bytes": dict(lane_wal_bytes or {}),
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._thresholds = {
                "wal_high_bytes": high,
                "wal_resume_bytes": wal_resume,
                "disk_reserve_bytes": reserve,
                "disk_resume_bytes": disk_resume,
            }
            if self._last_hist_mono is None or now_mono - self._last_hist_mono >= HISTORY_EVERY_S:
                self._last_hist_mono = now_mono
                self._history.append(
                    {"ts": self._last["ts"], "wal_bytes": wal_bytes, "disk_free_bytes": disk_free_bytes}
                )
            was = self._wal or self._disk
            if wal_bytes is not None:
                if not self._wal:
                    if wal_bytes >= high:
                        self._wal_over += 1
                        if self._wal_over >= self.trip_after:
                            self._wal, self._wal_over, self._wal_under = True, 0, 0
                            tripped.append("wal")
                    else:
                        self._wal_over = 0
                else:
                    self._peak_wal_while_engaged = max(self._peak_wal_while_engaged, wal_bytes)
                    if wal_bytes <= wal_resume:
                        self._wal_under += 1
                        if self._wal_under >= self.resume_after:
                            self._wal, self._wal_over, self._wal_under = False, 0, 0
                            released.append("wal")
                    else:
                        self._wal_under = 0
            if disk_free_bytes is not None:
                if not self._disk:
                    if disk_free_bytes < reserve:
                        self._disk_over += 1
                        if self._disk_over >= self.trip_after:
                            self._disk, self._disk_over, self._disk_under = True, 0, 0
                            tripped.append("disk")
                    else:
                        self._disk_over = 0
                else:
                    held = self._hold_until is not None and now_mono < self._hold_until
                    if disk_free_bytes >= disk_resume and not held:
                        self._disk_under += 1
                        if self._disk_under >= self.resume_after:
                            self._disk, self._disk_over, self._disk_under = False, 0, 0
                            self._hold_until = None
                            released.append("disk")
                    else:
                        self._disk_under = 0
            self._account_locked(was, now_mono)
            engaged = self._wal or self._disk
        self._log_transitions(tripped, released)
        return engaged

    def _account_locked(self, was: bool, now_mono: float) -> None:
        """Episode bookkeeping. Caller holds the lock."""
        now = self._wal or self._disk
        if now and not was:
            self._engagements += 1
            self._since = datetime.now(UTC).isoformat(timespec="seconds")
            self._since_mono = now_mono
            self._peak_wal_while_engaged = int(self._last.get("wal_bytes") or 0)
        elif was and not now and self._since_mono is not None:
            self._total_engaged_s += now_mono - self._since_mono
            self._since, self._since_mono = None, None

    def _log_transitions(self, tripped: list[str], released: list[str]) -> None:
        # OUTSIDE the lock: the log handler does file I/O and workers' admit() must never
        # queue behind it (the memory guard's own rule).
        for kind in tripped:
            if kind == "wal":
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (WAL) -- collection pausing: the write-ahead log is "
                    "%s against a limit of %s on this machine; something is holding a read open. "
                    "It resumes by itself when the log resets.",
                    _si(self._last.get("wal_bytes")),
                    _si(self._thresholds.get("wal_high_bytes")),
                )
            else:
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (DISK) -- collection pausing before the drive fills: "
                    "%s free against a reserve of %s. It resumes by itself once about %s is free.",
                    _si(self._last.get("disk_free_bytes")),
                    _si(self._thresholds.get("disk_reserve_bytes")),
                    _si(self._thresholds.get("disk_resume_bytes")),
                )
        for kind in released:
            _LOG.warning("storage guard released (%s recovered) -- collection resumes", kind)

    def note_disk_full(self, detail: str = "a write failed: the drive is full") -> None:
        """A write FAILED for want of space: stop now, without waiting for the next sample.

        Called from the engine's error hook and from the pass's own failure path. It is a
        latch, not a sample: it holds for at least :data:`ERROR_HOLD_S` and releases only when
        free space is healthy too, so a drive that reports room but refuses writes (a quota)
        cannot flap at pass cadence. Never raises.
        """
        if not self.enabled():
            return
        try:
            now_mono = self._clock()
            with self._lock:
                was = self._wal or self._disk
                self._disk_full_events += 1
                self._last_disk_full = {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "detail": str(detail)[:200],
                    "disk_free_bytes": self._last.get("disk_free_bytes"),
                    "wal_bytes": self._last.get("wal_bytes"),
                    "corpus_bytes": self._last.get("corpus_bytes"),
                }
                self._disk = True
                self._disk_over = self._disk_under = 0
                self._hold_until = now_mono + ERROR_HOLD_S
                self._account_locked(was, now_mono)
                first = not was
            if first:
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (DISK) -- a write failed for want of space (%s); "
                    "free %s, WAL %s, corpus %s. Collection pauses until space is free again.",
                    str(detail)[:120],
                    _si(self._last.get("disk_free_bytes")),
                    _si(self._last.get("wal_bytes")),
                    _si(self._last.get("corpus_bytes")),
                )
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            pass

    def note_error(self, exc: BaseException | None, where: str = "") -> bool:
        """Latch DISK when ``exc`` is a full-drive failure; returns whether it was. Never raises."""
        try:
            if is_disk_full(exc):
                self.note_disk_full(f"{where + ': ' if where else ''}{type(exc).__name__}: {exc}")
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def reset(self, *, reason: str = "user action") -> None:
        """Explicit resume (a user pressed start, run-now or resume): a RETRY, never an
        override. The guard re-trips after ``trip_after`` fresh over-threshold samples if the
        WAL is still pinned or the drive still full (an override of a full-disk guard is
        exactly how a pass wedges)."""
        was = False
        now_mono = self._clock()
        with self._lock:
            was = self._wal or self._disk
            self._wal = self._disk = False
            self._wal_over = self._wal_under = self._disk_over = self._disk_under = 0
            self._hold_until = None
            self._account_locked(was, now_mono)
        if was:
            _LOG.warning("storage guard released (%s) -- collection resumes", reason)

    # -- the pull side -------------------------------------------------------------
    def poll(self) -> bool:
        """Take a fresh reading NOW and return the engaged state afterwards."""
        r = self._readings() or {}
        return self.observe(
            wal_bytes=r.get("wal_bytes"),
            corpus_bytes=r.get("corpus_bytes"),
            disk_free_bytes=r.get("disk_free_bytes"),
            disk_total_bytes=r.get("disk_total_bytes"),
            lane_wal_bytes=r.get("lane_wal_bytes"),
        )

    def drain_if_due(self) -> dict | None:
        """While the WAL latch is engaged, try to reset it (the boundary's own call), at most
        every :data:`DRAIN_EVERY_S`; name the holders when TRUNCATE is busy. Supervisor only.

        Returns the drain record when one ran. Runs on the supervisor thread, so a busy
        write gate (bounded at 30 s by ``checkpoint_wal``) delays nothing but this thread.
        """
        now_mono = self._clock()
        with self._lock:
            if not self._wal and not self._disk:
                return None
            if self._last_drain_mono is not None and now_mono - self._last_drain_mono < DRAIN_EVERY_S:
                return None
            self._last_drain_mono = now_mono
        try:
            rec = self._drain()
        except Exception:  # noqa: BLE001 - the drain must never kill the supervisor
            _LOG.debug("storage guard: drain failed", exc_info=True)
            rec = None
        pinned = isinstance(rec, dict) and (rec.get("busy") == 1 or "skipped" in rec)
        report = None
        if pinned and (self._last_pin_mono is None or now_mono - self._last_pin_mono >= PIN_REPORT_EVERY_S):
            report = _pin_report(rec)
        with self._lock:
            self._drains += 1
            self._last_drain = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "busy": rec.get("busy") if isinstance(rec, dict) else None,
                "skipped": rec.get("skipped") if isinstance(rec, dict) else None,
                "wal_bytes_before": rec.get("wal_bytes_before") if isinstance(rec, dict) else None,
                "wal_bytes_after": rec.get("wal_bytes_after") if isinstance(rec, dict) else None,
                "ran": rec is not None,
            }
            if report is not None:
                self._last_pin_report = report
                self._last_pin_mono = now_mono
        if report is not None:
            tops = "; ".join(
                f"{h['thread']} ({h['age_s']:.0f} s)"
                + (f" at {h['stack'][-1]}" if h.get("stack") else "")
                for h in report.get("holders", [])[:4]
            )
            _LOG.warning(
                "storage guard: the WAL cannot be reset -- TRUNCATE is busy; checkouts: %s",
                tops or "none listed (the holder is not a pooled checkout)",
            )
        return rec

    def wait_if_engaged(self, stop: threading.Event | None = None, *, poll_s: float = 2.0) -> bool:
        """Block, interruptibly, while engaged. For a long background writer at a chunk
        boundary; holds no session, gate or permit here. Returns whether it waited.

        Only useful while the supervisor is running (it is what releases the latch).
        """
        waited = False
        while self.admit() is not None:
            if stop is not None and stop.is_set():
                break
            waited = True
            if stop is not None:
                stop.wait(poll_s)
            else:
                time.sleep(poll_s)
        return waited

    # -- introspection -------------------------------------------------------------
    def state(self, *, detail: bool = False) -> dict:
        """The honest, numbers-first state for status payloads and the bundle.

        ``detail`` adds the six-hour history (360 samples): it rides the bundle's
        storage block, never the polled status payload.
        """
        with self._lock:
            wal, disk = self._wal, self._disk
            thr = dict(self._thresholds)
            last = dict(self._last)
            notes: list[dict[str, Any]] = []
            if disk:
                notes.append(
                    {
                        "kind": "disk",
                        "frame": FRAME_DISK,
                        "vars": {
                            "free": last.get("disk_free_bytes"),
                            "reserve": thr.get("disk_reserve_bytes"),
                            "resume": thr.get("disk_resume_bytes"),
                        },
                    }
                )
            if wal:
                notes.append(
                    {
                        "kind": "wal",
                        "frame": FRAME_WAL,
                        "vars": {"size": last.get("wal_bytes"), "limit": thr.get("wal_high_bytes")},
                    }
                )
            reason = " ".join(_render_english(n) for n in notes) or None
            return {
                "enabled": self.enabled(),
                "engaged": wal or disk,
                "kinds": [n["kind"] for n in notes],
                "phase": PHASE_DISK if disk else (PHASE_WAL if wal else None),
                "since": self._since,
                "reason": reason,
                "notes": notes,
                "engagements": self._engagements,
                "total_engaged_s": round(self._total_engaged_s, 1),
                "peak_wal_bytes_while_engaged": self._peak_wal_while_engaged if (wal or disk) else None,
                "disk_full_events": self._disk_full_events,
                "last_disk_full": self._last_disk_full,
                "thresholds": {
                    **thr,
                    "trip_after_samples": self.trip_after,
                    "resume_after_samples": self.resume_after,
                },
                "last_reading": last,
                "last_drain": self._last_drain,
                "drains": self._drains,
                "last_pin_report": self._last_pin_report,
                **({"history": list(self._history)} if detail else {}),
                "readings_available": (
                    any(last.get(k) is not None for k in ("wal_bytes", "disk_free_bytes")) if last else None
                ),
                "method": (
                    "Measured from file sizes and the drive's free bytes; no table is read. "
                    "WAL limit = min(clamp(10% of the corpus file, 512 MiB, 2 GiB), 10% of free "
                    "disk), never below 128 MiB: it protects normal bursts (floor), the next "
                    "unlock's recovery time (ceiling) and the drive (the free-disk term). Disk "
                    "reserve = max(1 GiB, 2% of the drive). Engages after "
                    f"{self.trip_after} consecutive samples, resumes after {self.resume_after} "
                    "healthy ones with margin, or at once on a full-disk write error. "
                    "Missing readings never count. The history is one sample a minute for six "
                    "hours, in memory only."
                ),
            }


def _render_english(note: dict[str, Any]) -> str:
    v = note["vars"]
    return note["frame"].format(**{k: _si(x) for k, x in v.items()})


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default


# Process-wide singleton (no thread, no I/O at import). Call sites use it as
# ``storage_guard.storage_guard`` (a module attribute) so tests can swap in a fake.
storage_guard = StorageGuard()


# --- the supervisor -----------------------------------------------------------------

#: How often the supervisor samples the drive. File sizes and a statvfs: cheap enough that
#: five seconds is not a cost, and short enough that a WAL growing at the measured 1.4 MB/s
#: moves under 10 MB between samples.
POLL_EVERY_S = 5.0

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_SUP_LOCK = threading.Lock()


def _supervise() -> None:
    while not _STOP.is_set():
        try:
            g = storage_guard
            if g.enabled():
                g.poll()
                g.drain_if_due()
        except Exception:  # noqa: BLE001 - a guard that dies silently is worse than none
            _LOG.warning("storage guard supervisor tick failed", exc_info=True)
        _STOP.wait(POLL_EVERY_S)


def start() -> bool:
    """Start the supervisor (idempotent across unlocks; False when disabled or running).

    Zero network, no database connection of its own at start: the first tick reads file
    sizes, and only an engaged WAL latch ever runs a checkpoint.
    """
    global _THREAD
    if not storage_guard.enabled():
        return False
    with _SUP_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_supervise, name="oo-storage-guard", daemon=True)
        _THREAD.start()
        return True


def stop() -> None:
    _STOP.set()


def supervisor_running() -> bool:
    """Whether the supervisor thread is alive. The pass loop asks, because the supervisor is
    what releases the latch: without it (``OO_NO_SCHEDULER=1`` at boot, then the scheduler
    started over the API) a loop waiting on the latch would wait for ever, so the loop then
    takes the readings and the drain itself."""
    t = _THREAD
    return t is not None and t.is_alive() and not _STOP.is_set()
