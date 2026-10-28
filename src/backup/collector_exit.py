"""A restore confirms the collector has left the corpus before it copies it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP THIS CLOSES
-------------------
An import runs inside ``runner.exclusive_window()`` (or, for one volume restore,
``pause_for_exclusive_operation()``). Both stop the collector the same way: signal the
``oo-scheduler`` loop and join it for a bounded time (``BackgroundScheduler.stop``, 10 s by
default). A pass has no stop check inside it, only between passes, so a pass deep in a write can
outlive that join by minutes (``runner.resume_after_exclusive_operation`` records one that took 39
minutes to wind down on a write-bound machine), and a pass started by "Run now" before the window
opened is not touched at all: the window only blocks the NEXT ``run_now``. The window's return was
read as "collection is paused", and the restore copied the corpus, merged into the copy and swapped
the copy in. Whatever a lingering pass committed to the live file after the copy was taken is
discarded by the swap (the copy is the new corpus; ``merge.py`` states that loss where it is made).

WHAT THIS DOES
--------------
``wait_for_collector_exit`` looks at the scheduler (the loop thread, and a pass in flight) and
waits, bounded, for both to be gone, BEFORE the working copy is taken. A pass that finishes inside
the wait lands its writes in the copy, so they survive. A pass still running when the bound ends is
NOT waited out further and is NOT hidden: the answer says ``confirmed: False`` and names what was
still executing, the restore carries that in its report, and the import dialog stops saying
collection is paused. The restore goes on, because the pause is a courtesy and an import is the
point (``volume_job``, ``import_queue._run``); the report says what that costs.

It does not stop anything and it takes no lock: it only reads. It is not a statement about any
OTHER writer (the housekeeping lane, the Wikipedia drain, registered background jobs, the API
write routes, boot upkeep): the window never stopped those and this does not look for them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

_LOG = logging.getLogger(__name__)

#: How long a restore waits for a collection pass that was still running when the pause was asked
#: for. What it protects: the start of the copy, from hanging behind a pass that never exits. It is
#: the resume side's own budget (``resume_after_exclusive_operation``: 19 retries x 30 s = 570 s,
#: itself chosen to exceed the 438 s worst single blocked write that project measured), rounded up.
#: A pass that outlives it is the 39-minute wind-down case: the restore goes on and says so.
COLLECTOR_EXIT_WAIT_S = 600.0

#: How often the wait looks again. What it protects: a Stop pressed during the wait, which is
#: read once per look (an import's Stop must not sit behind a pass for ten minutes).
COLLECTOR_EXIT_POLL_S = 1.0


def collector_activity() -> tuple[list[str], str | None]:
    """What of the collector is executing right now, and why that could not be read (or None).

    ``([], None)``: nothing is. ``(names, None)``: those are. ``([], reason)``: the scheduler could
    not be read, which is NOT the same as "idle" and is never reported as it."""
    try:
        from src.scheduler.runner import get_scheduler

        sched = get_scheduler()
        names: list[str] = []
        if sched.is_running():
            names.append("the collection loop")
        # A pass started by "Run now" runs on its own thread and leaves the loop stopped, so the
        # loop's thread alone would call it idle. ``active`` is the scheduler's own busy flag
        # (set by every pass and by off-peak maintenance, under its state lock).
        lock = getattr(sched, "_state_lock", None)
        if lock is not None:
            with lock:
                busy = bool(getattr(sched, "_active", False))
        else:
            busy = bool(getattr(sched, "_active", False))
        if busy:
            names.append("a collection pass")
        return names, None
    except Exception as exc:  # noqa: BLE001 - a probe that cannot look says so, it never raises into a restore
        # The class only: the words of an exception can carry a path or a driver's text, and this
        # string goes into the report and the run log.
        return [], f"the scheduler could not be read ({type(exc).__name__})"


def wait_for_collector_exit(
    *,
    should_stop: Callable[[], bool] | None = None,
    timeout: float | None = None,
    poll_s: float | None = None,
) -> dict:
    """Wait, bounded, until no collection pass is executing. Returns what was found:

    ``confirmed``  True: at the last look nothing of the collector was executing. False: the
                   bound ended with something executing (``still`` names it). None: the
                   scheduler could not be read (``reason`` says why), which is not "idle".
    ``waited_s``   seconds spent waiting (0.0 when nothing was running at the first look).
    ``bound_s``    the bound that applied.
    ``still``      names of what was executing at the last look.

    A Stop (``should_stop``) ends the wait at the next look; the caller re-checks its own abort
    point straight after, so a Stop is never read as an answer here."""
    bound = float(COLLECTOR_EXIT_WAIT_S if timeout is None else timeout)
    step = max(0.001, float(COLLECTOR_EXIT_POLL_S if poll_s is None else poll_s))
    t0 = time.monotonic()
    still, why = collector_activity()
    # The R161 shape: the condition is tested inside the loop body, so the back-edge is not
    # the only place the exit is decided.
    while True:
        if why is not None or not still:
            break
        if should_stop is not None and should_stop():
            break
        left = bound - (time.monotonic() - t0)
        if left <= 0:
            break
        time.sleep(min(step, left))
        still, why = collector_activity()
    waited = time.monotonic() - t0
    out: dict = {"confirmed": None, "waited_s": round(waited, 1), "bound_s": bound, "still": list(still)}
    if why is not None:
        out["reason"] = why
        _LOG.warning("could not confirm that background collection has left the corpus: %s", why)
    elif not still:
        out["confirmed"] = True
    else:
        out["confirmed"] = False
        _LOG.warning(
            "%s still running %.0f s after the import asked collection to pause; the import goes on "
            "and its report says so",
            " and ".join(still), waited,
        )
    return out
