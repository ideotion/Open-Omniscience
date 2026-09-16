"""
Owner-measured bytes-over-time for a file download (PERF-09).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS, and why it is a MODULE rather than two loops. Per-job rate and
ETA were a stated, reasoned omission (``CLAUDE.md`` UI invariant #20): "the
owners report only bytes/percent, NOT a rate; an honest rate needs
owner-measured bytes-over-time in the manager -- never a client-side guess
across the adaptive poll". That omission was right, and this is the thing it
asked for: the measurement is taken HERE, in the download loop, at the instant
bytes arrive, by the only party that can see them.

A client-side rate cannot be honest, and the reason is structural rather than a
matter of care: the task-manager poll is ADAPTIVE, so a browser dividing two
observed byte counts by two observed clock readings is measuring its own polling
jitter as much as the transfer -- and it cannot see a pause at all, so a resumed
download would be charged for the time it spent stopped.

WHAT IT REFUSES TO SAY, which is most of the design:

  * **An unmeasurable rate is ABSENT, never 0.** ``0 B/s`` reads as "stalled",
    which is a different fact from "not measured yet", and the recorded
    ``.get(key, 0)`` family is exactly this defect: a default that invents the
    measurement the omission exists to prevent. Every snapshot carries
    ``measured`` plus a ``reason`` when it is False.
  * **A stale rate is not a rate.** Samples are pruned against a FRESH clock
    reading at READ time, not only when bytes arrive -- so a download whose
    bytes stopped ages out of its own window and reports "no bytes received in
    the last N s" with the idle time, rather than repeating its last healthy
    figure forever. A frozen instrument that keeps publishing is worse than one
    that stops.
  * **A pause is not slow.** ``reset()`` on start/resume clears the window, so a
    resumed transfer is never charged for the minutes (or days) it sat paused.
  * **Nothing here is persisted.** A rate restored from a state file after a
    restart describes a transfer that is no longer happening; after a restart a
    download is honestly unmeasured until new bytes arrive.
  * **An ETA needs BOTH halves.** It is published only when a rate was really
    measured AND the server gave a real ``Content-Length``; a percentage-derived
    or catalog-estimate-derived ETA would be a fabricated countdown of the kind
    invariant #20 already refuses for the scheduler.

The BANDWIDTH CAP is deliberately NOT here. Throttling is a change to the fetch
loop's behaviour, not a measurement, and it is sequenced after this by the
throughput brief; what it would need is written down in the PR rather than
half-built.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections import deque

#: How far back a rate may look. Long enough to smooth a 1 MiB chunk boundary,
#: short enough that the figure describes the transfer NOW rather than its
#: average since it started.
_DEFAULT_WINDOW_S = 20.0
#: Below this span the division is arithmetic noise rather than a measurement --
#: two samples a few milliseconds apart produce a spectacular and meaningless
#: number. Refusing is the honest answer for the first moments of a download.
_MIN_SPAN_S = 1.0
#: A hard bound on retained samples, so a fast transfer cannot grow this
#: unboundedly between reads. The reported window is the span the retained
#: samples ACTUALLY cover, never the nominal one -- a bound that silently
#: shortens the window must not silently misreport it.
_MAX_SAMPLES = 512

#: What the published figure means, in the payload, beside the figure.
METHOD = (
    "bytes received by the download worker itself, divided by the wall time "
    "between the first and last sample still inside the window"
)


class RateSampler:
    """Bytes-over-time for ONE download, measured by its own worker.

    Thread-safe: ``observe`` is called from the download thread and ``snapshot``
    from whichever thread serves ``/api/jobs``.
    """

    def __init__(
        self,
        *,
        window_s: float = _DEFAULT_WINDOW_S,
        min_span_s: float = _MIN_SPAN_S,
        max_samples: int = _MAX_SAMPLES,
        clock=time.monotonic,
    ) -> None:
        self._window_s = float(window_s)
        self._min_span_s = float(min_span_s)
        self._clock = clock  # injected in tests; monotonic in production
        self._lock = threading.Lock()
        self._samples: deque[tuple[float, int]] = deque(maxlen=max(2, int(max_samples)))
        self._last_at: float | None = None

    # -- writing (download thread) ----------------------------------------- #

    def reset(self, downloaded_bytes: int = 0) -> None:
        """Start a fresh measurement window at ``downloaded_bytes``.

        Called on every start AND resume: a resumed download must not be charged
        for the time it spent paused, and its partial-file byte count is a
        starting point rather than progress made just now.
        """
        with self._lock:
            self._samples.clear()
            self._last_at = None
            self._samples.append((self._clock(), max(0, int(downloaded_bytes))))

    def observe(self, downloaded_bytes: int) -> None:
        """Record the CUMULATIVE byte count after a chunk landed.

        A count that goes BACKWARDS means the transfer restarted from zero (a
        200 where a 206 was asked for), so the window is opened afresh rather
        than kept. Comparing only the window's first and last sample would not
        catch that -- a restart in the MIDDLE leaves first<last, so the rate
        would come out positive, plausible and wrong (it would charge the bytes
        received since the restart against the whole window, understating the
        real rate). The check therefore belongs on every observation, not on the
        pair that happens to bound the window.
        """
        now = self._clock()
        b = max(0, int(downloaded_bytes))
        with self._lock:
            if self._samples and b < self._samples[-1][1]:
                self._samples.clear()
            self._samples.append((now, b))
            self._last_at = now
            self._prune(now)

    # -- reading (API thread) ---------------------------------------------- #

    def snapshot(self, *, total_bytes: int | None = None, done_bytes: int | None = None) -> dict:
        """The measurement, or an honest account of why there isn't one.

        ``total_bytes``/``done_bytes`` are supplied by the caller because the
        ETA is only meaningful against the server's REAL ``Content-Length``; a
        catalog size estimate must never become a countdown.
        """
        now = self._clock()
        with self._lock:
            self._prune(now)
            samples = list(self._samples)
            last_at = self._last_at

        if not samples:
            if last_at is not None:
                # EVERYTHING aged out: bytes really have stopped arriving. That
                # is a measurement of a DIFFERENT quantity, and it is the one an
                # operator watching a stuck download wants.
                return {
                    "measured": False,
                    "reason": f"no bytes received in the last {self._window_s:g} s",
                    "idle_s": round(now - last_at, 1),
                }
            return {"measured": False, "reason": "no bytes observed yet"}
        if len(samples) < 2:
            # ONE sample: a window that just opened (a start, a resume, or a
            # restart detected in observe). Deliberately NOT folded into the
            # stalled branch above -- an idle_s of ~0 beside "no bytes received"
            # would describe a transfer that is in fact perfectly healthy and
            # merely young.
            return {"measured": False, "reason": "only one sample in the window so far"}

        span = samples[-1][0] - samples[0][0]
        if span < self._min_span_s:
            return {
                "measured": False,
                "reason": f"measured over {span:.2f} s, under the {self._min_span_s:g} s floor",
            }
        # No negative-delta branch: ``observe`` opens a fresh window the moment
        # the count goes backwards, so the retained samples are non-decreasing by
        # construction and such a branch would be unreachable. An unreachable
        # refusal with a test written for it is a guard that cannot fail.
        rate = (samples[-1][1] - samples[0][1]) / span
        out: dict = {
            "measured": True,
            "bytes_per_s": round(rate, 1),
            "window_s": round(span, 2),
            "samples": len(samples),
            "method": METHOD,
        }
        # The ETA rides ONLY on a measured rate AND a real total. Both halves
        # are checked here rather than by each caller, so a caller cannot get
        # one right and the other wrong.
        if total_bytes and done_bytes is not None and rate > 0:
            remaining = int(total_bytes) - int(done_bytes)
            if remaining > 0:
                out["eta_seconds"] = round(remaining / rate, 1)
        return out

    # -- internals ---------------------------------------------------------- #

    def _prune(self, now: float) -> None:
        """Drop samples older than the window. Called on BOTH write and read:
        pruning only on write would let a stalled download keep reporting the
        last healthy rate for as long as nobody sent it another byte."""
        cutoff = now - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


#: Every ``RateRegistry`` built in this process, so the per-process budget can
#: enumerate the file downloads without reaching into the two job managers that
#: own them. A WEAK set: a manager that is garbage-collected takes its registry
#: with it, and a stale entry would otherwise keep reporting a download that no
#: longer exists.
#:
#: This is deliberately NOT a second measurement. The bytes are still counted by
#: the worker that receives them, exactly as this module's header requires; the
#: registry-of-registries only makes the owners' OWN numbers enumerable from one
#: place, which is what "per-process" needs and what a machine-wide network gauge
#: would get wrong (a NIC counter sees every other tenant's traffic as ours).
_REGISTRIES: weakref.WeakSet = weakref.WeakSet()

#: Guards ADDING to the set against SNAPSHOTTING it. Removals need no guard --
#: ``WeakSet`` already defers those through its own ``_IterationGuard`` -- but
#: ``add()`` writes straight through, so a registry constructed on one thread while
#: another is taking the snapshot raises ``RuntimeError: Set changed size during
#: iteration``. Live-reproduced against the real constructor and the real reader
#: (not a lookalike) in about a second of contention.
#:
#: The raise lands OUTSIDE the per-registry try/except below -- it happens while the
#: loop is being entered, not inside it -- so it escapes ``process_download_rate``,
#: escapes ``compose``, and is swallowed only by the perf monitor's outermost
#: DEBUG-level handler: that tick contributes no sample AND the governor is never
#: asked to observe. A lock is the fix rather than a wider ``except`` because
#: catching it would still lose the tick, and the window is real: a bulk download
#: starting while a collection pass runs is the exact scenario this slice is about.
_REGISTRIES_LOCK = threading.Lock()


class RateRegistry:
    """One sampler per download key, shared by the wiki-dump and OSM managers.

    Both managers grew the same download loop independently; giving them ONE
    registry is what stops the measurement existing on one and not the other --
    the recorded "a fix at one of two call sites is not fixing it" shape, which
    has already bitten these two managers' backup and resume paths.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, RateSampler] = {}
        with _REGISTRIES_LOCK:
            _REGISTRIES.add(self)

    def start(self, key: str, downloaded_bytes: int = 0) -> RateSampler:
        with self._lock:
            s = self._by_key.get(key)
            if s is None:
                s = self._by_key[key] = RateSampler()
        s.reset(downloaded_bytes)
        return s

    def get(self, key: str) -> RateSampler | None:
        with self._lock:
            return self._by_key.get(key)

    def forget(self, key: str) -> None:
        with self._lock:
            self._by_key.pop(key, None)

    def snapshot(self, key: str, **kw) -> dict:
        s = self.get(key)
        if s is None:
            # Never measured in THIS process: a download that finished before a
            # restart, or one that has not started. Distinct from "measured and
            # zero", and distinct from "stalled".
            return {"measured": False, "reason": "not measured in this session"}
        return s.snapshot(**kw)

    # -- process-wide aggregation (S04-13 S1) ------------------------------- #

    def live_rates(self) -> list[dict]:
        """Every sampler's snapshot, measured or not.

        Used by the per-process budget to sum the bytes THIS PROCESS is pulling
        through its file downloads. The refusals are the samplers' own -- this
        adds no judgement of its own, and in particular never turns an
        unmeasurable sampler into a zero.
        """
        with self._lock:
            samplers = list(self._by_key.items())
        return [dict(s.snapshot(), key=k) for k, s in samplers]




def process_download_rate() -> dict:
    """Bytes/s this process is pulling through its FILE downloads, right now.

    Sums only the samplers that are genuinely measuring. The result distinguishes
    three states that a single number cannot:

      * ``measured: True``  -- at least one download is measurable; ``bytes_per_s``
        is the sum over those, and ``unmeasured`` names the ones left out.
      * ``measured: False`` with ``reason`` -- downloads exist but none of them can
        be measured yet (all too young, all stalled, all just restarted).
      * ``measured: False, idle: True`` -- there are no downloads at all, which is a
        real observation and NOT the same as an unmeasurable one.

    ``bytes_per_s`` is therefore a LOWER BOUND on what the process is pulling
    whenever ``unmeasured`` is non-empty. For a BUDGET -- a ceiling -- a lower
    bound is the safe direction to act on: if what we could measure already
    exceeds the ceiling, the true total certainly does. The opposite reading
    (treating an unmeasurable download as zero) is the fabricated measurement
    this module exists to refuse, so the count is published beside the sum.
    """
    total = 0.0
    measured_n = 0
    unmeasured: list[dict] = []
    with _REGISTRIES_LOCK:
        registries = list(_REGISTRIES)
    for reg in registries:
        try:
            rows = reg.live_rates()
        except Exception:  # noqa: BLE001 - a faulty registry must not blank the budget
            continue
        for row in rows:
            if row.get("measured"):
                total += float(row.get("bytes_per_s") or 0.0)
                measured_n += 1
            else:
                unmeasured.append(
                    {"key": row.get("key"), "reason": row.get("reason") or "unmeasured"}
                )
    if measured_n:
        return {
            "measured": True,
            "bytes_per_s": round(total, 1),
            "downloads_measured": measured_n,
            "unmeasured": unmeasured,
            "method": METHOD,
        }
    if unmeasured:
        return {
            "measured": False,
            "reason": "downloads are running but none is measurable yet",
            "downloads_measured": 0,
            "unmeasured": unmeasured,
        }
    return {
        "measured": False,
        "idle": True,
        "reason": "no file download is running",
        "downloads_measured": 0,
        "unmeasured": [],
    }
