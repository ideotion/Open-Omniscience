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
from tests.test_llm_bulk_queue import _FakeLlm, _seed, _summaries, _use, _wait

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


def test_a_resumed_run_counts_as_its_own_only_what_it_stored_before_the_stop(queue, monkeypatch):
    """Lane E follow-up (b): a summary another run wrote during the pause is skipped, and is not counted as this run's own."""
    from datetime import UTC, datetime

    from src.database.models import ArticleAnalysis
    from src.database.session import session_scope

    fake = _SlowLlm(hang_on=2)
    _use(monkeypatch, fake)
    ids = _seed(3)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    try:
        assert fake.started.wait(10)
        assert lbq.KIND not in bg.stop_all_jobs(5.0)
    finally:
        fake.hold.set()
    assert llm_api.wait_abandoned_generations(lambda: False)
    assert {e["id"]: e for e in queue.snapshot()["entries"]}[eid]["stored"] == 1
    with session_scope() as s:  # another run's summary of the second article, written during the pause
        s.add(ArticleAnalysis(article_id=ids[1], kind="summary", result="theirs", model="m", prompt_version="other",
                              created_at=datetime.now(UTC)))
    assert queue.resume() and lbq._JOB.join(15)
    final = {e["id"]: e for e in queue.snapshot()["entries"]}[eid]
    assert final["state"] == "done", final
    assert (final["stored"], final["skipped"]) == (2, 1), final
    assert [_summaries(a) for a in ids] == [1, 1, 1], "an article was stored twice or skipped"


def test_a_stop_before_the_replay_ends_never_loses_the_runs_own_stored_count(queue, monkeypatch):
    """Opus read: a resume zeroes ``stored`` and earns it back from the replayed lines, so a stop before they were all replayed
    used to save the partial count, and the next resume put the run's own earlier work under skipped."""
    fake = _SlowLlm(hang_on=3)
    _use(monkeypatch, fake)
    ids = _seed(3)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    try:
        assert fake.started.wait(10)
        assert lbq.KIND not in bg.stop_all_jobs(5.0)
    finally:
        fake.hold.set()
    assert llm_api.wait_abandoned_generations(lambda: False)
    with queue._lock:  # what a stop that landed before the first replayed line leaves: nothing replayed, all of it still owed
        entry = {e["id"]: e for e in queue._entries}[eid]
        assert entry["stored"] == 2, entry
        entry["prior_stored"], entry["stored"] = 2, 0
    assert queue.resume() and lbq._JOB.join(15)
    final = {e["id"]: e for e in queue.snapshot()["entries"]}[eid]
    assert final["state"] == "done", final
    assert (final["stored"], final["skipped"]) == (3, 0), final
    assert [_summaries(a) for a in ids] == [1, 1, 1]


def test_a_stop_during_run_setup_pauses_the_run_before_any_selection_or_model_call(queue, monkeypatch):
    """The machine probe is the slow part of setup: the stop is looked at right after it, before the selection and the model."""
    fake = _FakeLlm()
    probing = threading.Event()

    def _slow_probe():
        probing.set()
        time.sleep(1.0)
        return ("ollama", fake)

    monkeypatch.setattr("src.api.llm.get_llm_client_with_name", _slow_probe)
    prepared: list[bool] = []
    real_prepare = llm_api.prepare_bulk_run
    monkeypatch.setattr(llm_api, "prepare_bulk_run", lambda *a, **k: prepared.append(True) or real_prepare(*a, **k))
    ids = _seed(2)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    assert probing.wait(10)
    t0 = time.monotonic()
    assert lbq.KIND not in bg.stop_all_jobs(5.0)
    assert time.monotonic() - t0 < 2.5
    assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "paused"
    assert prepared == [], "the selection ran after the stop"
    assert fake.calls == [] and [_summaries(a) for a in ids] == [0, 0]


def test_prepare_bulk_run_looks_at_the_stop_before_it_registers_anything(monkeypatch):
    """The second look, inside setup: after the selection and the model name, before a task row or the model is touched."""
    from src.database.session import SessionLocal
    from src.monitoring import tasks as _tasks

    fake = _FakeLlm()
    ids = _seed(1)
    before = len(_tasks.snapshot())
    req = llm_api.BulkLLMRequest(op="summarize", model="m", article_ids=ids, skip_existing=False)
    with SessionLocal() as db, pytest.raises(llm_api.BulkRunStopped):
        llm_api.prepare_bulk_run(req, db, ("ollama", fake), should_stop=lambda: True)
    assert fake.calls == [] and len(_tasks.snapshot()) == before


class _StoppingCtx:
    stopping = True

    def set_progress(self, **_kw):
        pass


@pytest.mark.parametrize("shutdown", [False, True])
def test_a_resume_pressed_while_a_stopped_drain_ends_is_kept_unless_the_app_is_shutting_down(queue, monkeypatch, shutdown):
    """Lane E follow-up: the stopped drain's end used to pause the queue again over a Resume pressed in that instant."""
    fake = _FakeLlm()
    _use(monkeypatch, fake)
    ids = _seed(1)
    assert queue._load()
    queue._paused = True
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    queue._draining = True  # a stopped drain is ending
    monkeypatch.setattr(lbq._JOB, "stop_requested", lambda: True)
    assert queue.resume()
    counts = iter([0, 1 if shutdown else 0, 1 if shutdown else 0, 1 if shutdown else 0])
    monkeypatch.setattr(lbq, "stop_all_count", lambda: next(counts, 1 if shutdown else 0))
    lbq._drain(_StoppingCtx())
    if shutdown:
        assert queue.snapshot()["paused"] is True
        assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "queued"
    else:
        assert _wait(lambda: {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] == "done"), queue.snapshot()
        assert lbq._JOB.join(15)
        assert _summaries(ids[0]) == 1


def test_a_resume_during_a_drain_that_is_not_stopping_leaves_no_mark_for_a_later_stop(queue, monkeypatch):
    """Security read 1: a Resume pressed during a normal drain (nothing paused, a 404 to the caller) used to arm the restart, and
    the mark then outlived the drain into a later, unrelated stop."""
    assert queue._load()
    queue._draining = True
    monkeypatch.setattr(lbq._JOB, "stop_requested", lambda: False)
    assert queue.resume() is False
    assert queue._resumed_while_draining is False
    queue._resumed_while_draining = True  # one armed while stopping...
    queue.enqueue({"op": "summarize", "model": "m", "article_ids": _seed(1)})
    assert queue._next() is not None
    assert queue._resumed_while_draining is False, "...is spent by the next pick, so it never outlives the drain it was for"


def test_a_model_release_stop_is_never_undone_by_a_resume_pressed_while_it_lands(queue, monkeypatch):
    """Security read 1: a release or stop of the model waits for the run to pause; a Resume pressed meanwhile must not start the
    queue again under the release (it would run the next entry and the model would be freed under it, or reloaded)."""
    fake = _FakeLlm()
    _use(monkeypatch, fake)
    ids = _seed(1)
    assert queue._load()
    queue._paused = True  # nothing starts on its own: the drain below is the one the release stopped
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    calls = {"n": 0}
    resumed: list[bool] = []

    def _count() -> int:
        calls["n"] += 1
        if calls["n"] == 2:  # the drain's end: the release has stopped it, and the operator presses Resume in that instant
            with queue._lock:
                queue._backend_pause = True  # what pause_for_backend sets
            resumed.append(queue.resume())
        return 0

    monkeypatch.setattr(lbq, "stop_all_count", _count)
    monkeypatch.setattr(lbq._JOB, "stop_requested", lambda: True)
    with queue._lock:
        queue._draining = True
    lbq._drain(_StoppingCtx())
    assert calls["n"] >= 2 and queue._resumed_while_draining is False
    assert queue._draining is False, "the drain started again under the model release"
    assert queue.snapshot()["paused"] is True
    assert {e["id"]: e["state"] for e in queue.snapshot()["entries"]}[eid] in ("queued", "paused")
    assert fake.calls == [] and _summaries(ids[0]) == 0


def test_the_streamed_bulk_route_stops_on_its_task_manager_stop_without_waiting_for_the_generation(monkeypatch):
    """POST /api/llm/bulk (no queue, no ``should_stop``) polls its task-manager Stop while a generation runs, as a queued run does."""
    import json

    from src.database.session import SessionLocal
    from src.monitoring import tasks as _tasks

    fake = _SlowLlm()
    ids = _seed(2)
    req = llm_api.BulkLLMRequest(op="summarize", model="m", article_ids=ids, skip_existing=False)
    with SessionLocal() as db:
        tok, gen, _ = llm_api.prepare_bulk_run(req, db, ("ollama", fake))
    events: list[dict] = []
    t = threading.Thread(target=lambda: events.extend(json.loads(line) for line in gen))
    t.start()
    try:
        assert fake.started.wait(10)
        t0 = time.monotonic()
        _tasks.request_cancel(tok)
        t.join(3)
        assert not t.is_alive() and time.monotonic() - t0 < 2.0, "the Stop waited for the generation"
        assert events[-1]["event"] == "stopped", events[-1]
    finally:
        fake.hold.set()
    assert llm_api.wait_abandoned_generations(lambda: False)
    assert [_summaries(a) for a in ids] == [0, 0]
