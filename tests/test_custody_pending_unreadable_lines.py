"""A queue line that cannot be read is neither glued to the next record nor erased unseen (R386 class).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``custody_pending.jsonl`` is what a custody write that failed at ingest waits in, and the situations that make a
write fail (a full disk, a power cut) are the ones that cut a queue write short. A line cut short has no newline,
so the next record used to land on it and both were unreadable; ``read_pending`` skipped what it could not read
without a word, and ``drain`` rewrote the file from the records it had read, which erased the unreadable text
for good.

These tests drive the real ``note_failed`` / ``read_pending`` / ``drain`` against real files in a temporary data
directory. The unreadable text carries a marker no log line may repeat: a queue line can hold a url.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.custody import pending
from src.database.models import Article, Base, Source

_MARKER = "token-ZZTOP-must-not-be-logged"
_TORN = '{"article_id":3,"item_hash":null,"url":"https://c.example/' + _MARKER


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    (tmp_path / "data").mkdir()
    pending._REPORTED_UNREADABLE.clear()
    yield
    pending._REPORTED_UNREADABLE.clear()


def _torn_after(*article_ids: int) -> None:
    """Queue ``article_ids``, then leave a line cut short (no trailing newline) at the end of the file."""
    for i in article_ids:
        assert pending.note_failed(i, error="TimeoutError: pool")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(_TORN.encode())


def _ids() -> list[int]:
    return [int(r["article_id"]) for r in pending.read_pending()]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_cut_short_line_is_not_glued_to_the_next_record():
    _torn_after(1, 2)
    assert pending.note_failed(4, error="TimeoutError: pool")
    assert _ids() == [1, 2, 4], "the record queued after a cut-short line is readable"
    lines = pending.pending_path().read_bytes().split(b"\n")
    assert _TORN.encode() in lines, "the cut-short text stands on a line of its own"


def test_a_file_that_ends_in_a_newline_gets_no_blank_line_between_records():
    assert pending.note_failed(1, error="E") and pending.note_failed(2, error="E")
    raw = pending.pending_path().read_bytes()
    assert b"\n\n" not in raw and not raw.startswith(b"\n"), "no blank line at the start of a new file or between records"
    assert _ids() == [1, 2]


def test_an_empty_queue_file_gets_no_leading_blank_line():
    pending.pending_path().write_bytes(b"")
    assert pending.note_failed(1, error="E")
    assert not pending.pending_path().read_bytes().startswith(b"\n") and _ids() == [1]


def test_a_cut_short_line_is_reported_by_line_number_and_length_and_never_by_its_text(caplog):
    _torn_after(1, 2)
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1, 2]
    got = _warnings(caplog)
    assert len(got) == 1, got
    assert "line 3" in got[0] and f"{len(_TORN.encode())} bytes" in got[0], got[0]
    everything = caplog.text + "".join(str(r.args) + str(r.exc_info) for r in caplog.records)
    assert _MARKER not in everything and "c.example" not in everything


def test_the_same_line_is_reported_once_however_often_the_queue_is_read(caplog):
    _torn_after(1)
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            pending.read_pending()
            pending.pending_count()
    assert len(_warnings(caplog)) == 1


def test_a_line_that_is_json_but_not_a_record_is_reported_too(caplog):
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(b"[1,2]\n" + b'{"no_article_id":true}\n')
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1]
    got = _warnings(caplog)
    assert len(got) == 2 and "line 2" in got[0] and "line 3" in got[1], got


def test_a_line_that_is_not_text_does_not_stop_the_queue_from_being_read(caplog):
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(b'\xff\xfe{"article_id":9}\n')
    assert pending.note_failed(2, error="E")
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1, 2]
    assert len(_warnings(caplog)) == 1 and "line 2" in _warnings(caplog)[0]


# -- drain: what happens to the line when the queue is rewritten ------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def custody(monkeypatch, db):
    import src.database.session as dbs

    @contextmanager
    def _scope():
        yield db
        db.commit()

    monkeypatch.setattr(dbs, "session_scope", _scope)
    from src.custody.settings import save_settings

    save_settings({"auto_log_on_ingest": True})


def _article(db, n: int) -> Article:
    src = db.query(Source).filter_by(domain="c.example").first()
    if src is None:
        src = Source(name="c.example", domain="c.example")
        db.add(src)
        db.flush()
    a = Article(url=f"https://c.example/{n}", canonical_url=f"https://c.example/{n}", source_id=src.id, title="t",
                content=f"body {n}", hash=f"hash-{n}", language="en", published_at=datetime.now(UTC),
                created_at=datetime.now(UTC))
    db.add(a)
    db.commit()
    return a


def _side() -> Path:
    return pending.pending_path().with_name(pending.UNREADABLE_FILE)


def test_drain_sets_the_unreadable_line_aside_whole_and_says_so(custody, db, caplog):
    a = _article(db, 1)
    _torn_after(a.id)
    with caplog.at_level(logging.DEBUG):
        res = pending.drain()
    assert res["recorded"] == 1 and res["still_pending"] == 0, res
    assert not pending.pending_path().exists(), "nothing readable is left to wait: the queue file is gone"
    assert _side().read_bytes() == _TORN.encode() + b"\n", "the line is kept byte for byte"
    said = [m for m in _warnings(caplog) if "set aside" in m]
    assert len(said) == 1 and _side().name in said[0] and "line(s) 2;" in said[0], said
    assert _MARKER not in caplog.text


def test_a_line_that_cannot_be_set_aside_stays_in_the_queue_file(custody, db, caplog):
    a = _article(db, 1)
    _torn_after(a.id)
    _side().mkdir()  # opening it for append fails, as a read-only or full volume would
    with caplog.at_level(logging.DEBUG):
        res = pending.drain()
    assert res["recorded"] == 1, res
    assert pending.pending_path().read_bytes() == _TORN.encode() + b"\n", "an unreadable line is never erased unseen"
    assert any("could not be set aside" in m for m in _warnings(caplog))
    assert _MARKER not in caplog.text


def test_the_same_line_is_not_set_aside_twice(custody, db):
    a, b = _article(db, 1), _article(db, 2)
    _torn_after(a.id)
    assert pending.drain()["recorded"] == 1
    first = _side().read_bytes()
    assert pending.note_failed(b.id, error="E")
    assert pending.drain()["recorded"] == 1
    assert _side().read_bytes() == first, "the queue no longer holds the line, so a later rewrite finds nothing to move"


def test_a_drain_that_also_removes_an_entry_for_a_gone_article_sets_the_line_aside_once(custody, db):
    """One drain, two settled entries (one written, one for an article that no longer exists) and the line beside them."""
    a = _article(db, 1)
    _torn_after(a.id, 50)  # article 50 does not exist: counted gone and removed
    res = pending.drain()
    assert res["recorded"] == 1 and res["article_gone"] == 1, res
    assert _ids() == []
    assert _side().read_bytes() == _TORN.encode() + b"\n"


def test_a_line_that_is_gone_from_the_queue_and_comes_back_is_reported_again(caplog):
    """The reported set follows the file: once a line is no longer in it, an identical line later is a new problem."""
    _torn_after(1)
    with caplog.at_level(logging.DEBUG):
        pending.read_pending()
        pending.pending_path().unlink()
        pending.read_pending()  # the file is gone: nothing is unreadable now
        _torn_after(1)
        pending.read_pending()
    assert len(_warnings(caplog)) == 2


def test_lines_set_aside_by_different_drains_accumulate_in_the_side_file(custody, db):
    a, b = _article(db, 1), _article(db, 2)
    _torn_after(a.id)
    assert pending.drain()["recorded"] == 1
    with open(pending.pending_path(), "ab") as fh:  # a second cut-short line, later
        fh.write(b'{"article_id":9,"item_h')
    assert pending.note_failed(b.id, error="E")
    assert pending.drain()["recorded"] == 1
    assert _side().read_bytes() == _TORN.encode() + b"\n" + b'{"article_id":9,"item_h' + b"\n"
