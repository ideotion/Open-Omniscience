"""The all-diagnostics build ends its session's read transaction BETWEEN members.

The build runs every member on one session opened before the first and closed after the last,
so its pooled connection was checked out for the whole 9 to 48 minutes, and the WAL checkpoint
record of the 2026-10-06 bundles names ``bgjob-all-diagnostics`` as the oldest reader (26 s to
3,172 s) beside logs of up to 1.19 GB. ``_release_read_between_members`` hands the connection back at
every member boundary through the app's one safe way to do it (``release_idle_connection``,
which declines a session that has written) and the manifest says how each boundary went.

WHAT THESE TESTS DO NOT CLAIM, because it was measured the other way round: the shared engine runs
pysqlite in its legacy mode, where a SELECT starts no BEGIN, so on an empty corpus SQLite's own
``connection.in_transaction`` was False after all 77 real members. Between members the standing
thing was the pooled session, not a SQLite snapshot. A snapshot pins the log only while a
member's statement or open cursor runs, and that is a member's own time, not the boundary's.
So the checkpoint test below gives its session an explicit ``BEGIN`` (the recipe
``read_snapshot.py`` uses, and what any member that opens a transaction does) to MODEL a pin, and
the first test proves the model by showing the checkpoint blocked when the release is switched off.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
import zipfile

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import QueuePool

from src.api.diagnostics import bundle as _bundle
from src.database.maintenance import StatementTimeout


class _Base(DeclarativeBase):
    pass


class _Note(_Base):
    __tablename__ = "note"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(default="")


def _engine(path, *, explicit_begin):
    """A WAL file behind a small QueuePool. ``explicit_begin`` puts pysqlite out of its legacy
    mode and emits a real BEGIN when a SQLAlchemy transaction starts (the ``read_snapshot``
    recipe), so a session that has read holds a snapshot until its transaction ends."""
    eng = create_engine(
        f"sqlite:///{path}", future=True, poolclass=QueuePool, pool_size=2, max_overflow=0,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _record):
        if explicit_begin:
            dbapi.isolation_level = None
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    if explicit_begin:
        @event.listens_for(eng, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")

    _Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def wal_db(tmp_path):
    """(path, factory): a fresh WAL file, and a function building the engine over it."""
    path = tmp_path / "corpus.db"
    made = []

    def build(explicit_begin=False):
        eng = _engine(path, explicit_begin=explicit_begin)
        made.append(eng)
        return eng

    yield path, build
    for eng in made:
        eng.dispose()


def _commit_a_frame(path):
    """Another connection commits, so the log holds a frame the session's snapshot predates."""
    con = sqlite3.connect(path, timeout=0)
    try:
        con.execute("INSERT INTO note (body) VALUES ('later')")
        con.commit()
    finally:
        con.close()


def _truncate_checkpoint_busy(path):
    """``PRAGMA wal_checkpoint(TRUNCATE)`` from a third connection with no busy wait: ``busy``
    is 1 when a reader still holds the log, 0 when the checkpoint completed."""
    con = sqlite3.connect(path, timeout=0)
    try:
        return con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    finally:
        con.close()


def _run(members, db, **kw):
    """The real writer over stub members; returns (results, manifest)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = _bundle._write_all_diagnostics_zip(members, z, db=db, profile="full", **kw)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        manifest = json.loads(z.read("manifest.json"))
    return results, manifest


def _pin_then_probe(db, eng, path, seen):
    """Member 1 reads on the session and lets another connection commit; member 2 is a NON-db
    member (so it runs with no session of its own) that reads, at the boundary, what a
    checkpoint and the pool see. The name ``db`` is the free variable that makes member 1 a
    db member (``_member_touches_db``), so it runs inline on this thread."""
    def pin():
        db.execute(text("SELECT count(*) FROM note")).scalar()
        _commit_a_frame(path)
        return {"pinned": True}

    def probe():
        seen["busy"] = _truncate_checkpoint_busy(path)
        seen["checked_out"] = eng.pool.checkedout()
        return {"probed": True}

    return [("pin.json", pin), ("probe.json", probe)]


def test_a_pinned_snapshot_is_released_at_the_boundary_so_the_log_can_be_checkpointed(wal_db):
    path, build = wal_db
    eng = build(explicit_begin=True)
    seen: dict = {}
    with Session(eng) as db:
        _run(_pin_then_probe(db, eng, path, seen), db)
    assert seen["busy"] == 0, "the checkpoint completed between the two members"


def test_the_model_really_pins_the_log_when_the_release_is_switched_off(wal_db, monkeypatch):
    """The negative control that makes the test above mean something: with the release a no-op,
    the very same sequence leaves the checkpoint BLOCKED by the session's snapshot."""
    path, build = wal_db
    eng = build(explicit_begin=True)
    monkeypatch.setattr(_bundle, "_release_read_between_members", lambda db: "declined")
    seen: dict = {}
    with Session(eng) as db:
        _run(_pin_then_probe(db, eng, path, seen), db)
    assert seen["busy"] == 1, "a session that kept its snapshot blocks the checkpoint"


def test_the_pooled_connection_goes_back_between_members(wal_db, monkeypatch):
    """On the shared engine's own mode (legacy pysqlite) the boundary's effect is the pool slot:
    the build used to keep one checked out for its whole run."""
    path, build = wal_db
    eng = build(explicit_begin=False)
    seen: dict = {}
    with Session(eng) as db:
        _run(_pin_then_probe(db, eng, path, seen), db)
    assert seen["checked_out"] == 0, "no connection is held while the next member starts"
    # and it WAS held without the release: the first member left the session in a transaction
    monkeypatch.setattr(_bundle, "_release_read_between_members", lambda db: "declined")
    kept: dict = {}
    with Session(eng) as db:
        _run(_pin_then_probe(db, eng, path, kept), db)
    assert kept["checked_out"] == 1


def _pin_how_then_probe(db, eng, path, seen, how):
    """``_pin_then_probe`` with the first member ending the way the long members end: it has
    read and let another connection commit, and THEN it fails, times out or overruns its
    deadline. These are the members whose snapshot matters most, so the boundary after them
    is the one that must not be skipped."""
    def pin():
        db.execute(text("SELECT count(*) FROM note")).scalar()
        _commit_a_frame(path)
        if how == "error":
            raise RuntimeError("the member failed after reading")
        if how == "timeout":
            raise StatementTimeout("the member was aborted at its deadline")
        if how == "partial":
            time.sleep(0.15)
        return {"pinned": True}

    def probe():
        seen["busy"] = _truncate_checkpoint_busy(path)
        seen["checked_out"] = eng.pool.checkedout()
        return {"probed": True}

    return [("pin.json", pin), ("probe.json", probe)]


@pytest.mark.parametrize(
    ("how", "outcome"),
    [("error", "error"), ("timeout", "skipped-deadline"), ("partial", "partial-deadline")],
)
def test_a_member_that_failed_or_overran_still_releases_at_its_boundary(wal_db, monkeypatch, how, outcome):
    """The long members are the ones that fail or overrun, and a release after the ``ok``
    ones only would leave the snapshot pinned exactly where the log grows most. Each
    ending is checked on the member's own outcome (so the case is the one named), then on
    what the next member sees: the log free to checkpoint and no pooled connection held."""
    path, build = wal_db
    eng = build(explicit_begin=True)
    monkeypatch.setattr(_bundle, "_all_diag_db_member_deadline_s", lambda: 0.05)
    seen: dict = {}
    with Session(eng) as db:
        results, manifest = _run(_pin_how_then_probe(db, eng, path, seen, how), db)
    assert results[0]["outcome"] == outcome, results[0]
    assert seen["busy"] == 0, "the checkpoint completed between the two members"
    assert seen["checked_out"] == 0, "no connection is held while the next member starts"
    assert manifest["run"]["read_release"]["released"] >= 1


@pytest.mark.parametrize("how", ["error", "timeout", "partial"])
def test_the_release_after_a_failing_member_is_what_frees_the_log(wal_db, monkeypatch, how):
    """The negative control for the test above: with the release switched off, the same
    ending leaves the member's snapshot standing, so the checkpoint is blocked."""
    path, build = wal_db
    eng = build(explicit_begin=True)
    monkeypatch.setattr(_bundle, "_all_diag_db_member_deadline_s", lambda: 0.05)
    monkeypatch.setattr(_bundle, "_release_read_between_members", lambda db: "declined")
    seen: dict = {}
    with Session(eng) as db:
        _run(_pin_how_then_probe(db, eng, path, seen, how), db)
    assert seen["busy"] == 1, "a snapshot kept past a failed member blocks the checkpoint"


def test_a_member_that_wrote_is_never_rolled_back(wal_db):
    """The release declines a session with flushed work: slower, never wrong. The row the member
    flushed is still there when the owner of the session commits."""
    path, build = wal_db
    eng = build(explicit_begin=False)

    with Session(eng) as db:
        def writes():
            db.add(_Note(body="kept"))
            db.flush()
            return {"wrote": True}

        def after():
            return {"after": True}

        results, manifest = _run([("writes.json", writes), ("after.json", after)], db)
        db.commit()
    with Session(eng) as check:
        assert [n.body for n in check.query(_Note).all()] == ["kept"]
    assert all(r["ok"] for r in results)
    block = manifest["run"]["read_release"]
    assert block["declined"] >= 1, block


def test_the_manifest_says_how_each_boundary_went(wal_db):
    path, build = wal_db
    eng = build(explicit_begin=False)
    with Session(eng) as db:
        def reads():
            db.execute(text("SELECT 1")).scalar()
            return {"x": 1}

        _, manifest = _run([("a.json", reads), ("b.json", reads), ("c.json", lambda: {"y": 2})], db)
    block = manifest["run"]["read_release"]
    assert block["released"] == 2, "the two members that read left a transaction, and each boundary ended it"
    assert block["none_held"] == 1, "the member that never touched the session left nothing to end"
    assert block["declined"] == 0
    assert block["method"] and block["caveat"], "the figures carry what they measure and what they do not"
    assert "does not bound ONE member" in block["caveat"]
    # what the figures claim to measure, and what they do not: the wording is the contract (a method
    # that said a standing reader "is no longer seen" overclaimed, because a statement or a cursor a
    # member left open is not ended by a release)
    assert "ends its session's transaction" in block["method"]
    assert "not ended by it" in block["method"]
    assert "could not say" in block["caveat"]


def test_no_session_means_no_block_not_a_zero(wal_db):
    """A caller that passed no session never released anything, so the manifest has no figure
    (a block of zeros would read as 'looked and found nothing to release')."""
    _, manifest = _run([("a.json", lambda: {"x": 1})], None)
    assert "read_release" not in manifest["run"]


def test_a_session_that_cannot_answer_never_costs_the_bundle(wal_db):
    class _Broken:
        def in_transaction(self):
            raise RuntimeError("no session state")

    results, manifest = _run([("a.json", lambda: {"x": 1}), ("b.json", lambda: {"y": 2})], _Broken())
    assert [r["ok"] for r in results] == [True, True], "both members are in the archive"
    assert manifest["run"]["read_release"]["declined"] == 2, "and the boundary says it could not release"


def test_a_stub_without_a_transaction_state_holds_nothing(wal_db):
    results, manifest = _run([("a.json", lambda: {"x": 1})], object())
    assert results[0]["ok"] is True
    assert manifest["run"]["read_release"]["none_held"] == 1
