"""Controls placed where the task happens (lane-m-routes): free or stop the model without losing a run, the import re-index
backlog as a task-manager row with Resume, and the low-memory pause with its own Resume.

What these pin: releasing or stopping Ollama while a queued summary or translation run is in flight PAUSES that run at its
article boundary first and frees the model only then (R669: paused, never lost; Resume stores nothing twice); with nothing
running the action happens at once; a daemon this app does not own is refused by name and pauses nothing. The backlog row is
drawn only for a measured, non-empty backlog, read at most once per cache window, hidden while its job runs, and its Resume is
refused while an import or restore holds the machine. The UI halves run in model_and_pause_controls_node_test.js.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.jobs import llm_bulk_queue as lbq
from tests import test_llm_bulk_queue as _bq
from tests.test_llm_bulk_queue import _FakeLlm, _seed, _summaries, _use, _wait

# The bulk queue's own fixtures (an in-memory stored queue), shared rather than copied.
store = _bq.store
queue = _bq.queue

_ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ free / stop the model


def test_a_release_while_a_run_is_in_flight_pauses_the_run_first_and_frees_the_model_after(queue, monkeypatch):
    import src.llm.ollama_lifecycle as life
    from src.api import llm as llm_api

    gate = threading.Semaphore(0)
    _use(monkeypatch, _FakeLlm(gate))
    released = threading.Event()
    order: list[str] = []

    def _release():
        order.append("release:" + ("running" if lbq._JOB.status().get("running") else "stopped"))
        released.set()
        return {"released": ["m"], "attempted": True}

    monkeypatch.setattr(life, "release_vram", _release)
    ids = _seed(4)
    eid = queue.enqueue({"op": "summarize", "model": "m", "article_ids": ids, "skip_existing": False})["entry"]["id"]
    gate.release()
    assert _wait(lambda: _summaries(ids[0]) == 1)

    out = llm_api.ollama_release()
    assert out.get("deferred") is True and out.get("paused_runs") is True, out
    assert not released.is_set(), "the model was freed under a generation in flight"
    gate.release()  # the article in flight ends
    assert released.wait(15), "the release never happened once the run had paused"
    assert order == ["release:stopped"], order
    entry = {e["id"]: e for e in queue.snapshot()["entries"]}[eid]
    assert entry["state"] == "paused", entry
    # Resume finishes the run without storing any article twice.
    for _ in range(10):
        gate.release()
    assert queue.resume()
    assert lbq._JOB.join(15)
    assert [_summaries(a) for a in ids] == [1, 1, 1, 1]


def test_with_nothing_running_the_release_and_the_stop_happen_at_once(monkeypatch):
    import src.llm.ollama_lifecycle as life
    from src.api import llm as llm_api

    monkeypatch.setattr(life, "release_vram", lambda: {"released": [], "attempted": True})
    monkeypatch.setattr(life, "owns_daemon", lambda: True)
    monkeypatch.setattr(life, "stop", lambda: {"stopped": True})
    assert not lbq._JOB.status().get("running")
    assert llm_api.ollama_release() == {"released": [], "attempted": True}
    assert llm_api.ollama_stop() == {"stopped": True}


def test_a_daemon_this_app_does_not_own_is_refused_by_name_and_pauses_nothing(monkeypatch):
    import src.llm.ollama_lifecycle as life
    from src.api import llm as llm_api

    paused: list[int] = []
    monkeypatch.setattr(lbq, "pause_for_backend", lambda: paused.append(1) or True)
    monkeypatch.setattr(life, "owns_daemon", lambda: False)
    monkeypatch.setattr(life, "stop", lambda: {"stopped": False, "reason": "not started by this app"})
    assert llm_api.ollama_stop() == {"stopped": False, "reason": "not started by this app"}
    assert paused == [], "a stop the app refuses paused a run for nothing"


# ------------------------------------------------------------------ the re-index backlog row


class _Job:
    def __init__(self, state: str = "idle"):
        self.state = state

    def status(self) -> dict:
        return {"state": self.state}


@pytest.fixture()
def backlog(monkeypatch):
    import src.api.jobs as jobs_api

    reads: list[int] = []
    box = {"pending": 12, "available": True, "job": _Job()}

    def _read():
        reads.append(1)
        return {"available": box["available"], "articles_pending": box["pending"]}

    monkeypatch.setattr("src.backup.merge.reindex_backlog", _read)
    monkeypatch.setattr("src.jobs.background.get_job", lambda kind: box["job"] if kind == "reindex-resume" else None)
    monkeypatch.setattr(jobs_api, "_backlog_cache", {"at": 0.0, "value": None})
    return jobs_api, reads, box


def test_a_waiting_backlog_is_one_row_with_resume_and_is_read_once_per_window(backlog):
    jobs_api, reads, _box = backlog
    rows = jobs_api._reindex_backlog_rows()
    assert [(r["id"], r["state"], r["actions"]) for r in rows] == [("reindex-backlog", "paused", ["resume"])]
    assert "(12)" in rows[0]["label"]
    jobs_api._reindex_backlog_rows()
    jobs_api._reindex_backlog_rows()
    assert len(reads) == 1, "the polled task manager re-read a backlog that is linear in its size"


def test_no_row_for_an_empty_or_unreadable_backlog_or_while_its_job_runs(backlog):
    jobs_api, _reads, box = backlog
    box["pending"] = 0
    assert jobs_api._reindex_backlog_rows() == []
    jobs_api._backlog_cache["value"] = None
    box["pending"], box["available"] = 5, False  # unreadable is not "empty", but there is nothing true to draw a count from
    assert jobs_api._reindex_backlog_rows() == []
    jobs_api._backlog_cache["value"] = None
    box["available"], box["job"] = True, _Job("running")  # the running job is its own row, with Cancel
    assert jobs_api._reindex_backlog_rows() == []


def test_the_backlog_resume_is_refused_under_an_exclusive_hold_and_starts_the_job_otherwise(backlog, monkeypatch):
    jobs_api, _reads, _box = backlog
    started: list[int] = []
    monkeypatch.setattr("src.api.backup_v2.reindex_backlog_resume", lambda: started.append(1) or {"started": True})

    class _Sched:
        hold = True

        def holds_exclusive(self):
            return self.hold

    sched = _Sched()
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: sched)
    with pytest.raises(HTTPException) as e:
        jobs_api.resume_job("reindex-backlog")
    assert e.value.status_code == 409 and started == []
    sched.hold = False
    jobs_api._backlog_cache["value"] = {"available": True, "articles_pending": 3}
    assert jobs_api.resume_job("reindex-backlog")["resumed"] == "reindex-backlog"
    assert started == [1] and jobs_api._backlog_cache["value"] is None, "the row outlived the Resume that started its job"


# ------------------------------------------------------------------ the UI halves


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_ui_halves():
    r = subprocess.run(["node", str(_ROOT / "tests" / "model_and_pause_controls_node_test.js")],
                       capture_output=True, text=True, timeout=60, cwd=str(_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MODEL AND PAUSE CONTROLS OK" in r.stdout


def test_each_control_sits_where_its_task_is():
    core = (_ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    tm = (_ROOT / "src/static/taskmanager.js").read_text(encoding="utf-8")
    ai = (_ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    # The low-memory pause carries its own Resume in both task managers, and it POSTs the guard's retry.
    assert core.count('a.phase === "paused-low-memory" ? " " + _memResumeBtn(') == 2
    assert "/api/scheduler/memory-guard/resume" in core and "/api/scheduler/memory-guard/resume" in tm
    assert 'data-tm="memory-resume"' in tm and 'act === "memory-resume"' in tm
    # The backlog row resumes through the local-kind path (no consent: local work).
    assert 'j.kind === "reindex-backlog"' in core and '"reindex-backlog"' in tm
    # Settings > Models: free the GPU always when Ollama runs; stop only the daemon this app started.
    assert "releaseOllama(this)" in ai and "(oll.can_stop" in ai and "stopOllama(this)" in ai
    assert "/api/llm/ollama/release" in ai and "/api/llm/ollama/stop" in ai
    assert "_vllmInstallCost()" in ai and "/api/llm/vllm/install/preflight" in ai
