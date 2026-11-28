"""R826 stage 3c (row 409): an import's rows bulk-load into a FRESH segment, made without its non-unique indexes and its
search sync triggers, and sealed once: the deferred schema added, every article indexed for search in one pass, the identity
written, the file read back with every reader check, and the registry row moved from ``reserved`` to ``closed``. A load that
never seals leaves nothing readable."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.database import at_rest_state, fts, segment_open, segment_write
from src.database import segments as sg
from src.database.connect import have_driver
from src.database.segment_schema import bulk_split
from src.database.segments import SegmentError
from tests._app_engine import app_sqlite_engine

_PW = "r826-stage-3c-bulk-load-test-passphrase"
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="links and inode checks (POSIX)")


@pytest.fixture()
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "OOS data"
    d.mkdir()
    (d / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    import src.api.unlock as unlock

    monkeypatch.setattr(unlock, "main_db_path", lambda **_: d / "open_omniscience.db")
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", True)
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: False)
    return d


@pytest.fixture()
def shared(data):
    from src.database.models import Base

    path = data / "open_omniscience.db"
    eng = app_sqlite_engine(path)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    con.execute("INSERT INTO sources (id, name, domain) VALUES (7, 's', 's.test')")
    con.execute("INSERT INTO keywords (id, term, normalized_term) VALUES (3, 'harbour', 'harbour')")
    yield con
    segment_write._BULK_LOADING.clear()
    con.close()


def _article(n: int, **extra) -> dict:
    return {
        "url": f"https://s.test/{n}",
        "canonical_url": f"https://s.test/{n}",
        "source_id": 7,
        "title": f"Harbour report {n}",
        "content": f"The harbour authority published figures {n}.",
        "hash": f"h{n}",
        **extra,
    }


def _row(shared, seg_no: int) -> sg.Segment:
    return next(s for s in sg.registry(shared) if s.seg_no == seg_no)


def _load(t, first: int, n: int) -> list[int]:
    ids = t.add_articles([_article(i) for i in range(first, first + n)])
    t.add_rows("keyword_mentions", [{"keyword_id": 3, "article_id": i, "source_id": 7, "count": 1} for i in ids])
    return ids


def test_the_split_defers_only_non_unique_indexes_and_the_search_sync_triggers():
    now, later = bulk_split(segment_open.segment_ddl())
    assert len(now) + len(later) == len(segment_open.segment_ddl())
    folded = [" ".join(s.split()).upper() for s in later]
    assert folded and all(s.startswith("CREATE INDEX ") or s.startswith("CREATE TRIGGER IF NOT EXISTS ARTICLE_FTS_A") for s in folded)
    assert sum(s.startswith("CREATE TRIGGER") for s in folded) == len(fts._FTS_TRIGGERS)
    kept = " ".join(" ".join(s.split()).upper() for s in now)
    assert "CREATE UNIQUE INDEX IX_MENTION_KEYWORD_ARTICLE" in kept, "a unique index is a constraint: it stays for the load"
    assert "ARTICLE_FTS_TITLE_AI" in kept, "the title index keeps its triggers"


@posix_only
@pytest.mark.parametrize("encrypted", [False, pytest.param(True, marks=sqlcipher_only)])
def test_a_sealed_load_is_a_closed_segment_the_reader_opens_with_its_search_built(data, shared, monkeypatch, encrypted):
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: encrypted)
    key = _PW if encrypted else None
    w = segment_write.open_writer(shared, key=key)
    with w.transaction() as t:
        live = t.add_articles([_article(0)])
    load = segment_write.open_bulk_load(shared, key=key, size=50)
    assert _row(shared, load.seg.seg_no).state == "reserved"
    with load.transaction() as t:
        ids = _load(t, 1, 20)
    with load.transaction() as t:
        ids += _load(t, 21, 10)
    assert ids == list(range(load.seg.id_lo, load.seg.id_lo + 30))
    sealed = load.seal()
    assert sealed.state == "closed" and sealed.generation == 1
    assert _row(shared, w.seg.seg_no).state == "open", "the segment the app writes to stays the open one"
    with w.transaction() as t:
        assert t.add_articles([_article(99)])[0] == live[0] + 1
    w.close()
    con = segment_open.open_segment(sealed, key=key)  # every reader check, the exact schema among them
    try:
        assert sg.segment_counters(con) == (1, load.seg.id_lo + 30)
        hits = con.execute("SELECT rowid FROM article_fts WHERE article_fts MATCH 'figures' ORDER BY rowid").fetchall()
        assert [h[0] for h in hits] == ids, "every loaded article is in the search index"
        assert len(con.execute("SELECT rowid FROM article_fts_title WHERE article_fts_title MATCH 'harb*'").fetchall()) == 30
        assert con.execute("SELECT COUNT(*) FROM keyword_mentions").fetchone()[0] == 30
    finally:
        con.close()
    # The index was written the way the delete trigger reads it: a delete after the seal leaves it consistent.
    rw = segment_write._open_read_write(sealed, key)
    try:
        rw.execute("DELETE FROM articles WHERE id = ?", (ids[0],))
        rw.execute("INSERT INTO article_fts(article_fts, rank) VALUES ('integrity-check', 1)")
        assert rw.execute("SELECT COUNT(*) FROM article_fts WHERE article_fts MATCH 'figures'").fetchone()[0] == 29
    finally:
        rw.close()
    stores = json.loads((data / at_rest_state.RECORD_NAME).read_text(encoding="utf-8"))["stores"]
    assert (f"corpus:seg-{sealed.seg_no}" in stores) is encrypted, "named in the at-rest record at the seal, keyed only"


@posix_only
def test_with_the_switch_off_a_bulk_load_makes_nothing(data, shared, monkeypatch):
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    with pytest.raises(SegmentError):
        segment_write.open_bulk_load(shared)
    assert not (data / "corpus").exists()
    assert sg.registry(shared) == [] or all(s.state != "reserved" for s in sg.registry(shared))


@posix_only
def test_a_load_that_never_sealed_is_abandoned_by_the_next_settle_and_never_read(data, shared):
    load = segment_write.open_bulk_load(shared, size=50)
    with load.transaction() as t:
        _load(t, 1, 5)
    seg_no = load.seg.seg_no
    load._con.close()  # the process died here: no seal, no abandon
    segment_write._BULK_LOADING.clear()
    w = segment_write.open_writer(shared)
    try:
        assert _row(shared, seg_no).state == "abandoned", "a file with no identity proves nothing"
        assert w.seg.seg_no != seg_no and w.seg.id_lo > load.seg.id_hi, "its ids are never given out again"
    finally:
        w.close()


@posix_only
def test_a_live_load_is_left_alone_when_the_writer_settles_the_registry(data, shared):
    load = segment_write.open_bulk_load(shared, size=50)
    w = segment_write.open_writer(shared)
    w.close()
    assert _row(shared, load.seg.seg_no).state == "reserved"
    with load.transaction() as t:
        _load(t, 1, 3)
    assert load.seal().state == "closed"


@posix_only
def test_a_row_naming_a_missing_shared_row_is_refused_and_the_load_goes_on(data, shared):
    load = segment_write.open_bulk_load(shared, size=50)
    with load.transaction() as t:
        first = _load(t, 1, 2)
    with pytest.raises(SegmentError), load.transaction() as t:
        t.add_articles([_article(3)])
        t.add_rows("keyword_mentions", [{"keyword_id": 999, "article_id": first[0], "count": 1}])
    assert load.next_id == first[-1] + 1, "the refused transaction's ids were given back"
    with load.transaction() as t:
        assert t.add_articles([_article(3)]) == [first[-1] + 1]
    sealed = load.seal()
    con = segment_open.open_segment(sealed)
    try:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 3
    finally:
        con.close()


@posix_only
def test_a_full_load_raises_segment_full_and_seals_what_it_holds(data, shared):
    load = segment_write.open_bulk_load(shared, size=4)
    with load.transaction() as t:
        _load(t, 1, 3)
    with pytest.raises(segment_write.SegmentFull), load.transaction() as t:
        t.add_articles([_article(4), _article(5)])
    assert load.seal().state == "closed"


@posix_only
def test_an_abandoned_load_removes_its_file_and_its_ids_stay_used(data, shared):
    load = segment_write.open_bulk_load(shared, size=10)
    with load.transaction() as t:
        _load(t, 1, 2)
    path = data / "corpus" / load.seg.file_name
    assert path.exists()
    load.abandon()
    assert not path.exists()
    assert _row(shared, load.seg.seg_no).state == "abandoned"
    with pytest.raises(SegmentError), load.transaction():
        pass
    nxt = sg.reserve_segment(shared, 5)
    assert nxt.id_lo > load.seg.id_hi


@posix_only
def test_a_seal_that_fails_abandons_the_load_and_removes_its_file(data, shared, monkeypatch):
    load = segment_write.open_bulk_load(shared, size=10)
    with load.transaction() as t:
        _load(t, 1, 2)
    path = data / "corpus" / load.seg.file_name

    def boom(con):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(fts, "rebuild_index", boom)
    with pytest.raises(RuntimeError):
        load.seal()
    assert not path.exists()
    assert _row(shared, load.seg.seg_no).state == "abandoned"


@posix_only
def test_a_name_swapped_during_the_load_is_never_sealed(data, shared, tmp_path):
    load = segment_write.open_bulk_load(shared, size=10)
    with load.transaction() as t:
        _load(t, 1, 2)
    path = data / "corpus" / load.seg.file_name
    other = tmp_path / "elsewhere.db"
    os.replace(path, other)
    sqlite3.connect(path).close()  # another file now has the segment's name
    with pytest.raises(SegmentError):
        load.seal()
    assert path.exists(), "a file this load did not make is never removed"
    assert _row(shared, load.seg.seg_no).state == "abandoned"


def test_a_next_id_outside_the_range_is_refused():
    r = sg.Reservation(1, "seg-1.db", 10, 19)
    con = sqlite3.connect(":memory:", isolation_level=None)
    try:
        for bad in (9, 21, True):
            with pytest.raises(SegmentError):
                sg.commit_segment(con, r, next_id=bad)
        sg.commit_segment(con, r, next_id=20)
        assert sg.segment_counters(con) == (1, 20)
    finally:
        con.close()


@posix_only
def test_a_load_opened_beside_a_live_writer_never_settles_the_writers_segment_closed(data, shared):
    w = segment_write.open_writer(shared)
    try:
        # A crash's leftover: a reserved row whose file proves its identity. Settling now would open it and close the
        # live writer's segment under it.
        left = sg.reserve_segment(shared, 5)
        segment_open.create_segment(left)
        load = segment_write.open_bulk_load(shared, size=10)
        assert _row(shared, w.seg.seg_no).state == "open", "the live writer's segment is never closed under it"
        assert _row(shared, left.seg_no).state == "reserved", "left for the next settle with no writer live"
        load.abandon()
        with w.transaction() as t:
            t.add_articles([_article(1)])
    finally:
        w.close()


@posix_only
def test_a_give_up_removes_the_file_even_when_the_registry_step_fails(data, shared, monkeypatch):
    load = segment_write.open_bulk_load(shared, size=10)
    with load.transaction() as t:
        _load(t, 1, 2)
    path = data / "corpus" / load.seg.file_name

    def busy(con, seg_no):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as m:
        m.setattr(segment_write, "mark_abandoned", busy)
        with pytest.raises(sqlite3.OperationalError):
            load.abandon()
    assert not path.exists(), (
        "a reserved row whose file is gone is abandoned safely by the next settle"
    )
    assert load.seg.seg_no not in segment_write._BULK_LOADING
    w = segment_write.open_writer(shared)
    w.close()
    assert _row(shared, load.seg.seg_no).state == "abandoned"


@posix_only
def test_a_schema_changed_during_the_load_is_refused_before_any_trigger_runs(data, shared):
    load = segment_write.open_bulk_load(shared, size=10)
    with load.transaction() as t:
        _load(t, 1, 2)
    other = sqlite3.connect(data / "corpus" / load.seg.file_name, isolation_level=None)
    other.execute("CREATE TRIGGER planted AFTER INSERT ON articles BEGIN SELECT 1; END")
    other.close()
    with pytest.raises(SegmentError), load.transaction() as t:
        t.add_articles([_article(3)])
    with pytest.raises(SegmentError):
        load.seal()
    assert _row(shared, load.seg.seg_no).state == "abandoned"


@posix_only
def test_a_load_left_unsealed_by_its_with_block_is_abandoned(data, shared):
    with segment_write.open_bulk_load(shared, size=10) as load, load.transaction() as t:
        _load(t, 1, 2)
    assert _row(shared, load.seg.seg_no).state == "abandoned"
    assert not (data / "corpus" / load.seg.file_name).exists()
    assert load.seg.seg_no not in segment_write._BULK_LOADING


@posix_only
def test_two_threads_on_one_shared_connection_never_meet_inside_a_registry_transaction(data, shared, monkeypatch):
    """The writer's generation catch-up holds a shared-file transaction open on ``shared``; a reference check on another
    thread over the same connection waits for it instead of reading inside it (and refusing a committed row)."""
    import threading

    inside, other_done = threading.Event(), threading.Event()

    def slow_record_generation(con, seg_no, generation):
        con.execute("BEGIN IMMEDIATE")
        inside.set()
        other_done.wait(1.0)  # with the lock the other thread is blocked here and this times out; without it, it ran
        con.execute("UPDATE corpus_segments SET generation = ? WHERE seg_no = ?", (generation, seg_no))
        con.execute("COMMIT")

    w = segment_write.open_writer(shared)
    try:
        monkeypatch.setattr(segment_write, "record_generation", slow_record_generation)
        result: list[object] = []

        def check():
            inside.wait(5)
            try:
                segment_write.check_shared_references(shared, "keyword_mentions", [{"keyword_id": 3}])
                result.append("ok")
            except SegmentError as exc:
                result.append(exc)
            finally:
                other_done.set()

        t = threading.Thread(target=check)
        t.start()
        with w.transaction() as tx:
            tx.add_articles([_article(1)])
        t.join(5)
        assert result == ["ok"], "the check waited for the other thread's registry transaction to end"
    finally:
        w.close()


# --- stage 4a: a live load's claim is honoured by every process on the data folder -------------------------------------

_CHILD = r"""
import json, os, sqlite3, sys
from pathlib import Path
d = Path(os.environ["OO_DATA_DIR"])
import src.api.unlock as unlock
unlock.main_db_path = lambda **_: d / "open_omniscience.db"
from src.database import segment_open, segment_write
segment_open.SEGMENT_WRITES_ENABLED = True
segment_open._shared_is_encrypted = lambda: False
con = sqlite3.connect(d / "open_omniscience.db", isolation_level=None, check_same_thread=False)
load = segment_write.open_bulk_load(con, size=10)
print(load.seg.seg_no, flush=True)
sys.stdin.readline()
"""


def _claims(data: Path) -> list[str]:
    return sorted(p.name for p in (data / "leases").glob("segment-load.*.claim")) if (data / "leases").exists() else []


@posix_only
def test_another_process_s_live_load_is_never_abandoned_and_a_dead_one_s_is(data, shared):
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", _CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
    try:
        seg_no = int(child.stdout.readline())
        assert len(_claims(data)) == 1, "the child's claim is on disk"
        segment_write.open_writer(shared).close()  # a settle in THIS process, which knows nothing of the child's load
        assert _row(shared, seg_no).state == "reserved", "another process's live load is left alone"
    finally:
        child.kill()
        child.wait(10)
    w = segment_write.open_writer(shared)
    w.close()
    assert _row(shared, seg_no).state == "abandoned", "its owner is gone: a crash's leftover"
    assert _claims(data) == [], "the dead owner's claim was removed"


@posix_only
def test_an_unreadable_claim_holds_every_reservation(data, shared):
    load = segment_write.open_bulk_load(shared, size=10)
    seg_no = load.seg.seg_no
    load._con.close()
    segment_write._BULK_LOADING.clear()  # as if THIS process had died: only the claim file can speak for the load now
    (data / "leases" / ("segment-load." + "e" * 32 + ".claim")).write_text("{not json", encoding="utf-8")
    segment_write.open_writer(shared).close()
    assert _row(shared, seg_no).state == "reserved", "a claim that cannot be read is never taken as no claim"


def test_an_unreadable_claim_older_than_ten_seconds_is_a_leftover(data, shared):
    """As ``corpus_lease`` treats an unreadable lease: held while new, removed once old (security reads on stage 4a)."""
    load = segment_write.open_bulk_load(shared, size=10)
    seg_no = load.seg.seg_no
    load._con.close()
    segment_write._BULK_LOADING.clear()
    segment_write._rewrite_claim()  # this process's own claim goes with its loads
    bad = data / "leases" / ("segment-load." + "e" * 32 + ".claim")
    bad.write_text("{not json", encoding="utf-8")
    old = bad.stat().st_mtime - segment_write._UNREADABLE_CLAIM_S - 5
    os.utime(bad, (old, old))
    segment_write.open_writer(shared).close()
    assert not bad.exists() and _row(shared, seg_no).state == "abandoned"


def test_no_bulk_load_starts_when_this_process_cannot_be_recorded(data, shared, monkeypatch):
    """An empty owner record (psutil failed) would make a claim nobody can ever judge dead: the load is refused before
    anything is reserved."""
    from src.safety import process_owner

    monkeypatch.setattr(process_owner, "owner_record", lambda: {})
    before = [(s.seg_no, s.state) for s in sg.registry(shared)]
    with pytest.raises(SegmentError):
        segment_write.open_bulk_load(shared, size=10)
    assert [(s.seg_no, s.state) for s in sg.registry(shared)] == before
    assert _claims(data) == [] and not segment_write._RESERVING[0]


@posix_only
def test_this_process_s_claim_names_its_live_loads_and_goes_when_they_end(data, shared):
    assert _claims(data) == []
    a = segment_write.open_bulk_load(shared, size=10)
    b = segment_write.open_bulk_load(shared, size=10)
    (claim,) = (data / "leases").glob("segment-load.*.claim")
    rec = json.loads(claim.read_text(encoding="utf-8"))
    assert rec["seg_nos"] == sorted([a.seg.seg_no, b.seg.seg_no]) and rec["reserving"] is False
    assert oct(os.stat(data / "leases").st_mode & 0o777) == "0o700"
    with a.transaction() as t:
        _load(t, 1, 2)
    a.seal()
    assert json.loads(claim.read_text(encoding="utf-8"))["seg_nos"] == [b.seg.seg_no]
    b.abandon()
    assert _claims(data) == []
