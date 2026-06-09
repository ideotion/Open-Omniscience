"""
Tests for the Theme-4 briefing producers: story lineage + coverage advisor.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing.producers import coverage_advisor, story_lineage
from src.database.models import Article, Base, Source

_WIRE = ("According to Reuters, the central bank raised interest rates by half a point today "
         "amid persistent inflation and a tight labour market, signalling that further "
         "tightening could follow before the end of the year if price pressures do not ease.")


@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    now = datetime.now(UTC)
    for i in range(12):  # 12 FR outlets echoing one wire story
        src = Source(name=f"outlet{i:02d}", domain=f"o{i:02d}.fr", country="fr", language="fr")
        s.add(src)
        s.flush()
        s.add(Article(url=f"https://o{i:02d}.fr/x", canonical_url=f"https://o{i:02d}.fr/x",
                      source_id=src.id, title="Rates decision", content=_WIRE, hash=f"h{i}",
                      language="fr", published_at=now - timedelta(hours=20 - i), created_at=now))
    s.commit()
    return s


def test_story_lineage_traces_to_wire(corpus):
    cards = story_lineage(corpus)
    assert cards, "expected a lineage card from a 12-outlet echoed story"
    c = cards[0]
    assert c.bucket == "context"
    assert c.signal["wire_origin"] == "Reuters"
    assert c.signal["metric"] == "echoing_sources" and c.signal["value"] == 12
    assert "earliest" in c.caveat.lower()           # honest: not "the truth"


def test_coverage_advisor_flags_single_country_skew(corpus):
    cards = coverage_advisor(corpus)
    assert cards, "expected a coverage card when 100% of collection is one country"
    c = cards[0]
    assert c.bucket == "context"
    assert c.signal["value"] == 1.0                 # 100% one country
    assert "suggestion" in c.summary.lower() or "consider" in c.summary.lower()
    assert "never filters or caps" in c.caveat.lower()   # surface, never enforce
