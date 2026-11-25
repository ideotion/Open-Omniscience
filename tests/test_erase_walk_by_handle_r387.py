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
