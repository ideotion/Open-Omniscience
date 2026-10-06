"""Boot order: the three heavy start-up jobs run one after the other, not all at once.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (diagnostics 2026-09-30, the crashing instance, cause C). Every restart began the
insights cache warm-up, the in-memory keyword rollup and the re-index resume within the same
minute: four threads had used 56.8 s, 52.0 s and 35.4 s of CPU by the time the machine had 1 GB
free, and thirteen minutes after boot the rollup was still building. Three whole-corpus jobs
side by side are three working sets in memory at once and three claims on the write gate, and
the process was SIGKILLed with all of them running.

THE ORDER, and why. (1) the cache warm-up: about a minute, and what makes Home fast; (2) the
rollup's first build: the biggest read, which analytics need and which the warm-up's own reads
kick off; (3) the re-index resume: it owes hours and holds the write gate, so it goes last. After
the first run of each the order no longer applies: a rollup rebuilt later for a changed corpus, or
a re-index the operator starts, run as before. Nothing is slowed for good. A rollup that a serve
kicks AFTER the re-index has started builds beside it, as it always did; it already declines when
memory is short, and ``snapshot()`` says so rather than adding a wait. A later start-up job (the
keyword recompute, T3) takes its place in ``STEPS``, after the re-index; none is wired yet.

NO TIMEOUT. A step that never ends keeps the later ones waiting; that step is the fault and has to
be seen, not bypassed. Two things make it seen: a step that takes five minutes or more is logged as
a WARNING (the rolling error log keeps warnings) naming what it held up, and ``snapshot()`` (the
diagnostics bundle's columnar.json) says for every step its state, when it started and how long it
has run or waited. A step that raises, is skipped or declines always releases the next one: each
ends in a ``finally``.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable

_LOG = logging.getLogger(__name__)

# Seconds after which a step is worth a warning in the error log: long enough that the warm-up
# and an ordinary rollup never trip it, short enough that a build that holds the re-index back
# for the afternoon is on record while it is still running.
SLOW_STEP_S = 300.0

# The steps, in the order they run. A step's state: pending | running | done | failed | skipped | declined.
STEPS = ("warm-cache", "rollup", "reindex-resume")

_LOCK = threading.Lock()
_STATE: dict[str, object] = {"warm": "pending", "reindex_pending": None}
_STEPS: dict[str, dict[str, object]] = {}
_SEQUENCE: dict[str, object] = {"started_at": None}


def _reset() -> None:
    with _LOCK:
        _STEPS.clear()
        _STEPS.update({n: {"state": "pending", "started_at": None, "seconds": None} for n in STEPS})
        _SEQUENCE["started_at"] = None


_reset()


def snapshot() -> dict:
    """Where the boot sequence is, for the diagnostics bundle: per step its state, when it started
    (UTC) and the seconds it has run (a running step) or took (a finished one); for a pending step
    the seconds it has waited behind the earlier ones. Counts and times only, no score."""
    now = time.time()
    progress = _progress_of("rollup")  # read before _LOCK: the build holds its own lock briefly, never this one
    with _LOCK:
        began = _SEQUENCE["started_at"]
        steps = []
        for name in STEPS:
            row = dict(_STEPS[name])
            if row["state"] == "running" and row["started_at"] is not None:
                row["seconds"] = round(now - float(row["started_at"]), 1)  # type: ignore[arg-type]
            elif row["state"] == "pending" and began is not None:
                row["waited_s"] = round(now - float(began), 1)  # type: ignore[arg-type]
            if name == "rollup" and row["state"] == "running" and progress is not None:
                row["progress"] = progress
            if row["started_at"] is not None:
                row["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(row["started_at"])))  # type: ignore[arg-type]
            steps.append({"step": name, **row})
        return {
            "order": list(STEPS),
            "steps": steps,
            "reindex_requested": _STATE["reindex_pending"],
            "method": (
                "The three heavy start-up jobs run one after the other. A rollup a serve kicks after "
                "the re-index has started builds beside it, and declines when memory is short. "
                "No timeout: a step that does not end shows here as running, with its seconds; the rollup step "
                "also shows its build's stage, rows streamed, rows/s and seconds since it last moved, and the "
                f"log says so when it has not moved for {SLOW_STEP_S:.0f} s (checked every {SLOW_STEP_S:.0f} s)."
            ),
        }


def request_reindex(articles_pending: int) -> None:
    """Ask for the re-index resume to start at the end of the sequence (it is not started here)."""
    with _LOCK:
        _STATE["reindex_pending"] = int(articles_pending)


def warm_running() -> bool:
    """True from the sequence's start until its warm-up step ends: the rollup declines meanwhile."""
    with _LOCK:
        return _STATE["warm"] == "running"


def heavy_step_verdict() -> dict | None:
    """The decline a serve-kicked heavy build (the map coverage serve, the rollup) answers with
    while the boot's cache warm-up or rollup step runs, else ``None``."""
    with _LOCK:
        busy = _STATE["warm"] == "running" or _STEPS["rollup"]["state"] == "running"
    if busy:
        return {
            "reason": "boot_order",
            "detail": "the start-up cache warm-up or rollup build is running; this build waits its turn",
        }
    return None


#: The steps that carry their own progress channel (see ``_progress_of``).
_PROGRESS_STEPS = frozenset({"rollup"})


def _progress_of(name: str) -> dict | None:
    """What the step reports about its own progress: today only the rollup build does (rows streamed, the
    rate and when it last moved). ``None`` for a step with no progress channel, or when none is readable."""
    if name not in _PROGRESS_STEPS:
        return None
    try:
        from src.analytics import rollup_serve

        return rollup_serve.build_progress()
    except Exception:  # noqa: BLE001 - a missing reading is no information, never an error
        return None


def _progress_text(p: dict) -> str:
    rate = f" at {p['rows_per_s']:,} rows/s" if p.get("rows_per_s") else ""
    return f"{p['stage']}: {p['rows_done']:,} rows{rate}, last moved {p['idle_s']:.0f} s ago"


def _warn_still_running(name: str, holds: str) -> None:
    p = _progress_of(name)
    _LOG.warning(
        "boot step %s is still running after %.0f s; %s waiting behind it%s",
        name, SLOW_STEP_S, holds, f" ({_progress_text(p)})" if p else "",
    )


class _SlowWatch:
    """The warning for a step that runs long, re-armed for as long as the step runs.

    It speaks once when the step passes ``SLOW_STEP_S`` (it is still running, and what it reports), then
    every ``SLOW_STEP_S`` after that ONLY when the step's own progress has not moved for that long: a build
    that is streaming rows is slow, a build that has stopped moving is stuck, and the log should say which.
    A step with no progress channel is warned about once, as before."""

    def __init__(self, name: str, holds: str) -> None:
        self.name, self.holds = name, holds
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._stopped = False
        self._first = True

    def start(self) -> None:
        self._arm()

    def _arm(self) -> None:
        timer = threading.Timer(SLOW_STEP_S, self._fire)
        timer.daemon = True
        with self._lock:
            if self._stopped:
                return
            self._timer = timer
        timer.start()

    def _fire(self) -> None:
        if self._first:
            self._first = False
            _warn_still_running(self.name, self.holds)
        else:
            p = _progress_of(self.name)
            if p is not None and p["idle_s"] >= SLOW_STEP_S:
                if p["stage"] == "aggregate":
                    # one statement over the whole staging table: it reports nothing until it ends, so
                    # the honest wording is "waiting on it", not "stuck"
                    _LOG.warning(
                        "boot step %s has been in its single aggregate statement for %.0f s, which reports no "
                        "progress while it runs; %s waiting behind it (%s)",
                        self.name, p["idle_s"], self.holds, _progress_text(p),
                    )
                else:
                    _LOG.warning(
                        "boot step %s has made no progress for %.0f s; %s waiting behind it (%s)",
                        self.name, p["idle_s"], self.holds, _progress_text(p),
                    )
        if self.name not in _PROGRESS_STEPS:
            return  # nothing more it could ever report: one warning, as before
        with contextlib.suppress(RuntimeError):  # a machine too starved for a thread ends the watch quietly
            self._arm()

    def cancel(self) -> None:
        with self._lock:
            self._stopped = True
            timer = self._timer
        if timer is not None:
            timer.cancel()


def _timed(name: str, step: Callable[[], None], *, holds: str) -> None:
    mono = time.monotonic()
    with _LOCK:
        _STEPS[name].update(state="running", started_at=time.time())
    state = "failed"  # until the step returns: a BaseException that ends it must not read as done
    # The warning is logged WHILE a step is still running, so one that never ends is on record too.
    slow = _SlowWatch(name, holds)
    try:
        # Inside the try: a machine too starved to start a thread must not leave the step "running"
        # for ever (that would hold every later step, and the map serve's heavy-step verdict, up).
        with contextlib.suppress(RuntimeError):
            slow.start()
        step()
        state = "done"
    except _Skipped as skipped:
        state = skipped.state
    except Exception:  # noqa: BLE001 - a start-up step must never take the others down
        _LOG.warning("boot step %s failed; the next step still runs", name, exc_info=True)
    finally:
        slow.cancel()
        took = time.monotonic() - mono
        with _LOCK:
            _STEPS[name].update(state=state, seconds=round(took, 1))
    if took >= SLOW_STEP_S:
        _LOG.warning("boot step %s took %.0f s; %s waited behind it", name, took, holds)
    else:
        _LOG.info("boot step %s took %.1f s", name, took)


class _Skipped(Exception):  # noqa: N818 - a signal, not an error
    """A step that ended without doing its work: recorded as ``skipped`` (nothing to do) or
    ``declined`` (it was refused, e.g. for memory), never as ``done`` and never as ``failed``."""

    def __init__(self, state: str = "skipped") -> None:
        super().__init__(state)
        self.state = state


def _rollup_first_build() -> None:
    from src.analytics import rollup_serve

    if not rollup_serve.serve_enabled():
        raise _Skipped
    outcome = rollup_serve.build_now_and_wait()
    if outcome == "declined":
        raise _Skipped("declined")
    if outcome == "failed":
        raise RuntimeError("the rollup's first build failed (see the rollup_serve block)")
    if outcome != "built":  # only a build that happened reads as done, whatever else comes back
        raise RuntimeError(f"the rollup's first build reported {outcome!r}, not a finished build")


def _start_reindex() -> None:
    with _LOCK:
        pending = _STATE["reindex_pending"]
    if pending is None:
        raise _Skipped
    from src.backup.volume_job import start_reindex_drain

    started, detail = start_reindex_drain()
    _LOG.info(
        "boot re-index auto-resume: %s (%s article(s) pending)",
        "started" if started else f"not started ({detail})", pending,
    )
    if not started:
        raise _Skipped("declined")


def run(warm: Callable[[], None]) -> None:
    """The sequence, in the calling thread: warm-up, rollup first build, re-index resume."""
    with _LOCK:
        _STATE["warm"] = "running"
        _SEQUENCE["started_at"] = time.time()
    try:
        _timed("warm-cache", warm, holds="the rollup build and the re-index")
    finally:
        with _LOCK:
            _STATE["warm"] = "done"
    _timed("rollup", _rollup_first_build, holds="the re-index")
    _timed("reindex-resume", _start_reindex, holds="nothing")
