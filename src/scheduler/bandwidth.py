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

from src.utils.interrupts import wait as _wait

# Default seed concurrency for target mode (maintainer's estimate: ~25 workers
# reach ~500 kbps). Only a STARTING point — the controller measures and adapts.
DEFAULT_SEED = 25
# The controller changes the worker count at most this often (rate tracking only;
# contention back-off reacts immediately). Damps oscillation.
DEFAULT_MIN_ADJUST_INTERVAL_S = 3.0

VALID_RATE_MODES = ("target", "maximum")

# MAXIMUM MODE: start low, climb while the stored-articles rate rises (R178, R180). Each number names what it protects.
#: Where a pass with no learned seed starts. The lab count at which the single-writer gate stops queueing on 2 CPUs: a place to climb
#: from, not the answer (the climb finds the machine's own count). Never above ``w_max``; a learned seed always wins over it.
MAXIMUM_START = 4
#: A window is at least this long: the longest clean-lab write-gate hold was 5.2 s, so even the shortest window holds many whole
#: hold cycles, and the time a fetch spends in flight (the lab's 300 ms, a field Tor circuit's seconds) is a small share of it.
MAXIMUM_WINDOW_S = 240.0
#: A window also holds at least this many SOURCE COMPLETIONS before it is read. A stored count moves in lumps (one source returns its
#: articles together), so the noise of a window's count falls with the number of completions in it and not with its seconds;
#: this is the number below which two windows at the same permit count differed by more than the margin below.
#: Measured: see the ledger row "governor reads stored articles" (the lab's fixed-permit cell, window rate against completions).
MAXIMUM_WINDOW_SOURCES = 100
#: A window counts as a rise or a fall only beyond this fraction of the previous window's rate: above the noise of a window of the
#: size above, so that noise neither climbs nor steps back.
MAXIMUM_MARGIN = 0.10
#: Writer and CPU saturation are decided per window: a window with at least this share of saturated ticks takes ONE cut in place
#: of its climb decision. A cut on every tick (about 0.3 s) outran a climb once per window by a hundred to one and held the count
#: at one permit (lab cell G1: 45 art/min against 58 with the cut folded, G3).
MAXIMUM_CUT_SHARE = 0.5


class _AdjustableSemaphore:
    """A semaphore whose permit count can be changed while threads hold/await it.

    ``acquire`` blocks while the number of holders has reached ``permits``;
    ``set_permits`` can raise the ceiling (waking waiters) or lower it (holders in
    excess simply finish their one unit of work and release — never preempted).
    Permits are clamped to >= 1 so at least one worker always proceeds: the pass
    can never deadlock to a halt.
    """

    def __init__(self, permits: int) -> None:
        # a plain RLock under the Condition and `with self._lock:` everywhere: a Condition's own __enter__/__exit__ are Python frames, where a
        # KeyboardInterrupt can land between "taken" and "released" and leave the lock taken for ever (see src/config/kv_store.py::_hold_lock)
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._permits = max(1, int(permits))
        self._active = 0

    def acquire(self) -> None:
        with self._lock:
            # the loop is `while True: if not <wanted>: break` and not `while <wanted>:` -- CPython 3.13 leaves the back-edge of the second form outside the `with`'s exception table (src/utils/interrupts.py)
            while True:
                if self._active < self._permits:
                    break
                _wait(self._cond, self._lock)
            self._active += 1

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1
            self._cond.notify_all()  # not notify(): a stale entry in the waiter list (an interrupted wait) would swallow the one wake

    def set_permits(self, n: int) -> None:
        with self._lock:
            self._permits = max(1, int(n))
            self._cond.notify_all()

    @property
    def permits(self) -> int:
        with self._lock:
            return self._permits

    @property
    def active(self) -> int:
        with self._lock:
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
        ramp_ceiling: int | None = None,
        min_adjust_interval_s: float = DEFAULT_MIN_ADJUST_INTERVAL_S,
        window_s: float = MAXIMUM_WINDOW_S,
        window_sources: int = MAXIMUM_WINDOW_SOURCES,
        margin: float = MAXIMUM_MARGIN,
    ) -> None:
        self.mode = mode if mode in VALID_RATE_MODES else "target"
        self.target_kbps = max(1, int(target_kbps))
        self.w_max = max(1, int(w_max))
        # A SOFT ceiling on the upward ramp, distinct from the hard ``w_max``. Without
        # it the learned ceiling (scheduler.capacity) would bound only where a pass
        # STARTS: the ramp would climb back toward w_max within the same pass, overshoot
        # the capacity the machine just demonstrated, and re-trigger the pressure the
        # seed existed to avoid. Capping it here moves the probing entirely BETWEEN
        # passes, where capacity's own relaxation raises the ceiling one controlled step
        # after a pass that saw no pressure. Defaults to w_max, so a caller that knows
        # nothing about this machine gets exactly the previous behaviour.
        self.ramp_ceiling = (
            self.w_max
            if ramp_ceiling is None
            else max(1, min(int(ramp_ceiling), self.w_max))
        )
        if seed is None:
            # No explicit seed: maximum mode opens wide, target mode eases in. An
            # EXPLICIT seed is honoured in both modes — it is a caller that already
            # knows something about this machine (see scheduler.capacity), and the
            # old unconditional `maximum` override silently discarded it, which
            # made the learned ceiling a no-op in exactly the mode that needs it.
            seed = min(MAXIMUM_START, self.w_max) if self.mode == "maximum" else min(DEFAULT_SEED, self.w_max)
        self._sem = _AdjustableSemaphore(max(1, min(int(seed), self.w_max)))
        self._window_s = max(0.0, float(window_s))
        self._window_sources = max(0, int(window_sources))
        self._margin = max(0.0, float(margin))
        self._win: dict = {}
        self._reset_window()
        self._prev_rate: float | None = None
        self._prev_unit: str | None = None
        self._climbed = False
        #: the last window decision, for the perf log: what the rule saw, not only what it did
        self.last_window: dict | None = None
        self._min_interval = max(0.0, float(min_adjust_interval_s))
        self._last_adjust = 0.0
        self._last_reason = "seed"

    def _reset_window(self) -> None:
        self._win = {"t0": None, "sum": 0.0, "n": 0, "writer": 0, "cpu": 0, "a0": None, "s0": None}

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
        loop_lagging: bool = False,
        now: float | None = None,
        window_rate: float | None = None,
        articles_total: int | None = None,
        sources_total: int | None = None,
    ) -> tuple[int, str]:
        """Adjust the permit count from the measured rate + contention flags.

        Returns ``(new_permits, reason)``. Contention back-off reacts on EVERY
        tick (safety first); rate tracking is rate-limited to ``min_adjust_interval``
        so the controller settles instead of oscillating. The permit count is
        always within ``[1, w_max]``.

        The flags are checked in order of how certain the harm is, and the reason names
        the FIRST that is true rather than blurring them: memory can kill the machine,
        the writer is a measured queue, CPU contention is someone else's need, and
        ``loop_lagging`` (P6) is our own server being made to wait. They are separate
        reasons because the remedies and the evidence differ, and a reader of the perf
        log has to be able to tell which one moved the permits.
        """
        now = time.monotonic() if now is None else now
        cur = self._sem.permits
        maximum = self.mode == "maximum"

        # 1) Contention always wins — reduce immediately, regardless of the rate. In MAXIMUM mode only memory and loop lag are
        # immediate (the first can kill the machine, the second starves our own API server); writer and CPU saturation are
        # decided per window (see ``_window_step``).
        if mem_low or loop_lagging or (not maximum and (writer_saturated or cpu_saturated)):
            # In maximum mode writer and CPU saturation are not what is acting here (they are decided per window), so a tick that
            # also carried one of them is named for the flag that IS: memory, or loop lag.
            reason = (
                "mem-low"
                if mem_low
                else "writer-saturated"
                if writer_saturated and not maximum
                else "cpu-saturated"
                if cpu_saturated and not maximum
                else "loop-lag"
            )
            if mem_low:
                # Memory is the one contention signal where overshoot is not merely slow
                # but fatal — the machine thrashes into swap and may be OOM-killed — so it
                # gets a MULTIPLICATIVE decrease (the standard AIMD discipline) where the
                # others get a linear step. From 50 that is 6 ticks to the floor instead
                # of 25, and every tick spent descending is a tick spent AT the pressure
                # that triggered the descent (measured on a 4-core/3.65 GiB box: 43 s of
                # 150–300 MB-available thrash to walk 50 → 1, once per pass).
                # Writer/CPU saturation stay linear on purpose: those cost throughput,
                # not the machine, and over-cutting them just wastes capacity.
                new = max(1, cur // 2)
            else:
                # Writer, CPU and loop-lag all get the LINEAR step. P6's is linear for the
                # same reason the other two are — it costs throughput, not the machine —
                # and for one more: unlike memory, the collector may not even be the cause
                # of loop lag (a synchronous call on the loop blocks it by itself), so the
                # descent has to be slow enough for CollectionMonitor to notice it is not
                # helping and stop. A multiplicative cut would reach the floor first.
                new = max(1, cur - 1)
            if new != cur:
                self._sem.set_permits(new)
                self._last_adjust = now
            if maximum:
                # The window spanned two regimes; its mean and the last window's no longer compare.
                self._reset_window()
                self._prev_rate = None
                self._prev_unit = None
                self._climbed = False
            self._last_reason = reason
            return new, reason

        if maximum:
            return self._window_step(
                float(measured_kbps if window_rate is None else window_rate),
                articles_total, sources_total,
                writer_saturated=writer_saturated, cpu_saturated=cpu_saturated, now=now,
            )

        # 2) Rate tracking — damped to one change per interval.
        if now - self._last_adjust < self._min_interval:
            self._last_reason = "settling"
            return cur, "settling"

        # The ramp climbs to the SOFT ceiling, never past it. When no ceiling was
        # learned it IS w_max, so the branches below are unchanged for any machine
        # that has never backed off under memory pressure.
        top = self.ramp_ceiling
        held_by_learned = top < self.w_max
        # target mode (maximum returned above)
        lo, hi = self.target_kbps * 0.9, self.target_kbps * 1.1
        if measured_kbps < lo and cur < top:
            new, reason = min(top, cur + 1), "below-target"
        elif measured_kbps > hi and cur > 1:
            new, reason = max(1, cur - 1), "above-target"
        elif measured_kbps > hi:
            # THE HIGH-SIDE TWIN of the branch below, which was missing (found
            # by an adversarial pass on S04-13 S1 and reproduced: at the floor,
            # 160x over target, this reported "in-band"). Above target AND
            # unable to cut any further -- "in-band" claims the rate is where it
            # should be, which is the opposite of what is happening, exactly as
            # the comment below says for the mirror case.
            #
            # It became easy to reach when the governor started observing the
            # WHOLE PROCESS (Q1012): a bulk download can sit far above the
            # target for its whole duration, where the collector's own rate
            # rarely could. The permit count is genuinely at its floor and that
            # is correct -- the lever has been pulled all the way -- so only the
            # WORD was wrong, which is the cheaper half to fix and the one a
            # reader of the perf log acts on.
            new, reason = cur, "above-target-at-floor"
        elif measured_kbps < lo and held_by_learned and cur >= top:
            # Below target AND unable to climb: "in-band" would claim the rate is
            # where it should be, which is the opposite of what is happening.
            new, reason = cur, "at-learned-ceiling"
        else:
            new, reason = cur, "in-band"

        if new != cur:
            self._sem.set_permits(new)
            self._last_adjust = now
        self._last_reason = reason
        return new, reason

    def _window_step(
        self,
        collector_kbps: float,
        articles_total: int | None,
        sources_total: int | None,
        *,
        writer_saturated: bool,
        cpu_saturated: bool,
        now: float,
    ) -> tuple[int, str]:
        """MAXIMUM mode, one tick: accumulate; at the end of a window take at most ONE step.

        The signal is the articles STORED per minute over the window (``articles_total`` is the pass's running count; R180): the
        thing the operator wants more of, and not the bytes the permits happen to move. A window is read once it has run
        ``MAXIMUM_WINDOW_S`` AND seen ``MAXIMUM_WINDOW_SOURCES`` source completions (``sources_total``); until then the reason is
        ``thin``. With no article count at all (a caller that does not pass one) the signal falls back to the collector's mean
        bytes rate and the window record says so in ``signal``.

        Start low, climb one permit while the window's rate is above the previous window's by the margin, step back once after a
        climb that fell by the margin, and let a mostly-saturated window take one cut in place of its climb. The ceiling is the
        soft ``ramp_ceiling`` (``w_max`` unless a learned one is lower)."""
        cur = self._sem.permits
        w = self._win
        if w["t0"] is None:
            w["t0"], w["a0"], w["s0"] = now, articles_total, sources_total
        w["sum"] += collector_kbps
        w["n"] += 1
        w["writer"] += 1 if writer_saturated else 0
        w["cpu"] += 1 if cpu_saturated else 0
        if now - w["t0"] < self._window_s:
            self._last_reason = "settling"
            return cur, "settling"
        completions = None if sources_total is None or w["s0"] is None else max(0, sources_total - w["s0"])
        if completions is not None and completions < self._window_sources:
            # Long enough but too few completions to read a count: keep accumulating (the window is NOT reset), and say why.
            self._last_reason = "thin"
            return cur, "thin"
        n = max(1, w["n"])
        elapsed = max(now - w["t0"], 1e-6)
        mean_kbps = w["sum"] / n
        stored = max(0, articles_total - w["a0"]) if articles_total is not None and w["a0"] is not None else None
        unit = "articles/min" if stored is not None else "collector kbps"
        rate = stored * 60.0 / elapsed if stored is not None else mean_kbps
        saturated = max(w["writer"], w["cpu"]) / n
        prev = self._prev_rate if self._prev_unit == unit else None
        top = self.ramp_ceiling
        held_by_learned = top < self.w_max
        # Only the window right AFTER a climb may step back: whatever this window does, the next one is not "after a climb"
        # unless this one climbed.
        climbed_before, self._climbed = self._climbed, False
        new, reason = cur, "hold"
        if saturated >= MAXIMUM_CUT_SHARE:
            if cur > 1:
                new = cur - 1
                reason = "writer-saturated" if w["writer"] >= w["cpu"] else "cpu-saturated"
            else:
                # The cut REPLACES the climb. At the floor there is nothing to cut, and climbing on a saturated window would
                # add the permit the next window takes back.
                reason = "saturated-at-floor"
        elif rate <= 0.0:
            # Nothing stored in the window: there is no rate to compare, so no climb on it and no baseline taken from it.
            reason = "no-articles"
        elif prev is None or rate > prev * (1.0 + self._margin):
            if cur < top:
                new, reason = cur + 1, "hill-up"
                self._climbed = True
            else:
                # Name WHICH ceiling is holding: reporting "at-ceiling" while sitting at 4 of a configured 50 would read as the
                # operator's setting being met.
                reason = "at-learned-ceiling" if held_by_learned else "at-ceiling"
        elif rate < prev * (1.0 - self._margin) and climbed_before and cur > 1:
            new, reason = cur - 1, "hill-back"
        self.last_window = {
            "signal": unit,
            "rate": round(rate, 1),
            "prev_rate": None if prev is None else round(prev, 1),
            "articles": stored,
            "sources": completions,
            "elapsed_s": round(elapsed, 1),
            "collector_kbps": round(mean_kbps, 1),
            "ticks": w["n"],
            "writer_saturated_share": round(w["writer"] / n, 2),
            "cpu_saturated_share": round(w["cpu"] / n, 2),
            "decision": reason,
        }
        if new != cur:
            self._sem.set_permits(new)
            self._last_adjust = now
        if rate > 0.0 and reason != "hill-back":
            # A window that fell and was stepped back from is not the baseline: taking its rate would let the permit count that
            # was just given up beat it by the margin and be climbed to again, and the rule would spend every other window
            # at the worse count. The better rate stays the baseline until a window at the count it went back to replaces it.
            self._prev_rate, self._prev_unit = rate, unit
        self._reset_window()
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
            "last_window": self.last_window,
        }
