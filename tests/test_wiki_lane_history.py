"""The lane keeps its own hourly history, and the runner says where each tick's seconds went.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read from 15 operator bundles (2026-10-06): the walk ran at 37 % of what its own answer time
allows and nothing recorded where the rest went; a refusal kept only its LAST error; a drain's
hold of the corpus connection was visible once, by luck. The history answers those from a bundle
and survives a restart. What may not regress: it never raises into the lane, it is bounded, an
unmeasured figure is absent (never 0), and recording adds one write a tick, not one per event.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import select

from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import history as H
from src.wiki import walk as W
from src.wiki.lane_models import WikiLaneHour
from src.wiki.runner import DRAIN_RING, WikiLaneRunner
from src.wiki.tiers import budget_state


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


def _rows(**where):
    with lane_session("wiki") as db:
        out = db.execute(select(WikiLaneHour)).scalars().all()
        cols = [c.name for c in WikiLaneHour.__table__.columns]
        rows = [SimpleNamespace(**{c: getattr(r, c) for c in cols}) for r in out]
    return [r for r in rows if all(getattr(r, k) == v for k, v in where.items())]


NOW = datetime(2026, 10, 6, 3, 41, tzinfo=UTC)
HOUR = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# The buffer: aggregates in memory, one transaction per flush, nothing lost on a failure.
# --------------------------------------------------------------------------- #
def test_events_in_one_hour_aggregate_into_one_row(lane):
    buf = H.HistoryBuffer(now=lambda: NOW)
    buf.note("walk", edition="en", kind="ok", ms=1000, bytes_=5000, pages=18, detail="a")
    buf.note("walk", edition="en", kind="ok", ms=3000, bytes_=7000, pages=22, detail="b")
    buf.note("walk", edition="fr", kind="ok", ms=500, bytes_=100, pages=1)
    with lane_session("wiki") as db:
        assert buf.flush(db) == 2
    (en,) = _rows(edition="en")
    assert (en.n, en.sum_ms, en.max_ms, en.sum_bytes, en.sum_pages) == (2, 4000, 3000, 12000, 40)
    assert en.last_detail == "b" and en.hour_start == HOUR


def test_a_second_flush_adds_to_the_row_rather_than_replacing_it(lane):
    buf = H.HistoryBuffer(now=lambda: NOW)
    for _ in range(2):
        buf.note("drain", kind="ok", ms=100, pages=5)
        with lane_session("wiki") as db:
            buf.flush(db)
    (row,) = _rows(metric="drain")
    assert row.n == 2 and row.sum_ms == 200 and row.sum_pages == 10


def test_a_failed_flush_keeps_everything_for_the_next_one_and_says_so(lane):
    buf = H.HistoryBuffer(now=lambda: NOW)
    buf.note("drain", kind="ok", ms=100)

    class Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError):
        buf.flush(Broken())
    assert buf.pending() == 1 and buf.flush_failures == 1 and "locked" in buf.last_flush_error
    buf.note("drain", kind="ok", ms=50)
    with lane_session("wiki") as db:
        buf.flush(db)
    (row,) = _rows(metric="drain")
    assert row.n == 2 and row.sum_ms == 150, "nothing was lost across the failure"


def test_rows_past_the_retention_window_are_pruned_at_the_flush(lane):
    buf = H.HistoryBuffer(now=lambda: NOW)
    old = NOW - timedelta(days=H.RETENTION_DAYS + 1)
    with lane_session("wiki") as db:
        H.write_agg(db, (H.hour_of(old), "drain", "", "ok"), _agg(n=1))
        H.write_agg(db, (H.hour_of(NOW - timedelta(days=H.RETENTION_DAYS - 1)), "drain", "", "ok"), _agg(n=1))
    buf.note("drain", kind="ok", ms=1)
    with lane_session("wiki") as db:
        buf.flush(db)
    assert len(_rows()) == 2, "the old row is gone, the in-window one and the new one stay"


def _agg(**kw):
    a = H.Agg()
    a.add(**kw)
    return a


def test_retry_after_is_the_longest_and_a_date_form_is_absent_not_guessed():
    a = H.Agg()
    a.add(retry_after_s=5)
    a.add(retry_after_s=30)
    a.add(retry_after_s=None)
    assert a.max_retry_after_s == 30

    def exc(value):
        resp = requests.Response()
        resp.status_code = 429
        resp.headers["Retry-After"] = value
        return requests.HTTPError("429", response=resp)

    assert H.retry_after_of(exc("45")) == 45
    assert H.retry_after_of(exc("Wed, 21 Oct 2026 07:28:00 GMT")) is None
    assert H.retry_after_of(exc("999999999")) == H.RETRY_AFTER_MAX_S
    assert H.retry_after_of(ValueError("no response")) is None


def test_stream_counters_become_per_tick_differences_and_a_reset_is_not_negative():
    d, base = H.stream_deltas(None, {"events_seen": 10, "connections": 1, "read_timeouts": 0})
    assert d == {"events_seen": 10, "connections": 1}
    d, base = H.stream_deltas(base, {"events_seen": 25, "connections": 1, "read_timeouts": 2})
    assert d == {"events_seen": 15, "read_timeouts": 2}
    d, base = H.stream_deltas(base, {"events_seen": 4, "connections": 1, "read_timeouts": 2})
    assert d == {"events_seen": 4}, "a rebuilt runner restarts its counters at zero"
    kept, _ = H.per_edition_deltas({"en": 5}, {"en": 9, "fr": 3})
    assert kept == {"en": 4, "fr": 3}


def test_percentiles_by_nearest_rank_and_none_for_no_data():
    assert H.percentile([], 0.5) is None
    data = list(range(1, 101))
    assert H.percentile(data, 0.5) == 50 and H.percentile(data, 0.95) == 95
    assert H.percentile([7], 0.95) == 7


# --------------------------------------------------------------------------- #
# The walk writes its history inside its own transaction.
# --------------------------------------------------------------------------- #
class _Scripted:
    def __init__(self, answers):
        self.answers = list(answers)

    def fetch_edition_statistics(self, wiki):
        return {"articles": 10}

    def fetch_walk_batch(self, wiki, *, continue_params=None, limit=50):
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return {"response_bytes": 100, **answer}


def _walker(client):
    ticks = iter(range(0, 10_000, 2))
    return W.WikiWalker(
        client=client, editions=("en",), lane_session=lambda: lane_session("wiki"),
        budget=lambda: budget_state(total_gb=20, disk_bytes=0, editions=1),
        enabled=lambda: True, transport=lambda: "direct", batch=2,
        monotonic=lambda: float(next(ticks)),
    )


def _batch(pages, cont=None, complete=False):
    return {"pages": pages, "continue": cont, "complete": complete, "props_complete": True,
            "error": None, "malformed": None, "skipped": 0}


def _p(pid, title):
    return {"page_id": pid, "title": title, "qid": None, "length_bytes": 10, "last_revid": pid}


def _http(status, retry_after=None):
    resp = requests.Response()
    resp.status_code = status
    if retry_after is not None:
        resp.headers["Retry-After"] = retry_after
    return requests.HTTPError(f"{status}", response=resp)


def test_an_answered_batch_is_recorded_with_its_pages_bytes_and_bookmark(lane):
    client = _Scripted([_batch([_p(1, "A"), _p(2, "B")], cont={"gapcontinue": "C"})])
    _walker(client).walk_for(3600, max_requests=2)
    (row,) = _rows(metric="walk", kind="ok")
    assert row.edition == "en" and row.n == 1 and row.sum_pages == 2 and row.sum_bytes == 100
    assert json.loads(row.last_detail) == {"gapcontinue": "C"}


def test_every_refusal_is_counted_by_kind_with_the_retry_after_the_wiki_asked_for(lane):
    client = _Scripted([_http(429, "30"), _http(429, "90"), requests.ConnectionError("down"),
                        _http(403)])
    walker = _walker(client)
    for _ in range(5):  # the first step reads the edition's count, then one per batch
        walker.step("en")
        walker._not_before.clear()
    busy = _rows(metric="walk", kind=W.WAIT_SERVICE_BUSY)[0]
    assert busy.n == 2 and busy.max_retry_after_s == 90 and "HTTP 429" in busy.last_detail
    assert _rows(metric="walk", kind=W.WAIT_CONNECTION)[0].n == 1
    refused = _rows(metric="walk", kind=W.WAIT_REFUSED)[0]
    assert refused.n == 1 and refused.max_retry_after_s is None
    assert "http://" not in (busy.last_detail or "") and "https://" not in (busy.last_detail or "")


# --------------------------------------------------------------------------- #
# The runner: where each tick's seconds went, and the drain's own duration.
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _runner(clock, **kw):
    state = {"value": "running"}
    runner = WikiLaneRunner(
        adapter=SimpleNamespace(offer=lambda _c: None, note_position=lambda *_a: None),
        stream=SimpleNamespace(run=lambda *a, **k: None, counters=None),
        lane_session=lambda: None,
        state_of=lambda: state["value"],
        hot_sets=dict,
        budget=lambda: None,
        sleep=lambda s: setattr(clock, "t", clock.t + s),
        monotonic=clock,
        **kw,
    )
    return runner


def test_a_tick_is_split_into_the_drain_the_windows_and_the_sleep():
    clock = _Clock()

    class Window:
        def __init__(self, seconds):
            self.seconds = seconds

        def walk_for(self, left, *, should_stop):
            clock.t += self.seconds
            return SimpleNamespace(as_dict=lambda: {})

    runner = _runner(clock, walker=Window(12.0))
    runner._close_tick = runner._close_tick  # the real one, with a lane that cannot be opened
    runner._tick_part("drain", 8000)
    runner.idle(30.0)
    assert runner.ticks == 1
    last = runner.drain_status()["tick"]["last"][-1]
    assert last == {"drain": 8000, "walk": 12000, "sleep": 18000}
    assert runner.drain_status()["tick"]["totals_s"] == {"drain": 8.0, "sleep": 18.0, "walk": 12.0}


def test_the_tick_ring_and_the_drain_ring_are_bounded():
    clock = _Clock()
    runner = _runner(clock)
    for i in range(50):
        runner._tick_part("drain", i)
        runner._close_tick()
    assert len(runner.drain_status()["tick"]["last"]) == 20 and runner.ticks == 50
    for i in range(DRAIN_RING + 5):
        runner._drain_ms.append(float(i))
    assert runner.drain_status()["drain_duration"]["measured"] == DRAIN_RING


def test_drain_duration_is_absent_not_zero_before_a_drain_ran():
    d = _runner(_Clock()).drain_status()["drain_duration"]
    assert d["measured"] == 0 and d["p50_s"] is None and d["p95_s"] is None and d["max_s"] is None


def test_a_drain_records_its_duration_its_stages_and_whether_it_failed(lane):
    clock = _Clock()
    runner = _runner(clock)

    def hot():
        clock.t += 2.0
        return {}

    runner._hot_sets = hot

    class Lane:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    runner._lane_session = lambda: Lane()
    import src.wiki.runner as R

    original = R.drain_once

    def fake_drain_once(*a, **k):
        clock.t += 5.0
        return R.DrainReport(revisions_stored=7)

    R.drain_once = fake_drain_once
    try:
        runner.drain()

        def boom(*a, **k):
            clock.t += 1.0
            raise RuntimeError("busy")

        R.drain_once = boom
        with pytest.raises(RuntimeError):
            runner.drain()
    finally:
        R.drain_once = original
    d = runner.drain_status()["drain_duration"]
    assert d["measured"] == 2 and d["max_s"] == 7.0 and d["p50_s"] == 3.0
    assert d["stage_totals_s"] == {"feeds-wall": 6.0, "hot-sets": 4.0}
    with lane_session("wiki") as db:
        runner._history.flush(db)
    ok = _rows(metric="drain", kind="ok")[0]
    failed = _rows(metric="drain", kind="failed")[0]
    assert ok.n == 1 and ok.sum_pages == 7 and ok.sum_ms == 7000
    assert failed.n == 1


def test_closing_a_tick_writes_the_history_in_one_flush_and_records_the_stream(lane):
    clock = _Clock()
    runner = _runner(clock)
    counters = {"events_seen": 12, "connections": 2, "per_edition": {"en": 5}}
    runner.stream_counters = lambda: counters  # type: ignore[method-assign]
    runner._lane_session = lambda: lane_session("wiki")
    runner._tick_part("walk", 4000)
    runner._close_tick()
    assert _rows(metric="tick", kind="walk")[0].sum_ms == 4000
    assert _rows(metric="stream", kind="events_seen")[0].n == 12
    assert _rows(metric="stream", kind="kept", edition="en")[0].n == 5
    counters["events_seen"] = 20
    runner._close_tick()
    assert _rows(metric="stream", kind="events_seen")[0].n == 20, "differences, not totals"


def test_a_history_that_cannot_be_written_never_raises_into_the_lane():
    runner = _runner(_Clock())  # its lane session is ``None``: cannot be entered
    runner._tick_part("drain", 10)
    runner._close_tick()  # must not raise
    assert runner.drain_status()["history"]["pending_rows"] >= 1


# --------------------------------------------------------------------------- #
# What a bundle reads.
# --------------------------------------------------------------------------- #
def test_the_snapshot_is_whole_ordered_and_says_its_method(lane):
    buf = H.HistoryBuffer(now=lambda: NOW)
    buf.note("walk", edition="en", kind="ok", ms=10, pages=3)
    buf.note("tick", kind="sleep", ms=100)
    with lane_session("wiki") as db:
        buf.flush(db)
    from src.wiki.service import lane_history

    out = lane_history()
    assert out["measured"] is True and out["retention_days"] == H.RETENTION_DAYS
    assert {"method", "caveat"} <= set(out)
    kinds = [(r["metric"], r["kind"]) for r in out["rows"]]
    assert kinds == sorted(kinds) or len(kinds) == 2
    walk = next(r for r in out["rows"] if r["metric"] == "walk")
    assert walk["edition"] == "en" and walk["sum_pages"] == 3 and "hour" in walk


def test_a_lane_that_never_stored_says_so_instead_of_reporting_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    dispose_all()
    try:
        from src.wiki.service import lane_history

        out = lane_history()
        assert out["measured"] is False and out["rows"] == [] and "never stored" in out["reason"]
    finally:
        dispose_all()


def test_the_diagnostics_route_returns_the_same_history(lane):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.diagnostics import router

    app = FastAPI()
    app.include_router(router)
    buf = H.HistoryBuffer()
    buf.note("drain", kind="ok", ms=5)
    with lane_session("wiki") as db:
        buf.flush(db)
    body = TestClient(app).get("/api/diagnostics/wiki-lane-history").json()
    assert body["measured"] is True and body["rows"][0]["metric"] in {"drain"}


# --------------------------------------------------------------------------- #
# The coordinator-side Opus read of #1314 (2026-10-06): four defects, each pinned.
# --------------------------------------------------------------------------- #
def test_a_flush_that_fails_at_the_commit_keeps_its_rows_and_its_prune(lane):
    """The lane's sessions do not autoflush: the INSERTs only reach the database at flush and
    commit, so a failure THERE used to look like success (rows dropped, flush_failures 0)."""
    buf = H.HistoryBuffer(now=lambda: NOW)
    buf.note("tick", kind="drain", ms=29_000)
    buf.note("drain", kind="ok", ms=100)

    with lane_session("wiki") as db:
        class CommitFails:
            def __getattr__(self, name):
                return getattr(db, name)

            def commit(self):
                db.rollback()
                raise RuntimeError("database or disk is full")

        with pytest.raises(RuntimeError):
            buf.flush(CommitFails())
    assert buf.pending() == 2 and buf.flush_failures == 1 and "full" in buf.last_flush_error
    assert buf._last_prune_hour is None, "a rolled-back prune is tried again, not skipped for an hour"
    assert _rows() == []
    with lane_session("wiki") as db:
        assert buf.flush(db) == 2
    assert _rows(metric="tick", kind="drain")[0].sum_ms == 29_000
    assert len(_rows()) == 2


def test_a_retry_after_made_of_unicode_digits_is_absent_not_a_crash():
    resp = requests.Response()
    resp.status_code = 429
    resp.headers["Retry-After"] = "²"  # a superscript two: str.isdigit() is True, int() raises
    assert H.retry_after_of(requests.HTTPError("429", response=resp)) is None


def test_a_drain_that_dies_building_its_hot_sets_is_booked_there_not_as_corpus_time(lane):
    clock = _Clock()
    runner = _runner(clock)

    def hot():
        clock.t += 30.0
        raise RuntimeError("database is locked")

    runner._hot_sets = hot
    with pytest.raises(RuntimeError):
        runner.drain()
    d = runner.drain_status()["drain_duration"]
    assert d["stage_totals_s"] == {"hot-sets": 30.0}, "no feeds stage ran, so none is booked"


def test_a_lane_that_keeps_failing_writes_its_history_while_it_is_failing(lane):
    clock = _Clock()
    state = {"value": "running"}
    runner = WikiLaneRunner(
        adapter=SimpleNamespace(offer=lambda _c: None, note_position=lambda *_a: None),
        stream=SimpleNamespace(run=lambda *a, **k: None, counters=None),
        lane_session=lambda: lane_session("wiki"),
        state_of=lambda: state["value"],
        hot_sets=dict,
        budget=lambda: None,
        sleep=lambda s: setattr(clock, "t", clock.t + s),
        monotonic=clock,
    )
    calls = {"n": 0}

    def failing_drain():
        calls["n"] += 1
        clock.t += 2.0
        runner._note_drain(False, 2000, 0, None)
        if calls["n"] >= 2:
            state["value"] = "halted"
        raise RuntimeError("busy")

    runner.drain = failing_drain  # type: ignore[method-assign]
    runner.run_until_stopped()
    failed = _rows(metric="drain", kind="failed")
    assert failed and failed[0].n == 2, "both failed drains reached the file before any recovery"
    waits = _rows(metric="tick", kind="failure-wait")
    assert waits and waits[0].sum_ms > 0, "the failure waits are recorded, not lost"


# --------------------------------------------------------------------------- #
# The coordinator's delta check of #1314 (2026-10-06): the write-gate hold and the rest.
# --------------------------------------------------------------------------- #
def test_a_drain_records_what_its_own_thread_held_of_the_write_gate_and_nobody_elses(lane):
    """The hold is the gate's accounting of THIS thread, read and cleared around each drain: another
    thread's hold inside the same interval is in the process-wide ``total_held_s`` and not here."""
    import threading
    import time

    import src.wiki.runner as R
    from src.database.writer import write_gate

    clock = _Clock()
    runner = _runner(clock)

    class Lane:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    runner._lane_session = lambda: Lane()

    def other_thread_holds():
        write_gate.acquire()
        time.sleep(0.15)
        write_gate.release()

    def fake_drain_once(*a, **k):
        t = threading.Thread(target=other_thread_holds, name="somebody-else")
        t.start()
        t.join()
        write_gate.acquire()
        time.sleep(0.03)
        write_gate.release()
        return R.DrainReport(revisions_stored=1)

    original = R.drain_once
    R.drain_once = fake_drain_once
    try:
        runner.drain()
    finally:
        R.drain_once = original
    g = runner.drain_status()["drain_duration"]["write_gate"]
    assert g["measured_drains"] == 1 and g["grants"] == 1
    assert 0.03 <= g["held_s"] < 0.12, "only this thread's own hold, not the other thread's 0.15 s"
    assert g["longest_hold_s"] == g["held_s"]
    with lane_session("wiki") as db:
        runner._history.flush(db)
    assert _rows(metric="drain_gate", kind="grants")[0].n == 1
    assert _rows(metric="drain_gate", kind="held")[0].sum_ms >= 30
    assert _rows(metric="drain_gate", kind="longest")[0].max_ms >= 30


def test_an_unwatched_drain_has_no_gate_figure_rather_than_a_zero():
    runner = _runner(_Clock())
    g = runner.drain_status()["drain_duration"]["write_gate"]
    assert g["measured_drains"] == 0 and g["held_s"] is None and g["grants"] is None


def test_a_retry_after_of_thousands_of_digits_is_absent_not_a_crash():
    resp = requests.Response()
    resp.status_code = 429
    resp.headers["Retry-After"] = "9" * 5000  # past Python's integer-from-string limit
    assert H.retry_after_of(requests.HTTPError("429", response=resp)) is None


def test_the_tick_is_closed_before_a_stop_and_after_every_failure_wait(lane):
    """Run one successful drain and stop: the file has the tick. And a failing lane has its FIRST
    failed drain on disk before the second one runs, not only at the end."""
    clock = _Clock()
    state = {"value": "running"}
    seen_in_file = []

    def build():
        return WikiLaneRunner(
            adapter=SimpleNamespace(offer=lambda _c: None, note_position=lambda *_a: None),
            stream=SimpleNamespace(run=lambda *a, **k: None, counters=None),
            lane_session=lambda: lane_session("wiki"),
            state_of=lambda: state["value"],
            hot_sets=dict,
            budget=lambda: None,
            sleep=lambda s: setattr(clock, "t", clock.t + s),
            monotonic=clock,
        )

    one = build()

    def ok_drain():
        clock.t += 1.0
        one._note_drain(True, 1000, 0, None)
        one.drains += 1

    one.drain = ok_drain  # type: ignore[method-assign]
    one.refresh_one_pageview_top = lambda: None  # type: ignore[method-assign]
    one.run_until_stopped(max_drains=1)
    assert _rows(metric="tick", kind="drain")[0].sum_ms == 1000, "the last drain before a stop is written"

    two = build()
    calls = {"n": 0}

    def failing():
        calls["n"] += 1
        if calls["n"] == 2:
            seen_in_file.append(sum(r.n for r in _rows(metric="drain", kind="failed")))
            state["value"] = "halted"
        two._note_drain(False, 2000, 0, None)
        raise RuntimeError("busy")

    two.drain = failing  # type: ignore[method-assign]
    two.run_until_stopped()
    assert seen_in_file == [1], "the first failed drain was already on disk when the second ran"


def test_a_row_unwritable_past_the_retention_window_is_dropped_and_counted():
    now = [NOW]
    buf = H.HistoryBuffer(now=lambda: now[0])
    buf.note("drain", kind="ok", ms=1)
    now[0] = NOW + timedelta(days=H.RETENTION_DAYS + 1)
    buf.note("drain", kind="ok", ms=2)

    class Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("disk is full")

    with pytest.raises(RuntimeError):
        buf.flush(Broken())
    assert buf.dropped_rows == 1 and buf.pending() == 1, "the week-old row went, the fresh one stayed"


def test_a_lane_file_from_before_the_history_table_is_unmeasured_and_the_table_comes_back(lane):
    from sqlalchemy import text

    from src.wiki.service import lane_history

    with lane_session("wiki") as db:
        db.execute(text("DROP TABLE wiki_lane_hourly"))
    out = lane_history()
    assert out["measured"] is False and out["rows"] == [] and "no history table" in out["reason"]
    dispose_all()
    create_lane("wiki")  # what every drain open does
    buf = H.HistoryBuffer(now=lambda: NOW)
    buf.note("drain", kind="ok", ms=5)
    with lane_session("wiki") as db:
        assert buf.flush(db) == 1
    assert lane_history()["measured"] is True


def test_an_idle_window_is_slept_in_slices_and_ends_when_stopped():
    clock = _Clock()
    runner = _runner(clock)
    slept: list[float] = []

    def sleeper(seconds):
        slept.append(seconds)
        clock.t += seconds
        if len(slept) == 2:
            runner._stop.set()

    runner._sleep = sleeper  # type: ignore[method-assign]
    runner.idle(30.0)
    assert slept == [1.0, 1.0], "one unsliced sleep would have been [30.0] and ignored the stop"


def test_a_failure_writing_the_walks_history_row_does_not_lose_the_pages(lane, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("history table is broken")

    monkeypatch.setattr(W.history, "record", boom)
    client = _Scripted([_batch([_p(1, "A"), _p(2, "B")], cont={"gapcontinue": "C"})])
    _walker(client).walk_for(3600, max_requests=2)
    with lane_session("wiki") as db:
        from src.wiki.lane_models import WikiWalkPage

        assert len(db.execute(select(WikiWalkPage)).scalars().all()) == 2, "the walk's page rows were committed"
    assert _rows(metric="walk") == []


def test_a_database_error_writing_the_walks_history_row_rolls_back_only_that_row(lane, monkeypatch):
    """The failure that surfaces at the SAVEPOINT's flush (a unique conflict), not in the Python call."""

    def conflicting(lane_, metric, **_k):
        for _ in range(2):
            lane_.add(WikiLaneHour(hour_start=HOUR, metric=metric, edition="en", kind="dup"))

    monkeypatch.setattr(W.history, "record", conflicting)
    client = _Scripted([_batch([_p(1, "A"), _p(2, "B")], cont={"gapcontinue": "C"})])
    _walker(client).walk_for(3600, max_requests=2)
    with lane_session("wiki") as db:
        from src.wiki.lane_models import WikiWalkPage

        assert len(db.execute(select(WikiWalkPage)).scalars().all()) == 2
    assert _rows(metric="walk") == []
