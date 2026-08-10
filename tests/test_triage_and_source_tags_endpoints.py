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
from src.llm import backend as llm_backend
from src.llm.ollama import LLMUnavailable


def _fake_client(list_installed):
    """A tiny stand-in with just the `list_installed` method the run endpoints
    call through the backend seam -- returned wrapped as ("ollama", client) so
    monkeypatching llm_backend.get_client_with_name works regardless of which
    backend name the test cares about (these tests never touch generate())."""
    return type("C", (), {"list_installed": list_installed})()


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


def test_keyword_triage_run_starts_under_airplane_mode_with_loopback_ollama(monkeypatch):
    """2026-07-24 gate-split fix (Session A §7): loopback Ollama inference is
    airplane-safe, so the endpoint's OWN blanket kill-switch refusal is gone --
    the run reaches .start() while airplane mode is engaged, gated only by the
    client's own loopback-vs-clearnet check (never touched here, and never
    exercised -- the stub client makes no socket call at all, loopback or not)."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    started_kwargs: dict = {}
    monkeypatch.setattr(
        d._KEYWORD_TRIAGE_JOB,
        "start",
        lambda **kw: (started_kwargs.update(kw), {"state": "running", "kind": "keyword-triage"})[
            1
        ],
    )
    body = d.KeywordTriageRunBody(model="granite4:micro")
    resp = d.keyword_triage_run(body)
    payload = json.loads(bytes(resp.body))
    assert payload["started"] is True
    assert started_kwargs["model"] == "granite4:micro"


def test_keyword_triage_run_still_refuses_when_ollama_is_genuinely_unavailable(monkeypatch):
    """The gate split removed the endpoint's OWN blanket refusal, not the client's
    loopback-vs-clearnet distinction: a non-loopback backend (or Ollama simply not
    running) still 409s under airplane mode -- defense in depth is untouched."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    def _raise_unavailable(self):
        raise LLMUnavailable(
            "Network is OFF (airplane mode): refusing the Ollama request. "
            "Turn airplane mode off to use the local LLM."
        )

    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(_raise_unavailable)),
    )
    body = d.KeywordTriageRunBody(model="stub:test")
    with pytest.raises(HTTPException) as ei:
        d.keyword_triage_run(body)
    assert ei.value.status_code == 409


def test_keyword_triage_run_refuses_an_uninstalled_model(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    body = d.KeywordTriageRunBody(model="not-installed:tag")
    with pytest.raises(HTTPException) as ei:
        d.keyword_triage_run(body)
    assert ei.value.status_code == 400
    assert "not installed" in ei.value.detail


def test_keyword_triage_run_falls_back_to_the_active_model_when_none_is_given(monkeypatch):
    """2026-07-26 field-remarks items 1-3: model omitted entirely (or null) must
    resolve via active_model() -- the SAME house-wide fallback perception_job.py's
    own extraction endpoint already uses -- never a required-field 422, and never
    forcing the user to type a model tag for a routine run."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["installed-default:tag"])),
    )
    monkeypatch.setattr("src.api.llm.active_model", lambda: "installed-default:tag")
    started_kwargs: dict = {}
    monkeypatch.setattr(
        d._KEYWORD_TRIAGE_JOB,
        "start",
        lambda **kw: (started_kwargs.update(kw), {"state": "running", "kind": "keyword-triage"})[
            1
        ],
    )
    body = d.KeywordTriageRunBody()  # model omitted -- must NOT 422
    resp = d.keyword_triage_run(body)
    assert resp.status_code == 200
    assert started_kwargs["model"] == "installed-default:tag"


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


def test_source_tags_run_starts_under_airplane_mode_with_loopback_ollama(monkeypatch):
    """Mirrors the keyword-triage gate-split proof: loopback Ollama is airplane-safe,
    so the endpoint's own blanket refusal is gone."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    started_kwargs: dict = {}
    monkeypatch.setattr(
        d._SOURCE_TAGS_JOB,
        "start",
        lambda **kw: (started_kwargs.update(kw), {"state": "running", "kind": "source-tags"})[1],
    )
    body = d.SourceTagsRunBody(model="granite4:micro")
    resp = d.source_tags_run(body)
    payload = json.loads(bytes(resp.body))
    assert payload["started"] is True
    assert started_kwargs["model"] == "granite4:micro"


def test_source_tags_run_still_refuses_when_ollama_is_genuinely_unavailable(monkeypatch):
    """A non-loopback backend (or Ollama simply not running) still 409s under
    airplane mode -- the gate split only removed the endpoint's redundant blanket
    check, never the client's own loopback-vs-clearnet gate."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    def _raise_unavailable(self):
        raise LLMUnavailable("Network is OFF (airplane mode): refusing the Ollama request.")

    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(_raise_unavailable)),
    )
    body = d.SourceTagsRunBody(model="stub:test")
    with pytest.raises(HTTPException) as ei:
        d.source_tags_run(body)
    assert ei.value.status_code == 409


def test_source_tags_run_refuses_an_uninstalled_model(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["granite4:micro"])),
    )
    body = d.SourceTagsRunBody(model="not-installed:tag")
    with pytest.raises(HTTPException) as ei:
        d.source_tags_run(body)
    assert ei.value.status_code == 400


def test_source_tags_run_falls_back_to_the_active_model_when_none_is_given(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        llm_backend,
        "get_client_with_name",
        lambda *a, **kw: ("ollama", _fake_client(lambda self: ["installed-default:tag"])),
    )
    monkeypatch.setattr("src.api.llm.active_model", lambda: "installed-default:tag")
    started_kwargs: dict = {}
    monkeypatch.setattr(
        d._SOURCE_TAGS_JOB,
        "start",
        lambda **kw: (started_kwargs.update(kw), {"state": "running", "kind": "source-tags"})[1],
    )
    body = d.SourceTagsRunBody()  # model omitted -- must NOT 422
    resp = d.source_tags_run(body)
    assert resp.status_code == 200
    assert started_kwargs["model"] == "installed-default:tag"


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


def test_keyword_triage_job_status_reports_a_genuine_error_after_a_permanent_outage(
    monkeypatch, tmp_path
):
    """2026-07-26 field-remarks item 7's honest-contract UPDATE to this test
    (was: 'reports_a_paused_progressive_sweep_on_an_outage', pinning the
    paused==done conflation as intentional -- superseded by the retry-with-
    backoff fix, NOT deleted per the field-remarks doc's own instruction).

    A SINGLE LLMUnavailable no longer immediately pauses the sweep -- it is
    retried with exponential backoff first (proven in isolation in
    tests/test_triage_progressive.py). Only once the retry budget is genuinely
    exhausted does the run terminate, and it now does so HONESTLY: the outer
    BackgroundJob state becomes 'error' (never a benign-looking 'done'), so
    /status, /last, and the generic /api/jobs task-manager list all agree a
    permanently-failed run is NOT resumable-in-place -- closing exactly the
    state-machine disagreement the original investigation named. This test
    exercises the REAL ``BackgroundJob.start()`` (a thread, joined) to prove the
    wiring an operator actually hits, not just the worker function in
    isolation; the outage client is passed directly via the ``client`` kwarg
    (the same seam ``run_progressive_triage_job`` exposes for tests) rather
    than monkeypatching ``OllamaClient`` globally. The retry budget + backoff
    are shrunk via monkeypatch so this test runs in milliseconds, not minutes."""
    from contextlib import contextmanager

    from src.ai_layer import triage_job as triage_job_mod

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
        def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
            from src.llm.ollama import LLMUnavailable

            raise LLMUnavailable("simulated outage")

    monkeypatch.setattr("src.database.session.session_scope", fake_scope)
    monkeypatch.setattr("src.ai_layer.triage_job._triage_dir", lambda: tmp_path)
    # A permanently-outaged backend now retries with backoff before giving up --
    # shrink the budget + backoff so this test runs fast (RaisingClient never
    # recovers, so the FULL default budget would otherwise really sleep for
    # minutes before this thread ever finishes).
    monkeypatch.setattr(triage_job_mod, "_TRIAGE_MAX_CONSECUTIVE_FAILURES", 2)
    monkeypatch.setattr(triage_job_mod, "_TRIAGE_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(triage_job_mod, "_TRIAGE_BACKOFF_CAP_S", 0.02)

    d._KEYWORD_TRIAGE_JOB.start(
        model="stub:test", min_articles=0, batch_size=5, client=RaisingClient()
    )
    d._KEYWORD_TRIAGE_JOB._thread.join(5)

    st = d.keyword_triage_status()
    body = json.loads(bytes(st.body))
    assert body["state"] == "error", (
        "the outer BackgroundJob state must genuinely read 'error' once the retry "
        "budget is exhausted -- never a benign-looking 'done' the generic "
        "/api/jobs task-manager list would silently filter out as finished"
    )
    assert "2 consecutive" in (body.get("error") or "")
    assert "simulated outage" in (body.get("error") or "")
