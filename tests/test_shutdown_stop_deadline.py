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

import pytest

from src.api import llm as llm_api
from src.jobs import background as bg
from src.jobs import llm_bulk_queue as lbq
from tests import test_llm_bulk_queue as _bq
from tests.test_llm_bulk_queue import _FakeLlm, _seed, _summaries, _use

store = _bq.store
queue = _bq.queue


class _SlowLlm(_FakeLlm):
    """Generation number ``hang_on`` hangs until ``hold`` is set (a CPU model on a long article); the others answer at once."""

    def __init__(self, hang_on: int = 1):
        super().__init__()
        self.hold = threading.Event()
        self.started = threading.Event()
        self._n = 0
        self._hang_on = hang_on

    def generate(self, prompt, **kw):
        self._n += 1
        if self._n == self._hang_on:
            self.started.set()
            self.hold.wait(30)
        return super().generate(prompt, **kw)


def test_a_stop_during_a_long_generation_pauses_the_run_within_the_deadline_and_resume_stores_each_once(queue, monkeypatch):
    fake = _SlowLlm(hang_on=2)  # the first article is stored before the stop, so the resume must skip it
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
        assert [_summaries(a) for a in ids] == [1, 0, 0], "an article was stored from a generation the stop abandoned"
        assert llm_api.abandoned_generations() == 1
    finally:
        fake.hold.set()  # the abandoned generation ends in its own thread; its result is dropped
    assert llm_api.wait_abandoned_generations(lambda: False)
    assert [_summaries(a) for a in ids] == [1, 0, 0], "the abandoned generation stored its result after the stop"
    assert queue.resume() and lbq._JOB.join(15)
    assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "done"
    assert [_summaries(a) for a in ids] == [1, 1, 1], "the resume stored an article twice or skipped one"


def test_a_task_manager_stop_during_a_generation_cancels_the_run_and_stores_nothing_of_it(queue, monkeypatch):
    fake = _SlowLlm()
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
    assert llm_api.wait_abandoned_generations(lambda: False)
    assert [_summaries(a) for a in ids] == [0, 0]


def test_freeing_the_model_waits_for_the_generation_a_stop_abandoned(queue, monkeypatch):
    """R669 kept: the release happens once the run paused AND its abandoned model call returned, never under it."""
    fake = _SlowLlm()
    _use(monkeypatch, fake)
    ids = _seed(2)
    queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})
    freed = threading.Event()
    try:
        assert fake.started.wait(10)
        out = llm_api._after_runs_pause(lambda: freed.set() or {"released": []}, "release-test")
        assert out.get("deferred") is True, out
        assert lbq._JOB.join(3), "the pause waited for the generation"
        time.sleep(0.5)
        assert not freed.is_set(), "the model was freed while the abandoned generation still ran"
    finally:
        fake.hold.set()
    assert freed.wait(5), "the release never happened after the generation returned"
    assert [_summaries(a) for a in ids] == [0, 0]


def test_an_abandoned_batch_makes_no_further_model_call():
    """A long article split in parts stops after the part in flight: the client of an abandoned batch refuses every next call."""
    abandoned = threading.Event()
    calls: list[str] = []

    class _C:
        def generate(self, prompt, **_kw):
            calls.append(prompt)
            return "ok"

    c = llm_api._StopAwareClient(_C(), abandoned)
    assert c.generate("one") == "ok"
    abandoned.set()
    with pytest.raises(llm_api._GenerationAbandoned):
        c.generate("two")
    assert calls == ["one"]


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
