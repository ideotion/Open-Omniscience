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

import logging
import threading
import time
from collections.abc import Callable

_LOG = logging.getLogger(__name__)

# Seconds after which a step is worth a warning in the error log: long enough that the warm-up
# and an ordinary rollup never trip it, short enough that a build that holds the re-index back
# for the afternoon is on record while it is still running.
SLOW_STEP_S = 300.0

# The steps, in the order they run. A step's state: pending | running | done | failed | skipped.
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
    with _LOCK:
        began = _SEQUENCE["started_at"]
        steps = []
        for name in STEPS:
            row = dict(_STEPS[name])
            if row["state"] == "running" and row["started_at"] is not None:
                row["seconds"] = round(now - float(row["started_at"]), 1)  # type: ignore[arg-type]
            elif row["state"] == "pending" and began is not None:
                row["waited_s"] = round(now - float(began), 1)  # type: ignore[arg-type]
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
                "No timeout: a step that does not end shows here as running, with its seconds."
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


def _timed(name: str, step: Callable[[], None], *, holds: str) -> None:
    mono = time.monotonic()
    with _LOCK:
        _STEPS[name].update(state="running", started_at=time.time())
    state = "done"
    try:
        step()
    except _Skipped:
        state = "skipped"
    except Exception:  # noqa: BLE001 - a start-up step must never take the others down
        state = "failed"
        _LOG.warning("boot step %s failed; the next step still runs", name, exc_info=True)
    finally:
        took = time.monotonic() - mono
        with _LOCK:
            _STEPS[name].update(state=state, seconds=round(took, 1))
    if took >= SLOW_STEP_S:
        _LOG.warning("boot step %s took %.0f s; %s waited behind it", name, took, holds)
    else:
        _LOG.info("boot step %s took %.1f s", name, took)


class _Skipped(Exception):  # noqa: N818 - a signal, not an error
    """A step that had nothing to do: recorded as skipped, not failed."""


def _rollup_first_build() -> None:
    from src.analytics import rollup_serve

    if not rollup_serve.serve_enabled():
        raise _Skipped
    rollup_serve.build_now_and_wait()


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
