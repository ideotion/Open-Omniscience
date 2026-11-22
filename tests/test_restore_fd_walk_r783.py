"""R783: on a system that can, a folder restore walks the backup BY FOLDER HANDLE and opens every file
one name at a time, relative to the folder before it, never following a link (``os.fwalk`` +
``openat`` with ``O_NOFOLLOW``). A folder swapped for a link after the checks is then refused by the
system at the open itself, where R779 could only narrow the window. Where the system cannot, R779's
path is kept, decided by what the system offers and never by its name; both paths refuse the same
things with the same counts (R779's own tests run unchanged).
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path, PurePosixPath

import pytest

from src.backup import folder_backup
from src.backup.folder_backup import SourceChanged, restore_folder_backup
from tests.os_scope import scope_os

ROOT = Path(__file__).resolve().parents[1]
needs_links = pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="POSIX links")


def _touch(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _setup(tmp: Path) -> tuple[Path, Path, dict[str, Path]]:
    backup = tmp / "backup"
    _touch(backup / "wiki_dumps" / "a.bz2", b"aaa")
    _touch(backup / "wiki_dumps" / "sub" / "c.bz2", b"ccc")
    outside = tmp / "outside"
    _touch(outside / "c.bz2", b"SECRET")
    targets = {c: tmp / "live" / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")}
    return backup, outside, targets


def _swap(backup: Path, outside: Path) -> None:
    sub = backup / "wiki_dumps" / "sub"
    sub.rename(backup.parent / "moved_away")
    os.symlink(outside, sub)


def _live_bytes(live: Path) -> dict[str, bytes]:
    return {p.relative_to(live).as_posix(): p.read_bytes() for p in sorted(live.rglob("*")) if p.is_file()}


def _kinds():
    return [pytest.param(True, id="fd"), pytest.param(False, id="path")]


def test_the_capability_is_decided_by_what_the_system_offers_not_its_name():
    src = (ROOT / "src" / "backup" / "folder_backup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "_FD_RELATIVE" for t in n.targets))
    text = ast.get_source_segment(src, node) or ""
    for name in ("fwalk", "supports_dir_fd", "O_NOFOLLOW", "O_DIRECTORY"):
        assert name in text
    for name in ("os.name", "sys.platform", "platform."):
        assert name not in text
    if hasattr(os, "fwalk") and os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        assert folder_backup._FD_RELATIVE is True  # this system can: the new path is the one tested here


@needs_links
@pytest.mark.parametrize("fd", _kinds())
def test_a_folder_swapped_for_a_link_after_the_checks_is_refused_at_the_open(tmp_path, monkeypatch, fd):
    if fd and not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    monkeypatch.setattr(folder_backup, "_FD_RELATIVE", fd)
    backup, outside, tgt = _setup(tmp_path)
    real = folder_backup.link_on_the_way
    done: list[bool] = []

    def swapping(root, rel):
        out = real(root, rel)
        if not done and Path(root) == backup and Path(rel).name == "sub":
            _swap(backup, outside)  # after every check by path, before the open
            done.append(True)
        return out

    monkeypatch.setattr(folder_backup, "link_on_the_way", swapping)
    res = restore_folder_backup(backup, targets=tgt)
    assert done, "the swap never ran: the test did not reach the window it is about"
    assert _live_bytes(tgt["wiki_dumps"]) == {"a.bz2": b"aaa"}
    assert res["refused_symlinks"] == 1 and res["incomplete"] is True and res["restored"] == 1
    assert res["unread_total"] == 0 and res["unread"] == []


@needs_links
@pytest.mark.parametrize("fd", _kinds())
def test_a_folder_swapped_for_a_link_mid_walk_is_never_entered(tmp_path, monkeypatch, fd):
    if fd and not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    monkeypatch.setattr(folder_backup, "_FD_RELATIVE", fd)
    backup, outside, tgt = _setup(tmp_path)
    swapped: list[bool] = []

    if fd:
        real_fwalk = os.fwalk

        def fake_fwalk(top=".", topdown=True, onerror=None, *, follow_symlinks=False, dir_fd=None):
            for item in real_fwalk(top, topdown, onerror, follow_symlinks=follow_symlinks, dir_fd=dir_fd):
                if not swapped:
                    _swap(backup, outside)  # the category folder is listed; "sub" is about to be looked at
                    swapped.append(True)
                yield item

        scope_os(monkeypatch, folder_backup, fwalk=fake_fwalk)
    else:
        real_walk = os.walk

        def fake_walk(top, topdown=True, onerror=None, followlinks=False):
            for item in real_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
                if not swapped:
                    _swap(backup, outside)
                    swapped.append(True)
                yield item

        scope_os(monkeypatch, folder_backup, walk=fake_walk)
    res = restore_folder_backup(backup, targets=tgt)
    assert swapped
    assert _live_bytes(tgt["wiki_dumps"]) == {"a.bz2": b"aaa"}
    assert res["refused_symlinks"] == 1 and res["incomplete"] is True


@needs_links
def test_the_open_itself_refuses_a_link_on_the_way(tmp_path):
    if not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    backup, outside, _ = _setup(tmp_path)
    cat_st = os.lstat(backup / "wiki_dumps")
    member = PurePosixPath("sub/c.bz2")
    fd = folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, member)
    try:
        assert os.read(fd, 16) == b"ccc"
    finally:
        os.close(fd)
    _swap(backup, outside)
    with pytest.raises(SourceChanged):
        folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, member)
    # the file's own name a link: refused the same way
    os.unlink(backup / "wiki_dumps" / "sub")
    _touch(backup / "wiki_dumps" / "sub" / "x", b"")
    os.symlink(outside / "c.bz2", backup / "wiki_dumps" / "sub" / "c.bz2")
    with pytest.raises(SourceChanged):
        folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, member)


@needs_links
def test_a_category_folder_replaced_after_the_walk_is_refused(tmp_path):
    if not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    backup, _, _ = _setup(tmp_path)
    cat_st = os.lstat(backup / "wiki_dumps")
    (backup / "wiki_dumps").rename(tmp_path / "old_cat")
    _touch(backup / "wiki_dumps" / "a.bz2", b"other")
    with pytest.raises(SourceChanged):
        folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, PurePosixPath("a.bz2"))


def test_without_the_capability_the_path_checks_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_backup, "_FD_RELATIVE", False)

    def never(*a, **k):
        raise AssertionError("the walk by folder handle ran without the capability")

    monkeypatch.setattr(folder_backup, "_open_member_fd", never)
    scope_os(monkeypatch, folder_backup, fwalk=never)
    backup, _, tgt = _setup(tmp_path)
    res = restore_folder_backup(backup, targets=tgt)
    assert res["restored"] == 2 and res["incomplete"] is False
    assert _live_bytes(tgt["wiki_dumps"]) == {"a.bz2": b"aaa", "sub/c.bz2": b"ccc"}


def test_no_handle_is_left_open(tmp_path):
    if not folder_backup._FD_RELATIVE or not os.path.isdir("/proc/self/fd"):
        pytest.skip("needs the walk by folder handle and /proc")
    backup, _, tgt = _setup(tmp_path)
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(3):
        restore_folder_backup(backup, targets=tgt)
    assert len(os.listdir("/proc/self/fd")) <= before


def test_the_help_keeps_the_windows_limit_and_drops_the_posix_one():
    manuals = {"en": ROOT / "docs" / "USER_MANUAL.md"}
    manuals.update({p.parent.name: p for p in (ROOT / "docs" / "i18n").glob("*/USER_MANUAL.md")})
    assert len(manuals) == 12
    for lang, f in manuals.items():
        text = f.read_text(encoding="utf-8")
        # the limit sentence now names both halves: the closed one (Linux, macOS) and the stated one (Windows)
        line = next((ln for ln in text.splitlines() if "Linux" in ln and "macOS" in ln and "OneDrive" in ln), None)
        assert line is not None, lang + ": the R783 limit sentence is missing"
        assert line.count("Windows") >= 2, lang + ": the Windows limit is no longer stated"
    en = manuals["en"].read_text(encoding="utf-8")
    assert "another account on the same computer that can write into the backup folder" not in en
