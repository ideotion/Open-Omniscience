"""R791 (row 318): Verify never says OK on a folder backup a restore would leave incomplete because of a link.

A restore never follows a link: a category folder, a folder below it or a file that is a link is left out (R779/R783),
and the restore reads "Restore incomplete". Verify used to resolve the category folder and hash through it, so it could
report every file sound on a backup whose restore refuses them. Now such a file is "a link, not checked": it is not read,
it counts as a failure, and the verdict is never OK. Each test plants a link to a real copy of the files outside the
backup, so the bytes WOULD match if Verify read through the link.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from src.backup import folder_backup
from src.backup.folder_backup import (
    MANIFEST_NAME,
    BackupItem,
    verify_folder_backup,
    write_folder_backup,
)

posix_only = pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")


def _backup(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "enwiki").mkdir(parents=True)
    (src / "enwiki" / "a.bz2").write_bytes(b"a" * 100)
    (src / "c.pbf").write_bytes(b"c" * 200)
    dest = tmp_path / "dest"
    write_folder_backup(
        dest,
        [
            BackupItem("wiki_dumps", "enwiki/a.bz2", src / "enwiki" / "a.bz2", 100),
            BackupItem("osm_regions", "europe.pbf", src / "c.pbf", 200),
        ],
    )
    assert verify_folder_backup(dest)["ok"] is True
    return dest


def _swap_for_link(path: Path, outside: Path) -> None:
    """Move ``path`` (a folder or a file) out of the backup and leave a link to it in its place."""
    shutil.move(str(path), str(outside))
    os.symlink(outside, path)


@posix_only
def test_a_linked_category_folder_is_not_checked_and_fails_the_verdict(tmp_path, monkeypatch):
    dest = _backup(tmp_path)
    _swap_for_link(dest / "wiki_dumps", tmp_path / "elsewhere")
    read: list[str] = []
    real_path, real_fd = folder_backup._sha256_file, folder_backup._open_member_fd

    def _spy(p, *a, **k):
        read.append(str(p))
        return real_path(p, *a, **k)

    def _spy_fd(root, cat, cat_st, rel):
        read.append(f"{cat}/{rel}")
        return real_fd(root, cat, cat_st, rel)

    monkeypatch.setattr(folder_backup, "_sha256_file", _spy)
    monkeypatch.setattr(folder_backup, "_open_member_fd", _spy_fd)
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["link_not_checked"] == 1 and rep["summary"]["ok"] == 1
    prob = [p for p in rep["problems"] if p["status"] == "link_not_checked"]
    assert prob == [{"category": "wiki_dumps", "rel": "enwiki/a.bz2", "status": "link_not_checked",
                     "why": "a link, not checked", "why_i18n": [{"t": "a link, not checked", "v": {}}]}]
    assert not any("wiki_dumps" in r for r in read)  # never opened through the link
    assert any("osm_regions" in r for r in read)  # the spy does see a read
    assert rep["links"].startswith("Not checked: 1. ")
    assert rep["links_i18n"][0]["v"] == {"n": 1}


@posix_only
def test_a_linked_folder_below_the_category_and_a_linked_file_are_not_checked(tmp_path):
    dest = _backup(tmp_path)
    _swap_for_link(dest / "wiki_dumps" / "enwiki", tmp_path / "elsewhere-dir")
    _swap_for_link(dest / "osm_regions" / "europe.pbf", tmp_path / "elsewhere.pbf")
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["link_not_checked"] == 2 and rep["summary"]["ok"] == 0


@posix_only
def test_verify_and_restore_refuse_the_same_linked_category(tmp_path):
    """The point of R791: what restore leaves out, verify never calls verified."""
    dest = _backup(tmp_path)
    _swap_for_link(dest / "wiki_dumps", tmp_path / "elsewhere")
    targets = {"wiki_dumps": tmp_path / "live-wiki", "osm_regions": tmp_path / "live-osm"}
    res = folder_backup.restore_folder_backup(dest, categories=["wiki_dumps", "osm_regions"], targets=targets)
    assert "wiki_dumps" in res["refused_categories"] and res["incomplete"] is True
    assert verify_folder_backup(dest)["ok"] is False


def test_a_backup_without_links_still_verifies_and_carries_no_links_line(tmp_path):
    rep = verify_folder_backup(_backup(tmp_path))
    assert rep["ok"] is True and rep["summary"]["link_not_checked"] == 0
    assert "links" not in rep


@posix_only
def test_the_run_records_count_a_link_not_checked_as_a_mismatch(tmp_path):
    """The run journal and the storage-events record read ``_verify_counts``: a failing verdict never sits beside zero."""
    dest = _backup(tmp_path)
    _swap_for_link(dest / "wiki_dumps", tmp_path / "elsewhere")
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert folder_backup._verify_counts(rep) == (rep["files_checked"], 1)


def test_a_member_on_another_device_than_its_category_is_not_checked(tmp_path, monkeypatch):
    """Restore refuses a member whose device differs from its category folder's (a mount point, a FUSE folder)."""
    dest = _backup(tmp_path)
    member = os.fspath(dest / "osm_regions" / "europe.pbf")

    class _OtherDevice:  # this module's own view of os, never the process's (R351)
        def __getattr__(self, name):
            return getattr(os, name)

        @staticmethod
        def lstat(path, *a, **k):
            st = os.lstat(path, *a, **k)
            if os.fspath(path) == member:
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 1, *tuple(st)[3:]))
            return st

    monkeypatch.setattr(folder_backup, "os", _OtherDevice())
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["link_not_checked"] == 1
    assert [p["rel"] for p in rep["problems"]] == ["europe.pbf"]


def _unsigned(dest: Path, edit) -> None:
    """Edit the manifest as an older, unsigned backup would carry it, so the signature is not what fails."""
    m = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    m.pop("signature", None)
    edit(m)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


@pytest.mark.parametrize("rel", [
    "enwiki/../enwiki/a.bz2", "./enwiki/a.bz2", "enwiki//a.bz2", "enwiki\\a.bz2", "enwiki/a.bz2\x00", "/enwiki/a.bz2", "",
])
def test_a_name_that_is_not_a_plain_member_name_is_refused_by_its_name(tmp_path, rel):
    """A ``..`` that resolves back inside the folder could lead the look past a link on its way: refused by
    the name alone, never resolved, and a NUL never raises."""
    dest = _backup(tmp_path)
    _unsigned(dest, lambda m: m["categories"]["wiki_dumps"][0].update(rel=rel))
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["traversal_refused"] == 1


@posix_only
def test_a_dotdot_way_through_a_link_is_refused_and_never_read(tmp_path, monkeypatch):
    dest = _backup(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copy(dest / "wiki_dumps" / "enwiki" / "a.bz2", outside / "a.bz2")
    os.symlink(outside, dest / "wiki_dumps" / "hop")
    _unsigned(dest, lambda m: m["categories"]["wiki_dumps"][0].update(rel="hop/../enwiki/a.bz2"))
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False and rep["summary"]["traversal_refused"] == 1


def test_a_file_that_cannot_be_read_is_unreadable_never_a_crash_nor_a_pass(tmp_path, monkeypatch):
    dest = _backup(tmp_path)

    def _fails(*a, **k):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(folder_backup, "_hash_fd", _fails)
    monkeypatch.setattr(folder_backup, "_sha256_file", _fails)
    rep = verify_folder_backup(dest)  # must not raise
    assert rep["ok"] is False
    assert rep["summary"]["unreadable"] == 2
    assert folder_backup._verify_counts(rep) == (2, 2)


@posix_only
def test_a_link_no_entry_names_still_fails_the_verdict(tmp_path):
    """Restore counts every link it meets on its walk, listed or not: so does Verify, without following it."""
    dest = _backup(tmp_path)
    (tmp_path / "secret").write_bytes(b"s")
    os.symlink(tmp_path / "secret", dest / "wiki_dumps" / "enwiki" / "extra")
    os.symlink(tmp_path / "secret", dest / "wiki_dumps" / ("skip" + folder_backup._PART_SUFFIX))
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["link_not_checked"] == 1 and rep["summary"]["ok"] == 2
    assert [p for p in rep["problems"] if p["status"] == "link_not_checked"] == [
        {"category": "wiki_dumps", "rel": "enwiki/extra", "status": "link_not_checked",
         "why": "a link, not in the manifest", "why_i18n": [{"t": "a link, not in the manifest", "v": {}}]}
    ]
    targets = {"wiki_dumps": tmp_path / "live-wiki", "osm_regions": tmp_path / "live-osm"}
    res = folder_backup.restore_folder_backup(dest, categories=["wiki_dumps", "osm_regions"], targets=targets)
    assert res["incomplete"] is True  # the two agree


@pytest.mark.skipif(not folder_backup._FD_RELATIVE, reason="the handle-relative open is POSIX only")
def test_a_folder_swapped_for_a_link_after_the_look_is_refused_at_the_open(tmp_path, monkeypatch):
    """The look said plain; the folder is a link by the time of the open. The open refuses it, by handle,
    and the file it leads to is never read. The link points inside the backup, so the path check that
    resolves it passes too: only the open stands between the race and the read."""
    dest = _backup(tmp_path)
    _swap_for_link(dest / "wiki_dumps" / "enwiki", dest / "wiki_dumps" / "moved")
    monkeypatch.setattr(folder_backup, "_member_link", lambda *a, **k: None)
    hashed: list[int] = []
    real = folder_backup._hash_fd
    monkeypatch.setattr(folder_backup, "_hash_fd", lambda fd: hashed.append(fd) or real(fd))
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    probs = {p["rel"]: p["status"] for p in rep["problems"]}
    assert probs["enwiki/a.bz2"] == "link_not_checked"
    assert len(hashed) == 1  # only the osm file
