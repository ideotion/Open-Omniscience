"""The storage-events journal's run kinds also keep the folder backup, restore and verification of the large data (WAL, 2026-10-16).

``FolderBackupManager`` copies, restores and verifies tens of gigabytes of wiki dumps, map extracts and model blobs across a drive. Each
mode already left a line in the run journal (``folder-export``, ``folder-import``, ``verify``); none left a durable record that survives a
process killed in the middle of it, and a start that was refused (no room on the drive, a destination that cannot be used, a job already
running) left nothing at all. They record into the same three kinds as the volume set (the run journal calls a folder backup an
``export`` and a folder restore an ``import``) and say ``via: "folder"``, so a reader keeps one list of backups and tells them apart by
that key.

What this file pins:

1. every end of every mode is its own outcome (``ok``, ``paused``, ``cancelled``, ``error``), with the class of the failure and none of
   its words (a destination or a file name must reach neither the journal file, the member, nor the slot's answer);
2. a backup reads the free bytes of its destination after its run is written open, and a restore reads none (it writes to the live
   folders of each category, on any number of volumes: one number would read as the volume it writes to);
3. a start that is refused is a closed record with its fixed sentence and ``via: "folder"``, and the record is written before the raise;
4. a worker that exits by a way no branch names still closes its run, in a ``finally``;
5. the hooks hand over a class name, a key of a table and a named fact (the scan over the sources is in
   ``tests/test_storage_events_runs.py``, extended to this file).
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

import src.backup.folder_backup as fb
from src.backup.folder_backup import BackupItem, FolderBackupManager
from src.monitoring import storage_events as se
from tests.test_storage_events_runs import _events, _nothing_secret_anywhere, _only

ROOT = Path(__file__).resolve().parents[1]
MARKER = "MARKER-folder-4711-correct-horse"


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    se.reset_for_tests()
    yield path
    se.reset_for_tests()


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _items(root: Path) -> list[BackupItem]:
    return [
        BackupItem("wiki_dumps", f"enwiki/{MARKER}-a.bz2", _write(root / "a.bz2", b"a" * 100), 100),
        BackupItem("wiki_dumps", "enwiki/b.bz2", _write(root / "b.bz2", b"b" * 50), 50),
        BackupItem("osm_regions", "europe.pbf", _write(root / "c.pbf", b"c" * 200), 200),
    ]


def _join(mgr: FolderBackupManager, timeout: float = 10.0) -> None:
    thread = mgr._thread
    if thread is not None:
        thread.join(timeout)
        assert not thread.is_alive(), "the folder job must have ended"


# --------------------------------------------------------------------------- #
#  1. The three modes, end to end
# --------------------------------------------------------------------------- #
def test_a_folder_backup_that_finishes_is_an_ok_export_via_folder_with_its_figures(journal, tmp_path):
    mgr = FolderBackupManager()
    drive = tmp_path / f"drive-{MARKER}"
    mgr.start(str(drive), ["wiki_dumps", "osm_regions"], _items=_items(tmp_path / "src"))
    _join(mgr)
    assert mgr.status()["state"] == "done"
    event = _only("run_export")
    assert (event["via"], event["outcome"], event["open"]) == ("folder", "ok", False)
    assert (event["files"], event["copied"], event["skipped"], event["bytes"]) == (3, 3, 0, 350)
    assert isinstance(event["dest_free_bytes"], int) and event["seconds"] >= 0
    assert "error" not in event
    _nothing_secret_anywhere(journal, MARKER, str(drive), "enwiki")


def test_a_folder_backup_is_written_open_with_the_free_bytes_of_its_destination_before_it_copies(journal, tmp_path, monkeypatch):
    seen: list[dict] = []

    def copying(*a, **k):
        seen.append(dict(_events("run_export")[-1]))
        return {"stopped": False, "complete": True, "copied": 0, "skipped": 0, "bytes_copied": 0}

    monkeypatch.setattr(fb, "write_folder_backup", copying)
    mgr = FolderBackupManager()
    mgr.start(str(tmp_path / "drive"), ["wiki_dumps"], _items=_items(tmp_path / "src"))
    _join(mgr)
    assert seen and seen[0]["open"] is True and seen[0]["via"] == "folder" and "outcome" not in seen[0]
    assert "dest_free_bytes" in seen[0] and seen[0]["files"] == 3, "the free bytes were read before the copy began"


def test_the_free_bytes_are_those_of_the_volume_the_destination_is_on_and_a_failed_read_leaves_the_field_absent(journal, tmp_path, monkeypatch):
    asked: list[object] = []

    def free_of(path=None):
        asked.append(path)
        return None

    monkeypatch.setattr(se, "free_bytes_of", free_of)
    mgr = FolderBackupManager()
    mgr.start(str(tmp_path / "drive"), ["wiki_dumps"], _items=_items(tmp_path / "src"))
    _join(mgr)
    assert asked == [tmp_path.resolve()], "a destination that is not made yet is the volume of its nearest existing parent, never the data folder"
    assert "dest_free_bytes" not in _only("run_export"), "an unreadable figure is absent, never 0"
    asked.clear()
    mgr2 = FolderBackupManager()
    mgr2.start(str(tmp_path / "drive"), ["wiki_dumps"], _items=_items(tmp_path / "src2"))  # made by the first run: it exists now
    _join(mgr2)
    assert asked == [(tmp_path / "drive").resolve()], "a destination that exists is stat-ed as it is"


@pytest.mark.parametrize(("cancel", "outcome"), [(False, "paused"), (True, "cancelled")])
def test_a_stopped_backup_is_paused_or_cancelled_and_says_how_far_it_got(journal, tmp_path, monkeypatch, cancel, outcome):
    monkeypatch.setattr(
        fb, "write_folder_backup", lambda *a, **k: {"stopped": True, "complete": False, "copied": 1, "skipped": 2, "bytes_copied": 100}
    )
    mgr = FolderBackupManager()
    mgr._cancelled = cancel
    mgr._run_backup(tmp_path / "drive", _items(tmp_path / "src"), [])
    event = _only("run_export")
    assert (event["via"], event["outcome"], event["copied"], event["skipped"], event["bytes"]) == ("folder", outcome, 1, 2, 100)


def test_a_failing_backup_leaves_the_class_and_none_of_the_words(journal, tmp_path, monkeypatch):
    def failing(*a, **k):
        raise OSError(f"{MARKER} no space left on {tmp_path}")

    monkeypatch.setattr(fb, "write_folder_backup", failing)
    mgr = FolderBackupManager()
    with pytest.raises(OSError):
        mgr._run_backup(tmp_path / "drive", _items(tmp_path / "src"), [])
    assert mgr.status()["state"] == "error"
    event = _only("run_export")
    assert (event["via"], event["outcome"], event["error"], event["open"]) == ("folder", "error", "OSError", False)
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path), "no space left")


def test_a_folder_restore_that_finishes_is_an_ok_import_via_folder_and_reads_no_free_space(journal, tmp_path):
    backup = tmp_path / "drive"
    fb.write_folder_backup(backup, _items(tmp_path / "src"))
    lw, lo = tmp_path / f"lw-{MARKER}", tmp_path / "lo"
    mgr = FolderBackupManager()
    mgr.start(str(backup), ["wiki_dumps", "osm_regions"], mode="restore", _targets={"wiki_dumps": lw, "osm_regions": lo})
    _join(mgr)
    assert mgr.status()["state"] == "done"
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["open"]) == ("folder", "ok", False)
    assert event["restored"] == 3 and event["skipped"] == 0
    assert "data_free_bytes" not in event and "dest_free_bytes" not in event, "the files go to the live folders of each category"
    _nothing_secret_anywhere(journal, MARKER, str(lw), "enwiki")


@pytest.mark.parametrize(("cancel", "outcome"), [(False, "paused"), (True, "cancelled")])
def test_a_stopped_restore_is_paused_or_cancelled(journal, tmp_path, monkeypatch, cancel, outcome):
    monkeypatch.setattr(fb, "restore_folder_backup", lambda *a, **k: {"stopped": True, "restored": 1, "skipped": 0})
    mgr = FolderBackupManager()
    mgr._cancelled = cancel
    mgr._run_restore(tmp_path, [], ["wiki_dumps"])
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["restored"], event["skipped"]) == ("folder", outcome, 1, 0)


def test_a_failing_restore_leaves_the_class_and_none_of_the_words(journal, tmp_path, monkeypatch):
    def failing(*a, **k):
        raise PermissionError(f"{MARKER} {tmp_path}")

    monkeypatch.setattr(fb, "restore_folder_backup", failing)
    mgr = FolderBackupManager()
    with pytest.raises(PermissionError):
        mgr._run_restore(tmp_path, [], ["wiki_dumps"])
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["error"], event["open"]) == ("folder", "error", "PermissionError", False)
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path))


def test_a_folder_verify_that_finishes_is_an_ok_verify_via_folder_with_what_it_checked(journal, tmp_path):
    backup = tmp_path / "drive"
    fb.write_folder_backup(backup, _items(tmp_path / "src"))
    mgr = FolderBackupManager()
    mgr.start(str(backup), [], mode="verify")
    _join(mgr)
    event = _only("run_verify")
    assert (event["via"], event["outcome"], event["open"]) == ("folder", "ok", False)
    assert (event["checked"], event["mismatches"], event["set_ok"]) == (3, 0, True)
    assert "data_free_bytes" not in event and "dest_free_bytes" not in event


def test_a_verify_that_finds_a_changed_file_is_still_an_ok_run_with_the_mismatch_counted_and_the_set_marked_not_ok(journal, tmp_path):
    backup = tmp_path / "drive"
    fb.write_folder_backup(backup, _items(tmp_path / "src"))
    (backup / "osm_regions" / "europe.pbf").write_bytes(b"x")  # a file whose size no longer matches the manifest
    mgr = FolderBackupManager()
    mgr.start(str(backup), [], mode="verify")
    _join(mgr)
    event = _only("run_verify")
    assert (event["outcome"], event["checked"], event["mismatches"], event["set_ok"]) == ("ok", 3, 1, False)


def test_a_verify_with_no_manifest_has_no_counts_and_the_set_marked_not_ok(journal, tmp_path):
    mgr = FolderBackupManager()
    mgr.start(str(tmp_path), [], mode="verify")  # an existing folder with nothing in it
    _join(mgr)
    event = _only("run_verify")
    assert (event["outcome"], event["set_ok"]) == ("ok", False)
    assert "checked" not in event and "mismatches" not in event, "no count is made up for a report that has none"


@pytest.mark.parametrize(("cancel", "outcome"), [(False, "paused"), (True, "cancelled")])
def test_a_stopped_verify_is_paused_or_cancelled_and_has_no_verdict(journal, tmp_path, monkeypatch, cancel, outcome):
    monkeypatch.setattr(
        fb,
        "verify_folder_backup",
        lambda *a, **k: {"stopped": True, "ok": False, "files_checked": 2, "summary": {"ok": 2, "missing": 0}},
    )
    mgr = FolderBackupManager()
    mgr._cancelled = cancel
    mgr._run_verify(tmp_path, [], [])
    event = _only("run_verify")
    assert (event["via"], event["outcome"], event["checked"], event["mismatches"]) == ("folder", outcome, 2, 0)
    assert "set_ok" not in event, "a stopped verify did not reach a verdict: ok False there would read as a bad set"


def test_the_counts_of_a_verify_report_are_the_failures_its_verdict_counts_and_not_size_only():
    summary = {"ok": 5, "size_only": 4, "missing": 1, "size_mismatch": 2, "checksum_mismatch": 3, "traversal_refused": 4, "malformed_entries": 5}
    assert fb._verify_counts({"files_checked": 24, "summary": summary}) == (24, 15)
    assert fb._verify_counts({"files_checked": 0, "summary": {}}) == (0, 0)
    for report in ({}, {"manifest_found": False}, {"summary": None}, {"summary": "x"}):
        assert fb._verify_counts(report) == (None, None)


def test_a_failing_verify_leaves_the_class_and_none_of_the_words(journal, tmp_path, monkeypatch):
    def failing(*a, **k):
        raise ValueError(f"{MARKER} manifest of {tmp_path}")

    monkeypatch.setattr(fb, "verify_folder_backup", failing)
    mgr = FolderBackupManager()
    with pytest.raises(ValueError):
        mgr._run_verify(tmp_path, [], [])
    event = _only("run_verify")
    assert (event["via"], event["outcome"], event["error"], event["open"]) == ("folder", "error", "ValueError", False)
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path), "manifest of")


@pytest.mark.parametrize("worker", ["_run_backup", "_run_restore", "_run_verify"])
def test_an_exit_no_branch_names_still_closes_the_run(journal, tmp_path, monkeypatch, worker):
    class Unhandled(BaseException):
        pass

    def exiting(*a, **k):
        raise Unhandled

    for name in ("write_folder_backup", "restore_folder_backup", "verify_folder_backup"):
        monkeypatch.setattr(fb, name, exiting)
    mgr = FolderBackupManager()
    with pytest.raises(Unhandled):
        getattr(mgr, worker)(tmp_path, [], ["wiki_dumps"])
    kind = {"_run_backup": "run_export", "_run_restore": "run_import", "_run_verify": "run_verify"}[worker]
    assert _only(kind)["outcome"] == "ended-without-a-recorded-outcome"


# --------------------------------------------------------------------------- #
#  2. A start that is refused
# --------------------------------------------------------------------------- #
def test_a_backup_without_room_is_a_refusal_with_its_sentence_and_no_number_of_the_drive(journal, tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "free_bytes", lambda _p: 0)
    mgr = FolderBackupManager()
    with pytest.raises(ValueError, match="Not enough free space"):
        mgr.start(str(tmp_path / f"drive-{MARKER}"), ["wiki_dumps"], _items=_items(tmp_path / "src"))
    event = _only("run_export")
    assert (event["outcome"], event["ran"], event["via"]) == ("refused", False, "folder")
    assert event["reason"] == se.RUN_REFUSALS["no-space"] and "open" not in event
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path))


@pytest.mark.parametrize("kind", ["missing-parent", "empty", "a-file"])
def test_a_destination_that_cannot_be_used_is_a_refusal_with_the_class_and_not_the_path(journal, tmp_path, kind):
    dest = {
        "missing-parent": str(tmp_path / f"no-{MARKER}" / "drive"),
        "empty": "  ",
        "a-file": str(_write(tmp_path / f"file-{MARKER}", b"x")),
    }[kind]
    mgr = FolderBackupManager()
    with pytest.raises(ValueError):
        mgr.start(dest, ["wiki_dumps"], _items=_items(tmp_path / "src"))
    event = _only("run_export")
    assert (event["outcome"], event["ran"], event["via"], event["error"]) == ("refused", False, "folder", "ValueError")
    assert event["reason"] == se.RUN_REFUSALS["destination-unusable"]
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path))


@pytest.mark.parametrize(("mode", "kind"), [("restore", "run_import"), ("verify", "run_verify")])
def test_a_source_that_is_not_a_folder_is_a_refusal_for_a_restore_and_for_a_verify(journal, tmp_path, mode, kind):
    mgr = FolderBackupManager()
    with pytest.raises(ValueError, match="not a folder"):
        mgr.start(str(tmp_path / f"missing-{MARKER}"), [], mode=mode)
    event = _only(kind)
    assert (event["outcome"], event["ran"], event["via"]) == ("refused", False, "folder")
    assert event["reason"] == se.RUN_REFUSALS["not-a-folder"]
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path))


def test_a_start_while_a_job_runs_is_a_refusal_of_the_kind_that_asked_and_the_run_in_flight_still_ends_ok(journal, tmp_path, monkeypatch):
    hold, entered = threading.Event(), threading.Event()

    def slow(*a, **k):
        entered.set()
        assert hold.wait(10)
        return {"stopped": False, "complete": True, "copied": 3, "skipped": 0, "bytes_copied": 350}

    monkeypatch.setattr(fb, "write_folder_backup", slow)
    mgr = FolderBackupManager()
    mgr.start(str(tmp_path / "drive"), ["wiki_dumps"], _items=_items(tmp_path / "src"))
    assert entered.wait(10)
    for mode, kind in (("backup", "run_export"), ("restore", "run_import"), ("verify", "run_verify")):
        with pytest.raises(RuntimeError):
            mgr.start(str(tmp_path / "drive"), [], mode=mode)
        (event,) = [e for e in _events(kind) if e.get("outcome") == "refused"]
        assert (event["reason"], event["via"], event["ran"]) == (se.RUN_REFUSALS["folder-running"], "folder", False)
    hold.set()
    _join(mgr)
    assert [e["outcome"] for e in _events("run_export")].count("ok") == 1, "the run in flight was not pushed out and ended ok"


def test_a_mode_that_is_not_one_is_refused_as_before_and_records_nothing(journal, tmp_path):
    mgr = FolderBackupManager()
    with pytest.raises(ValueError, match="unknown folder-backup mode"):
        mgr.start(str(tmp_path), [], mode="erase")
    for kind in se.RUN_KINDS.values():
        assert se.diagnostics_member(10**9)["kinds"][kind]["total"] == 0


# --------------------------------------------------------------------------- #
#  3. The sources
# --------------------------------------------------------------------------- #
def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / "src/backup/folder_backup.py").read_text(encoding="utf-8"))
    (cls,) = [c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "FolderBackupManager"]
    (fn,) = [f for f in cls.body if isinstance(f, ast.FunctionDef) and f.name == name]
    return fn


def _is_record(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and stmt.value.func.attr == "run_refused"
    )


def test_every_refusing_raise_of_the_start_follows_its_record_and_only_the_unknown_mode_has_none():
    fn = _method("start")
    with_record = without = 0
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if not isinstance(stmt, ast.Raise):
                    continue
                if any(_is_record(earlier) for earlier in block[:i]):
                    with_record += 1
                else:
                    without += 1
                    text = ast.unparse(stmt)
                    assert "unknown folder-backup mode" in text, f"{fn.name}:{stmt.lineno}: a raise with no record before it: {text}"
    assert (with_record, without) == (4, 1)


@pytest.mark.parametrize("name", ["_run_backup", "_run_restore", "_run_verify"])
def test_each_worker_closes_its_run_in_a_finally_net(name):
    fn = _method(name)
    nets = [
        c
        for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        for stmt in t.finalbody
        for c in ast.walk(stmt)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "run_ended"
        and len(c.args) == 2 and isinstance(c.args[1], ast.Constant) and c.args[1].value == "ended-without-a-recorded-outcome"
    ]
    assert len(nets) == 1, f"{name} must close its run in a finally"


def test_the_manager_records_into_the_journal_this_module_reads_and_every_run_is_told_via_folder():
    assert fb.storage_events is se
    assert fb._RUN_OF == {"backup": "export", "restore": "import", "verify": "verify"}
    assert set(fb._RUN_OF.values()) <= set(se.RUN_KINDS)
    tree = ast.parse((ROOT / "src/backup/folder_backup.py").read_text(encoding="utf-8"))
    started = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"run_started", "run_refused"}
    ]
    assert len(started) == 3 + 4
    for call in started:
        via = [kw for kw in call.keywords if kw.arg == "via"]
        assert len(via) == 1 and isinstance(via[0].value, ast.Constant) and via[0].value.value == "folder", call.lineno


def test_the_member_says_the_folder_modes_are_runs_too():
    assert "folder backup" in se._METHOD and "'folder'" in se._METHOD
