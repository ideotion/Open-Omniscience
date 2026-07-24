"""
Endpoint-level tests for the B6 (2026-07-24 Session B) LIVE perception-eval
run (POST /api/diagnostics/perception-eval-live + its /last reader). Calls the
FastAPI route functions directly (mirrors test_triage_and_source_tags_
endpoints.py's style) -- no TestClient, no network; the active backend is
injected via the same llm_backend.get_client_with_name seam B5's tests use.
"""

from __future__ import annotations

import json

from src.ai_layer import perception_job as J
from src.api import diagnostics as d
from src.llm import backend as llm_backend


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("WHO: none\nWHERE: none\nWHEN: none")


def test_perception_eval_live_runs_against_the_resolved_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _FakeClient())
    )
    body = d.PerceptionEvalLiveBody(model="stub:test")
    resp = d.perception_eval_live(body)
    payload = json.loads(bytes(resp.body))
    assert payload["status"] == "ok"
    assert payload["model"] == "stub:test"
    assert payload["backend"] == "ollama"
    assert "report" in payload


def test_perception_eval_live_last_is_an_honest_stub_when_nothing_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    resp = d.perception_eval_live_last()
    payload = json.loads(bytes(resp.body))
    assert payload["available"] is False


def test_perception_eval_live_last_reads_the_saved_run(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _FakeClient())
    )
    d.perception_eval_live(d.PerceptionEvalLiveBody(model="stub:test"))
    resp = d.perception_eval_live_last()
    payload = json.loads(bytes(resp.body))
    assert payload["available"] is True
    assert payload["model"] == "stub:test"
