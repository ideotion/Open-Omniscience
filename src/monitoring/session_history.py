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
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure, scrubbed_name
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
LEDGER_FEATURES = ("collection", "clock-step", "span", "end-peaks")

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


def _code_markers() -> dict[str, Any] | None:
    """Which build this session runs (finding E): see ``build_marker``. Never raises."""
    try:
        from src.monitoring.build_marker import process_markers

        return process_markers()
    except Exception:  # noqa: BLE001 - a build marker is a nicety on a boot record
        return None


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
    except OSError as exc:
        log_failure(_LOG, "session ledger: could not append", exc, level=logging.DEBUG)


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
    except OSError as exc:
        log_failure(_LOG, "session ledger: could not write liveness", exc, level=logging.DEBUG)


def read_liveness() -> dict[str, Any] | None:
    try:
        rec = json.loads(liveness_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("session_id") else None


# --------------------------------------------------------------------------- #
#  The session's own records
# --------------------------------------------------------------------------- #


def previous_session_id() -> str | None:
    """The ledger's id of the session that came before this one, by the rule ``_close_previous`` uses: the nearest boot BEFORE this
    session's own boot record, else (this session's boot was never appended) the last boot of the ledger; ``None`` when the ledger
    names none. A boot written LATER by another instance does not win (a second instance that fails to bind still boots: the
    server runs its lifespan startup before it binds). What a reader of the previous session's marks compares the marks' own
    ``session_id`` with (:func:`_hwm_last_seen` does the same at the end record). Never raises."""
    try:
        now = current_session().get("session_id")
        boots = [r.get("session_id") for r in read_records() if r.get("kind") == "boot" and isinstance(r.get("session_id"), str)]
        if now in boots:
            boots = boots[: boots.index(now)]
        return boots[-1] if boots else None
    except Exception:  # noqa: BLE001 - a nicety on a record, never load-bearing
        return None


def _hwm_last_seen(prev_state: dict[str, Any] | None, sid: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """``(marks, why_not)``: the memory high-water sidecar's record of the session that died, and when there is none to trust, why
    (``"absent"``, ``"unreadable"``, ``"another session"`` or ``"no identity"``). Read before ``capture_previous()`` resets it (the
    boot calls this module first), so it still describes the session that died.

    WHOSE it is is decided by identity, never by a process id alone (the system reuses them): ``sid`` is the ledger's id for the
    session that died, and the sidecar must carry the same one (``session_hwm`` writes it from the ledger at boot). A sidecar with
    no id is no evidence, and so is a stale one a failed reset left behind, which names an older session. The SEED (no ``sid``: the
    ledger holds no boot of that session) has only the sentinel's process id to go by, and refuses when either side lacks it."""
    try:
        from src.monitoring.session_hwm import previous_why

        got, why = previous_why()
    except Exception:  # noqa: BLE001 - a nicety on a record, never load-bearing
        return None, "unreadable"
    if not isinstance(got, dict):
        return None, why or "absent"
    if sid is not None:
        ident = got.get("session_id")
        if not isinstance(ident, str) or not ident:
            return None, "no identity"
        return (got, None) if ident == sid else (None, "another session")
    want, have = (prev_state or {}).get("pid"), got.get("pid")
    if not isinstance(want, int) or not isinstance(have, int):
        return None, "no identity"
    return (got, None) if want == have else (None, "another session")


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
    hwm = _hwm_last_seen(prev_state)[0] if state != "clean" else None
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
        # The marks AND when each was set: the chronology shows these beside the session's other dated
        # events, and a minimum with no time cannot be placed among them.
        try:
            peaks = _peaks_of(hwm)
        except Exception:  # noqa: BLE001 - the ledger never breaks a boot; the end is written without the marks
            peaks = None
        if peaks:
            end["previous_peaks"] = peaks
    _append(end)
    return end


#: The marks the memory high-water sidecar keeps, which an end record carries as ``previous_peaks`` (the seed and every unclean end).
_PEAK_KEYS = (
    "rss_max_mb", "rss_max_at", "avail_min_mb", "avail_min_at", "swap_used_max_mb", "swap_used_max_at", "phase",
)
#: The most one of the two memory records of an end (``previous_at_peak``, ``previous_pressure``) may take, in bytes of the
#: line as it is WRITTEN (ASCII-escaped JSON). WHAT IT PROTECTS: the ledger's size and the debug bundle's. A crash loop writes
#: one end per boot, and ``boots.json`` carries ten of them inside its own 30 KiB share of the 4 MB zip; two records of 2,048
#: bytes keep an end near 5 KiB, so the member's cut to its budget drops a few of the oldest boots and never a record in half.
#: A cut says what it left out (``cut``); it never shrinks what is COUNTED (``threads_in_snapshot``).
END_RECORD_MAX_BYTES = 2048
#: How many of the busiest threads of the newest heavy snapshot an end record names. WHAT IT PROTECTS: the record's size (about
#: 150 bytes a thread): three innermost frames say where a crash loop sat, and a fourth seldom changes the answer. The count of
#: threads in the snapshot is kept whole, and the cut counts the ones left out.
_END_THREADS = 3
#: The longest a thread's NAME and its innermost FRAME may be in an end record (after paths are tokenised). WHAT THEY PROTECT:
#: the record's size against a name or a frame that carries a long text; a name or frame that is cut ends in :data:`_CUT_MARK`.
_THREAD_NAME_MAX = 80
_FRAME_MAX = 160
_CUT_MARK = "…[cut]"


def _json_size(value: Any) -> int:
    """The size of ``value`` as the ledger WRITES it (``_append``: ASCII-escaped, no spaces), not as UTF-8 text: a letter outside
    ASCII is six bytes in the file."""
    return len(json.dumps(value, separators=(",", ":"), default=str).encode("ascii"))


def _cut_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + _CUT_MARK


def _peaks_of(hwm: dict[str, Any]) -> dict[str, Any]:
    return {k: hwm[k] for k in _PEAK_KEYS if k in hwm}


def _scalars(source: Any) -> dict[str, Any]:
    """The plain numbers and short texts of ``source``: what a record of the memory's makeup keeps of a nested reading."""
    if not isinstance(source, dict):
        return {}
    return {k: v for k, v in source.items() if isinstance(v, (int, float, str, bool))}


def _at_peak_record(hwm: dict[str, Any]) -> dict[str, Any] | None:
    """What the memory was made of at the session's RSS peak (``at_peak``: anonymous against file-backed, glibc's heap in
    use against freed-but-held, CPython's blocks), its plain fields, cut to :data:`END_RECORD_MAX_BYTES` with the cut named. The
    cut's own text is counted before it is written."""
    got = _scalars(hwm.get("at_peak"))
    if not got:
        return None
    left_out = 0
    while got and _json_size(got if not left_out else {**got, "cut": {"fields_left_out": len(got) + left_out}}) > END_RECORD_MAX_BYTES:
        got.popitem()
        left_out += 1
    if left_out:
        got["cut"] = {"fields_left_out": left_out}
    return got


def _pressure_record(hwm: dict[str, Any]) -> dict[str, Any] | None:
    """The newest HEAVY snapshot of the session, as much of it as a crash needs: why it was taken and when, the memory
    readings, CPython's blocks, the guard's block with the release ladder's last record (rebuilt from the allow-list: numbers,
    step names and the class of an error), and the busiest threads by NAME and innermost frame with every path tokenised
    (``path_tokens``: nothing under the home directory is written whole). Cut to :data:`END_RECORD_MAX_BYTES` as the line is
    written, and ``cut`` says what it left out (threads, then the release record, then the guard block, and how many names or
    frames were cut short); the cut's own text is counted before it is written."""
    from src.monitoring.path_tokens import tokenise_paths
    from src.monitoring.release_view import allow_listed, vouched_names

    snaps = hwm.get("pressure")
    snap = snaps[-1] if isinstance(snaps, list) and snaps and isinstance(snaps[-1], dict) else None
    if snap is None:
        return None
    snap = vouched_names(snap)  # a snapshot an older build wrote kept its thread names raw
    out: dict[str, Any] = {k: snap[k] for k in ("why", "at", "avail_mb", "total_mb", "rss_mb", "swap_used_mb") if k in snap}
    blocks = (snap.get("memory") or {}).get("py_alloc_blocks") if isinstance(snap.get("memory"), dict) else None
    if blocks is not None:
        out["py_alloc_blocks"] = blocks
    guard = snap.get("guard")
    if isinstance(guard, dict):
        out["guard"] = {k: v for k, v in guard.items() if k != "last_release"}
        release = allow_listed(guard.get("last_release"))
        if release is not None:
            out["release"] = release
    threads = []
    for t in snap.get("threads") or []:
        if not isinstance(t, dict) or t.get("waiting") or t.get("sampler"):
            continue
        stack = t.get("stack") or []
        name = tokenise_paths(scrubbed_name(str(t.get("name") or "?")) or "?")
        frame = tokenise_paths(str(stack[0])) if stack else None
        threads.append({
            "name": _cut_text(name, _THREAD_NAME_MAX),
            "frame": None if frame is None else _cut_text(frame, _FRAME_MAX),
            **({"cpu_s": t["cpu_s"]} if "cpu_s" in t else {}),
        })
        if len(threads) == _END_THREADS:
            break
    if threads:
        out["threads"] = threads
    out["threads_in_snapshot"] = len([t for t in snap.get("threads") or [] if isinstance(t, dict)])

    def texts_cut() -> int:
        """How many TEXTS (a name or a frame) of the threads still in the record were cut: counted from what is in it."""
        return sum(1 for t in out.get("threads", []) for k in ("name", "frame") if isinstance(t.get(k), str) and t[k].endswith(_CUT_MARK))

    cut: dict[str, Any] = {"texts_cut": texts_cut()} if texts_cut() else {}
    # The largest cut text this record can carry, reserved while anything is being cut: the size is the line as written.
    reserve = {"texts_cut": 2 * _END_THREADS, "threads_left_out": _END_THREADS, "fields_left_out": ["release", "guard"]}

    def over() -> bool:
        return _json_size({**out, "cut": reserve}) > END_RECORD_MAX_BYTES

    if _json_size({**out, **({"cut": cut} if cut else {})}) > END_RECORD_MAX_BYTES:
        while over() and out.get("threads"):
            out["threads"].pop()
            cut["threads_left_out"] = cut.get("threads_left_out", 0) + 1
        if not out.get("threads"):
            out.pop("threads", None)
        for field in ("release", "guard"):
            if over() and field in out:
                del out[field]
                cut.setdefault("fields_left_out", []).append(field)
    if texts_cut():  # after the loop: a thread the size loop left out takes its cut texts with it
        cut["texts_cut"] = texts_cut()
    else:
        cut.pop("texts_cut", None)
    if cut:
        out["cut"] = cut
    return out


def _end_evidence(prev_state: dict[str, Any] | None, sid: str | None, last_boot: dict[str, Any] | None = None) -> dict[str, Any]:
    """What an UNCLEAN end carries of its own session (``end-peaks``): ``previous_peaks`` (the marks with their times), what the memory was made of at the peak and the newest
    heavy snapshot's essentials, read from the high-water sidecar of the session that died. WHOSE sidecar it is: the ledger's id
    for that session must be the one the sidecar carries (:func:`_hwm_last_seen`); a sidecar that carries no id is accepted only
    when the ledger's last boot and the sentinel describe ONE process (:func:`_same_process`) and the sidecar names that
    process. An end that has no evidence says why (``previous_evidence_missing``: ``absent``, ``unreadable``, ``another session``
    or ``no identity``), so a missing record is never read as a session that had nothing to report. Best-effort: nothing here
    fails a boot."""
    hwm, why = _hwm_last_seen(prev_state, sid)
    if not hwm and why == "no identity" and isinstance(prev_state, dict) and isinstance(last_boot, dict) and _same_process(last_boot, prev_state):
        hwm, why = _hwm_last_seen(prev_state)  # a sidecar with no id: by the sentinel's process, which the boot has just been shown to share
    if not hwm:
        return {"previous_evidence_missing": why or "absent"}
    out: dict[str, Any] = {}
    for name, build in (("previous_peaks", _peaks_of), ("previous_at_peak", _at_peak_record), ("previous_pressure", _pressure_record)):
        try:
            got = build(hwm)
        except Exception:  # noqa: BLE001 - a record that cannot be built is absent, never a failed boot
            _LOG.debug("end record: %s not built", name)
            continue
        if got:
            out[name] = got
    return out


def _same_process(boot: dict[str, Any], state: dict[str, Any]) -> bool:
    """Whether the ledger's last boot record and the forensics sentinel describe ONE process. A pid is
    not an identity (the machine reuses them, and an app started the same way at every login gets much
    the same one), so the pid must agree AND the machine boot where both name one AND the moment the
    process began where both carry one -- the three tests ``earlier_unclean_ends`` makes to tell the
    previous session from an older one. A sidecar of another process must never hand its marks to this
    session's end line."""
    if state.get("pid") is None or boot.get("pid") != state.get("pid"):
        return False
    try:
        from src.monitoring.exit_evidence import _SAME_START_S, _same_boot, _when

        boot_id = state.get("boot_id")
        if not _same_boot(boot.get("machine_boot_id"), boot_id if isinstance(boot_id, str) else None):
            return False
        began, started = _when(boot.get("at")), _when(state.get("started_at"))
        return began is None or started is None or abs(began - started) <= _SAME_START_S
    except Exception:  # noqa: BLE001 - a doubt about identity is "not the same": no marks are handed over
        return False


#: The reasons the app itself gives for a shutdown it has begun (``record_shutdown_phase(reason=...)`` call sites; the memory stop's is pinned
#: equal by a test). An allow-list, so the ledger never carries a value the sentinel file happened to hold.
_SHUTDOWN_REASONS = frozenset({"memory exhausted", "lifespan shutdown", "data drive disconnected"})


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
        # The reason the app gave for the shutdown it had begun (the sentinel keeps it): a stop the kernel cut short still says why
        # it was ending. Only a phrase of the app's own vocabulary is carried.
        said = (prev_state or {}).get("shutdown_reason")
        if said is not None:
            # A string of the app's own vocabulary is carried as it is; anything else (an unknown phrase, a non-string from a
            # damaged sidecar) is said to be unrecognised, never dropped (every absence has a reason) and never copied.
            rec["reason"] = said if isinstance(said, str) and said in _SHUTDOWN_REASONS else "unrecognised"
        exit_seen = _launcher_exit(prev_state)
        if exit_seen:
            rec["exit"] = exit_seen
        rec.update(_end_evidence(prev_state, sid, last_boot))
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


def _boot_memory_budget() -> dict[str, Any]:
    """The reading this process's memory budget was resolved from: the tier, the RAM total
    it was decided on, the logical CPUs, whether that tier leaves the in-memory keyword rollup on
    by default, and when. Written on the boot record so EVERY session of the ledger says
    which tier it ran under: until this, the tier reached a report only on a pass-end
    summary line, which three of seventeen bundles happened to keep, and on a virtual
    machine whose memory is ballooned the tier can differ from one boot to the next."""
    try:
        from src.config.memory_budget import resolved_reading

        return resolved_reading()
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return {"error": type(exc).__name__}


def _boot_allocator() -> dict[str, Any]:
    """Which C allocator this process runs on and whether its malloc arenas are capped
    (R114), compactly: the four fields that answer it, never the sentence that explains
    them (the previous-session peaks carry that). The ledger spans updates, so a comparison
    on one instance before and after the cap is a read of these, session by session."""
    try:
        from src.monitoring.session_hwm import allocator_setting

        got = allocator_setting()
        return {k: got.get(k) for k in ("allocator", "arena_cap", "effective", "source")}
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return {"error": type(exc).__name__}


def _boot_core_guard() -> dict[str, Any]:
    """Which guard against a core dump this process runs under (``src/monitoring/core_guard.py``), compactly: the mechanism
    (``rlimit``, ``dumpable``, ``none`` or ``unsupported``), the soft and hard limit it reads, whether a child is covered,
    and which handler the machine sends a dump to. Written on the boot record so a session that ended in a native crash
    says whether it could have left a dump holding the passphrase: a crash with no dump is not a crash that did not
    happen, and a dump on a machine whose record says ``none`` is not a surprise."""
    try:
        from src.monitoring.core_guard import status

        got = status()
        return {k: got.get(k) for k in ("mechanism", "soft", "hard", "dumpable", "inherited_by_children", "handler")}
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return {"error": type(exc).__name__}


def _boot_env_take() -> dict[str, Any]:
    """Whether the passphrases this process was started with left its environment (``secret_scrub.take_from_environment``): the
    NAMES of the variables still there (never a value) and the CLASS of any failure of the take. A take that failed leaves the value
    in the environment every child inherits, and a record that said nothing would read as a take that worked. The take runs at the
    first import of ``src.database.connect``: where that has not happened yet the names are still there for the first import to
    take, so the record says the store is not imported and gives both lists as null (a name reported then would read as a failed take, and an empty list as a take that worked). The lifespan imports the store before the boot record, so this is the answer only of a caller that is not the server."""
    try:
        if "src.database.connect" not in sys.modules:
            return {"store_imported": False, "still_in_environment": None, "take_failed": None}
        from src.monitoring import secret_scrub

        failed = secret_scrub.take_failed()
        connect_failed = getattr(sys.modules.get("src.database.connect"), "_TAKE_FAILED", None)
        if connect_failed:
            failed.append(str(connect_failed))
        return {
            "store_imported": True,
            "still_in_environment": [n for n in secret_scrub.HELD_ENV_VARS if os.environ.get(n)],
            "take_failed": failed,
        }
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return {"error": type(exc).__name__}


def _boot_rollup_mode() -> str | None:
    """``auto``, ``forced-on`` or ``forced-off``: whether an operator's own
    ``OO_COLUMNAR_SERVE`` is in play beside the tier's default. A rollup that is off
    because the variable says so is not one that is off because the tier does. Read from the
    environment only. A read that cannot be taken is ``unreadable (ErrorName)``, as its two
    siblings record theirs as an error: ``None`` is the record of a build that did not keep
    this at all, and a failure must not be mistaken for it."""
    try:
        from src.analytics.rollup_serve import serve_mode

        return serve_mode()
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return f"unreadable ({type(exc).__name__})"


def _boot_build() -> dict[str, Any] | None:
    """Which build this session ran (``build_id.build_identity``): the commit where there is a checkout, a hash of the source
    files' bytes and the schema head, so an update reads as an update and not as a crash. Never raises."""
    try:
        from src.monitoring.build_id import build_identity

        return build_identity()
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        return {"error": type(exc).__name__}


def _bind_hwm(sid: str) -> None:
    """Give the memory high-water sidecar this session's ledger id, so the next boot can tell its marks from a stale file's."""
    try:
        from src.monitoring.session_hwm import bind_session

        bind_session(sid)
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        _LOG.debug("session ledger: the sidecar was not bound (%s)", type(exc).__name__)


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
        "memory_budget": _boot_memory_budget(),
        "allocator": _boot_allocator(),
        "rollup_serve_mode": _boot_rollup_mode(),
        "core_guard": _boot_core_guard(),
        "env_take": _boot_env_take(),
        "build": _boot_build(),
        "code": _code_markers(),
    }
    _append(rec)
    _bind_hwm(sid)
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


#: How often this thread also reads memory (2026-09-26). The high-water marks were fed
#: only by the collector's monitor, so a peak reached while collection was paused
#: (Insights after a boot, the memory guard's own pause) was never seen -- and the
#: field burst that killed a 4 GB machine took 45 s from 1 GB available to none, which
#: a once-a-minute reading could miss entirely. A read is three /proc files. This is
#: also the one thread that snapshots every thread when memory runs short.
MEMORY_WATCH_S = 5.0


def _loop() -> None:
    next_tick = time.monotonic() + TICK_S
    while not _STOP.wait(max(0.0, min(MEMORY_WATCH_S, next_tick - time.monotonic()))):
        if time.monotonic() >= next_tick:
            next_tick = time.monotonic() + TICK_S
            try:
                tick_once()
            except Exception as exc:  # noqa: BLE001 - the tick must never kill its thread
                log_failure(_LOG, "session ledger: tick failed", exc, level=logging.DEBUG)
        try:
            from src.monitoring.session_hwm import observe

            observe(may_snapshot_threads=True)
        except Exception as exc:  # noqa: BLE001 - best-effort and throttled on its own
            log_failure(_LOG, "session ledger: memory observe failed", exc, level=logging.DEBUG)
        try:
            # The vitals history rides this same tick (R119): no thread of its own.
            from src.monitoring.vitals_history import tick

            tick()
        except Exception as exc:  # noqa: BLE001 - best-effort; the history never raises into the tick
            log_failure(_LOG, "session ledger: vitals tick failed", exc, level=logging.DEBUG)


def start_liveness() -> bool:
    """Start the once-a-minute tick, which also reads memory every ``MEMORY_WATCH_S``
    (idempotent; one daemon thread per process)."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        try:
            from src.monitoring.vitals_history import start as _vitals_start

            _vitals_start()
        except Exception as exc:  # noqa: BLE001 - the history is optional context, never a boot failure
            log_failure(_LOG, "session ledger: vitals history did not start", exc, level=logging.DEBUG)
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
    try:
        from src.monitoring.vitals_history import flush as _vitals_flush

        _vitals_flush()  # a clean end writes the history it holds (a kill loses at most five minutes)
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "session ledger: vitals flush failed", exc, level=logging.DEBUG)


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
