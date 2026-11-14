"""Encrypting in place closes a serve that was in use at that moment as soon as it is free (open-on-main row 50).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``close_serves_after_encryption`` never waits, so a serve whose lock was held (a query, a build swapping) was left open and
only named in ``busy``: its offload folder, made while the library was plaintext, stayed on disk until the next rebuild.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.analytics import map_serve
from src.scheduler import release


class _Con:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def served(monkeypatch, tmp_path):
    folder = tmp_path / "duckdb_tmp" / "123-abcd1234"
    folder.mkdir(parents=True)
    (folder / "duckdb_temp_storage-1.tmp").write_bytes(b"plaintext rows")
    con = _Con()
    monkeypatch.setitem(map_serve._STATE, "con", con)
    monkeypatch.setitem(map_serve._STATE, "spill", str(folder))
    monkeypatch.setitem(map_serve._STATE, "built_at", 1.0)
    monkeypatch.delitem(release.sys.modules, "src.analytics.rollup_serve", raising=False)  # this test closes the map serve only
    return con, folder


def _wait_for(cond, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_a_serve_in_use_is_closed_with_its_folder_once_it_is_free(served):
    con, folder = served
    map_serve._LOCK.acquire()  # a query is running
    try:
        out = release.close_serves_after_encryption()
        assert out.get("busy") == ["map_serve"] and out.get("deferred") == ["map_serve"]
        time.sleep(0.1)
        assert not con.closed and folder.exists(), "closed under a running query"
    finally:
        map_serve._LOCK.release()
    assert _wait_for(lambda: con.closed and not folder.exists()), "the busy serve kept its plaintext folder after the encryption"
    assert map_serve._STATE["con"] is None and map_serve._STATE["spill"] is None


def test_a_serve_swapped_in_while_busy_with_no_folder_is_not_closed(served):
    con, folder = served
    newer = _Con()
    map_serve._LOCK.acquire()
    try:
        release.close_serves_after_encryption()
        map_serve._STATE["con"] = newer  # built after the encryption: no offload folder (the replacer retired the old one itself)
        map_serve._STATE["spill"] = None
    finally:
        map_serve._LOCK.release()
    assert _wait_for(lambda: not any(t.name.startswith("close-map_serve") for t in threading.enumerate()))
    assert not newer.closed and map_serve._STATE["con"] is newer, "the connection built after the encryption was closed"


def test_a_serve_swapped_in_while_busy_with_a_plaintext_era_folder_is_closed_too(served, tmp_path):
    """The lock holder was a build that passed its encryption check just before the encryption and swapped in: its folder was
    made while the library was plaintext, so it goes with its connection."""
    con, _folder = served
    newer = _Con()
    newer_folder = tmp_path / "duckdb_tmp" / "123-ffff0000"
    newer_folder.mkdir()
    map_serve._LOCK.acquire()
    try:
        release.close_serves_after_encryption()
        map_serve._STATE["con"] = newer
        map_serve._STATE["spill"] = str(newer_folder)
    finally:
        map_serve._LOCK.release()
    assert _wait_for(lambda: newer.closed and not newer_folder.exists()), "a plaintext-era folder outlived the encryption"
    assert map_serve._STATE["con"] is None and map_serve._STATE["spill"] is None
