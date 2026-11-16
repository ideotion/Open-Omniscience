"""R701: the backup export is ONE server-side job that survives a page reload (R712, R713).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Until R701 the page chained two jobs: the corpus volumes, a data-safety check run IN THE
PAGE, then the large-data copy. A reload between the two meant the copy never started and
the folder read «Backup incomplete». These tests drive the real managers through their test
seams (the volume job's ``_backup_fn``, the folder job's ``_items``) and prove:

  * the folder phase runs with no further call from any client (the reload case);
  * the data-safety gate is the server's now, and an unconfirmed corpus phase never starts
    the copy (the export reads ``failed`` with a named reason);
  * no passphrase reaches the request record, the status, the job registry or a log;
  * a pause in either phase and a resume continue in the SAME dated folder;
  * a restore refuses while an export runs, naming it (R712);
  * the shutdown's ``stop_all_jobs`` stops an export in either phase within its deadline;
  * the main export dialog calls only the new routes (R713 keeps the old ones for the
    advanced panel).
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from pathlib import Path

import pytest

import src.backup.export_job as ej
import src.backup.folder_backup as fb
import src.backup.volume_job as vj
import src.jobs.background as bg
from src.backup.export_folder import REQUEST_NAME, is_export_folder_name, read_export_request
from src.backup.folder_backup import MANIFEST_NAME as FOLDER_MANIFEST
from src.backup.folder_backup import BackupItem
from src.backup.volumes import VolumeStopped
from tests.js_source_helper import app_js, function_body, python_function_source, strip_comments
from tests.test_export_folder import _job_fn

#: Distinctive enough that any appearance anywhere is this passphrase and nothing else.
_PASS = "Zebra-Quokka-7731-planted-export-secret"


@pytest.fixture
def mgrs(monkeypatch):
    """Fresh volume, folder and export managers as the process singletons; the job registry given back afterwards."""
    with bg._REG_LOCK:
        saved = dict(bg._REGISTRY)
    vol = vj.VolumeBackupManager()
    fold = fb.FolderBackupManager()
    monkeypatch.setattr(vj, "_MANAGER", vol)
    monkeypatch.setattr(fb, "_FOLDER_MANAGER", fold)
    exp = ej.ExportJobManager()
    monkeypatch.setattr(ej, "_MANAGER", exp)
    yield exp, vol, fold
    exp.cancel()
    exp._job.join(10)
    with bg._REG_LOCK:
        bg._REGISTRY.clear()
        bg._REGISTRY.update(saved)


def _items(tmp_path: Path) -> list[BackupItem]:
    blob = tmp_path / "weights.bin"
    blob.write_bytes(b"w" * 4096)
    return [BackupItem("models", "m/weights.bin", blob, 4096)]


def _wait(mgr, states: tuple[str, ...], timeout: float = 60.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = mgr.status()
        if st["state"] in states and not mgr._job._alive():
            return st
        time.sleep(0.02)
    raise AssertionError(f"export never reached {states}: {mgr.status()}")


def _blocking_then(real, started: threading.Event):
    """A corpus phase that runs until it is asked to stop, the FIRST time; then ``real``."""
    calls = {"n": 0}

    def fn(dest, pw, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            return real(dest, pw, **kw)
        started.set()
        while True:
            if kw["should_stop"]():
                raise VolumeStopped("stopped between volumes")
            time.sleep(0.01)

    return fn


@pytest.fixture
def blocking_copy(monkeypatch):
    """The large-data copy runs until it is asked to stop, the FIRST time; later calls copy for real."""
    real = fb.write_folder_backup
    started = threading.Event()
    calls = {"n": 0}

    def fake(dest_root, items, *, progress_cb=None, should_stop=None):
        calls["n"] += 1
        if calls["n"] > 1:
            return real(dest_root, items, progress_cb=progress_cb, should_stop=should_stop)
        started.set()
        while True:
            if should_stop and should_stop():
                return {"stopped": True, "complete": False, "copied": 0, "skipped": 0, "bytes_copied": 0}
            time.sleep(0.01)

    monkeypatch.setattr(fb, "write_folder_backup", fake)
    return started


def _dated(drive: Path) -> list[Path]:
    return sorted(p for p in drive.iterdir() if p.is_dir() and is_export_folder_name(p.name))


# --------------------------------------------------------------------------- #
#  The reload: no client ever starts the second phase
# --------------------------------------------------------------------------- #
def test_the_folder_phase_runs_with_no_client_call_and_the_summary_reads_complete(mgrs, tmp_path):
    from src.api.backup_v2 import export_summary_read

    exp, _vol, fold = mgrs
    drive = tmp_path / "drive"
    exp.start(
        str(drive), corpus=True, categories=["models"], passphrase=_PASS,
        _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path),
    )
    # The page is gone: nothing here calls /folder/start (or anything else).
    st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    assert st["state"] == "done", st
    dest = Path(st["dest"])
    assert fold.status()["dest"] == str(dest) and fold.status()["state"] == "done"
    assert (dest / FOLDER_MANIFEST).is_file(), "the large-data copy never ran"
    facts = export_summary_read(str(dest))
    assert facts["missing"] == {"known": True, "corpus": False, "categories": []}, facts["missing"]
    assert facts["corpus_included"] is True
    assert read_export_request(dest)["phase"] == "done"
    assert _dated(drive) == [dest]


# --------------------------------------------------------------------------- #
#  The data-safety gate is the server's
# --------------------------------------------------------------------------- #
class _FakeVolumes:
    """A volume manager whose finished job is NOT a backup of the export's folder."""

    def __init__(self, how: str) -> None:
        self.how = how
        self.dest: str | None = None
        self.t = 1000.0

    def start_backup(self, dest, pw, **_kw):
        self.dest = dest
        return {"state": "running", "mode": "backup", "dest": str(dest), "running": True, "started_at": self.t}

    def status(self):
        if self.how == "mode":
            return {"state": "done", "mode": "verify", "dest": self.dest, "running": False, "started_at": self.t}
        if self.how == "dest":
            return {"state": "done", "mode": "backup", "dest": str(self.dest) + "_another_drive", "running": False,
                    "started_at": self.t}
        if self.how == "other-job":
            # Done, a backup, THIS folder -- but not the job this export started (R701 item 7).
            return {"state": "done", "mode": "backup", "dest": self.dest, "running": False, "started_at": self.t + 1}
        return {"state": "running", "mode": "backup", "dest": self.dest, "running": True, "started_at": self.t}

    def pause(self):
        pass

    def cancel(self):
        pass


class _SpyFolder:
    def __init__(self) -> None:
        self.started: list = []

    def start(self, *a, **k):
        self.started.append((a, k))
        raise AssertionError("the large-data phase started after an unconfirmed corpus phase")

    def status(self):
        return {"state": "idle", "mode": "backup", "dest": None, "running": False}


@pytest.mark.parametrize("how", ["mode", "dest", "other-job"])
def test_an_unconfirmed_corpus_phase_never_starts_the_copy(mgrs, tmp_path, how):
    spy = _SpyFolder()
    exp = ej.ExportJobManager(volume_manager=_FakeVolumes(how), folder_manager=spy)
    try:
        exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS)
        st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    finally:
        exp._job.join(10)
    assert st["state"] == "failed" and st["reason"] == "volumes-unconfirmed", st
    assert st["error"] == ej.UNCONFIRMED
    assert spy.started == []
    assert read_export_request(st["dest"])["phase"] == "volumes", "the cursor must still name the unfinished phase"


def test_a_failed_corpus_phase_never_starts_the_copy(mgrs, tmp_path):
    exp, _vol, fold = mgrs

    def boom(dest, pw, **kw):
        raise OSError("the drive went away")

    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=boom, _items=_items(tmp_path))
    st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    assert st["state"] == "failed" and st["reason"] == "volumes-error", st
    assert "the drive went away" in st["error"]
    assert fold.status()["state"] == "idle", "the copy started after a failed corpus phase"
    assert not (Path(st["dest"]) / FOLDER_MANIFEST).exists()


# --------------------------------------------------------------------------- #
#  The passphrase rule
# --------------------------------------------------------------------------- #
def test_no_passphrase_in_the_record_the_status_the_registry_or_the_logs(mgrs, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    exp, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    seen: list[str] = []
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    seen.append(json.dumps(exp.status()))
    seen.append(json.dumps(bg.all_job_statuses(), default=str))
    st = _wait(exp, ("done",))
    assert exp._secret == [], "the orchestrator still holds the passphrase after the corpus phase started"
    seen.append(json.dumps(st))

    # A failure whose own text quotes the passphrase.
    def leaky(dest, pw, **kw):
        raise RuntimeError(f"could not open the key {pw}")

    exp2_drive = tmp_path / "drive2"
    exp.start(str(exp2_drive), corpus=True, categories=[], passphrase=_PASS, _backup_fn=leaky)
    st2 = _wait(exp, ("failed",))
    assert st2["reason"] == "volumes-error"
    seen.append(json.dumps(st2))
    seen.append(json.dumps(bg.all_job_statuses(), default=str))
    for folder in _dated(drive) + _dated(exp2_drive):
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md"):
                seen.append(f.read_text(encoding="utf-8", errors="replace"))
        assert (folder / REQUEST_NAME).is_file()
    seen.append(caplog.text)
    seen.extend(r.getMessage() for r in caplog.records)
    for i, text in enumerate(seen):
        assert _PASS not in text, f"the passphrase leaked into item {i}: {text[:300]}"


def test_the_passphrase_is_never_a_job_kwarg_and_the_status_holds_no_request_body():
    """The background job's kwargs live as long as its thread: the passphrase must not be one."""
    src = (Path(__file__).resolve().parents[1] / "src/backup/export_job.py").read_text(encoding="utf-8")
    begin = python_function_source(src, "_begin")
    assert "self._job.start()" in begin, "the worker must be started with no kwargs at all"
    status = python_function_source(src, "status")
    assert "self._secret" not in status and "self._request\n" not in status
    assert status.count("passphrase") == status.count("needs_passphrase"), "the status reads a passphrase"


# --------------------------------------------------------------------------- #
#  Pause and resume stay in ONE dated folder
# --------------------------------------------------------------------------- #
def test_a_pause_in_the_folder_phase_then_resume_makes_no_second_folder(mgrs, tmp_path, blocking_copy):
    exp, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60), "the copy never started"
    exp.pause()
    st = _wait(exp, ("paused",))
    dest = Path(st["dest"])
    assert st["phase"] == "folder" and st["needs_passphrase"] is False
    assert read_export_request(dest)["phase"] == "folder"
    exp.resume()  # no passphrase: the copy needs none
    st = _wait(exp, ("done",))
    assert Path(st["dest"]) == dest
    assert _dated(drive) == [dest], "a resume allocated a second dated folder"
    assert (dest / FOLDER_MANIFEST).is_file()


def test_a_pause_in_the_corpus_phase_resumes_with_the_passphrase_in_the_same_folder(mgrs, tmp_path):
    exp, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    started = threading.Event()
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp.pause()
    st = _wait(exp, ("paused",))
    dest = Path(st["dest"])
    assert st["phase"] == "volumes" and st["needs_passphrase"] is True
    with pytest.raises(ValueError, match="passphrase"):
        exp.resume()
    exp.resume(str(dest), passphrase=_PASS)
    st = _wait(exp, ("done",))
    assert _dated(drive) == [dest]
    assert (dest / FOLDER_MANIFEST).is_file(), "the resume did not go on to the copy"


def test_after_a_restart_the_record_alone_resumes_the_named_phase(mgrs, tmp_path, blocking_copy, monkeypatch):
    """No auto-restart: a NEW manager (a restarted process) knows nothing, and the folder's record
    is what a resume continues from."""
    exp, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60)
    exp.pause()
    dest = Path(_wait(exp, ("paused",))["dest"])
    fresh = ej.ExportJobManager()
    monkeypatch.setattr(ej, "_MANAGER", fresh)
    assert fresh.status()["state"] == "idle", "a restarted process must not resume on its own"
    monkeypatch.setattr(fb, "collect_items", lambda **_k: _items(tmp_path))
    fresh.resume(str(dest))
    assert _wait(fresh, ("done",))["dest"] == str(dest)
    assert _dated(drive) == [dest]


# --------------------------------------------------------------------------- #
#  R712: a restore refuses while an export runs
# --------------------------------------------------------------------------- #
def test_a_restore_refuses_while_an_export_runs_and_names_it(mgrs, tmp_path, blocking_copy):
    from src.api.jobs import _import_refusal
    from src.backup.merge import WriterJobsRefused, refuse_while_writer_jobs_run

    exp, _vol, _fold = mgrs
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60)
    # The large-data phase: the volume job is idle, so its own one-job rule refuses nothing.
    with pytest.raises(WriterJobsRefused, match="Backup export"):
        refuse_while_writer_jobs_run()
    assert "Backup export" in (_import_refusal() or ""), "the import page's question does not see the export"
    exp.pause()
    _wait(exp, ("paused",))
    refuse_while_writer_jobs_run()  # a paused export is not running: the restore may go ahead


def test_the_page_reads_the_export_refusal_back_in_the_operator_language():
    import re
    import subprocess

    from src.backup.merge import _EXPORT_RUNNING_REFUSAL
    from tests.test_clickthrough_b13_leftovers import array_literal, function_source, object_literal

    js = app_js()
    message = _EXPORT_RUNNING_REFUSAL.format(job="Backup export")
    size_re = re.search(r'const _OO_SIZE_RE = "[^"\n]*";', js)
    assert size_re
    prog = "\n".join([
        "const OOI18N = { t: (x) => 'T:' + x, tf: (x, v) => 'FRAME<' + x + '>' + JSON.stringify(v) };",
        "const window = { OOI18N };",
        function_source(js, "_sizeText"),
        "const _OO_SPACE_WHAT = " + object_literal(js, "_OO_SPACE_WHAT") + ";",
        size_re.group(0),
        "const _OO_SPACE_RES = " + array_literal(js, "_OO_SPACE_RES") + ";",
        function_source(js, "ooServerText"),
        "process.stdout.write(JSON.stringify(ooServerText(" + json.dumps(message) + ")));",
    ])
    proc = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    key = (
        "A backup export is running ({job}). Nothing was imported and nothing in your corpus changed: an import would switch "
        "the corpus the export is reading. Let the export finish, or pause it, then import again."
    )
    assert out.startswith("FRAME<" + key + ">"), out
    assert json.loads(out.partition(">")[2]) == {"job": "T:Backup export"}
    for path in sorted((Path(__file__).resolve().parents[1] / "src/static/locales").glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        assert key in table and "{job}" in table[key], path.name
        assert "Backup export" in table, path.name


# --------------------------------------------------------------------------- #
#  R689: the shutdown stops an export in either phase within its deadline
# --------------------------------------------------------------------------- #
def test_stop_all_jobs_stops_an_export_in_the_corpus_phase(mgrs, tmp_path):
    exp, _vol, _fold = mgrs
    started = threading.Event()
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    t0 = time.monotonic()
    left = bg.stop_all_jobs(5.0)
    assert time.monotonic() - t0 < 5.0
    assert "backup-export" not in left, left
    st = exp.status()
    assert st["state"] == "paused" and st["phase"] == "volumes", "a shutdown must PAUSE, keeping the volumes"
    assert read_export_request(st["dest"])["phase"] == "volumes"


def test_stop_all_jobs_stops_an_export_in_the_folder_phase(mgrs, tmp_path, blocking_copy):
    exp, _vol, fold = mgrs
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60)
    t0 = time.monotonic()
    left = bg.stop_all_jobs(5.0)
    assert time.monotonic() - t0 < 5.0
    assert "backup-export" not in left, left
    st = exp.status()
    assert st["state"] == "paused" and st["phase"] == "folder"
    assert not fold.status()["running"], "the copy is still running after the shutdown's stop"


# --------------------------------------------------------------------------- #
#  The page: ONE job, ONE status (R713 keeps the old routes for the advanced panel)
# --------------------------------------------------------------------------- #
_MAIN_EXPORT_FNS = (
    "_uxRun", "_uxResume", "_uxPauseResume", "_uxCompleteExport", "_uxShowLastCompletedExportSummary",
    "_uxCancelExport", "_uxWatchExport",
)
_OLD_PHASE_ROUTES = (
    "/api/backup/v2/volumes/", "/api/backup/folder/", "/api/backup/export-folder",
)


def test_the_main_export_dialog_calls_only_the_export_job_routes():
    js = app_js()
    for fn in _MAIN_EXPORT_FNS:
        body = strip_comments(function_body(js, fn))
        for old in _OLD_PHASE_ROUTES:
            assert old not in body, f"{fn} still calls {old}: the main export must use only /api/backup/export/*"
    run = strip_comments(function_body(js, "_uxRun"))
    assert '"/api/backup/export/start"' in run
    assert "passphrase: pass" in run and "verify_after_write: verifyAfterWrite" in run
    watch = strip_comments(function_body(js, "_uxWatchExport"))
    assert '"/api/backup/export/status"' in watch
    assert '"/api/backup/export/resume"' in strip_comments(function_body(js, "_uxResume"))
    assert '"/api/backup/export/pause"' in strip_comments(function_body(js, "_uxPauseResume"))
    assert '"/api/backup/export/cancel"' in strip_comments(function_body(js, "_uxCancelExport"))
    # A reload re-attaches: the reopened dialog reads the export job first.
    reopen = strip_comments(function_body(js, "_uxShowLastCompletedExportSummary"))
    assert '"/api/backup/export/status"' in reopen and "_uxWatchExport(" in reopen
    # The data-safety gate is the server's: the page no longer chains the second phase.
    assert 's1.state !== "done"' not in run


def test_the_old_phase_routes_stay_for_the_advanced_panel():
    """R713: kept, with the guards they have today."""
    from src.api import backup_v2

    paths = {(sorted(r.methods)[0], r.path) for r in backup_v2.router.routes}  # the router's own definitions
    for p in ("/api/backup/v2/volumes/start", "/api/backup/folder/start", "/api/backup/export-folder"):
        assert ("POST", p) in paths, p
    for m, p in (("POST", "/api/backup/export/start"), ("GET", "/api/backup/export/status"),
                 ("POST", "/api/backup/export/pause"), ("POST", "/api/backup/export/resume"),
                 ("POST", "/api/backup/export/cancel")):
        assert (m, p) in paths, p
    js = app_js()
    assert '"/api/backup/v2/volumes/start"' in function_body(js, "volBackupStart"), "the advanced panel lost its start"


# =========================================================================== #
#  Review of 1b88c0b74 (R701 R712 R713): each test below fails on that commit.
# =========================================================================== #
class _SlowStop:
    """A volume manager whose job honours a stop only when ``release`` is set, and then
    ends as the FIRST stop it was asked for (a pause stays a pause on its side)."""

    def __init__(self) -> None:
        self.dest: str | None = None
        self.state = "idle"
        self.t = 0.0
        self.asked: list[str] = []
        self.release = threading.Event()

    def start_backup(self, dest, pw, **_kw):
        self.dest, self.state, self.t = str(dest), "running", time.time()
        return self.status()

    def status(self):
        return {"state": self.state, "mode": "backup", "dest": self.dest,
                "running": self.state == "running", "started_at": self.t}

    def _end(self) -> None:
        self.release.wait(30)
        if self.state == "running":
            self.state = "paused" if self.asked[0] == "pause" else "cancelled"

    def pause(self):
        self.asked.append("pause")
        threading.Thread(target=self._end, daemon=True).start()

    def cancel(self):
        self.asked.append("cancel")
        threading.Thread(target=self._end, daemon=True).start()


def _until(pred, timeout: float = 10.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition never held")


def test_a_slow_stop_keeps_the_export_live_and_stopping_until_its_phase_ends(mgrs, tmp_path, monkeypatch):
    """Item 4: no deadline ends the export while its phase still writes into the folder."""
    from src.backup.merge import WriterJobsRefused, refuse_while_writer_jobs_run

    monkeypatch.setattr(ej, "_STOP_WAIT_S", 0.2, raising=False)  # the old cut-off, made short
    vol = _SlowStop()
    exp = ej.ExportJobManager(volume_manager=vol, folder_manager=_SpyFolder())
    monkeypatch.setattr(ej, "_MANAGER", exp)
    try:
        exp.start(str(tmp_path / "drive"), corpus=True, categories=[], passphrase=_PASS)
        _until(lambda: vol.state == "running")
        exp.pause()
        time.sleep(0.8)
        st = exp.status()
        assert st["state"] == "stopping" and st["running"] is True, st
        assert exp.live()
        with pytest.raises(WriterJobsRefused, match="Backup export"):
            refuse_while_writer_jobs_run()  # R712 holds while the phase is still stopping
        vol.release.set()
        st = _wait(exp, ("paused", "failed", "cancelled", "done"))
        assert st["state"] == "paused" and st["phase"] == "volumes", st
        assert not exp.live()
    finally:
        vol.release.set()
        exp._job.join(10)


class _Interrupt(BaseException):
    pass


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the interrupt goes on up, as it must
def test_a_base_exception_in_the_worker_never_leaves_the_export_running(mgrs, tmp_path):
    """Item 4: live() cannot stick at True after the worker died of a BaseException."""

    class _Dies(_FakeVolumes):
        def start_backup(self, dest, pw, **_kw):
            raise _Interrupt()

    exp = ej.ExportJobManager(volume_manager=_Dies("running"), folder_manager=_SpyFolder())
    try:
        exp.start(str(tmp_path / "drive"), corpus=True, categories=[], passphrase=_PASS)
        exp._job.join(10)
    finally:
        exp._job.join(10)
    st = exp.status()
    assert st["state"] == "failed" and st["reason"] == "interrupted", st
    assert not exp.live()
    assert exp._secret == []


def test_pause_then_cancel_while_stopping_ends_cancelled(mgrs, tmp_path, monkeypatch):
    """Item 9: the last explicit request wins, and a Cancel outranks a Pause -- even when the
    phase's own job had already taken the Pause."""
    vol = _SlowStop()
    exp = ej.ExportJobManager(volume_manager=vol, folder_manager=_SpyFolder())
    try:
        exp.start(str(tmp_path / "drive"), corpus=True, categories=[], passphrase=_PASS)
        _until(lambda: vol.state == "running")
        exp.pause()
        _until(lambda: exp.status()["state"] == "stopping")
        exp.cancel()
        vol.release.set()
        st = _wait(exp, ("paused", "failed", "cancelled", "done"))
    finally:
        vol.release.set()
        exp._job.join(10)
    assert st["state"] == "cancelled", st
    assert read_export_request(st["dest"])["phase"] == "cancelled"


def test_a_paused_export_can_be_cancelled_and_its_partial_volumes_go(mgrs, tmp_path):
    """Item 9: the page shows Cancel on a paused export, and the server takes it."""
    exp, _vol, _fold = mgrs
    started = threading.Event()
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp.pause()
    dest = Path(_wait(exp, ("paused",))["dest"])
    partial = dest / "vol-0001.ooenc"
    partial.write_bytes(b"partial")
    st = exp.cancel()
    assert st["state"] == "cancelled", st
    assert read_export_request(dest)["phase"] == "cancelled"
    assert not partial.exists(), "a cancelled corpus phase kept its partial volumes"
    assert not exp.live()


def test_the_task_manager_shows_a_paused_export_as_paused(mgrs, tmp_path, blocking_copy):
    """Item 9: the worker thread has ended, but the export is paused, not done."""
    from src.api.jobs import _background_jobs

    exp, _vol, _fold = mgrs
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60)
    rows = [r for r in _background_jobs() if r["kind"] == "backup-export"]
    assert [r["state"] for r in rows] == ["running"], rows
    exp.pause()
    _wait(exp, ("paused",))
    rows = [r for r in _background_jobs() if r["kind"] == "backup-export"]
    assert [r["state"] for r in rows] == ["paused"], rows
    assert rows[0]["actions"] == []


class _OtherFolderJob:
    """A folder manager whose status, after the export's start, is ANOTHER copy into the same
    folder (the advanced panel's /folder/start in the poll window)."""

    def __init__(self) -> None:
        self.dest: str | None = None

    def start(self, dest, categories, **_kw):
        self.dest = str(dest)
        return {"state": "running", "mode": "backup", "dest": self.dest, "running": True, "started_at": 1.0}

    def status(self):
        return {"state": "done", "mode": "backup", "dest": self.dest, "running": False, "started_at": 2.0}


def test_a_large_data_job_that_is_not_this_exports_is_never_counted_as_its_copy(mgrs, tmp_path):
    """Item 7: identity is mode, folder AND the started_at the start answered with."""
    exp = ej.ExportJobManager(volume_manager=_FakeVolumes("running"), folder_manager=_OtherFolderJob())
    try:
        exp.start(str(tmp_path / "drive"), corpus=False, categories=["models"])
        st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    finally:
        exp._job.join(10)
    assert st["state"] == "failed" and st["reason"] == "folder-unconfirmed", st
    assert st["error"] == ej.FOLDER_UNCONFIRMED and st["error_phase"] == "folder"
    assert read_export_request(st["dest"])["phase"] == "folder"


class _Restoring:
    def status(self):
        return {"state": "running", "mode": "restore", "dest": "/somewhere", "running": True, "started_at": 1.0}


@pytest.mark.parametrize("where", ["volumes", "folder", "queue"])
def test_an_export_refuses_to_start_or_resume_while_a_restore_runs(mgrs, tmp_path, monkeypatch, where):
    """Item 8: R712 the other way round, with a named refusal."""
    import src.backup.import_queue as iq

    exp0, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    # A paused large-data phase to try to resume.
    started = threading.Event()
    exp0.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
               _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp0.pause()
    dest = Path(_wait(exp0, ("paused",))["dest"])
    kw: dict = {}
    if where == "volumes":
        kw["volume_manager"] = _Restoring()
    elif where == "folder":
        kw["folder_manager"] = _Restoring()
    else:
        class _Q:
            _state = "running"
        monkeypatch.setattr(iq, "_MANAGER", _Q())
    exp = ej.ExportJobManager(**kw)
    with pytest.raises(RuntimeError) as start_err:
        exp.start(str(drive), corpus=False, categories=["models"], _items=_items(tmp_path))
    assert str(start_err.value) == ej.RESTORE_RUNNING
    with pytest.raises(RuntimeError) as resume_err:
        exp.resume(str(dest), passphrase=_PASS)
    assert str(resume_err.value) == ej.RESTORE_RUNNING
    assert _dated(drive) == [dest], "a refused start still allocated a folder"


def test_a_record_naming_only_unknown_categories_is_refused_and_copies_nothing(mgrs, tmp_path, monkeypatch):
    """Item 6: the folder job widens a list of unknown names to EVERY category."""
    from src.backup.export_folder import allocate_export_folder

    exp, _vol, fold = mgrs
    monkeypatch.setattr(fb, "collect_items", lambda **_k: _items(tmp_path))
    dest = allocate_export_folder(tmp_path / "drive")
    (dest / REQUEST_NAME).write_text(json.dumps({
        "schema": "oo-export-request-1", "corpus": False, "categories": ["bogus"], "inside": False, "phase": "folder",
    }), encoding="utf-8")
    assert read_export_request(dest)["categories"] == [], "an unknown category was read back from the record"
    with pytest.raises(ValueError) as err:
        exp.resume(str(dest))
    assert str(err.value) == ej.NO_CATEGORIES
    assert fold.status()["state"] == "idle", "the copy started"
    assert sorted(p.name for p in dest.iterdir()) == [REQUEST_NAME], "something was copied"


@pytest.mark.parametrize("ending", ["cancelled", "done"])
def test_copy_the_large_data_files_now_finishes_a_done_or_cancelled_export(mgrs, tmp_path, blocking_copy, monkeypatch, ending):
    """Item 2: the completion panel's «Copy the large-data files now» for a folder whose
    record says done or cancelled but still lacks the files, through the REAL folder job,
    into the SAME folder, copying only what is missing."""
    from src.api.backup_v2 import export_summary_read

    exp, _vol, fold = mgrs
    drive = tmp_path / "drive"
    present = tmp_path / "present.bin"
    present.write_bytes(b"p" * 1000)
    items = _items(tmp_path) + [BackupItem("models", "m/present.bin", present, 1000)]
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=items)
    assert blocking_copy.wait(60)
    exp.cancel()
    dest = Path(_wait(exp, ("cancelled",))["dest"])
    assert read_export_request(dest)["phase"] == "cancelled"
    if ending == "done":
        from src.backup.export_folder import update_export_phase

        update_export_phase(dest, "done")
    (dest / "models" / "m").mkdir(parents=True)
    (dest / "models" / "m" / "present.bin").write_bytes(b"p" * 1000)  # already copied before the stop
    assert export_summary_read(str(dest))["missing"]["categories"] == ["models"]
    fresh = ej.ExportJobManager()  # a restarted process: nothing but the folder
    monkeypatch.setattr(ej, "_MANAGER", fresh)
    monkeypatch.setattr(fb, "collect_items", lambda **_k: items)
    fresh.resume(str(dest))  # no passphrase: the corpus is already there
    st = _wait(fresh, ("done", "failed", "paused", "cancelled"))
    assert st["state"] == "done" and st["dest"] == str(dest), st
    assert _dated(drive) == [dest]
    assert (dest / FOLDER_MANIFEST).is_file()
    prog = fold.status()["progress"]
    assert prog.get("copied") == 1 and prog.get("skipped") == 1, prog
    assert export_summary_read(str(dest))["missing"] == {"known": True, "corpus": False, "categories": []}


def test_a_managers_own_error_reaches_the_status_unprefixed_with_its_phase_beside_it(mgrs, tmp_path):
    """Item 5: the page translates a manager's sentence whole; a prefix broke that."""
    exp, _vol, _fold = mgrs

    def wrong(dest, pw, **kw):
        raise ValueError("wrong passphrase or the file has been altered")

    exp.start(str(tmp_path / "drive"), corpus=True, categories=[], passphrase=_PASS, _backup_fn=wrong)
    st = _wait(exp, ("failed",))
    assert st["error"] == "wrong passphrase or the file has been altered", st["error"]
    assert st["error_phase"] == "volumes"


def _ooservertext_in(lang: str, messages: list[str]) -> list[str]:
    """ooServerText as shipped, under a page whose t()/tf() read the REAL locale file."""
    import re
    import subprocess

    from tests.test_clickthrough_b13_leftovers import array_literal, function_source, object_literal

    js = app_js()
    table = json.loads((Path(__file__).resolve().parents[1] / f"src/static/locales/{lang}.json").read_text("utf-8"))
    size_re = re.search(r'const _OO_SIZE_RE = "[^"\n]*";', js)
    assert size_re
    prog = "\n".join([
        "const TABLE = " + json.dumps(table, ensure_ascii=False) + ";",
        "const OOI18N = { t: (x) => (TABLE[x] || x),",
        "  tf: (x, v) => (TABLE[x] || x).replace(/\\{(\\w+)\\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)) };",
        "const window = { OOI18N };",
        function_source(js, "_sizeText"),
        "const _OO_SPACE_WHAT = " + object_literal(js, "_OO_SPACE_WHAT") + ";",
        size_re.group(0),
        "const _OO_SPACE_RES = " + array_literal(js, "_OO_SPACE_RES") + ";",
        function_source(js, "ooServerText"),
        "process.stdout.write(JSON.stringify(" + json.dumps(messages) + ".map(ooServerText)));",
    ])
    # In a file: a whole locale table is past the argv limit. It went on node's stdin until row 93, and on Windows that run never
    # returned (named by the portability legs' hang watchdog, run 43803278424, shard 3): no other node test here feeds stdin, and
    # every one that passes on Windows runs a file. Written and read as UTF-8 on every OS (Windows' default is the ANSI code page),
    # and bounded, so a stuck node is a named failure rather than a hang.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "ooservertext.js"
        script.write_text(prog, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False
        )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_gate_and_the_wrong_passphrase_sentences_render_translated_in_french():
    """Item 5: what the status carries is what the page translates -- in a real locale."""
    fr = json.loads((Path(__file__).resolve().parents[1] / "src/static/locales/fr.json").read_text("utf-8"))
    gate, wrong = _ooservertext_in("fr", [ej.UNCONFIRMED, "wrong passphrase or the file has been altered"])
    assert gate == fr[ej.UNCONFIRMED] and gate != ej.UNCONFIRMED, gate
    assert wrong == fr["Could not open this backup: the passphrase is wrong, or its files have been altered."], wrong


_FIXED = ("UNCONFIRMED", "FOLDER_UNCONFIRMED", "NEEDS_PASSPHRASE", "NOTHING_TO_RESUME", "ALREADY_RUNNING",
          "RESTORE_RUNNING", "NO_CATEGORIES", "NOT_AN_EXPORT_FOLDER", "NO_RECORD", "INTERNAL", "INTERRUPTED")


def test_every_fixed_export_sentence_is_translated_whole_in_every_locale():
    """Item 5: the export's own sentences carry no path or class, and each one is a key."""
    sentences = [getattr(ej, n) for n in _FIXED]
    for path in sorted((Path(__file__).resolve().parents[1] / "src/static/locales").glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        for s in sentences:
            assert s in table, (path.name, s)
    out = _ooservertext_in("de", sentences)
    de = json.loads((Path(__file__).resolve().parents[1] / "src/static/locales/de.json").read_text("utf-8"))
    assert out == [de[s] for s in sentences]


# =========================================================================== #
#  Security re-read of baf4f4938: each test below fails on that commit.
# =========================================================================== #
def _planted_folder(tmp_path: Path, monkeypatch) -> Path:
    """A dated folder on the drive with a valid record in the large-data phase, carrying a
    planted key, as anyone who can write the drive could leave it."""
    from src.backup.export_folder import allocate_export_folder

    monkeypatch.setattr(fb, "collect_items", lambda **_k: _items(tmp_path))
    dest = allocate_export_folder(tmp_path / "drive")
    (dest / REQUEST_NAME).write_text(json.dumps({
        "schema": "oo-export-request-1", "requested_at": "2026-11-14T12:00:00+00:00", "corpus": False,
        "categories": ["models"], "inside": False, "phase": "folder", "planted": "ATTACKER-SHAPED",
    }), encoding="utf-8")
    return dest


def test_a_planted_temp_file_link_is_never_written_through_on_resume(mgrs, tmp_path, monkeypatch):
    """Security item 1: ``.oopart`` planted as a link to a file outside the folder."""
    exp, _vol, _fold = mgrs
    dest = _planted_folder(tmp_path, monkeypatch)
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched", encoding="utf-8")
    link = dest / (REQUEST_NAME + ".oopart")
    try:
        link.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    exp.resume(str(dest))
    st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    assert victim.read_text(encoding="utf-8") == "untouched", "the resume wrote through the planted link"
    assert st["state"] == "done", st
    rec = dest / REQUEST_NAME
    assert not rec.is_symlink() and not link.is_symlink()
    raw = json.loads(rec.read_text(encoding="utf-8"))
    assert raw["phase"] == "done"
    assert "planted" not in raw, "a planted key was copied back into the record"


def test_a_record_that_is_a_link_is_refused_and_its_target_untouched(mgrs, tmp_path, monkeypatch):
    """Security item 1: the record itself planted as a link -- read as no record, never rewritten."""
    exp, _vol, fold = mgrs
    dest = _planted_folder(tmp_path, monkeypatch)
    victim = tmp_path / "victim.json"
    victim.write_text((dest / REQUEST_NAME).read_text(encoding="utf-8"), encoding="utf-8")
    before = victim.read_text(encoding="utf-8")
    (dest / REQUEST_NAME).unlink()
    try:
        (dest / REQUEST_NAME).symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(ValueError) as err:
        exp.resume(str(dest))
    assert str(err.value) == ej.NO_RECORD
    assert victim.read_text(encoding="utf-8") == before
    assert fold.status()["state"] == "idle"


def test_an_export_refuses_to_start_or_resume_while_a_single_file_restore_holds_the_marker(mgrs, tmp_path, monkeypatch):
    """Security item 2: the synchronous ``/legacy/restore`` owns no manager; it holds the shared
    marker (src/backup/restore_marker.py), and the export sees it."""
    from src.api import backup_v2
    from src.backup import restore_marker

    exp, _vol, _fold = mgrs
    drive = tmp_path / "drive"
    started = threading.Event()
    exp.start(str(drive), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp.pause()
    dest = Path(_wait(exp, ("paused",))["dest"])

    inside = threading.Event()
    leave = threading.Event()

    # The REAL single-file restore, held at its first step (round 3, item 7: a wrapper beside
    # it proved nothing about the restore itself).
    def held_at_the_memory_check():
        inside.set()
        leave.wait(30)
        raise backup_v2.MergeError("released by the test")

    monkeypatch.setattr(backup_v2, "check_memory_before_staging", held_at_the_memory_check)
    archive = tmp_path / "old-backup.db"
    archive.write_bytes(b"x" * 64)

    def run():
        # the release ends it with a refusal, as intended
        with contextlib.suppress(Exception):
            backup_v2.restore_legacy_path(str(archive), None)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    try:
        assert inside.wait(10)
        assert restore_marker.restore_in_progress(), "the single-file restore is running and the marker does not count it"
        with pytest.raises(RuntimeError) as start_err:
            exp.start(str(drive), corpus=False, categories=["models"], _items=_items(tmp_path))
        assert str(start_err.value) == ej.RESTORE_RUNNING
        with pytest.raises(RuntimeError) as resume_err:
            exp.resume(str(dest), passphrase=_PASS)
        assert str(resume_err.value) == ej.RESTORE_RUNNING
        assert _dated(drive) == [dest]
    finally:
        leave.set()
        t.join(10)
    assert not restore_marker.restore_in_progress()


def test_every_restore_path_enters_the_marker():
    """Security item 2: the single-file restore, the volume and folder restore workers and the
    import queue's run all run inside the shared marker."""
    import ast

    from src.api import backup_v2

    root = Path(__file__).resolve().parents[1]
    for path, name in (("src/api/backup_v2.py", "restore_legacy_path"), ("src/backup/volume_job.py", "_run_restore"),
                       ("src/backup/folder_backup.py", "_run_restore"), ("src/backup/import_queue.py", "_run")):
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        fns = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name]
        assert fns, f"{path}:{name} not found"
        for fn in fns:
            assert "restore_marker.marked" in [ast.unparse(d) for d in fn.decorator_list], (
                f"{path}:{name} does not enter the restore marker")
    assert backup_v2.restore_legacy_path.__wrapped__ is not None


# =========================================================================== #
#  Correctness read of baf4f4938, and Plan's R712 scope ruling: red on that commit.
# =========================================================================== #
def test_a_failed_corpus_phase_can_be_cancelled_here_and_after_a_restart(mgrs, tmp_path, monkeypatch):
    """Item 5: «Resume export» was offered for a failed folder forever."""
    exp, _vol, _fold = mgrs

    def boom(dest, pw, **kw):
        raise OSError("the drive went away")

    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=boom, _items=_items(tmp_path))
    st = _wait(exp, ("failed",))
    dest = Path(st["dest"])
    assert read_export_request(dest)["phase"] == "volumes"
    partial = dest / "vol-0001.ooenc"
    partial.write_bytes(b"partial")
    # After a restart: the folder's record is all there is.
    fresh = ej.ExportJobManager()
    monkeypatch.setattr(ej, "_MANAGER", fresh)
    fresh.cancel(str(dest))
    assert read_export_request(dest)["phase"] == "cancelled"
    assert not partial.exists(), "the cancelled corpus phase kept its partial volumes"
    # And in the same process.
    exp2_drive = tmp_path / "drive2"
    exp.start(str(exp2_drive), corpus=True, categories=[], passphrase=_PASS, _backup_fn=boom)
    dest2 = Path(_wait(exp, ("failed",))["dest"])
    assert exp.cancel()["state"] == "cancelled"
    assert read_export_request(dest2)["phase"] == "cancelled"


def test_a_cancel_after_paused_but_before_the_worker_exits_is_acted_on(mgrs, tmp_path, monkeypatch):
    """Item 6: the flag a worker has stopped reading is never the whole of a cancel."""
    exp, _vol, _fold = mgrs
    started = threading.Event()
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp.pause()
    dest = Path(_wait(exp, ("paused",))["dest"])
    partial = dest / "vol-0001.ooenc"
    partial.write_bytes(b"partial")
    monkeypatch.setattr(exp._job, "_alive", lambda: True)  # the worker has set paused and not yet returned
    st = exp.cancel()
    assert st["state"] == "cancelled", st
    assert read_export_request(dest)["phase"] == "cancelled"
    assert not partial.exists(), "the cancelled corpus phase kept its partial volumes"


def test_a_stop_after_the_boundary_check_never_starts_the_copy(mgrs, tmp_path, monkeypatch):
    """Item 7: a pause landing between the boundary check and the copy's start."""
    spy = _SpyFolder()
    exp = ej.ExportJobManager(folder_manager=spy)
    real = ej.update_export_phase

    def cursor_then_pause(folder, phase):
        out = real(folder, phase)
        if phase == "folder":
            exp.pause()  # after the corpus phase's boundary check, before the copy starts
        return out

    monkeypatch.setattr(ej, "update_export_phase", cursor_then_pause)
    try:
        exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
                  _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
        st = _wait(exp, ("done", "failed", "paused", "cancelled"))
    finally:
        exp._job.join(10)
    assert st["state"] == "paused" and st["phase"] == "folder", st
    assert spy.started == [], "the copy started after the pause"


def _restorable(tmp_path: Path) -> Path:
    src = tmp_path / "blobsrc"
    src.mkdir()
    return src


@pytest.mark.parametrize("phase", ["volumes", "folder"])
def test_a_large_data_import_is_refused_by_name_while_an_export_runs(mgrs, tmp_path, blocking_copy, phase):
    """Item 9 (Plan's R712 ruling): a ``blobs`` import is refused for the whole export, naming it."""
    exp, _vol, fold = mgrs
    started = threading.Event()
    fn = _blocking_then(_job_fn(tmp_path, "a"), started) if phase == "volumes" else _job_fn(tmp_path, "a")
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=fn, _items=_items(tmp_path))
    assert (started if phase == "volumes" else blocking_copy).wait(60)
    assert exp.status()["phase"] == phase
    with pytest.raises(RuntimeError, match="Backup export"):
        fold.start(str(_restorable(tmp_path)), ["models"], mode="restore")


def test_an_export_start_is_refused_while_a_large_data_import_holds_the_marker(mgrs, tmp_path, monkeypatch):
    """Item 9: the blobs import's worker holds the shared marker for its whole run."""
    exp, _vol, fold = mgrs
    inside, leave = threading.Event(), threading.Event()

    def blocking_restore(*_a, **_k):
        inside.set()
        leave.wait(30)
        return {"restored": 0, "skipped": 0}

    monkeypatch.setattr(fb, "restore_folder_backup", blocking_restore)
    t = threading.Thread(target=fold._run_restore, args=(_restorable(tmp_path), [], ["models"]), daemon=True)
    t.start()
    try:
        assert inside.wait(10)
        with pytest.raises(RuntimeError) as err:
            exp.start(str(tmp_path / "drive"), corpus=False, categories=["models"], _items=_items(tmp_path))
        assert str(err.value) == ej.RESTORE_RUNNING
    finally:
        leave.set()
        t.join(10)


# =========================================================================== #
#  Round 3 on f31454a28: red on that commit (item 5's identity test excepted, see it).
# =========================================================================== #
def test_a_cancel_landing_while_a_pause_is_recorded_is_never_lost(mgrs, tmp_path, monkeypatch):
    """Round 3, item 2: the Cancel arrives after the pause was decided and before the state reads paused."""
    exp, _vol, _fold = mgrs
    started = threading.Event()
    real = ej.update_export_phase
    fired: list = []

    def cursor_then_cancel(folder, phase):
        out = real(folder, phase)
        if phase == "volumes" and exp._state == "stopping" and not fired:
            fired.append(1)
            exp.cancel()  # accepted: the export still reads stopping
        return out

    monkeypatch.setattr(ej, "update_export_phase", cursor_then_cancel)
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    dest = Path(exp.status()["dest"])
    partial = dest / "vol-0001.ooenc"
    partial.write_bytes(b"partial")
    exp.pause()
    st = _wait(exp, ("paused", "cancelled", "failed", "done"))
    assert fired, "the window was never reached"
    assert st["state"] == "cancelled", st
    assert read_export_request(dest)["phase"] == "cancelled"
    assert not partial.exists(), "the cancelled corpus phase kept its partial volumes"


def test_a_cancel_before_a_resumed_corpus_phase_starts_removes_the_paused_runs_volumes(mgrs, tmp_path, monkeypatch):
    """Round 3, item 3."""
    exp, _vol, _fold = mgrs
    started = threading.Event()
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    exp.pause()
    dest = Path(_wait(exp, ("paused",))["dest"])
    partial = dest / "vol-0001.ooenc"
    partial.write_bytes(b"partial")
    real = ej.update_export_phase

    def cursor_then_cancel(folder, phase):
        out = real(folder, phase)
        if phase == "volumes" and exp._state == "running":
            exp.cancel()  # after the resume went live, before the corpus phase starts
        return out

    monkeypatch.setattr(ej, "update_export_phase", cursor_then_cancel)
    exp.resume(str(dest), passphrase=_PASS)
    st = _wait(exp, ("paused", "cancelled", "failed", "done"))
    assert st["state"] == "cancelled", st
    assert read_export_request(dest)["phase"] == "cancelled"
    assert not partial.exists(), "the paused run's partial volumes stayed in a cancelled folder"


def _bounded(fn, timeout: float = 5.0):
    """Run ``fn`` in a thread; the result, or AssertionError when it is still blocked."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return t, box


def test_a_fifo_planted_as_the_record_never_blocks_a_resume_or_a_cancel(mgrs, tmp_path, monkeypatch):
    """Round 3, item 4 (security nit): a FIFO in place of the record used to block the read
    forever -- under the export's lock and the restore marker's."""
    import os

    from src.backup import restore_marker
    from src.backup.export_folder import allocate_export_folder

    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs here")
    exp, _vol, _fold = mgrs
    dest = allocate_export_folder(tmp_path / "drive")
    fifo = dest / REQUEST_NAME
    os.mkfifo(fifo)
    try:
        for call in (lambda: exp.resume(str(dest), passphrase=_PASS), lambda: exp.cancel(str(dest))):
            t, box = _bounded(call)
            assert not t.is_alive(), "a FIFO planted as the record blocked the call"
            if "error" in box:
                assert isinstance(box["error"], ValueError) and str(box["error"]) == ej.NO_RECORD, box
        t, _box = _bounded(restore_marker.restore_in_progress)
        assert not t.is_alive(), "the restore marker's lock is held by a blocked read"
    finally:
        # Unblock a reader still waiting on the FIFO (the old code), so later tests are not held up.
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass


def test_the_phase_managers_paused_job_reads_cancelled_after_the_export_is_cancelled(mgrs, tmp_path, blocking_copy):
    """Round 3, item 6: the advanced panel must not offer to resume a cancelled export's copy."""
    exp, _vol, fold = mgrs
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_job_fn(tmp_path, "a"), _items=_items(tmp_path))
    assert blocking_copy.wait(60)
    exp.pause()
    _wait(exp, ("paused",))
    _until(lambda: not fold.status()["running"])
    assert fold.status()["state"] == "paused"
    exp.cancel()
    assert fold.status()["state"] == "cancelled", fold.status()


def test_the_live_exports_folder_named_another_way_is_cancelled_through_the_job(mgrs, tmp_path, monkeypatch):
    """Round 3, item 5 (security nit). The identity is the drive's (``os.path.samefile``), so a
    case-insensitive drive's other spelling of the live folder is the live folder, and the
    {dir} path never rewrites its record under the running worker. EMULATED: this test runs on
    a case-sensitive file system, so the drive's answers are given; it pins the identity rule
    and is not meaningfully red on f31454a28 there: it fails on that commit only because the
    module did not import ``os`` (that commit compared resolved spellings, which a real
    case-insensitive drive defeats and this emulation cannot reproduce)."""
    import os

    exp, _vol, _fold = mgrs
    started = threading.Event()
    exp.start(str(tmp_path / "drive"), corpus=True, categories=["models"], passphrase=_PASS,
              _backup_fn=_blocking_then(_job_fn(tmp_path, "a"), started), _items=_items(tmp_path))
    assert started.wait(30)
    dest = exp.status()["dest"]
    other = dest.upper()
    real_exists, real_same = os.path.exists, os.path.samefile
    from tests.os_scope import scope_os_path

    scope_os_path(
        monkeypatch,
        ej,
        exists=lambda p: real_exists(dest) if str(p) == other else real_exists(p),
        samefile=lambda a, b: str(a).lower() == str(b).lower() or real_same(a, b),
    )
    assert ej._same_path(other, dest)
    exp.cancel(other)
    st = _wait(exp, ("paused", "cancelled", "failed", "done"))
    assert st["state"] == "cancelled", st  # the job cancelled it: the worker, not a record write
