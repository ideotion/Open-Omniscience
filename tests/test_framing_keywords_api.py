"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoint tests for the framing and keyword-management routers (finding TEST-05,
0.0.8 WP4). Both routers need the [analysis] extra; on a core-only install this
module is collect_ignore'd by conftest.py alongside the other analysis tests.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("vaderSentiment", reason="framing/keywords need the [analysis] extra")

from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Article, Source
from src.database.session import init_db, session_scope

_TEXT = (
    "The new water treaty reshapes river management across the basin. Critics call "
    "the water treaty rushed; supporters say river management finally gets funding."
)


def _seed(n: int = 3) -> None:
    init_db()
    with session_scope() as s:
        domain = f"frame-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"Framing {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        for i in range(n):
            s.add(
                Article(
                    url=f"https://{domain}/a/{i}",
                    canonical_url=f"https://{domain}/a/{i}",
                    source_id=src.id,
                    title=f"Treaty take {i}",
                    content=_TEXT + f" Take number {i}.",
                    language="en",
                    hash=uuid.uuid4().hex + uuid.uuid4().hex,
                )
            )


# --- framing ----------------------------------------------------------------- #


def test_framing_without_query_uses_recent_articles():
    _seed()
    with TestClient(app) as client:
        r = client.get("/api/framing")
        assert r.status_code == 200
        body = r.json()
        assert body["total_articles"] >= 1
        assert isinstance(body["framing"], list)


def test_framing_rejects_invalid_query():
    with TestClient(app) as client:
        r = client.get("/api/framing", params={"query": "(water AND"})
        assert r.status_code == 400


def test_framing_caveat_discloses_vader_english_limit():
    """B1 disclosure (audit-07): the framing surface shows VADER tone per outlet,
    so its caveat MUST state that VADER is an English-lexicon method and tone for
    non-English coverage is unreliable -- otherwise a non-English corpus is scored
    silently. (corpus-sentiment already discloses this; framing did not.)"""
    _seed()
    with TestClient(app) as client:
        cav = (client.get("/api/framing").json().get("caveat") or "").lower()
        assert "vader" in cav and "english" in cav, f"framing caveat omits the VADER/English limit: {cav!r}"


# --- keyword management ------------------------------------------------------ #


def test_extract_keywords_from_text():
    with TestClient(app) as client:
        r = client.get("/api/keywords/extract", params={"text": _TEXT})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        terms = [k["term"] if isinstance(k, dict) else k for k in body["result"]["keywords"]]
        assert any("treaty" in str(t).lower() or "water" in str(t).lower() for t in terms)


def test_extract_requires_text_param():
    with TestClient(app) as client:
        r = client.get("/api/keywords/extract")
        assert r.status_code == 422  # FastAPI validation: text is required


def test_extract_article_weights_title():
    with TestClient(app) as client:
        r = client.post(
            "/api/keywords/extract/article",
            params={"article_text": _TEXT, "title": "Water treaty"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


def test_categories_statistics_and_frequencies_respond():
    _seed()
    with TestClient(app) as client:
        for path in ("/api/keywords/categories", "/api/keywords/statistics",
                     "/api/keywords/frequencies"):
            r = client.get(path, params={"text": _TEXT})
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            assert r.json().get("success", True) is not False


# --------------------------------------------------------------------------- #
# 2026-08-20 additions (quality-ratchet session, TEST-05 residue): the honest
# failure paths framing never had, and the four keyword routes WP4 left out.
# --------------------------------------------------------------------------- #


def test_framing_limit_bounds_are_validated():
    """limit is declared ge=2, le=1000 — both sides must 422, not clamp
    silently (the floor is 2, not 1: a one-article "comparison" is not one)."""
    with TestClient(app) as client:
        assert client.get("/api/framing", params={"limit": 1}).status_code == 422
        assert client.get("/api/framing", params={"limit": 2000}).status_code == 422


def test_framing_zero_match_query_returns_the_full_empty_shape():
    """A query matching nothing is a REAL answer (200 + zeros), never a 404 —
    and the payload must still carry every disclosure field, so a consumer
    reading analyzed_n/capped never KeyErrors on an empty corpus."""
    with TestClient(app) as client:
        r = client.get(
            "/api/framing", params={"query": f"zz{uuid.uuid4().hex[:12]}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["sources_compared"] == 0
        assert body["total_articles"] == 0
        assert body["framing"] == []
        for key in ("shared_terms", "caveat", "analyzed_n", "total_n", "capped"):
            assert key in body, f"empty framing payload dropped {key!r}"


def test_top_phrases_categorize_and_process_respond():
    """The four keyword_management routes WP4 left uncovered at HTTP level."""
    with TestClient(app) as client:
        for path, params in (
            ("/api/keywords/top", {"text": _TEXT}),
            ("/api/keywords/phrases", {"text": _TEXT}),
            ("/api/keywords/process", {"text": _TEXT}),
            ("/api/keywords/categorize", {"keywords": ["water", "treaty"]}),
        ):
            r = client.get(path, params=params)
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            assert r.json()["success"] is True, f"{path} reported failure"


def test_top_requires_text_param():
    with TestClient(app) as client:
        assert client.get("/api/keywords/top").status_code == 422
