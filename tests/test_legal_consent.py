"""Tests for the legal consent gate (src.legal.consent + src.api.legal).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These run without a browser and without the full app: the HTTP tests mount only the
legal router on a throwaway FastAPI app, and the consent record is isolated to a temp
data dir via OO_DATA_DIR.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def data_dir_env(tmp_path, monkeypatch):
    """Isolate the consent record to a temp data dir (read at call time by src.paths)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def test_needs_acceptance_when_no_record(data_dir_env):
    from src.legal import consent

    assert consent.load_consent() is None
    assert consent.needs_acceptance() is True
    assert consent.is_accepted() is False
    status = consent.consent_status()
    assert status["required"] is True
    assert status["accepted_version"] is None
    assert len(status["documents"]) == 4


def test_record_then_accepted(data_dir_env):
    from src.legal import consent

    rec = consent.record_consent()
    assert rec["version"] == consent.CONSENT_DOC_VERSION
    # ISO-8601, timezone-aware timestamp.
    ts = datetime.fromisoformat(rec["accepted_at"])
    assert ts.tzinfo is not None
    assert consent.consent_path().is_file()
    assert consent.is_accepted() is True
    assert consent.needs_acceptance() is False
    on_disk = json.loads(consent.consent_path().read_text(encoding="utf-8"))
    assert on_disk["schema"] == consent.CONSENT_SCHEMA
    assert on_disk["documents"] == [d["id"] for d in consent.LEGAL_DOCUMENTS]


def test_version_bump_reprompts(data_dir_env):
    from src.legal import consent

    consent.record_consent("0.draft")
    assert consent.is_accepted("0.draft") is True
    # A newer document-set version has not been accepted yet -> re-prompt.
    assert consent.needs_acceptance("99.next") is True
    assert consent.is_accepted("99.next") is False


def test_corrupt_record_is_not_accepted(data_dir_env):
    from src.legal import consent

    consent.consent_path().write_text("{ not valid json", encoding="utf-8")
    assert consent.load_consent() is None
    assert consent.needs_acceptance() is True


def _legal_app() -> FastAPI:
    from src.api.legal import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_api_status_and_accept(data_dir_env):
    from src.legal.consent import CONSENT_DOC_VERSION

    client = TestClient(_legal_app())
    body = client.get("/api/legal/consent").json()
    assert body["required"] is True
    assert len(body["documents"]) == 4

    r = client.post("/api/legal/consent", json={"version": CONSENT_DOC_VERSION})
    assert r.status_code == 200
    assert r.json()["required"] is False

    after = client.get("/api/legal/consent").json()
    assert after["required"] is False
    assert after["accepted_version"] == CONSENT_DOC_VERSION


def test_api_version_mismatch_rejected(data_dir_env):
    from src.legal import consent

    client = TestClient(_legal_app())
    r = client.post("/api/legal/consent", json={"version": "totally-wrong"})
    assert r.status_code == 400
    # Nothing was recorded.
    assert consent.needs_acceptance() is True
