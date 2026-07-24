"""Per-stage wall-clock timing for the restore/import pipeline (field-feedback
Session A §4: "instrument first, own the machine, then optimize").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the manual ``time.monotonic()``-delta / rounded-3dp convention already
used on the EXPORT side (``src/backup/stream_backup.py``'s ``wall_s``/
``gate_held_s``), so a restore report reads consistently beside an export
report. MEASUREMENT ONLY: a timer never changes control flow, never swallows
an exception (the ``finally`` inside :meth:`StageTimings.stage` records the
elapsed time and then lets the exception propagate exactly as it would
without this module), and never blocks a caller that ignores it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class StageTimings:
    """Accumulates named stage wall-seconds, in first-recorded order.

    Two ways to record a stage: wrap the work in ``with timings.stage(name):``
    (the common case), or call :meth:`record` with an elapsed value already
    computed elsewhere (e.g. a sub-call that hands back its own ``wall_s``).
    Re-recording the SAME name overwrites its value but keeps its original
    position in ``report()["stages"]`` -- a caller who times a stage twice
    (e.g. a retry) sees the latest duration, never a duplicate/summed entry.

    ``on_start`` (field-feedback Session A §4, "progress everywhere" — phase
    pings for stages that otherwise have no progress callback of their own):
    an optional ``Callable[[str], None]`` fired with the stage NAME the
    instant ``stage()`` is entered, BEFORE the timed work runs — so a caller
    can show "now doing: swap" live instead of only learning a stage's
    duration after it finishes. Report-only: wrapped in its own try/except so
    a raising sink can never break the timed work (mirrors merge_corpus's
    own progress_cb contract) and never delays entry into the stage.
    """

    def __init__(self, *, on_start: Callable[[str], None] | None = None) -> None:
        self._t0 = time.monotonic()
        self._values: dict[str, float] = {}
        self._order: list[str] = []
        self._on_start = on_start

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if self._on_start is not None:
            try:
                self._on_start(name)
            except Exception:  # noqa: BLE001 - progress reporting must never break the stage
                pass
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.record(name, time.monotonic() - t0)

    def record(self, name: str, seconds: float) -> None:
        if name not in self._values:
            self._order.append(name)
        self._values[name] = round(max(0.0, seconds), 3)

    def report(self) -> dict:
        """``{"stages": {name: seconds, ...}, "wall_s": total_since_construction}``.

        ``wall_s`` is the ELAPSED time since this ``StageTimings`` was built,
        not the sum of ``stages`` -- the two legitimately differ (untimed
        gaps between stages, or a caller that never wraps every stage), and
        reporting the sum as if it were the true wall time would be a
        fabricated total. Both numbers are real, both are shown."""
        return {
            "stages": {name: self._values[name] for name in self._order},
            "wall_s": round(time.monotonic() - self._t0, 3),
        }
