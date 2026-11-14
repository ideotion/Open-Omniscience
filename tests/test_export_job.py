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

    def start_backup(self, dest, pw, **_kw):
        self.dest = dest

    def status(self):
        if self.how == "mode":
            return {"state": "done", "mode": "verify", "dest": self.dest, "running": False}
        if self.how == "dest":
            return {"state": "done", "mode": "backup", "dest": str(self.dest) + "_another_drive", "running": False}
        return {"state": "running", "mode": "backup", "dest": self.dest, "running": True}

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


@pytest.mark.parametrize("how", ["mode", "dest"])
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
