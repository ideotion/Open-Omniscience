"""The background-task registry + its task-manager surface.

The task manager must show "what is actually happening" — including LLM/analysis
work, not only scrapes and downloads (maintainer 2026-06-18). src.monitoring.tasks
is a tiny live registry; /api/jobs surfaces it; /api/jobs/history serves completed
passes. The registry is pure stdlib so it runs in the core-only sandbox; the
/api/jobs tests import fastapi (CI).
"""

from __future__ import annotations

import time

import src.monitoring.tasks as tasks


def _reset():
    with tasks._LOCK:
        tasks._TASKS.clear()


def test_register_update_finish_roundtrip():
    _reset()
    tok = tasks.register("llm", "Translating 3 articles", detail="model x", total=3)
    snap = tasks.snapshot()
    assert len(snap) == 1
    assert snap[0]["kind"] == "llm" and snap[0]["label"] == "Translating 3 articles"
    assert snap[0]["total"] == 3 and snap[0]["done"] == 0
    assert snap[0]["elapsed_s"] >= 0

    tasks.update(tok, done=2, detail="2/3")
    snap = tasks.snapshot()
    assert snap[0]["done"] == 2 and snap[0]["detail"] == "2/3"

    tasks.finish(tok)
    assert tasks.snapshot() == []


def test_track_context_manager_always_finishes():
    _reset()
    with tasks.track("analytics", "Extracting keywords", total=10):
        assert len(tasks.snapshot()) == 1
    assert tasks.snapshot() == []  # finished on normal exit

    # ...and on an exception inside the block.
    try:
        with tasks.track("llm", "Summarizing"):
            assert len(tasks.snapshot()) == 1
            raise ValueError("boom")
    except ValueError:
        pass
    assert tasks.snapshot() == []


def test_stale_tasks_are_pruned():
    _reset()
    tok = tasks.register("llm", "leaked task")
    # Simulate a missed finish() by ageing the task past the stale window.
    with tasks._LOCK:
        tasks._TASKS[tok]["updated_at"] = time.time() - (tasks._STALE_S + 1)
    assert tasks.snapshot() == []  # snapshot prunes stale rows defensively


def test_snapshot_is_ordered_oldest_first():
    _reset()
    a = tasks.register("llm", "first")
    b = tasks.register("analytics", "second")
    labels = [t["label"] for t in tasks.snapshot()]
    assert labels == ["first", "second"]
    tasks.finish(a)
    tasks.finish(b)


def test_task_jobs_surface_in_api():
    # Imports fastapi (runs in CI; skipped where fastapi is absent).
    import pytest

    pytest.importorskip("fastapi")
    import src.api.jobs as jobs

    _reset()
    tok = tasks.register("llm", "Translating → French", detail="model x", total=4)
    tasks.update(tok, done=1)
    rows = jobs._task_jobs()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == f"task:{tok}" and row["kind"] == "llm"
    assert row["state"] == "running" and row["actions"] == []
    assert row["progress"]["total"] == 4 and row["progress"]["done"] == 1
    assert row["progress"]["percent"] == 25
    tasks.finish(tok)


def test_jobs_history_endpoint_shape(monkeypatch):
    import pytest

    pytest.importorskip("fastapi")
    import src.api.jobs as jobs

    sample = [{"ok": True, "result": {"articles_stored": 7, "mode": "rss", "duration_s": 12.3}}]
    monkeypatch.setattr("src.scheduler.runlog.recent_runs", lambda limit=20: sample)
    out = jobs.jobs_history(limit=5)
    assert out["count"] == 1 and out["runs"] == sample
