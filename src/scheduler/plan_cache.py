"""The polled collection-activity panel reads its "what would the next pass do" preview from memory.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. ``GET /api/scheduler/activity`` is polled by the top-bar chip, the vitals popover and the
task-manager window, and each poll used to open a pooled connection to count and sample the
source catalogue for the preview. When the pool was busy (a slow article list holds a slot for
minutes, the collector holds up to its ceiling) the poll waited the pool's 30 s checkout
timeout and answered 500: 333 of 329,968 polls on nine field instances, 97 on one of them
(2026-09-30 diagnostics, rank 7), and the task manager went blank exactly when the machine
was busiest -- when an operator most wants to see it.

WHAT. The preview is a deliberately loose glimpse (a re-randomised sample of the next sources
and a stated-arithmetic estimate; the pass re-randomises every time), so a preview a few seconds
old is as true as a fresh one. The poll therefore never waits on the database: it is answered from
the last good preview, labelled with how old it is, and at most ONE background refresh runs at a
time (its own thread, its own session, its own wait) whenever the preview has aged past
:data:`FRESH_S`. Nothing is rejected and no limit is imposed on the caller: this is not the
ruling-gated 429 cap on polled GETs, it removes the poll's dependency on the pool.

WHAT IT REFUSES. Never a preview for settings the operator has since changed (it would show a plan
the next pass will not run): when the settings differ it says "computing" instead. Never a silent
failure: a refresh that fails is recorded and shown with the preview's age, which keeps
growing -- the honest reading of "the database is not answering".
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

_LOG = logging.getLogger(__name__)

#: A preview younger than this is served as is, with no refresh. It protects the database from the
#: hot poll (this endpoint was the #1 route by server time in the 2026-06 field data: ~4,000
#: polls at ~119 ms each) while staying well inside what the preview means: the sample it
#: shows is re-randomised per pass and the estimate moves only when a pass ends.
FRESH_S = 15.0

#: A preview older than this is LABELLED stale to the reader. Four times FRESH_S: a refresh that
#: has failed to land for four cycles is news, one that is merely between cycles is not.
STALE_S = 60.0

#: How long a poll waits for the very first preview (nothing cached, or the settings changed)
#: before answering "computing". Short: the answer a blocked poll gives is worth less than the
#: panel that stays responsive, and the next poll gets the result.
FIRST_WAIT_S = 2.0


def _settings_key(settings: Any) -> str:
    """A stable identity for the settings a preview was computed for."""
    try:
        data = dataclasses.asdict(settings)
    except TypeError:
        data = {"repr": repr(settings)}
    return json.dumps(data, sort_keys=True, default=str)


class PlanPreviewCache:
    """Last-good preview, single-flight background refresh. Thread-safe; never blocks long."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock
        self._wall = wall or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._entry: dict[str, Any] | None = None
        self._inflight: threading.Event | None = None
        self._last_error: dict[str, Any] | None = None
        self._refreshes = 0
        self._failures = 0

    # -- the read the endpoint makes ----------------------------------------------
    def get(self, settings: Any, compute: Callable[[], dict]) -> dict:
        """The preview for ``settings``, labelled. ``compute`` runs only on the refresh thread."""
        key = _settings_key(settings)
        now = self._clock()
        with self._lock:
            entry = self._entry
            fresh = entry is not None and entry["key"] == key and now - entry["at"] <= FRESH_S
            start = not fresh and self._inflight is None
            if start:
                self._inflight = threading.Event()
            waiter = self._inflight
        if start and waiter is not None:
            self._spawn(key, compute, waiter)
        if not fresh and (entry is None or entry["key"] != key) and waiter is not None:
            # Nothing usable for THESE settings: give the refresh a short, bounded head start.
            waiter.wait(FIRST_WAIT_S)
        with self._lock:
            entry = self._entry
            refreshing = self._inflight is not None
            err = dict(self._last_error) if self._last_error else None
        return self._label(entry, key, refreshing, err)

    def _label(
        self, entry: dict[str, Any] | None, key: str, refreshing: bool, err: dict[str, Any] | None
    ) -> dict:
        if entry is None or entry["key"] != key:
            out: dict[str, Any] = {"state": "computing", "as_of": None, "age_s": None, "stale": False}
        else:
            age = max(0.0, self._clock() - entry["at"])
            out = dict(entry["value"])
            out.update(
                {
                    "state": "fresh" if age <= FRESH_S else ("refreshing" if refreshing else "stale"),
                    "as_of": entry["wall"],
                    "age_s": round(age, 1),
                    "stale": age > STALE_S,
                }
            )
        if err is not None:
            out["refresh_error"] = err
        return out

    # -- the background refresh ----------------------------------------------------
    def _spawn(self, key: str, compute: Callable[[], dict], done: threading.Event) -> None:
        try:
            threading.Thread(
                target=self._refresh, args=(key, compute, done), name="oo-plan-preview", daemon=True
            ).start()
        except Exception:  # noqa: BLE001 - no thread: release the slot, the next poll tries again
            with self._lock:
                self._inflight = None
            done.set()

    def _refresh(self, key: str, compute: Callable[[], dict], done: threading.Event) -> None:
        try:
            value = compute()
            with self._lock:
                self._entry = {
                    "key": key,
                    "value": value,
                    "at": self._clock(),
                    "wall": self._wall().isoformat(timespec="seconds"),
                }
                self._last_error = None
                self._refreshes += 1
        except Exception as exc:  # noqa: BLE001 - the preview is advisory; say so, never raise
            with self._lock:
                self._failures += 1
                self._last_error = {
                    "at": self._wall().isoformat(timespec="seconds"),
                    "type": type(exc).__name__,
                    # The exception's own first line only: SQLAlchemy's wrapper carries the SQL
                    # and its bound parameters.
                    "message": (str(getattr(exc, "orig", exc)).splitlines() or [""])[0][:160],
                }
            _LOG.debug("plan preview refresh failed", exc_info=True)
        finally:
            with self._lock:
                self._inflight = None
            done.set()

    # -- introspection ---------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "refreshes": self._refreshes,
                "failures": self._failures,
                "refreshing": self._inflight is not None,
                "last_error": dict(self._last_error) if self._last_error else None,
            }

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._entry = None
            self._inflight = None
            self._last_error = None
            self._refreshes = self._failures = 0


#: The process-wide cache the activity endpoint reads (no thread, no I/O at import).
plan_cache = PlanPreviewCache()
