"""GET /api/database/backup writes its plaintext snapshot where the corpus lives, for the app's own page, one at a time (audit 0.5.0, A-008).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The route used to write a full plaintext copy of the corpus into the operating system's temporary directory for ANY GET, so a web
page of another site could make a machine copy its whole corpus out of the data folder with one ``<img src>``. It now refuses a
request from another site before it touches the disk, takes one snapshot at a time, checks the free space of the data volume
before it writes, writes into an owner-only directory beside the database, and removes that directory when the response ends.

The TestClient names its host ``testserver``; the app's own page sends ``Sec-Fetch-Site: same-origin`` and (for a ``fetch``)
``Origin: http://testserver``.
"""

from __future__ import annotations

import asyncio
import collections
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.api.database as dbapi
import src.backup.sqlite_backup as sb
from src.api.main import app
from src.database.session import init_db

OWN_PAGE = {"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"}
FOREIGN = [
    {"Origin": "http://evil.example"},
    {"Origin": "http://testserver:9999"},  # another port on the same host is another origin
    {"Origin": "null"},
    {"Referer": "http://evil.example/page"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "same-origin", "Origin": "http://evil.example"},  # the stricter of the two decides
]


@pytest.fixture()
def data_dir():
    init_db()
    d = sb.live_db_path().parent
    for left in d.glob(".oo-backup-*"):
        import shutil

        shutil.rmtree(left, ignore_errors=True)
    dbapi._backup_flight = None
    yield d
    dbapi._backup_flight = None


@pytest.fixture()
def client(data_dir):
    with TestClient(app) as c:
        yield c


def _left_over(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob(".oo-backup-*"))


def _forbid_snapshots(monkeypatch):
    calls: list[Path] = []

    def spy(dest):
        calls.append(Path(dest))
        raise AssertionError("a snapshot was started")

    monkeypatch.setattr(sb, "backup_to", spy)
    return calls


@pytest.mark.parametrize("headers", FOREIGN, ids=[str(sorted(h.items())) for h in FOREIGN])
def test_a_request_from_another_site_is_refused_before_anything_is_written(client, data_dir, monkeypatch, headers):
    calls = _forbid_snapshots(monkeypatch)
    made: list[str] = []
    real = dbapi.tempfile.mkdtemp
    monkeypatch.setattr(dbapi.tempfile, "mkdtemp", lambda *a, **k: made.append("mkdtemp") or real(*a, **k))
    r = client.get("/api/database/backup", headers=headers)
    assert r.status_code == 403
    assert not calls and not made, "the refusal came after the disk was touched"
    assert _left_over(data_dir) == []
    assert dbapi._backup_flight is None, "a refused request must not hold the slot"


@pytest.mark.parametrize("headers", [{}, OWN_PAGE, {"Sec-Fetch-Site": "none"}, {"Referer": "http://testserver/index.html"}])
def test_the_apps_own_page_and_callers_that_are_not_browsers_are_served(client, data_dir, headers):
    r = client.get("/api/database/backup", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-sqlite3")
    assert r.content[:16] == b"SQLite format 3\x00"
    assert "X-OO-Free-Space-Check" not in r.headers


def test_the_snapshot_is_written_beside_the_database_and_removed_when_the_response_ends(client, data_dir, monkeypatch):
    seen: dict = {}
    real = sb.backup_to

    def spy(dest):
        dest = Path(dest)
        seen["dest"] = dest
        seen["mode"] = dest.parent.stat().st_mode & 0o777
        return real(dest)

    monkeypatch.setattr(sb, "backup_to", spy)

    def no_system_temp(*a, **k):
        raise AssertionError("the snapshot went to the system temporary directory")

    monkeypatch.setattr(dbapi.tempfile, "mkstemp", no_system_temp)
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 200
    dest = seen["dest"]
    assert dest.parent.parent == data_dir and dest.parent.name.startswith(".oo-backup-")
    if os.name == "posix":
        assert seen["mode"] == 0o700, "the snapshot directory is the owner's alone"
    assert not dest.parent.exists(), "the snapshot outlived its response"
    assert dbapi._backup_flight is None
    out = Path(data_dir) / "downloaded-copy.db"
    out.write_bytes(r.content)
    try:
        conn = sqlite3.connect(str(out))
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    finally:
        out.unlink()
    assert {"articles", "sources"} <= names


def test_an_encrypted_store_is_refused_and_leaves_nothing(client, data_dir, monkeypatch):
    import src.database.connect as connect

    monkeypatch.setattr(connect, "is_encrypted_file", lambda p: True)
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 400
    assert "never decrypts the corpus" in r.json()["detail"]
    assert _left_over(data_dir) == []
    assert dbapi._backup_flight is None


Usage = collections.namedtuple("Usage", "total used free")


def test_a_volume_without_room_for_the_snapshot_is_refused_with_both_figures(client, data_dir, monkeypatch):
    calls = _forbid_snapshots(monkeypatch)
    monkeypatch.setattr(dbapi.shutil, "disk_usage", lambda p: Usage(10**9, 10**9 - 10, 10))
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 507
    detail = r.json()["detail"]
    assert "10 bytes free" in detail and "needed" in detail
    needed = int(detail.split("up to ")[1].split(" ")[0].replace(",", ""))
    assert needed >= sb.live_db_path().stat().st_size, "the figure asked for is less than the database file itself"
    assert not calls and _left_over(data_dir) == [] and dbapi._backup_flight is None


def test_a_free_space_that_cannot_be_read_is_not_a_refusal_and_the_response_says_so(client, data_dir, monkeypatch):
    def broken(path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(dbapi.shutil, "disk_usage", broken)
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 200
    assert r.headers["X-OO-Free-Space-Check"] == "not-read"


def test_only_one_snapshot_is_made_at_a_time_and_the_slot_comes_back(client, data_dir, monkeypatch):
    dbapi._claim_backup_slot()
    try:
        calls = _forbid_snapshots(monkeypatch)
        r = client.get("/api/database/backup", headers=OWN_PAGE)
        assert r.status_code == 429
        assert not calls and _left_over(data_dir) == []
        assert dbapi._backup_flight is not None, "the refused request released the OTHER request's claim"
    finally:
        dbapi._release_backup_slot(None)
    monkeypatch.undo()
    assert client.get("/api/database/backup", headers=OWN_PAGE).status_code == 200


def test_a_claim_whose_response_never_ran_is_taken_over_after_the_stale_age(client, data_dir):
    dbapi._backup_flight = (None, time.monotonic() - dbapi._BACKUP_STALE_AFTER_S - 1)
    assert client.get("/api/database/backup", headers=OWN_PAGE).status_code == 200
    assert dbapi._backup_flight is None


def test_a_failed_snapshot_frees_the_slot_and_removes_its_directory(client, data_dir, monkeypatch):
    def boom(dest):
        Path(dest).write_bytes(b"half")
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sb, "backup_to", boom)
    with pytest.raises(sqlite3.OperationalError):
        client.get("/api/database/backup", headers=OWN_PAGE)
    assert _left_over(data_dir) == []
    assert dbapi._backup_flight is None


def test_a_response_that_ends_in_error_still_removes_the_directory_and_frees_the_slot(data_dir):
    dbapi._claim_backup_slot()
    workdir = data_dir / ".oo-backup-test"
    workdir.mkdir()
    snap = workdir / "snapshot.db"
    snap.write_bytes(b"x" * 1000)
    dbapi._note_backup_dir(workdir)
    resp = dbapi._SnapshotResponse(snap, workdir, media_type="application/x-sqlite3")

    async def gone(message):
        raise OSError("client went away")

    async def receive():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "GET", "headers": [], "extensions": {}}
    with pytest.raises(BaseException):  # noqa: B017 - whatever the transport raises, the cleanup must have run
        asyncio.run(resp(scope, receive, gone))
    assert not workdir.exists()
    assert dbapi._backup_flight is None


def test_a_crashed_servers_leftovers_are_swept_but_a_younger_directory_and_other_files_are_not(client, data_dir):
    old = data_dir / ".oo-backup-crashed"
    young = data_dir / ".oo-backup-streaming"
    other = data_dir / ".oo-unlock-keep"
    for d in (old, young, other):
        d.mkdir()
        (d / "snapshot.db").write_bytes(b"x")
    two_days = time.time() - 2 * dbapi._BACKUP_STALE_AFTER_S
    os.utime(old, (two_days, two_days))
    os.utime(other, (two_days, two_days))
    try:
        assert client.get("/api/database/backup", headers=OWN_PAGE).status_code == 200
        assert not old.exists(), "a leftover older than the stale age stayed"
        assert young.exists(), "a directory another server may be streaming from was removed"
        assert other.exists(), "a directory that is not a snapshot's was removed"
    finally:
        for d in (old, young, other):
            import shutil

            shutil.rmtree(d, ignore_errors=True)


def test_the_refusal_lives_in_the_route_not_the_middleware():
    """A-001 owns the middleware; the route has to be safe on its own (R214)."""
    src = Path(dbapi.__file__).read_text(encoding="utf-8")
    assert "_refuse_cross_site(request)" in src
    assert "def download_backup(request: Request)" in src
