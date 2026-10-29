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
from src.custody.log import CustodyLog
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


def test_a_line_of_only_whitespace_is_blank_not_unreadable(caplog):
    """A hand-edited file (CRLF endings, a stray space) is not reported as damaged."""
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(b"   \n\r\n\t\n")
    assert pending.note_failed(2, error="E")
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1, 2]
    assert _warnings(caplog) == []


def test_a_line_that_is_json_but_not_a_record_is_reported_too(caplog):
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(b"[1,2]\n" + b'{"no_article_id":true}\n')
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1]
    got = _warnings(caplog)
    assert len(got) == 2 and "line 2" in got[0] and "line 3" in got[1], got


@pytest.mark.parametrize("line", [b'\xff{"article_id":9}\n', b'\xff\xfe{"article_id":9}\n'], ids=["invalid-utf8", "utf16-bom-lookalike"])
def test_a_line_that_is_not_text_does_not_stop_the_queue_from_being_read(caplog, line):
    """The first is bytes ``json.loads`` cannot decode at all (UnicodeDecodeError); ``FF FE`` it reads as a UTF-16 byte-order mark and
    fails as a JSON error instead, which is why both are here: a tidy-up of ``except ValueError`` to ``except JSONDecodeError`` must
    fail on the first."""
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(line)
    assert pending.note_failed(2, error="E")
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1, 2]
    assert len(_warnings(caplog)) == 1 and "line 2" in _warnings(caplog)[0]


def test_a_line_nested_too_deep_to_parse_is_one_unreadable_line_not_an_error(caplog):
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(b"[" * 200000 + b"\n")
    with caplog.at_level(logging.DEBUG):
        assert _ids() == [1]
    assert len(_warnings(caplog)) == 1 and "line 2" in _warnings(caplog)[0]


@pytest.mark.parametrize("line", [b'{"article_id":"x"}', b'{"article_id":"7"}', b'{"article_id":true}', b'{"article_id":1.5}',
                                  b'{"article_id":null}', b'{"id":1}', b'{"article_id":0}', b'{"article_id":-3}',
                                  b'{"article_id":9223372036854775808}'],
                         ids=["text", "digit-text", "bool", "float", "null", "no-id", "zero", "negative", "over-sqlite-int"])
def test_a_line_whose_article_id_is_not_a_row_id_is_not_a_record(line):
    """``{"article_id":true}`` used to be drained as article 1, a text id stopped every drain at its ``int()``, and an id past
    SQLite's integer made every drain's column read raise ``OverflowError`` (no entry without a hash was ever written)."""
    assert pending.note_failed(1, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(line + b"\n")
    assert _ids() == [1]


def _number_or_file_name(arg) -> bool:
    """A log argument that cannot carry the text of a line: a number, a list of numbers ("2, 3") or the side file's name."""
    return isinstance(arg, int) or arg == pending.UNREADABLE_FILE or str(arg).replace(", ", "").isdigit()


def test_the_log_lines_the_queue_writes_carry_numbers_and_the_file_name_only(caplog):
    """The log call is handed the text of nothing: every argument is a number or a digit list or the side file's name."""
    _torn_after(1, 2)
    with caplog.at_level(logging.DEBUG, logger=pending._LOG.name):
        pending.read_pending()
    assert caplog.records
    for r in caplog.records:
        for arg in (r.args if isinstance(r.args, tuple) else ()):
            assert _number_or_file_name(arg), (r.msg, arg)


def test_a_read_in_progress_waits_for_an_append_in_progress(monkeypatch, caplog):
    """An append of many records is several writes; a read between two of them would see a half line and report an unreadable
    one that is not there. The read takes the file lock, so it waits for the append to finish."""
    import threading

    real = pending._append_bytes
    seen: dict = {}
    reader = threading.Thread(target=lambda: seen.setdefault("ids", _ids()))

    def two_writes(p, data):
        half = len(data) // 2
        real(p, data[:half])
        reader.start()
        reader.join(0.3)
        seen["reader_waited"] = reader.is_alive()  # it must still be waiting for the lock this append holds
        real(p, data[half:])

    monkeypatch.setattr(pending, "_append_bytes", two_writes)
    with caplog.at_level(logging.DEBUG):
        assert pending.note_failed(1, error="E")
        reader.join(5)  # the append has returned and released the lock, so the read can run now
    assert seen["reader_waited"] is True and seen["ids"] == [1]
    assert _warnings(caplog) == []


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
    assert len([m for m in _warnings(caplog) if "is not a usable record" in m]) == 1, "the drain's own read reports the line once"
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


def test_a_clean_drain_sets_nothing_aside_and_logs_nothing(custody, db, caplog):
    a = _article(db, 1)
    assert pending.note_failed(a.id, error="E")
    with caplog.at_level(logging.DEBUG):
        assert pending.drain()["recorded"] == 1
    assert not _side().exists() and _warnings(caplog) == []


def test_a_line_cut_short_while_a_drain_runs_is_set_aside_with_the_others(custody, db):
    """The final re-read exists to honour what changed while the drain ran: an ingest thread's write cut short after the drain's
    first read must end up in the side file, not be dropped with the settled entries."""
    a = _article(db, 1)
    assert pending.note_failed(a.id, error="E")

    def factory():
        with open(pending.pending_path(), "ab") as fh:
            fh.write(b'{"article_id":77,"cut')
        return CustodyLog()

    assert pending.drain(log_factory=factory)["recorded"] == 1
    assert _side().read_bytes() == b'{"article_id":77,"cut\n'


def test_a_cut_short_copy_in_the_side_file_does_not_take_the_next_copy_onto_its_line(custody, db):
    a = _article(db, 1)
    _side().write_bytes(b'{"article_id":7,"c')  # an earlier copy that stopped part way (a full disk)
    _torn_after(a.id)
    assert pending.drain()["recorded"] == 1
    assert _side().read_bytes().split(b"\n") == [b'{"article_id":7,"c', _TORN.encode(), b""]


def test_a_drain_with_a_limit_keeps_the_entries_it_did_not_take(custody, db):
    a, b = _article(db, 1), _article(db, 2)
    _torn_after(a.id, b.id)
    res = pending.drain(limit=1)
    assert res["recorded"] == 1 and res["still_pending"] == 1, res
    assert _ids() == [b.id]
    assert _side().read_bytes() == _TORN.encode() + b"\n"


def test_an_entry_queued_while_a_drain_runs_survives_the_rewrite(custody, db):
    """The rewrite works from a re-read of the file, not from what the drain read at its start."""
    a = _article(db, 1)
    assert pending.note_failed(a.id, error="E")

    def factory():
        assert pending.note_failed(99, error="E")
        return CustodyLog()

    assert pending.drain(log_factory=factory)["recorded"] == 1
    assert _ids() == [99]


def test_a_file_that_cannot_be_read_at_the_final_re_read_is_left_as_it_is(custody, db, monkeypatch, caplog):
    """A transient read error used to read as an empty queue, and the rewrite then deleted every record still owed and every
    unreadable line, with no log line and a clean-looking result."""
    a, b = _article(db, 1), _article(db, 2)
    _torn_after(a.id, b.id)
    before = pending.pending_path().read_bytes()
    real, calls = pending._read_bytes, []

    def flaky():
        calls.append(1)
        if len(calls) == 2:  # the first is the drain's own read, the second its re-read before the rewrite
            raise OSError(5, "Input/output error")
        return real()

    monkeypatch.setattr(pending, "_read_bytes", flaky)
    with caplog.at_level(logging.DEBUG):
        res = pending.drain(limit=1)
    monkeypatch.setattr(pending, "_read_bytes", real)
    assert res["recorded"] == 1 and res["queue_read_error"] == "OSError", res
    assert pending.pending_path().read_bytes() == before, "the queue file is exactly as it was"
    assert not _side().exists()
    assert any("re-read the pending file" in m for m in _warnings(caplog))


def test_a_file_that_cannot_be_read_reads_as_no_records_and_says_so(monkeypatch, caplog):
    assert pending.note_failed(1, error="E")

    def boom():
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(pending, "_read_bytes", boom)
    with caplog.at_level(logging.DEBUG):
        assert pending.read_pending() == []
    assert any("could not read the pending file" in m for m in _warnings(caplog))


def test_a_queue_path_that_cannot_be_read_is_not_an_empty_queue(caplog):
    """Only a file that is not there is an empty queue: any other read error reaches the callers as an error (a rewrite from an
    "empty" read deletes every record still owed). A directory at the path is a read error that needs no patching."""
    pending.pending_path().mkdir()
    with pytest.raises(OSError) as err:
        pending._read_all()
    assert not isinstance(err.value, FileNotFoundError)
    with caplog.at_level(logging.DEBUG):
        assert pending.read_pending() == []
    assert any("could not read the pending file" in m for m in _warnings(caplog))


def _read_bytes_refused(monkeypatch) -> None:
    """Reading the queue file raises ``PermissionError`` (``chmod`` does not do it when the tests run as root)."""
    real = Path.read_bytes

    def read_bytes(self):
        if self == pending.pending_path():
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def test_a_read_parses_outside_the_file_lock(custody, db, monkeypatch):
    """The lock is held for the bytes only: parsing a large queue under it made every ingest thread's ``note_failed`` wait (measured
    211 ms against 47 ms with 60,000 records)."""
    a = _article(db, 1)
    assert pending.note_failed(a.id, error="E")
    real, held = pending._parse, []

    def parse(data):
        held.append(pending._LOCK.locked())
        return real(data)

    monkeypatch.setattr(pending, "_parse", parse)
    pending.read_pending()
    pending.drain()
    assert held[:2] == [False, False], held  # read_pending, and the drain's first read; the final re-read holds it by design


def test_a_permission_error_is_not_an_empty_queue(monkeypatch):
    assert pending.note_failed(1, error="E")
    _read_bytes_refused(monkeypatch)
    with pytest.raises(PermissionError):
        pending._read_all()


def test_a_drain_of_a_queue_that_cannot_be_read_says_so_and_leaves_the_file(custody, db, monkeypatch, caplog):
    """The first read of a drain used to come back as an empty queue: a clean-looking result and nothing in it to say the owed
    entries were not looked at."""
    a = _article(db, 1)
    _torn_after(a.id)
    before = pending.pending_path().read_bytes()
    with monkeypatch.context() as m, caplog.at_level(logging.DEBUG):
        _read_bytes_refused(m)
        res = pending.drain()
    assert res == {"recorded": 0, "already_present": 0, "article_gone": 0, "still_pending": 0,
                   "queue_read_error": "PermissionError"}, res
    assert pending.pending_path().read_bytes() == before and not _side().exists()
    assert any("nothing was drained" in m for m in _warnings(caplog))


def test_still_pending_after_a_failed_re_read_counts_what_the_drain_read_and_did_not_settle(custody, db, monkeypatch):
    """Two entries are read: one carries the hash it needs and is recorded; the other needs a column read, which fails, so it
    stays. The final re-read then fails: what is left is the one entry, neither none nor both."""
    assert pending.note_failed(1, item_hash="hash-1", error="E")
    assert pending.note_failed(2, error="E")

    def pool_timeout():
        raise RuntimeError("pool timeout")

    def refused():
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(pending, "_read_all", refused)
    res = pending.drain(session_factory=pool_timeout)
    assert res["recorded"] == 1 and res["still_pending"] == 1, res
    assert res["queue_read_error"] == "OSError" and res["read_error"], res


def _windows(line: bytes, size: int = 12) -> set[str]:
    return {line[i:i + size].decode("latin-1") for i in range(len(line) - size + 1)}


def test_no_log_record_of_a_read_or_a_drain_carries_any_part_of_an_unreadable_line(custody, db, monkeypatch, caplog):
    """A marker past the first bytes of a line lets a log of the line's PREFIX pass, so every 12-byte window of each unreadable
    line is looked for in every message, argument and traceback: a read, a drain that sets the lines aside, a drain whose
    set-aside fails, and a drain whose final re-read fails."""
    a = _article(db, 1)
    lines = [_TORN.encode(), b'{"article_id":"https://c.example/' + _MARKER.encode() + b'"}']
    assert pending.note_failed(a.id, error="E")
    with open(pending.pending_path(), "ab") as fh:
        fh.write(lines[0] + b"\n" + lines[1] + b"\n")
    with caplog.at_level(logging.DEBUG):
        pending.read_pending()
        _side().mkdir()  # the set-aside fails, and both lines stay in the queue
        pending.drain()
        _side().rmdir()
        assert pending.note_failed(a.id, error="E")
        pending.drain()  # the set-aside succeeds
        assert _side().read_bytes() == b"".join(line + b"\n" for line in lines)
        assert pending.note_failed(a.id, error="E")
        with monkeypatch.context() as m:
            m.setattr(pending, "_read_all", lambda: (_ for _ in ()).throw(OSError(5, "Input/output error")))
            pending.drain()
    logged = "\n".join(f"{r.getMessage()} {r.args} {r.exc_info} {r.exc_text}" for r in caplog.records)
    for line in lines:
        leaked = sorted(w for w in _windows(line) if w in logged)
        assert not leaked, leaked[:3]
    said = [r for r in caplog.records if "set aside" in r.getMessage() and "could not" not in r.getMessage()]
    assert len(said) == 1 and all(_number_or_file_name(x) for x in said[0].args), said[0].args


def test_the_text_of_a_line_with_a_text_article_id_never_reaches_a_log_or_stops_the_drain(custody, db, caplog):
    a = _article(db, 1)
    assert pending.note_failed(a.id, error="E")
    line = b'{"article_id":"https://c.example/' + _MARKER.encode() + b'"}\n'
    with open(pending.pending_path(), "ab") as fh:
        fh.write(line)
    with caplog.at_level(logging.DEBUG):
        res = pending.drain()
    assert res["recorded"] == 1, res
    assert _side().read_bytes() == line
    assert _MARKER not in caplog.text
