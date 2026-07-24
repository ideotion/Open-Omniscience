"""
Endpoint-level tests for the who/where/when perception-EXTRACTION job API (B6.2/
B6.3, 2026-07-24 field-feedback Session B). Mirrors
test_triage_and_source_tags_endpoints.py's exact style -- call the FastAPI route
functions directly, no TestClient.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from src.api import diagnostics as d
from src.llm import backend as llm_backend
from src.llm.ollama import LLMUnavailable


def _fake_client(list_installed):
    return type("C", (), {"list_installed": list_installed})()


def _reset(job):
    with job._lock:
        job._state = "idle"
        job._result = None
        job._thread = None
        job._error = None


@pytest.fixture(autouse=True)
def _clean_job():
    _reset(d._PERCEPTION_EXTRACT_JOB)
    yield
    _reset(d._PERCEPTION_EXTRACT_JOB)


def test_perception_extract_run_starts_under_airplane_mode_with_loopback(monkeypatch):
    """Loopback inference is airplane-safe (mirrors the keyword-triage gate-split
    proof) -- the endpoint carries no blanket kill-switch refusal of its own."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    started_kwargs: dict = {}
    monkeypatch.setattr(
        d._PERCEPTION_EXTRACT_JOB,
        "start",
        lambda **kw: (
            started_kwargs.update(kw),
            {"state": "running", "kind": "perception-extract"},
        )[1],
    )
    body = d.PerceptionExtractRunBody(model="granite4:micro")
    resp = d.perception_extract_run(body)
    payload = json.loads(bytes(resp.body))
    assert payload["started"] is True
    assert started_kwargs["model"] == "granite4:micro"


def test_perception_extract_run_still_refuses_when_backend_genuinely_unavailable(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    def _raise_unavailable(self):
        raise LLMUnavailable("Network is OFF (airplane mode): refusing the request.")

    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _fake_client(_raise_unavailable))
    )
    body = d.PerceptionExtractRunBody(model="stub:test")
    with pytest.raises(HTTPException) as ei:
        d.perception_extract_run(body)
    assert ei.value.status_code == 409


def test_perception_extract_run_refuses_an_uninstalled_model(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    body = d.PerceptionExtractRunBody(model="not-installed:tag")
    with pytest.raises(HTTPException) as ei:
        d.perception_extract_run(body)
    assert ei.value.status_code == 400
    assert "not installed" in ei.value.detail


def test_perception_extract_download_is_404_until_a_run_completes():
    with pytest.raises(HTTPException) as ei:
        d.perception_extract_download()
    assert ei.value.status_code == 404


def test_perception_extract_cancel_is_idempotent_and_returns_status():
    resp = d.perception_extract_cancel()
    body = json.loads(bytes(resp.body))
    assert "state" in body and body["kind"] == "perception-extract"


def test_perception_extract_last_is_an_honest_stub_when_nothing_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr("src.ai_layer.perception_extract_job._dir", lambda: tmp_path)
    resp = d.perception_extract_last()
    body = json.loads(bytes(resp.body))
    assert body["available"] is False


def test_perception_extract_gate_reads_the_saved_live_eval_report(monkeypatch):
    monkeypatch.setattr(
        "src.ai_layer.perception_job.last_perception_eval_live_report",
        lambda: {"by_language": {"en": {
            "who": {"hallucination_rate": 0.0},
            "where": {"hallucination_rate": 0.0},
            "when": {"hallucination_rate": 0.0},
        }}},
    )
    resp = d.perception_extract_gate()
    body = json.loads(bytes(resp.body))
    assert body["en"]["active"] is True


def test_perception_extract_job_status_reports_a_paused_progressive_sweep_on_an_outage(
    monkeypatch, tmp_path
):
    """Mirrors the keyword-triage proof exactly: a local-model outage PAUSES the
    sweep (complete: False + paused_reason) -- the BackgroundJob layer itself
    still reaches 'done' (the worker caught the exception and returned normally).
    Exercises the REAL BackgroundJob.start() (a thread, joined)."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database.models import Article, Base, Source

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    src = Source(name="Src", domain="src.test", tags="news")
    session.add(src)
    session.flush()
    session.add(Article(
        url="https://src.test/1", canonical_url="https://src.test/1", source_id=src.id,
        title="T", content="c", language="en", hash="h1",
    ))
    session.commit()

    @contextmanager
    def fake_scope():
        yield session
        session.commit()

    class RaisingClient:
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            from src.llm.ollama import LLMUnavailable

            raise LLMUnavailable("simulated outage")

    monkeypatch.setattr("src.database.session.session_scope", fake_scope)
    monkeypatch.setattr("src.ai_layer.perception_extract_job._dir", lambda: tmp_path)

    gate_report = {"by_language": {"en": {
        "who": {"hallucination_rate": 0.0},
        "where": {"hallucination_rate": 0.0},
        "when": {"hallucination_rate": 0.0},
    }}}
    d._PERCEPTION_EXTRACT_JOB.start(
        model="stub:test", batch_size=5, client=RaisingClient(), gate_report=gate_report,
    )
    d._PERCEPTION_EXTRACT_JOB._thread.join(5)

    st = d.perception_extract_status()
    body = json.loads(bytes(st.body))
    assert body["state"] == "done"
    assert body["result"]["complete"] is False
    assert "simulated outage" in body["result"]["paused_reason"]
