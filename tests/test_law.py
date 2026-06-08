"""
Tests for the world-law change-tracking vertical (§5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Catalog load + seeding, baseline → change → flag tracking (with a stub fetcher), the
model-legislation cross-jurisdiction near-dup card, and the API surface. No network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision, Source
from src.ingest import FetchResult
from src.law.catalog import load_legal_catalog, register_documents, seed_legal_sources
from src.law.track import page_text, track_document, track_watched

_BODY = (" ".join(f"Section {i}: every person shall have the right to liberty and security."
                  for i in range(40)))
_BIGGER = _BODY + " " + " ".join(f"Amendment {i}: this provision is hereby substituted and "
                                 "extended across the realm." for i in range(60))


def _html(body: str) -> str:
    return f"<html><head><title>Act</title></head><body><main>{body}</main></body></html>"


class StubFetcher:
    """A deterministic fetcher: serves a programmable page per URL (no network)."""

    def __init__(self):
        self.page = ""

    def fetch(self, url: str, *, require_html: bool = True) -> FetchResult:
        return FetchResult(requested_url=url, final_url=url, status_code=200,
                           content=self.page, content_type="text/html", fetched_at=datetime.now(UTC))


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------------------------------------------------------- #
#  Catalog + seeding
# --------------------------------------------------------------------------- #
def test_catalog_loads_real_sources_and_documents():
    cat = load_legal_catalog()
    assert len(cat["sources"]) >= 30          # a worldwide set of official portals
    assert len(cat["documents"]) >= 5
    # Spot-check real official domains are present.
    domains = {s["domain"] for s in cat["sources"]}
    assert "legislation.gov.uk" in domains and "eur-lex.europa.eu" in domains
    assert any(s["source_type"] == "ip" for s in cat["sources"])


def test_seed_sources_and_register_documents(db):
    s = seed_legal_sources(db)
    assert s["created"] >= 30
    assert db.query(Source).filter_by(source_type="legal").count() >= 10
    d = register_documents(db)
    assert d["created"] >= 5
    # Idempotent.
    assert seed_legal_sources(db)["created"] == 0
    assert register_documents(db)["created"] == 0


# --------------------------------------------------------------------------- #
#  Tracking: baseline → unchanged → change (flagged) → revert
# --------------------------------------------------------------------------- #
def test_page_text_strips_chrome():
    txt = page_text("<html><body><script>x=1</script><nav>menu</nav><p>The law text.</p></body></html>")
    assert "The law text." in txt
    assert "menu" not in txt and "x=1" not in txt


def test_track_baseline_change_flag_revert(db):
    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://example.test/act")
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()

    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "baseline"
    assert doc.baseline_text is not None

    assert track_document(db, fetcher, doc)["status"] == "unchanged"

    fetcher.page = _html(_BIGGER)
    res = track_document(db, fetcher, doc)
    assert res["status"] == "changed"
    assert res["delta_bytes"] > 1000 and res["flagged"] is True
    assert "large_addition" in res["flag_reasons"]

    # Reverting to the baseline text is recognised as a known version, not a new change.
    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "reverted"

    revs = db.query(LawRevision).filter_by(document_id=doc.id).count()
    assert revs == 2  # baseline + the one genuine change


def test_track_watched_tally_and_fetch_error(db):
    db.add(LawDocument(jurisdiction="uk", title="A", url="https://ex.test/a"))
    db.commit()

    class BadFetcher:
        def fetch(self, url, *, require_html=True):
            from src.ingest import FetchFailed
            raise FetchFailed("boom")

    tally = track_watched(db, BadFetcher())
    assert tally["errors"] == 1 and tally["baselines"] == 0  # loud degradation, no fabrication


# --------------------------------------------------------------------------- #
#  Model-legislation card (cross-jurisdiction near-dup) + law-change card
# --------------------------------------------------------------------------- #
def test_model_legislation_producer(db):
    text = _BODY
    db.add(LawDocument(jurisdiction="uk", title="UK Bill", url="https://uk.test/x", baseline_text=text))
    db.add(LawDocument(jurisdiction="us", title="US Bill", url="https://us.test/x", baseline_text=text))
    db.add(LawDocument(jurisdiction="uk", title="Other", url="https://uk.test/y",
                       baseline_text="A wholly different statute about fishing quotas and coastal waters." * 5))
    db.commit()
    from src.briefing.producers import model_legislation

    cards = model_legislation(db)
    assert cards, "expected a cross-jurisdiction model-legislation card"
    c = cards[0]
    assert c.bucket == "investigate"
    assert set(c.signal["jurisdictions"]) == {"uk", "us"}


def test_law_change_card(db):
    doc = LawDocument(jurisdiction="eu", title="GDPR", url="https://eu.test/gdpr",
                      official_url="https://eur-lex.europa.eu/x")
    db.add(doc)
    db.commit()
    db.add(LawRevision(document_id=doc.id, observed_at=datetime.now(UTC), content_hash="h1",
                       size=5000, delta_bytes=1500, flagged=True, flag_reasons="large_addition"))
    db.commit()
    from src.briefing.producers import law_change

    cards = law_change(db)
    assert cards and cards[0].bucket == "watch"
    assert cards[0].evidence[0]["url"] == "https://eur-lex.europa.eu/x"


# --------------------------------------------------------------------------- #
#  API smoke
# --------------------------------------------------------------------------- #
def test_law_api(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    from fastapi.testclient import TestClient

    from src.api.main import app
    with TestClient(app) as c:
        seeded = c.post("/api/law/seed").json()
        # Assert the idempotent TOTAL (created-or-already-present), so the test is robust
        # to the app DB being shared across TestClient tests in a full run.
        assert seeded["sources"]["total"] >= 30
        assert seeded["documents"]["total"] >= 5
        status = c.get("/api/law/status").json()
        assert status["documents"] >= 5 and "caveat" in status
        docs = c.get("/api/law/documents").json()
        assert len(docs["documents"]) >= 5
