"""Row 264 (R696, a follow-up to row 256 / R702 part 2): whoever meets a separate store's switch for its rebuilt copy is REFUSED with the
fixed words, never told "internal error".

``versioned.store`` refuses an open that waited past ``SWAP_WAIT_S`` with :class:`LaneSwapping`. Before this row nothing caught it, so a
route answered the catch-all's 500 ("internal error: ...") and wrote a traceback as for a crash. One test per caller class:

  * a ROUTE that lets it escape answers 409 with ``SWAPPING_WORDS`` and writes no traceback;
  * a BACKGROUND JOB records exactly ``SWAPPING_WORDS`` as its error (also when the worker wrapped it), and logs no traceback; any
    other failure is recorded as before;
  * a caller that CATCHES it itself (the task manager's walk row) keeps answering without the count, as it does for any lane failure.
"""
from __future__ import annotations

import contextlib
import logging
import threading

import pytest

from src.database.connect import set_passphrase
from src.jobs.background import BackgroundJob
from src.versioned import store
from src.versioned.store import SWAPPING_WORDS, LaneSwapping

PASSPHRASE = "a lane shares the corpus passphrase"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    set_passphrase(PASSPHRASE)
    store.dispose_all()
    monkeypatch.setattr(store, "SWAP_WAIT_S", 0.2)
    try:
        yield tmp_path
    finally:
        store.dispose_all()
        set_passphrase(None)


@contextlib.contextmanager
def _switching(kind: str):
    """The lane held as a rebuild's switch holds it, with nothing else open."""
    store.create_lane(kind)
    store.dispose_all()
    with store.held_for_swap(kind):
        yield


def _tracebacks(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.exc_info or "Traceback" in r.getMessage()]


# --- a route ------------------------------------------------------------------------------------------------------------------------


def test_the_app_answers_a_switch_with_its_own_handler_not_the_catch_all():
    from src.api import main

    assert main.app.exception_handlers.get(LaneSwapping) is main.lane_swapping_handler
    assert main.app.exception_handlers.get(Exception) is not main.lane_swapping_handler


def test_a_route_that_meets_the_switch_answers_409_with_the_fixed_words(data_dir, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.main import lane_swapping_handler
    from src.api.medical import router
    from src.medical import store as M

    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(LaneSwapping, lane_swapping_handler)
    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.DEBUG)
    with _switching(M.LANE):
        r = client.get("/api/medical/status")
    assert r.status_code == 409
    assert r.json() == {"detail": SWAPPING_WORDS}
    assert "internal error" not in r.text
    assert _tracebacks(caplog) == []
    # and once the switch has ended, the same route answers
    assert client.get("/api/medical/status").status_code == 200


def test_the_fixed_words_are_keyed_for_the_ui():
    import json
    from pathlib import Path

    en = json.loads((Path(__file__).resolve().parents[1] / "src/static/locales/en.json").read_text(encoding="utf-8"))
    assert SWAPPING_WORDS in en


# --- a background job ---------------------------------------------------------------------------------------------------------------


def _run(job: BackgroundJob) -> dict:
    job.start()
    assert job.join(10)
    return job.status()


def test_a_background_job_that_meets_the_switch_records_the_fixed_words(data_dir, caplog):
    from sqlalchemy import text

    def worker(ctx):
        with store.lane_session("law") as s:
            s.execute(text("SELECT 1"))
        return {"ok": 1}

    caplog.set_level(logging.DEBUG)
    with _switching("law"):
        st = _run(BackgroundJob("test-row264-swap", "T", worker))
    assert st["state"] == "error"
    assert st["error"] == SWAPPING_WORDS
    assert "internal error" not in st["error"] and "LaneSwapping" not in st["error"]
    assert _tracebacks(caplog) == []


def test_a_worker_that_wrapped_the_refusal_still_records_the_fixed_words(caplog):
    def worker(ctx):
        try:
            raise LaneSwapping(SWAPPING_WORDS)
        except LaneSwapping as exc:
            raise RuntimeError("the medical update could not read its store") from exc

    caplog.set_level(logging.DEBUG)
    st = _run(BackgroundJob("test-row264-wrapped", "T", worker))
    assert st["state"] == "error" and st["error"] == SWAPPING_WORDS
    assert _tracebacks(caplog) == []


def test_any_other_failure_is_recorded_as_before(caplog):
    def worker(ctx):
        raise ValueError("an ordinary failure")

    caplog.set_level(logging.DEBUG)
    st = _run(BackgroundJob("test-row264-other", "T", worker))
    assert st["state"] == "error"
    assert st["error"] == "ValueError: an ordinary failure"
    assert any(r.exc_info or "Traceback" in r.getMessage() for r in caplog.records)


# --- a caller that catches it itself ------------------------------------------------------------------------------------------------


def test_the_task_managers_walk_row_still_shows_without_its_count(data_dir, monkeypatch):
    from src.api import jobs

    monkeypatch.setattr("src.wiki.service.lane_service_status", lambda: {"walk": {"state": "walking"}})
    with _switching("wiki"):
        rows = jobs._wiki_walk_jobs()
    assert len(rows) == 1  # the row is shown; only the pages-seen count is absent


def test_no_open_is_left_counted_after_a_refused_one(data_dir):
    with _switching("law"), pytest.raises(LaneSwapping), store.lane_session("law") as s:
        s.connection()
    assert store.in_use("law") == 0 and store.quiet("law")
    done = threading.Event()

    def reader():
        with store.lane_session("law") as s:
            s.connection()
        done.set()

    t = threading.Thread(target=reader)
    t.start()
    t.join(10)
    assert done.is_set()


def test_a_failure_raised_from_none_after_a_refusal_is_recorded_as_itself(caplog):
    def worker(ctx):
        try:
            raise LaneSwapping(SWAPPING_WORDS)
        except LaneSwapping:
            raise ValueError("the fallback failed on its own") from None

    caplog.set_level(logging.DEBUG)
    st = _run(BackgroundJob("test-row264-from-none", "T", worker))
    assert st["error"] == "ValueError: the fallback failed on its own"


# --- the count a switch reads: never a connection that no longer exists, always one that may still be open (fails closed) ------------


class _Record:
    """Stands in for SQLAlchemy's pool record: the count reads only its ``dbapi_connection``."""

    def __init__(self, conn) -> None:
        self.dbapi_connection = conn


class _Conn:
    pass


@contextlib.contextmanager
def _noted(conn, record, **flags):
    store._note("osm", id(conn), record=record, **flags)
    try:
        yield
    finally:
        store._note("osm", id(conn), live=False, out=False)


def test_a_connection_whose_pool_record_was_collected_is_not_counted():
    # The CI failure of row 256's own test (2026-11-21, shard 2 on three PRs): an id left in the open set by a connection that was
    # freed with no ``close`` event, later reused by an unrelated object (it resolved to a ``deque``), so the switch refused a lane
    # nothing had open.
    import gc

    conn = _Conn()
    holder = [_Record(conn)]  # the test's one reference: the store keeps only a weak one
    store._note("osm", id(conn), live=True, out=True, record=holder[0])
    try:
        assert store.in_use("osm") == 1 and not store.quiet("osm")
        holder.clear()
        gc.collect()
        assert store.in_use("osm") == 0 and store.quiet("osm")
    finally:
        store._note("osm", id(conn), live=False, out=False)


def test_a_record_that_now_holds_another_connection_drops_the_old_one():
    first, second = _Conn(), _Conn()
    rec = _Record(first)
    with _noted(first, rec, live=True):
        assert not store.quiet("osm")
        rec.dbapi_connection = second
        assert store.quiet("osm")


def test_what_cannot_be_read_still_counts_as_open():
    # fail closed: a record holding no connection right now is uncertain, and an entry with no record at all is never dropped
    conn, other = _Conn(), _Conn()
    rec = _Record(conn)
    with _noted(conn, rec, live=True, out=True):
        rec.dbapi_connection = None
        assert store.in_use("osm") == 1 and not store.quiet("osm")
    with _noted(other, None, live=True, out=True):
        assert store.in_use("osm") == 1 and not store.quiet("osm")
    assert store.quiet("osm")


def _real_engine(tmp_path):
    return store._build_engine(store.lane("osm"), tmp_path / "osm-probe.db")


def test_on_a_real_pool_a_checked_out_connection_counts_and_an_idle_one_counts_until_closed(data_dir):
    eng = _real_engine(data_dir)
    try:
        conn = eng.connect()
        assert store.in_use("osm") == 1 and not store.quiet("osm")
        conn.close()
        assert store.in_use("osm") == 0 and not store.quiet("osm")  # idle in its pool, still open on the file
        eng.dispose()
        assert store.quiet("osm")
    finally:
        eng.dispose()


def test_on_a_real_pool_a_detached_connection_counts_until_it_is_closed(data_dir):
    eng = _real_engine(data_dir)
    try:
        raw = eng.raw_connection()
        raw.detach()
        raw.cursor().execute("SELECT 1")  # still open on the file
        assert store.in_use("osm") == 1 and not store.quiet("osm")
        eng.dispose()
        assert not store.quiet("osm")  # a disposal does not close a detached connection
        raw.close()
        assert store.quiet("osm")
    finally:
        eng.dispose()


def test_on_a_real_pool_a_connection_freed_with_no_close_event_is_not_counted(data_dir):
    import gc

    eng = _real_engine(data_dir)
    with eng.connect():
        pass
    assert not store.quiet("osm")  # idle in the pool
    del eng  # the pool goes with its engine, never disposed: its connection is freed, and no ``close`` event fires
    gc.collect()
    assert store.quiet("osm")
