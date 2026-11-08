"""The streamed AI runs outlive their tab, and the task manager can stop them (2026-11-08, the background-mode thread).

Bulk summarize/translate, AI keyword extraction and the custom prompt runs did their work INSIDE the response generator, so
closing the browser stopped them. ``src/api/detached_stream.py`` runs the same generator on its own thread. These tests pin what
that must keep true: every line still reaches an open tab in order; a reader that leaves does not stop the run; a Stop from the
task manager ends it between items and the runner's own ``finally`` still runs; nothing grows without bound when nobody reads.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import detached_stream as ds
from src.monitoring import tasks

REPO = Path(__file__).resolve().parents[1]


def _runner(n: int, log: list, *, delay: float = 0.0, gate: threading.Event | None = None):
    try:
        for i in range(n):
            if gate is not None:
                gate.wait(5)
            if delay:
                time.sleep(delay)
            log.append(i)
            yield f"{i}\n"
    finally:
        log.append("finally")


def _wait(pred, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_every_line_reaches_an_open_reader_in_order():
    log: list = []
    assert list(ds.detached(_runner(50, log), None)) == [f"{i}\n" for i in range(50)]
    assert log[-1] == "finally"


def test_a_reader_that_leaves_does_not_stop_the_run():
    """THE POINT. Before, closing the tab ended the generator after the item in flight."""
    log: list = []
    it = ds.detached(_runner(30, log, delay=0.005), None)
    assert next(it) == "0\n"
    it.close()  # the response ended: the client left
    assert _wait(lambda: "finally" in log), log
    assert [x for x in log if x != "finally"] == list(range(30)), "every item ran to the end with nobody reading"


def test_stop_from_the_task_manager_ends_the_run_between_items_and_runs_its_finally():
    tok = tasks.register("llm", "Summarizing 100 article(s)", total=100, cancellable=True)
    try:
        log: list = []
        it = ds.detached(_runner(100, log, delay=0.01), tok)
        assert next(it) == "0\n"
        assert tasks.request_cancel(tok)
        rest = list(it)
        assert _wait(lambda: "finally" in log)
        assert '"aborted":true' in rest[-1] and "stopped from the task manager" in rest[-1]
        done = [x for x in log if x != "finally"]
        assert len(done) < 100, "the stop was ignored"
        assert len(rest) <= len(done)
    finally:
        tasks.finish(tok)


def test_nothing_accumulates_when_nobody_reads(monkeypatch):
    monkeypatch.setattr(ds, "BUFFER", 5)
    monkeypatch.setattr(ds, "PUT_WAIT_S", 0.05)
    log: list = []
    it = ds.detached(_runner(200, log), None)
    del it  # never iterated, never closed: the worst reader
    assert _wait(lambda: "finally" in log, 10), "the run hung on a full queue nobody reads"
    assert len([x for x in log if x != "finally"]) == 200


def test_a_failing_run_ends_the_stream_with_an_aborted_done_line():
    import json

    def boom():
        yield "a\n"
        raise RuntimeError("model went away")

    out = list(ds.detached(boom(), None))
    assert out[0] == "a\n" and len(out) == 2
    last = json.loads(out[1])
    assert last["event"] == "done" and last["aborted"] is True


def test_a_slow_reader_still_gets_the_end_and_the_run_is_not_held_back(monkeypatch):
    """Opus read: a reader slower than PUT_WAIT_S once used to lose every later line AND the end, and its worker spun forever."""
    monkeypatch.setattr(ds, "BUFFER", 5)
    monkeypatch.setattr(ds, "PUT_WAIT_S", 0.05)
    log: list = []
    got: list = []

    def read():
        for line in ds.detached(_runner(40, log), None):
            got.append(line)
            time.sleep(0.03)

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(15)
    assert not t.is_alive(), "the reader never saw the end of the stream"
    assert "finally" in log and got and got[0] == "0\n"
    assert got[-1] == "39\n", "the last line must reach a reader that is still there"


# --------------------------------------------------------------------------- the task registry and the task manager


def test_only_a_cancellable_task_can_be_stopped_and_finish_forgets_it():
    plain = tasks.register("llm", "x")
    stoppable = tasks.register("llm", "y", cancellable=True)
    try:
        assert not tasks.request_cancel(plain)
        assert not tasks.cancel_requested(stoppable)
        assert tasks.request_cancel(stoppable) and tasks.cancel_requested(stoppable)
        rows = {t["token"]: t for t in tasks.snapshot()}
        assert rows[stoppable]["cancellable"] is True and rows[plain]["cancellable"] is False
    finally:
        tasks.finish(plain)
        tasks.finish(stoppable)
    assert not tasks.request_cancel(stoppable) and not tasks.cancel_requested(stoppable)


@pytest.fixture
def jobs_client():
    from src.api.jobs import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_task_manager_offers_stop_and_the_cancel_route_reaches_the_run(jobs_client):
    tok = tasks.register("llm", "Translating 3 article(s)", total=3, cancellable=True)
    plain = tasks.register("analytics", "something short")
    try:
        rows = {j["id"]: j for j in jobs_client.get("/api/jobs").json()["jobs"]}
        assert rows[f"task:{tok}"]["actions"] == ["stop"]
        assert rows[f"task:{plain}"]["actions"] == []
        r = jobs_client.post(f"/api/jobs/task:{tok}/cancel")
        assert r.status_code == 200 and tasks.cancel_requested(tok)
        assert jobs_client.post(f"/api/jobs/task:{plain}/cancel").status_code == 404
        assert jobs_client.post("/api/jobs/task:999999/cancel").status_code == 404
        assert jobs_client.post("/api/jobs/task:abc/cancel").status_code == 404
    finally:
        tasks.finish(tok)
        tasks.finish(plain)


def test_the_three_streamed_runs_are_detached_and_stoppable():
    """Source-level: each of the three streamed AI runs registers cancellable and returns through detached()."""
    ai = (REPO / "src" / "api" / "ai.py").read_text(encoding="utf-8")
    llm = (REPO / "src" / "api" / "llm.py").read_text(encoding="utf-8")
    assert ai.count("detail_vars={\"model\": model}, cancellable=True") == 2 and ai.count("detached(_stream(), _tok") == 2
    assert llm.count("detail_vars={\"model\": model}, cancellable=True") == 1 and llm.count("detached(_stream(), _tok") == 1
    # The page's own Cancel needs the run's task id to stop it on the server (Opus read of #1830).
    tag = 'headers={"X-OO-Task": f"task:{_tok}"}'
    assert ai.count(tag) == 2 and llm.count(tag) == 1


def test_the_task_manager_draws_stop_for_a_stoppable_run():
    js = (REPO / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    assert 'String(j.id).startsWith("task:") && Array.isArray(j.actions) && j.actions.includes("stop")' in js


# --------------------------------------------------------------------------- Opus read of #1830


def test_a_stalled_reader_still_gets_the_runners_own_end(monkeypatch):
    """Once stalled, a full queue dropped every line, the runner's own done line too: a slow tab read a failed run as finished."""
    import json

    monkeypatch.setattr(ds, "BUFFER", 3)
    monkeypatch.setattr(ds, "PUT_WAIT_S", 0.05)
    log: list = []

    def runner():
        yield from _runner(20, log)
        yield json.dumps({"event": "done", "aborted": True, "reason": "model went away"}, separators=(",", ":")) + "\n"

    it = ds.detached(runner(), None)
    assert _wait(lambda: "finally" in log), "the run waited on a reader that does not read"
    time.sleep(0.2)  # the producer has finished: everything it could not feed was dropped
    rest = list(it)
    assert rest and json.loads(rest[-1]) == {"event": "done", "aborted": True, "reason": "model went away"}


def test_a_stall_never_loses_a_stop_or_failure_end(monkeypatch):
    import json

    monkeypatch.setattr(ds, "BUFFER", 3)
    monkeypatch.setattr(ds, "PUT_WAIT_S", 0.05)

    def boom():
        for i in range(10):
            yield f"{i}\n"
        raise RuntimeError("model went away")

    it = ds.detached(boom(), None)
    time.sleep(0.5)
    out = list(it)
    last = json.loads(out[-1])
    assert last["event"] == "done" and last["aborted"] is True


def test_a_stop_that_lands_after_the_runs_own_end_adds_no_second_end():
    """The cancel check ran after every line, the final done line included: a Stop in that gap appended an aborted end, and the
    page overwrote a finished run with "stopped"."""
    import json

    tok = tasks.register("llm", "Summarizing 1 article(s)", total=1, cancellable=True)
    try:
        def runner():
            yield "0\n"
            tasks.request_cancel(tok)  # pressed just as the run sends its end
            yield json.dumps({"event": "done", "aborted": False}, separators=(",", ":")) + "\n"

        out = list(ds.detached(runner(), tok))
        dones = [json.loads(x) for x in out if '"event":"done"' in x]
        assert dones == [{"event": "done", "aborted": False}]
    finally:
        tasks.finish(tok)


def test_the_pages_cancel_stops_the_run_on_the_server_not_only_the_fetch():
    """Opus read of #1830: aborting the fetch no longer stops a detached run, so a page Cancel that only aborted reported
    "Cancelled" while the model kept writing, and the queue started the next run beside it."""
    js = (REPO / "src" / "static" / "app-analysis.js").read_text(encoding="utf-8")
    cancel = js[js.index("function bulkJobCancel("):js.index("function bulkJobClearDone(")]
    stop = js[js.index("function bulkLlmStop("):js.index("function bulkLlmRun(")]
    for body in (cancel, stop):
        assert ".abort()" not in body, "a Cancel that only aborts the fetch leaves the run going on the server"
        assert "_stopServerRun(" in body
    helper = js[js.index("async function _stopServerRun("):]
    assert "/api/jobs/${encodeURIComponent(taskId)}/cancel" in helper[:400]
    assert js.count('resp.headers.get("X-OO-Task")') == 2


def test_a_stopping_extractor_run_keeps_its_own_state_and_blocks_a_second_start():
    """Opus re-read of #1830: with one global state, a reopened panel's Start launched a second run beside a stopping one and the
    first run's end wiped the second's state, so the second could no longer be cancelled."""
    js = (REPO / "src" / "static" / "app-analysis.js").read_text(encoding="utf-8")
    assert "_bulkStopping" not in js and "_bulkTask" not in js
    start = js[js.index("async function aiRunPromptStart("):]
    start = start[: start.index("\n    }\n")]
    assert start.index("if (_aiRuns[ctx]) {") < start.index("_aiRuns[ctx] = run;") < start.index("await fetch(")
    assert "if (_aiRuns[ctx] === run) delete _aiRuns[ctx];" in start
