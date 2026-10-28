"""A restore confirms the collector has left the corpus before it copies it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP THIS CLOSES
-------------------
An import runs inside ``runner.exclusive_window()`` (or, for one volume restore,
``pause_for_exclusive_operation()``). Both stop the collector the same way: signal the
``oo-scheduler`` loop and join it for a bounded time (``BackgroundScheduler.stop``, 10 s by
default). A pass checks its stop flag between sources, not inside a write, so a pass deep in a write
can outlive that join by minutes (``runner.resume_after_exclusive_operation`` records one that took 39
minutes to wind down on a write-bound machine). And ``stop()`` signals only a RUNNING loop: a pass
started by "Run now" before the window opened, on a loop that was not running, is never asked to stop
and is not touched at all (the window only blocks the NEXT ``run_now``). The window's return was read
as "collection is paused", and the restore copied the corpus, merged into the copy and swapped the copy
in. Whatever a lingering pass committed to the live file after the copy was taken is discarded by the
swap (the copy is the new corpus; ``merge.py`` states that loss where it is made).

WHAT THIS DOES
--------------
``wait_for_collector_exit`` looks at the scheduler (the loop thread, and a pass or maintenance run in
flight) and waits, bounded, for both to be gone, BEFORE the working copy is taken. A pass that finishes
inside the wait lands its writes in the copy, so they survive. A pass still running when the bound ends
is NOT waited out further and is NOT hidden: the answer says ``confirmed: False`` and names what was
still executing, the restore carries that in its report, and the import dialog stops saying collection
is paused. The restore goes on, because the pause is a courtesy and an import is the point
(``volume_job``, ``import_queue._run``); the report says what that costs.

THE DIALOG READS IT WHILE THE RESTORE RUNS. The answer reaches the queue's status only in the item's
summary, which exists after the merge, the verification and the swap: hours after the wait. So the wait
also publishes itself in this module (``wait_state`` while it waits, ``last_answer`` once it has
answered), which ``ImportQueueManager.status()`` reads, and the dialog can say "waiting for a collection
pass" during the wait and "could not confirm a pause" from the moment the wait gave up. It is
in-process state only (a restore and its dialog are one process); nothing is persisted from here.

STATED LIMITS (``runner.py``, which another lane owns). A pass started by "Run now" on a loop that was not running is
not signalled to stop (``BackgroundScheduler.stop`` returns before it sets the flag), so the wait watches it and spends its
bound if the pass is long; and ``BackgroundScheduler.start`` does not check the exclusive hold, so the Start button, the
network toggle or the unattended start can bring the loop back while an import runs. Neither makes this wait wrong: both
make it answer ``confirmed: False`` more often than a pass-scoped stop and a checked ``start`` would.

It does not stop anything and it takes no lock on the corpus: it only reads. It is not a statement about
any OTHER writer (the housekeeping lane, the Wikipedia drain, registered background jobs, the API write
routes, boot upkeep): the window never stopped those and this does not look for them.
"""

from __future__ import annotations

import logging
import threading
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

# What the wait publishes for the dialog (see "THE DIALOG READS IT" above). Small dicts, replaced whole
# under the lock, copied on the way out.
_STATE_LOCK = threading.Lock()
_WAITING: dict | None = None
_LAST: dict | None = None
#: The wall clock for the published timestamps, bound here so a test that replaces this module's ``time`` with a stepped clock
#: (the waiting is measured on the monotonic one) does not also replace the clock the dialog compares ``at`` against.
_wall = time.time


def wait_state() -> dict | None:
    """The wait that is running right now, or None: ``{"since": epoch seconds, "still": [names], "bound_s": ...}``."""
    with _STATE_LOCK:
        return dict(_WAITING, still=list(_WAITING["still"])) if _WAITING else None


def last_answer() -> dict | None:
    """The answer of the most recent finished wait in this process, with ``at`` (epoch seconds), or None."""
    with _STATE_LOCK:
        return dict(_LAST, still=list(_LAST["still"])) if _LAST else None


def _publish(*, waiting: dict | None, answer: dict | None = None) -> None:
    global _WAITING, _LAST
    with _STATE_LOCK:
        _WAITING = waiting
        if answer is not None:
            _LAST = dict(answer, at=_wall())


def collector_activity() -> tuple[list[str], str | None]:
    """What of the collector is executing right now, and why that could not be read (or None).

    ``([], None)``: nothing is. ``(names, None)``: those are. ``([], reason)``: the scheduler could
    not be read, which is NOT the same as "idle" and is never reported as it. ``_active`` is the
    scheduler's own busy flag; it is set by a collection pass AND by off-peak maintenance (both write
    the corpus), which is why the second name says so."""
    try:
        from src.scheduler.runner import get_scheduler

        sched = get_scheduler()
        names: list[str] = []
        if sched.is_running():
            names.append("the collection loop")
        # A pass started by "Run now" runs on its own thread and leaves the loop stopped, so the
        # loop's thread alone would call it idle. ``_active`` is read under the scheduler's state lock.
        lock = getattr(sched, "_state_lock", None)
        if lock is not None:
            with lock:
                busy = bool(getattr(sched, "_active", False))
        else:
            busy = bool(getattr(sched, "_active", False))
        if busy:
            names.append("a collection pass or maintenance run")
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
                   bound ended, or a Stop ended the wait, with something executing (``still``
                   names it). None: the scheduler could not be read (``reason`` says why),
                   which is not "idle".
    ``waited_s``   seconds spent waiting (0.0 when nothing was running at the first look).
    ``bound_s``    the bound that applied.
    ``still``      names of what was executing at the last look.
    ``stopped``    present and True when a Stop, not the bound, ended the wait.

    A Stop (``should_stop``) ends the wait at the next look; the caller re-checks its own abort
    point straight after, so a Stop is never read as an answer here."""
    bound = float(COLLECTOR_EXIT_WAIT_S if timeout is None else timeout)
    step = max(0.001, float(COLLECTOR_EXIT_POLL_S if poll_s is None else poll_s))
    t0 = time.monotonic()
    stopped = False
    still, why = collector_activity()
    try:
        # Every exit is decided in the body, in the order: answered, Stop, bound.
        while True:
            if why is not None or not still:
                break
            _publish(waiting={"since": _wall() - (time.monotonic() - t0), "still": list(still), "bound_s": bound})
            if should_stop is not None and should_stop():
                stopped = True
                break
            left = bound - (time.monotonic() - t0)
            if left <= 0:
                break
            time.sleep(min(step, left))
            still, why = collector_activity()
    finally:
        _publish(waiting=None)
    waited = time.monotonic() - t0
    out: dict = {"confirmed": None, "waited_s": round(waited, 1), "bound_s": bound, "still": list(still)}
    if stopped:
        out["stopped"] = True
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
    _publish(waiting=None, answer=out)
    return out
