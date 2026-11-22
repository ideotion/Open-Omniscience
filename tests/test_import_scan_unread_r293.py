"""Row 293: the backup import scan never crashes on, nor silently undercounts, what it cannot read.

``_dir_totals`` summed ``p.stat()`` over ``rglob`` with nothing catching an error, so one file in a backup's
wiki/maps/models folder the app may not stat failed ``/api/backup/import-scan`` with a 500 and listed nothing
(the readable corpus volumes included); a subfolder it could not list was skipped silently; and a link was
followed and counted although a restore refuses every link. The scan now counts exactly what
``restore_folder_backup`` restores, carries ``unread_entries`` with a reason when it was refused something,
``refused_links`` for links, and ``unread_folders`` for folders its own walk could not enter.
tests/import_scan_unread_r293_node_test.js runs the checklist row that shows it.

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

import src.backup.import_scan as import_scan
from src.backup.folder_backup import restore_folder_backup
from src.backup.import_scan import (
    SCAN_LINKS,
    SCAN_UNREAD,
    SCAN_UNSIZED,
    _dir_totals,
    scan_import_folder,
)
from tests.os_scope import scope_os

ROOT = Path(__file__).resolve().parents[1]


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _refuse_lstat(monkeypatch, *names: str, exc=PermissionError, code=errno.EACCES) -> None:
    real = os.lstat

    def fake(p, *a, **kw):
        if os.path.basename(str(p)) in names:
            raise exc(code, "refused", str(p))
        return real(p, *a, **kw)

    scope_os(monkeypatch, import_scan, lstat=fake)


def test_a_file_it_may_not_stat_no_longer_fails_the_scan(tmp_path, monkeypatch):
    _touch(tmp_path / "volumes.json", b"{}")
    _touch(tmp_path / "vol-00000.ooenc")
    _touch(tmp_path / "wiki_dumps" / "a.bz2", b"aaa")
    _touch(tmp_path / "wiki_dumps" / "locked.bz2", b"bbbbbb")
    _refuse_lstat(monkeypatch, "locked.bz2")
    f = scan_import_folder(tmp_path)["found"]
    assert f["corpus"][0]["volumes"] == 1  # the rest of the scan is still there
    wiki = f["blobs"]["wiki"]
    assert wiki["count"] == 1 and wiki["bytes"] == 3
    assert wiki["unread_entries"] == 1 and wiki["reason"] == SCAN_UNREAD
    root = f["blob_roots"][0]
    assert root["wiki"]["unread_entries"] == 1 and root["categories"] == ["wiki_dumps"]


def test_a_category_folder_it_cannot_list_is_still_listed_as_unread(tmp_path, monkeypatch):
    _touch(tmp_path / "osm_regions" / "kenya.osm.pbf")
    real_walk = os.walk

    def fake_walk(top, onerror=None, followlinks=False):
        if str(top).endswith("osm_regions"):
            onerror(PermissionError(errno.EACCES, "refused", str(top)))
            return
        yield from real_walk(top, onerror=onerror, followlinks=followlinks)

    scope_os(monkeypatch, import_scan, walk=fake_walk)
    maps = scan_import_folder(tmp_path)["found"]["blobs"]["maps"]
    assert maps == {"count": 0, "bytes": 0, "unread_entries": 1, "reason": SCAN_UNREAD}


def test_an_unlistable_category_the_manifest_declares_shows_the_manifest_totals(tmp_path, monkeypatch):
    _touch(tmp_path / "oo-folder-backup.json", json.dumps(
        {"categories": {"osm_regions": [{"rel": "kenya.osm.pbf", "size": 40}, {"rel": "chad.osm.pbf", "size": 2}]}}
    ).encode())
    _touch(tmp_path / "osm_regions" / "kenya.osm.pbf")
    real_walk = os.walk

    def fake_walk(top, onerror=None, followlinks=False):
        if str(top).endswith("osm_regions"):
            onerror(PermissionError(errno.EACCES, "refused", str(top)))
            return
        yield from real_walk(top, onerror=onerror, followlinks=followlinks)

    scope_os(monkeypatch, import_scan, walk=fake_walk)
    maps = scan_import_folder(tmp_path)["found"]["blobs"]["maps"]
    assert maps["count"] == 2 and maps["bytes"] == 42  # the manifest's word, never the 0 it read
    assert maps["unread_entries"] == 1 and maps["reason"] == SCAN_UNREAD


def test_a_folder_it_may_not_look_at_is_refused_with_a_reason_not_a_crash(tmp_path, monkeypatch):
    target = tmp_path / "backup"
    target.mkdir()

    def refuse(self, *a, **kw):
        raise PermissionError(errno.EACCES, "refused", str(self))

    monkeypatch.setattr(import_scan.Path, "is_dir", refuse)
    with pytest.raises(ValueError, match="could not be read"):
        scan_import_folder(target)


def test_a_file_that_vanished_mid_scan_is_gone_not_unread(tmp_path, monkeypatch):
    _touch(tmp_path / "models" / "blobs" / "sha256-a")
    _touch(tmp_path / "models" / "blobs" / "sha256-gone")
    _refuse_lstat(monkeypatch, "sha256-gone", exc=FileNotFoundError, code=errno.ENOENT)
    assert _dir_totals(tmp_path / "models") == {"count": 1, "bytes": 1}


def test_the_scan_counts_what_restore_restores(tmp_path):
    """Links (to a file and to a folder) and copies in progress: the scan's count equals restore's."""
    src = tmp_path / "backup"
    _touch(src / "wiki_dumps" / "a.bz2", b"aa")
    _touch(src / "wiki_dumps" / "sub" / "b.bz2", b"bbb")
    _touch(src / "wiki_dumps" / "c.bz2.oopart", b"partial")
    outside = _touch(tmp_path / "outside" / "secret.txt", b"s" * 50)
    try:
        (src / "wiki_dumps" / "file-link").symlink_to(outside)
        (src / "wiki_dumps" / "dir-link").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted here")
    tot = _dir_totals(src / "wiki_dumps")
    assert tot == {"count": 2, "bytes": 5, "refused_links": 2}
    live = tmp_path / "live"
    got = restore_folder_backup(src, categories=["wiki_dumps"], targets={"wiki_dumps": live})
    assert got["restored"] == tot["count"]
    assert got["refused_symlinks"] == tot["refused_links"]
    assert sorted(p.name for p in live.rglob("*") if p.is_file()) == ["a.bz2", "b.bz2"]


def test_folders_the_scan_walk_could_not_enter_are_counted(tmp_path, monkeypatch):
    _touch(tmp_path / "a.eml")
    (tmp_path / "locked").mkdir()
    real_walk = os.walk

    def fake_walk(top, onerror=None, followlinks=False):
        for dirpath, dirs, files in real_walk(top, followlinks=followlinks):
            if dirpath.endswith("locked"):
                onerror(PermissionError(errno.EACCES, "refused", dirpath))
                continue
            yield dirpath, dirs, files

    scope_os(monkeypatch, import_scan, walk=fake_walk)
    f = scan_import_folder(tmp_path)["found"]
    assert f["unread_folders"] == 1 and f["newsletters"]["count"] == 1


def test_a_clean_folder_carries_none_of_the_new_fields(tmp_path):
    _touch(tmp_path / "wiki_dumps" / "a.bz2")
    _touch(tmp_path / "open-omniscience-1.oobackup", b"12345")
    f = scan_import_folder(tmp_path)["found"]
    # This hand-built folder has no manifest, so its file is counted as not listed (R780).
    assert {k: f["blobs"]["wiki"][k] for k in ("count", "bytes")} == {"count": 1, "bytes": 1}
    assert f["blobs"]["wiki"]["unlisted"] == 1
    assert not {"unread_entries", "refused_links", "refused_layout"} & set(f["blobs"]["wiki"])
    assert "unread_folders" not in f
    assert f["legacy_backup"][0]["bytes"] == 5 and "reason" not in f["legacy_backup"][0]


def test_a_legacy_file_whose_size_cannot_be_read_is_null_not_zero(tmp_path, monkeypatch):
    _touch(tmp_path / "open-omniscience-1.oobackup", b"12345")
    real = os.stat

    def fake_stat(p, *a, **kw):
        if os.path.basename(str(p)) == "open-omniscience-1.oobackup":
            raise PermissionError(errno.EACCES, "refused", str(p))
        return real(p, *a, **kw)

    scope_os(monkeypatch, import_scan, stat=fake_stat)
    item = scan_import_folder(tmp_path)["found"]["legacy_backup"][0]
    assert item["bytes"] is None and item["reason"] == SCAN_UNSIZED


def test_every_reason_is_a_key_in_all_twelve_catalogues():
    keys = [SCAN_UNREAD, SCAN_LINKS, SCAN_UNSIZED, "at least",
            "1 folder here could not be read, so anything inside it is not listed.",
            "{n} folders here could not be read, so anything inside them is not listed."]
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        cat = json.loads(p.read_text(encoding="utf-8"))
        missing = [k for k in keys if not cat.get(k)]
        assert not missing, (p.name, missing)


def test_the_checklist_row_runs_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "import_scan_unread_r293_node_test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
