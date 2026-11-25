"""
Row 387 (R812 (c), R783): the erase's long walks go by the data folder's handle, never by its path.

Steps 5b and 6 walked the data folder with ``os.walk`` on its path, and the final removal was ``shutil.rmtree`` on the path. A data
folder (or a drive at its place) swapped after the walk began was then reached by its path: whatever stood there now was
overwritten and removed, and the folder the erase had started on was left. On POSIX the walks now start from the handle the
erase took on the folder before its first write: every folder is opened by name from it with ``O_NOFOLLOW | O_DIRECTORY``, and
every file is looked at, written and unlinked by name through its folder's handle. Windows has no folder handle here and keeps
the walk by path, the window stated beside the drive re-checks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.safety import crypto_erase
from tests.os_scope import scope_os

pytestmark = pytest.mark.skipif(sys.platform == "win32" or not hasattr(os, "O_DIRECTORY"), reason="POSIX folder handles")


def _folder(tmp_path: Path) -> Path:
    data = tmp_path / "OOS data"
    (data / "sub").mkdir(parents=True)
    (data / "sub" / "notes.json").write_bytes(b"SECRET" * 1000)
    (data / "app_settings.json").write_text('{"k": 1}', encoding="utf-8")
    return data


def _swap_when_walked(monkeypatch, data: Path, aside: Path) -> None:
    """At the first walk (5b), the folder the erase started on moves aside and another folder takes its path, holding a file of the
    operator's under the same name as one of the app's."""
    real = crypto_erase._erase_roots
    swapped: list[bool] = []

    def roots(base, **kw):
        out = real(base, **kw)
        if not swapped:
            swapped.append(True)
            os.rename(data, aside)
            (data / "sub").mkdir(parents=True)
            (data / "sub" / "notes.json").write_bytes(b"the operator's own file")
        return out

    monkeypatch.setattr(crypto_erase, "_erase_roots", roots)


def test_a_folder_swapped_mid_erase_is_never_reached_by_its_path(tmp_path, monkeypatch):
    data = _folder(tmp_path)
    aside = tmp_path / "moved aside"
    _swap_when_walked(monkeypatch, data, aside)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "sub" / "notes.json").read_bytes() == b"the operator's own file"  # never written, never removed
    assert data.is_dir(), "the folder now at the path is not the one the erase started on: never removed"
    assert not (aside / "sub" / "notes.json").exists(), "the folder the erase started on is the one erased"
    assert not (aside / "app_settings.json").exists()


def test_by_path_the_same_swap_reaches_the_other_folder(tmp_path, monkeypatch):
    """The control: without the handle (Windows), the walk goes by path and reaches what stands there now."""
    monkeypatch.setattr(crypto_erase, "_walk_fd", lambda hold: None)
    data = _folder(tmp_path)
    aside = tmp_path / "moved aside"
    _swap_when_walked(monkeypatch, data, aside)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert not (data / "sub" / "notes.json").exists()
    assert (aside / "sub" / "notes.json").exists()


def test_a_sub_folder_swapped_for_a_link_is_never_entered(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (data / "sub").symlink_to(outside, target_is_directory=True)
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        got, err = crypto_erase._open_below(fd, ("sub",))
        assert got is None and isinstance(err, OSError)
    finally:
        os.close(fd)


def test_a_file_swapped_for_a_link_is_never_written_through(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    target = tmp_path / "elsewhere.txt"
    target.write_bytes(b"keep me")
    (data / "x.json").symlink_to(target)
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert crypto_erase._overwrite(data / "x.json", at=crypto_erase._At(fd, "x.json")) is False
    finally:
        os.close(fd)
    assert target.read_bytes() == b"keep me"


def test_the_walk_by_handle_reaches_every_file_and_never_a_link(tmp_path):
    data = _folder(tmp_path)
    (data / "sub" / "deeper").mkdir()
    (data / "sub" / "deeper" / "a.bin").write_bytes(b"a")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.bin").write_bytes(b"b")
    (data / "link").symlink_to(outside, target_is_directory=True)
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        got = {str(p.relative_to(data)): at is not None for p, at in crypto_erase._files_under([data], data, lambda e: None, base_fd=fd)}
    finally:
        os.close(fd)
    assert got == {"app_settings.json": True, "link": True, "sub/notes.json": True, "sub/deeper/a.bin": True}


def test_a_folder_the_walk_cannot_open_is_named_by_its_path(tmp_path, monkeypatch):
    data = _folder(tmp_path)
    failed: list[OSError] = []
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    real = crypto_erase._open_below

    def refusing(base_fd, parts):
        return (None, PermissionError(13, "denied")) if parts == ("sub",) else real(base_fd, parts)

    monkeypatch.setattr(crypto_erase, "_open_below", refusing)
    try:
        list(crypto_erase._files_under([data], data, failed.append, base_fd=fd))
    finally:
        os.close(fd)
    assert [e.filename for e in failed] == [str(data / "sub")]
    assert all(str(fd) != e.filename for e in failed)


def test_without_a_folder_handle_the_walk_goes_by_path():
    assert crypto_erase._walk_fd(None) is None
    assert crypto_erase._walk_fd((Path("x"), (1, 2), None)) is None


def test_a_folder_moved_away_mid_erase_is_erased_by_its_handle_and_never_said_removed(tmp_path, monkeypatch):
    """Security read: the folder the erase started on is walked from its handle wherever it went, and "removed" is said only when
    that very folder was removed."""
    data = _folder(tmp_path)
    aside = tmp_path / "moved aside"
    real = crypto_erase._erase_roots
    moved: list[bool] = []

    def roots(base, **kw):
        if not moved:
            moved.append(True)
            os.rename(data, aside)  # nothing takes its path
        return real(base, **kw)

    monkeypatch.setattr(crypto_erase, "_erase_roots", roots)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert not (aside / "sub" / "notes.json").exists()
    assert not (aside / "app_settings.json").exists()
    assert report.get("removed") is False and report.get("removed_at_rmtree") is False and report.get("folder_moved") is True


def test_a_drive_mounted_below_is_never_entered(tmp_path, monkeypatch):
    """Security read: a folder below whose device is not the data folder's is refused like a link, named as not checked."""
    data = _folder(tmp_path)
    real_fstat = os.fstat
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    base_dev = real_fstat(fd).st_dev
    sub_ino = os.stat(data / "sub").st_ino

    class _Other:
        def __init__(self, st):
            self.st_dev, self.st_ino, self.st_nlink = base_dev + 1, st.st_ino, st.st_nlink

    scope_os(monkeypatch, crypto_erase, fstat=lambda f: _Other(real_fstat(f)) if real_fstat(f).st_ino == sub_ino else real_fstat(f))
    try:
        got, err = crypto_erase._open_below(fd, ("sub",))
    finally:
        os.close(fd)
    assert got is None and isinstance(err, OSError)


def test_a_handle_that_cannot_be_taken_never_stops_the_walk(tmp_path, monkeypatch):
    data = _folder(tmp_path)
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)

    def no_more(_fd):
        raise OSError(24, "too many")

    scope_os(monkeypatch, crypto_erase, dup=no_more)
    try:
        got, err = crypto_erase._open_below(fd, ())
    finally:
        os.close(fd)
    assert got is None and err is not None and err.errno == 24


def test_another_name_of_a_refused_copy_is_still_rewritten(tmp_path):
    """Security read: a refused copy is kept by its NAME (row 402), never by its identity: an app file that is another name of it
    is rewritten under that name as before."""
    data = _folder(tmp_path)
    other = data / "sub" / "notes.json"
    other.write_bytes(b"PLAINTEXTSECRET" * 2000)
    os.link(other, data / "pre-restore-20261114T090000Z.db")  # a copy the erase refuses: it has a second name
    fd = os.open(other, os.O_RDONLY)
    try:
        crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
        body = os.pread(fd, 30000, 0)
    finally:
        os.close(fd)
    assert b"PLAINTEXTSECRET" not in body


def test_the_removal_never_empties_a_folder_on_another_device(tmp_path, monkeypatch):
    data = _folder(tmp_path)
    (data / "sub" / "drive").mkdir()
    (data / "sub" / "drive" / "theirs.txt").write_bytes(b"on another drive")
    real_fstat = os.fstat
    drive_ino = os.stat(data / "sub" / "drive").st_ino

    class _Other:
        def __init__(self, st):
            self.st_dev, self.st_ino, self.st_nlink, self.st_mode = st.st_dev + 1, st.st_ino, st.st_nlink, st.st_mode

    scope_os(monkeypatch, crypto_erase, fstat=lambda f: _Other(real_fstat(f)) if real_fstat(f).st_ino == drive_ino else real_fstat(f))
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        crypto_erase._rmtree_at(fd, "sub")
    finally:
        os.close(fd)
    assert (data / "sub" / "drive" / "theirs.txt").read_bytes() == b"on another drive"
    assert not (data / "sub" / "notes.json").exists()


def test_a_data_folder_swapped_for_a_link_is_never_said_removed(tmp_path, monkeypatch):
    data = _folder(tmp_path)
    aside = tmp_path / "moved aside"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    real = crypto_erase._erase_roots
    moved: list[bool] = []

    def roots(base, **kw):
        if not moved:
            moved.append(True)
            os.rename(data, aside)
            data.symlink_to(elsewhere, target_is_directory=True)
        return real(base, **kw)

    monkeypatch.setattr(crypto_erase, "_erase_roots", roots)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert not (aside / "sub").exists(), "the held folder is emptied through its handle"
    assert report.get("removed") is False and report.get("folder_moved") is True
    assert elsewhere.is_dir()


def test_a_very_deep_tree_is_removed_without_recursion(tmp_path):
    """Security read: the removal keeps its own stack, so a tree deeper than Python's recursion limit never aborts the erase."""
    data = tmp_path / "OOS data"
    data.mkdir()
    fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        cur = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
        for _ in range(sys.getrecursionlimit() + 200):
            os.mkdir("d", dir_fd=cur)
            nxt = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=cur)
            os.close(cur)
            cur = nxt
        os.close(os.open("secret", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=cur))
        os.close(cur)
        crypto_erase._rmtree_at(fd, "d")
        assert "d" not in os.listdir(fd)
    finally:
        os.close(fd)


def test_the_walk_by_path_yields_a_top_level_file_with_no_handle(tmp_path):
    """Security read: the by-path walk (Windows, or no hold) gives every item as (path, None), a top-level file of app-only scope too."""
    data = _folder(tmp_path)
    got = list(crypto_erase._files_under([data / "app_settings.json", data / "sub"], data, lambda e: None))
    assert (data / "app_settings.json", None) in got and (data / "sub" / "notes.json", None) in got
