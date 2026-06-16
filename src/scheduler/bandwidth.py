"""
The bandwidth governor: steer download throughput by adjusting how many sources
are fetched at once — never by hammering one source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (maintainer ruling 2026-06-16): the user does not think in
"parallel tasks", they think in download speed. So the collector takes a
download-rate TARGET (or "maximum") and the governor varies the number of
ACTIVELY-FETCHING workers to approach it. Honesty, by construction:

  * A target is best-effort, never a promise. Realised speed is bounded by the
    sources, the network (much lower over Tor), the CPU and the single encrypted
    writer. The governor measures the app's OWN real download rate and nudges the
    worker count toward the target; it cannot conjure bytes the network won't give.
  * Source respect is invariant. The governor ONLY changes how many DISTINCT
    hosts run concurrently. The per-host lock + per-host minimum interval in the
    EthicalFetcher are untouched, so a single host is never fetched by more than
    one worker at a time — politeness is never traded for speed.
  * Contention back-off is self-protective AND visible. When the writer gate, the
    CPU, or memory become the limit, the governor REDUCES the worker count below
    what the rate target would ask, and the reason is recorded in the
    collection-performance log (src/monitoring/collect_perf.py) — never hidden.

What it is, stated plainly: an application-level adjustable semaphore (permits =
the allowed concurrent fetches) plus a damped AIMD controller that resizes it.
``acquire``/``release`` bracket each worker's fetch+store; ``observe`` is called
once per monitor tick with the measured rate + contention flags and returns the
new permit count and a human reason. All time is injectable so the control loop
is deterministically testable with no real waiting.
"""

from __future__ import annotations

import threading
import time

# Default seed concurrency for target mode (maintainer's estimate: ~25 workers
# reach ~500 kbps). Only a STARTING point — the controller measures and adapts.
DEFAULT_SEED = 25
# The controller changes the worker count at most this often (rate tracking only;
# contention back-off reacts immediately). Damps oscillation.
DEFAULT_MIN_ADJUST_INTERVAL_S = 3.0

VALID_RATE_MODES = ("target", "maximum")


class _AdjustableSemaphore:
    """A semaphore whose permit count can be changed while threads hold/await it.

    ``acquire`` blocks while the number of holders has reached ``permits``;
    ``set_permits`` can raise the ceiling (waking waiters) or lower it (holders in
    excess simply finish their one unit of work and release — never preempted).
    Permits are clamped to >= 1 so at least one worker always proceeds: the pass
    can never deadlock to a halt.
    """

    def __init__(self, permits: int) -> None:
        self._cond = threading.Condition()
        self._permits = max(1, int(permits))
        self._active = 0

    def acquire(self) -> None:
        with self._cond:
            while self._active >= self._permits:
                self._cond.wait()
            self._active += 1

    def release(self) -> None:
        with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify()

    def set_permits(self, n: int) -> None:
        with self._cond:
            self._permits = max(1, int(n))
            self._cond.notify_all()

    @property
    def permits(self) -> int:
        with self._cond:
            return self._permits

    @property
    def active(self) -> int:
        with self._cond:
            return self._active


class BandwidthGovernor:
    """Resize the concurrent-fetch permit set to track a download-rate target.

    ``mode`` is "target" (track ``target_kbps``) or "maximum" (ramp to ``w_max``,
    backing off only under contention). ``w_max`` is the hard ceiling; ``seed`` is
    the starting permit count. Workers call :meth:`acquire`/:meth:`release`; the
    monitor loop calls :meth:`observe` once per tick.
    """

    def __init__(
        self,
        *,
        mode: str = "target",
        target_kbps: int = 500,
        w_max: int = 50,
        seed: int | None = None,
        min_adjust_interval_s: float = DEFAULT_MIN_ADJUST_INTERVAL_S,
    ) -> None:
        self.mode = mode if mode in VALID_RATE_MODES else "target"
        self.target_kbps = max(1, int(target_kbps))
        self.w_max = max(1, int(w_max))
        if seed is None:
            seed = min(DEFAULT_SEED, self.w_max)
        if self.mode == "maximum":
            seed = self.w_max
        self._sem = _AdjustableSemaphore(max(1, min(int(seed), self.w_max)))
        self._min_interval = max(0.0, float(min_adjust_interval_s))
        self._last_adjust = 0.0
        self._last_reason = "seed"

    # -- worker side ------------------------------------------------------- #

    def acquire(self) -> None:
        self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    @property
    def permits(self) -> int:
        return self._sem.permits

    @property
    def active(self) -> int:
        return self._sem.active

    # -- controller side --------------------------------------------------- #

    def observe(
        self,
        measured_kbps: float,
        *,
        writer_saturated: bool = False,
        cpu_saturated: bool = False,
        mem_low: bool = False,
        now: float | None = None,
    ) -> tuple[int, str]:
        """Adjust the permit count from the measured rate + contention flags.

        Returns ``(new_permits, reason)``. Contention back-off reacts on EVERY
        tick (safety first); rate tracking is rate-limited to ``min_adjust_interval``
        so the controller settles instead of oscillating. The permit count is
        always within ``[1, w_max]``.
        """
        now = time.monotonic() if now is None else now
        cur = self._sem.permits

        # 1) Contention always wins — reduce immediately, regardless of the rate.
        if mem_low or writer_saturated or cpu_saturated:
            reason = (
                "mem-low" if mem_low else "writer-saturated" if writer_saturated else "cpu-saturated"
            )
            step = 2 if mem_low else 1
            new = max(1, cur - step)
            if new != cur:
                self._sem.set_permits(new)
                self._last_adjust = now
            self._last_reason = reason
            return new, reason

        # 2) Rate tracking — damped to one change per interval.
        if now - self._last_adjust < self._min_interval:
            self._last_reason = "settling"
            return cur, "settling"

        if self.mode == "maximum":
            if cur < self.w_max:
                new = min(self.w_max, cur + 2)
                reason = "ramp-max"
            else:
                new, reason = cur, "at-ceiling"
        else:  # target
            lo, hi = self.target_kbps * 0.9, self.target_kbps * 1.1
            if measured_kbps < lo and cur < self.w_max:
                new, reason = min(self.w_max, cur + 1), "below-target"
            elif measured_kbps > hi and cur > 1:
                new, reason = max(1, cur - 1), "above-target"
            else:
                new, reason = cur, "in-band"

        if new != cur:
            self._sem.set_permits(new)
            self._last_adjust = now
        self._last_reason = reason
        return new, reason

    def stats(self) -> dict:
        """A point-in-time view for the perf log (no estimates)."""
        return {
            "mode": self.mode,
            "target_kbps": self.target_kbps,
            "w_max": self.w_max,
            "permits": self.permits,
            "active": self.active,
            "last_reason": self._last_reason,
        }
