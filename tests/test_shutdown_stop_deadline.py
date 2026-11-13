"""R689: every registered writer job notices a stop within the shutdown's deadline, and one that does not can write nothing after it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What these pin (R689 (1); the disposal side, (2), is the data durability lane's ``src/database/after_shutdown.py``). The bulk summary/translation queue looked at its stop only after a whole generation (minutes on a CPU model),
so the shutdown's 5 s ``stop_all_jobs`` gave up on it and disposed the engine under it: now a stop during a long generation ends
the run within a fraction of a second, PAUSED, nothing stored for the article in flight, and the resume stores every article once.
The Insights backlog looked at its stop only between 300-article batches: now between articles.
"""

from __future__ import annotations

import threading
import time

from src.jobs import background as bg
from src.jobs import llm_bulk_queue as lbq
from tests import test_llm_bulk_queue as _bq
from tests.test_llm_bulk_queue import _FakeLlm, _seed, _summaries, _use

store = _bq.store
queue = _bq.queue


class _SlowFirstLlm(_FakeLlm):
    """The first generation hangs until ``hold`` is set (a CPU model on a long article); later ones answer at once."""

    def __init__(self):
        super().__init__()
        self.hold = threading.Event()
        self.started = threading.Event()
        self._first = True

    def generate(self, prompt, **kw):
        if self._first:
            self._first = False
            self.started.set()
            self.hold.wait(30)
        return super().generate(prompt, **kw)


def test_a_stop_during_a_long_generation_pauses_the_run_within_the_deadline_and_resume_stores_each_once(queue, monkeypatch):
    fake = _SlowFirstLlm()
    _use(monkeypatch, fake)
    ids = _seed(3)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    try:
        assert fake.started.wait(10), "the generation never started"
        t0 = time.monotonic()
        left = bg.stop_all_jobs(5.0)
        took = time.monotonic() - t0
        assert lbq.KIND not in left, "the shutdown gave up on the queue: it would dispose the engine under a writer"
        assert took < 2.0, f"the stop waited for the generation ({took:.1f} s)"
        entry = {e["id"]: e for e in queue.snapshot()["entries"]}[eid]
        assert entry["state"] == "paused", entry
        assert [_summaries(a) for a in ids] == [0, 0, 0], "an article was stored from a generation the stop abandoned"
    finally:
        fake.hold.set()  # the abandoned generation ends in its own thread; its result is dropped
    time.sleep(0.3)
    assert [_summaries(a) for a in ids] == [0, 0, 0], "the abandoned generation stored its result after the stop"
    assert queue.resume() and lbq._JOB.join(15)
    assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "done"
    assert [_summaries(a) for a in ids] == [1, 1, 1], "the resume stored an article twice or skipped one"


def test_a_task_manager_stop_during_a_generation_cancels_the_run_and_stores_nothing_of_it(queue, monkeypatch):
    fake = _SlowFirstLlm()
    _use(monkeypatch, fake)
    ids = _seed(2)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    try:
        assert fake.started.wait(10)
        assert queue.cancel(eid)
        assert lbq._JOB.join(3), "the Stop waited for the generation"
        assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "cancelled"
    finally:
        fake.hold.set()
    assert [_summaries(a) for a in ids] == [0, 0]


def test_the_insights_backlog_stops_between_articles_not_between_batches(monkeypatch):
    from src.analytics import store as an_store
    from src.database.session import session_scope

    _seed(5)
    calls: list[int] = []

    def _index(session, art, **_kw):
        calls.append(art.id)
        return {"article_id": art.id, "mentions": 0}

    monkeypatch.setattr(an_store, "index_article", _index)
    with session_scope() as s:
        r = an_store.backfill_corpus(s, extractor=None, limit=300, should_stop=lambda: len(calls) >= 2)
    assert r.get("stopped") is True and len(calls) == 2, (r, calls)
    assert r["remaining"] is None, "a stopping batch still counted the backlog"

    # The job: a stop raised during a batch ends the drain after the article in hand, and it says it stopped.
    from src.jobs import insights_backlog as ib

    class _Ctx:
        def __init__(self):
            self.n = 0

        @property
        def stopping(self):
            return len(calls) >= 3

        def set_progress(self, **_kw):
            self.n += 1

    monkeypatch.setattr(ib, "_busy_reason", lambda: None)
    monkeypatch.setattr("src.scheduler.maintenance.note_page_drain", lambda **_kw: None)
    out = ib._drain(_Ctx())
    assert out["ended"] == "stopping" and len(calls) == 3, (out, calls)
