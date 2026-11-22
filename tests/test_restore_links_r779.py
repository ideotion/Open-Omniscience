"""R779: a backup never pulls files from outside itself, and a restore never writes through a link.

A category folder that is a link (``wiki_dumps`` -> some other place on the machine) used to be FOLLOWED
by both the import scan and the restore, which copied that place's files into the live data folder. It is
now refused, never followed, listed by the scan with its reason, and reported by the restore as incomplete.
The destination side gets the same rule: no link between the live folder and the file, and a leftover
``.oopart`` planted as a link is removed rather than written through.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup.folder_backup import SourceChanged, _atomic_copy, restore_folder_backup
from src.backup.import_scan import SCAN_LINKED_CATEGORY, scan_import_folder
from src.backup.links import is_link, link_on_the_way, stays_inside

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs POSIX symlinks")


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _targets(tmp: Path) -> dict[str, Path]:
    return {c: tmp / "live" / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")}


def _files(d: Path) -> list[str]:
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) if d.exists() else []


def test_a_category_folder_that_is_a_link_is_refused_never_followed(tmp_path):
    secret = _touch(tmp_path / "elsewhere" / "private.txt", b"not yours")
    backup = tmp_path / "backup"
    _touch(backup / "osm_regions" / "kenya.osm.pbf", b"map")
    backup.mkdir(exist_ok=True)
    os.symlink(secret.parent, backup / "wiki_dumps")
    tgt = _targets(tmp_path)
    res = restore_folder_backup(backup, targets=tgt)
    assert _files(tgt["wiki_dumps"]) == []  # nothing from the other place reached the live folder
    assert _files(tgt["osm_regions"]) == ["kenya.osm.pbf"]  # the rest still restores
    assert res["refused_categories"] == ["wiki_dumps"] and res["incomplete"] is True
    assert secret.read_bytes() == b"not yours"


def test_the_backup_folder_the_person_picked_may_itself_be_a_link(tmp_path):
    real = tmp_path / "drive" / "backup"
    _touch(real / "wiki_dumps" / "en.xml.bz2", b"dump")
    picked = tmp_path / "shortcut"
    os.symlink(real, picked)
    tgt = _targets(tmp_path)
    res = restore_folder_backup(picked, targets=tgt)
    assert res["restored"] == 1 and res["refused_categories"] == [] and res["incomplete"] is False
    assert _files(tgt["wiki_dumps"]) == ["en.xml.bz2"]


def test_a_folder_link_below_a_category_is_not_followed(tmp_path):
    _touch(tmp_path / "elsewhere" / "private.txt")
    backup = tmp_path / "backup"
    _touch(backup / "models" / "blobs" / "sha256-a", b"a")
    os.symlink(tmp_path / "elsewhere", backup / "models" / "sneaky")
    tgt = _targets(tmp_path)
    res = restore_folder_backup(backup, targets=tgt)
    assert _files(tgt["models"]) == ["blobs/sha256-a"]
    assert res["refused_symlinks"] == 1


def test_the_restore_never_writes_through_a_link_in_the_live_folder(tmp_path):
    backup = tmp_path / "backup"
    _touch(backup / "osm_regions" / "africa" / "kenya.osm.pbf", b"map")
    _touch(backup / "osm_regions" / "chad.osm.pbf", b"map2")
    outside = tmp_path / "outside"
    outside.mkdir()
    tgt = _targets(tmp_path)
    tgt["osm_regions"].mkdir(parents=True)
    os.symlink(outside, tgt["osm_regions"] / "africa")
    res = restore_folder_backup(backup, targets=tgt)
    assert list(outside.iterdir()) == []  # nothing written through the link
    assert res["refused_dest_links"] == 1 and res["incomplete"] is True
    assert res["restored"] == 1  # the file with no link on its way still lands


def test_a_live_folder_the_person_moved_with_a_link_still_receives_files(tmp_path):
    backup = tmp_path / "backup"
    _touch(backup / "wiki_dumps" / "en.xml.bz2", b"dump")
    moved = tmp_path / "big-drive" / "wiki_dumps"
    moved.mkdir(parents=True)
    tgt = _targets(tmp_path)
    tgt["wiki_dumps"].parent.mkdir(parents=True)
    os.symlink(moved, tgt["wiki_dumps"])
    res = restore_folder_backup(backup, targets=tgt)
    assert res["restored"] == 1 and res["refused_dest_links"] == 0
    assert _files(moved) == ["en.xml.bz2"]


def test_a_planted_part_file_link_is_removed_not_written_through(tmp_path):
    victim = _touch(tmp_path / "victim.txt", b"keep me")
    src = _touch(tmp_path / "src.bin", b"payload")
    dst = tmp_path / "live" / "file.bin"
    dst.parent.mkdir()
    os.symlink(victim, dst.with_name(dst.name + ".oopart"))
    assert _atomic_copy(src, dst) is True
    assert victim.read_bytes() == b"keep me"
    assert dst.read_bytes() == b"payload" and not is_link(dst)


def test_a_member_swapped_after_its_check_is_refused_not_read(tmp_path):
    checked = _touch(tmp_path / "backup" / "wiki_dumps" / "a.bz2", b"dump")
    other = _touch(tmp_path / "elsewhere" / "s.txt", b"secret")
    dst = tmp_path / "live" / "a.bz2"
    dst.parent.mkdir()
    with pytest.raises(SourceChanged):  # same name, another file: refused by device and inode
        _atomic_copy(checked, dst, nofollow_src=True, expect=os.lstat(other))
    checked.unlink()
    os.symlink(other, checked)
    with pytest.raises(SourceChanged):  # the name became a link: not opened
        _atomic_copy(checked, dst, nofollow_src=True, expect=os.lstat(other))
    assert not dst.exists() and not (tmp_path / "live" / "a.bz2.oopart").exists()


def test_a_member_link_alone_makes_the_restore_incomplete(tmp_path):
    _touch(tmp_path / "elsewhere" / "s.txt")
    backup = tmp_path / "backup"
    _touch(backup / "wiki_dumps" / "en.xml.bz2", b"dump")
    os.symlink(tmp_path / "elsewhere" / "s.txt", backup / "wiki_dumps" / "fr.xml.bz2")
    res = restore_folder_backup(backup, targets=_targets(tmp_path))
    assert res["restored"] == 1 and res["refused_symlinks"] == 1 and res["incomplete"] is True


def test_the_scan_and_the_restore_count_the_same_links(tmp_path):
    _touch(tmp_path / "elsewhere" / "x" / "1")
    _touch(tmp_path / "elsewhere" / "x" / "2")
    backup = tmp_path / "backup"
    _touch(backup / "models" / "blobs" / "sha256-a")
    os.symlink(tmp_path / "elsewhere" / "x", backup / "models" / "dirlink")
    os.symlink(tmp_path / "elsewhere" / "x" / "1", backup / "models" / "filelink")
    (backup / "models" / "work.oopart").mkdir()
    _touch(backup / "models" / "work.oopart" / "inside")
    scan = scan_import_folder(backup)["found"]["blobs"]["models"]
    res = restore_folder_backup(backup, targets=_targets(tmp_path))
    assert scan["count"] == res["restored"] == 2  # a plain folder named .oopart is entered by both
    assert scan["refused_links"] == res["refused_symlinks"] == 2


def test_the_scan_lists_a_linked_category_with_its_reason_and_counts_nothing(tmp_path):
    _touch(tmp_path / "elsewhere" / "a.bz2", b"aaaa")
    backup = tmp_path / "backup"
    _touch(backup / "osm_regions" / "kenya.osm.pbf")
    os.symlink(tmp_path / "elsewhere", backup / "wiki_dumps")
    f = scan_import_folder(backup)["found"]
    assert f["blobs"]["wiki"] == {"count": 0, "bytes": 0, "linked": 1}
    root = f["blob_roots"][0]
    assert root["wiki"]["reason"] == SCAN_LINKED_CATEGORY and "wiki_dumps" in root["categories"]
    assert f["blobs"]["maps"]["count"] == 1


def test_a_manifest_never_stands_in_for_a_linked_category(tmp_path):
    _touch(tmp_path / "elsewhere" / "a.bz2")
    backup = tmp_path / "backup"
    _touch(backup / "oo-folder-backup.json", json.dumps(
        {"categories": {"wiki_dumps": [{"rel": "a.bz2", "size": 1}]}}).encode())
    os.symlink(tmp_path / "elsewhere", backup / "wiki_dumps")
    wiki = scan_import_folder(backup)["found"]["blobs"]["wiki"]
    assert wiki["count"] == 0 and wiki["linked"] == 1  # the restore will not restore it, so the scan does not count it


def test_the_link_helpers(tmp_path):
    base = tmp_path / "base"
    (base / "a").mkdir(parents=True)
    os.symlink(tmp_path, base / "a" / "up")
    assert is_link(base / "a" / "up") and not is_link(base / "a") and not is_link(base / "missing")
    assert link_on_the_way(base, Path("a/up/x")) and not link_on_the_way(base, Path("a/new/x"))
    real = os.path.realpath(base)
    assert stays_inside(base / "a" / "f", real) and not stays_inside(base / "a" / "up" / "f", real)
    assert not stays_inside(tmp_path / "base-sibling" / "f", real)  # a prefix is not containment


def test_every_new_string_is_a_key_in_all_twelve_catalogues():
    src = (ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    keys = [SCAN_LINKED_CATEGORY, "a link, not restored", "Import incomplete — some files were not restored",
            "Not restored — links inside the backup, which a restore never follows"]
    keys += [line.split('t("', 1)[1].split('")', 1)[0] for line in src.splitlines()
             if 't("Restore incomplete — ' in line]
    assert len(keys) == 6
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        cat = json.loads(p.read_text(encoding="utf-8"))
        missing = [k for k in keys if not cat.get(k)]
        assert not missing, (p.name, missing)


def test_the_page_says_it_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "restore_links_r779_node_test.js")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
