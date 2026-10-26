"""GET /api/database/backup writes its plaintext snapshot where the corpus lives, for the app's own page, one at a time (audit 0.5.0, A-008).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The route used to write a full plaintext copy of the corpus into the operating system's temporary directory for ANY GET, so a web
page of another site could make a machine copy its whole corpus out of the data folder with one ``<img src>``. It now refuses a
request from another site before it touches the disk, takes one snapshot at a time, checks the free space of the data volume
before it writes, writes into an owner-only directory beside the database, and removes that directory when the response ends.

The TestClient names its host ``testserver``; the app's own page sends ``Sec-Fetch-Site: same-origin`` and (for a ``fetch``)
``Origin: http://testserver``.

THE REFUSAL IS THE ROUTE'S OWN (R214): the tests that prove it call the route function directly, with no application and so no
middleware around it, and with a Host the DNS-rebinding guard would also have stopped.
"""

from __future__ import annotations

import asyncio
import collections
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

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
    {"Sec-Fetch-Site": "CROSS-SITE"},  # header values are not case-sensitive
    {"Sec-Fetch-Site": "same-origin", "Origin": "http://evil.example"},  # the stricter of the two decides
]


class _Seen:
    """``module`` as the route module sees it, with some attributes replaced.

    Patching ``tempfile.mkdtemp`` or ``shutil.disk_usage`` on the real module would change them for every thread of the process,
    the TestClient's own among them; this changes the one name ``src.api.database`` reads."""

    def __init__(self, real, **over):
        self._real, self._over = real, over

    def __getattr__(self, name):
        return self._over[name] if name in self._over else getattr(self._real, name)


@pytest.fixture()
def data_dir():
    init_db()
    d = sb.live_db_path().parent
    for left in d.glob(".oo-backup-*"):
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


def _request(headers: dict[str, str], host: str = "testserver") -> Request:
    """A request as the ASGI server would hand it to the route, with no application around it."""
    raw = {"host": host, **{k.lower(): v for k, v in headers.items()}}
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/database/backup",
            "query_string": b"",
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in raw.items()],
        }
    )


@pytest.mark.parametrize("headers", FOREIGN, ids=[str(sorted(h.items())) for h in FOREIGN])
def test_a_request_from_another_site_is_refused_before_anything_is_written(client, data_dir, monkeypatch, headers):
    calls = _forbid_snapshots(monkeypatch)
    made: list[str] = []
    real = dbapi.tempfile.mkdtemp
    monkeypatch.setattr(dbapi, "tempfile", _Seen(dbapi.tempfile, mkdtemp=lambda *a, **k: made.append("mkdtemp") or real(*a, **k)))
    r = client.get("/api/database/backup", headers=headers)
    assert r.status_code == 403
    assert not calls and not made, "the refusal came after the disk was touched"
    assert _left_over(data_dir) == []
    assert dbapi._backup_flight is None, "a refused request must not hold the slot"


@pytest.mark.parametrize("headers", FOREIGN, ids=[str(sorted(h.items())) for h in FOREIGN])
def test_the_route_refuses_a_foreign_request_by_itself_with_no_middleware_around_it(data_dir, monkeypatch, headers):
    calls = _forbid_snapshots(monkeypatch)
    with pytest.raises(HTTPException) as refused:
        dbapi.download_backup(_request(headers))
    assert refused.value.status_code == 403
    assert not calls and dbapi._backup_flight is None and _left_over(data_dir) == []


@pytest.mark.parametrize("host", ["evil.test:8000", "evil.test", "127.0.0.1.evil.test", "", "localhost.evil.test:8000"])
def test_a_name_rebound_to_loopback_is_refused_even_though_the_browser_calls_it_same_origin(data_dir, monkeypatch, host):
    """DNS rebinding: the page on ``evil.test`` is same-origin with ITSELF, so Sec-Fetch-Site says ``same-origin`` and its Origin
    equals its Host, and the page can READ the answer. Only the Host check stops it, and the route makes it for itself."""
    calls = _forbid_snapshots(monkeypatch)
    headers = {"Sec-Fetch-Site": "same-origin", "Origin": f"http://{host}"}
    with pytest.raises(HTTPException) as refused:
        dbapi.download_backup(_request(headers, host=host))
    assert refused.value.status_code == 403
    assert not calls and dbapi._backup_flight is None and _left_over(data_dir) == []


def test_a_host_the_operator_named_is_served_with_its_own_origin(monkeypatch):
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "corpus.lan")
    dbapi._refuse_cross_site(_request({"Sec-Fetch-Site": "same-origin", "Origin": "http://corpus.lan:8000"}, host="corpus.lan:8000"))
    with pytest.raises(HTTPException):  # the name is the operator's, the origin is not
        dbapi._refuse_cross_site(_request({"Origin": "http://evil.test:8000"}, host="corpus.lan:8000"))


def test_origin_decides_when_a_request_sends_both_origin_and_referer():
    """``Origin`` is the browser's own statement of who is asking; the ``Referer`` is read only when there is no ``Origin``."""
    dbapi._refuse_cross_site(_request({"Origin": "http://testserver", "Referer": "http://evil.example/p"}))
    with pytest.raises(HTTPException):
        dbapi._refuse_cross_site(_request({"Origin": "http://evil.example", "Referer": "http://testserver/p"}))


@pytest.mark.parametrize(
    "headers",
    [{}, OWN_PAGE, {"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": "Same-Origin"}, {"Referer": "http://testserver/index.html"}],
)
def test_the_apps_own_page_and_callers_that_are_not_browsers_are_served(client, data_dir, headers):
    r = client.get("/api/database/backup", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-sqlite3")
    assert r.content[:16] == b"SQLite format 3\x00"
    assert "X-OO-Free-Space-Check" not in r.headers


def test_a_request_that_sends_none_of_the_three_headers_is_served_which_is_the_stated_limit(client, data_dir):
    """Firefox before 90, Safari before 16.4 and old webviews send no Sec-Fetch-Site, and a no-cors ``<img>`` GET with
    ``referrerpolicy="no-referrer"`` carries no Origin and no Referer either: the route cannot tell it from curl. Pinned so the
    limit is a decision in the record and not a surprise; the page cannot read the answer, and the slot and the space gate bound the cost."""
    r = client.get("/api/database/backup")
    assert r.status_code == 200 and _left_over(data_dir) == []


def test_the_same_limit_holds_for_a_name_the_operator_serves_over_plain_http(monkeypatch):
    """Browsers attach Fetch Metadata only to loopback and HTTPS targets, so a page that points an ``<img>`` at an
    ``OO_ALLOWED_HOSTS`` name over plain HTTP sends none of the three headers either: served, as curl is. Pinned so the second
    form of the limit is a decision in the record and not a surprise."""
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "corpus.lan")
    dbapi._refuse_cross_site(_request({}, host="corpus.lan:8000"))


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

    monkeypatch.setattr(dbapi, "tempfile", _Seen(dbapi.tempfile, mkstemp=no_system_temp))
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
    measured: list[Path] = []

    def usage(path):
        measured.append(Path(path))
        return Usage(10**9, 10**9 - 10, 10)

    monkeypatch.setattr(dbapi, "shutil", _Seen(dbapi.shutil, disk_usage=usage))
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 507
    assert measured == [data_dir], "the volume measured is not the one the snapshot is written on"
    detail = r.json()["detail"]
    assert "10 bytes free" in detail and "up to" in detail and "needed" in detail
    needed = int(detail.split("up to ")[1].split(" ")[0].replace(",", ""))
    assert needed >= sb.live_db_path().stat().st_size, "the figure asked for is less than the database file itself"
    assert not calls and _left_over(data_dir) == [] and dbapi._backup_flight is None


class _Sized:
    """What ``Path.stat`` returns for a file whose size the test chooses."""

    def __init__(self, size):
        self.st_size = size


def _wal_of(size, *, unreadable=False):
    """``Path`` as the route sees it, with a log file of ``size`` bytes (the real database file keeps its real size)."""

    class WithWal(type(Path())):
        def stat(self, *a, **k):
            if self.name.endswith("-wal"):
                if unreadable:
                    raise PermissionError(13, "denied")
                return _Sized(size)
            return super().stat(*a, **k)

    return WithWal


def test_the_log_file_counts_toward_the_room_a_snapshot_needs_and_room_for_exactly_that_is_enough(client, data_dir, monkeypatch):
    """database + log is what a snapshot can write; one byte less is refused, exactly that is served."""
    wal = 700_000
    monkeypatch.setattr(dbapi, "Path", _wal_of(wal))
    room = {}

    def usage(path):
        return Usage(10**12, 0, sb.live_db_path().stat().st_size + wal + room["delta"])

    monkeypatch.setattr(dbapi, "shutil", _Seen(dbapi.shutil, disk_usage=usage))
    room["delta"] = -1
    short = client.get("/api/database/backup", headers=OWN_PAGE)
    assert short.status_code == 507, "the log file was left out of the room a snapshot needs"
    room["delta"] = 0
    exact = client.get("/api/database/backup", headers=OWN_PAGE)
    assert exact.status_code == 200, "room for exactly the database and its log was refused"
    assert "X-OO-Free-Space-Check" not in exact.headers


def test_a_refusal_for_room_says_at_least_when_a_size_could_not_be_read(client, data_dir, monkeypatch):
    """A figure built from one size is a floor, not an upper bound, and the refusal must not call it 'up to'."""
    monkeypatch.setattr(dbapi, "Path", _wal_of(0, unreadable=True))
    monkeypatch.setattr(dbapi, "shutil", _Seen(dbapi.shutil, disk_usage=lambda p: Usage(10**9, 10**9 - 1, 1)))
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 507
    detail = r.json()["detail"]
    assert "at least" in detail and "up to" not in detail and "could not be read" in detail


def test_a_free_space_that_cannot_be_read_is_not_a_refusal_and_the_response_says_so(client, data_dir, monkeypatch):
    def broken(path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(dbapi, "shutil", _Seen(dbapi.shutil, disk_usage=broken))
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 200
    assert r.headers["X-OO-Free-Space-Check"] == "not-read"


def test_a_log_file_whose_size_cannot_be_read_leaves_the_figure_short_and_the_response_says_so(client, data_dir, monkeypatch):
    """A WAL that exists but cannot be measured would make ``needed`` smaller than the truth without a word."""
    monkeypatch.setattr(dbapi, "Path", _wal_of(0, unreadable=True))
    r = client.get("/api/database/backup", headers=OWN_PAGE)
    assert r.status_code == 200
    assert r.headers["X-OO-Free-Space-Check"] == "not-read"


def test_only_one_snapshot_is_made_at_a_time_and_the_slot_comes_back(client, data_dir, monkeypatch):
    token = dbapi._claim_backup_slot()
    try:
        calls = _forbid_snapshots(monkeypatch)
        r = client.get("/api/database/backup", headers=OWN_PAGE)
        assert r.status_code == 429
        assert not calls and _left_over(data_dir) == []
        assert dbapi._backup_flight is not None and dbapi._backup_flight[0] is token, "the refused request released the OTHER request's claim"
    finally:
        dbapi._release_backup_slot(token, None)
    monkeypatch.undo()
    assert client.get("/api/database/backup", headers=OWN_PAGE).status_code == 200


def test_a_claim_whose_response_never_ran_is_taken_over_after_the_stale_age(client, data_dir):
    dbapi._backup_flight = (object(), time.monotonic() - dbapi._BACKUP_STALE_AFTER_S - 1)
    assert client.get("/api/database/backup", headers=OWN_PAGE).status_code == 200
    assert dbapi._backup_flight is None


def test_a_download_that_was_taken_over_does_not_free_or_overwrite_the_takeovers_claim(data_dir):
    a = dbapi._claim_backup_slot()
    dbapi._backup_flight = (a, time.monotonic() - dbapi._BACKUP_STALE_AFTER_S - 1)
    b = dbapi._claim_backup_slot()  # taken over
    a_dir = data_dir / ".oo-backup-a"
    a_dir.mkdir()
    assert dbapi._backup_flight[0] is b
    dbapi._release_backup_slot(a, a_dir)  # the first request finishes at last
    assert not a_dir.exists(), "a request's own directory is its own to remove"
    assert dbapi._backup_flight is not None and dbapi._backup_flight[0] is b, "the first request freed the takeover's claim"
    with pytest.raises(HTTPException) as busy:
        dbapi._claim_backup_slot()
    assert busy.value.status_code == 429
    dbapi._release_backup_slot(b, None)
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


class _Stop(BaseException):
    """What a shutdown or an interrupt raises in the worker: not an ``Exception``, so ``except Exception`` would miss it."""


def test_a_stop_that_is_not_an_exception_still_frees_the_slot_and_removes_the_directory(data_dir, monkeypatch):
    def stops(dest):
        Path(dest).write_bytes(b"half")
        raise _Stop()

    monkeypatch.setattr(sb, "backup_to", stops)
    with pytest.raises(_Stop):
        dbapi.download_backup(_request({}))
    assert _left_over(data_dir) == []
    assert dbapi._backup_flight is None


def _snapshot_response(data_dir: Path):
    token = dbapi._claim_backup_slot()
    workdir = data_dir / ".oo-backup-test"
    workdir.mkdir()
    snap = workdir / "snapshot.db"
    snap.write_bytes(b"x" * 1000)
    return workdir, dbapi._SnapshotResponse(snap, workdir, token, media_type="application/x-sqlite3")


_SCOPE = {"type": "http", "method": "GET", "headers": [], "extensions": {}}


async def _receive():
    return {"type": "http.disconnect"}


def test_a_response_that_fails_at_its_first_message_still_removes_the_directory_and_frees_the_slot(data_dir):
    workdir, resp = _snapshot_response(data_dir)

    async def gone(message):
        raise OSError("client went away")

    with pytest.raises(OSError, match="client went away"):
        asyncio.run(resp(_SCOPE, _receive, gone))
    assert not workdir.exists()
    assert dbapi._backup_flight is None


def test_a_response_that_fails_in_the_middle_of_the_body_still_removes_the_directory_and_frees_the_slot(data_dir):
    workdir, resp = _snapshot_response(data_dir)

    async def drops_the_body(message):
        if message["type"] == "http.response.body":
            raise OSError("connection reset")

    with pytest.raises(OSError, match="connection reset"):
        asyncio.run(resp(_SCOPE, _receive, drops_the_body))
    assert not workdir.exists()
    assert dbapi._backup_flight is None


def test_a_response_that_is_cancelled_still_removes_the_directory_and_frees_the_slot(data_dir):
    """A response task cancelled once (``wait_for`` here) still gets its directory removed and its claim freed. This case also
    passes without the shield, because a single cancellation is survivable; the cancel-scope case below is the one that pins it."""
    workdir, resp = _snapshot_response(data_dir)

    async def run() -> None:
        async def stalls(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(30)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(resp(_SCOPE, _receive, stalls), 0.3)
        for _ in range(100):  # the removal runs in a worker thread that outlives the cancelled task by a moment
            if not workdir.exists() and dbapi._backup_flight is None:
                return
            await asyncio.sleep(0.05)

    asyncio.run(run())
    assert not workdir.exists()
    assert dbapi._backup_flight is None


def test_a_response_whose_scope_is_cancelled_again_and_again_still_removes_the_directory(data_dir):
    """The server runs the response inside a cancel scope that stays cancelled (anyio's cancellation is level-triggered: every
    later await in the scope is cancelled too), unlike ``wait_for``'s single cancellation. The removal has to run anyway."""
    import anyio

    workdir, resp = _snapshot_response(data_dir)

    async def ok(message):
        return None

    async def run() -> None:
        with anyio.CancelScope() as scope:
            scope.cancel()
            await resp(_SCOPE, _receive, ok)
        for _ in range(100):
            if not workdir.exists() and dbapi._backup_flight is None:
                return
            await asyncio.sleep(0.05)

    anyio.run(run)
    assert not workdir.exists(), "the removal was skipped by a scope that was already cancelled"
    assert dbapi._backup_flight is None


def test_the_removal_does_not_run_on_the_event_loop(data_dir, monkeypatch):
    """Deleting a corpus-sized file can take seconds on some file systems; the old BackgroundTask ran it in the threadpool."""
    workdir, resp = _snapshot_response(data_dir)
    where: list[bool] = []
    real = dbapi._release_backup_slot

    def spy(token, wd):
        where.append(threading.current_thread() is threading.main_thread())
        return real(token, wd)

    monkeypatch.setattr(dbapi, "_release_backup_slot", spy)

    async def ok(message):
        return None

    asyncio.run(resp(_SCOPE, _receive, ok))
    assert where == [False], "the removal ran on the event loop's thread"
    assert not workdir.exists()


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
            shutil.rmtree(d, ignore_errors=True)
