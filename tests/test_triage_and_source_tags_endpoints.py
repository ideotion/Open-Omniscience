"""
Endpoint-level tests for the keyword-triage and source-tags job APIs
(mirrors ``test_p0_validation.py``'s endpoint-test style -- call the FastAPI
route functions directly, no TestClient needed).
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from src.api import diagnostics as d


def _reset(job):
    with job._lock:
        job._state = "idle"
        job._result = None
        job._thread = None
        job._error = None


@pytest.fixture(autouse=True)
def _clean_jobs():
    _reset(d._KEYWORD_TRIAGE_JOB)
    _reset(d._SOURCE_TAGS_JOB)
    yield
    _reset(d._KEYWORD_TRIAGE_JOB)
    _reset(d._SOURCE_TAGS_JOB)


def test_keyword_triage_run_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    body = d.KeywordTriageRunBody(model="stub:test")
    with pytest.raises(HTTPException) as ei:
        d.keyword_triage_run(body)
    assert ei.value.status_code == 409
    assert "airplane" in ei.value.detail


def test_keyword_triage_run_refuses_an_uninstalled_model(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.ollama.OllamaClient",
        lambda *a, **kw: type("C", (), {"list_installed": lambda self: ["granite4:micro"]})(),
    )
    body = d.KeywordTriageRunBody(model="not-installed:tag")
    with pytest.raises(HTTPException) as ei:
        d.keyword_triage_run(body)
    assert ei.value.status_code == 400
    assert "not installed" in ei.value.detail


def test_keyword_triage_download_is_404_until_a_run_completes():
    with pytest.raises(HTTPException) as ei:
        d.keyword_triage_download()
    assert ei.value.status_code == 404


def test_keyword_triage_cancel_is_idempotent_and_returns_status():
    resp = d.keyword_triage_cancel()
    body = json.loads(bytes(resp.body))
    assert "state" in body and body["kind"] == "keyword-triage"


def test_keyword_triage_last_is_an_honest_stub_when_nothing_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr("src.ai_layer.triage_job._triage_dir", lambda: tmp_path)
    resp = d.keyword_triage_last()
    body = json.loads(bytes(resp.body))
    assert body["available"] is False


def test_source_tags_run_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    body = d.SourceTagsRunBody(model="stub:test")
    with pytest.raises(HTTPException) as ei:
        d.source_tags_run(body)
    assert ei.value.status_code == 409


def test_source_tags_run_refuses_an_uninstalled_model(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.ollama.OllamaClient",
        lambda *a, **kw: type("C", (), {"list_installed": lambda self: ["granite4:micro"]})(),
    )
    body = d.SourceTagsRunBody(model="not-installed:tag")
    with pytest.raises(HTTPException) as ei:
        d.source_tags_run(body)
    assert ei.value.status_code == 400


def test_source_tags_download_is_404_until_a_run_completes():
    with pytest.raises(HTTPException) as ei:
        d.source_tags_download()
    assert ei.value.status_code == 404


def test_source_tags_cancel_is_idempotent_and_returns_status():
    resp = d.source_tags_cancel()
    body = json.loads(bytes(resp.body))
    assert "state" in body and body["kind"] == "source-tags"


def test_source_tags_last_is_an_honest_stub_when_nothing_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr("src.ai_layer.source_tags_job._dir", lambda: tmp_path)
    resp = d.source_tags_last()
    body = json.loads(bytes(resp.body))
    assert body["available"] is False


def test_source_tags_selftest_endpoint_passes():
    resp = d.source_tags_selftest(download=False)
    body = json.loads(bytes(resp.body))
    assert body["passed"] is True


def test_keyword_triage_job_status_stays_done_while_result_state_is_error(monkeypatch, tmp_path):
    """KNOWN WRINKLE (documented, not fixed at the BackgroundJob layer): a worker
    that catches an exception and returns normally -- as ``run_keyword_triage_job``
    does for an Ollama outage mid-run, per its own honesty contract -- leaves
    ``BackgroundJob._state`` at 'done'; only the run's own ``result.state`` says
    'error'. The panel JS checks ``result.state`` first (see runKeywordTriage in
    app.js) specifically because of this. This test exercises the REAL
    ``BackgroundJob.start()`` (a thread, joined) to prove the wiring an operator
    actually hits, not just the worker function in isolation."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database.models import Base, Keyword

    # StaticPool: the worker runs on a REAL background thread (BackgroundJob.start()),
    # and SQLite's default per-thread pooling for ':memory:' would hand that thread a
    # brand-new, table-less database -- StaticPool keeps the ONE connection shared.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add(
        Keyword(
            term="topic", normalized_term="topic", language="en", article_count=5, mention_count=10
        )
    )
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
    monkeypatch.setattr("src.ai_layer.triage_job._triage_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: RaisingClient())

    d._KEYWORD_TRIAGE_JOB.start(model="stub:test", limit=10, min_articles=0, batch_size=5)
    d._KEYWORD_TRIAGE_JOB._thread.join(5)

    st = d.keyword_triage_status()
    body = json.loads(bytes(st.body))
    assert body["state"] == "done"  # the BackgroundJob layer: no exception escaped
    assert body["result"]["state"] == "error"  # the ACTUAL run outcome
    assert "simulated outage" in body["result"]["error"]
