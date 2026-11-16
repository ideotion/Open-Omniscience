"""The bulk summarize / translate queue and the Insights backlog drain run on the server (R600's second PR, OPEN_QUEUE item 40).

What these pin: a queued run starts, runs and stores with nobody reading (the page only adds); runs go one at a time and in order;
a Stop ends the running run between articles and the queue goes on; stopping the job (the app shutting down) leaves the run
PAUSED, and so does a hard stop that never got to say so; after a restart nothing starts by itself, and Resume finishes the run
without storing any article twice (``skip_existing`` off, so only ``resume_since`` can prevent it); a locked store refuses an add
instead of writing an empty queue over the stored one; and the Insights drain is a writer job that stops on a stuck backlog.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.database.models import Article, ArticleAnalysis, Source
from src.database.session import init_db, session_scope
from src.jobs import llm_bulk_queue as lbq
from src.llm.ollama import GenerationResult


class _FakeLlm:
    """Offline stand-in for the local model. ``gate`` (when set) holds each generation until the test lets it go."""

    def __init__(self, gate: threading.Semaphore | None = None):
        self.gate = gate
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate is not None:
                assert self.gate.acquire(timeout=10), "the test never released a generation"
            self.calls.append(prompt)
            return GenerationResult(model=model, text=f"OUT[{len(self.calls)}]")
        finally:
            with self._lock:
                self.in_flight -= 1


def _seed(n: int) -> list[int]:
    init_db()
    ids = []
    with session_scope() as s:
        domain = f"bq-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"BQ {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        for i in range(n):
            a = Article(
                url=f"https://{domain}/{i}", canonical_url=f"https://{domain}/{i}", source_id=src.id,
                title=f"Article {i}", content="A body about rivers and floods. " * 20, language="en",
                hash=uuid.uuid4().hex + uuid.uuid4().hex,
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
    return ids


def _summaries(aid: int) -> int:
    with session_scope() as s:
        return s.query(ArticleAnalysis).filter(ArticleAnalysis.article_id == aid, ArticleAnalysis.kind == "summary").count()


def _wait(pred, secs: float = 15.0) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture()
def store(monkeypatch):
    """An in-memory stand-in for the encrypted ``app_state`` rows, so each test starts from an empty stored queue."""
    import json

    from src.config import kv_store

    rows: dict[str, dict] = {}
    state = {"locked": False}
    real = {n: getattr(kv_store, n) for n in ("kv_get_json_checked", "kv_get_json", "kv_set_json", "kv_delete")}

    def _copy(value):
        return None if value is None else json.loads(json.dumps(value))

    def _ours(key) -> bool:
        return str(key).startswith(lbq.KV_KEY)

    def _get_checked(key):
        if not _ours(key):
            return real["kv_get_json_checked"](key)
        if state["locked"]:
            raise RuntimeError("file is not a database")
        return _copy(rows.get(key))  # a copy, as the real store reads one: an edit in memory is not a write

    monkeypatch.setattr(kv_store, "kv_get_json_checked", _get_checked)
    monkeypatch.setattr(kv_store, "kv_get_json", lambda key: _copy(rows.get(key)) if _ours(key) else real["kv_get_json"](key))
    def _swapped(expect_swap) -> bool:
        return expect_swap is not None and kv_store.kv_swap_epoch() != expect_swap

    def _set(key, obj, *, expect_swap=None):
        if not _ours(key):
            return real["kv_set_json"](key, obj, expect_swap=expect_swap)
        if _swapped(expect_swap):  # the real store checks this after a restore's hold: same contract
            raise kv_store.KvSwapped("swapped")
        rows[key] = json.loads(json.dumps(obj))

    def _delete(key, *, expect_swap=None):
        if not _ours(key):
            return real["kv_delete"](key, expect_swap=expect_swap)
        if not _swapped(expect_swap):
            rows.pop(key, None)

    monkeypatch.setattr(kv_store, "kv_set_json", _set)
    monkeypatch.setattr(kv_store, "kv_delete", _delete)
    return rows, state


@pytest.fixture()
def queue(store, monkeypatch, tmp_path):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    q = lbq.LlmBulkQueue()
    monkeypatch.setattr(lbq, "_QUEUE", q)
    yield q
    lbq._JOB.cancel()
    lbq._JOB.join(15)


def _use(monkeypatch, fake: _FakeLlm) -> None:
    monkeypatch.setattr("src.api.llm.get_llm_client_with_name", lambda: ("ollama", fake))


def _restart(store) -> lbq.LlmBulkQueue:
    """A new process reading the same stored rows."""
    return lbq.LlmBulkQueue()


def test_a_queued_run_runs_and_stores_with_nobody_reading_and_runs_go_one_at_a_time(queue, monkeypatch):
    gate = threading.Semaphore(0)  # holds the first run until the second is added, so "ahead" is not a race
    fake = _FakeLlm(gate)
    _use(monkeypatch, fake)
    a, b = _seed(3), _seed(2)
    from src.api.main import app

    with TestClient(app) as client:
        r1 = client.post("/api/llm/bulk/queue", json={"op": "summarize", "model": "m", "article_ids": a})
        r2 = client.post("/api/llm/bulk/queue", json={"op": "summarize", "model": "m", "article_ids": b})
        assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
        assert r2.json()["ahead"] == 1
        for _ in range(5):
            gate.release()
        # Nobody reads again: the page is gone, and the server finishes both runs. Joined INSIDE the app's lifetime: leaving
        # the block is the app's shutdown, whose stop-all (R670) rightly leaves a run in flight PAUSED (R669) -- the
        # shutdown test below pins that half.
        assert lbq._JOB.join(15)
    snap = queue.snapshot()
    assert [e["state"] for e in snap["entries"]] == ["done", "done"], snap
    assert [e["stored"] for e in snap["entries"]] == [3, 2]
    assert all(_summaries(aid) == 1 for aid in a + b)
    assert fake.max_in_flight == 1, "two runs went to the model at once"


def test_the_queue_refuses_an_add_while_the_store_is_locked_and_never_writes_over_it(queue, store, monkeypatch):
    rows, state = store
    rows[lbq.KV_KEY] = {"seq": 7, "paused": True, "entries": [{"id": 7, "op": "summarize", "body": {"op": "summarize", "article_ids": [1]}, "state": "queued"}]}
    state["locked"] = True
    from src.api.main import app

    with TestClient(app) as client:
        r = client.post("/api/llm/bulk/queue", json={"op": "summarize", "article_ids": [1]})
        assert r.status_code == 409, r.text
        assert client.get("/api/llm/bulk/queue").json()["readable"] is False
    assert rows[lbq.KV_KEY]["seq"] == 7 and len(rows[lbq.KV_KEY]["entries"]) == 1, "the stored queue was overwritten"


def test_an_add_is_validated_before_it_is_stored(queue):
    with pytest.raises(ValueError):
        queue.enqueue({"op": "bogus", "article_ids": [1]})
    with pytest.raises(ValueError):
        queue.enqueue({"op": "summarize"})
    assert queue.snapshot()["entries"] == []


def test_a_stop_ends_the_running_run_between_articles_and_the_queue_goes_on(queue, monkeypatch):
    gate = threading.Semaphore(0)
    fake = _FakeLlm(gate)
    _use(monkeypatch, fake)
    a, b = _seed(5), _seed(1)
    first = queue.enqueue({"op": "summarize", "model": "m", "article_ids": a})["entry"]["id"]
    queue.enqueue({"op": "summarize", "model": "m", "article_ids": b})
    gate.release()
    assert _wait(lambda: _summaries(a[0]) == 1)
    assert queue.cancel(first)
    for _ in range(10):
        gate.release()
    assert lbq._JOB.join(15)
    states = {e["id"]: e for e in queue.snapshot()["entries"]}
    assert states[first]["state"] == "cancelled", states
    # Within one article (R669 (c)): the one stored before the Stop, at most the one whose generation was in flight, nothing after.
    assert states[first]["stored"] <= 2, "the stop was not honoured within one article"
    assert sum(_summaries(aid) for aid in a[2:]) == 0, "articles after the one in flight were still run"
    assert "article_ids" not in states[first]["body"], "a cancelled run kept what it was run on"
    assert _summaries(b[0]) == 1, "the run behind the stopped one never ran"
    from src.monitoring.tasks import snapshot

    assert not [t for t in snapshot() if t.get("kind") == "llm"], "the stopped run left its task-manager row behind"


def test_a_shutdown_leaves_the_run_paused_and_resume_finishes_it_without_storing_an_article_twice(queue, store, monkeypatch):
    gate = threading.Semaphore(0)
    fake = _FakeLlm(gate)
    _use(monkeypatch, fake)
    ids = _seed(4)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    behind = queue.enqueue({"op": "summarize", "model": "m", "article_ids": _seed(1)})["entry"]["id"]
    gate.release()
    gate.release()
    assert _wait(lambda: _summaries(ids[1]) == 1)
    lbq._JOB.cancel()  # the app shutting down (the registry's stop-all)
    gate.release()  # the generation in flight ends; its article is stored or dropped, never half-stored
    assert lbq._JOB.join(15)
    entry = {e["id"]: e for e in queue.snapshot()["entries"]}
    assert entry[eid]["state"] == "paused" and entry[behind]["state"] == "queued"
    # A restart: nothing starts by itself, and the task manager offers Resume / Cancel on the paused queue.
    q2 = _restart(store)
    monkeypatch.setattr(lbq, "_QUEUE", q2)
    snap = q2.snapshot()
    assert snap["paused"] is True and not snap["draining"]
    rows = lbq.queue_rows()
    assert [(r["id"], r["state"], r["actions"]) for r in rows] == [("llm-bulk-queue", "paused", ["resume", "cancel"])]
    for _ in range(10):
        gate.release()
    assert q2.resume()
    assert lbq._JOB.join(15)
    final = {e["id"]: e for e in q2.snapshot()["entries"]}
    assert final[eid]["state"] == "done" and final[behind]["state"] == "done", final
    assert [_summaries(aid) for aid in ids] == [1, 1, 1, 1], "a resumed run stored an article twice or skipped one"
    # The articles stored before the restart were recognised as done: the whole run's tally is 4 stored, none counted twice.
    assert final[eid]["stored"] == 4 and final[eid]["skipped"] == 0, final[eid]


def test_a_finished_run_keeps_no_trace_of_the_search_it_ran_on(queue, store, monkeypatch):
    """R669 (b): the typed search lives in the encrypted store only while the run is pending; done or cancelled, it is gone."""
    rows, _ = store

    def _prep(req, db, client_info, *, resume_since=None, should_stop=None):
        def gen():
            yield '{"event":"done","aborted":false}\n'

        return 1, gen(), [11]

    monkeypatch.setattr("src.api.llm.prepare_bulk_run", _prep)
    _use(monkeypatch, _FakeLlm())
    assert queue._load()
    queue._paused = True  # hold the drain so the second run can be cancelled while it waits
    done_id = queue.enqueue({"op": "summarize", "query": "secret inquiry one"})["entry"]["id"]
    gone_id = queue.enqueue({"op": "translate", "query": "secret inquiry two", "target_language": "French"})["entry"]["id"]
    assert "secret inquiry" in str(rows[lbq.KV_KEY])  # pending: held, in the encrypted store only
    assert queue.cancel(gone_id)
    queue._paused = False
    queue.kick()
    assert lbq._JOB.join(15)
    entries = {x["id"]: x for x in queue.snapshot()["entries"]}
    assert entries[done_id]["state"] == "done" and entries[gone_id]["state"] == "cancelled"
    assert "secret inquiry" not in str(rows), "a finished or cancelled run left its search in the store"
    assert not [k for k in rows if k.startswith(lbq.IDS_KEY_PREFIX)]


def test_a_search_the_index_refuses_leaves_a_fixed_phrase_not_its_words(queue, store, monkeypatch):
    """R669 (b): the refusal of a malformed search quotes the typed words; the finished run keeps a fixed phrase instead."""
    from fastapi import HTTPException

    rows, _ = store

    def _prep(req, db, client_info, *, resume_since=None, should_stop=None):
        raise HTTPException(status_code=400, detail="Invalid search query: unexpected token: 'zebrafinch'")

    monkeypatch.setattr("src.api.llm.prepare_bulk_run", _prep)
    _use(monkeypatch, _FakeLlm())
    eid = queue.enqueue({"op": "summarize", "query": "zebrafinch AND"})["entry"]["id"]
    assert lbq._JOB.join(15)
    entry = {x["id"]: x for x in queue.snapshot()["entries"]}[eid]
    assert entry["state"] == "error" and entry["error"] == lbq._SEARCH_REFUSED
    assert "zebrafinch" not in str(rows) and "zebrafinch" not in str(queue.snapshot())


def test_a_swapped_corpus_file_takes_the_queue_and_its_searches_with_it(queue, store, monkeypatch):
    """A panic wipe (or a restore, a merge) swaps the file under the queue: what was read from the old one, typed searches
    included, is neither served nor written into the new one. Saving one setting is not a swap."""
    from src.config.kv_store import kv_invalidate

    rows, _ = store
    _use(monkeypatch, _FakeLlm())
    assert queue._load()
    queue._paused = True
    queue.enqueue({"op": "summarize", "query": "wiped inquiry"})
    kv_invalidate("some.setting")  # one key: the queue stays
    assert len(queue.snapshot()["entries"]) == 1
    rows.clear()  # the new file holds no queue
    kv_invalidate()  # what panic_wipe, a restore and a merge call
    assert queue.snapshot()["entries"] == [] and queue.snapshot()["paused"] is False
    queue._save()
    assert "wiped inquiry" not in str(rows), "the old corpus's search was written into the new one"


def test_a_run_in_flight_when_the_file_is_swapped_stops_and_writes_nothing_of_it(queue, store, monkeypatch):
    from src.config.kv_store import kv_invalidate

    gate = threading.Semaphore(0)
    _use(monkeypatch, _FakeLlm(gate))
    rows, _ = store
    ids = _seed(5)
    queue.enqueue({"op": "summarize", "model": "m", "query": "swap inquiry", "article_ids": ids})
    gate.release()
    assert _wait(lambda: _summaries(ids[0]) == 1)
    rows.clear()
    kv_invalidate()
    for _ in range(10):
        gate.release()
    assert lbq._JOB.join(15)
    assert sum(_summaries(aid) for aid in ids[2:]) == 0, "the run went on against a swapped file"
    assert "swap inquiry" not in str(rows) and not rows, rows


def test_an_older_snapshot_never_lands_after_a_newer_one(queue, store):
    """Two saves racing: the one snapshotted first but written last is dropped, so a cancelled run's search cannot come back."""
    rows, _ = store
    assert queue._load()
    queue._paused = True
    eid = queue.enqueue({"op": "summarize", "query": "racing inquiry"})["entry"]["id"]
    release = threading.Event()
    real = queue._write_lock

    class _Gated:
        def __enter__(self):
            if threading.current_thread().name == "stale-saver":
                assert release.wait(10)
            return real.__enter__()

        def __exit__(self, *exc):
            return real.__exit__(*exc)

    queue._write_lock = _Gated()
    stale = threading.Thread(target=queue._save, name="stale-saver")
    stale.start()  # snapshots while the run still holds its search, then waits before writing
    assert _wait(lambda: queue._save_seq >= 2, 5)
    assert queue.cancel(eid)  # the newer snapshot: cancelled, search forgotten, written
    release.set()
    stale.join(10)
    assert rows[lbq.KV_KEY]["entries"][0]["state"] == "cancelled"
    assert "racing inquiry" not in str(rows), "a stale snapshot brought a cancelled run's search back"


def test_the_model_is_loopback_only_so_a_resume_needs_no_network_consent():
    """R669 (a): Resume and the drains ask no consent BECAUSE the model can only be loopback. If a client ever accepts a remote
    endpoint, this fails, and Resume must then pass the airplane-mode and consent gate of a fresh run."""
    from src.llm.ollama import LLMError, OllamaClient
    from src.llm.vllm_client import VllmClient

    for cls in (OllamaClient, VllmClient):
        with pytest.raises(LLMError):
            cls(base_url="http://models.example.org:11434")
        with pytest.raises(LLMError):
            cls(base_url="http://127.0.0.1.evil.example:11434")


def test_a_run_the_process_died_under_comes_back_paused(store):
    rows, _ = store
    rows[lbq.KV_KEY] = {"seq": 3, "paused": False, "entries": [
        {"id": 2, "op": "translate", "body": {"op": "translate", "query": "flood"}, "state": "running", "task": 9, "since": "2026-11-13T10:00:00"},
        {"id": 3, "op": "summarize", "body": {"op": "summarize", "query": "river"}, "state": "queued"},
    ]}
    q = _restart(store)
    snap = q.snapshot()
    assert snap["paused"] is True
    assert [(e["id"], e["state"]) for e in snap["entries"]] == [(2, "paused"), (3, "queued")]
    assert "task" not in snap["entries"][0]


def test_the_frozen_article_list_is_what_a_resumed_run_works_on(queue, store, monkeypatch):
    """A search that matches more articles after the restart does not grow the run: the list is frozen when it first starts."""
    seen: list = []

    def _prep(req, db, client_info, *, resume_since=None, should_stop=None):
        seen.append((req.article_ids, req.query, resume_since))

        def gen():
            yield '{"event":"done","aborted":false}\n'

        return 1, gen(), [11, 12]

    monkeypatch.setattr("src.api.llm.prepare_bulk_run", _prep)
    _use(monkeypatch, _FakeLlm())
    rows, _ = store
    rows[f"{lbq.IDS_KEY_PREFIX}5"] = {"ids": [11, 12]}
    rows[lbq.KV_KEY] = {"seq": 5, "paused": True, "entries": [
        {"id": 5, "op": "summarize", "body": {"op": "summarize", "query": "flood"}, "state": "running", "since": "2026-11-13T10:00:00"},
    ]}
    q = _restart(store)
    monkeypatch.setattr(lbq, "_QUEUE", q)
    assert q.resume()
    assert lbq._JOB.join(15)
    assert seen and seen[0][0] == [11, 12] and seen[0][1] is None and seen[0][2] is not None, seen
    assert f"{lbq.IDS_KEY_PREFIX}5" not in rows, "a finished run's frozen list was left behind"


def test_the_running_queue_job_is_not_a_second_row_beside_its_run(queue, monkeypatch):
    from src.api import jobs as jobs_api

    monkeypatch.setattr("src.jobs.background.all_job_statuses", lambda: [{**lbq._JOB.status(), "state": "running", "running": True}])
    assert not [r for r in jobs_api._background_jobs() if r["kind"] == lbq.KIND]


def test_the_queue_job_is_a_writer_and_cancellable():
    assert lbq._JOB.is_writer and lbq._JOB.cancellable


# --------------------------------------------------------------------------- #
#  the Insights backlog drain
# --------------------------------------------------------------------------- #
@pytest.fixture()
def backlog(monkeypatch):
    from src.jobs import insights_backlog as ib

    ib._reset_for_tests()
    monkeypatch.setattr(ib, "_busy_reason", lambda: None)
    yield ib
    ib.get_job().cancel()
    ib.get_job().join(15)
    ib._reset_for_tests()


def test_the_backlog_drain_runs_to_empty_on_the_server(backlog, monkeypatch):
    left = [650]

    def _batch(session, *, extractor, limit, should_stop=None):
        left[0] = max(0, left[0] - limit)
        return {"indexed": limit, "newly_indexed": limit, "failed": 0, "never_attempted": left[0]}

    monkeypatch.setattr("src.analytics.store.backfill_corpus", _batch)
    r = backlog.start()
    assert r["started"] is True
    assert backlog.get_job().join(15)
    res = backlog.get_job().status()["result"]
    assert res["ended"] == "drained" and res["complete"] and res["batches"] == 3, res


def test_a_backlog_stuck_twice_stops_the_restarts(backlog, monkeypatch):
    monkeypatch.setattr(
        "src.analytics.store.backfill_corpus",
        lambda session, *, extractor, limit, should_stop=None: {"indexed": limit, "newly_indexed": 0, "failed": 0, "never_attempted": 5},
    )
    assert backlog.start()["started"]
    assert backlog.get_job().join(15)
    assert backlog.get_job().status()["result"]["ended"] == "not_shrinking"
    assert backlog.start()["started"]
    assert backlog.get_job().join(15)
    again = backlog.start()
    assert again == {**again, "started": False, "reason": "stuck"}


def test_the_backlog_drain_does_not_start_while_other_work_owns_the_rows(monkeypatch):
    from src.jobs import insights_backlog as ib

    ib._reset_for_tests()

    class _Sched:
        def holds_exclusive(self):
            return True

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Sched())
    r = ib.start()
    assert r["started"] is False and r["reason"] == "exclusive_hold"


def test_the_backlog_drain_is_a_cancellable_writer_and_the_idle_slice_is_not_its_rival(monkeypatch):
    from src.jobs import insights_backlog as ib
    from src.scheduler import maintenance

    assert ib.get_job().is_writer and ib.get_job().cancellable
    monkeypatch.setattr(maintenance, "_page_draining", lambda **_: False)
    monkeypatch.setattr(
        "src.jobs.background.all_job_statuses", lambda: [{"kind": ib.KIND, "running": True, "is_writer": True}]
    )
    assert maintenance._backlog_busy_reason(exclude_kind=ib.KIND) in (None, "corpus_lease_held", "reindex_running")
    assert maintenance._backlog_busy_reason() == "writer_job_running", "the idle slice must stand back while the job drains"


def test_a_cancel_stored_before_the_process_died_stays_a_cancel(store):
    rows, _ = store
    rows[lbq.KV_KEY] = {"seq": 4, "paused": False, "entries": [
        {"id": 4, "op": "summarize", "body": {"op": "summarize", "query": "dropped inquiry"}, "state": "running", "stopping": True,
         "task": 3, "since": "2026-11-13T10:00:00"},
    ]}
    rows[f"{lbq.IDS_KEY_PREFIX}4"] = {"ids": [1, 2]}
    snap = _restart(store).snapshot()
    assert [(e["id"], e["state"]) for e in snap["entries"]] == [(4, "cancelled")]
    assert snap["paused"] is False, "a queue with nothing left waiting was restored paused"
    assert "dropped inquiry" not in str(snap) and f"{lbq.IDS_KEY_PREFIX}4" not in rows


def test_cancelling_the_last_waiting_run_lifts_the_restart_pause(store):
    rows, _ = store
    rows[lbq.KV_KEY] = {"seq": 2, "paused": True, "entries": [
        {"id": 2, "op": "summarize", "body": {"op": "summarize", "query": "q"}, "state": "paused", "since": "2026-11-13T10:00:00"},
    ]}
    q = _restart(store)
    assert q.snapshot()["paused"] is True
    assert q.cancel(2)
    assert q.snapshot()["paused"] is False
    assert rows[lbq.KV_KEY]["paused"] is False


def test_a_source_the_run_cannot_find_is_not_quoted_in_its_error(queue, store, monkeypatch):
    from fastapi import HTTPException

    rows, _ = store

    def _prep(req, db, client_info, *, resume_since=None, should_stop=None):
        raise HTTPException(status_code=404, detail="Unknown source: 'Quietpaper Gazette'")

    monkeypatch.setattr("src.api.llm.prepare_bulk_run", _prep)
    _use(monkeypatch, _FakeLlm())
    eid = queue.enqueue({"op": "summarize", "source": "Quietpaper Gazette"})["entry"]["id"]
    assert lbq._JOB.join(15)
    entry = {x["id"]: x for x in queue.snapshot()["entries"]}[eid]
    assert entry["error"] == lbq._SEARCH_REFUSED and "Quietpaper" not in str(rows)


def test_a_cancel_is_honoured_while_a_restore_holds_the_machine(queue, monkeypatch):
    """A Stop pressed during the restore hold ends the run then, not when the restore is over."""
    hold = threading.Event()
    hold.set()

    class _Sched:
        def holds_exclusive(self):
            return hold.is_set()

    gate = threading.Semaphore(0)
    _use(monkeypatch, _FakeLlm(gate))
    ids = _seed(4)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    gate.release()
    assert _wait(lambda: _summaries(ids[0]) == 1)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Sched())
    gate.release()
    assert _wait(lambda: _summaries(ids[1]) == 1)
    assert queue.cancel(eid)
    try:
        assert lbq._JOB.join(10), "the Stop waited for the restore to end"
    finally:
        hold.clear()
        for _ in range(5):
            gate.release()
    assert {e["id"]: e for e in queue.snapshot()["entries"]}[eid]["state"] == "cancelled"


def test_the_bulk_queue_does_not_hold_the_insights_backlog_back(monkeypatch):
    """The queue writes summaries, never the keyword index, and may run for hours: indexing carries on beside it."""
    from src.scheduler import maintenance

    monkeypatch.setattr(maintenance, "_page_drain_at", 0.0)
    monkeypatch.setattr(maintenance, "_job_drain_at", 0.0)
    statuses = [{"kind": "llm-bulk-queue", "running": True, "is_writer": True}]
    monkeypatch.setattr("src.jobs.background.all_job_statuses", lambda: statuses)
    assert maintenance._backlog_busy_reason() is None
    statuses.append({"kind": "some-writer", "running": True, "is_writer": True})
    assert maintenance._backlog_busy_reason() == "writer_job_running"


def test_two_stuck_runs_must_be_back_to_back_to_stop_the_restarts(backlog, monkeypatch):
    left = {"n": 5}
    monkeypatch.setattr(
        "src.analytics.store.backfill_corpus",
        lambda session, *, extractor, limit, should_stop=None: {"indexed": limit, "newly_indexed": 0, "failed": 0, "never_attempted": left["n"]},
    )
    assert backlog.start()["started"] and backlog.get_job().join(15)
    left["n"] = 0
    assert backlog.start()["started"] and backlog.get_job().join(15)  # drained in between
    left["n"] = 5
    assert backlog.start()["started"] and backlog.get_job().join(15)
    assert backlog.start()["started"], "a stuck run that was not back to back with the first stopped the restarts"
    assert backlog.get_job().join(15)


def test_the_backlog_drain_does_not_take_its_own_yield_signal_for_a_rival(monkeypatch):
    """Each batch tells an idle slice to yield (the page's old signal); the job itself must not stop on it."""
    from src.jobs import insights_backlog as ib
    from src.scheduler import maintenance

    ib._reset_for_tests()
    monkeypatch.setattr(maintenance, "_page_drain_at", 0.0)
    monkeypatch.setattr(maintenance, "_job_drain_at", 0.0)
    left = [900]

    def _batch(session, *, extractor, limit, should_stop=None):
        left[0] = max(0, left[0] - limit)
        return {"indexed": limit, "newly_indexed": limit, "failed": 0, "never_attempted": left[0]}

    monkeypatch.setattr("src.analytics.store.backfill_corpus", _batch)
    try:
        r = ib.start()
        assert r["started"], r
        assert ib.get_job().join(15)
        result = ib.get_job().status()["result"]
        assert result["ended"] == "drained" and result["batches"] == 3, result
        assert maintenance._page_draining(), "an idle slice under way was not told to yield"
    finally:
        ib._reset_for_tests()


def test_a_task_label_never_carries_a_free_text_target_language():
    """R672: /api/jobs and the terminal panel show task labels, so a typed target goes in only when it is a known language."""
    from src.api.llm import _label_target, _translate_label_frame

    assert _label_target("French") == "French" and _label_target("fr") == "French"
    assert _label_target("my private codeword") == "another language"
    assert _translate_label_frame("my private codeword", "Translating → {language} {n} article(s)", n=1) == {}


def test_the_store_refuses_a_write_read_from_a_file_swapped_since():
    """The guard the queue's writes rely on: checked after a restore's hold, so a save that waited never lands in the new file."""
    from src.config import kv_store

    old = kv_store.kv_swap_epoch()
    kv_store.kv_invalidate()
    with pytest.raises(kv_store.KvSwapped):
        kv_store.kv_set_json("jobs.test_swap_guard", {"x": 1}, expect_swap=old)
    kv_store.kv_delete("jobs.test_swap_guard", expect_swap=old)  # a no-op, never an error


def test_a_save_that_waited_through_a_swap_writes_nothing(queue, store):
    rows, _ = store
    assert queue._load()
    queue._paused = True
    queue.enqueue({"op": "summarize", "query": "held inquiry"})
    rows.clear()
    release = threading.Event()
    real = queue._write_lock

    class _Gated:
        def __enter__(self):
            if threading.current_thread().name == "held-saver":
                assert release.wait(10)
            return real.__enter__()

        def __exit__(self, *exc):
            return real.__exit__(*exc)

    queue._write_lock = _Gated()
    t = threading.Thread(target=queue._save, name="held-saver")
    t.start()  # snapshot under the old file, then waits (as behind a restore's hold)
    assert _wait(lambda: queue._save_seq >= 2, 5)
    from src.config.kv_store import kv_invalidate

    kv_invalidate()  # the swap
    release.set()
    t.join(10)
    assert "held inquiry" not in str(rows), "a save read from the old file landed in the new one"


def test_a_run_that_crashes_ends_in_error_and_the_runs_behind_it_go_on(queue, monkeypatch):
    real_run = lbq.LlmBulkQueue._run
    calls = []

    def _run(self, ctx, entry, gen0):
        calls.append(entry["id"])
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real_run(self, ctx, entry, gen0)

    monkeypatch.setattr(lbq.LlmBulkQueue, "_run", _run)
    _use(monkeypatch, _FakeLlm())
    ids = _seed(1)
    assert queue._load()
    queue._paused = True
    first = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids})["entry"]["id"]
    second = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    queue.resume()
    assert lbq._JOB.join(15)
    entries = {e["id"]: e for e in queue.snapshot()["entries"]}
    assert entries[first]["state"] == "error" and "boom" not in str(entries[first])
    assert entries[second]["state"] == "done", entries


def test_a_cancel_before_the_first_start_is_honoured_during_a_restore_hold(queue, monkeypatch):
    hold = threading.Event()
    hold.set()

    class _Sched:
        def holds_exclusive(self):
            return hold.is_set()

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Sched())
    _use(monkeypatch, _FakeLlm())
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": _seed(1)})["entry"]["id"]
    assert _wait(lambda: {e["id"]: e for e in queue.snapshot()["entries"]}[eid]["state"] == "running", 5)
    assert queue.cancel(eid)
    try:
        assert lbq._JOB.join(10), "the Cancel waited for the restore to end"
    finally:
        hold.clear()
    assert {e["id"]: e for e in queue.snapshot()["entries"]}[eid]["state"] == "cancelled"


def test_a_cancel_restored_at_load_is_written_back(store):
    rows, _ = store
    rows[lbq.KV_KEY] = {"seq": 6, "paused": False, "entries": [
        {"id": 6, "op": "translate", "body": {"op": "translate", "query": "restored inquiry", "target_language": "Klingon"},
         "state": "running", "stopping": True},
    ]}
    _restart(store).snapshot()
    assert "restored inquiry" not in str(rows) and "Klingon" not in str(rows), rows
