"""S12 — the Leads 2.0 VIEW assembly (evidence chips · disclosed order · major floor · clusters).

Pins the §2 surfacing over briefing card DICTS: ``sort=default`` preserves Home's order EXACTLY
(the conservative default), ``sort=prominence`` reorders by the disclosed order_key, the chips are
REAL fields (n · distinct sources · freshest age), the major fact is a threshold FACT, clustering
stacks overlapping leads, and no key is a composite score. Plus the endpoint wiring.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.briefing.card import Card
from src.briefing.leads import assemble_leads_view

_NOW = datetime(2026, 7, 13)


def _card(key, *, n, sources, ages=(), article_ids=()) -> dict:
    ev = [{"source": f"src{i}", "published_at": None} for i in range(sources)]
    for i, a in enumerate(ages):
        if i < len(ev):
            ev[i]["published_at"] = (_NOW - timedelta(days=a)).isoformat()
    return Card(
        type="rising", title=f"T{key}", summary="s", bucket="rising", method="m", caveat="c",
        key=key, n=n, evidence=ev, article_ids=list(article_ids),
    ).to_dict()


def test_default_sort_preserves_input_order_exactly():
    cards = [_card("a", n=500, sources=2), _card("b", n=10, sources=6), _card("c", n=5, sources=1)]
    view = assemble_leads_view(cards, now=_NOW, sort="default")
    assert [ld["key"] for ld in view["leads"]] == ["a", "b", "c"]  # byte-identical to Home
    assert view["sort"] == "default"


def test_prominence_sort_reorders_by_the_disclosed_key():
    cards = [_card("a", n=500, sources=2), _card("b", n=10, sources=6)]
    view = assemble_leads_view(cards, now=_NOW, sort="prominence")
    assert [ld["key"] for ld in view["leads"]] == ["b", "a"]  # more independent sources first
    assert "disclosed order" in view["leads"][0]["order_explain"]


def test_evidence_chips_are_real_fields_not_a_score():
    view = assemble_leads_view([_card("a", n=42, sources=3, ages=(2,))], now=_NOW)
    chips = view["leads"][0]["evidence_chips"]
    assert chips["n"] == 42
    assert chips["distinct_sources"] == 3
    assert chips["newest_age_days"] == 2.0


def test_undated_evidence_yields_none_age_never_fabricated():
    view = assemble_leads_view([_card("a", n=5, sources=2)], now=_NOW)  # no ages
    assert view["leads"][0]["evidence_chips"]["newest_age_days"] is None


def test_major_floor_is_a_threshold_fact():
    cards = [_card("m", n=120, sources=6), _card("s", n=120, sources=2)]
    view = assemble_leads_view(cards, now=_NOW, floors={"min_n": 50, "min_sources": 5})
    by = {ld["key"]: ld for ld in view["leads"]}
    assert by["m"]["major"]["major"] is True
    assert by["s"]["major"]["major"] is False and "<" in by["s"]["major"]["fact"]


def test_cluster_stacks_overlapping_leads():
    cards = [
        _card("c1", n=5, sources=2, article_ids=[1, 2, 3, 4]),
        _card("c2", n=5, sources=2, article_ids=[2, 3, 4, 5]),  # Jaccard 3/5 >= 0.5
        _card("c3", n=5, sources=2, article_ids=[90, 91]),  # disjoint
    ]
    view = assemble_leads_view(cards, now=_NOW, cluster=True)
    assert view["clusters"]["n_clusters"] == 1


def test_no_score_key_anywhere():
    view = assemble_leads_view(
        [_card("a", n=42, sources=3, ages=(1,))], now=_NOW, sort="prominence", cluster=True
    )
    banned = ("score", "ranking", "rating", "grade")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in banned), k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(view)


def test_bad_sort_raises():
    with pytest.raises(ValueError, match="sort"):
        assemble_leads_view([], now=_NOW, sort="turbo")


def test_endpoint_serves_the_view_over_the_cached_briefing(monkeypatch):
    """The /api/insights/leads-view endpoint reads the cached briefing and assembles the view;
    sort=default preserves Home's order, a bad sort is 400."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import src.briefing.service as svc
    from src.api.main import app
    from src.database.models import Base
    from src.database.session import get_db

    cards = [_card("a", n=500, sources=2), _card("b", n=10, sources=6)]
    monkeypatch.setattr(
        svc, "get_briefing", lambda *a, **k: {"generated_at": "2026-07-13T00:00:00", "cards": cards}
    )

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.get("/api/insights/leads-view")
            assert r.status_code == 200, r.text
            body = r.json()
            assert [ld["key"] for ld in body["leads"]] == ["a", "b"]  # default = Home order
            assert body["generated_at"] == "2026-07-13T00:00:00"
            rp = c.get("/api/insights/leads-view", params={"sort": "prominence"})
            assert [ld["key"] for ld in rp.json()["leads"]] == ["b", "a"]
            assert c.get("/api/insights/leads-view", params={"sort": "turbo"}).status_code == 400
    finally:
        app.dependency_overrides.clear()
