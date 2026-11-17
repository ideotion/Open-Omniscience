"""The repair's sidecar is flushed through a handle Windows will flush (row 138).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_write_json_atomic`` opened the sidecar's ``.tmp`` read-only and called ``os.fsync`` on it. Windows refuses to flush a
read-only handle (EBADF), so every repair that wrote its sidecar failed there with "Bad file descriptor" and the boot repair
of a damaged library never completed. POSIX flushes a read-only descriptor, so the failure never showed on Linux or macOS:
this test puts the Windows rule in place on any POSIX system (on Windows the real ``os.fsync`` already enforces it).

A ``.json.tmp`` left by such a failed run is ignored by the next repair: sidecars are found by the whole name
``<stem>.salvage-<UTC time><suffix>.json``, which a ``.json.tmp`` never matches, so it is never read as a sidecar.
"""

from __future__ import annotations

import errno
import json
import os

import pytest

from src.database import repair

fcntl = pytest.importorskip("fcntl") if os.name != "nt" else None


@pytest.fixture
def windows_fsync(monkeypatch):
    """``os.fsync`` that refuses a descriptor opened read-only, as Windows does."""
    if fcntl is None:
        return
    real = os.fsync

    def refusing(fd: int) -> None:
        if (fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE) == os.O_RDONLY:
            raise OSError(errno.EBADF, "Bad file descriptor")
        real(fd)

    monkeypatch.setattr(repair.os, "fsync", refusing)


def test_the_sidecar_is_written_where_windows_refuses_to_flush_a_read_only_handle(tmp_path, windows_fsync):
    sidecar = tmp_path / "live.salvage-20261117T000000Z.db.json"
    repair._write_json_atomic(sidecar, {"stamp": "20261117T000000Z"})
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"stamp": "20261117T000000Z"}
    assert not list(tmp_path.glob("*.tmp")), "the temporary file became the sidecar"


def test_a_tmp_left_by_a_failed_run_is_not_a_sidecar_name(tmp_path):
    live = tmp_path / "live.db"
    pattern = repair._scratch_pattern(live, r"\.json")
    assert pattern.fullmatch("live.salvage-20261117T000000Z.db.json")
    assert not pattern.fullmatch("live.salvage-20261117T000000Z.db.json.tmp")
