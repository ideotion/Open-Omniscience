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

import os
import shutil
from pathlib import Path

import pytest

from src.backup import folder_backup
from src.backup.folder_backup import BackupItem, verify_folder_backup, write_folder_backup

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
    real = folder_backup._sha256_file

    def _spy(p, *a, **k):
        read.append(str(p))
        return real(p, *a, **k)

    monkeypatch.setattr(folder_backup, "_sha256_file", _spy)
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["link_not_checked"] == 1 and rep["summary"]["ok"] == 1
    prob = [p for p in rep["problems"] if p["status"] == "link_not_checked"]
    assert prob == [{"category": "wiki_dumps", "rel": "enwiki/a.bz2", "status": "link_not_checked",
                     "why": "a link, not checked", "why_i18n": [{"t": "a link, not checked", "v": {}}]}]
    assert not any("wiki_dumps" in r for r in read)  # never hashed through the link
    assert rep["links"].startswith("Files not checked: 1. ")
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
