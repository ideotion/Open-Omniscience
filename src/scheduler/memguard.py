"""
The RSS memory guard: pause collection LOUDLY before the OOM-killer fires.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (P0.3 E3, field event 2026-07-09): the app died SILENTLY by
kernel OOM at RSS 10,599 MB on a ~10,237 MB VM, 21.6 hours into one continuous
crawl pass. The bandwidth governor already backs workers off under memory
pressure (mem_low), but back-off alone cannot stop a slow accumulation — the
process just grows more slowly until the kernel kills it with no trace. This
guard is the hard stop above the governor: when the process is provably close
to the cliff it PAUSES collection — loudly, visibly, resumably — instead of
letting the kernel end the run silently.

Honesty & safety by construction:

  * MEASURED readings only (psutil RSS / available / total). A missing reading
    (no psutil, a sandbox) never trips anything — no fabricated pressure.
  * HYSTERESIS both ways: it takes ``trip_after`` CONSECUTIVE over-threshold
    samples to engage (a single transient spike — one huge page being parsed —
    can never false-fire), and ``resume_after`` consecutive healthy samples to
    disengage (no flapping at the threshold).
  * The guard NEVER touches the writer gate, holds no locks while sampling
    others' state, and never blocks a worker mid-fetch: workers consult it
    BEFORE starting a source (a non-blocking read) and defer the source to the
    next pass; in-flight fetches always finish. Deadlock-free by construction.
  * Pause is VISIBLE: engaged state + the real numbers ride the scheduler
    status / activity payloads and the collect job's phase — never a silent
    stall. Resume is automatic when memory recovers, or explicit via the
    scheduler start/run-now/resume user actions.

``OO_MEM_GUARD=0`` disables the guard entirely (the governor back-off and the
per-pass hygiene still apply). Thresholds are env-tunable:

  OO_MEM_GUARD_RSS_PCT   trip when RSS >= this % of total RAM   (default 85)
  OO_MEM_GUARD_AVAIL_MB  trip when available RAM <= this        (default 256)
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime

_LOG = logging.getLogger("scheduler.memguard")


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.getenv(name, "") or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default


def _psutil_readings() -> dict:
    """Direct psutil readings for between-pass polls. All None on any error —
    a missing reading must never trip (or hold) the guard."""
    out: dict = {"rss_mb": None, "mem_avail_mb": None, "mem_total_mb": None}
    try:
        import psutil

        vm = psutil.virtual_memory()
        out["mem_avail_mb"] = round(vm.available / (1024 * 1024), 1)
        out["mem_total_mb"] = round(vm.total / (1024 * 1024), 1)
        out["rss_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - readings are best-effort
        pass
    return out


class MemoryGuard:
    """A trip/resume latch over measured memory readings, with hysteresis.

    TRIP  when, for >= ``trip_after`` consecutive samples, RSS >= ``rss_pct``%
          of total RAM OR available memory <= ``avail_floor_mb``.
    RESUME when, for >= ``resume_after`` consecutive samples, the readings are
          healthy WITH MARGIN (RSS <= rss_pct - 10 points AND available >=
          2 x avail_floor_mb) — or on an explicit :meth:`reset` (user action).

    Readings are pushed by the collection-perf monitor during a pass
    (:meth:`observe`) and pulled directly between passes (:meth:`poll`).
    ``readings_fn`` is injectable so tests drive fake RSS deterministically.
    """

    def __init__(
        self,
        *,
        rss_pct: float | None = None,
        avail_floor_mb: float | None = None,
        trip_after: int | None = None,
        resume_after: int | None = None,
        readings_fn=None,
    ) -> None:
        self.rss_pct = _env_float("OO_MEM_GUARD_RSS_PCT", 85.0) if rss_pct is None else rss_pct
        self.avail_floor_mb = (
            _env_float("OO_MEM_GUARD_AVAIL_MB", 256.0) if avail_floor_mb is None else avail_floor_mb
        )
        self.trip_after = _env_int("OO_MEM_GUARD_TRIP_AFTER", 3) if trip_after is None else max(1, trip_after)
        self.resume_after = (
            _env_int("OO_MEM_GUARD_RESUME_AFTER", 2) if resume_after is None else max(1, resume_after)
        )
        # Resume needs MARGIN below the trip line (hysteresis gap, no flapping).
        self.resume_rss_pct = max(1.0, self.rss_pct - 10.0)
        self._readings = readings_fn or _psutil_readings
        self._lock = threading.Lock()
        self._engaged = False
        self._since: str | None = None
        self._reason: str | None = None
        self._over = 0
        self._under = 0
        self._last: dict = {}

    @staticmethod
    def enabled() -> bool:
        return os.getenv("OO_MEM_GUARD", "1") != "0"

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._engaged

    def observe(
        self,
        *,
        rss_mb: float | None,
        mem_avail_mb: float | None,
        mem_total_mb: float | None,
    ) -> bool:
        """Feed one measured sample; returns the engaged state afterwards.

        All-None readings carry no information: they neither advance the trip
        counter nor the resume counter (never a fabricated pressure OR a
        fabricated recovery).
        """
        if not self.enabled():
            return False
        rss_frac_pct: float | None = None
        if rss_mb is not None and mem_total_mb:
            rss_frac_pct = 100.0 * rss_mb / mem_total_mb
        tripped_reason: str | None = None
        resumed = False
        with self._lock:
            self._last = {
                "rss_mb": rss_mb,
                "mem_avail_mb": mem_avail_mb,
                "mem_total_mb": mem_total_mb,
                "rss_pct_of_total": round(rss_frac_pct, 1) if rss_frac_pct is not None else None,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            if rss_frac_pct is None and mem_avail_mb is None:
                return self._engaged  # no information — hold state, count nothing
            over_rss = rss_frac_pct is not None and rss_frac_pct >= self.rss_pct
            over_avail = mem_avail_mb is not None and mem_avail_mb <= self.avail_floor_mb
            if not self._engaged:
                if over_rss or over_avail:
                    self._over += 1
                    if self._over >= self.trip_after:
                        self._engaged = True
                        self._since = datetime.now(UTC).isoformat(timespec="seconds")
                        self._reason = self._describe(rss_frac_pct, mem_avail_mb, over_rss, over_avail)
                        self._over = 0
                        self._under = 0
                        tripped_reason = self._reason
                else:
                    self._over = 0
            else:
                healthy_rss = rss_frac_pct is None or rss_frac_pct <= self.resume_rss_pct
                healthy_avail = mem_avail_mb is None or mem_avail_mb >= 2.0 * self.avail_floor_mb
                if healthy_rss and healthy_avail and not (over_rss or over_avail):
                    self._under += 1
                    if self._under >= self.resume_after:
                        self._resume_locked()
                        resumed = True
                else:
                    self._under = 0
            engaged = self._engaged
        # Log OUTSIDE the lock (skeptic nit: the jsonl error handler does file
        # I/O; workers' admit() checks must never queue behind a log write).
        if tripped_reason:
            _LOG.warning(
                "MEMORY GUARD ENGAGED — collection pausing before the "
                "OOM-killer can fire: %s (thresholds: rss >= %.0f%% of "
                "total or available <= %.0f MB, %d consecutive samples)",
                tripped_reason,
                self.rss_pct,
                self.avail_floor_mb,
                self.trip_after,
            )
        if resumed:
            _LOG.warning("memory guard released (memory recovered) — collection resumes")
        return engaged

    def poll(self) -> bool:
        """Take a fresh reading NOW (between passes, when no monitor is
        sampling) and return the engaged state afterwards."""
        r = self._readings() or {}
        return self.observe(
            rss_mb=r.get("rss_mb"),
            mem_avail_mb=r.get("mem_avail_mb"),
            mem_total_mb=r.get("mem_total_mb"),
        )

    def reset(self, *, reason: str = "user action") -> None:
        """Explicit resume (a user pressed start/run-now/resume). The guard
        re-trips after ``trip_after`` fresh over-threshold samples if memory
        is still genuinely low — reset is a retry, never an override forever."""
        was_engaged = False
        with self._lock:
            if self._engaged:
                self._resume_locked()
                was_engaged = True
            self._over = 0
            self._under = 0
        if was_engaged:
            _LOG.warning("memory guard released (%s) — collection resumes", reason)

    def _resume_locked(self) -> None:
        # Caller logs OUTSIDE the lock (see observe/reset).
        self._engaged = False
        self._reason = None
        self._since = None
        self._over = 0
        self._under = 0

    @staticmethod
    def _describe(rss_frac_pct, mem_avail_mb, over_rss: bool, over_avail: bool) -> str:
        parts = []
        if over_rss:
            parts.append(f"process RSS at {rss_frac_pct:.1f}% of total RAM")
        if over_avail:
            parts.append(f"only {mem_avail_mb:.0f} MB of system memory available")
        return " and ".join(parts) or "memory pressure"

    def state(self) -> dict:
        """The honest, numbers-first state for status/activity payloads."""
        with self._lock:
            return {
                "enabled": self.enabled(),
                "engaged": self._engaged,
                "since": self._since,
                "reason": self._reason,
                "thresholds": {
                    "rss_pct_of_total": self.rss_pct,
                    "avail_floor_mb": self.avail_floor_mb,
                    "trip_after_samples": self.trip_after,
                    "resume_after_samples": self.resume_after,
                    "resume_rss_pct": self.resume_rss_pct,
                },
                "last_reading": dict(self._last),
                # Honest visibility: an "enabled" guard with no readings (no
                # psutil) is BLIND — surfaced, never implied protection.
                "readings_available": (
                    any(v is not None for k, v in self._last.items() if k != "ts")
                    if self._last
                    else None
                ),
                "method": (
                    "Measured psutil readings; engages only after "
                    f"{self.trip_after} consecutive over-threshold samples, "
                    f"resumes after {self.resume_after} consecutive healthy ones "
                    "or a user action. Missing readings never count."
                ),
            }


# Process-wide singleton (no thread, no I/O at import). Call sites access it as
# ``memguard.memory_guard`` (module attribute) so tests can swap in a fake.
memory_guard = MemoryGuard()
