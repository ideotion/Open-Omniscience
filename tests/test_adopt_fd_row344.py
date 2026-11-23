"""Row 344: a descriptor handed to a file object is closed exactly once, whatever is raised on the way.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``os.fdopen(fd)`` inside ``try: ... except BaseException: os.close(fd)`` closed the descriptor a SECOND time when the
exception came after the file object existed (an interrupt before the ``return``, an error building the buffer, after
which ``io.open`` closes the raw file itself). By then another open may own the number, a SQLite connection's above
all, and closing it drops the process's locks on that file (R789). ``regular_file.adopt_fd`` replaces the pattern at
every site; these tests inject the failure right after the ``FileIO`` is built and then put ANOTHER file on the freed
number: a second close would take that one.
"""

from __future__ import annotations

import ast
import errno
import gc
import os
from pathlib import Path

import pytest

import src.backup.regular_file as RF

ROOT = Path(__file__).resolve().parents[1]


def _is_closed(n: int) -> bool:
    try:
        os.fstat(n)
    except OSError as exc:
        assert exc.errno == errno.EBADF
        return True
    return False


def _occupy(n: int, path: Path) -> int:
    """Put ``path`` on number ``n`` (as any later open could), returning the inode it leads to."""
    other = os.open(path, os.O_RDONLY)  # the lowest free number: often ``n`` itself
    if other != n:
        try:
            os.dup2(other, n)
        finally:
            os.close(other)
    return os.fstat(n).st_ino


@pytest.fixture
def files(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"a" * 100)
    b = tmp_path / "b.bin"
    b.write_bytes(b"b" * 100)
    return a, b


@pytest.fixture
def fail_after_fileio(monkeypatch):
    """Raise right after the FileIO exists, as an interrupt or a buffer error would. The FileIO itself is KEPT (``held``),
    so a version that let it own the number would close it again only when the test lets go of it, which is after
    ANOTHER file sits on the number: the second close then lands on that file, where :func:`_closed_once` sees it."""
    held: list = []

    def boom(raw, *a, **kw):
        held.append(raw)
        raise KeyboardInterrupt

    monkeypatch.setitem(RF._BUFFERED, "rb", boom)
    monkeypatch.setitem(RF._BUFFERED, "wb", boom)
    return held


def _raised(call) -> BaseException:
    try:
        call()
    except (KeyboardInterrupt, MemoryError) as exc:
        return exc
    pytest.fail("nothing was raised")


def _closed_once(held: list, other: Path, exc: BaseException | None = None) -> None:
    n = held[0].fileno()  # the half-built FileIO still names the number: nothing closed it through the object
    assert _is_closed(n), "the failure left the descriptor open"
    ino = _occupy(n, other)
    try:
        if exc is not None:
            exc.__traceback__ = None  # its frames hold the half-built objects too
        held.clear()
        gc.collect()  # the half-built file object is finalised now: it must not close what the number leads to
        assert not _is_closed(n), "the descriptor was closed a second time, taking another file's number with it"
        assert os.fstat(n).st_ino == ino
    finally:
        os.close(n)


def test_adopt_fd_closes_once_when_the_buffer_fails(files, fail_after_fileio):
    a, b = files
    fd = os.open(a, os.O_RDONLY)
    exc = _raised(lambda: RF.adopt_fd(fd, "rb"))
    assert fail_after_fileio[0].fileno() == fd
    _closed_once(fail_after_fileio, b, exc)


def test_open_regular_closes_once_when_the_buffer_fails(files, fail_after_fileio):
    a, b = files
    exc = _raised(lambda: RF.open_regular(a))
    _closed_once(fail_after_fileio, b, exc)


def test_create_new_closes_once_when_the_buffer_fails(files, fail_after_fileio, tmp_path):
    _, b = files
    exc = _raised(lambda: RF.create_new(tmp_path / "new.bin"))
    _closed_once(fail_after_fileio, b, exc)


def test_hash_fd_closes_once_when_the_buffer_fails(files, fail_after_fileio):
    from src.backup.folder_backup import _hash_fd

    a, b = files
    fd = os.open(a, os.O_RDONLY)
    exc = _raised(lambda: _hash_fd(fd))
    _closed_once(fail_after_fileio, b, exc)


def test_read_manifest_json_closes_once_when_the_buffer_fails(files, monkeypatch, tmp_path):
    from src.backup.manifest_file import read_manifest_json

    _, b = files
    m = tmp_path / "m.json"
    m.write_text('{"a": 1}', encoding="utf-8")
    held: list = []

    def boom(raw, *a, **kw):
        held.append(raw)
        raise MemoryError  # one the reader turns into "unreadable"

    monkeypatch.setitem(RF._BUFFERED, "rb", boom)
    assert read_manifest_json(m) is None
    _closed_once(held, b)


def _reopened_survives(n: int, other: Path) -> None:
    assert _is_closed(n)
    ino = _occupy(n, other)
    try:
        gc.collect()
        assert os.fstat(n).st_ino == ino
    finally:
        os.close(n)


def test_an_adopted_file_closes_its_descriptor_once(files):
    a, b = files
    f = RF.adopt_fd(os.open(a, os.O_RDONLY), "rb")
    n = f.fileno()
    assert f.read() == b"a" * 100
    f.close()
    _reopened_survives(n, b)
    del f


def test_an_adopted_file_dropped_unclosed_still_closes_its_descriptor(files):
    a, _ = files
    f = RF.adopt_fd(os.open(a, os.O_RDONLY), "rb")
    n = f.fileno()
    del f
    gc.collect()
    assert _is_closed(n)


def test_an_adopted_writer_writes_and_closes(tmp_path, files):
    _, b = files
    with RF.create_new(tmp_path / "w.bin") as f:
        n = f.fileno()
        f.write(b"xyz")
    assert (tmp_path / "w.bin").read_bytes() == b"xyz"
    _reopened_survives(n, b)


def _closes_fd_on_failure(handler_or_final: list[ast.stmt]) -> bool:
    return any(
        isinstance(node, ast.Call) and ast.unparse(node.func) == "os.close"
        for stmt in handler_or_final
        for node in ast.walk(stmt)
    )


def test_no_fdopen_sits_in_a_try_that_also_closes_the_descriptor():
    """Every instance of the pattern in src: an ``os.fdopen`` in a ``try`` whose handler or ``finally`` calls
    ``os.close``. Use ``regular_file.adopt_fd`` instead."""
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            fdopens = [n for s in node.body for n in ast.walk(s) if isinstance(n, ast.Call) and ast.unparse(n.func) == "os.fdopen"]
            if not fdopens:
                continue
            closing = node.finalbody + [s for h in node.handlers for s in h.body]
            if not _closes_fd_on_failure(closing):
                continue
            for call in fdopens:
                if any(kw.arg == "closefd" for kw in call.keywords):
                    continue  # closefd=False: the file object never closes the number
                found.append(f"{path.relative_to(ROOT)}:{call.lineno}")
    assert found == [], f"os.fdopen inside a try that closes the descriptor on failure: {found}"
