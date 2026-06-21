"""Model-download queue: pulls run one at a time, cancellable (brief §2.C1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading

import pytest

from src.llm.pull_queue import ModelPullManager


class _FakeClient:
    """Yields Ollama-style progress; a "block" model waits on a release event so the
    test can deterministically observe the active pull + cancel it."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()
        self._active = 0
        self.max_concurrent = 0
        self.pulled = []

    def pull(self, model):
        self._active += 1
        self.max_concurrent = max(self.max_concurrent, self._active)
        if model == "block":
            self.started.set()
        yield {"status": "pulling", "total": 100, "completed": 50}
        if model == "block":
            self.release.wait(2)
        yield {"status": "success", "total": 100, "completed": 100}
        self._active -= 1
        self.pulled.append(model)


def _mgr(fake):
    return ModelPullManager(client_factory=lambda: fake)


def _join(mgr, t=3.0):
    if mgr._thread is not None:
        mgr._thread.join(t)


def test_pulls_run_one_at_a_time():
    fake = _FakeClient()
    mgr = _mgr(fake)
    for m in ("a:1", "b:1", "c:1"):
        mgr.enqueue(m)
    _join(mgr)
    assert fake.max_concurrent == 1
    assert fake.pulled == ["a:1", "b:1", "c:1"]  # sequential, in order
    done = {h["model"]: h["status"] for h in mgr.status()["history"]}
    assert done == {"a:1": "done", "b:1": "done", "c:1": "done"}


def test_cancel_queued_removes_it():
    fake = _FakeClient()
    mgr = _mgr(fake)
    mgr.enqueue("block")
    fake.started.wait(2)  # the pump is now busy pulling "block"
    mgr.enqueue("later")
    assert "later" in mgr.status()["queue"]
    mgr.cancel("later")  # removed from the queue while block is active
    assert "later" not in mgr.status()["queue"]
    fake.release.set()
    _join(mgr)
    hist = {h["model"]: h["status"] for h in mgr.status()["history"]}
    assert hist.get("later") == "cancelled" and hist.get("block") == "done"
    assert "later" not in fake.pulled


def test_cancel_active_aborts():
    fake = _FakeClient()
    mgr = _mgr(fake)
    mgr.enqueue("block")
    fake.started.wait(2)
    assert mgr.status()["active"]["model"] == "block"
    mgr.cancel("block")  # aborts the active pull (Ollama pull is not resumable)
    fake.release.set()
    _join(mgr)
    hist = {h["model"]: h["status"] for h in mgr.status()["history"]}
    assert hist.get("block") == "cancelled"


def test_bad_model_name_rejected():
    mgr = ModelPullManager()
    with pytest.raises(ValueError, match="invalid model name"):
        mgr.enqueue("../etc/passwd")


def test_idempotent_enqueue_and_status_shape():
    fake = _FakeClient()
    mgr = _mgr(fake)
    mgr.enqueue("block")
    fake.started.wait(2)
    mgr.enqueue("block")  # already active -> not queued twice
    assert mgr.status()["queue"] == []
    fake.release.set()
    _join(mgr)
    s = ModelPullManager().status()
    assert s == {"active": None, "queue": [], "history": []}
