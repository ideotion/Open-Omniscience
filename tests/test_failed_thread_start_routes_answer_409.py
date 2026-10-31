"""A route whose manager could not make its worker thread answers 409, not an unhandled 500.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. ``tests/test_failed_thread_start_leaves_no_leaked_slot.py`` and ``tests/test_failed_thread_start_leaves_no_phantom_job.py``
pin that a manager whose ``Thread.start()`` refuses ("can't start new thread", the process or the machine is out of threads) puts its
job right and goes on raising the ``RuntimeError``. Before that change a start that failed answered 200 with a row that never moved;
after it, a route that maps only ``ValueError`` (or only the manager's own refusal class) lets the ``RuntimeError`` through as an
unhandled 500. ``src/api/backup_v2.py`` already answers 409 for the same error. This file pins the routes this lane owns:

- ``POST /api/llm/pull/queue``, ``POST /api/llm/default-model/install`` (the Ollama path AND the vLLM path) and the batch router
  ``_queue_downloads`` (both backends);
- ``POST /api/jobs/{id}/resume`` for a Wikipedia dump, an OSM region and the search re-index;
- ``POST /api/search/index-job`` and ``POST /api/search/index-job/resume``;
- ``POST /api/scheduler/start``, the Start button's route: ``BackgroundScheduler.start()`` has undone its state and re-raised since the
  thread-start change, and the route (in no ownership table, so taken under R307) mapped nothing.

What it pins: the status (409), what the body carries (the exception's words where the neighbouring routes carry them, a CODE where
the neighbours answer with codes: the search re-index never puts an exception's text in a response), that nothing the failed start
did not do is recorded as done (the model is not saved as the preference), that the batch refuses ONE model and queues the rest, and
that a refusal of the re-index manager still answers its own code (``SearchReindexRefused`` is a ``RuntimeError``, so the order of the
two ``except`` clauses is load-bearing), that an interrupt (a ``BaseException``) is not mapped to a status, and that the failure is in the
log (the 500 handler used to put it there; with the status answered, nothing else would).

The failure is injected in the module under test (its ``threading`` replaced by one whose ``Thread`` refuses to start), never on the
process-wide class. The client does not re-raise server errors, so a route that lets the error through is seen as the 500 it answers.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.database import fts_reindex
from src.geo import osm_downloads
from src.llm import pull_queue
from src.wiki import dumps as wiki_dumps

_CANNOT_START = "can't start new thread"


class _Threading:
    """What a module sees as ``threading``: the real one, except that the first ``fail_first`` threads it makes refuse to start."""

    def __init__(self, fail_first: int = 1) -> None:
        self.refusals_left = fail_first
        outer = self

        class Thread(threading.Thread):
            def start(self) -> None:
                if outer.refusals_left > 0:
                    outer.refusals_left -= 1
                    raise RuntimeError(_CANNOT_START)
                super().start()

        self.Thread = Thread

    def __getattr__(self, name: str):
        return getattr(threading, name)


def _cannot_start(monkeypatch, module, fail_first: int = 1) -> _Threading:
    shim = _Threading(fail_first)
    monkeypatch.setattr(module, "threading", shim)
    return shim


@pytest.fixture
def client():
    from src.api.main import app

    # ``raise_server_exceptions=False``: a route that lets the error through answers the 500 it would answer a real caller, and the
    # test reads the status instead of seeing an exception inside the client. ``base_url``: the host allow-set (R226).
    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    # The download managers refuse to start while airplane mode is engaged; this file is about what happens after they decide to.
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)


# --------------------------------------------------------------------------- #
#  the pull queue, the default-model install and the batch router
# --------------------------------------------------------------------------- #
@pytest.fixture
def pull(monkeypatch):
    """A fresh pull manager whose pump thread cannot start, standing in for the process's one."""
    mgr = pull_queue.ModelPullManager()
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: mgr)
    _cannot_start(monkeypatch, pull_queue, fail_first=10)
    return mgr


def test_the_pull_queue_route_answers_409_with_the_words_not_a_500(client, pull):
    r = client.post("/api/llm/pull/queue", json={"model": "llama3:8b"})
    assert r.status_code == 409
    assert _CANNOT_START in r.json()["detail"]
    assert pull.status()["queue"] == [], "the model the failed start could not pull is not left queued"


def test_a_malformed_model_name_still_answers_400(client, pull):
    r = client.post("/api/llm/pull/queue", json={"model": "../etc/passwd"})
    assert r.status_code == 400


def _ollama_plan(monkeypatch, saved: list) -> None:
    monkeypatch.setattr(
        "src.api.llm._default_model_plan",
        lambda: {"backend": "ollama", "artifact": "ministral-3:3b", "prerequisite": None},
    )
    monkeypatch.setattr("src.ingest.egress_window.egress_permitted", lambda _purpose: True)
    monkeypatch.setattr("src.config.app_settings.save_settings", lambda patch: saved.append(dict(patch)))


def test_the_default_model_install_answers_409_and_does_not_save_the_model_as_the_preference(client, pull, monkeypatch):
    saved: list = []
    _ollama_plan(monkeypatch, saved)
    r = client.post("/api/llm/default-model/install")
    assert r.status_code == 409
    assert _CANNOT_START in r.json()["detail"]
    assert saved == [], "a model whose download did not begin is not the operator's chosen model"


def test_the_batch_refuses_one_model_with_the_reason_and_queues_the_rest(monkeypatch):
    from src.api import llm

    class _Manager:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def enqueue(self, model: str) -> dict:
            self.asked.append(model)
            if model == "b:1":
                raise RuntimeError(_CANNOT_START)
            return {}

        def status(self) -> dict:
            return {"active": None, "queue": list(self.asked)}

    mgr = _Manager()
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: mgr)
    ok = [{"key": k, "label": k.upper(), "identifier": f"{k}:1"} for k in ("a", "b", "c")]
    out = llm._queue_downloads("ollama", ok, [])
    assert mgr.asked == ["a:1", "b:1", "c:1"], "the batch went on past the model whose pump could not start"
    assert out["queued"] == ["a:1", "c:1"], "and does not count it as queued"
    assert [(r["key"], _CANNOT_START in r["reason"]) for r in out["refused"]] == [("b", True)]


# --------------------------------------------------------------------------- #
#  /api/jobs/{id}/resume for a dump, an OSM region and the search re-index
# --------------------------------------------------------------------------- #
def _entry_that_failed_to_start(monkeypatch, tmp_path, module, manager_cls, start_args):
    """A manager holding one entry whose first start refused, with the next start set to refuse as well."""
    mgr = manager_cls(base_dir=tmp_path, http_get=lambda url, headers: None)
    monkeypatch.setattr(module, "get_manager", lambda: mgr)
    shim = _cannot_start(monkeypatch, module, fail_first=1)
    with pytest.raises(RuntimeError):
        mgr.start(*start_args)
    shim.refusals_left = 1
    return mgr


def test_a_dump_resume_whose_worker_cannot_start_answers_409(client, monkeypatch, tmp_path):
    mgr = _entry_that_failed_to_start(monkeypatch, tmp_path, wiki_dumps, wiki_dumps.DumpDownloadManager, ("en",))
    key = mgr.list()[0]["key"]
    r = client.post(f"/api/jobs/dump:{key}/resume")
    assert r.status_code == 409
    assert _CANNOT_START in r.json()["detail"]


def test_an_osm_resume_whose_worker_cannot_start_answers_409(client, monkeypatch, tmp_path):
    mgr = _entry_that_failed_to_start(monkeypatch, tmp_path, osm_downloads, osm_downloads.OsmDownloadManager, ("europe", "Europe"))
    key = mgr.list()[0]["key"]
    r = client.post(f"/api/jobs/osm:{key}/resume")
    assert r.status_code == 409
    assert _CANNOT_START in r.json()["detail"]


def test_an_unknown_dump_or_region_is_still_a_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(wiki_dumps, "get_manager", lambda: wiki_dumps.DumpDownloadManager(base_dir=tmp_path, http_get=lambda u, h: None))
    monkeypatch.setattr(osm_downloads, "get_manager", lambda: osm_downloads.OsmDownloadManager(base_dir=tmp_path, http_get=lambda u, h: None))
    assert client.post("/api/jobs/dump:no-such:key/resume").status_code == 404
    assert client.post("/api/jobs/osm:atlantis/resume").status_code == 404


# --------------------------------------------------------------------------- #
#  the search re-index: three routes, answered with CODES
# --------------------------------------------------------------------------- #
@pytest.fixture
def reindex(monkeypatch, tmp_path):
    """A re-index manager whose worker thread cannot start, standing in for the process's one."""
    mgr = fts_reindex.SearchReindexJobManager(state_path=tmp_path / "reindex.json", report_path=tmp_path / "report.json")
    monkeypatch.setattr(fts_reindex, "get_search_reindex_manager", lambda: mgr)
    return mgr


def test_the_reindex_start_answers_the_code_worker_not_started(client, monkeypatch, reindex):
    _cannot_start(monkeypatch, fts_reindex)
    r = client.post("/api/search/index-job")
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": fts_reindex.REFUSED_WORKER_NOT_STARTED}
    assert _CANNOT_START not in r.text, "nothing an exception carries reaches a response on these routes"


def test_the_reindex_resume_answers_the_code_on_both_of_its_routes(client, monkeypatch, reindex):
    shim = _cannot_start(monkeypatch, fts_reindex)
    assert client.post("/api/search/index-job").status_code == 409  # leaves the run saved as "error", which a resume continues
    for route in ("/api/search/index-job/resume", "/api/jobs/search-reindex/resume"):
        shim.refusals_left = 1
        r = client.post(route)
        assert r.status_code == 409, route
        assert r.json()["detail"] == {"code": fts_reindex.REFUSED_WORKER_NOT_STARTED}, route
        assert _CANNOT_START not in r.text, route


def test_a_refusal_of_the_reindex_manager_still_answers_its_own_code_on_every_route(client, reindex):
    """``SearchReindexRefused`` is a ``RuntimeError``: with the two clauses in the other order every refusal would read as a failed start."""
    reindex._thread = threading.current_thread()  # a live thread: the manager is running
    assert client.post("/api/search/index-job").json()["detail"] == {"code": fts_reindex.REFUSED_RUNNING}
    reindex._thread = None  # and nothing is paused
    for route in ("/api/search/index-job/resume", "/api/jobs/search-reindex/resume"):
        r = client.post(route)
        assert r.status_code == 409 and r.json()["detail"] == {"code": fts_reindex.REFUSED_NOTHING_PAUSED}, route


def test_the_four_codes_are_distinct():
    codes = [
        fts_reindex.REFUSED_RUNNING,
        fts_reindex.REFUSED_NOTHING_PAUSED,
        fts_reindex.REFUSED_NOT_UPGRADED,
        fts_reindex.REFUSED_WORKER_NOT_STARTED,
    ]
    assert len(set(codes)) == 4, "a test that compares a route's answer to the constant passes when two constants share a value"


# --------------------------------------------------------------------------- #
#  the vLLM half of the install and of the batch (a BackgroundJob, not the pull queue)
# --------------------------------------------------------------------------- #
class _Job:
    """A vLLM download job: ``start`` raises ``error`` when it is given one (``BackgroundJob.start`` re-raises a refused thread start,
    and raises as well when a run is already in flight)."""

    def __init__(self, error: BaseException | None = None, events: list | None = None) -> None:
        self.error = error
        self.events = events if events is not None else []

    def status(self) -> dict:
        return {"running": False}

    def start(self, **kwargs) -> dict:
        if self.error is not None:
            raise self.error
        self.events.append(("start", kwargs))
        return self.status()


def _vllm_plan(monkeypatch, job: _Job, events: list) -> None:
    monkeypatch.setattr("src.api.llm._default_model_plan", lambda: {"backend": "vllm", "artifact": "org/model", "prerequisite": None})
    monkeypatch.setattr("src.ingest.egress_window.egress_permitted", lambda _purpose: True)
    monkeypatch.setattr("src.config.app_settings.save_settings", lambda patch: events.append(("save", dict(patch))))
    monkeypatch.setattr("src.llm.vllm_lifecycle.venv_python", lambda: Path(__file__))  # a file that exists: the venv is "installed"
    monkeypatch.setattr("src.api.llm._get_vllm_model_job", lambda: job)


@pytest.mark.parametrize("error", [RuntimeError(_CANNOT_START), RuntimeError("a vllm-model-download job is already running")])
def test_the_vllm_install_answers_409_and_does_not_save_the_model_as_the_preference(client, monkeypatch, error):
    events: list = []
    _vllm_plan(monkeypatch, _Job(error), events)
    r = client.post("/api/llm/default-model/install")
    assert r.status_code == 409
    assert str(error) in r.json()["detail"]
    assert events == [], "a model whose download did not begin is not the operator's chosen model"


def test_the_vllm_install_that_starts_saves_the_preference_after_the_start(client, monkeypatch):
    events: list = []
    _vllm_plan(monkeypatch, _Job(events=events), events)
    r = client.post("/api/llm/default-model/install")
    assert r.status_code == 200 and r.json()["action"] == "downloading"
    assert events == [("start", {"model": "org/model"}), ("save", {"llm_model_vllm": "org/model"})]


def test_the_vllm_batch_refuses_every_model_with_a_409_when_its_one_job_cannot_start(monkeypatch):
    from fastapi import HTTPException

    from src.api import llm

    monkeypatch.setattr("src.api.llm._get_vllm_model_job", lambda: _Job(RuntimeError(_CANNOT_START)))
    ok = [{"key": "a", "label": "A", "identifier": "org/a"}, {"key": "b", "label": "B", "identifier": "org/b"}]
    with pytest.raises(HTTPException) as caught:
        llm._queue_downloads("vllm", ok, [])
    assert caught.value.status_code == 409 and _CANNOT_START in caught.value.detail


def test_the_vllm_batch_that_starts_queues_every_model(monkeypatch):
    from src.api import llm

    job = _Job()
    monkeypatch.setattr("src.api.llm._get_vllm_model_job", lambda: job)
    ok = [{"key": "a", "label": "A", "identifier": "org/a"}, {"key": "b", "label": "B", "identifier": "org/b"}]
    out = llm._queue_downloads("vllm", ok, [])
    assert out["queued"] == ["org/a", "org/b"] and out["refused"] == []
    assert job.events == [("start", {"models": ["org/a", "org/b"]})]


class _InstallJob:
    """The vLLM ENGINE install job (``POST /api/llm/vllm/install``): its ``start`` raises, and leaves the state a real ``BackgroundJob``
    leaves: ``error`` when the worker thread could not start, ``running`` when another run was already in flight."""

    def __init__(self, message: str, *, state_after: str) -> None:
        self.message, self.state_after, self.state = message, state_after, "idle"

    def status(self) -> dict:
        return {"running": self.state == "running", "state": self.state}

    def start(self, **_kwargs) -> dict:
        self.state = self.state_after
        raise RuntimeError(self.message)


def _vllm_engine_install(monkeypatch, job: _InstallJob) -> None:
    monkeypatch.setattr("src.ingest.egress_window.egress_permitted", lambda _purpose: True)
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": True})
    monkeypatch.setattr("src.llm.vllm_lifecycle.platform_support", lambda: {"supported": True})
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.install_preflight", lambda **_kw: {"blocking": [], "requires_acknowledgement": False, "warnings": []}
    )
    monkeypatch.setattr("src.api.llm._get_vllm_install_job", lambda: job)


def test_a_vllm_engine_install_that_lost_a_race_is_a_status_and_not_logged_as_a_failed_start(client, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _vllm_engine_install(monkeypatch, _InstallJob("a vllm-install job is already running", state_after="running"))
    r = client.post("/api/llm/vllm/install", json={})
    assert r.status_code == 200 and r.json()["started"] is False and r.json()["state"] == "running"
    assert caplog.text == ""


def test_the_vllm_install_does_not_map_an_error_that_is_not_a_failed_start(client, monkeypatch):
    """Only a ``RuntimeError`` is the start's refusal; anything else is still the unhandled error (and the 500 handler still logs it)."""
    _vllm_plan(monkeypatch, _Job(TypeError("not a refusal")), [])
    assert client.post("/api/llm/default-model/install").status_code == 500


def test_a_batch_that_queued_nothing_says_nothing_to_do_and_names_every_refusal(monkeypatch):
    from src.api import llm

    one = [{"key": "a", "label": "A", "identifier": "a:1"}]
    for error in (RuntimeError(_CANNOT_START), ValueError("not a model tag")):
        monkeypatch.setattr(pull_queue, "get_pull_manager", lambda error=error: _Raises(error))
        out = llm._queue_downloads("ollama", one, [{"key": "z", "label": "Z", "reason": "earlier"}])
        assert out["action"] == "nothing_to_do" and out["queued"] == []
        assert [r["key"] for r in out["refused"]] == ["z", "a"], "the refusals made before the batch are kept, the batch's own are added"


# --------------------------------------------------------------------------- #
#  POST /api/scheduler/start: the collection loop's own thread
# --------------------------------------------------------------------------- #
class _Loop:
    """A scheduler stand-in: ``start()`` answers ``started``, or raises ``error``."""

    def __init__(self, error: BaseException | None = None, started: bool = True) -> None:
        self.error, self.started = error, started

    def start(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.started

    def status(self) -> dict:
        return {"running": self.started and self.error is None}


def _scheduler_route(monkeypatch, scheduler) -> list[str]:
    """``POST /api/scheduler/start`` with ``scheduler`` as the process's one. The route clears the kill switch before it starts; that is
    process-wide state this file does not need to touch. Returns the record of what the route did AFTER the start."""
    after: list[str] = []
    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: scheduler)
    monkeypatch.setattr("src.api.scheduler._resume_wiki_lane", lambda: after.append("wiki lane resumed"))
    monkeypatch.setattr("src.ingest.clear_kill_switch", lambda: None)
    monkeypatch.setattr("src.ingest.note_operator_crossed_online", lambda: None)
    return after


def test_a_collection_start_whose_loop_thread_cannot_start_answers_409_not_500(client, monkeypatch):
    """The REAL scheduler: ``BackgroundScheduler.start()`` undoes its state and re-raises ``can't start new thread``; the route used to let
    that through as a 500 (it is the Start button's route). The loop is not running afterwards, and the route did not go on to resume the
    Wikipedia lane as if collection had started."""
    from src.scheduler import runner

    scheduler = runner.BackgroundScheduler(run_once_fn=lambda: {})
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)  # a real supervisor thread is not this test's business
    _cannot_start(monkeypatch, runner)
    after = _scheduler_route(monkeypatch, scheduler)
    r = client.post("/api/scheduler/start")
    assert r.status_code == 409 and _CANNOT_START in r.json()["detail"]
    assert scheduler.is_running() is False
    assert after == [], "the Wikipedia lane was resumed after a start that did not happen"


def test_a_collection_start_that_works_is_unchanged(client, monkeypatch):
    after = _scheduler_route(monkeypatch, _Loop())
    r = client.post("/api/scheduler/start")
    assert r.status_code == 200 and r.json()["started"] is True and r.json()["running"] is True
    assert after == ["wiki lane resumed"]


def test_a_collection_start_that_raises_something_else_is_still_the_unhandled_error(client, monkeypatch):
    """Only a ``RuntimeError`` is the start's refusal (the manager raises nothing else for it)."""
    _scheduler_route(monkeypatch, _Loop(TypeError("not a refusal")))
    assert client.post("/api/scheduler/start").status_code == 500


# --------------------------------------------------------------------------- #
#  what is NOT mapped: another error of the same routes, and an interrupt
# --------------------------------------------------------------------------- #
class _Raises:
    """A manager whose every call raises ``error``."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def _boom(self, *_a, **_k):
        raise self.error

    start = resume = enqueue = _boom

    def status(self) -> dict:
        return {"active": None, "queue": []}


@pytest.mark.parametrize("route, module", [("dump", wiki_dumps), ("osm", osm_downloads)])
def test_a_resume_that_raises_a_value_error_is_a_409_with_the_words_like_the_branches_beside_it(client, monkeypatch, route, module):
    monkeypatch.setattr(module, "get_manager", lambda: _Raises(ValueError("unsafe key")))
    r = client.post(f"/api/jobs/{route}:k/resume")
    assert r.status_code == 409 and "unsafe key" in r.json()["detail"]


def test_a_malformed_model_name_still_answers_400_on_the_install_too(client, monkeypatch):
    saved: list = []
    _ollama_plan(monkeypatch, saved)
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: _Raises(ValueError("not a model tag")))
    r = client.post("/api/llm/default-model/install")
    assert r.status_code == 400 and "not a model tag" in r.json()["detail"]
    assert saved == []


class _Interrupt(BaseException):
    """Stands for a ``KeyboardInterrupt`` / ``SystemExit``: not an ``Exception``, so no clause meant for a failed start may catch it."""


def test_an_interrupt_is_not_mapped_to_a_status_by_any_of_the_routes(monkeypatch):
    from src.api import jobs, llm, search_omni
    from src.api import scheduler as scheduler_api

    boom = _Raises(_Interrupt())
    monkeypatch.setattr(fts_reindex, "get_search_reindex_manager", lambda: boom)
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: boom)
    monkeypatch.setattr(wiki_dumps, "get_manager", lambda: boom)
    monkeypatch.setattr(osm_downloads, "get_manager", lambda: boom)
    monkeypatch.setattr("src.api.llm._get_vllm_model_job", lambda: _Job(_Interrupt()))
    _scheduler_route(monkeypatch, _Loop(_Interrupt()))
    one = [{"key": "a", "label": "A", "identifier": "a:1"}]

    def install(plan_for) -> None:
        plan_for()
        llm.default_model_install()

    calls = {
        "Ollama install": lambda: install(lambda: _ollama_plan(monkeypatch, [])),
        "vLLM install": lambda: install(lambda: _vllm_plan(monkeypatch, _Job(_Interrupt()), [])),
        "pull queue": lambda: llm.llm_pull_queue(llm.ModelRequest(model="llama3:8b")),
        "batch (Ollama)": lambda: llm._queue_downloads("ollama", one, []),
        "batch (vLLM)": lambda: llm._queue_downloads("vllm", one, []),
        "dump resume": lambda: jobs.resume_job("dump:k"),
        "OSM resume": lambda: jobs.resume_job("osm:k"),
        "re-index resume (jobs)": lambda: jobs.resume_job("search-reindex"),
        "re-index start": search_omni.search_index_job,
        "re-index resume": lambda: search_omni.search_index_job_action("resume"),
        "collection start": scheduler_api.scheduler_start,
    }
    for name, call in calls.items():
        try:
            call()
        except _Interrupt:
            continue
        except BaseException as other:  # noqa: BLE001 - the point: a clause that caught the interrupt answered a status instead
            pytest.fail(f"{name}: the interrupt was turned into {type(other).__name__}")
        pytest.fail(f"{name}: the call returned")


# --------------------------------------------------------------------------- #
#  the failure is in the log
# --------------------------------------------------------------------------- #
def test_a_refused_start_is_logged_on_every_route_that_maps_it(client, monkeypatch, tmp_path, caplog):
    """Before the status was mapped the 500 handler logged the error with its traceback; the diagnostics panel then tells the operator
    "the log has the details". With the status answered nothing else would, so each clause logs it (a WARNING, scrubbed)."""
    caplog.set_level(logging.WARNING)

    def logged(label: str) -> None:
        assert any(r.levelno == logging.WARNING and _CANNOT_START in r.getMessage() for r in caplog.records), (
            f"{label}: the refused start is not in the log as a WARNING"
        )
        caplog.clear()

    # the pull queue: the queue route, the Ollama install, and the batch router (which logs a refused start, never a malformed tag)
    mgr = pull_queue.ModelPullManager()
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: mgr)
    _cannot_start(monkeypatch, pull_queue, fail_first=10)
    assert client.post("/api/llm/pull/queue", json={"model": "llama3:8b"}).status_code == 409
    logged("pull queue")
    _ollama_plan(monkeypatch, [])
    assert client.post("/api/llm/default-model/install").status_code == 409
    logged("Ollama install")
    from src.api import llm

    one = [{"key": "a", "label": "A", "identifier": "a:1"}]
    assert llm._queue_downloads("ollama", one, [])["refused"][0]["key"] == "a"
    logged("batch")
    monkeypatch.setattr(pull_queue, "get_pull_manager", lambda: _Raises(ValueError("not a model tag")))
    assert llm._queue_downloads("ollama", one, [])["refused"][0]["key"] == "a"
    assert caplog.text == "", "a malformed tag is not a failed start and is not logged as one"

    # the search re-index (the routes answer a code, never the words): the start and both resumes
    reindex = fts_reindex.SearchReindexJobManager(state_path=tmp_path / "reindex.json", report_path=tmp_path / "report.json")
    monkeypatch.setattr(fts_reindex, "get_search_reindex_manager", lambda: reindex)
    shim = _cannot_start(monkeypatch, fts_reindex)
    r = client.post("/api/search/index-job")
    assert r.status_code == 409 and _CANNOT_START not in r.text
    logged("re-index start")
    for route in ("/api/search/index-job/resume", "/api/jobs/search-reindex/resume"):
        shim.refusals_left = 1
        assert client.post(route).status_code == 409
        logged(route)

    # the dump and OSM resumes
    for label, module, cls, args in (
        ("dump", wiki_dumps, wiki_dumps.DumpDownloadManager, ("en",)),
        ("osm", osm_downloads, osm_downloads.OsmDownloadManager, ("europe", "Europe")),
    ):
        manager = _entry_that_failed_to_start(monkeypatch, tmp_path / label, module, cls, args)
        assert client.post(f"/api/jobs/{label}:{manager.list()[0]['key']}/resume").status_code == 409
        logged(f"{label} resume")

    # the collection start (the real scheduler, its loop thread refused)
    from src.scheduler import runner

    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    _cannot_start(monkeypatch, runner)
    _scheduler_route(monkeypatch, runner.BackgroundScheduler(run_once_fn=lambda: {}))
    assert client.post("/api/scheduler/start").status_code == 409
    logged("collection start")

    # the vLLM engine install keeps its contract (the status with ``started: false``) and now logs a refused start
    _vllm_engine_install(monkeypatch, _InstallJob(_CANNOT_START, state_after="error"))
    r = client.post("/api/llm/vllm/install", json={})
    assert r.status_code == 200 and r.json()["started"] is False and r.json()["state"] == "error"
    logged("vLLM engine install")

    # the vLLM install and the vLLM batch
    _vllm_plan(monkeypatch, _Job(RuntimeError(_CANNOT_START)), [])
    assert client.post("/api/llm/default-model/install").status_code == 409
    logged("vLLM install")
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        llm._queue_downloads("vllm", one, [])
    logged("vLLM batch")
