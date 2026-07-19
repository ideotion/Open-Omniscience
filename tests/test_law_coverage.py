"""
S5 of the law-vertical brief (2026-07-17): the per-jurisdiction law coverage/
freshness diagnostic. Counts + verdict tallies only, no score; THE COMPLETENESS
PRINCIPLE (never present a tracked count as a coverage claim) is pinned as an
explicit, honest string on every jurisdiction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.law.coverage import law_coverage_report


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_empty_store_reports_zero_honestly():
    s = _session()
    r = law_coverage_report(s)
    assert r["documents"] == 0 and r["baselined"] == 0
    assert r["jurisdictions"] == []
    assert "no score" in r["method"] or "no score" in r["caveat"]


def test_per_jurisdiction_counts_and_verdicts():
    s = _session()
    now = datetime.now(UTC)
    s.add_all(
        [
            LawDocument(
                jurisdiction="uk", title="Act 1", url="https://law.example/uk1",
                baseline_text="x", last_status="baseline captured", last_checked_at=now,
            ),
            LawDocument(
                jurisdiction="uk", title="Act 2", url="https://law.example/uk2",
                last_status="fetch error: robots.txt disallows https://x",
                last_checked_at=now - timedelta(hours=5),
            ),
            LawDocument(
                jurisdiction="fr", title="Loi 1", url="https://law.example/fr1",
                baseline_text="y", last_status="changed (+10 bytes vs baseline)",
                last_checked_at=now,
            ),
            LawDocument(jurisdiction="fr", title="Loi 2", url="https://law.example/fr2"),  # never checked
        ]
    )
    s.commit()

    r = law_coverage_report(s)
    assert r["documents"] == 4 and r["baselined"] == 2
    by_jur = {j["jurisdiction"]: j for j in r["jurisdictions"]}
    assert set(by_jur) == {"fr", "uk"}

    uk = by_jur["uk"]
    assert uk["tracked"] == 2 and uk["baselined"] == 1 and uk["baseline_pct"] == 50.0
    assert uk["verdicts"] == {"baselined": 1, "robots_blocked": 1}
    assert uk["never_checked"] == 0
    assert uk["oldest_check_age_hours"] == 5.0 and uk["newest_check_age_hours"] == 0.0

    fr = by_jur["fr"]
    assert fr["tracked"] == 2 and fr["baselined"] == 1
    assert fr["verdicts"] == {"changed": 1}
    assert fr["never_checked"] == 1  # Loi 2 was never fetched


def test_completeness_principle_never_fabricates_a_coverage_fraction():
    """THE COMPLETENESS PRINCIPLE (brief §2): no enumeration adapter exists yet
    (S6, network-gated) -- every jurisdiction must say so honestly, never present
    the tracked count as if it measured the whole legal corpus."""
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr"))
    s.commit()
    r = law_coverage_report(s)
    assert r["jurisdictions"][0]["coverage"] == "no enumeration adapter — coverage unknown"


def test_never_checked_document_does_not_pollute_the_age_stats():
    s = _session()
    s.add(LawDocument(jurisdiction="us", title="Statute", url="https://law.example/us"))
    s.commit()
    r = law_coverage_report(s)
    us = r["jurisdictions"][0]
    assert us["never_checked"] == 1
    assert us["oldest_check_age_hours"] is None and us["newest_check_age_hours"] is None
