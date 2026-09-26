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
- ``suspend`` -- the machine was not running this process for a gap between two
                 liveness ticks. On Linux the boot-time clock (which keeps counting
                 through a suspend) against the monotonic clock (which does not) says
                 so exactly; elsewhere it is the wall clock running ahead of the
                 monotonic one, and the record says it cannot tell that from a clock
                 change;
- ``clock-step`` -- the wall clock was CHANGED while the process kept running (an NTP
                 correction, a manual set). Recorded from the boot-time clock on Linux,
                 and everywhere for a BACKWARD step, which no suspend can produce
                 (2026-09-24, field finding RR-5: a NUC booted 12 hours fast and its
                 chronology read 12 hours short, because a backward step left no record
                 and every duration was a difference of two wall stamps);
- ``event``   -- something a reader wants on the timeline (the network toggle, the
                 release run's start/resume/interim reports), recorded by the code
                 that does it through :func:`record_event`.

THE LIVENESS FILE (``session_liveness.json``) is rewritten every minute with the time
and the process uptime, so a session that dies without reaching the shutdown hook
still has a "last seen" to the minute. It is a small atomic overwrite, never appended
to and never fsynced -- an instrument on a periodic path must not become a load source
(the 2026-08-06 run-journal lesson).

THE CLOCKS. Every record carries the monotonic uptime (``uptime_s``) beside its wall
stamp, and the liveness file and the end record carry the SPAN (``span_s``: the
boot-time clock's advance on Linux, the running time plus the inferred suspends
elsewhere). A duration is read from those, never from two wall stamps a clock change
may lie between; the chronology re-bases a session's start when its boot stamp
disagrees with them.

THE PRE-LEDGER SESSION (RR-11). The ledger begins at the first boot of the build that
carries it, so the session just before -- often the crash that prompted the update --
was invisible to it. When the ledger holds no boot at all, the first boot SEEDS that
session from forensics' sentinel (and the memory high-water sidecar for when it was
last seen), marked ``source: forensics-sentinel`` so it is never read as a ledger
measurement.

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
#: A wall-clock change smaller than this between two ticks is not recorded: NTP slews
#: and small steps are not a chronology event, a 12-hour correction is.
CLOCK_STEP_MIN_S = 120.0
#: Compaction ceiling: the ledger keeps the newest lines when it grows past this.
MAX_LINES = 4000
#: What this build's records carry, written on every boot record, so a reader can tell
#: "this session never started collection" (the feature is present and no event was
#: recorded) from "this build did not record collection" (the feature is absent).
LEDGER_FEATURES = ("collection", "clock-step", "span")

_LOCK = threading.Lock()
_SESSION_ID: str | None = None
_STARTED_AT: str | None = None
_STARTED_MONO: float | None = None
_LAST_TICK_WALL: float | None = None
_LAST_TICK_MONO: float | None = None
_STARTED_BT: float | None = None
_LAST_TICK_BT: float | None = None
#: Seconds of suspend this session's ticks recorded -- the span's fallback where the
#: boot-time clock does not exist.
_SUSPENDED_S = 0.0
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
#: ``tick_once``'s "read the boot-time clock yourself" default, distinct from ``None``
#: ("there is no boot-time clock"), so tests that inject the other two clocks never mix
#: an injected reading with a real one.
_AUTO: Any = object()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_at(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def boottime() -> float | None:
    """The boot-time clock: it keeps counting through a suspend and never jumps with the
    wall clock. Linux only; ``None`` elsewhere, and every caller degrades to the
    monotonic-only inference it had before."""
    clk = getattr(time, "CLOCK_BOOTTIME", None)
    if clk is None:
        return None
    try:
        return float(time.clock_gettime(clk))
    except (OSError, AttributeError, ValueError):
        return None


def machine_boot_id() -> str | None:
    """The kernel's id for THIS boot of the machine (Linux). Two sessions with different
    ids had a machine reboot between them -- a fact about a gap the app otherwise cannot
    know anything about. ``None`` where the file does not exist."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() or None
    except (OSError, ValueError):
        return None


def _norm_iso(value: Any) -> str | None:
    """An ISO stamp from another file (forensics writes ``+00:00``) in this ledger's
    ``Z`` form, or None when it does not parse."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _span_s(now_mono: float, now_bt: float | None) -> tuple[float | None, str]:
    """How long this session has existed, suspends included, and how that was measured.
    Never a difference of two wall stamps: that is the number a clock change corrupts."""
    if _STARTED_MONO is None:
        return None, "no session"
    if now_bt is not None and _STARTED_BT is not None:
        return round(now_bt - _STARTED_BT, 1), "boot-time clock"
    return (round(now_mono - _STARTED_MONO + _SUSPENDED_S, 1),
            "monotonic clock plus the suspends the liveness ticks inferred")


def _write_liveness(now_wall: float, now_mono: float, now_bt: float | None = None) -> None:
    if _SESSION_ID is None or _STARTED_MONO is None:
        return
    span, basis = _span_s(now_mono, now_bt)
    rec = {
        "schema": LEDGER_SCHEMA,
        "session_id": _SESSION_ID,
        "at": _iso_at(now_wall),
        "uptime_s": round(now_mono - _STARTED_MONO, 1),
        "span_s": span,
        "span_basis": basis,
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


def _hwm_last_seen(prev_state: dict[str, Any]) -> dict[str, Any] | None:
    """The memory high-water sidecar's record of the previous session, when it names the
    same process as the sentinel. Read before ``capture_previous()`` resets it (the boot
    calls this module first), so it still describes the session that died."""
    try:
        from src.monitoring.session_hwm import previous

        got = previous()
    except Exception:  # noqa: BLE001 - a nicety on a seeded record, never load-bearing
        return None
    if not isinstance(got, dict):
        return None
    if prev_state.get("pid") is not None and got.get("pid") is not None and got.get("pid") != prev_state.get("pid"):
        return None
    return got


def _seed_pre_ledger(prev_state: dict[str, Any] | None) -> dict[str, Any] | None:
    """RR-11: the ledger holds no boot yet, so the session just before it -- the one
    forensics' sentinel describes -- would be invisible to the chronology. Write it from
    that sentinel, labelled as such. Its end is dated only where a file dates it: the
    clean-shutdown stamp, the last teardown stamp, or the high-water sidecar's last write
    (to about half a minute); otherwise the end has no time, as any other would."""
    if not isinstance(prev_state, dict):
        return None
    started = _norm_iso(prev_state.get("started_at"))
    if started is None:
        return None
    state = str(prev_state.get("state") or "")
    pid = prev_state.get("pid")
    sid = "pre-ledger-" + started.replace("-", "").replace(":", "") + (f"-{pid}" if pid else "")
    basis_src = "forensics' session sentinel (session_state.json), from before the ledger existed"
    _append({
        "kind": "boot", "session_id": sid, "at": started, "pid": pid, "source": "forensics-sentinel",
        "basis": ("seeded at the ledger's first boot from " + basis_src + ": only this session's "
                  "start and how it ended are known -- no liveness ticks, no suspends, no events"),
    })
    end: dict[str, Any] = {"kind": "end", "session_id": sid, "written_by": "next-boot",
                           "source": "forensics-sentinel", "sentinel_state": state or None}
    ended = _norm_iso(prev_state.get("ended_at"))
    teardown = _norm_iso(prev_state.get("shutdown_phase_at"))
    hwm = _hwm_last_seen(prev_state) if state != "clean" else None
    last_seen = _norm_iso((hwm or {}).get("last_ts"))
    if state == "clean" and ended:
        end.update({"at": ended, "clean": True, "basis": "the sentinel's clean-shutdown stamp"})
    elif state in ("shutting-down", "dispose-done") and teardown:
        end.update({"at": teardown, "clean": False,
                    "basis": "the sentinel's last teardown stamp: the process died during its own shutdown"})
    elif last_seen:
        end.update({"at": last_seen, "clean": False if state else None,
                    "basis": ("the memory high-water sidecar's last write (within about 30 s of the "
                              "last reading); the sentinel says the process never reached its shutdown hook")})
    else:
        end.update({"at": None, "clean": False if state and state != "clean" else None,
                    "basis": "the sentinel names no end time and nothing else dated it, so the end has no time"})
    if hwm:
        peaks = {k: hwm[k] for k in ("rss_max_mb", "avail_min_mb", "swap_used_max_mb", "phase") if k in hwm}
        if peaks:
            end["previous_peaks"] = peaks
    _append(end)
    return end


def _close_previous(prev_state: dict[str, Any] | None, liveness: dict[str, Any] | None) -> dict[str, Any] | None:
    """Write the ``end`` record the previous session could not write for itself, when
    the ledger's last word on it is not already an end. Dated from the sentinel (a
    clean end) or the liveness file (the last minute it was seen); a session with
    neither gets an end with NO time, which is the honest record. When the ledger holds
    no boot at all, the previous session is SEEDED from the sentinel instead (RR-11)."""
    records = read_records()
    last_boot = next((r for r in reversed(records) if r.get("kind") == "boot"), None)
    if last_boot is None:
        return _seed_pre_ledger(prev_state)
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
                    "span_s": liveness.get("span_s"),
                    "sentinel_state": state or None})
    else:
        rec.update({"at": None, "clean": False if state and state != "clean" else None,
                    "basis": "no sentinel end and no liveness tick, so the end has no time",
                    "sentinel_state": state or None})
    if rec.get("clean") is not True:
        exit_seen = _launcher_exit(prev_state)
        if exit_seen:
            rec["exit"] = exit_seen
    _append(rec)
    return rec


def _launcher_exit(prev_state: dict[str, Any] | None) -> dict[str, Any] | None:
    """How the launcher saw the previous process end (2026-09-26), for its end line.

    The ledger is the one record that spans many sessions, so this is where a machine
    that crashes daily shows WHICH signal each death was -- a pattern one boot's
    report cannot show."""
    pid = (prev_state or {}).get("pid")
    if not isinstance(pid, int):
        return None
    boot = (prev_state or {}).get("boot_id")
    try:
        from src.monitoring.exit_evidence import launcher_exit

        got = launcher_exit(pid, boot if isinstance(boot, str) else None)
    except Exception:  # noqa: BLE001 - the ledger never breaks a boot
        return None
    if not got:
        return None
    return {k: got.get(k) for k in ("signal", "status", "kind", "at", "seen_by")}


def record_boot(prev_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Called once per process from ``forensics.record_session_start`` (after the
    sentinel is read). Closes the previous session's record if it could not, appends
    this boot, and starts the liveness tick."""
    global _SESSION_ID, _STARTED_AT, _STARTED_MONO, _LAST_TICK_WALL, _LAST_TICK_MONO
    global _STARTED_BT, _LAST_TICK_BT, _SUSPENDED_S
    now_wall, now_mono, now_bt = time.time(), time.monotonic(), boottime()
    started_at = _iso_at(now_wall)
    sid = f"{started_at.replace('-', '').replace(':', '')}-{os.getpid()}"
    liveness = read_liveness()
    closed = _close_previous(prev_state, liveness)
    with _LOCK:
        _SESSION_ID, _STARTED_AT, _STARTED_MONO = sid, started_at, now_mono
        _LAST_TICK_WALL, _LAST_TICK_MONO = now_wall, now_mono
        _STARTED_BT = _LAST_TICK_BT = now_bt
        _SUSPENDED_S = 0.0
    rec = {
        "kind": "boot",
        "session_id": sid,
        "at": started_at,
        "pid": os.getpid(),
        "app_version": _app_version(),
        "previous_sentinel_state": (prev_state or {}).get("state"),
        "previous_closed_by_this_boot": bool(closed),
        "machine_boot_id": machine_boot_id(),
        "clocks": "boot-time" if now_bt is not None else "monotonic-only",
        "ledger_features": list(LEDGER_FEATURES),
    }
    _append(rec)
    compact_if_needed()
    _write_liveness(now_wall, now_mono, now_bt)
    if os.getenv("OO_SESSION_LIVENESS", "1") != "0":
        start_liveness()
    return rec


def record_end(*, clean: bool = True, reason: str | None = None) -> dict[str, Any] | None:
    """Called from ``forensics.record_clean_shutdown``. The session's own end line."""
    if _SESSION_ID is None:
        return None
    stop_liveness()
    now_wall, now_mono, now_bt = time.time(), time.monotonic(), boottime()
    span, basis = _span_s(now_mono, now_bt)
    rec = {
        "kind": "end",
        "session_id": _SESSION_ID,
        "at": _iso_at(now_wall),
        "clean": bool(clean),
        "basis": "this session's own shutdown hook",
        "uptime_s": round(now_mono - (_STARTED_MONO or now_mono), 1),
        "span_s": span,
        "span_basis": basis,
        "reason": reason,
    }
    _append(rec)
    _write_liveness(now_wall, now_mono, now_bt)
    return rec


def record_event(event: str, **fields: Any) -> dict[str, Any] | None:
    """A timeline event from the code that does the thing (the network toggle, the
    release run). Never raises; returns the record or None when no session is open."""
    rec: dict[str, Any] = {"kind": "event", "event": str(event), "session_id": _SESSION_ID, "at": _now_iso()}
    if _STARTED_MONO is not None:
        # Where on the session's own clock this happened, so a reader can place it even
        # when the wall clock was changed after it (RR-5).
        rec["uptime_s"] = round(time.monotonic() - _STARTED_MONO, 1)
    rec.update(fields)
    _append(rec)
    return rec


def current_session() -> dict[str, Any]:
    """This process's own record, from memory (no file read)."""
    if _SESSION_ID is None or _STARTED_MONO is None:
        return {"session_id": None, "started_at": None, "uptime_s": None, "span_s": None, "pid": os.getpid(),
                "reason": "record_boot() was never called in this process"}
    now_mono = time.monotonic()
    span, basis = _span_s(now_mono, boottime() if _STARTED_BT is not None else None)
    return {
        "session_id": _SESSION_ID,
        "started_at": _STARTED_AT,
        # The running time (the monotonic clock stops during a suspend on Linux)...
        "uptime_s": round(now_mono - _STARTED_MONO, 1),
        # ...and the time since the boot, suspends included. Neither is a difference of
        # wall stamps, so neither moves when the clock is corrected.
        "span_s": span,
        "span_basis": basis,
        "pid": os.getpid(),
    }


# --------------------------------------------------------------------------- #
#  The liveness tick (and the suspend inference it carries)
# --------------------------------------------------------------------------- #


def tick_once(now_wall: float | None = None, now_mono: float | None = None,
              now_bt: Any = _AUTO) -> dict[str, Any] | None:
    """One liveness tick: compare the clocks against the last tick, record a suspend
    and/or a clock step, rewrite the liveness file. Returns the suspend record, or None.

    THREE CLOCKS, TWO QUESTIONS (RR-5). The monotonic clock stops during a suspend on
    Linux and never jumps; the boot-time clock keeps counting through a suspend and never
    jumps; the wall clock does both. So between two ticks:

      * boot-time advance minus monotonic advance = how long the machine was SUSPENDED;
      * wall advance minus boot-time advance     = how far the wall clock was CHANGED.

    Where the boot-time clock does not exist, the wall-minus-monotonic difference is all
    there is: a positive one is a suspend OR a forward change (the record says it cannot
    tell), and a negative one can only be a clock change, because a suspend never moves
    the wall clock backward -- the case that left the NUC's 12-hour correction without a
    single record. Clocks are injectable so the inference is testable without sleeping;
    injecting the wall and monotonic clocks without a boot-time reading means "this
    platform has none", never a mix of a real reading with injected ones."""
    global _LAST_TICK_WALL, _LAST_TICK_MONO, _LAST_TICK_BT, _SUSPENDED_S
    if _SESSION_ID is None:
        return None
    injected = now_wall is not None or now_mono is not None
    now_wall = time.time() if now_wall is None else now_wall
    now_mono = time.monotonic() if now_mono is None else now_mono
    if now_bt is _AUTO:
        now_bt = None if injected else boottime()
    suspend: dict[str, Any] | None = None
    with _LOCK:
        last_wall, last_mono, last_bt = _LAST_TICK_WALL, _LAST_TICK_MONO, _LAST_TICK_BT
        _LAST_TICK_WALL, _LAST_TICK_MONO, _LAST_TICK_BT = now_wall, now_mono, now_bt
    if last_wall is not None and last_mono is not None:
        d_wall, d_mono = now_wall - last_wall, now_mono - last_mono
        up_before = round(last_mono - (_STARTED_MONO or last_mono), 1)
        up_now = round(now_mono - (_STARTED_MONO or now_mono), 1)
        if now_bt is not None and last_bt is not None:
            d_bt = now_bt - last_bt
            suspended, stepped, clocks = d_bt - d_mono, d_wall - d_bt, "boot-time"
            suspend_basis = (
                "the boot-time clock advanced more than the monotonic clock between two "
                "liveness ticks: the machine was suspended (a sleep or a hibernation) for "
                "this gap; a wall-clock change cannot produce this record"
            )
            step_basis = (
                "the wall clock moved against the boot-time clock between two liveness "
                "ticks while the process kept running: a clock correction, not a suspend"
            )
        else:
            gap = d_wall - d_mono
            clocks = "monotonic-only"
            suspended, stepped = (gap, 0.0) if gap > 0 else (0.0, gap)
            suspend_basis = (
                "the wall clock advanced more than the monotonic clock between two "
                "liveness ticks, so the process was not running for this gap; a "
                "sleep, a hibernation and a clock change leave the same record"
            )
            step_basis = (
                "the wall clock went BACKWARD against the monotonic clock between two "
                "liveness ticks: only a clock change does that (a suspend moves it forward)"
            )
        if suspended > SUSPEND_MIN_GAP_S:
            suspend = {
                "kind": "suspend",
                "session_id": _SESSION_ID,
                "from": _iso_at(now_wall - suspended),
                "to": _iso_at(now_wall),
                "gap_s": round(suspended),
                # Where the gap sits on the session's own clock: after the tick at this
                # monotonic uptime, before the next. A reader places it from these,
                # not from the wall stamps a later correction may move.
                "uptime_before_s": up_before,
                "uptime_s": up_now,
                "clocks": clocks,
                "basis": suspend_basis,
            }
            _SUSPENDED_S += round(suspended)
            _append(suspend)
        if abs(stepped) > CLOCK_STEP_MIN_S:
            _append({
                "kind": "clock-step",
                "session_id": _SESSION_ID,
                "at": _iso_at(now_wall),
                "step_s": round(stepped),
                "direction": "forward" if stepped > 0 else "backward",
                "uptime_s": up_now,
                "clocks": clocks,
                "basis": step_basis,
            })
    _write_liveness(now_wall, now_mono, now_bt)
    return suspend


def _loop() -> None:
    while not _STOP.wait(TICK_S):
        try:
            tick_once()
        except Exception:  # noqa: BLE001 - the tick must never kill its thread
            _LOG.debug("session ledger: tick failed", exc_info=True)
        # The memory high-water marks were fed only by the collector, so a peak
        # reached while collection was paused (Insights after a boot, the memory
        # guard's own pause) was never seen. Once a minute closes that gap
        # (2026-09-26); observe() is best-effort and throttled on its own.
        try:
            from src.monitoring.session_hwm import observe

            observe()
        except Exception:  # noqa: BLE001
            _LOG.debug("session ledger: memory observe failed", exc_info=True)


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
    global _STARTED_BT, _LAST_TICK_BT, _SUSPENDED_S
    stop_liveness()
    with _LOCK:
        _SESSION_ID = _STARTED_AT = _STARTED_MONO = None
        _LAST_TICK_WALL = _LAST_TICK_MONO = None
        _STARTED_BT = _LAST_TICK_BT = None
        _SUSPENDED_S = 0.0
