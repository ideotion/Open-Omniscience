"""leads_quality diagnostic (Leads-calibration S6.1, 2026-07-18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins: the export carries every card the CURRENT run_all() pass produces, with real
per-card facts (n, independent-source count, the card's own disclosed signal, the
major-floor fact) and no fabricated/composite score anywhere.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.leads_quality import leads_quality_report
from src.database.models import Base


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _no_score_keys(obj):
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _no_score_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_score_keys(v)


def test_empty_corpus_is_honest():
    s = _sess()
    out = leads_quality_report(s)
    assert out["schema"] == "oo-leads-quality-1"
    assert out["count"] == 0 and out["cards"] == []
    assert out["method"] and out["caveat"]


def test_exports_real_registered_cards_with_disclosed_facts():
    from src.briefing import registry

    def _one(_session):
        from src.briefing.card import Card

        return [
            Card(
                type="audit_leadsq", title="t", summary="s", bucket="context",
                method="m", caveat="c", key="lq-1", n=42,
                signal={"metric": "value", "value": 42},
                evidence=[{"source": "A"}, {"source": "B"}],
            )
        ]

    registry.register("audit_leadsq_producer", _one)
    try:
        s = _sess()
        out = leads_quality_report(s)
        rows = [r for r in out["cards"] if r["type"] == "audit_leadsq"]
        assert len(rows) == 1
        row = rows[0]
        assert row["key"] == "lq-1" and row["bucket"] == "context" and row["n"] == 42
        assert row["distinct_sources"] == 2
        assert row["signal"] == {"metric": "value", "value": 42}
        assert "major" in row and "fact" in row["major"]
        _no_score_keys(out)
    finally:
        registry._REGISTRY = [
            (n, p) for (n, p) in registry._REGISTRY if n != "audit_leadsq_producer"
        ]


def test_endpoint_is_wired():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        body = c.get("/api/diagnostics/leads-quality").json()
    assert body["schema"] == "oo-leads-quality-1"
    assert "cards" in body and "method" in body and "caveat" in body
