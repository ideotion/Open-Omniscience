"""
Endpoint-level tests for the qualification-assist API (B7.2, 2026-07-24
field-feedback Session B). Uses app.dependency_overrides[get_db] over an
isolated in-memory engine (the established endpoint-test pattern -- never
seed the shared SessionLocal).
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import diagnostics as d
from src.database.models import Article, Base, Source


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def test_run_404s_for_an_unknown_source(db_session):
    body = d.QualificationAssistBody(source_id=999)
    with pytest.raises(HTTPException) as ei:
        d.qualification_assist_run(body, db=db_session)
    assert ei.value.status_code == 404


def test_run_persists_a_proposals_artifact_and_never_touches_the_source(
    db_session, tmp_path, monkeypatch
):
    from src.ai_layer import qualification_assist as QA

    monkeypatch.setattr(QA, "_dir", lambda: tmp_path)

    class _FakeResult:
        def __init__(self, text):
            self.text = text

    class _FakeClient:
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            low = prompt.lower()
            if "storm" in low or "residents" in low:
                return _FakeResult("article")
            if "subscribe" in low or "privacy policy" in low:
                return _FakeResult("junk")
            return _FakeResult("junk")

    monkeypatch.setattr(
        "src.llm.backend.get_client_with_name", lambda *a, **kw: ("ollama", _FakeClient())
    )

    src = Source(name="Src", domain="src.test", tags="news")
    db_session.add(src)
    db_session.flush()
    db_session.add(Article(
        url="https://src.test/1", canonical_url="https://src.test/1", source_id=src.id,
        title="Nav page", content="this is a menu of links to subscribe", hash="h1",
    ))
    db_session.commit()
    before_status = src.status

    body = d.QualificationAssistBody(source_id=src.id)
    resp = d.qualification_assist_run(body, db=db_session)
    payload = json.loads(bytes(resp.body))
    assert payload["source_id"] == src.id
    assert payload["checked"] == 1

    db_session.refresh(src)
    assert src.status == before_status  # never auto-decided


def test_last_is_an_honest_stub_when_nothing_has_run(tmp_path, monkeypatch):
    from src.ai_layer import qualification_assist as QA

    monkeypatch.setattr(QA, "_dir", lambda: tmp_path)
    resp = d.qualification_assist_last(source_id=None)
    body = json.loads(bytes(resp.body))
    assert body["available"] is False


def test_selftest_endpoint_passes():
    resp = d.qualification_assist_selftest(download=False)
    body = json.loads(bytes(resp.body))
    assert body["passed"] is True
