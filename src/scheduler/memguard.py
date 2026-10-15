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

THE CLEAN STOP (``OO_MEM_STOP=0`` turns it off; question 22a, B2). A guard that stays engaged while available memory sits on
the floor has not helped: the pause stops NEW work, and the memory the process already holds does not come back (the 2026-09-30
plateau sat at 64 MB or less for 12 minutes before the kernel killed it). :func:`stall_decision` is the pure criterion for that
state, replayed against the recorded series in ``tests/test_memguard_stop.py``; when it holds, the guard hands the process to
``src.scheduler.memstop`` ONCE, which keeps the evidence and shuts the app down through the path the power button uses. The
window is :data:`STOP_WINDOW_S` (``OO_MEM_STOP_WINDOW_S``) and the floor :data:`STOP_AVAIL_MB` (``OO_MEM_STOP_AVAIL_MB``).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime

from src.monitoring.secret_scrub import log_failure

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


#: How long, engaged, available memory must have sat on the floor (300 s fired 724 s before the kernel's kill on the recorded
#: 2026-09-30 series; 120 s would stop a machine that recovers within two minutes, 600 s leaves the teardown too little room).
STOP_WINDOW_S = 300.0
#: The floor: a quarter of the guard's own 256 MB line. A reading above TWICE this (a brief recovery) breaks the plateau.
STOP_AVAIL_MB = 64.0
#: Fewest readings a window may stand on, the share of them that must be at the floor, and the share of the window its real
#: span must cover (a missing reading counts nothing, as in ``observe``).
STOP_MIN_SAMPLES = 10
STOP_LOW_SHARE = 0.9
STOP_SPAN_SHARE = 0.95
#: This process must hold this share of the machine's RAM, or stopping it frees nothing another process is holding.
STOP_HELD_SHARE = 1.0 / 3.0


def stall_decision(
    samples: "list[tuple[float, float]] | deque[tuple[float, float]]",
    now: float,
    *,
    window_s: float = STOP_WINDOW_S,
    floor_mb: float = STOP_AVAIL_MB,
    rss_mb: float | None = None,
    total_mb: float | None = None,
) -> dict:
    """Whether the engaged guard has STALLED at the floor. ``samples`` are ``(monotonic seconds, available MB)`` taken while the
    guard was engaged; the window is the last ``window_s`` seconds up to ``now``. Pure: no clock, no state, no I/O.

    ``due`` is true only when ALL hold: at least :data:`STOP_MIN_SAMPLES` readings in the window; their real span at least
    :data:`STOP_SPAN_SHARE` of the window; at least :data:`STOP_LOW_SHARE` of them at ``floor_mb`` or less; none above twice
    the floor (a recovery, even a brief one, breaks the plateau); and the process holds at least :data:`STOP_HELD_SHARE` of the
    machine's RAM. The answer always carries the numbers it was made from and, when not due, the one condition that failed
    first (``why``), so a record never asserts more than was measured. ``held_elsewhere`` is set when the memory is the
    plateau's but not this process's."""
    inside = [(t, a) for t, a in samples if now - window_s <= t <= now]
    out: dict = {"due": False, "window_s": window_s, "floor_mb": floor_mb, "samples": len(inside)}
    if len(inside) < STOP_MIN_SAMPLES:
        out["why"] = "too few readings in the window"
        return out
    span = now - inside[0][0]
    out["span_s"] = round(span, 1)
    if span < STOP_SPAN_SHARE * window_s:
        out["why"] = "the readings do not span the window"
        return out
    # A recovery can hide in a stretch with no readings: no gap (between readings, or from the last one to now) may be longer
    # than a tenth of the window, the same share as the fewest readings it may stand on.
    gaps = [b[0] - a[0] for a, b in zip(inside, inside[1:], strict=False)] + [now - inside[-1][0]]
    out["longest_gap_s"] = round(max(gaps), 1)
    if max(gaps) > window_s / STOP_MIN_SAMPLES:
        out["why"] = "a stretch of the window has no readings"
        return out
    low = sum(1 for _t, a in inside if a <= floor_mb)
    top = max(a for _t, a in inside)
    out["low_share"] = round(low / len(inside), 3)
    out["max_avail_mb"] = round(top, 1)
    if top > 2.0 * floor_mb:
        out["why"] = "available memory recovered inside the window"
        return out
    if low < STOP_LOW_SHARE * len(inside):
        out["why"] = "too few readings at the floor"
        return out
    if rss_mb is None or not total_mb:
        out["why"] = "this process's share of the memory could not be read"
        return out
    share = rss_mb / total_mb
    out["held_share"] = round(share, 3)
    if share < STOP_HELD_SHARE:
        out["why"] = "memory held elsewhere"
        out["held_elsewhere"] = True
        return out
    out["due"] = True
    return out


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
    try:
        from src.monitoring.swap import swap_readings

        out.update(swap_readings())
    except Exception:  # noqa: BLE001
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
        release_fn=None,
        stop_fn=None,
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
        # S1.2: what an engage RELEASES. Injectable so tests drive the ladder
        # deterministically; the record is kept so a report can say what was
        # freed rather than assert that pausing helped.
        self._release_fn = release_fn
        self._last_release: dict | None = None
        # The clean stop (B2): the engaged window's readings, the one-shot flag, and the last criterion answer. ``stop_fn`` is
        # injectable so the guard stays a latch in tests and the sequence is its own module.
        self._stop_fn = stop_fn
        self._stall: deque[tuple[float, float]] = deque()
        self._stop_started = False
        self._stall_last: dict | None = None
        self._lock = threading.Lock()
        self._engaged = False
        self._since: str | None = None
        # Process-cumulative engage CYCLES and engaged TIME. A soak's question is "how
        # often did this machine hit the wall, and for how long", and the guard until now
        # published only its current state -- from which a three-day run and a three-day
        # run with forty pauses in it look identical. The transition is rare by
        # construction (``trip_after`` consecutive over-threshold samples), so counting it
        # costs nothing on any path that runs often.
        self._engagements = 0
        self._total_engaged_s = 0.0
        self._engaged_since_mono: float | None = None
        self._reason: str | None = None
        self._over = 0
        self._under = 0
        self._last: dict = {}
        # Our own swapped-out bytes at the previous sample, so a RISE can be
        # distinguished from a machine that paged out once and settled.
        self._last_proc_swap: float | None = None

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
        proc_swap_mb: float | None = None,
    ) -> bool:
        """Feed one measured sample; returns the engaged state afterwards.

        All-None readings carry no information: they neither advance the trip
        counter nor the resume counter (never a fabricated pressure OR a
        fabricated recovery).

        S1.2 — a SWAP-OUT IS NOT A RECOVERY. Moving our pages to disk raises
        ``available`` and lowers RSS at the same time, which is precisely the
        healthy turn the resume condition is watching for; the field readings
        show ``available`` alternating 200/600 MB while RSS sat at 1600 and
        ``VmSwap`` climbed. So while our OWN swap is RISING the resume counter is
        reset: the machine is not recovering, it is paying for the same pages in
        a slower place. Only a RISE counts — steady swap is what a box that has
        already paged out looks like for the rest of its life, and treating that
        as pressure would pin the guard on forever.
        """
        if not self.enabled():
            return False
        rss_frac_pct: float | None = None
        if rss_mb is not None and mem_total_mb:
            rss_frac_pct = 100.0 * rss_mb / mem_total_mb
        tripped_reason: str | None = None
        tripped_engagement = 0
        resumed = False
        stop_decision: dict | None = None
        with self._lock:
            prev_swap = self._last_proc_swap
            if proc_swap_mb is not None:
                self._last_proc_swap = proc_swap_mb
            self._last = {
                "rss_mb": rss_mb,
                "mem_avail_mb": mem_avail_mb,
                "mem_total_mb": mem_total_mb,
                "proc_swap_mb": proc_swap_mb,
                "proc_swap_rising": (
                    None
                    if proc_swap_mb is None or prev_swap is None
                    else proc_swap_mb > prev_swap
                ),
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
                        self._engagements += 1
                        self._engaged_since_mono = time.monotonic()
                        self._since = datetime.now(UTC).isoformat(timespec="seconds")
                        self._reason = self._describe(rss_frac_pct, mem_avail_mb, over_rss, over_avail)
                        self._over = 0
                        self._under = 0
                        tripped_reason = self._reason
                        tripped_engagement = self._engagements
                        self._stall.clear()
                else:
                    self._over = 0
            else:
                healthy_rss = rss_frac_pct is None or rss_frac_pct <= self.resume_rss_pct
                healthy_avail = mem_avail_mb is None or mem_avail_mb >= 2.0 * self.avail_floor_mb
                swapping_out = bool(self._last.get("proc_swap_rising"))
                if (
                    healthy_rss
                    and healthy_avail
                    and not (over_rss or over_avail)
                    and not swapping_out
                ):
                    self._under += 1
                    if self._under >= self.resume_after:
                        self._resume_locked()
                        resumed = True
                else:
                    self._under = 0
                if self._engaged:
                    stop_decision = self._note_stall_locked(mem_avail_mb, rss_mb, mem_total_mb)
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
            self._run_release(tripped_engagement)
        if resumed:
            _LOG.warning("memory guard released (memory recovered) — collection resumes")
        if stop_decision is not None:
            self._run_stop(stop_decision)
        return engaged

    @staticmethod
    def stop_enabled() -> bool:
        return os.getenv("OO_MEM_STOP", "1") != "0"

    def _note_stall_locked(self, avail: float | None, rss: float | None, total: float | None) -> dict | None:
        """Fold one engaged sample into the stall window and, when the criterion holds for the first time, claim the one stop.
        Caller holds the lock and runs the stop OUTSIDE it. The window is pruned by TIME (older than the window), so what it
        holds is bounded by how often readings arrive, not by a count."""
        if avail is None or not self.stop_enabled():
            return None
        now = time.monotonic()
        window = _env_float("OO_MEM_STOP_WINDOW_S", STOP_WINDOW_S)
        floor = _env_float("OO_MEM_STOP_AVAIL_MB", STOP_AVAIL_MB)
        self._stall.append((now, avail))
        while self._stall and self._stall[0][0] < now - window:
            self._stall.popleft()
        decision = stall_decision(self._stall, now, window_s=window, floor_mb=floor, rss_mb=rss, total_mb=total)
        self._stall_last = decision
        if not decision["due"] or self._stop_started:
            return None
        self._stop_started = True
        return decision

    def _run_stop(self, decision: dict) -> None:
        """Hand the process to the clean stop. Never raises: the pause stands whether or not the stop runs."""
        fn = self._stop_fn
        if fn is None:
            from src.scheduler.memstop import execute as fn  # noqa: PLC0415
        try:
            fn(decision, self)
        except Exception as exc:  # noqa: BLE001 - a failed stop leaves the pause in force
            log_failure(_LOG, "memory guard: the clean stop failed", exc, level=logging.WARNING)

    def raw_pressure(
        self,
        *,
        rss_mb: float | None,
        mem_avail_mb: float | None,
        mem_total_mb: float | None,
    ) -> bool | None:
        """Whether THIS ONE sample, alone, crosses the guard's trip thresholds.

        D2 (2026-09-11). :meth:`observe` answers a different question -- "should
        collection be PAUSED right now" -- and deliberately needs ``trip_after``
        CONSECUTIVE over-threshold samples before it says yes, so a single brushed
        tick can never false-fire a pause. That hysteresis is correct for the pause
        decision and wrong for anything that wants to COUNT pressure across a pass
        the way ``CollectionMonitor`` already counts ``mem_low`` ticks: a machine
        that hovers right at the line reads as ``engagements: 0`` for its entire
        life (RSS repeatedly touching 85% without ever holding it for three
        straight samples), which is indistinguishable, to a caller reading only
        ``observe``'s return, from a machine with no pressure at all.

        This is the unlatched reading underneath that latch -- same thresholds
        (``self.rss_pct`` / ``self.avail_floor_mb``, so a caller never re-embeds
        the numbers), same formula, NO state, NO hysteresis, and no memory of any
        earlier sample: it neither trips nor clears anything and is safe to call
        every tick from anywhere, including tests, without disturbing
        :meth:`observe`'s own latch. ``None`` when neither reading is available --
        the same "no information" refusal :meth:`observe` makes, because an absent
        reading must never be read as a healthy one.
        """
        if not self.enabled():
            return None
        rss_frac_pct = (
            100.0 * rss_mb / mem_total_mb if rss_mb is not None and mem_total_mb else None
        )
        if rss_frac_pct is None and mem_avail_mb is None:
            return None
        over_rss = rss_frac_pct is not None and rss_frac_pct >= self.rss_pct
        over_avail = mem_avail_mb is not None and mem_avail_mb <= self.avail_floor_mb
        return over_rss or over_avail

    def _run_release(self, engagement: int | None = None) -> None:
        """Release residents on engage. Never raises — the pause must stand even
        if the release fails, and this runs when the machine is already in
        trouble. The record is stamped with the number of the engagement it was run
        for (``engagement``, default the current count), so a reader can tell the
        ladder of THIS engagement from the last one's."""
        fn = self._release_fn
        if fn is None:
            from src.scheduler.release import release_residents as fn  # noqa: PLC0415
        try:
            rec = fn()
        except Exception as exc:  # noqa: BLE001 - a failed release is not a failed pause
            log_failure(_LOG, "memory guard: release ladder failed", exc, level=logging.DEBUG)
            return
        with self._lock:
            stamp = self._engagements if engagement is None else engagement
            self._last_release = {**rec, "engagement": stamp} if isinstance(rec, dict) else rec

    def last_release(self) -> dict | None:
        """The most recent release record (None until an engage has run one)."""
        with self._lock:
            return self._last_release

    def poll(self) -> bool:
        """Take a fresh reading NOW (between passes, when no monitor is
        sampling) and return the engaged state afterwards."""
        r = self._readings() or {}
        return self.observe(
            rss_mb=r.get("rss_mb"),
            mem_avail_mb=r.get("mem_avail_mb"),
            mem_total_mb=r.get("mem_total_mb"),
            proc_swap_mb=r.get("proc_swap_mb"),
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
        if self._engaged_since_mono is not None:
            self._total_engaged_s += time.monotonic() - self._engaged_since_mono
            self._engaged_since_mono = None
        self._engaged = False
        self._reason = None
        self._since = None
        self._over = 0
        self._under = 0
        self._stall.clear()
        self._stall_last = None

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
                # Since THIS PROCESS started -- a restart resets them, which is correct
                # for a soak (a restart ends the soak) and must be read that way.
                "engagements": self._engagements,
                # Closed episodes only: an episode still open is ``engaged``/``since``
                # above, and folding it in here would make a currently-paused machine
                # report a completed duration it has not finished serving.
                "total_engaged_s": round(self._total_engaged_s, 1),
                "thresholds": {
                    "rss_pct_of_total": self.rss_pct,
                    "avail_floor_mb": self.avail_floor_mb,
                    "trip_after_samples": self.trip_after,
                    "resume_after_samples": self.resume_after,
                    "resume_rss_pct": self.resume_rss_pct,
                },
                "last_reading": dict(self._last),
                "stop": {
                    "enabled": self.stop_enabled(),
                    "started": self._stop_started,
                    "last_decision": dict(self._stall_last) if self._stall_last else None,
                },
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
