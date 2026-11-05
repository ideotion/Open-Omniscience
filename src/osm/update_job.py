"""The OSM lane's daily-update job: the one place a person's "update this country" becomes a run of :func:`src.osm.apply.update_country`
(v0.6.0 B1, S06-01 S1, the job and consent layer).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS DOES THAT NOTHING ELSE DOES: it starts a fetch from the replication mirror. Everything under ``src/osm`` that reads the lane makes no
request; this module is the single entry, and it is gated three ways before a thread starts:

* the CONSENT: the caller says it went through the one online consent (``consent=True``), the same shape as the OpenTimestamps anchor
  (UI invariant #14f): a caller that never went through the page gets the same refusal as the page would;
* the KILL SWITCH: engaged means a named refusal, never a job that starts and then "fails";
* the COUNTRY: ``update_country`` itself refuses a country with no finished cut, no replication position or no kept border, by name.

One worker runs one country at a time (the lane has one writer); the others wait in order and show as queued. A job's record stays after it
ends so the task manager can say how it ended; starting the country again replaces it. Nothing is persisted: after a restart there is no job
to resume, and the country's own position (written in the same transaction as the objects) is where the next run starts.

Progress is real: files applied of files owed, counted by ``update_country`` after each file. There is no rate, no ETA and no percentage of
bytes (the size of a change file is read when it is fetched, not before), and the run has no bandwidth cap (invariant #20: the S04-13
per-process budget is the one rate authority).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: ``state`` values of a job record. ``done`` covers every ended run whatever its ``outcome`` (the outcome word says how it ended).
STATES = ("queued", "running", "done")


#: How a daily-update job ended, as the task manager's detail line and the Places page's status line. Each is a locale key (x12), a fixed sentence: the specific ``reason`` the
#: run gave is in ``/api/osm/updates`` and the diagnostics member, never printed here, because some of them quote the network's own words.
OUTCOME_SENTENCES = {
    "applied": "Updated to the newest daily change file.",
    "current": "Already up to date: the mirror has nothing newer.",
    "stopped": "Stopped before the end of the files owed; the next update continues from here.",
    "refused": "Refused: airplane mode or protected mode stopped the fetch. Nothing was changed.",
    "unavailable": "The mirror could not be reached. Nothing was changed.",
    "mirror-unreadable": "The mirror's answer could not be read. Nothing was changed.",
    "rebaseline_needed": "The mirror no longer holds the files this country needs. Download its extract again.",
    "superseded": "Something else cut or updated this country meanwhile, so the file was not applied.",
    "failed": "A change file did not apply and was rolled back. The country stands at the last good file.",
    "not-ready": "This country cannot be updated as it is: it needs a finished cut with a recorded position.",
}


class UpdateRefused(Exception):  # noqa: N818 - a refusal, named by what refused it, like ``RebaselineRefused``
    """The request was refused before any job existed; ``str(exc)`` is the sentence to show, ``kind`` says which gate."""

    kind = "refused"

    def __init__(self, kind: str, text: str) -> None:
        super().__init__(text)
        self.kind = kind


class ConsentRefused(UpdateRefused):
    """No ``consent: true``: the page's one online consent did not run for this request."""

    def __init__(self, text: str) -> None:
        super().__init__("consent", text)


class KillSwitchRefused(UpdateRefused):
    """The network kill switch is engaged (airplane mode): a named refusal, never a job that starts and fails."""

    def __init__(self, text: str) -> None:
        super().__init__("kill-switch", text)


_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_QUEUE: list[str] = []
_WORKER: threading.Thread | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_source_for(region: str):
    from src.osm.replication import GuardedDiffSource

    return GuardedDiffSource(region)


def request_update(
    country: str,
    *,
    consent: bool,
    source_for: Callable[[str], Any] | None = None,
    kill_switch: Callable[[], bool] | None = None,
    run: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Queue an update of ``country`` (alpha-2 or alpha-3); returns the job record. Raises :class:`UpdateRefused` or ``ValueError``.

    ``source_for``, ``kill_switch`` and ``run`` are the seams the tests use (a fixture mirror, a switch, a synchronous runner); the
    defaults are the guarded mirror, the app's kill switch and a thread of the module's own.
    """
    from src.ingest import kill_switch_active
    from src.osm.apply import KILL_SWITCH_TEXT
    from src.osm.ingest import country_codes

    alpha2, alpha3 = country_codes(country)
    if not consent:
        raise ConsentRefused("this fetch needs the online consent; it was not given")
    if (kill_switch or kill_switch_active)():
        raise KillSwitchRefused(KILL_SWITCH_TEXT)
    with _LOCK:
        job = _JOBS.get(alpha3)
        if job is not None and job["state"] in ("queued", "running"):
            return {**_public(job), "started": False}
        job = {
            "alpha3": alpha3,
            "alpha2": alpha2,
            "state": "queued",
            "queued_at": _now(),
            "started_at": None,
            "finished_at": None,
            "applied": 0,
            "owed": None,
            "outcome": None,
            "error_class": None,
            "from_sequence": None,
            "to_sequence": None,
            "owed_remaining": None,
            "_args": {"source_for": source_for or _default_source_for, "kill_switch": kill_switch, "run": run},
        }
        _JOBS[alpha3] = job
        _QUEUE.append(alpha3)
        _ensure_worker()
        return {**_public(job), "started": True}


def _public(job: dict[str, Any]) -> dict[str, Any]:
    """The record as the route and the task manager may see it: counts, positions, an outcome word, a fixed sentence and, when the run
    itself raised, the exception CLASS. The run's own ``reason`` is NOT here: it can quote the network's or a library's words (a URL, a
    host), and nothing on a screen or in a response needs them (the log and the diagnostics member keep the facts)."""
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    if job.get("state") == "done" and job.get("outcome") in OUTCOME_SENTENCES:
        out["sentence"] = OUTCOME_SENTENCES[job["outcome"]]
    return out


def _ensure_worker() -> None:
    """Start the worker if none is alive. Called with ``_LOCK`` held. A worker that died (an interrupt, an exit) is replaced by the next request."""
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    _WORKER = threading.Thread(target=_work, name="osm-update-worker", daemon=True)
    _WORKER.start()


def _work() -> None:
    global _WORKER
    from src.osm.apply import update_country

    me = threading.current_thread()
    try:
        while True:
            with _LOCK:
                if not _QUEUE:
                    _WORKER = None  # under the lock the enqueuer also holds, so a job queued now starts a new worker
                    return
                alpha3 = _QUEUE.pop(0)
                job = _JOBS[alpha3]
                job["state"], job["started_at"] = "running", _now()
                args = dict(job["_args"])

            def progress(applied: int, owed: int, _job: dict[str, Any] = job) -> None:
                with _LOCK:
                    _job["applied"], _job["owed"] = applied, owed

            ended: dict[str, Any] = {"outcome": "failed", "error_class": "BaseException"}
            try:
                runner = args["run"] or update_country
                kwargs: dict[str, Any] = {"source_for": args["source_for"], "on_progress": progress}
                if args["kill_switch"] is not None:
                    kwargs["kill_switch"] = args["kill_switch"]
                report = runner(alpha3, **kwargs)
                ended = {
                    "outcome": report.outcome,
                    "from_sequence": report.from_sequence,
                    "to_sequence": report.to_sequence,
                    "owed_remaining": report.owed_remaining,
                }
            except Exception as exc:  # noqa: BLE001 - recorded on the job as "failed" with the class only; logged in full here
                log_failure(_LOG, f"osm: the {alpha3} update job failed", exc, level=logging.WARNING)
                ended = {"outcome": "failed", "error_class": type(exc).__name__}
            except BaseException as exc:  # an interrupt or an exit: recorded below, then the worker ends with it
                ended = {"outcome": "failed", "error_class": type(exc).__name__}
                raise
            finally:
                # Whatever ended the run, an interrupt included, the job is not left "running": the page would poll it for ever.
                with _LOCK:
                    job.update(ended)
                    job["state"], job["finished_at"] = "done", _now()
    finally:
        with _LOCK:
            if _WORKER is me:
                _WORKER = None


def jobs() -> list[dict[str, Any]]:
    """Every job record, queued and running first (in order), then the ended ones, newest first. Read-only copies."""
    with _LOCK:
        records = [_public(j) for j in _JOBS.values()]
        order = {a: i for i, a in enumerate(_QUEUE)}
    live = [r for r in records if r["state"] == "running"] + sorted(
        (r for r in records if r["state"] == "queued"), key=lambda r: order.get(r["alpha3"], 0)
    )
    ended = sorted((r for r in records if r["state"] == "done"), key=lambda r: r["finished_at"] or "", reverse=True)
    return live + ended


def wait_idle(timeout: float = 10.0) -> bool:
    """Block until the worker has drained the queue (for tests and shutdown); True when it did."""
    worker = _WORKER
    if worker is None:
        return True
    worker.join(timeout)
    return not worker.is_alive()


def _reset_for_tests() -> None:
    with _LOCK:
        _JOBS.clear()
        _QUEUE.clear()
