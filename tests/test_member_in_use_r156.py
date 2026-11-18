"""A staged backup member another program holds says "in use, try again", never "no key opens it" (row 156).

The restore decrypts a staged SQLCipher member by trying each passphrase it was given (``stream_backup._export_plaintext_with_keys``),
and the lane merge ATTACHes a staged lane member the same way (``lane_merge._attach``). A member another program holds right now fails
every key alike with SQLite's busy code, and both used to answer "none of the available passphrases open it": on a store whose
passphrase cannot be recovered, a person told that may doubt the one key they have. A lock is not about the key, so both now stop at
the first busy answer and say the member is in use. Every case runs on a real file.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.backup import lane_merge, stream_backup
from src.backup.volumes import VolumeError, member_in_use
from src.database import connect as connect_mod
from src.database.connect import connect

_KEY = "a-long-enough-passphrase-for-r156-4Jd"
_OTHER = "another-long-enough-passphrase-8Qx"


@pytest.fixture()
def member(tmp_path):
    p = tmp_path / "custody_log.db"
    c = connect(p, key=_KEY, check_same_thread=False)
    c.execute("CREATE TABLE t(a)")
    c.commit()
    c.close()
    connect_mod._last_good_page_size.clear()
    yield p
    connect_mod._last_good_page_size.clear()


@pytest.fixture()
def opens(monkeypatch):
    """Every open the restore makes, with a short busy timeout (the restore's default is 30 s; the answer is the same)."""
    seen: list[str | None] = []
    real = connect_mod.connect

    def quick(p, **kw):
        seen.append(kw.get("key"))
        kw["timeout"] = 0.05
        return real(p, **kw)

    monkeypatch.setattr(connect_mod, "connect", quick)
    return seen


def _held(p, key=_KEY):
    holder = connect(p, key=key, check_same_thread=False) if key else sqlite3.connect(str(p))
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO t VALUES (1)")
    return holder


def test_a_held_staged_member_is_in_use_and_no_second_key_is_tried(member, opens, tmp_path):
    holder = _held(member)
    try:
        with pytest.raises(VolumeError) as refused:
            stream_backup._export_plaintext_with_keys(member, tmp_path / "plain.db", [_OTHER, _KEY])
    finally:
        holder.rollback()
        holder.close()
    assert str(refused.value) == member_in_use("custody_log.db")
    assert "none of the available" not in str(refused.value)
    assert opens == [_OTHER], "a lock is not about the key: the second key is not tried"


def test_positive_control_wrong_keys_on_a_free_member_still_say_no_key_opens_it(member, opens, tmp_path):
    with pytest.raises(VolumeError) as refused:
        stream_backup._export_plaintext_with_keys(member, tmp_path / "plain.db", [_OTHER])
    assert "none of the available passphrases open it" in str(refused.value)


def test_the_right_key_on_a_free_member_exports_it(member, opens, tmp_path):
    stream_backup._export_plaintext_with_keys(member, tmp_path / "plain.db", [_OTHER, _KEY])
    c = sqlite3.connect(str(tmp_path / "plain.db"))
    try:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (0,)
    finally:
        c.close()


def test_a_busy_error_raised_outside_the_key_check_is_in_use_too(monkeypatch, tmp_path):
    err = sqlite3.OperationalError("database is locked")
    err.sqlite_errorcode = 5

    def held(*_a, **_kw):
        raise err

    tried: list[str] = []

    def held_counted(p, **kw):
        tried.append(kw.get("key"))
        return held(p, **kw)

    monkeypatch.setattr(connect_mod, "connect", held_counted)
    with pytest.raises(VolumeError) as refused:
        stream_backup._export_plaintext_with_keys(tmp_path / "x.db", tmp_path / "y.db", ["k1", "k2"])
    assert str(refused.value) == member_in_use("x.db")
    assert tried == ["k1"]


def test_a_lock_taken_after_the_key_opened_is_in_use_too(member, monkeypatch, tmp_path):
    """A holder that takes the member between the key check and the export gets the same answer."""
    real = connect_mod.connect
    err = sqlite3.OperationalError("database is locked")
    err.sqlite_errorcode = 5

    class _Busy:
        def __init__(self, conn):
            self._c = conn

        def execute(self, *a):
            return self._c.execute(*a)

        def cursor(self):
            raise err

        def close(self):
            self._c.close()

    monkeypatch.setattr(connect_mod, "connect", lambda p, **kw: _Busy(real(p, **kw)))
    with pytest.raises(VolumeError) as refused:
        stream_backup._export_plaintext_with_keys(member, tmp_path / "plain.db", [_KEY])
    assert str(refused.value) == member_in_use("custody_log.db")


def test_a_held_lane_member_is_in_use_at_attach(tmp_path):
    lane = tmp_path / "lane.db"
    c = sqlite3.connect(str(lane))
    c.execute("CREATE TABLE t(a)")
    c.commit()
    c.close()
    holder = _held(lane, key=None)
    live = sqlite3.connect(str(tmp_path / "live.db"), timeout=0.05)
    try:
        with pytest.raises(lane_merge.LaneMergeError) as refused:
            lane_merge._attach(live, lane, [None])
    finally:
        live.close()
        holder.rollback()
        holder.close()
    assert str(refused.value) == member_in_use("lane.db")


def test_a_held_encrypted_lane_member_is_in_use_at_attach_whatever_the_key_order(tmp_path):
    """The production path: an encrypted lane member ATTACHed inside a keyed live connection, a wrong key tried first."""
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    lane = tmp_path / "lane.db"
    c = sqlcipher3.connect(str(lane))
    c.execute(f"PRAGMA key = '{_KEY}'")
    c.execute("PRAGMA cipher_page_size = 4096")
    c.execute("CREATE TABLE t(a)")
    c.commit()
    c.close()
    holder = sqlcipher3.connect(str(lane))
    holder.execute(f"PRAGMA key = '{_KEY}'")
    holder.execute("PRAGMA cipher_page_size = 4096")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO t VALUES (1)")
    live = sqlcipher3.connect(str(tmp_path / "live.db"), timeout=0.05)
    live.execute(f"PRAGMA key = '{_OTHER}'")
    try:
        with pytest.raises(lane_merge.LaneMergeError) as refused:
            lane_merge._attach(live, lane, [_OTHER, _KEY])
        assert live.execute("PRAGMA database_list").fetchall()[-1][1] == "main", "nothing stays attached"
    finally:
        live.close()
        holder.rollback()
        holder.close()
    assert str(refused.value) == member_in_use("lane.db")


def test_a_held_lane_member_does_not_use_up_an_attempt(tmp_path, monkeypatch):
    """Security read B: "try again in a moment" must not spend one of the three tries a lane gets before it is skipped."""
    from src.versioned import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    store.dispose_all()
    entry = {"name": "lanes/wiki.db", "kind": "wiki"}
    held = {"lanes": [{"kind": "wiki", "state": "failed", "in_use": True, "reason": "x"}]}
    for _ in range(lane_merge.MAX_LANE_ATTEMPTS + 2):
        lane_merge.mark_lanes_owed("held", [entry])
        lane_merge.record_lane_outcome("held", held)
    assert lane_merge.lanes_pending("held") is True
    assert lane_merge._read_pending()["held"]["attempts"] == 0
    # Positive control: a real failure is counted, and so is a held member beside one.
    mixed = {"lanes": [*held["lanes"], {"kind": "osm", "state": "failed", "reason": "y"}]}
    for _ in range(lane_merge.MAX_LANE_ATTEMPTS):
        lane_merge.mark_lanes_owed("mixed", [entry])
        lane_merge.record_lane_outcome("mixed", mixed)
    assert lane_merge.lanes_pending("mixed") is False


def test_merge_staged_lanes_marks_a_held_member_in_use(tmp_path, monkeypatch):
    def held(*_a, **_kw):
        raise lane_merge.LaneMemberInUse(member_in_use("wiki.db"))

    monkeypatch.setattr(lane_merge, "merge_lane_file", held)
    (tmp_path / "lanes").mkdir()
    rep = lane_merge.merge_staged_lanes(tmp_path, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    (lane,) = rep["lanes"]
    assert lane["state"] == "failed" and lane["in_use"] is True
    assert lane["reason"] == member_in_use("wiki.db")
