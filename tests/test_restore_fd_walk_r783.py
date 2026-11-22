"""R783: on a system that can, a folder restore walks the backup BY FOLDER HANDLE and opens every file
one name at a time, relative to the folder before it, never following a link (a walk by handle +
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
    for name in ("supports_dir_fd", "supports_fd", "O_NOFOLLOW", "O_DIRECTORY"):
        assert name in text
    for name in ("os.name", "sys.platform", "platform."):
        assert name not in text
    if os.open in os.supports_dir_fd and os.scandir in os.supports_fd and hasattr(os, "O_NOFOLLOW"):
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
        real_fd_walk = folder_backup._fd_walk

        def fake_fd_walk(top):
            for item in real_fd_walk(top):
                if not swapped:
                    _swap(backup, outside)  # the category folder is listed; "sub" is about to be looked at
                    swapped.append(True)
                yield item

        monkeypatch.setattr(folder_backup, "_fd_walk", fake_fd_walk)
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
    """A link in its place is refused at the open. A different real folder in its place passes the
    folder's second look (a made-up inode number on FAT looks the same), so its files are caught by the
    member's own identity check: the file opened must be the file that was walked."""
    if not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")
    backup, outside, tgt = _setup(tmp_path)
    cat_st = os.lstat(backup / "wiki_dumps")
    seen = os.lstat(backup / "wiki_dumps" / "a.bz2")
    (backup / "wiki_dumps").rename(tmp_path / "old_cat")
    os.symlink(outside, backup / "wiki_dumps")
    with pytest.raises(SourceChanged):
        folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, PurePosixPath("a.bz2"))
    os.unlink(backup / "wiki_dumps")
    _touch(backup / "wiki_dumps" / "a.bz2", b"other")
    opener = lambda: folder_backup._open_member_fd(backup, "wiki_dumps", cat_st, PurePosixPath("a.bz2"))  # noqa: E731
    with pytest.raises(SourceChanged):
        folder_backup._atomic_copy(backup / "wiki_dumps" / "a.bz2", tmp_path / "out.bz2", nofollow_src=True,
                                   expect=seen, opener=opener)
    assert not (tmp_path / "out.bz2").exists()


def test_without_the_capability_the_path_checks_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_backup, "_FD_RELATIVE", False)

    def never(*a, **k):
        raise AssertionError("the walk by folder handle ran without the capability")

    monkeypatch.setattr(folder_backup, "_open_member_fd", never)
    monkeypatch.setattr(folder_backup, "_fd_walk", never)
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


def _fd_only():
    if not folder_backup._FD_RELATIVE:
        pytest.skip("this system has no walk by folder handle")


def test_a_category_folder_that_cannot_be_opened_is_one_unlisted_entry_and_the_rest_restores(tmp_path, monkeypatch):
    """Read finding: ``os.fwalk`` raised here and stopped the whole restore; R778 counts it and goes on."""
    _fd_only()
    backup, _, tgt = _setup(tmp_path)
    _touch(backup / "osm_regions" / "x.pbf", b"xx")
    real_open = os.open

    def fake_open(path, flags, *a, **k):
        if os.fspath(path) == os.fspath(backup / "wiki_dumps") and flags & os.O_DIRECTORY:
            raise PermissionError(13, "secret system words")
        return real_open(path, flags, *a, **k)

    scope_os(monkeypatch, folder_backup, open=fake_open)
    res = restore_folder_backup(backup, targets=tgt)
    assert {"category": "wiki_dumps", "rel": "", "why": "folder-unlisted"} in res["unread"]
    assert _live_bytes(tgt["osm_regions"]) == {"x.pbf": b"xx"} and res["incomplete"] is True
    assert "secret" not in repr(res)


@pytest.mark.parametrize("part_way", [False, True])
def test_a_folder_whose_listing_fails_is_one_unlisted_entry(tmp_path, monkeypatch, part_way):
    """Read finding: a listing that fails (a damaged drive answering EIO) raised past the walk."""
    _fd_only()
    backup, _, tgt = _setup(tmp_path)
    _touch(backup / "wiki_dumps" / "sub" / "d.bz2", b"ddd")
    real_open, real_scandir = os.open, os.scandir
    sub_fds: set[int] = set()

    def fake_open(path, flags, *a, **k):
        fd = real_open(path, flags, *a, **k)
        if os.fspath(path) == "sub" and flags & os.O_DIRECTORY and k.get("dir_fd") is not None:
            sub_fds.add(fd)
        return fd

    class _Failing:
        def __init__(self, it):
            self.it = it

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.it.close()

        def __iter__(self):
            if part_way:
                yield next(iter(self.it))
            raise OSError(5, "secret system words")

    def fake_scandir(arg="."):
        it = real_scandir(arg)
        return _Failing(it) if isinstance(arg, int) and arg in sub_fds else it

    scope_os(monkeypatch, folder_backup, open=fake_open, scandir=fake_scandir)
    res = restore_folder_backup(backup, targets=tgt)
    assert sub_fds, "the sub-folder was never opened by handle"
    assert {"category": "wiki_dumps", "rel": "sub", "why": "folder-unlisted"} in res["unread"]
    assert _live_bytes(tgt["wiki_dumps"]) == {"a.bz2": b"aaa"} and res["incomplete"] is True
    assert "secret" not in repr(res)


_DEEP = """
import os, resource, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from src.backup.folder_backup import restore_folder_backup
backup, live = Path(sys.argv[2]), Path(sys.argv[3])
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (48, hard))
res = restore_folder_backup(backup, targets={c: live / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")})
print(res["restored"], res["incomplete"], res["unread_folders"])
"""


def test_a_folder_nested_deeper_than_the_process_has_handles_restores_whole(tmp_path):
    """Read finding: ``os.fwalk`` holds a handle per level, so a deep backup ran out of handles and stopped.
    The walk by handle reopens each folder from the category folder: a few handles, whatever the depth."""
    _fd_only()
    import subprocess
    import sys

    backup, _, _ = _setup(tmp_path)
    deep = backup / "wiki_dumps"
    for i in range(120):
        deep = deep / f"d{i}"
    _touch(deep / "z.bz2", b"z")
    out = subprocess.run([sys.executable, "-c", _DEEP, str(ROOT), str(backup), str(tmp_path / "live")],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split() == ["3", "False", "0"]


@needs_links
def test_both_walks_agree_on_a_tricky_tree(tmp_path, monkeypatch):
    """Links to folders, dangling links, ``.oopart`` names and folders, a pipe, a link two levels down:
    the walk by handle and the walk by path give the same members, counts and result."""
    _fd_only()
    backup, outside, _ = _setup(tmp_path)
    w = backup / "wiki_dumps"
    os.symlink(outside, w / "to_dir")
    os.symlink(outside, w / "x.oopart")
    os.symlink(tmp_path / "nowhere", w / "dangling")
    os.symlink(tmp_path / "nowhere", w / "d.oopart")
    _touch(w / "f.oopart", b"part")
    _touch(w / "dir.oopart" / "inside.bz2", b"in")
    os.mkfifo(w / "pipe")
    _touch(w / "sub" / "deeper" / "e.bz2", b"e")
    os.symlink(outside / "c.bz2", w / "sub" / "deeper" / "link.bz2")
    results = {}
    for fd in (True, False):
        monkeypatch.setattr(folder_backup, "_FD_RELATIVE", fd)
        unread: list = []
        members, links = folder_backup._category_members(w, unread)
        live = tmp_path / f"live{int(fd)}"
        res = restore_folder_backup(backup, targets={c: live / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")})
        results[fd] = ([(str(p), st.st_size) for p, st in members], links, unread,
                       {k: v for k, v in res.items() if k not in ("src",)}, _live_bytes(live / "wiki_dumps"))
    assert results[True] == results[False]
    assert results[True][1] == 3  # to_dir, dangling, link.bz2; the .oopart links are not counted


def test_a_category_folder_whose_inode_number_moved_is_still_the_folder(tmp_path, monkeypatch):
    """Opus read: on FAT32/exFAT the folder's inode number can be made up again during a long copy. The
    second look accepts it when the name is still that same folder, so a sound backup is not refused."""
    _fd_only()
    backup, _, tgt = _setup(tmp_path)
    real_lstat = os.lstat
    moved: list[bool] = []

    def lstat_once_moved(path, *a, **k):
        st = real_lstat(path, *a, **k)
        if os.fspath(path) == os.fspath(backup / "wiki_dumps") and not moved:
            moved.append(True)  # the walk's look: an inode number the kernel will not give again
            vals = list(st)
            vals[1] = st.st_ino + 987654
            return os.stat_result(vals)
        return st

    real_samestat = os.path.samestat
    scope_os(monkeypatch, folder_backup, lstat=lstat_once_moved)
    monkeypatch.setattr(folder_backup, "_category_swapped", lambda *a: False)
    res = restore_folder_backup(backup, targets=tgt)
    assert moved and real_samestat
    assert res["restored"] == 2 and res["refused_symlinks"] == 0 and res["incomplete"] is False
