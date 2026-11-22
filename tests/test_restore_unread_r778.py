"""R778: one file a restore cannot READ no longer stops the restore.

It is left out and counted, with one fixed reason (never the system's words); the rest is restored;
nothing half-copied is left behind; the result says "incomplete"; and a second run restores exactly the
files the first one could not. A failure on the WRITING side (a full disk, a live folder that cannot be
written) still stops the restore with an error, because every file after it would fail the same way.
Failures are injected through ``tests.os_scope`` (R351): the container runs as root, so ``chmod 000``
would not refuse anything here.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup import folder_backup, links
from src.backup.folder_backup import restore_folder_backup
from tests.os_scope import scope_os

ROOT = Path(__file__).resolve().parents[1]


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _skip_sub(monkeypatch, kind: str, on_sub=None) -> None:
    """What the walk does with a folder it cannot list: it never hands it back. R783: the restore walks by
    folder handle (``_fd_walk``) where the system can, and by path (``os.walk``) where it cannot; both are
    driven here, so the rule holds on either."""
    if kind == "path":
        monkeypatch.setattr(folder_backup, "_FD_RELATIVE", False)
        real_walk = os.walk

        def fake_walk(top, topdown=True, onerror=None, followlinks=False):
            for dirpath, dirnames, names in real_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
                if os.path.basename(dirpath) == "sub":
                    if on_sub is not None:
                        on_sub(dirpath)
                    dirnames.clear()
                    continue
                yield dirpath, dirnames, names

        scope_os(monkeypatch, folder_backup, walk=fake_walk)
        return
    if not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    real_walk = folder_backup._fd_walk

    def fake_fd_walk(top):
        for dirpath, dirnames, names, fd in real_walk(top):
            if os.path.basename(dirpath) == "sub":
                if on_sub is not None:
                    on_sub(dirpath)
                dirnames.clear()
                continue
            yield dirpath, dirnames, names, fd

    monkeypatch.setattr(folder_backup, "_fd_walk", fake_fd_walk)


_WALKS = pytest.mark.parametrize("kind", ["fd", "path"])


def _targets(tmp: Path) -> dict[str, Path]:
    return {c: tmp / "live" / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")}


def _files(d: Path) -> list[str]:
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) if d.exists() else []


def _backup(tmp: Path) -> Path:
    b = tmp / "backup"
    _touch(b / "wiki_dumps" / "a.bz2", b"aaa")
    _touch(b / "wiki_dumps" / "b.bz2", b"bbb")
    _touch(b / "osm_regions" / "kenya.osm.pbf", b"map")
    return b


def _refuse_open(monkeypatch, name: str, exc: OSError) -> None:
    real = os.open

    def fake(path, flags, *a, **k):
        if os.fspath(path).endswith(name) and not (flags & os.O_CREAT):
            raise exc
        return real(path, flags, *a, **k)

    scope_os(monkeypatch, folder_backup, open=fake)


@pytest.mark.parametrize(
    ("exc", "why"),
    [
        (PermissionError(errno.EACCES, "Permission denied"), "denied"),
        (FileNotFoundError(errno.ENOENT, "No such file"), "gone"),
        (IsADirectoryError(errno.EISDIR, "Is a directory"), "not-a-file"),
        (OSError(errno.EIO, "Input/output error"), "read-failed"),
    ],
)
def test_one_unreadable_file_is_counted_and_the_restore_goes_on(tmp_path, monkeypatch, exc, why):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    _refuse_open(monkeypatch, "a.bz2", exc)
    res = restore_folder_backup(backup, targets=tgt)
    assert _files(tgt["wiki_dumps"]) == ["b.bz2"]  # the rest of the category still restores
    assert _files(tgt["osm_regions"]) == ["kenya.osm.pbf"]  # and the next category too
    assert res["unread_total"] == 1 and res["unread_by_why"] == {why: 1}
    assert res["unread"] == [{"category": "wiki_dumps", "rel": "a.bz2", "why": why}]
    assert res["incomplete"] is True and res["stopped"] is False and res["restored"] == 2
    # the system's own words are never kept
    assert "Permission denied" not in json.dumps(res) and "Input/output" not in json.dumps(res)


def test_a_read_that_fails_part_way_leaves_no_partial_file(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    real_fdopen = os.fdopen

    class _Dies:
        def __init__(self, f):
            self._f, self._n = f, 0

        def read(self, n):
            self._n += 1
            if self._n > 1:
                raise OSError(errno.EIO, "Input/output error")
            return self._f.read(1)

        def __getattr__(self, name):
            return getattr(self._f, name)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._f.close()

    def fake(fd, mode="r", *a, **k):
        f = real_fdopen(fd, mode, *a, **k)
        return _Dies(f) if mode == "rb" and _is_a(fd) else f

    def _is_a(fd):
        try:
            return os.readlink(f"/proc/self/fd/{fd}").endswith("a.bz2")
        except OSError:
            return False

    if not Path("/proc/self/fd").exists():
        pytest.skip("needs /proc to tell the two files apart")
    scope_os(monkeypatch, folder_backup, fdopen=fake)
    res = restore_folder_backup(backup, targets=tgt)
    assert res["unread"] == [{"category": "wiki_dumps", "rel": "a.bz2", "why": "read-failed"}]
    # no live file and no temp file: nothing half-copied anywhere in the live folder
    assert _files(tgt["wiki_dumps"]) == ["b.bz2"]


def test_an_existing_live_file_is_never_touched_by_a_failed_read(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    _touch(tgt["wiki_dumps"] / "b.bz2", b"mine")
    _refuse_open(monkeypatch, "a.bz2", OSError(errno.EIO, "Input/output error"))
    res = restore_folder_backup(backup, targets=tgt)
    assert (tgt["wiki_dumps"] / "b.bz2").read_bytes() == b"mine"
    assert res["skipped"] == 1 and res["unread_total"] == 1


def test_a_second_run_restores_exactly_the_files_the_first_could_not(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    with monkeypatch.context() as m:
        _refuse_open(m, "a.bz2", PermissionError(errno.EACCES, "Permission denied"))
        first = restore_folder_backup(backup, targets=tgt)
    assert first["unread_total"] == 1 and first["restored"] == 2
    second = restore_folder_backup(backup, targets=tgt)
    assert second["restored"] == 1 and second["skipped"] == 2 and second["unread_total"] == 0
    assert second["incomplete"] is False
    assert (tgt["wiki_dumps"] / "a.bz2").read_bytes() == b"aaa"


@_WALKS
def test_a_folder_that_cannot_be_listed_is_one_entry_and_the_walk_goes_on(tmp_path, monkeypatch, kind):
    backup = _backup(tmp_path)
    _touch(backup / "wiki_dumps" / "sub" / "c.bz2", b"ccc")
    tgt = _targets(tmp_path)
    _skip_sub(monkeypatch, kind)
    res = restore_folder_backup(backup, targets=tgt)
    assert {"category": "wiki_dumps", "rel": "sub", "why": "folder-unlisted"} in res["unread"]
    assert _files(tgt["wiki_dumps"]) == ["a.bz2", "b.bz2"] and res["incomplete"] is True
    # a folder is counted apart: its files are unknown, so it is never "1 file"
    assert res["unread_folders"] == 1 and res["unread_total"] == 0


@_WALKS
def test_a_folder_that_vanishes_while_being_listed_is_not_counted(tmp_path, monkeypatch, kind):
    backup = _backup(tmp_path)
    _touch(backup / "wiki_dumps" / "sub" / "c.bz2", b"ccc")
    tgt = _targets(tmp_path)
    _skip_sub(monkeypatch, kind, shutil.rmtree)  # gone between the listing and the walk entering it
    res = restore_folder_backup(backup, targets=tgt)
    assert res["unread_folders"] == 0 and res["unread"] == [] and res["incomplete"] is False


def test_a_process_out_of_file_handles_stops_instead_of_marking_every_file(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    _refuse_open(monkeypatch, "a.bz2", OSError(errno.EMFILE, "Too many open files"))
    monkeypatch.setattr(folder_backup, "_process_can_open", lambda: False)
    with pytest.raises(OSError) as e:
        restore_folder_backup(backup, targets=tgt)
    assert not isinstance(e.value, folder_backup.SourceUnreadable)


def test_a_backup_writer_keeps_the_system_error_as_before(tmp_path, monkeypatch):
    src = _touch(tmp_path / "live" / "x.bz2", b"x")
    _refuse_open(monkeypatch, "x.bz2", PermissionError(errno.EACCES, "Permission denied"))
    with pytest.raises(PermissionError) as e:
        folder_backup._atomic_copy(src, tmp_path / "out" / "x.bz2")
    assert not isinstance(e.value, folder_backup.SourceUnreadable)


def test_a_category_folder_that_cannot_be_looked_at_is_counted_and_others_restore(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)
    real = os.lstat

    def fake(path, *a, **k):
        if Path(path) == backup / "wiki_dumps":
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path, *a, **k)

    scope_os(monkeypatch, links, lstat=fake)
    res = restore_folder_backup(backup, targets=tgt)
    assert res["unread"] == [{"category": "wiki_dumps", "rel": "", "why": "folder-unlisted"}]
    assert res["unread_folders"] == 1 and res["unread_total"] == 0 and res["incomplete"] is True
    assert _files(tgt["wiki_dumps"]) == [] and _files(tgt["osm_regions"]) == ["kenya.osm.pbf"]


def test_a_failure_on_the_writing_side_still_stops_the_restore(tmp_path, monkeypatch):
    backup = _backup(tmp_path)
    tgt = _targets(tmp_path)

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")

    scope_os(monkeypatch, folder_backup, replace=full)
    with pytest.raises(OSError) as e:
        restore_folder_backup(backup, targets=tgt)
    assert not isinstance(e.value, folder_backup.SourceUnreadable)
    assert not [p for p in (tgt["wiki_dumps"]).rglob("*") if p.is_file()]  # the temp went with it


def test_the_named_list_is_capped_but_every_reason_is_counted(tmp_path, monkeypatch):
    b = tmp_path / "backup"
    for i in range(7):
        _touch(b / "wiki_dumps" / f"f{i}.bz2", b"z")
    tgt = _targets(tmp_path)
    monkeypatch.setattr(folder_backup, "_PROBLEM_CAP", 3)
    _refuse_open(monkeypatch, ".bz2", PermissionError(errno.EACCES, "Permission denied"))
    res = restore_folder_backup(b, targets=tgt)
    assert res["unread_total"] == 7 and res["unread_by_why"] == {"denied": 7} and len(res["unread"]) == 3


def test_the_count_reaches_the_journal_the_diagnostics_and_the_queue_summary():
    src = (ROOT / "src/backup/folder_backup.py").read_text(encoding="utf-8")
    # The run journal (runlog.end, which Diagnostics reads) keeps the counts, never the names. The storage
    # events journal does not: its row in the Diagnostics zip has no room left for two more numbers per run.
    assert src.count('unread=res.get("unread_total")') == 1
    assert src.count('unread_folders=res.get("unread_folders")') == 1
    q = (ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8")
    for field in ('"unread_total"', '"unread_folders"', '"unread_by_why"', '"unread"'):
        assert field in q


def test_every_new_string_is_a_key_in_all_twelve_catalogues():
    keys = [
        "permission denied", "no longer there", "not a file", "could not be read",
        "Restore incomplete — folders in the backup that could not be listed, so whatever they hold was not restored",
        "Restore incomplete: {n} files not restored, because they could not be read. The rest was restored; run the import again to bring back only these",
    ]
    for f in sorted((ROOT / "src/static/locales").glob("*.json")):
        cat = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert cat.get(k), (f.name, k)
        if f.stem != "en":
            assert "{n}" in cat[keys[-1]], f.name


def test_the_page_says_it_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "restore_unread_r778_node_test.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@_WALKS
def test_running_out_of_file_handles_during_the_walk_stops_too(tmp_path, monkeypatch, kind):
    backup = _backup(tmp_path)
    _touch(backup / "wiki_dumps" / "sub" / "c.bz2", b"ccc")
    _skip_sub(monkeypatch, kind)  # what the walk does with a folder it has no handle left to open
    monkeypatch.setattr(folder_backup, "_process_can_open", lambda: False)
    with pytest.raises(OSError):
        restore_folder_backup(backup, targets=_targets(tmp_path))


_PROBE = """
import os, resource, sys
sys.path.insert(0, sys.argv[1])
from src.backup.folder_backup import _process_can_open
assert _process_can_open() is True
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
held = []
resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard))
try:
    while True:
        held.append(os.open(os.devnull, os.O_RDONLY))
except OSError:
    pass
print(_process_can_open())
"""


@pytest.mark.skipif(os.name == "nt", reason="needs the resource module")
def test_the_probe_itself_answers_false_at_the_file_limit():
    import sys

    r = subprocess.run([sys.executable, "-c", _PROBE, str(ROOT)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


def test_an_unread_name_that_is_not_utf8_still_renders_as_json(tmp_path, monkeypatch):
    # A foreign drive can hold a name that is not valid UTF-8; it comes back with a lone surrogate, which
    # the status responses (UTF-8 JSON) cannot encode. The result must still encode, with the byte replaced.
    backup = _backup(tmp_path)
    bad = os.fsdecode(b"x\xff.bin")
    _touch(backup / "wiki_dumps" / bad)
    tgt = _targets(tmp_path)
    _refuse_open(monkeypatch, bad, PermissionError(errno.EACCES, "Permission denied"))
    res = restore_folder_backup(backup, targets=tgt)
    assert res["unread_total"] == 1 and res["incomplete"] is True
    json.dumps(res, ensure_ascii=False).encode("utf-8")  # raised UnicodeEncodeError before
    assert res["unread"][0]["rel"] == "x�.bin"


def test_the_closed_dialog_toast_never_calls_an_incomplete_restore_complete():
    js = (ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    i = js.index('toast(t("Import complete."))')
    before = js[i - 400 : i]
    assert "s2.incomplete" in before and 'toast(t("Import incomplete — some files were not restored")' in before
