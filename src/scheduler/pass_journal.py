"""The pass-tail phase journal — where a pass died, not just that it did.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (2026-09-02, S0.5). The field's S2 session wrote its pass-end summary at
09:42:04 and never appended a scheduler run record. Everything between those two
points — the housekeeping-lane kick, discovery, source enrichment, the briefing
refresh, the WAL checkpoint under the write gate, ``record_run`` — is a window in
which the process demonstrably was, and from which nothing survived. Three
whole-corpus consumers and a multi-GB checkpoint run in there, and
``WriterGate.acquire()`` has no timeout, so a hang there is indistinguishable from a
dead process.

This records a bounded ``phase_begin`` / ``phase_end`` pair per tail step with the
memory readings at each boundary, so the next such death names its step.

THREE DESIGN RULES, each of which is a recorded lesson rather than a preference:

* **Its own file, never extra rows in ``scheduler_runs.jsonl``.** ``recent_runs()``
  reads that file and surfaces every line as a run; phase records there would appear
  as phantom passes in the task manager, the diagnostics bundle and the forensics
  report.
* **A ``begin`` without an ``end`` stays unmarked.** The absence IS the evidence. A
  terminal marker written to mean "handled" would make every crashed run read as
  finished from the first restart afterwards (the 2026-07-31 run-journal lesson).
* **Bounded, and cheap enough for the path it sits on.** The file is trimmed to a
  ring; a phase boundary is a handful per pass, not a per-article write (the
  2026-08-06 milestone-stream lesson, where an instrument on a hot path became the
  load).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

_FILE = "pass_journal.jsonl"
# A pass tail writes ~14 records (7 steps x begin/end). This holds many passes'
# worth of history while staying small enough to read in one gulp.
_MAX_LINES = 2000
_LOCK = threading.Lock()


def _path() -> Path:
    return data_dir() / _FILE


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _readings() -> dict[str, float]:
    """RSS / available / swap in MB, each ABSENT when unmeasurable (never 0)."""
    out: dict[str, float] = {}
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return out
    try:
        out["rss_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        out["mem_avail_mb"] = round(psutil.virtual_memory().available / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        out["swap_used_mb"] = round(psutil.swap_memory().used / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def _append(record: dict[str, Any]) -> None:
    try:
        with _LOCK:
            with _path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except OSError:
        _LOG.debug("could not append to %s", _FILE, exc_info=True)


def trim() -> None:
    """Hold the journal to a ring. Called at a pass boundary, not per record."""
    try:
        with _LOCK:
            p = _path()
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                return
            if len(lines) <= _MAX_LINES:
                return
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines[-_MAX_LINES:]) + "\n", encoding="utf-8")
            os.replace(tmp, p)
    except OSError:
        _LOG.debug("could not trim %s", _FILE, exc_info=True)


class phase:
    """Context manager recording one tail step.

    ``with phase("hygiene:checkpoint", pass_id=…):`` writes a begin record on entry
    and an end record on exit — including on an exception, whose type is recorded.
    A process that dies inside the block writes no end record, and that silence is
    what names the step."""

    def __init__(self, name: str, *, pass_id: str | None = None) -> None:
        self.name = name
        self.pass_id = pass_id
        self._t0 = 0.0

    def __enter__(self) -> phase:
        import time

        self._t0 = time.monotonic()
        rec: dict[str, Any] = {
            "event": "phase_begin",
            "phase": self.name,
            "ts": _now(),
            "pid": os.getpid(),
        }
        if self.pass_id:
            rec["pass_id"] = self.pass_id
        rec.update(_readings())
        _append(rec)
        try:
            from src.monitoring.session_hwm import observe

            observe(phase=f"pass tail: {self.name}")
        except Exception:  # noqa: BLE001
            pass
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        import time

        rec: dict[str, Any] = {
            "event": "phase_end",
            "phase": self.name,
            "ts": _now(),
            "pid": os.getpid(),
            "ms": round((time.monotonic() - self._t0) * 1000, 1),
        }
        if self.pass_id:
            rec["pass_id"] = self.pass_id
        if exc_type is not None:
            rec["error"] = f"{exc_type.__name__}: {exc}"
        rec.update(_readings())
        _append(rec)
        # Returns None: a journal must never swallow the exception it records.


def read(max_records: int = 400) -> list[dict[str, Any]]:
    """The tail of the journal, oldest first."""
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max_records:]:
        line = line.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


def unfinished_phase(records: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The last ``phase_begin`` with no matching ``phase_end``, or None.

    THIS IS DERIVED BY PAIRING, so it is published WITH its basis rather than as a
    measurement: a journal muted mid-run by a full disk leaves the identical
    signature as a process that died in the step. The caller must say which it
    cannot distinguish (the 2026-07-31 run-journal lesson)."""
    recs = read() if records is None else records
    open_phases: list[dict[str, Any]] = []
    for rec in recs:
        if rec.get("event") == "phase_begin":
            open_phases.append(rec)
        elif rec.get("event") == "phase_end":
            name = rec.get("phase")
            for i in range(len(open_phases) - 1, -1, -1):
                if open_phases[i].get("phase") == name:
                    open_phases.pop(i)
                    break
    if not open_phases:
        return None
    last = dict(open_phases[-1])
    last["basis"] = (
        "a phase_begin with no matching phase_end. Derived by PAIRING records, not "
        "observed directly: a journal that stopped being written for another reason "
        "(a full disk, a removed data dir) leaves the identical signature."
    )
    return last


def report() -> dict[str, Any]:
    """The journal's own summary for the forensics/diagnostics surfaces."""
    recs = read()
    out: dict[str, Any] = {
        "records": len(recs),
        "method": (
            "phase_begin/phase_end pairs written by the collector's pass tail, with "
            "the memory readings at each boundary. An unmeasurable reading is absent, "
            "never zero. A begin with no end is left unmarked — the absence is the "
            "evidence, so nothing is ever written to mean 'handled'."
        ),
    }
    if not recs:
        out["note"] = "no pass-tail phases recorded yet (no pass has reached its tail)"
        return out
    out["last_record_at"] = recs[-1].get("ts")
    stuck = unfinished_phase(recs)
    if stuck is not None:
        out["died_during"] = stuck
    else:
        out["died_during"] = None
        out["note"] = "every recorded phase has a matching end"
    # slowest completed phases, so a hang that eventually returned is still visible
    ends = [r for r in recs if r.get("event") == "phase_end" and r.get("ms") is not None]
    ends.sort(key=lambda r: -float(r.get("ms") or 0))
    out["slowest_phases"] = [
        {"phase": r.get("phase"), "ms": r.get("ms"), "ts": r.get("ts")} for r in ends[:5]
    ]
    return out
