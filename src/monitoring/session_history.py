"""The session ledger -- an append-only chronology of THIS install's process sessions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (2026-09-18, maintainer-asked). ``forensics.py`` keeps ONE sentinel:
the current session, and at boot the verdict on the previous one. That answers "did the
last session end cleanly?" and nothing older -- so after an unnoticed stop during a
multi-day run the app could not say how many times it had restarted, how long it had
been up in total, or how long its longest uninterrupted stretch was. The maintainer's
question was exactly that: *"what if I don't know when the machine stopped?"*

WHAT IS RECORDED, one JSON line each in ``data/session_history.jsonl``:
- ``boot``    -- this process started (session id, time, pid, app version, and the
                 previous session's sentinel state as forensics read it);
- ``end``     -- a session ended: at a clean shutdown its own record; for a session
                 that died, the record the NEXT boot writes for it, dated from the
                 LIVENESS file (see below) and saying so in ``basis``;
- ``suspend`` -- the wall clock advanced more than the monotonic clock between two
                 liveness ticks: the process was not running for that gap (a sleep,
                 a hibernation, a clock change -- the record says which it cannot
                 tell apart);
- ``event``   -- something a reader wants on the timeline (the network toggle, the
                 release run's start/resume/interim reports), recorded by the code
                 that does it through :func:`record_event`.

THE LIVENESS FILE (``session_liveness.json``) is rewritten every minute with the time
and the process uptime, so a session that dies without reaching the shutdown hook
still has a "last seen" to the minute. It is a small atomic overwrite, never appended
to and never fsynced -- an instrument on a periodic path must not become a load source
(the 2026-08-06 run-journal lesson).

HONESTY RULES
- The app cannot know what happened while it was not running. A gap between an end
  and the next boot is a gap with no record; the reader is told its bounds, never a
  cause. An end without a sentinel and without a liveness tick has NO time.
- A suspend is inferred from the two clocks, not from the OS. Its record names the
  three things it cannot distinguish.
- Every call is best-effort: a ledger that raises would be a second failure layered
  on the one it exists to explain. A lost line costs a reading, never the run.
- Nothing here touches the network or the database.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

LEDGER_FILE = "session_history.jsonl"
LIVENESS_FILE = "session_liveness.json"
LEDGER_SCHEMA = "oo-session-history-1"

#: The liveness tick period. One minute bounds an unclean end's "last seen" to a
#: minute, at the cost of one small file rewrite per minute.
TICK_S = 60.0
#: Wall-clock minus monotonic advance between two ticks beyond which the process is
#: judged NOT to have been running (a suspend). Two minutes over a one-minute tick:
#: scheduler jitter never reaches that, a laptop lid does.
SUSPEND_MIN_GAP_S = 120.0
#: Compaction ceiling: the ledger keeps the newest lines when it grows past this.
MAX_LINES = 4000

_LOCK = threading.Lock()
_SESSION_ID: str | None = None
_STARTED_AT: str | None = None
_STARTED_MONO: float | None = None
_LAST_TICK_WALL: float | None = None
_LAST_TICK_MONO: float | None = None
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_at(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ledger_path() -> Path:
    return data_dir() / LEDGER_FILE


def liveness_path() -> Path:
    return data_dir() / LIVENESS_FILE


def _app_version() -> str | None:
    try:
        from src.utils.export_envelope import app_version

        return str(app_version())
    except Exception:  # noqa: BLE001 - a version is a nicety on a boot record
        return None


# --------------------------------------------------------------------------- #
#  The file
# --------------------------------------------------------------------------- #


def _append(rec: dict[str, Any]) -> None:
    """One line, LF, appended under the module lock; best-effort by design."""
    rec = {"schema": LEDGER_SCHEMA, **rec}
    try:
        with _LOCK:
            p = ledger_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
    except OSError:
        _LOG.debug("session ledger: could not append", exc_info=True)


def read_records() -> list[dict[str, Any]]:
    """Every parseable line, oldest first. A damaged line is skipped, never fatal."""
    try:
        text = ledger_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind"):
            out.append(rec)
    return out


def compact_if_needed(max_lines: int = MAX_LINES) -> int:
    """Keep the newest ``max_lines`` lines. Returns how many were dropped. Called at
    boot, so a ledger can never grow without bound across a long-lived install."""
    try:
        with _LOCK:
            p = ledger_path()
            lines = p.read_text(encoding="utf-8").splitlines()
            if len(lines) <= max_lines:
                return 0
            keep = lines[-max_lines:]
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
            os.replace(tmp, p)
            return len(lines) - len(keep)
    except OSError:
        return 0


def _write_liveness(now_wall: float, now_mono: float) -> None:
    if _SESSION_ID is None or _STARTED_MONO is None:
        return
    rec = {
        "schema": LEDGER_SCHEMA,
        "session_id": _SESSION_ID,
        "at": _iso_at(now_wall),
        "uptime_s": round(now_mono - _STARTED_MONO, 1),
        "pid": os.getpid(),
    }
    try:
        p = liveness_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        _LOG.debug("session ledger: could not write liveness", exc_info=True)


def read_liveness() -> dict[str, Any] | None:
    try:
        rec = json.loads(liveness_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("session_id") else None


# --------------------------------------------------------------------------- #
#  The session's own records
# --------------------------------------------------------------------------- #


def _close_previous(prev_state: dict[str, Any] | None, liveness: dict[str, Any] | None) -> dict[str, Any] | None:
    """Write the ``end`` record the previous session could not write for itself, when
    the ledger's last word on it is not already an end. Dated from the sentinel (a
    clean end) or the liveness file (the last minute it was seen); a session with
    neither gets an end with NO time, which is the honest record."""
    records = read_records()
    last_boot = next((r for r in reversed(records) if r.get("kind") == "boot"), None)
    if last_boot is None:
        return None
    sid = last_boot.get("session_id")
    if any(r.get("kind") == "end" and r.get("session_id") == sid for r in records):
        return None
    state = str((prev_state or {}).get("state") or "")
    rec: dict[str, Any] = {"kind": "end", "session_id": sid, "written_by": "next-boot"}
    if state == "clean" and (prev_state or {}).get("ended_at"):
        rec.update({"at": prev_state["ended_at"], "clean": True,  # type: ignore[index]
                    "basis": "the clean-shutdown sentinel; the ledger line itself was not written"})
    elif liveness and liveness.get("session_id") == sid and liveness.get("at"):
        rec.update({"at": liveness["at"], "clean": False,
                    "basis": "the last liveness tick (to the minute); the process did not reach its shutdown hook",
                    "uptime_s": liveness.get("uptime_s"),
                    "sentinel_state": state or None})
    else:
        rec.update({"at": None, "clean": False if state and state != "clean" else None,
                    "basis": "no sentinel end and no liveness tick, so the end has no time",
                    "sentinel_state": state or None})
    _append(rec)
    return rec


def record_boot(prev_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Called once per process from ``forensics.record_session_start`` (after the
    sentinel is read). Closes the previous session's record if it could not, appends
    this boot, and starts the liveness tick."""
    global _SESSION_ID, _STARTED_AT, _STARTED_MONO, _LAST_TICK_WALL, _LAST_TICK_MONO
    now_wall, now_mono = time.time(), time.monotonic()
    started_at = _iso_at(now_wall)
    sid = f"{started_at.replace('-', '').replace(':', '')}-{os.getpid()}"
    liveness = read_liveness()
    closed = _close_previous(prev_state, liveness)
    with _LOCK:
        _SESSION_ID, _STARTED_AT, _STARTED_MONO = sid, started_at, now_mono
        _LAST_TICK_WALL, _LAST_TICK_MONO = now_wall, now_mono
    rec = {
        "kind": "boot",
        "session_id": sid,
        "at": started_at,
        "pid": os.getpid(),
        "app_version": _app_version(),
        "previous_sentinel_state": (prev_state or {}).get("state"),
        "previous_closed_by_this_boot": bool(closed),
    }
    _append(rec)
    compact_if_needed()
    _write_liveness(now_wall, now_mono)
    if os.getenv("OO_SESSION_LIVENESS", "1") != "0":
        start_liveness()
    return rec


def record_end(*, clean: bool = True, reason: str | None = None) -> dict[str, Any] | None:
    """Called from ``forensics.record_clean_shutdown``. The session's own end line."""
    if _SESSION_ID is None:
        return None
    stop_liveness()
    now_wall, now_mono = time.time(), time.monotonic()
    rec = {
        "kind": "end",
        "session_id": _SESSION_ID,
        "at": _iso_at(now_wall),
        "clean": bool(clean),
        "basis": "this session's own shutdown hook",
        "uptime_s": round(now_mono - (_STARTED_MONO or now_mono), 1),
        "reason": reason,
    }
    _append(rec)
    _write_liveness(now_wall, now_mono)
    return rec


def record_event(event: str, **fields: Any) -> dict[str, Any] | None:
    """A timeline event from the code that does the thing (the network toggle, the
    release run). Never raises; returns the record or None when no session is open."""
    rec = {"kind": "event", "event": str(event), "session_id": _SESSION_ID, "at": _now_iso(), **fields}
    _append(rec)
    return rec


def current_session() -> dict[str, Any]:
    """This process's own record, from memory (no file read)."""
    if _SESSION_ID is None or _STARTED_MONO is None:
        return {"session_id": None, "started_at": None, "uptime_s": None, "pid": os.getpid(),
                "reason": "record_boot() was never called in this process"}
    return {
        "session_id": _SESSION_ID,
        "started_at": _STARTED_AT,
        "uptime_s": round(time.monotonic() - _STARTED_MONO, 1),
        "pid": os.getpid(),
    }


# --------------------------------------------------------------------------- #
#  The liveness tick (and the suspend inference it carries)
# --------------------------------------------------------------------------- #


def tick_once(now_wall: float | None = None, now_mono: float | None = None) -> dict[str, Any] | None:
    """One liveness tick: compare the two clocks against the last tick, record a
    suspend if the wall clock ran ahead, rewrite the liveness file. Exposed with
    injectable clocks so the inference is testable without sleeping."""
    global _LAST_TICK_WALL, _LAST_TICK_MONO
    if _SESSION_ID is None:
        return None
    now_wall = time.time() if now_wall is None else now_wall
    now_mono = time.monotonic() if now_mono is None else now_mono
    suspend: dict[str, Any] | None = None
    with _LOCK:
        last_wall, last_mono = _LAST_TICK_WALL, _LAST_TICK_MONO
        _LAST_TICK_WALL, _LAST_TICK_MONO = now_wall, now_mono
    if last_wall is not None and last_mono is not None:
        gap = (now_wall - last_wall) - (now_mono - last_mono)
        if gap > SUSPEND_MIN_GAP_S:
            suspend = {
                "kind": "suspend",
                "session_id": _SESSION_ID,
                "from": _iso_at(now_wall - gap),
                "to": _iso_at(now_wall),
                "gap_s": round(gap),
                "basis": (
                    "the wall clock advanced more than the monotonic clock between two "
                    "liveness ticks, so the process was not running for this gap; a "
                    "sleep, a hibernation and a clock change leave the same record"
                ),
            }
            _append(suspend)
    _write_liveness(now_wall, now_mono)
    return suspend


def _loop() -> None:
    while not _STOP.wait(TICK_S):
        try:
            tick_once()
        except Exception:  # noqa: BLE001 - the tick must never kill its thread
            _LOG.debug("session ledger: tick failed", exc_info=True)


def start_liveness() -> bool:
    """Start the once-a-minute tick (idempotent; one daemon thread per process)."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="oo-session-liveness", daemon=True)
        _THREAD.start()
        return True


def stop_liveness() -> None:
    global _THREAD
    _STOP.set()
    t = _THREAD
    if t is not None and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=2.0)
    _THREAD = None


def _reset_for_tests() -> None:
    """Forget the in-memory session (tests only; the files are the tests' tmp dir)."""
    global _SESSION_ID, _STARTED_AT, _STARTED_MONO, _LAST_TICK_WALL, _LAST_TICK_MONO
    stop_liveness()
    with _LOCK:
        _SESSION_ID = _STARTED_AT = _STARTED_MONO = None
        _LAST_TICK_WALL = _LAST_TICK_MONO = None
