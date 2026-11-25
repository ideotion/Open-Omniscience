"""A staged backup member another program holds says "in use, try again", never "no key opens it" (row 156).

The restore opens a staged SQLCipher member in place by trying each passphrase it was given (``stream_backup._adopt_encrypted_member``, row 410-A),
and the lane merge ATTACHes a staged lane member the same way (``lane_merge._attach``). A member another program holds right now fails
every key alike with SQLite's busy code, and both used to answer "none of the available passphrases open it": on a store whose
passphrase cannot be recovered, a person told that may doubt the one key they have. A lock is not about the key, so both now stop at
the first busy answer and say the member is in use. Every case runs on a real file.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.backup import lane_merge, staged_key, stream_backup
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
    """Every keyed open the restore makes (row 410-A: the member is adopted in place, ``staged_key._open_with``), with a
    short busy timeout (the restore's default is 5 s; the answer is the same). Records which passphrase each open used."""
    seen: list[bytes] = []
    real = staged_key._open_with

    def counted(path, secret, page_size, **kw):
        if not seen or seen[-1] != secret:
            seen.append(secret)
        return real(path, secret, page_size, **kw)

    monkeypatch.setattr(staged_key, "BUSY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(staged_key, "_open_with", counted)
    return seen


def _held(p, key=_KEY):
    holder = connect(p, key=key, check_same_thread=False) if key else sqlite3.connect(str(p))
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO t VALUES (1)")
    return holder


def test_a_held_staged_member_is_in_use_and_no_second_key_is_tried(member, opens):
    holder = _held(member)
    try:
        with pytest.raises(VolumeError) as refused:
            stream_backup._adopt_encrypted_member(member, [_OTHER, _KEY])
    finally:
        holder.rollback()
        holder.close()
    assert str(refused.value) == member_in_use("custody_log.db")
    assert "none of the available" not in str(refused.value)
    assert opens == [_OTHER.encode()], "a lock is not about the key: the second key is not tried"
    assert not staged_key.is_keyed(member)


def test_positive_control_wrong_keys_on_a_free_member_still_say_no_key_opens_it(member, opens):
    with pytest.raises(VolumeError) as refused:
        stream_backup._adopt_encrypted_member(member, [_OTHER])
    assert "none of the available passphrases open it" in str(refused.value)
    assert not staged_key.is_keyed(member)


def test_the_right_key_on_a_free_member_adopts_it_in_place(member, opens):
    before = member.read_bytes()[:16]
    stream_backup._adopt_encrypted_member(member, [_OTHER, _KEY])
    try:
        assert staged_key.key_for(member).origin == "member"
        assert member.read_bytes()[:16] == before != b"SQLite format 3\x00", "never exported, never rewritten in clear"
        c = staged_key.open_staged(member)
        try:
            assert c.execute("SELECT count(*) FROM t").fetchone() == (0,)
        finally:
            c.close()
    finally:
        staged_key.forget(member)


def test_a_file_failure_is_named_by_its_class_and_never_its_words(monkeypatch, tmp_path):
    def denied(*_a, **_kw):
        raise PermissionError("/secret/path denied")

    monkeypatch.setattr(staged_key, "_open_with", denied)
    with pytest.raises(VolumeError) as refused:
        stream_backup._adopt_encrypted_member(tmp_path / "x.db", ["k1"])
    assert "PermissionError" in str(refused.value) and "/secret/path" not in str(refused.value)


def test_a_driver_failure_is_not_named(monkeypatch, tmp_path):
    """A file the driver cannot open at all reads as no key opening it, never with the driver's words."""
    p = tmp_path / "x.db"
    p.write_bytes(b"horse-battery" * 100)
    with pytest.raises(VolumeError) as refused:
        stream_backup._adopt_encrypted_member(p, ["k1"])
    assert "none of the available passphrases open it" in str(refused.value)
    assert "horse-battery" not in str(refused.value) and "OperationalError" not in str(refused.value)


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
