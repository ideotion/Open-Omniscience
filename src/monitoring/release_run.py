"""The 0.4 release acceptance run -- ONE button for the operator rows of the 0.4 board.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. ``docs/product/RELEASE_0.4_GATE.md`` closes on artifacts that only the operator's
own machine can produce: a committed import at scale (row A), a >= 72 h collector soak
(row B), an all-diagnostics bundle from the ~1M-article instance (row C), the soak
window and the qualification-integrity readings that rows D and E exist to make
readable, the P0 trio re-run on the new backup format (row K), the Wikipedia lane's
>= 72 h run (row P), and a handful of live probes no build sandbox can make (rows Q
and T). Each already has its own kit; what did not exist was one press that sequences
them and leaves ONE report a later reader can re-open. The maintainer asked for exactly
that (2026-09-18): "automate them with a one time single (fully automated) button".

WHAT IT COMPOSES, never re-implements:

  * :mod:`src.monitoring.p0_validation` -- the P0 trio (backup -> verify -> staged
    restore probe -> unlock -> collector), into a DATED export folder allocated by the
    export slice's own :func:`~src.backup.export_folder.allocate_export_folder`;
  * :mod:`src.monitoring.release_run_fresh_restore` -- a SUBPROCESS that restores that
    backup, COMMITTED, into a throwaway fresh install and reads the qualification
    integrity + the duplicate-key scan off the restored corpus (the two-process shape
    ``tests/test_restore_fixture_matrix.py`` records: one process is a self-restore);
  * the ruled online seam (``POST /api/system/network``) + the unattended-run kit
    (``POST /api/system/unattended/start``) -- collection, the wiki lane, the
    qualification drain and the expedition log, from the ONE path in;
  * :func:`~src.monitoring.soak_window.soak_window`,
    :func:`~src.catalog.qualification_integrity.qualification_integrity_report`, the
    lane counters route and the all-diagnostics job for the end-of-window readings.

HONESTY (the whole point, same rules as the P0 kit):

  * NO composite score. Every board row gets its own status from the closed vocabulary
    below and the evidence beside it; the summary is a tally of statuses, never a number
    to game.
  * NEVER a fabricated pass. A phase that cannot run here says ``not-measurable-here``
    WITH the reason and the operator step; a refused precondition says ``refused``.
  * The run is VERDICT-FREE about the board: it records what each clause measured and
    leaves "does this close the row" to the maintainer, exactly as the soak window does.
  * The passphrase is used and never stored: not in the state file, not in the report,
    not in a log line. The routes scrub defensively on the way out.
  * The state file survives a restart and says WHERE the run was when the process died,
    because a run that vanishes leaves the operator with nothing after three days.

WHAT IT MAY NOT DO. It never tags, never flips the version, never decides a ⛔ or an
RC item, never touches ``configs/``. The 0.3 row-5 quarantine pass is a DEFERRED
operator step (register ruling A1), so it runs only behind an explicit per-run opt-in
that defaults OFF -- ticking it is the maintainer's decision, not this module's.

THE FIELD ROUND (2026-09-24, six machines; ``docs/audit/16_…``, fixes RR-1 to RR-8).
Row 5 runs LAST, after the bundle, with collection paused (ruling FD01): it is a
whole-corpus re-index that held three 4 GB VMs for 50 to 61 hours before their soaks
could start. Every duration is monotonic, a suspend ends a soak stretch, a pool timeout
is retried and a failed phase keeps what it measured, each board row takes its status
from the evidence it holds, row C reads the bundle's manifest where the writer puts it,
and the bundle's release-run member carries the live run.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("monitoring.release_run")

RELEASE_RUN_SCHEMA = "oo-release-run-0-4-1"

#: The two instances the maintainer runs this on. The profile changes what the REPORT
#: says a number speaks to, never what is measured.
PROFILES = ("release-scale", "million")

#: The board's own bar for row B (and D's window).
SOAK_BAR_HOURS = 72.0

#: Row C's bar is "the ~1M-article instance"; below this the million profile is warned
#: (never refused -- the operator knows their machine better than a threshold does).
MILLION_FLOOR_ARTICLES = 500_000

#: Heartbeats: one an hour, bounded like the expedition log's event ring so a run that
#: lasts a fortnight cannot grow the state file without limit. A full ring SAYS it
#: dropped the oldest rather than presenting a truncated series as complete.
HEARTBEAT_INTERVAL_S = 3600.0
HEARTBEAT_CAP = 240

#: Every interim report is rewritten on this cadence during the soak, so an operator
#: who returns early can download a partial reading rather than nothing.
INTERIM_REPORT_INTERVAL_S = 24 * 3600.0

#: The closed vocabulary for a phase and for a board row.
PHASE_STATUSES = ("measured", "not-measurable-here", "refused", "skipped", "error", "cancelled")

_MIB = 1024 * 1024

#: The soak loop wakes this often to look at the stop event -- a cancel must land in
#: seconds, not at the next hourly heartbeat.
_TICK_S = 5.0

#: A suspend or a wall-clock change is recorded past this bound between two ticks: the
#: session ledger's own threshold, so the run and the chronology agree on what one is.
CLOCK_EVENT_MIN_S = 120.0

#: A pool timeout (``sqlalchemy.exc.TimeoutError``: every connection checked out for
#: 30 s) is transient by nature, and one of them cost Asus seven hours of row 5 and the
#: NUC three rows after a 72-hour soak (RR-2, RR-7). Retried after these waits, then
#: reported. The waits are stoppable: a cancel lands within one tick.
POOL_RETRY_DELAYS_S = (5.0, 15.0, 45.0, 120.0)

#: Row 5 (RR-6): a job whose article counter has not moved for this long, while it is
#: neither parked for an import nor in its uncounted tail (the prune), is PAUSED and
#: reported as stalled -- resumable from its cursor, never discarded. Slow is not
#: stalled: the Qubes VMs re-indexed for 60 hours and moved the whole time.
ROW5_STALL_S = 2 * 3600.0
#: Row 5's progress is sampled into the phase record this often, bounded like the
#: heartbeat ring, so a multi-day job leaves a rate a reader can re-open.
ROW5_SAMPLE_S = 600.0
ROW5_SAMPLE_CAP = 288
#: After row 5, collection is put back only once the old pass thread has exited; this
#: long at most, which on any real machine is far longer than a pass's wind-down.
RESUME_COLLECTION_WAIT_S = 3600.0

# --------------------------------------------------------------------------- #
#  Parameters
# --------------------------------------------------------------------------- #


@dataclass
class RunParams:
    dest_dir: str
    passphrase: str
    profile: str = "release-scale"
    soak_hours: float = SOAK_BAR_HOURS
    include_newsletters: bool = True
    online_probes: bool = True
    run_row5_quarantine: bool = False
    legacy_backup_path: str = ""
    keep_fresh_install: bool = False
    note: str = ""

    def validate(self) -> None:
        if self.profile not in PROFILES:
            raise ValueError(f"profile must be one of {PROFILES}, not {self.profile!r}")
        if not self.passphrase:
            raise ValueError("a backup passphrase is required")
        if not (0 < float(self.soak_hours) <= 24 * 60):
            raise ValueError("soak_hours must be a positive number of hours (at most 60 days)")


# --------------------------------------------------------------------------- #
#  State file (survives a restart; never carries the passphrase)
# --------------------------------------------------------------------------- #


def _run_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "diagnostics" / "release-run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _run_dir() / "state.json"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _stamp_epoch(iso: Any) -> float | None:
    """A run stamp (local time with its offset) as an epoch, or None."""
    if not iso or not isinstance(iso, str):
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


class _PhaseError(Exception):
    """A phase that failed PART of the way: ``partial`` is what it had measured, kept in
    the phase record rather than thrown away with the exception (RR-2). The NUC lost
    three board rows after a 72-hour soak because one read failed and the phase record
    kept nothing. ``status`` is ``error`` unless the cause was a refusal."""

    def __init__(self, message: str, *, partial: dict[str, Any], status: str = "error") -> None:
        super().__init__(message)
        self.partial = partial
        self.status = status


def _is_pool_timeout(exc: BaseException) -> bool:
    try:
        from sqlalchemy.exc import TimeoutError as PoolTimeout
    except Exception:  # noqa: BLE001 - without SQLAlchemy there is no pool to time out
        return False
    return isinstance(exc, PoolTimeout)


#: How a job manager's stored error names a pool timeout (it keeps ``str(exc)``, which
#: drops the class name).
_POOL_TIMEOUT_TEXT = ("QueuePool limit", "connection timed out")


def _sleep_stoppable(ctx: Any, seconds: float) -> None:
    end = time.monotonic() + seconds
    while not ctx.stopping:
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(_TICK_S, left))


def _retrying(ctx: Any, what: str, fn: Any, log: list[dict[str, Any]] | None = None) -> Any:
    """``fn()``, retried after a pool timeout on the ``POOL_RETRY_DELAYS_S`` backoff
    (RR-2, RR-7). Any other error, a cancel, or the last timeout is raised to the caller,
    which records it; every retry is written to ``log`` so a reader sees it happened."""
    delays = (*POOL_RETRY_DELAYS_S, None)
    for attempt, delay in enumerate(delays, start=1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified, then re-raised
            if delay is None or not _is_pool_timeout(exc) or ctx.stopping:
                raise
            if log is not None:
                log.append({"what": what, "attempt": attempt, "waited_s": delay, "at": _now_iso(),
                            "error": f"{type(exc).__name__}: {exc}"[:200]})
            _LOG.warning("release run: %s hit a pool timeout (attempt %d), retrying in %.0f s", what, attempt, delay)
            _sleep_stoppable(ctx, delay)
    raise AssertionError("unreachable")  # pragma: no cover - the loop returns or raises


def read_state() -> dict[str, Any]:
    """The last run's state, or ``{}``. A plain file read -- safe on a slow machine."""
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    """Atomic in-place rewrite; best-effort by design (losing the record must never
    break the run it describes -- the sidecar-resilience lesson)."""
    try:
        p = _state_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        _LOG.warning("could not persist release-run state", exc_info=True)


class _Run:
    """One run's mutable record: phases, heartbeats, artifacts. Thread-safe enough for
    a job thread writing and a status route reading the file it persists."""

    def __init__(self, params: RunParams) -> None:
        self.params = params
        self.started_at = _now_iso()
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.phases: list[dict[str, Any]] = []
        self.heartbeats: list[dict[str, Any]] = []
        self.heartbeats_dropped = 0
        self.soak: dict[str, Any] = {}
        self.artifacts: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.outcome: str | None = None
        self.report_path: str | None = None
        self._current: dict[str, Any] | None = None
        # Resume support (2026-09-18, maintainer-asked): the processes this run lived in,
        # and the soak stretches a restart split it into. A restart never redoes a
        # measured phase; it does restart the soak stretch, because the bar is continuous.
        self.sessions: list[dict[str, Any]] = [{"pid": os.getpid(), "started_at": self.started_at, "kind": "start"}]
        self.soak_stretches: list[dict[str, Any]] = []
        self.resumed = 0
        # RR-4: what the clocks did during the run -- a wall-clock change beside a phase,
        # a suspend inside the soak. Every duration is monotonic; these explain why a
        # wall stamp pair may disagree with it.
        self.clock_adjustments: list[dict[str, Any]] = []
        self.suspends: list[dict[str, Any]] = []
        self._current_mono: float | None = None

    # -- persistence ------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        p = self.params
        return {
            "schema": RELEASE_RUN_SCHEMA,
            "run_id": self.run_id,
            "profile": p.profile,
            "started_at": self.started_at,
            "pid": os.getpid(),
            "params": {
                # NEVER the passphrase.
                "dest_dir": p.dest_dir,
                "soak_hours": p.soak_hours,
                "include_newsletters": p.include_newsletters,
                "online_probes": p.online_probes,
                "run_row5_quarantine": p.run_row5_quarantine,
                "legacy_backup_path": p.legacy_backup_path,
                "keep_fresh_install": p.keep_fresh_install,
                "note": p.note,
            },
            "phase": (self._current or {}).get("name"),
            "phase_started_at": (self._current or {}).get("started_at"),
            "phases": list(self.phases),
            "soak": dict(self.soak),
            "soak_stretches": list(self.soak_stretches),
            "sessions": list(self.sessions),
            "resumed": self.resumed,
            "clock_adjustments": list(self.clock_adjustments),
            "suspends": list(self.suspends),
            "heartbeats": list(self.heartbeats),
            "heartbeats_cap": HEARTBEAT_CAP,
            "heartbeats_dropped": self.heartbeats_dropped,
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings),
            "outcome": self.outcome,
            "report_path": self.report_path,
            "updated_at": _now_iso(),
        }

    def persist(self) -> None:
        _write_state(self.snapshot())

    # -- phases ----------------------------------------------------------- #
    def begin(self, name: str) -> None:
        self._current = {"name": name, "started_at": _now_iso(), "ended_at": None}
        self._current_mono = time.monotonic()
        self.persist()

    def end(self, status: str, detail: str, **extra: Any) -> dict[str, Any]:
        assert status in PHASE_STATUSES, status
        cur = self._current or {"name": "?", "started_at": _now_iso()}
        ended = _now_iso()
        # RR-4: the phase's duration on the monotonic clock. The wall stamps beside it
        # are for reading, never for subtracting: on the NUC a phase "ended" seven hours
        # before it "started", because the clock was corrected in between.
        wall_s = round(time.monotonic() - self._current_mono, 1) if self._current_mono is not None else None
        cur.update({"ended_at": ended, "wall_s": wall_s, "status": status, "detail": detail, **extra})
        a, b = _stamp_epoch(cur.get("started_at")), _stamp_epoch(ended)
        if wall_s is not None and a is not None and b is not None and abs((b - a) - wall_s) > CLOCK_EVENT_MIN_S:
            self.clock_adjustments.append({
                "phase": cur.get("name"), "stamps_s": round(b - a), "wall_s": wall_s,
                "clock_moved_s": round((b - a) - wall_s),
                "basis": ("the phase's wall stamps and its monotonic duration disagree: the wall "
                          "clock was changed (or the machine suspended) during the phase; wall_s "
                          "is the duration, the stamps are only where the clock read"),
            })
        self.phases.append(cur)
        self._current = None
        self._current_mono = None
        self.persist()
        return cur

    def heartbeat(self, sample: dict[str, Any]) -> None:
        self.heartbeats.append(sample)
        if len(self.heartbeats) > HEARTBEAT_CAP:
            drop = len(self.heartbeats) - HEARTBEAT_CAP
            del self.heartbeats[:drop]
            self.heartbeats_dropped += drop
        self.persist()

    # -- resume ----------------------------------------------------------- #
    @classmethod
    def from_state(cls, state: dict[str, Any], passphrase: str) -> _Run:
        """Rebuild an INTERRUPTED run from its state file so it can be resumed: the same
        run id and start; every phase that reached a terminal status kept as it is; the
        phases a restart invalidates (the arming, the soak, the collect, the bundle, and
        anything that ended in ``error``/``cancelled``) dropped so they run again; the
        soak the restart cut short closed as a stretch ``ended_by: restart``, dated from
        its last heartbeat. The passphrase is never in the state, so the caller supplies
        it -- or "" when no remaining phase needs one."""
        prm = dict(state.get("params") or {})
        params = RunParams(
            dest_dir=str(prm.get("dest_dir") or ""), passphrase=passphrase,
            profile=str(state.get("profile") or "release-scale"),
            soak_hours=float(prm.get("soak_hours") or SOAK_BAR_HOURS),
            include_newsletters=bool(prm.get("include_newsletters", True)),
            online_probes=bool(prm.get("online_probes", True)),
            run_row5_quarantine=bool(prm.get("run_row5_quarantine", False)),
            legacy_backup_path=str(prm.get("legacy_backup_path") or ""),
            keep_fresh_install=bool(prm.get("keep_fresh_install", False)),
            note=str(prm.get("note") or ""),
        )
        run = cls(params)
        run.run_id = str(state.get("run_id"))
        run.started_at = str(state.get("started_at") or run.started_at)
        phases = [dict(ph) for ph in (state.get("phases") or []) if isinstance(ph, dict)]
        # A COMPLETED SOAK IS KEPT (RR-6). Row 5 now runs after the bundle and can take
        # days, so a restart inside it must not throw away a 72-hour soak that finished:
        # only the phases after the soak that did not reach a terminal status are redone.
        # A soak that did NOT complete is redone with its arming, as before: the bar is
        # continuous, and the process that armed it is gone.
        soak_ph = next((ph for ph in phases if ph.get("name") == "soak"), None)
        soak_complete = bool(soak_ph and soak_ph.get("status") == "measured"
                             and soak_ph.get("ended_by") in ("window-complete", "collect-now"))
        redo = () if soak_complete else _REDONE_ON_RESUME
        kept, dropped = [], []
        for ph in phases:
            if ph.get("status") in _TERMINAL_OK and ph.get("name") not in redo:
                kept.append(ph)
            else:
                dropped.append(f"{ph.get('name')}:{ph.get('status')}")
        run.phases = kept
        run.heartbeats = [dict(h) for h in (state.get("heartbeats") or []) if isinstance(h, dict)]
        run.heartbeats_dropped = int(state.get("heartbeats_dropped") or 0)
        run.artifacts = dict(state.get("artifacts") or {})
        run.warnings = list(state.get("warnings") or [])
        run.soak_stretches = [dict(s) for s in (state.get("soak_stretches") or []) if isinstance(s, dict)]
        run.sessions = [dict(s) for s in (state.get("sessions") or []) if isinstance(s, dict)] or run.sessions
        run.clock_adjustments = [dict(c) for c in (state.get("clock_adjustments") or []) if isinstance(c, dict)]
        run.suspends = [dict(c) for c in (state.get("suspends") or []) if isinstance(c, dict)]
        run.resumed = int(state.get("resumed") or 0) + 1
        prev_soak = dict(state.get("soak") or {})
        if soak_complete:
            run.soak = prev_soak
            if any(d.split(":", 1)[0] in ("collect", "bundle") for d in dropped):
                run.warnings.append(
                    "the end-of-window readings were taken again after a restart, by a process that "
                    "did not run the soak: the soak window and the lane counters are read from the "
                    "store and still describe it, P0.3's collector check describes the resumed process"
                )
        elif prev_soak.get("started_at") and not prev_soak.get("ended_at"):
            last_beat = run.heartbeats[-1] if run.heartbeats else {}
            prev_soak["ended_by"] = "restart"
            prev_soak["ended_at"] = last_beat.get("at") or state.get("updated_at")
            if last_beat.get("elapsed_h") is not None:
                prev_soak["elapsed_hours"] = last_beat.get("elapsed_h")
            prev_soak["end_basis"] = (
                "the last heartbeat before the restart (to the hour); the state file's "
                "updated_at when no heartbeat was kept"
            )
            run.soak_stretches.append(prev_soak)
        if not soak_complete:
            run.soak = {}
        run.sessions.append({
            "pid": os.getpid(), "started_at": _now_iso(), "kind": "resume",
            "interrupted_phase": state.get("phase"), "previous_pid": state.get("pid"),
            "previous_updated_at": state.get("updated_at"), "phases_rerun": dropped,
        })
        run.warnings.append(
            f"resumed after a restart (resume #{run.resumed}): the measured phases were kept, "
            + ("including the completed soak" if soak_complete
               else "the soak stretch started over because the bar is continuous")
        )
        return run


#: A phase with one of these statuses is DONE for a resume -- it is never run twice.
_TERMINAL_OK = ("measured", "skipped", "refused", "not-measurable-here")
#: Phases a restart invalidates whatever their status: the process that armed the soak
#: is gone, the soak is a new stretch, and collect/bundle read the end of the window.
_REDONE_ON_RESUME = ("arm_soak", "soak", "collect", "bundle")


def _ledger_event(event: str, **fields: Any) -> None:
    """A line on the session ledger's timeline; best-effort, never in the run's way."""
    with contextlib.suppress(Exception):
        from src.monitoring.session_history import record_event

        record_event(event, **fields)


def resume_preflight(passphrase: str = "", *, check_passphrase: bool = True) -> dict[str, Any]:
    """What a resume would do, or why it cannot -- the route's 400 text and the panel's
    hint both come from here, and the worker re-checks the same thing before it starts.
    Only an INTERRUPTED run resumes: a state file with no outcome, written by another
    process. A finished run is finished; a run in flight belongs to its own job."""
    state = read_state()
    if not state.get("run_id"):
        raise ValueError("no release run has been recorded on this instance")
    if state.get("outcome") is not None:
        raise ValueError(f"the last run finished ({state.get('outcome')}); nothing to resume -- start a new run")
    if state.get("pid") == os.getpid():
        raise ValueError("that run belongs to this process and is still in flight")
    done = {ph.get("name") for ph in (state.get("phases") or [])
            if isinstance(ph, dict) and ph.get("status") in _TERMINAL_OK}
    needs = not ({"p0_validation", "fresh_install_restore"} <= done)
    if check_passphrase and needs and not passphrase:
        raise ValueError(
            "the run was interrupted before the backup and the fresh-install restore had "
            "finished; enter the backup passphrase to resume them"
        )
    return {
        "run_id": state.get("run_id"), "profile": state.get("profile"),
        "interrupted_phase": state.get("phase"), "phases_done": sorted(str(d) for d in done),
        # "unlock_needed", not "needs_passphrase": the endpoint scrubber redacts any KEY
        # that contains the word, and a redacted boolean cannot drive a button.
        "unlock_needed": needs, "resumed_before": int(state.get("resumed") or 0),
        "soak_stretches_so_far": len(state.get("soak_stretches") or []) + (1 if (state.get("soak") or {}).get("started_at") else 0),
    }


# --------------------------------------------------------------------------- #
#  Small readers (each degrades to a stated absence, never to a fabricated 0)
# --------------------------------------------------------------------------- #


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / _MIB, 1)
    except Exception:  # noqa: BLE001 - RSS is best-effort
        return None


def _process_uptime_s() -> float | None:
    """How long this process has been running, on the session ledger's monotonic clock
    (RR-4). The psutil fallback subtracts a creation time from the wall clock, which a
    clock change moves; it is used only where the ledger never opened a session."""
    with contextlib.suppress(Exception):
        from src.monitoring.session_history import current_session

        up = current_session().get("uptime_s")
        if up is not None:
            return round(float(up), 1)
    try:
        import psutil

        return round(time.time() - psutil.Process().create_time(), 1)
    except Exception:  # noqa: BLE001
        return None


def _hardware() -> dict[str, Any]:
    out: dict[str, Any] = {"cores": os.cpu_count()}
    try:
        import psutil

        vm = psutil.virtual_memory()
        out["ram_total_mb"] = round(vm.total / _MIB)
        out["ram_available_mb"] = round(vm.available / _MIB)
    except Exception:  # noqa: BLE001
        out["ram_total_mb"] = None
        out["ram_available_mb"] = None
    return out


def _corpus_bytes() -> int | None:
    """The live store's on-disk size (the corpus file plus its -wal, plus every lane
    file), for the disk preflight. None when the backend is not a file."""
    total = 0
    try:
        from src.api.unlock import main_db_path

        p = main_db_path()
        if p is None:
            return None
        for cand in (p, Path(str(p) + "-wal")):
            with contextlib.suppress(OSError):
                total += cand.stat().st_size
    except Exception:  # noqa: BLE001
        return None
    with contextlib.suppress(Exception):
        from src.versioned.store import lane_file_bytes

        for kind in ("wiki", "law", "osm"):
            b = lane_file_bytes(kind)
            if b:
                total += int(b)
    return total


def _free_bytes_under(dest: Path) -> int | None:
    anchor = dest
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    try:
        return int(shutil.disk_usage(anchor).free)
    except OSError:
        return None


def _article_count() -> int | None:
    """One COUNT(*) at preflight. A deliberate one-off on a button press -- never on a
    panel open (the recorded diagnostics-section rule: expanding it fetches nothing)."""
    try:
        from sqlalchemy import func, select

        from src.database.models import Article
        from src.database.session import session_scope

        with session_scope() as db:
            return int(db.execute(select(func.count(Article.id))).scalar_one())
    except Exception:  # noqa: BLE001
        return None


def _statement_deadline_present() -> bool:
    """Row C's bar names 'a build carrying the statement_deadline fix'."""
    try:
        from src.database.maintenance import statement_deadline  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _network_state() -> dict[str, Any]:
    out: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        from src.ingest import kill_switch_active

        out["kill_switch_active"] = bool(kill_switch_active())
    with contextlib.suppress(Exception):
        from src.scheduler.runner import get_scheduler

        out["scheduler_running"] = bool(get_scheduler().is_running())
    with contextlib.suppress(Exception):
        from src.wiki.service import lane_service_status

        out["wiki_lane"] = lane_service_status()
    return out


# --------------------------------------------------------------------------- #
#  Phase 0 -- preflight
# --------------------------------------------------------------------------- #


def _preflight(run: _Run) -> dict[str, Any]:
    """Refuses only what would fail loudly mid-run; everything else is recorded."""
    from src.monitoring.p0_validation import backup_engine_format, validate_dest_dir
    from src.utils.export_envelope import app_version

    p = run.params
    dest = validate_dest_dir(p.dest_dir)  # raises ValueError -> refused by the caller
    corpus = _corpus_bytes()
    free = _free_bytes_under(dest)
    facts: dict[str, Any] = {
        "app_version": app_version(),
        "backup_engine_format": backup_engine_format(),
        "statement_deadline_fix_present": _statement_deadline_present(),
        "dest_dir": str(dest),
        "corpus_bytes": corpus,
        "dest_free_bytes": free,
        "hardware": _hardware(),
        "network_before": _network_state(),
        "process_uptime_s": _process_uptime_s(),
    }
    with contextlib.suppress(Exception):
        from src.backup.artifact import BACKUP_SCHEMA

        facts["backup_schema"] = BACKUP_SCHEMA
    n = _article_count()
    facts["articles"] = n
    facts["articles_method"] = "COUNT(*) over articles, once, at preflight"
    if p.profile == "million" and n is not None and n < MILLION_FLOOR_ARTICLES:
        run.warnings.append(
            f"the 'million' profile was chosen but this corpus holds {n:,} articles "
            f"(under {MILLION_FLOOR_ARTICLES:,}); row C's bar is the ~1M instance, so read "
            "this run's bundle as evidence at THIS scale, not at that one"
        )
    if p.profile == "release-scale" and n is not None and n >= MILLION_FLOOR_ARTICLES:
        run.warnings.append(
            f"this corpus holds {n:,} articles; the 'million' profile would have marked row "
            "C's bundle as the required artifact"
        )
    # Disk: the backup alone needs about one corpus; the staged restore probe and the
    # fresh install each need another. Refuse only the first; degrade the rest.
    if corpus and free is not None:
        facts["disk_needed_for_backup_bytes"] = int(corpus * 1.2)
        facts["disk_needed_for_full_run_bytes"] = int(corpus * 3.2)
        if free < corpus * 1.2:
            raise ValueError(
                f"the destination has {free / _MIB:,.0f} MiB free and the backup alone "
                f"needs about {corpus * 1.2 / _MIB:,.0f} MiB -- choose a larger drive"
            )
        facts["fresh_install_fits"] = free >= corpus * 3.2
    else:
        facts["fresh_install_fits"] = None
    return facts


# --------------------------------------------------------------------------- #
#  Phase 1 -- 0.3 row 5, the Tier-A quarantine pass (OPT-IN, deferred by ruling A1)
# --------------------------------------------------------------------------- #


def _exclusive_open() -> bool:
    try:
        from src.scheduler.runner import exclusive_window_open

        return bool(exclusive_window_open())
    except Exception:  # noqa: BLE001 - unknown is "not parked"
        return False


def _pause_collection() -> dict[str, Any]:
    """Stop the collector and the Wikipedia lane for row 5 (FD01, FD02: the soak is done,
    and a 4 GB machine with 1 GB of swap cannot carry a whole-corpus re-index beside
    collection -- two of the Qubes VMs ended the way an out-of-memory kill does).

    NOT an exclusive window, deliberately: the quarantine job and the re-index both PARK
    while one is open (they stand aside for an import), so claiming it here would stop
    the very jobs it is making room for, forever. The network state is not touched
    either: going offline and back would be a new offline->online transition the
    operator never consented to."""
    out: dict[str, Any] = {"scheduler_was_running": False, "wiki_lane_was_streaming": False}
    try:
        from src.scheduler.runner import get_scheduler

        sched = get_scheduler()
        out["scheduler_was_running"] = bool(sched.is_running())
        if out["scheduler_was_running"]:
            sched.stop(timeout=30.0)
            # stop()'s join is bounded; a pass deep in a write can outlive it. Said, not hidden.
            out["scheduler_still_winding_down"] = bool(sched.is_running())
    except Exception as exc:  # noqa: BLE001
        out["scheduler_error"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        from src.wiki.service import lane_service_status, stop_wiki_lane

        out["wiki_lane_was_streaming"] = bool((lane_service_status() or {}).get("streaming"))
        if out["wiki_lane_was_streaming"]:
            stop_wiki_lane(timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        out["wiki_lane_error"] = f"{type(exc).__name__}: {exc}"[:300]
    out["at"] = _now_iso()
    return out


def _resume_collection(paused: dict[str, Any] | None) -> dict[str, Any]:
    """Put back what row 5 stopped, and only that. Never over the operator's airplane
    mode. The collector is restarted only once its old pass thread has exited -- the
    wait SCHED-1 lacked: one refused ``start()`` there left Lenn's collector off for
    five days, because a pass winding down on a write-bound machine outlived every
    retry."""
    if not paused:
        return {"resumed": False, "reason": "nothing was paused"}
    out: dict[str, Any] = {"at": _now_iso()}
    try:
        from src.ingest import kill_switch_active
    except Exception:  # noqa: BLE001

        def kill_switch_active() -> bool:  # type: ignore[misc]
            return False
    if paused.get("scheduler_was_running"):
        try:
            from src.scheduler.runner import get_scheduler

            sched = get_scheduler()
            deadline = time.monotonic() + RESUME_COLLECTION_WAIT_S
            started = False
            while True:
                if kill_switch_active():
                    out["scheduler"] = "left stopped: airplane mode is on, so collection waits for the operator to go online"
                    break
                if sched.start():
                    started = True
                    break
                if time.monotonic() >= deadline:
                    out["scheduler"] = ("NOT restarted: the previous pass thread was still running after "
                                        f"{RESUME_COLLECTION_WAIT_S:.0f} s -- restart collection from the task manager")
                    _LOG.warning("release run: collection could not be restarted after row 5")
                    break
                time.sleep(_TICK_S)
            out["scheduler_restarted"] = started
        except Exception as exc:  # noqa: BLE001
            out["scheduler_error"] = f"{type(exc).__name__}: {exc}"[:300]
    if paused.get("wiki_lane_was_streaming"):
        if kill_switch_active():
            out["wiki_lane"] = "left stopped: airplane mode is on"
        else:
            try:
                from src.wiki.service import start_wiki_lane

                out["wiki_lane_restarted"] = bool(start_wiki_lane())
            except Exception as exc:  # noqa: BLE001
                out["wiki_lane_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


def _wait_job(ctx: Any, run: _Run, label: str, mgr: Any, out: dict[str, Any]) -> dict[str, Any]:
    """Wait for one row-5 job, and never blindly (RR-6, RR-7). While it runs: its counter
    is published as the run's progress and sampled into the phase record, an interim
    report is rewritten on the soak's cadence, a pool-timeout error is resumed from the
    job's cursor on the retry backoff, and a counter that has not moved for
    ``ROW5_STALL_S`` pauses the job and says so. A job parked for an import, or in its
    uncounted tail (the re-index's prune), is not stalled. A cancel pauses the job
    rather than leaving it running under a run that has stopped: paused, it resumes
    from its cursor whenever the operator wants."""
    samples: list[dict[str, Any]] = out.setdefault(f"{label}_progress", [])
    retries: list[dict[str, Any]] = out.setdefault("retries", [])
    t0 = time.monotonic()
    last_done: Any = None
    last_move = t0
    next_sample = t0
    next_interim = t0 + INTERIM_REPORT_INTERVAL_S
    resumed = 0
    while True:
        st = dict(mgr.status() or {})
        state = str(st.get("state") or "")
        done, total = st.get("articles_done"), st.get("articles_total")
        now = time.monotonic()
        if done != last_done:
            last_done, last_move = done, now
        tail = bool(total) and done is not None and done >= total
        parked = bool(st.get("parked_for_exclusive")) or _exclusive_open()
        if now >= next_sample:
            samples.append({"at": _now_iso(), "elapsed_s": round(now - t0), "done": done, "total": total,
                            "percent": st.get("percent"), "state": state, "parked": parked,
                            "articles_per_hour": st.get("articles_per_hour")})
            if len(samples) > ROW5_SAMPLE_CAP:
                del samples[1:len(samples) - ROW5_SAMPLE_CAP + 1]  # keep the first; drop the oldest after it
                out[f"{label}_progress_dropped"] = int(out.get(f"{label}_progress_dropped") or 0) + 1
            next_sample = now + ROW5_SAMPLE_S
        if tail and state == "running":
            what = "pruning orphan keywords and reconciling (no counter)"
        elif parked:
            what = "parked: an import owns the machine"
        else:
            what = f"{done if done is not None else '?'} of {total if total is not None else '?'}" + (
                f" ({st.get('percent')} %)" if st.get("percent") is not None else "")
        ctx.set_progress(detail=f"row 5: {label} -- {what}")
        err = str(st.get("error") or "")
        if (state == "error" and any(t in err for t in _POOL_TIMEOUT_TEXT)
                and resumed < len(POOL_RETRY_DELAYS_S) and not ctx.stopping):
            delay = POOL_RETRY_DELAYS_S[resumed]
            retries.append({"what": f"{label} job", "attempt": resumed + 1, "waited_s": delay, "at": _now_iso(),
                            "error": err[:200]})
            _sleep_stoppable(ctx, delay)
            if ctx.stopping:
                continue
            with contextlib.suppress(RuntimeError):
                mgr.resume()
            resumed += 1
            last_move = time.monotonic()
            continue
        if state == "paused":
            return st
        if state != "running" and not st.get("running"):
            return st
        if ctx.stopping:
            with contextlib.suppress(Exception):
                mgr.pause()
            st = dict(mgr.status() or {})
            st["paused_by"] = "the release run was cancelled; the job is paused at its cursor, not discarded"
            return st
        if not tail and not parked and now - last_move > ROW5_STALL_S:
            with contextlib.suppress(Exception):
                mgr.pause()
            st = dict(mgr.status() or {})
            st["stalled"] = {
                "no_progress_for_s": round(now - last_move), "bound_s": ROW5_STALL_S, "at_count": done,
                "basis": ("the article counter did not move for the bound while the job was neither "
                          "parked for an import nor in its uncounted tail; the job was PAUSED at its "
                          "cursor and can be resumed from the task manager"),
            }
            return st
        if now >= next_interim:
            with contextlib.suppress(Exception):
                _write_report(run, interim=True)
            _ledger_event("release-run", action="interim-report", run_id=run.run_id, phase="row5_quarantine")
            next_interim = now + INTERIM_REPORT_INTERVAL_S
        time.sleep(_TICK_S)


def _row5_quarantine(ctx: Any, run: _Run) -> dict[str, Any]:
    """The four commands of ``RELEASE_0.3_GATE.md`` §7.1, in order, with the two mode
    checks that section warns about read back from the run itself.

    WHAT IT COSTS, SAID (RR-6, FD01): a quarantine pass over every article, then a
    whole-corpus keyword re-index with the orphan prune -- hours on a small corpus, days
    on a slow machine (50 to 61 hours on the 4 GB Qubes VMs, where it did not finish).
    So it runs AFTER the soak, the collect and the bundle, with collection paused, and a
    failure keeps everything it had measured."""
    from src.analytics.quarantine_job import get_quarantine_manager
    from src.analytics.reindex_job import get_reindex_manager

    out: dict[str, Any] = {"retries": []}
    out["collection_paused"] = _pause_collection()
    try:
        qm = get_quarantine_manager()
        prior = dict(qm.status() or {})
        if prior.get("state") == "paused" and prior.get("articles_done"):
            # A restart inside row 5 left the quarantine PAUSED at its cursor (the manager
            # restores an interrupted run that way). Continue it rather than scan again
            # from the first article -- but only if it is THIS run's mode; another paused
            # run is the operator's, and is refused by name rather than overwritten.
            if prior.get("dry_run") is False and prior.get("include_prose_gate") is False \
                    and not prior.get("index_page_tiers"):
                out["quarantine_started"] = qm.resume()
                out["quarantine_continued_from"] = prior.get("articles_done")
            else:
                raise RuntimeError(
                    f"a different quarantine run is paused at {prior.get('articles_done')} articles "
                    f"(dry_run={prior.get('dry_run')}, include_prose_gate={prior.get('include_prose_gate')}); "
                    "resume or cancel it from the task manager first")
        else:
            out["quarantine_started"] = qm.start(write=True, include_prose_gate=False)  # RuntimeError -> refused
        st = _wait_job(ctx, run, "quarantine", qm, out)
        out["quarantine_final"] = st
        # §7.1 step 2: a run under the wrong criteria reports a tally that looks legitimate.
        out["mode_ok"] = (st.get("dry_run") is False) and (st.get("include_prose_gate") is False)
        if ctx.stopping or st.get("stalled") or st.get("state") == "paused":
            return out
        if st.get("state") != "done":
            out["reindex_skipped"] = (
                f"the quarantine pass ended '{st.get('state')}' ({st.get('error') or 'no error text'}), so the "
                "re-index was not started: a composition read over a half-applied quarantine would describe "
                "a run that never happened")
            raise _PhaseError(f"row 5: the quarantine pass ended '{st.get('state')}'", partial=out)
        ctx.set_progress(detail="row 5: re-index (keywords, prune after)")
        rm = get_reindex_manager()
        try:
            out["reindex_started"] = _retrying(
                ctx, "re-index start", lambda: rm.start(scope="keywords", prune_after=True, restart=False),
                out["retries"])
        except RuntimeError as exc:
            # A re-index already running, or a DIFFERENT one paused: the quarantine is done
            # and its tally is kept; the re-index is the operator's to resolve.
            raise _PhaseError(f"row 5: the re-index was refused: {exc}"[:400], partial=out, status="refused") from exc
        rs = _wait_job(ctx, run, "reindex", rm, out)
        out["reindex_final"] = rs
        if ctx.stopping or rs.get("stalled") or rs.get("state") == "paused":
            return out
        if rs.get("state") != "done":
            raise _PhaseError(f"row 5: the re-index ended '{rs.get('state')}'", partial=out)
        from src.analytics.figures import quarantine_composition
        from src.database.session import session_scope

        def _composition() -> Any:
            with session_scope() as db:
                return quarantine_composition(db, limit=40)

        out["composition"] = _retrying(ctx, "quarantine composition", _composition, out["retries"])
        return out
    except (_PhaseError, RuntimeError):
        raise
    except Exception as exc:  # noqa: BLE001 - keep what row 5 measured (RR-2)
        raise _PhaseError(f"{type(exc).__name__}: {exc}"[:400], partial=out) from exc
    finally:
        out["collection_resumed"] = _resume_collection(out.get("collection_paused"))


# --------------------------------------------------------------------------- #
#  Phase 2 -- the P0 trio into a dated export folder (rows J/K)
# --------------------------------------------------------------------------- #


def _p0_into_dated_folder(ctx: Any, run: _Run) -> dict[str, Any]:
    from src.backup.export_folder import allocate_export_folder
    from src.monitoring.p0_validation import run_p0_validation

    dated = allocate_export_folder(run.params.dest_dir)  # ExportFolderError -> refused
    run.artifacts["backup_folder"] = str(dated)
    run.persist()
    res = run_p0_validation(
        ctx,
        dest_dir=str(dated),
        passphrase=run.params.passphrase,
        include_newsletters=run.params.include_newsletters,
        # One full pass at scale; the incremental-refresh property is the P0 box's own
        # measurement and is not repeated here (it would double the backup time).
        measure_incremental=False,
    )
    report = res.get("report") or {}
    return {
        "backup_folder": str(dated),
        "p0_report_path": res.get("path"),
        "checks": {k: {"verdict": v.get("verdict"), "reason": v.get("reason")}
                   for k, v in (report.get("checks") or {}).items()},
        "summary": report.get("summary"),
        "backup_engine_format": report.get("backup_engine_format"),
        "backup_measurements": (
            (report.get("checks") or {}).get("p0_1_backup", {}).get("measurements")
        ),
    }


# --------------------------------------------------------------------------- #
#  Phase 3 -- the committed restore into a throwaway FRESH install (rows A/E/I/K)
# --------------------------------------------------------------------------- #


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fresh_install_restore(
    ctx: Any, run: _Run, backup_path: Path, *, label: str
) -> dict[str, Any]:
    """Spawn the helper with its OWN data dir. Two processes are what actually gives two
    corpora (the module-level engine singleton makes an in-process attempt a
    self-restore). The child's corpus is ENCRYPTED under the backup passphrase, so no
    plaintext copy of the operator's corpus ever sits on the drive; the dir carries the
    ``.restore-`` prefix the backup engine's own sweeper reclaims after a crash."""
    dest = Path(run.params.dest_dir).expanduser().resolve()
    fresh = dest / f".restore-release-run-{label}-{os.getpid()}"
    out_json = fresh.with_suffix(".json")
    env = {
        **os.environ,
        "OO_DATA_DIR": str(fresh),
        "OO_DB_PASSPHRASE": run.params.passphrase,
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
        "OO_RELEASE_RUN_BACKUP": str(backup_path),
        "OO_RELEASE_RUN_OUT": str(out_json),
    }
    env.pop("OO_DB_PLAINTEXT", None)
    t0 = time.monotonic()
    fresh.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(  # noqa: S603 - our own interpreter, our own module, no shell
        [sys.executable, "-m", "src.monitoring.release_run_fresh_restore"],
        cwd=str(_repo_root()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while proc.poll() is None:
            if ctx.stopping:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            ctx.set_progress(detail=f"fresh install ({label}): restoring, {time.monotonic() - t0:,.0f} s")
            time.sleep(2.0)
        stdout, stderr = proc.communicate(timeout=30)
        result: dict[str, Any] = {
            "label": label,
            "backup": str(backup_path),
            "fresh_dir": str(fresh),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "returncode": proc.returncode,
            "stderr_tail": (stderr or "")[-4000:],
        }
        payload: dict[str, Any] | None = None
        with contextlib.suppress(OSError, ValueError):
            payload = json.loads(out_json.read_text(encoding="utf-8"))
        if payload is None:
            with contextlib.suppress(ValueError, IndexError):
                payload = json.loads((stdout or "").strip().splitlines()[-1])
        result["child"] = payload
        return result
    finally:
        if not run.params.keep_fresh_install:
            shutil.rmtree(fresh, ignore_errors=True)
            with contextlib.suppress(OSError):
                out_json.unlink()


# --------------------------------------------------------------------------- #
#  Phase 4 -- arm the soak (rows B/D/P and the drain of row A)
# --------------------------------------------------------------------------- #


def _arm_soak(run: _Run) -> dict[str, Any]:
    """The ONE seam in (the network toggle's own function: collector + wiki lane), then
    the unattended kit (the measured drain decision + the expedition log). Never a
    second way to go online."""
    from src.api.system import set_network_mode, unattended_start

    net = set_network_mode({"online": True})
    armed = unattended_start({"note": run.params.note or f"0.4 release run ({run.params.profile})"})
    return {"network": net, "unattended": armed, "after": _network_state()}


def _heartbeat_sample(run: _Run) -> dict[str, Any]:
    started_mono = run.soak.get("started_mono")
    elapsed = (time.monotonic() - float(started_mono)) if started_mono is not None \
        else (time.time() - float(run.soak.get("started_epoch") or time.time()))
    sample: dict[str, Any] = {
        "at": _now_iso(),
        # RR-4: monotonic, so a clock change can neither end the window early nor grow it.
        "elapsed_h": round(elapsed / 3600.0, 2),
        "stretch": run.soak.get("stretch"),
        "rss_mb": _rss_mb(),
        "process_uptime_s": _process_uptime_s(),
    }
    with contextlib.suppress(Exception):
        from src.scheduler import memguard

        st = memguard.memory_guard.state()
        sample["memory_guard"] = {
            "engaged": st.get("engaged"),
            "engagements": st.get("engagements"),
            "total_engaged_s": st.get("total_engaged_s"),
        }
    sample.update(_network_state())
    return sample


# --------------------------------------------------------------------------- #
#  Online probes (rows P/Q/T) -- only while online, every refusal named
# --------------------------------------------------------------------------- #


def _law_live_checks() -> dict[str, Any]:
    """Fetch ONE tracked document per priority host through the ethical fetcher, and
    parse the CLML one with the adapter. URLs come from the catalogue, never from a
    literal here, so the host enumeration guard stays the single list."""
    from src.ingest import EthicalFetcher, FetchError
    from src.law.catalog import load_legal_catalog

    priority = ("legislation.gov.uk", "eur-lex.europa.eu", "gesetze-im-internet.de")
    catalog = load_legal_catalog()
    docs = catalog.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    picked: dict[str, dict] = {}
    for d in docs:
        url = str((d or {}).get("url") or "")
        for host in priority:
            if host in url and host not in picked:
                picked[host] = d
    fetcher = EthicalFetcher(timeout=45.0)
    out: dict[str, Any] = {}
    for host in priority:
        d = picked.get(host)
        if not d:
            out[host] = {"measured": False, "reason": "no tracked document for this host in configs/legal_sources.yml"}
            continue
        entry: dict[str, Any] = {"url": d.get("url"), "title": d.get("title")}
        t0 = time.monotonic()
        try:
            r = fetcher.fetch(str(d["url"]), require_html=False, keep_bytes=True)
            entry.update({"measured": True, "status_code": r.status_code,
                          "bytes": len(r.raw_content or b"") if getattr(r, "raw_content", None) else len(r.content or ""),
                          "elapsed_s": round(time.monotonic() - t0, 2)})
        except FetchError as exc:
            entry.update({"measured": False, "refusal": type(exc).__name__, "detail": str(exc)[:300],
                          "elapsed_s": round(time.monotonic() - t0, 2)})
        except Exception as exc:  # noqa: BLE001
            entry.update({"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        if host == "legislation.gov.uk" and entry.get("measured") and d.get("official_url"):
            # The per-document CLML the catalogue records as this host's bulk shape,
            # composed from the row's own official_url rather than typed here.
            clml_url = str(d["official_url"]).rstrip("/") + "/data.xml"
            try:
                from src.law.adapters.clml import parse_clml

                r = fetcher.fetch(clml_url, require_html=False, keep_bytes=True)
                raw: bytes = r.raw_content or (r.content or "").encode("utf-8")
                parsed = parse_clml(raw)
                prov = getattr(parsed, "provisions", None)
                entry["clml"] = {
                    "url": clml_url, "status_code": r.status_code, "bytes": len(raw),
                    "provisions": len(prov) if prov is not None else None,
                    "adapter_read_it": True,
                }
            except FetchError as exc:
                entry["clml"] = {"url": clml_url, "refusal": type(exc).__name__, "detail": str(exc)[:300]}
            except Exception as exc:  # noqa: BLE001
                entry["clml"] = {"url": clml_url, "error": f"{type(exc).__name__}: {exc}"[:300]}
        out[host] = entry
    return out


def _ores_probe() -> dict[str, Any]:
    """Q717: does the scoring endpoint still answer? Uses the lane's own newest revision
    when it has one, so the request is a real one; names the fallback otherwise."""
    from src.wiki.ores import ORES_AS_OF, OresClient

    revid: int | None = None
    wiki = "en"
    with contextlib.suppress(Exception):
        from sqlalchemy import select

        from src.versioned.models import VersionedChange
        from src.versioned.store import LaneAbsentError, lane_path, lane_session

        if lane_path("wiki").is_file():
            try:
                with lane_session("wiki") as lane:
                    row = lane.execute(
                        select(VersionedChange.change_ref, VersionedChange.feed)
                        .order_by(VersionedChange.id.desc())
                        .limit(1)
                    ).first()
            except LaneAbsentError:
                row = None
            if row and row[0]:
                tail = str(row[0]).rsplit("|", 1)[-1].strip()
                if tail.isdigit():
                    revid = int(tail)
                    feed = str(row[1] or "")
                    if feed and "." in feed:
                        wiki = feed.split(".", 1)[0][:8] or "en"
    client = OresClient()
    probe_revid = revid if revid is not None else 1
    scores = client.score(wiki, [probe_revid])
    return {
        "endpoint_as_of": ORES_AS_OF,
        "wiki": wiki,
        "revid": probe_revid,
        "revid_source": "the lane's newest recorded change" if revid is not None else "fallback revid 1 (the lane had no rows yet)",
        "outcome": client.last_outcome,
        "detail": client.last_detail,
        "scored": bool(scores),
    }


def _weights_digest_proposal() -> dict[str, Any]:
    """Row T's operator input, FETCHED rather than typed: the Hugging Face commit SHA of
    the roster model and the Ollama manifest digest of the roster tag. Written into the
    report as a PROPOSAL; nothing here edits ``src/llm/weights_pin.py`` or the registry
    -- pasting a value the maintainer read is their act, which is what makes it a pin."""
    from src.llm.ollama import MINISTRAL_TAG, MINISTRAL_VLLM_MODEL

    out: dict[str, Any] = {"hf": {"model": MINISTRAL_VLLM_MODEL}, "ollama": {"tag": MINISTRAL_TAG}}
    try:
        from src.safety.fetcher import guarded_session

        s = guarded_session()
        r = s.get(f"https://huggingface.co/api/models/{MINISTRAL_VLLM_MODEL}", timeout=30)
        if getattr(r, "status_code", None) == 200:
            sha = str((r.json() or {}).get("sha") or "")
            out["hf"].update({"measured": True, "sha": sha, "basis": "GET /api/models/<repo> -> sha (the repo's commit)"})
        else:
            out["hf"].update({"measured": False, "status_code": getattr(r, "status_code", None)})
    except Exception as exc:  # noqa: BLE001
        out["hf"].update({"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
    try:
        from src.llm.ollama import OllamaClient

        rows = OllamaClient(timeout=20.0).list_installed_detailed()
        hit = next((m for m in rows if m.get("tag") == MINISTRAL_TAG), None)
        if hit is None:
            out["ollama"].update({"measured": False, "reason": "the roster tag is not installed locally"})
        else:
            out["ollama"].update({"measured": bool(hit.get("digest")), "digest": hit.get("digest"),
                                  "basis": "the local Ollama's /api/tags manifest digest"})
    except Exception as exc:  # noqa: BLE001
        out["ollama"].update({"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
    out["how_to_pin"] = (
        "set OO_MODEL_REVISION to the 40-character sha and OO_OLLAMA_MODEL_DIGEST to the "
        "digest, or record them in src/llm/weights_pin.py's HF_REVISION_PINS / "
        "OLLAMA_DIGEST_PINS in a PR of your own -- a value is a pin only once a person read it"
    )
    return out


# --------------------------------------------------------------------------- #
#  Phase 6 -- collect the end-of-window readings (rows A/B/C/D/E/P)
# --------------------------------------------------------------------------- #


def _collect(ctx: Any, run: _Run) -> dict[str, Any]:
    """The end-of-window readings, EACH ON ITS OWN (RR-2). They used to share one database
    session, so one pool timeout on the second read discarded the first and the phase
    kept nothing -- the NUC lost rows B, D and E that way after 72 hours. Now every block
    gets its own session and the pool-timeout retry, a block that still fails records its
    own error beside the others, and the phase ends ``error`` WITH everything it read."""
    from src.catalog.qualification_integrity import qualification_integrity_report
    from src.database.session import session_scope
    from src.monitoring import expedition
    from src.monitoring.forensics import session_forensics
    from src.monitoring.p0_validation import _check_collector
    from src.monitoring.soak_window import soak_window

    out: dict[str, Any] = {}
    retries: list[dict[str, Any]] = []
    failed: list[str] = []

    def block(key: str, fn: Any, *, core: bool = True) -> None:
        try:
            out[key] = _retrying(ctx, key, fn, retries)
        except Exception as exc:  # noqa: BLE001 - recorded on the block, the others go on
            out[key] = {"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            if core:
                failed.append(key)

    def _sw() -> Any:
        with session_scope() as db:
            return soak_window(db, bar_hours=SOAK_BAR_HOURS)

    def _qi() -> Any:
        with session_scope() as db:
            return qualification_integrity_report(db)

    def _lanes() -> Any:
        from src.api.wiki_lane import lane_counters_route

        hours = float(run.soak.get("elapsed_hours") or 0.0)
        return lane_counters_route(window_days=max(1, min(90, math.ceil(hours / 24.0) + 1)))

    ctx.set_progress(detail="collect: soak window")
    block("soak_window", _sw)
    ctx.set_progress(detail="collect: qualification integrity (live corpus)")
    block("qualification_integrity_live", _qi)
    block("collector", _check_collector)
    ctx.set_progress(detail="collect: lane counters")
    block("wiki_lane_counters", _lanes, core=False)
    out["wiki_lane_service"] = _network_state().get("wiki_lane")
    with contextlib.suppress(Exception):
        out["expedition"] = expedition.digest()
    ctx.set_progress(detail="collect: session forensics")
    with contextlib.suppress(Exception):
        out["session_forensics"] = session_forensics()
    if run.params.online_probes and not ctx.stopping:
        ctx.set_progress(detail="collect: scoring endpoint probe")
        try:
            out["ores_probe"] = _ores_probe()
        except Exception as exc:  # noqa: BLE001
            out["ores_probe"] = {"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    out["pool_retries"] = retries
    if failed:
        raise _PhaseError(f"{len(failed)} end-of-window reading(s) failed: {', '.join(failed)}", partial=out)
    return out


#: Marker files the bundle writes IN PLACE of a member it could not collect. Each is a
#: few dozen bytes, so a "zero-byte member" check never sees the member was missing.
_MARKER_SUFFIXES = {".skipped-deadline.txt": "skipped-deadline", ".error.txt": "error",
                    ".declined.txt": "declined"}


def _read_bundle_archive(path: str) -> dict[str, Any]:
    """What row C's clause needs out of a finished archive, read from where the bundle
    writer PUTS it (RR-1): the coverage block at ``manifest.json`` -> ``run`` ->
    ``runtime_coverage`` (it was read from ``debug-bundle.json``, where it never is, so
    row C could not read satisfied on any machine); and every member's own ``outcome``
    from the manifest (RR-1b), because a member skipped at its deadline is ABSENT and
    replaced by a 52-byte marker -- ``source-audit.json`` was, on four of six machines,
    while the zero-byte list stayed empty."""
    import zipfile

    out: dict[str, Any] = {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        out["members_total"] = len(infos)
        out["zero_byte_members"] = sorted(i.filename for i in infos if i.file_size == 0)
        man: dict[str, Any] = {}
        with contextlib.suppress(KeyError, ValueError):
            man = json.loads(z.read("manifest.json").decode("utf-8")) or {}
        coverage = (man.get("run") or {}).get("runtime_coverage")
        coverage_from = "manifest.json run.runtime_coverage" if coverage is not None else None
        if coverage is None:
            with contextlib.suppress(KeyError, ValueError):
                dbg = json.loads(z.read("debug-bundle.json").decode("utf-8"))
                coverage = dbg.get("runtime_coverage")
                coverage_from = "debug-bundle.json runtime_coverage" if coverage is not None else None
        out["runtime_coverage"] = coverage
        out["runtime_coverage_from"] = coverage_from
        out["coverage_complete"] = bool((coverage or {}).get("complete")) if coverage else None
        # Per-member outcomes, from the manifest; for an archive older than the outcome
        # field, from the marker files it wrote instead of the members.
        members = [m for m in (man.get("members") or []) if isinstance(m, dict) and m.get("file")]
        by_outcome: dict[str, list[str]] = {}
        if members:
            for m in members:
                by_outcome.setdefault(str(m.get("outcome") or ("ok" if m.get("ok") else "unknown")), []).append(str(m["file"]))
            out["outcomes_from"] = "manifest.json members[].outcome"
        else:
            for n in names:
                for suffix, outcome in _MARKER_SUFFIXES.items():
                    if n.endswith(suffix):
                        by_outcome.setdefault(outcome, []).append(n[: -len(suffix)])
            out["outcomes_from"] = "marker files (the archive's manifest carries no member outcomes)"
        out["members_by_outcome"] = {k: sorted(v) for k, v in sorted(by_outcome.items())}
        out["skipped_deadline_members"] = sorted(by_outcome.get("skipped-deadline", []))
        out["error_members"] = sorted(by_outcome.get("error", []))
        out["partial_members"] = sorted(by_outcome.get("partial-deadline", []))
        # WHICH PROFILE THIS ARCHIVE IS (ruling R28, 2026-09-22). The run ASKS for a
        # full bundle, but when one is already building it RIDES that one -- and an
        # operator may have started a LIGHT bundle a minute earlier. A declined member
        # is ABSENT, not zero-byte. `None` means the archive predates the toggle, which
        # is a FULL bundle by construction -- only an explicit `false` may block the row.
        prof = man.get("profile") or {}
        if prof:
            out["profile"] = prof.get("name")
            out["complete_profile"] = prof.get("complete_profile")
            declined = [d for d in (prof.get("declined") or []) if isinstance(d, dict) and d.get("file")]
            out["declined_members"] = sorted(str(d["file"]) for d in declined)
            out["declined_by_machine"] = sorted(str(d["file"]) for d in declined if d.get("declined_by") == "machine")
    return out


def _bundle(ctx: Any) -> dict[str, Any]:
    """Row C: the all-diagnostics job, awaited, and its archive READ -- the coverage
    block, every member's outcome and the profile, which are what the bar names."""
    from src.api.diagnostics.bundle import _ALL_DIAG_JOB

    with contextlib.suppress(RuntimeError):  # already building -- ride the build in flight
        _ALL_DIAG_JOB.start()
    while True:
        st = _ALL_DIAG_JOB.status()
        if st.get("state") != "running":
            break
        if ctx.stopping:
            _ALL_DIAG_JOB.cancel()
        ctx.set_progress(detail=f"collect: all-diagnostics bundle · {st.get('detail') or ''}")
        time.sleep(_TICK_S)
    res = st.get("result") or {}
    out: dict[str, Any] = {"job_state": st.get("state"), "error": st.get("error"),
                           "path": res.get("path"), "bytes": res.get("bytes")}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        out["measured"] = False
        return out
    try:
        out.update(_read_bundle_archive(path))
        out["measured"] = True
    except Exception as exc:  # noqa: BLE001
        out["measured"] = False
        out["read_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


# --------------------------------------------------------------------------- #
#  The board rows -- what each clause got, in the vocabulary the gate uses
# --------------------------------------------------------------------------- #


def _phase(run: _Run, name: str) -> dict[str, Any]:
    for ph in run.phases:
        if ph.get("name") == name:
            return ph
    return {}


def _row(row: str, clause: str, status: str, evidence: dict[str, Any] | None, note: str = "") -> dict[str, Any]:
    return {"row": row, "clause": clause, "status": status, "evidence": evidence or {}, "note": note}


def board_rows(run: _Run) -> list[dict[str, Any]]:  # noqa: C901 - one branch per board row, by design
    """Verdict-free: each row carries what was MEASURED for its clause and what still
    belongs to the operator. Reading a row as closed is the maintainer's act."""
    p = run.params
    rows: list[dict[str, Any]] = []
    fresh = _phase(run, "fresh_install_restore")
    child = ((fresh.get("result") or {}).get("child") or {})
    p0 = _phase(run, "p0_validation").get("result") or {}
    soak = _phase(run, "soak")
    collect_ph = _phase(run, "collect")
    collect = collect_ph.get("result") or {}
    bundle_ph = _phase(run, "bundle")
    bundle = bundle_ph.get("result") or {}
    probes = _phase(run, "online_probes").get("result") or {}
    row5 = _phase(run, "row5_quarantine")
    million = p.profile == "million"

    def _block_status(block: Any, *, ran: bool) -> str:
        """RR-3: a row's status from the reading it holds. A reading that failed is an
        ERROR, named as one -- it used to read 'skipped', which says nobody tried."""
        if isinstance(block, dict) and block and block.get("measured") is not False and not block.get("error"):
            return "measured"
        if isinstance(block, dict) and (block.get("error") or block.get("measured") is False):
            return "error"
        if not ran:
            return "skipped"
        cs = collect_ph.get("status")
        return "error" if cs == "error" else (cs if cs in PHASE_STATUSES and cs != "measured" else "skipped")

    # A -- the committed import + the stamps surviving it
    if child and fresh.get("status") == "measured":
        integ = child.get("integrity") or {}
        rows.append(_row(
            "A", "one committed import reports the verdicts it stamped, and a previously-"
                 "disqualified source is still disqualified afterwards",
            "measured",
            {"restore": child.get("restore"), "counts": child.get("counts"),
             "integrity_verdict": integ.get("verdict"),
             "laundered_total": integ.get("laundered_total"), "demoted_total": integ.get("demoted_total"),
             "verified_disqualified_sample": integ.get("verified_disqualified_sample"),
             "checked": integ.get("checked"), "scale": "this instance's corpus, restored COMMITTED into a fresh install"},
            "the six-month re-check over the catalogue is the soak's drain; its outcome is the live-corpus integrity block on row E"
            + ("" if million else " -- row A's scale clause names ~1M articles; this instance's count is in the preflight"),
        ))
    else:
        rows.append(_row("A", "a committed import at scale", fresh.get("status") or "skipped",
                         {"phase": fresh}, "the fresh-install restore did not complete here"))

    # B -- the >= 72 h soak
    sw = collect.get("soak_window") or {}
    window = sw.get("window") or {}
    coll = collect.get("collector") or {}
    hb = run.heartbeats
    gaps = []
    for a, b in zip(hb, hb[1:], strict=False):
        with contextlib.suppress(Exception):
            gaps.append(round((float(b["elapsed_h"]) - float(a["elapsed_h"])) * 3600.0))
    restarted = any(
        (s.get("process_uptime_s") is not None and float(s["process_uptime_s"]) < float(s.get("elapsed_h") or 0) * 3600.0 - HEARTBEAT_INTERVAL_S)
        for s in hb
    )
    soak_status = soak.get("status") or "skipped"
    if soak_status != "measured":
        b_status = soak_status
    else:
        # The soak ran; the row's clause is only answered with the end-of-window reading
        # beside it. `measured` with `reaches_bar: null` was the NUC's report (RR-3).
        b_status = _block_status(collect.get("soak_window"), ran=bool(collect_ph))
    rows.append(_row(
        "B", "memory flat across >= 72 h of continuous collection; the process stayed up for the window it reports on",
        b_status,
        {"soak_hours_elapsed": run.soak.get("elapsed_hours"), "soak_hours_requested": p.soak_hours,
         "reaches_bar": window.get("reaches_bar"), "window_hours": window.get("hours"),
         "p0_3_collector": {"verdict": coll.get("verdict"), "reason": coll.get("reason")},
         "heartbeats": len(hb), "heartbeats_dropped": run.heartbeats_dropped,
         "max_gap_between_heartbeats_s": max(gaps) if gaps else None,
         "process_restart_seen_in_heartbeats": restarted,
         "memory_guard_last": (hb[-1].get("memory_guard") if hb else None),
         "stretches": len(run.soak_stretches),
         "longest_stretch_hours": max([float(s.get("elapsed_hours") or 0.0) for s in run.soak_stretches] or [0.0]),
         "resumed": run.resumed,
         "suspends_during_soak": list(run.suspends),
         "clock_adjustments": list(run.clock_adjustments),
         "elapsed_basis": "the monotonic clock, from the stretch's start (RR-4)",
         "end_of_window_reading": (collect.get("soak_window") or {}).get("error") or ("taken" if sw else "not taken")},
        "read P0.3 and the soak window together; a restart or a suspend ends the stretch and is visible here -- "
        "the bar is continuous, so only the longest stretch can reach it, never the sum"
        + ("; THE SOAK RAN but its end-of-window reading failed, so the clause has no answer from this run"
           if b_status == "error" and soak_status == "measured" else ""),
    ))

    # C -- the bundle on the ~1M instance
    if bundle.get("measured"):
        zero = bundle.get("zero_byte_members") or []
        declined = bundle.get("declined_members") or []
        by_machine = bundle.get("declined_by_machine") or []
        skipped = bundle.get("skipped_deadline_members") or []
        errored = bundle.get("error_members") or []
        partial = bundle.get("partial_members") or []
        light = bundle.get("complete_profile") is False
        # "Every member non-zero": a member skipped at its deadline or failed is ABSENT
        # (a marker stands in its place), so it fails the clause exactly as an empty
        # one would (RR-1b). A member cut short at its deadline is non-zero and is
        # counted as such, and named so the reader decides what "partial" is worth.
        ok = (bool(bundle.get("coverage_complete")) and not zero and not light
              and not skipped and not errored)
        notes = ["the bar names the ~1M instance"
                 + ("" if million else "; on the release-scale profile this bundle is evidence at this scale only")]
        if bundle.get("coverage_complete") is None:
            notes.append("the archive carries no coverage block, so the clause's first half cannot be read")
        if skipped:
            notes.append(f"{len(skipped)} member(s) hit their deadline and are ABSENT: " + ", ".join(skipped))
        if errored:
            notes.append(f"{len(errored)} member(s) FAILED and are absent: " + ", ".join(errored))
        if partial:
            notes.append(f"{len(partial)} member(s) stopped at their deadline and are PARTIAL (non-zero): " + ", ".join(partial))
        if light and by_machine and len(by_machine) == len(declined):
            notes.append("THIS FULL BUNDLE IS INCOMPLETE -- " + ", ".join(by_machine)
                         + " declined by the machine's memory (R27), so it cannot satisfy the clause's every member")
        elif light:
            notes.append("THIS BUNDLE IS LIGHT -- " + ", ".join(declined)
                         + " declined at the operator's request, so it cannot satisfy the clause's every member (R28)")
        rows.append(_row(
            "C", "one bundle whose coverage block reads complete: true, on a build carrying the statement_deadline fix, every member non-zero",
            "measured",
            {"path": bundle.get("path"), "bytes": bundle.get("bytes"), "members_total": bundle.get("members_total"),
             "coverage_complete": bundle.get("coverage_complete"), "coverage_from": bundle.get("runtime_coverage_from"),
             "zero_byte_members": zero, "members_by_outcome": bundle.get("members_by_outcome"),
             "skipped_deadline_members": skipped, "error_members": errored, "partial_members": partial,
             "bundle_profile": bundle.get("profile"), "complete_profile": bundle.get("complete_profile"),
             "declined_members": declined, "declined_by_machine": by_machine,
             "statement_deadline_fix_present": (_phase(run, "preflight").get("result") or {}).get("statement_deadline_fix_present"),
             "bar_satisfied_by_this_bundle": ok, "required_on_this_profile": million},
            "; ".join(notes),
        ))
    else:
        c_status = ("error" if (bundle_ph.get("status") == "error" or bundle.get("job_state") == "error"
                                or bundle.get("read_error")) else (bundle_ph.get("status") or "skipped"))
        if c_status == "measured":  # the phase ran and the archive was not there to read
            c_status = "error"
        rows.append(_row("C", "one bundle from the ~1M instance", c_status,
                         {**bundle, "phase_detail": bundle_ph.get("detail")},
                         "the bundle did not finish here" + (" -- REQUIRED on the million profile" if million else "")))

    # D / E -- the two bars, read from the run
    d_status = _block_status(collect.get("soak_window"), ran=bool(collect_ph)) if soak_status == "measured" \
        else ("skipped" if soak_status in ("skipped", "measured") else soak_status)
    rows.append(_row(
        "D", "one soak-window report from a run of >= 72 h, read alongside the P0.3 report",
        d_status,
        {"window": window, "unmeasured_blocks": sw.get("unmeasured"), "error": sw.get("error"),
         "blocks": sorted(k for k in sw if k not in ("window", "unmeasured", "error", "measured"))},
        "the same block the bundle carries as soak-window.json",
    ))
    live = collect.get("qualification_integrity_live") or {}
    live_ok = bool(live) and live.get("measured") is not False and not live.get("error")
    e_status = "measured" if (child.get("integrity") or live_ok) else _block_status(live, ran=bool(collect_ph))
    rows.append(_row(
        "E", "qualification-integrity read after the committed import; the clause is answered by inversions_total with the sources named",
        e_status,
        {"restored_corpus": (child.get("integrity") or {}).get("verdict"),
         "live_corpus_after_drain": {"verdict": live.get("verdict"), "laundered_total": live.get("laundered_total"),
                                     "demoted_total": live.get("demoted_total"), "checked": live.get("checked"),
                                     "error": live.get("error")}},
        "two readings on purpose: the restored install answers row A's clause, the live corpus answers the drain's",
    ))

    # G -- 0.3 row 5 (opt-in)
    if p.run_row5_quarantine:
        r5 = row5.get("result") or {}
        rf = r5.get("reindex_final") or {}
        rows.append(_row(
            "G", "0.3 row 5: the Tier-A quarantine pass (8 articles expected under nav-soup-v2 on the release-scale instance), the re-index, the composition",
            row5.get("status") or "skipped",
            {"mode_ok": r5.get("mode_ok"), "quarantine_final": r5.get("quarantine_final"),
             "reindex_final": rf.get("state"), "reindex_stalled": rf.get("stalled"),
             "reindex_skipped": r5.get("reindex_skipped"), "composition": r5.get("composition"),
             "wall_s": row5.get("wall_s"), "retries": r5.get("retries"),
             "collection_paused": r5.get("collection_paused"), "collection_resumed": r5.get("collection_resumed")},
            "run because the operator ticked it; ruling A1 had deferred it. It runs AFTER the soak, the collect and "
            "the bundle, with collection paused (FD01): a whole-corpus re-index takes hours to days. The v0.3.0 tag "
            "and the version flip are still not this run's",
        ))
    else:
        rows.append(_row("G", "0.3 row 5 (deferred by ruling A1)", "skipped", {}, "not ticked -- nothing was quarantined"))

    # I / J / K -- the backup side
    checks = p0.get("checks") or {}
    rows.append(_row(
        "J", "a dated OpenOmniscience_Backup folder, verified", "measured" if p0 else "skipped",
        {"backup_folder": p0.get("backup_folder"), "verify": checks.get("p0_1_verify")},
        "verified by the P0 kit's verify_stream_backup (signed manifest + every checksum), not by the export dialog's "
        "verify-after-write pass; BACKUP_SUMMARY.md is the dialog's and is not written here -- the reference-VM export through the dialog stays the operator's",
    ))
    rows.append(_row(
        "K", "the P0 trio re-run on the new format; a pre-migration backup restored with a 0-duplicate scan",
        "measured" if p0 else "skipped",
        {"backup_engine_format": p0.get("backup_engine_format"),
         "backup_schema": (_phase(run, "preflight").get("result") or {}).get("backup_schema"),
         "p0": checks, "p0_summary": p0.get("summary"),
         "duplicate_key_scan_on_restored_corpus": child.get("country_code_scan"),
         "legacy_backup": (_phase(run, "legacy_restore").get("result") or {}).get("child", {}).get("country_code_scan")
         if p.legacy_backup_path else "no pre-migration backup path was given"},
        "the P0 verdicts are the kit's own; the scan on the restored corpus is the row's artifact",
    ))
    rows.append(_row(
        "I", "a real restore at corpus scale through the volume set",
        "measured" if child and fresh.get("status") == "measured" else "skipped",
        {"restore": child.get("restore"), "elapsed_s": (fresh.get("result") or {}).get("elapsed_s"),
         "peak_rss_mb_child": child.get("peak_rss_mb"), "reindex_imported": False},
        "one backup, so K = 3 checkpointing was not exercised; the kill between stages 3 and 4 is a CI fixture and stays the operator's on this machine",
    ))

    # P -- the lane's run
    lc = collect.get("wiki_lane_counters") or {}
    p_status = "measured" if lc.get("measured") else (
        "error" if (lc.get("error") or collect_ph.get("status") == "error" and not lc) else "not-measurable-here")
    rows.append(_row(
        "P", "the lane ran >= 72 h inside its budget with its counters read from one artifact (rows/day, bytes/day, gap history)",
        p_status,
        {"counters": lc, "service": collect.get("wiki_lane_service"), "ores_probe": collect.get("ores_probe"),
         "soak_hours_elapsed": run.soak.get("elapsed_hours")},
        "the counters are computed from the lane's rows, so a restart does not lose them; Q717's verification is the ores_probe block"
        if lc.get("measured") else (lc.get("detail") or "the lane has no rows; was the top-bar toggle on?"),
    ))

    # Q -- the live checks
    law = probes.get("law") or {}
    rows.append(_row(
        "Q", "the live checks against the three priority hosts (Q924's verified tier)",
        "measured" if any((v or {}).get("measured") for v in law.values()) else ("skipped" if not p.online_probes else "not-measurable-here"),
        law, "the 44-row vetting board and the adapter ORDER (Q925 ⛔) stay the maintainer's",
    ))

    # T -- the digest values
    rows.append(_row(
        "T", "the weights digest VALUES (an operator input by design)",
        "measured" if any((probes.get("weights") or {}).get(k, {}).get("measured") for k in ("hf", "ollama")) else "skipped",
        probes.get("weights") or {}, "a PROPOSAL fetched from the publishers; pasting it is the pin",
    ))
    return rows


def _summary(rows: list[dict[str, Any]], run: _Run) -> dict[str, Any]:
    tally: dict[str, int] = {}
    for r in rows:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    p0 = (_phase(run, "p0_validation").get("result") or {}).get("summary") or {}
    return {
        "rows_by_status": tally,
        "any_phase_error": any(ph.get("status") == "error" for ph in run.phases),
        "p0_any_fail": bool(p0.get("fail")),
        "outcome": run.outcome,
        "note": (
            "A tally of statuses, never a score. 'measured' means the clause has a number a "
            "reader can re-open, not that the row is closed -- closing is the maintainer's reading."
        ),
    }


# --------------------------------------------------------------------------- #
#  Report file
# --------------------------------------------------------------------------- #


def _write_report(run: _Run, *, interim: bool) -> Path:
    rows = board_rows(run)
    report = {
        "schema": RELEASE_RUN_SCHEMA,
        "run_id": run.run_id,
        "profile": run.params.profile,
        "interim": interim,
        "created_at": _now_iso(),
        "started_at": run.started_at,
        "outcome": run.outcome,
        "warnings": list(run.warnings),
        "preflight": _phase(run, "preflight").get("result"),
        "phases": [{k: v for k, v in ph.items() if k != "result"} for ph in run.phases],
        "phase_results": {ph["name"]: ph.get("result") for ph in run.phases if "result" in ph},
        "soak": {k: v for k, v in run.soak.items() if k != "started_mono"},
        "soak_stretches": [{k: v for k, v in st.items() if k != "started_mono"} for st in run.soak_stretches],
        "sessions": list(run.sessions),
        "resumed": run.resumed,
        "clock_adjustments": list(run.clock_adjustments),
        "suspends": list(run.suspends),
        "heartbeats": list(run.heartbeats),
        "heartbeats_dropped": run.heartbeats_dropped,
        "artifacts": dict(run.artifacts),
        "board_rows": rows,
        "summary": _summary(rows, run),
        "method": (
            "Composes the P0 kit, a subprocess fresh-install restore, the ruled online seam, "
            "the unattended-run kit, the soak window, the qualification-integrity check, the "
            "lane counters and the all-diagnostics job. Measurements only; each board row "
            "carries its own status and evidence; nothing here decides whether a row closes. "
            "Every duration (a phase's wall_s, the soak's elapsed hours) is on the monotonic "
            "clock; the wall stamps beside them are where the clock read, and "
            "clock_adjustments says where the two disagreed."
        ),
    }
    out_dir = _run_dir()
    kind = "interim" if interim else "final"
    fname = f"oo-release-run-{run.params.profile}-{run.run_id}-{kind}.json"
    final = out_dir / fname
    part = out_dir / (fname + ".part")
    part.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(part, final)
    if not interim:
        # The final report supersedes every interim of the SAME run.
        for old in out_dir.glob(f"oo-release-run-{run.params.profile}-{run.run_id}-interim.json"):
            with contextlib.suppress(OSError):
                old.unlink()
    run.report_path = str(final)
    run.persist()
    return final


def _live_run(state: dict[str, Any]) -> dict[str, Any] | None:
    """The run in the state file, as a reader of the bundle needs it: where it is, since
    when, what it has measured so far. Never the passphrase (the state has none)."""
    if not state or not state.get("run_id"):
        return None
    beats = [h for h in (state.get("heartbeats") or []) if isinstance(h, dict)]
    interrupted = state.get("outcome") is None and state.get("pid") != os.getpid()
    return {
        "run_id": state.get("run_id"),
        "profile": state.get("profile"),
        "started_at": state.get("started_at"),
        "outcome": state.get("outcome"),
        "status": ("finished" if state.get("outcome") is not None
                   else ("interrupted (the process that ran it is gone)" if interrupted else "in progress")),
        "phase": state.get("phase"),
        "phase_started_at": state.get("phase_started_at"),
        "updated_at": state.get("updated_at"),
        "phases": [{k: ph.get(k) for k in ("name", "status", "started_at", "ended_at", "wall_s", "detail")}
                   for ph in (state.get("phases") or []) if isinstance(ph, dict)],
        "soak": {k: v for k, v in (state.get("soak") or {}).items() if k != "started_mono"},
        "soak_stretches": len(state.get("soak_stretches") or []),
        "heartbeats": len(beats),
        "last_heartbeat": beats[-1] if beats else None,
        "resumed": state.get("resumed"),
        "clock_adjustments": state.get("clock_adjustments") or [],
        "warnings": state.get("warnings") or [],
        "report_path": state.get("report_path"),
    }


def last_release_run_report() -> dict:
    """The newest saved report (final over interim) for the bundle member and the
    ``/release-run/last`` route -- read-only, never runs anything -- WITH the live run
    beside it whenever the saved report does not already describe it (RR-8). Three Qubes
    bundles said "no 0.4 release run has been made yet" 61 hours into a run, because
    only a finished soak ever saved a report."""
    live = _live_run(read_state())
    try:
        files = sorted(_run_dir().glob("oo-release-run-*.json"))
        if not files:
            out: dict[str, Any] = {"schema": RELEASE_RUN_SCHEMA, "available": False}
            if live:
                out["live_run"] = live
                out["note"] = (f"run {live['run_id']} is {live['status']}, at phase {live.get('phase')}, and "
                               "has not saved a report yet; live_run is its state file")
            else:
                out["note"] = "no 0.4 release run has been made yet -- Settings -> Advanced -> Diagnostics"
            return out
        newest = max(files, key=lambda p: p.stat().st_mtime)
        report = json.loads(newest.read_text(encoding="utf-8"))
        report["available"] = True
        report["source_file"] = newest.name
        if live and (str(live.get("run_id")) != str(report.get("run_id")) or report.get("interim")):
            report["live_run"] = live
        return report
    except Exception as exc:  # noqa: BLE001
        out = {"schema": RELEASE_RUN_SCHEMA, "available": False, "error": str(exc)[:300]}
        if live:
            out["live_run"] = live
        return out


def render_release_run_text(report: dict) -> str:
    """A readable rendering: the rows first, the phases after, the warnings last."""
    lines = [
        f"0.4 release run -- profile {report.get('profile')} -- run {report.get('run_id')}",
        f"created {report.get('created_at')} · started {report.get('started_at')} · "
        f"outcome {report.get('outcome')} · {'INTERIM' if report.get('interim') else 'final'}",
        "",
        "BOARD ROWS (status per clause; closing a row is the maintainer's reading)",
    ]
    for r in report.get("board_rows") or []:
        lines.append(f"  [{str(r.get('status', '')).upper()}] row {r.get('row')} -- {r.get('clause')}")
        if r.get("note"):
            lines.append(f"      note: {r['note']}")
        ev = r.get("evidence") or {}
        for k, v in list(ev.items())[:8]:
            s = json.dumps(v, default=str, ensure_ascii=False)
            lines.append(f"      {k}: {s[:240]}{'…' if len(s) > 240 else ''}")
    lines += ["", "PHASES"]
    for ph in report.get("phases") or []:
        took = f" · took {ph.get('wall_s')} s" if ph.get("wall_s") is not None else ""
        lines.append(f"  {ph.get('name')}: {ph.get('status')} · {ph.get('started_at')} -> {ph.get('ended_at')}{took} · {ph.get('detail', '')}")
    if report.get("clock_adjustments"):
        lines += ["", "CLOCK ADJUSTMENTS (durations above are monotonic; the stamps are where the clock read)"]
        lines += [f"  - {json.dumps(c, default=str, ensure_ascii=False)[:240]}" for c in report["clock_adjustments"]]
    if report.get("suspends"):
        lines += ["", "SUSPENDS DURING THE SOAK (each ended a stretch)"]
        lines += [f"  - {c.get('at')}: {c.get('seconds')} s ({c.get('clocks')})" for c in report["suspends"]]
    soak = report.get("soak") or {}
    if soak:
        lines += ["", f"SOAK: {soak.get('elapsed_hours')} of {soak.get('hours_requested')} h · ended by {soak.get('ended_by')} · "
                      f"{len(report.get('heartbeats') or [])} heartbeats ({report.get('heartbeats_dropped', 0)} dropped)"]
    if report.get("warnings"):
        lines += ["", "WARNINGS"] + [f"  - {w}" for w in report["warnings"]]
    summary = report.get("summary") or {}
    lines += ["", f"SUMMARY: {json.dumps(summary.get('rows_by_status') or {})} · "
                  f"p0 any fail: {summary.get('p0_any_fail')} · "
                  f"any phase error: {summary.get('any_phase_error')}", f"  {summary.get('note', '')}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  The worker
# --------------------------------------------------------------------------- #

#: "Collect now": set by the route; the soak loop ends its window early and the
#: end-of-window readings are taken. Cleared on every start.
_COLLECT_NOW = threading.Event()


def request_collect_now() -> None:
    _COLLECT_NOW.set()


def _run_phase(run: _Run, ctx: Any, name: str, fn: Any, *, refusals: tuple[type[BaseException], ...] = ()) -> dict[str, Any]:
    """Run one phase under the closed status vocabulary. A named refusal (a bad
    precondition) is ``refused``; anything else that raises is ``error`` -- and neither
    stops the run from writing its report, because a run that dies without one leaves
    the operator with nothing after three days."""
    run.begin(name)
    ctx.set_progress(detail=name)
    try:
        result = fn()
    except _PhaseError as exc:
        # RR-2: what the phase measured before it failed stays in its record.
        _LOG.warning("release run phase %s failed part of the way: %s", name, exc)
        ph = run.end(exc.status if exc.status in PHASE_STATUSES else "error", str(exc)[:400], result=exc.partial)
    except refusals as exc:
        ph = run.end("refused", f"{type(exc).__name__}: {exc}"[:400])
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal to the report
        _LOG.warning("release run phase %s failed", name, exc_info=True)
        ph = run.end("error", f"{type(exc).__name__}: {exc}"[:400])
    else:
        if ctx.stopping:
            ph = run.end("cancelled", "cancelled during this phase", result=result)
        else:
            ph = run.end("measured", "ok", result=result)
    _interim(run)
    return ph


def _interim(run: _Run) -> None:
    """An interim report after every phase (RR-8): a run is readable from its first
    finished phase, not only from inside a completed soak."""
    with contextlib.suppress(Exception):
        _write_report(run, interim=True)


class _Clocks:
    """The soak's two questions between ticks, the session ledger's way (RR-4): was the
    machine SUSPENDED (the boot-time clock ran ahead of the monotonic one), and was the
    wall clock CHANGED (it moved against the boot-time clock). Without a boot-time clock
    a forward jump reads as a suspend -- the conservative reading, since the bar may
    never be claimed across a gap nobody can vouch for -- and a backward one as a change."""

    def __init__(self) -> None:
        from src.monitoring.session_history import boottime

        self._bt = boottime
        self.mono, self.bt, self.wall = time.monotonic(), boottime(), time.time()

    def advance(self) -> tuple[float, float, str]:
        m, b, w = time.monotonic(), self._bt(), time.time()
        dm = m - self.mono
        if b is not None and self.bt is not None:
            db = b - self.bt
            out = (db - dm, (w - self.wall) - db, "boot-time")
        else:
            gap = (w - self.wall) - dm
            out = (gap, 0.0, "monotonic-only") if gap > 0 else (0.0, gap, "monotonic-only")
        self.mono, self.bt, self.wall = m, b, w
        return out


def _open_stretch(run: _Run, hours: float) -> float:
    started = time.monotonic()
    run.soak = {"started_at": _now_iso(), "started_epoch": time.time(), "started_mono": started,
                "hours_requested": hours, "elapsed_hours": 0.0, "ended_by": None,
                "stretch": len(run.soak_stretches) + 1, "pid": os.getpid()}
    run.heartbeat(_heartbeat_sample(run))
    return started


def _close_stretch(run: _Run, started: float, ended_by: str) -> None:
    run.soak["elapsed_hours"] = round((time.monotonic() - started) / 3600.0, 2)
    run.soak["ended_by"] = ended_by
    run.soak["ended_at"] = _now_iso()
    run.soak_stretches.append({k: v for k, v in run.soak.items() if k != "started_mono"})


def _soak(ctx: Any, run: _Run) -> None:
    """The window, on the MONOTONIC clock: elapsed time, the deadline, the heartbeat and
    interim cadences (RR-4). A wall-clock change is recorded and changes nothing. A
    SUSPEND ends the stretch -- the bar is continuous collection (R20), and a machine
    that slept was not collecting -- and a new stretch starts with the full window, the
    same rule a restart has always followed."""
    params = run.params
    run.begin("soak")
    clocks = _Clocks()
    started = _open_stretch(run, params.soak_hours)
    next_beat = started + HEARTBEAT_INTERVAL_S
    next_interim = started + INTERIM_REPORT_INTERVAL_S
    deadline = started + params.soak_hours * 3600.0
    ended_by = "window-complete"
    while True:
        now = time.monotonic()
        suspended, stepped, basis = clocks.advance()
        if abs(stepped) > CLOCK_EVENT_MIN_S:
            run.clock_adjustments.append({
                "at": _now_iso(), "phase": "soak", "clock_moved_s": round(stepped), "clocks": basis,
                "basis": "the wall clock was changed during the soak; the window runs on the monotonic clock and did not move"})
            run.persist()
        if suspended > CLOCK_EVENT_MIN_S:
            run.suspends.append({"at": _now_iso(), "seconds": round(suspended), "clocks": basis,
                                 "stretch": run.soak.get("stretch"),
                                 "basis": ("the machine was suspended: the boot-time clock ran ahead of the monotonic clock"
                                           if basis == "boot-time" else
                                           "the wall clock ran ahead of the monotonic clock -- a suspend, or a forward "
                                           "clock change this platform cannot tell from one")})
            _close_stretch(run, started, "suspend")
            run.warnings.append(
                f"the machine was suspended for {round(suspended)} s during stretch {run.soak.get('stretch')}; "
                "the bar is continuous, so a new stretch started with the full window")
            started = _open_stretch(run, params.soak_hours)
            next_beat = started + HEARTBEAT_INTERVAL_S
            deadline = started + params.soak_hours * 3600.0
            now = started
        run.soak["elapsed_hours"] = round((now - started) / 3600.0, 2)
        if ctx.stopping:
            ended_by = "cancelled"
            break
        if _COLLECT_NOW.is_set():
            ended_by = "collect-now"
            break
        if now >= deadline:
            break
        if now >= next_beat:
            run.heartbeat(_heartbeat_sample(run))
            next_beat += HEARTBEAT_INTERVAL_S
        if now >= next_interim:
            with contextlib.suppress(Exception):
                _write_report(run, interim=True)
            _ledger_event("release-run", action="interim-report", run_id=run.run_id)
            next_interim += INTERIM_REPORT_INTERVAL_S
        ctx.set_progress(
            detail=f"soak: {run.soak['elapsed_hours']} / {params.soak_hours} h · rss {_rss_mb()} MB"
        )
        time.sleep(_TICK_S)
    _close_stretch(run, started, ended_by)
    run.heartbeat(_heartbeat_sample(run))
    run.end("measured" if ended_by != "cancelled" else "cancelled",
            f"{run.soak['elapsed_hours']} h of {params.soak_hours} h, ended by {ended_by}"
            + (f" (stretch {run.soak.get('stretch')} of this run)" if len(run.soak_stretches) > 1 else ""),
            ended_by=ended_by)
    _interim(run)


def run_release_run(ctx: Any, **kwargs: Any) -> dict:  # noqa: C901 - the sequence IS the module
    """BackgroundJob worker. Returns ``{path, filename, report}``; the passphrase never
    lands in the returned dict."""
    resume = bool(kwargs.pop("resume", False))
    _COLLECT_NOW.clear()
    if resume:
        plan = resume_preflight(str(kwargs.get("passphrase") or ""))  # ValueError -> the job records it
        run = _Run.from_state(read_state(), str(kwargs.get("passphrase") or ""))
        _ledger_event("release-run", action="resume", run_id=run.run_id, profile=run.params.profile,
                      interrupted_phase=plan.get("interrupted_phase"))
    else:
        params = RunParams(**kwargs)
        params.validate()
        run = _Run(params)
        _ledger_event("release-run", action="start", run_id=run.run_id, profile=params.profile)
    params = run.params
    run.persist()
    total_phases = 8
    done = 0

    def _kept(name: str) -> bool:
        """True when a resume already holds a terminal record for this phase."""
        return _phase(run, name).get("status") in _TERMINAL_OK

    def step(detail: str) -> None:
        nonlocal done
        done += 1
        ctx.set_progress(done=done, total=total_phases, detail=detail)

    # 0 -- preflight (a refusal here ends the run before anything is written). On a
    # resume the measured preflight stands: the backup it sized is already on the drive.
    pre = _phase(run, "preflight") if _kept("preflight") else \
        _run_phase(run, ctx, "preflight", lambda: _preflight(run), refusals=(ValueError,))
    step("preflight")
    if pre.get("status") != "measured":
        run.outcome = "refused"
        path = _write_report(run, interim=False)
        return {"path": str(path), "filename": path.name, "report": json.loads(path.read_text(encoding="utf-8"))}

    # 1 -- the P0 trio into the dated folder (kept on a resume: the folder exists)
    if not ctx.stopping and not _kept("p0_validation"):
        from src.backup.export_folder import ExportFolderError

        _run_phase(run, ctx, "p0_validation", lambda: _p0_into_dated_folder(ctx, run),
                   refusals=(ExportFolderError, ValueError))
    step("P0 trio")

    # 2 -- the committed restore into a fresh install (needs the backup to have passed)
    p0res = _phase(run, "p0_validation").get("result") or {}
    backup_ok = ((p0res.get("checks") or {}).get("p0_1_verify") or {}).get("verdict") == "pass"
    fits = (_phase(run, "preflight").get("result") or {}).get("fresh_install_fits")
    if ctx.stopping or _kept("fresh_install_restore"):
        pass
    elif not backup_ok:
        run.begin("fresh_install_restore")
        run.end("not-measurable-here", "the backup did not verify, so there is nothing safe to restore")
    elif fits is False:
        run.begin("fresh_install_restore")
        run.end("not-measurable-here", "the destination lacks the room a second corpus copy needs; free about three corpus sizes and re-run")
    else:
        folder = Path(run.artifacts["backup_folder"])
        _run_phase(run, ctx, "fresh_install_restore",
                   lambda: _fresh_install_restore(ctx, run, folder, label="own-backup"))
    if params.legacy_backup_path and not ctx.stopping and not _kept("legacy_restore"):
        legacy = Path(params.legacy_backup_path).expanduser()
        if legacy.exists():
            _run_phase(run, ctx, "legacy_restore",
                       lambda: _fresh_install_restore(ctx, run, legacy, label="pre-migration"))
        else:
            run.begin("legacy_restore")
            run.end("refused", f"no such path: {legacy}")
    step("fresh install")

    # 3 -- arm the soak, then the online probes while the collector warms up. A resume
    # that kept a completed soak keeps its arming too: nothing is left to arm.
    if not ctx.stopping:
        if not _kept("arm_soak"):
            _run_phase(run, ctx, "arm_soak", lambda: _arm_soak(run))
        if _kept("online_probes"):
            pass
        elif params.online_probes:
            def _probes() -> dict[str, Any]:
                out: dict[str, Any] = {}
                try:
                    out["law"] = _law_live_checks()
                except Exception as exc:  # noqa: BLE001
                    out["law"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                try:
                    out["weights"] = _weights_digest_proposal()
                except Exception as exc:  # noqa: BLE001
                    out["weights"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                return out
            _run_phase(run, ctx, "online_probes", _probes)
        else:
            run.begin("online_probes")
            run.end("skipped", "online probes were not requested")
    step("armed")

    # 4 -- the soak itself, on the monotonic clock (RR-4)
    if _kept("soak"):
        pass
    elif not ctx.stopping and _phase(run, "arm_soak").get("status") == "measured":
        _soak(ctx, run)
    else:
        run.begin("soak")
        run.end("skipped", "the soak was not armed")
    step("soak")

    # 5 -- collect (also after a cancel: whatever the window gave is worth reading)
    if not _kept("collect"):
        _run_phase(run, ctx, "collect", lambda: _collect(ctx, run))
    step("collect")
    if not _kept("bundle"):
        _run_phase(run, ctx, "bundle", lambda: _bundle(ctx))
    step("bundle")

    # 6 -- 0.3 row 5 (opt-in only), LAST (FD01): the soak's evidence is written first, and
    # a whole-corpus re-index that takes days runs on its own time, collection paused.
    if _kept("row5_quarantine"):
        pass
    elif params.run_row5_quarantine and not ctx.stopping:
        _interim(run)
        _ledger_event("release-run", action="row5-start", run_id=run.run_id)
        _run_phase(run, ctx, "row5_quarantine", lambda: _row5_quarantine(ctx, run), refusals=(RuntimeError,))
    elif params.run_row5_quarantine:
        run.begin("row5_quarantine")
        run.end("skipped", "the run was cancelled before row 5 started")
    else:
        run.begin("row5_quarantine")
        run.end("skipped", "not requested (deferred by ruling A1; the operator did not tick it)")
    step("row 5")

    run.outcome = "cancelled" if ctx.stopping else "done"
    path = _write_report(run, interim=False)
    _ledger_event("release-run", action="finished", run_id=run.run_id, outcome=run.outcome)
    report = json.loads(path.read_text(encoding="utf-8"))
    return {"path": str(path), "filename": path.name, "report": report}
