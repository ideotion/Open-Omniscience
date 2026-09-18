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
            "phases": list(self.phases),
            "soak": dict(self.soak),
            "soak_stretches": list(self.soak_stretches),
            "sessions": list(self.sessions),
            "resumed": self.resumed,
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
        self.persist()

    def end(self, status: str, detail: str, **extra: Any) -> dict[str, Any]:
        assert status in PHASE_STATUSES, status
        cur = self._current or {"name": "?", "started_at": _now_iso()}
        cur.update({"ended_at": _now_iso(), "status": status, "detail": detail, **extra})
        self.phases.append(cur)
        self._current = None
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
        kept, dropped = [], []
        for ph in state.get("phases") or []:
            if not isinstance(ph, dict):
                continue
            if ph.get("status") in _TERMINAL_OK and ph.get("name") not in _REDONE_ON_RESUME:
                kept.append(dict(ph))
            else:
                dropped.append(f"{ph.get('name')}:{ph.get('status')}")
        run.phases = kept
        run.heartbeats = [dict(h) for h in (state.get("heartbeats") or []) if isinstance(h, dict)]
        run.heartbeats_dropped = int(state.get("heartbeats_dropped") or 0)
        run.artifacts = dict(state.get("artifacts") or {})
        run.warnings = list(state.get("warnings") or [])
        run.soak_stretches = [dict(s) for s in (state.get("soak_stretches") or []) if isinstance(s, dict)]
        run.sessions = [dict(s) for s in (state.get("sessions") or []) if isinstance(s, dict)] or run.sessions
        run.resumed = int(state.get("resumed") or 0) + 1
        prev_soak = dict(state.get("soak") or {})
        if prev_soak.get("started_at") and not prev_soak.get("ended_at"):
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
        run.soak = {}
        run.sessions.append({
            "pid": os.getpid(), "started_at": _now_iso(), "kind": "resume",
            "interrupted_phase": state.get("phase"), "previous_pid": state.get("pid"),
            "previous_updated_at": state.get("updated_at"), "phases_rerun": dropped,
        })
        run.warnings.append(
            f"resumed after a restart (resume #{run.resumed}): the measured phases were kept, "
            "the soak stretch started over because the bar is continuous"
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


def _wait_manager(ctx: Any, status_fn: Any, *, running_states: tuple[str, ...]) -> dict:
    """Poll a resumable manager until it leaves its running states, or a cancel lands.
    A PAUSED run is a person's decision and is not waited out."""
    last: dict = {}
    while True:
        last = status_fn() or {}
        state = str(last.get("state") or "")
        if state == "paused":
            return last
        if state not in running_states and not last.get("running"):
            return last
        if ctx.stopping:
            return last
        time.sleep(_TICK_S)


def _row5_quarantine(ctx: Any, run: _Run) -> dict[str, Any]:
    """The four commands of ``RELEASE_0.3_GATE.md`` §7.1, in order, with the two
    mode checks that section warns about read back from the run itself."""
    from src.analytics.quarantine_job import get_quarantine_manager
    from src.analytics.reindex_job import get_reindex_manager

    out: dict[str, Any] = {}
    qm = get_quarantine_manager()
    started = qm.start(write=True, include_prose_gate=False)  # RuntimeError -> refused
    out["quarantine_started"] = started
    st = _wait_manager(ctx, qm.status, running_states=("running",))
    out["quarantine_final"] = st
    # §7.1 step 2: a run under the wrong criteria reports a tally that looks legitimate.
    out["mode_ok"] = (st.get("dry_run") is False) and (st.get("include_prose_gate") is False)
    if ctx.stopping or st.get("state") == "paused":
        return out
    ctx.set_progress(detail="row 5: re-index (keywords, prune after)")
    rm = get_reindex_manager()
    out["reindex_started"] = rm.start(scope="keywords", prune_after=True, restart=False)
    out["reindex_final"] = _wait_manager(ctx, rm.status, running_states=("running",))
    if ctx.stopping:
        return out
    from src.analytics.figures import quarantine_composition
    from src.database.session import session_scope

    with session_scope() as db:
        out["composition"] = quarantine_composition(db, limit=40)
    return out


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
    sample: dict[str, Any] = {
        "at": _now_iso(),
        "elapsed_h": round((time.time() - run.soak["started_epoch"]) / 3600.0, 2),
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
    from src.catalog.qualification_integrity import qualification_integrity_report
    from src.database.session import session_scope
    from src.monitoring import expedition
    from src.monitoring.forensics import session_forensics
    from src.monitoring.p0_validation import _check_collector
    from src.monitoring.soak_window import soak_window

    out: dict[str, Any] = {}
    ctx.set_progress(detail="collect: soak window")
    with session_scope() as db:
        out["soak_window"] = soak_window(db, bar_hours=SOAK_BAR_HOURS)
        ctx.set_progress(detail="collect: qualification integrity (live corpus)")
        out["qualification_integrity_live"] = qualification_integrity_report(db)
    out["collector"] = _check_collector()
    ctx.set_progress(detail="collect: lane counters")
    try:
        from src.api.wiki_lane import lane_counters_route

        hours = float(run.soak.get("elapsed_hours") or 0.0)
        out["wiki_lane_counters"] = lane_counters_route(window_days=max(1, min(90, math.ceil(hours / 24.0) + 1)))
    except Exception as exc:  # noqa: BLE001
        out["wiki_lane_counters"] = {"measured": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
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
    return out


def _bundle(ctx: Any) -> dict[str, Any]:
    """Row C: the all-diagnostics job, awaited, and its archive READ -- the coverage
    block and every zero-byte member, which are the two things the bar names."""
    import zipfile

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
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            out["members_total"] = len(infos)
            out["zero_byte_members"] = sorted(i.filename for i in infos if i.file_size == 0)
            coverage = None
            with contextlib.suppress(KeyError, ValueError):
                dbg = json.loads(z.read("debug-bundle.json").decode("utf-8"))
                coverage = dbg.get("runtime_coverage")
            out["runtime_coverage"] = coverage
            out["coverage_complete"] = bool((coverage or {}).get("complete")) if coverage else None
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
    collect = _phase(run, "collect").get("result") or {}
    bundle = _phase(run, "bundle").get("result") or {}
    probes = _phase(run, "online_probes").get("result") or {}
    row5 = _phase(run, "row5_quarantine")
    million = p.profile == "million"

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
    rows.append(_row(
        "B", "memory flat across >= 72 h of continuous collection; the process stayed up for the window it reports on",
        "measured" if soak.get("status") == "measured" else (soak.get("status") or "skipped"),
        {"soak_hours_elapsed": run.soak.get("elapsed_hours"), "soak_hours_requested": p.soak_hours,
         "reaches_bar": window.get("reaches_bar"), "window_hours": window.get("hours"),
         "p0_3_collector": {"verdict": coll.get("verdict"), "reason": coll.get("reason")},
         "heartbeats": len(hb), "heartbeats_dropped": run.heartbeats_dropped,
         "max_gap_between_heartbeats_s": max(gaps) if gaps else None,
         "process_restart_seen_in_heartbeats": restarted,
         "memory_guard_last": (hb[-1].get("memory_guard") if hb else None),
         "stretches": len(run.soak_stretches),
         "longest_stretch_hours": max([float(s.get("elapsed_hours") or 0.0) for s in run.soak_stretches] or [0.0]),
         "resumed": run.resumed},
        "read P0.3 and the soak window together; a restart ends the stretch and is visible here -- "
        "the bar is continuous, so only the longest stretch can reach it, never the sum",
    ))

    # C -- the bundle on the ~1M instance
    if bundle.get("measured"):
        zero = bundle.get("zero_byte_members") or []
        ok = bool(bundle.get("coverage_complete")) and not zero
        rows.append(_row(
            "C", "one bundle whose coverage block reads complete: true, on a build carrying the statement_deadline fix, every member non-zero",
            "measured",
            {"path": bundle.get("path"), "bytes": bundle.get("bytes"), "members_total": bundle.get("members_total"),
             "coverage_complete": bundle.get("coverage_complete"), "zero_byte_members": zero,
             "statement_deadline_fix_present": (_phase(run, "preflight").get("result") or {}).get("statement_deadline_fix_present"),
             "bar_satisfied_by_this_bundle": ok, "required_on_this_profile": million},
            "the bar names the ~1M instance" + ("" if million else "; on the release-scale profile this bundle is evidence at this scale only"),
        ))
    else:
        rows.append(_row("C", "one bundle from the ~1M instance", bundle.get("job_state") and "error" or "skipped",
                         bundle, "the bundle did not finish here" + (" -- REQUIRED on the million profile" if million else "")))

    # D / E -- the two bars, read from the run
    rows.append(_row(
        "D", "one soak-window report from a run of >= 72 h, read alongside the P0.3 report",
        "measured" if sw else "skipped",
        {"window": window, "unmeasured_blocks": sw.get("unmeasured"), "blocks": sorted(k for k in sw if k not in ("window", "unmeasured"))},
        "the same block the bundle carries as soak-window.json",
    ))
    live = collect.get("qualification_integrity_live") or {}
    rows.append(_row(
        "E", "qualification-integrity read after the committed import; the clause is answered by inversions_total with the sources named",
        "measured" if (child.get("integrity") or live) else "skipped",
        {"restored_corpus": (child.get("integrity") or {}).get("verdict"),
         "live_corpus_after_drain": {"verdict": live.get("verdict"), "laundered_total": live.get("laundered_total"),
                                     "demoted_total": live.get("demoted_total"), "checked": live.get("checked")}},
        "two readings on purpose: the restored install answers row A's clause, the live corpus answers the drain's",
    ))

    # G -- 0.3 row 5 (opt-in)
    if p.run_row5_quarantine:
        r5 = row5.get("result") or {}
        rows.append(_row(
            "G", "0.3 row 5: the Tier-A quarantine pass (8 articles expected under nav-soup-v2 on the release-scale instance), the re-index, the composition",
            row5.get("status") or "skipped",
            {"mode_ok": r5.get("mode_ok"), "quarantine_final": r5.get("quarantine_final"),
             "reindex_final": (r5.get("reindex_final") or {}).get("state"), "composition": r5.get("composition")},
            "run because the operator ticked it; ruling A1 had deferred it. The v0.3.0 tag and the version flip are still not this run's",
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
    rows.append(_row(
        "P", "the lane ran >= 72 h inside its budget with its counters read from one artifact (rows/day, bytes/day, gap history)",
        "measured" if lc.get("measured") else "not-measurable-here",
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
        "soak": dict(run.soak),
        "soak_stretches": list(run.soak_stretches),
        "sessions": list(run.sessions),
        "resumed": run.resumed,
        "heartbeats": list(run.heartbeats),
        "heartbeats_dropped": run.heartbeats_dropped,
        "artifacts": dict(run.artifacts),
        "board_rows": rows,
        "summary": _summary(rows, run),
        "method": (
            "Composes the P0 kit, a subprocess fresh-install restore, the ruled online seam, "
            "the unattended-run kit, the soak window, the qualification-integrity check, the "
            "lane counters and the all-diagnostics job. Measurements only; each board row "
            "carries its own status and evidence; nothing here decides whether a row closes."
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


def last_release_run_report() -> dict:
    """The newest saved report (final over interim), for the bundle member and the
    ``/release-run/last`` route -- read-only, never runs anything."""
    try:
        files = sorted(_run_dir().glob("oo-release-run-*.json"))
        if not files:
            return {"schema": RELEASE_RUN_SCHEMA, "available": False,
                    "note": "no 0.4 release run has been made yet -- Settings -> Advanced -> Diagnostics"}
        newest = max(files, key=lambda p: p.stat().st_mtime)
        report = json.loads(newest.read_text(encoding="utf-8"))
        report["available"] = True
        report["source_file"] = newest.name
        return report
    except Exception as exc:  # noqa: BLE001
        return {"schema": RELEASE_RUN_SCHEMA, "available": False, "error": str(exc)[:300]}


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
        lines.append(f"  {ph.get('name')}: {ph.get('status')} · {ph.get('started_at')} -> {ph.get('ended_at')} · {ph.get('detail', '')}")
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
    except refusals as exc:
        return run.end("refused", f"{type(exc).__name__}: {exc}"[:400])
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal to the report
        _LOG.warning("release run phase %s failed", name, exc_info=True)
        return run.end("error", f"{type(exc).__name__}: {exc}"[:400])
    if ctx.stopping:
        return run.end("cancelled", "cancelled during this phase", result=result)
    return run.end("measured", "ok", result=result)


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

    # 1 -- 0.3 row 5 (opt-in only)
    if _kept("row5_quarantine"):
        pass
    elif params.run_row5_quarantine and not ctx.stopping:
        _run_phase(run, ctx, "row5_quarantine", lambda: _row5_quarantine(ctx, run), refusals=(RuntimeError,))
    else:
        run.begin("row5_quarantine")
        run.end("skipped", "not requested (deferred by ruling A1; the operator did not tick it)")
    step("row 5")

    # 2 -- the P0 trio into the dated folder (kept on a resume: the folder exists)
    if not ctx.stopping and not _kept("p0_validation"):
        from src.backup.export_folder import ExportFolderError

        _run_phase(run, ctx, "p0_validation", lambda: _p0_into_dated_folder(ctx, run),
                   refusals=(ExportFolderError, ValueError))
    step("P0 trio")

    # 3 -- the committed restore into a fresh install (needs the backup to have passed)
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

    # 4 -- arm the soak, then the online probes while the collector warms up
    if not ctx.stopping:
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

    # 5 -- the soak itself
    if not ctx.stopping and _phase(run, "arm_soak").get("status") == "measured":
        run.begin("soak")
        started = time.time()
        run.soak = {"started_at": _now_iso(), "started_epoch": started, "hours_requested": params.soak_hours,
                    "elapsed_hours": 0.0, "ended_by": None, "stretch": len(run.soak_stretches) + 1,
                    "pid": os.getpid()}
        run.heartbeat(_heartbeat_sample(run))
        next_beat = started + HEARTBEAT_INTERVAL_S
        next_interim = started + INTERIM_REPORT_INTERVAL_S
        deadline = started + params.soak_hours * 3600.0
        ended_by = "window-complete"
        while True:
            now = time.time()
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
        run.soak["elapsed_hours"] = round((time.time() - started) / 3600.0, 2)
        run.soak["ended_by"] = ended_by
        run.soak["ended_at"] = _now_iso()
        run.soak_stretches.append(dict(run.soak))
        run.heartbeat(_heartbeat_sample(run))
        run.end("measured" if ended_by != "cancelled" else "cancelled",
                f"{run.soak['elapsed_hours']} h of {params.soak_hours} h, ended by {ended_by}"
                + (f" (stretch {run.soak.get('stretch')} of this run)" if run.resumed else ""))
    else:
        run.begin("soak")
        run.end("skipped", "the soak was not armed")
    step("soak")

    # 6 -- collect (also after a cancel: whatever the window gave is worth reading)
    _run_phase(run, ctx, "collect", lambda: _collect(ctx, run))
    step("collect")
    _run_phase(run, ctx, "bundle", lambda: _bundle(ctx))
    step("bundle")

    run.outcome = "cancelled" if ctx.stopping else "done"
    path = _write_report(run, interim=False)
    _ledger_event("release-run", action="finished", run_id=run.run_id, outcome=run.outcome)
    report = json.loads(path.read_text(encoding="utf-8"))
    return {"path": str(path), "filename": path.name, "report": report}
