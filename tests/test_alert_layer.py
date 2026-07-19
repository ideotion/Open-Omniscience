"""Tests for the severity-tiered LOCAL alert layer (Cards batch E).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers the non-negotiables:
  * the hazard snapshot is a LOCAL cache with honest staleness — never the network;
  * the tier is a TRANSPARENT rule over real counts: 'urgent' ONLY ever comes from a
    provider-declared red hazard alert (a USGS magnitude band is NOT promoted to urgent);
  * fired watches → 'watch'; recent convergences → 'info';
  * the producer emits schema-valid, score-free Cards with a trigger, carrying method +
    caveat + the exact article_ids of its corpus evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.alerts import _hazard_tier, compute_alerts
from src.database.models import (
    Article,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
    Watch,
    WatchMatch,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _snapshot(records: list[dict], *, stale=False) -> dict:
    return {
        "records": records,
        "saved_at": datetime.now(UTC).isoformat(),
        "age_hours": 1.0,
        "stale": stale,
        "available": True,
    }


def _seed_convergence(s):
    """3 articles, 2 distinct sources, one place + one recent window → one convergence."""
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    on = date.today() - timedelta(days=5)
    for aid, src in ((101, 1), (102, 2), (103, 1)):
        s.add(Article(
            id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
            source_id=src, title=f"Story {aid}", content="event body text", hash=f"h{aid}",
            language="en", published_at=datetime.now(UTC), created_at=datetime.now(UTC),
        ))
        s.add(ArticleMentionedPlace(
            article_id=aid, name="Gaza", country="ps", kind="city",
            mentions=1, lat=31.5, lon=34.45, extractor="lexical-v1",
        ))
        s.add(ArticleMentionedDate(
            article_id=aid, mentioned_on=on, precision="day", extractor="dateextract",
            status="candidate",
        ))
    s.commit()
    return [101, 102, 103]


def _seed_fired_watch(s, article_ids):
    now = _now_naive()
    w = Watch(name="Flood watch", query="flood", threshold=3, window_days=7,
              enabled=True, last_matched_at=now)
    s.add(w)
    s.flush()
    s.add(WatchMatch(watch_id=w.id, matched_at=now, n_articles=len(article_ids),
                     new_articles=2, article_ids=json.dumps(article_ids)))
    s.commit()
    return w.id


# --------------------------------------------------------------------------- #
#  Hazard snapshot store (local, never the network)
# --------------------------------------------------------------------------- #
def test_hazard_snapshot_save_load_roundtrip(data_dir):
    from src.hazards.store import load_snapshot, save_snapshot

    save_snapshot([
        {"source": "gdacs", "type": "flood", "severity": "urgent", "title": "Big flood",
         "url": "https://gdacs.org/1", "time": "2026-07-01T00:00:00Z", "lat": 1.0, "lon": 2.0},
    ])
    snap = load_snapshot()
    assert snap["available"] is True
    assert len(snap["records"]) == 1
    assert snap["records"][0]["severity"] == "urgent"
    assert snap["stale"] is False  # just saved


def test_hazard_snapshot_absent_is_honest_empty(data_dir):
    from src.hazards.store import load_snapshot

    snap = load_snapshot()
    assert snap["available"] is False
    assert snap["records"] == []
    assert snap["stale"] is True  # nothing known → not "current"


def test_hazard_snapshot_reports_staleness(data_dir):
    from src.hazards.store import load_snapshot, save_snapshot

    old = datetime.now(UTC) - timedelta(hours=100)
    save_snapshot([{"source": "gdacs", "severity": "info", "url": "u"}], now=old)
    snap = load_snapshot(max_age_hours=48)
    assert snap["available"] is True and snap["stale"] is True
    assert snap["age_hours"] is not None and snap["age_hours"] > 48


# --------------------------------------------------------------------------- #
#  Tier mapping — 'urgent' is ONLY ever a provider red alert
# --------------------------------------------------------------------------- #
def test_hazard_tier_uses_provider_scale_never_fabricates_urgent():
    assert _hazard_tier("urgent") == "urgent"   # GDACS red
    assert _hazard_tier("watch") == "watch"     # GDACS orange
    assert _hazard_tier("info") == "info"       # GDACS green
    # A USGS magnitude band has NO provider-declared urgency → info, never promoted.
    assert _hazard_tier("major") == "info"
    assert _hazard_tier("strong") == "info"
    assert _hazard_tier(None) == "info"
    assert _hazard_tier("RED") == "info"  # not the provider vocabulary → info, not urgent


# --------------------------------------------------------------------------- #
#  compute_alerts — the transparent aggregation
# --------------------------------------------------------------------------- #
def test_compute_alerts_tiers_hazards_by_provider_severity(session):
    snap = _snapshot([
        {"source": "gdacs", "severity": "urgent", "type": "cyclone", "title": "Red cyclone", "url": "u1"},
        {"source": "gdacs", "severity": "watch", "type": "flood", "title": "Orange flood", "url": "u2"},
        {"source": "gdacs", "severity": "info", "type": "quake", "title": "Green quake", "url": "u3"},
        {"source": "usgs", "severity": "major", "type": "earthquake", "title": "M7", "url": "u4"},
    ])
    out = compute_alerts(session, snapshot=snap)
    tiers = out["tiers"]
    assert tiers["urgent"]["count"] == 1
    assert tiers["watch"]["count"] == 1
    # green GDACS + the USGS magnitude band both land in info (never urgent).
    assert tiers["info"]["count"] == 2
    assert out["highest_tier"] == "urgent"
    assert "never invents urgency" in out["caveat"]
    assert "no score" in out["caveat"].lower() or "score" not in json.dumps(tiers).lower()


def test_compute_alerts_folds_watches_and_convergences(session):
    ids = _seed_convergence(session)
    _seed_fired_watch(session, [901, 902])
    out = compute_alerts(session, snapshot=_snapshot([]))
    # A fired watch → watch tier, carrying its exact article ids.
    assert out["tiers"]["watch"]["count"] == 1
    assert set(out["tiers"]["watch"]["article_ids"]) == {901, 902}
    # A recent convergence → info tier, carrying the exact converging articles.
    assert out["tiers"]["info"]["count"] == 1
    assert set(out["tiers"]["info"]["article_ids"]) == set(ids)
    assert out["highest_tier"] == "watch"  # no urgent present → highest is watch


def test_compute_alerts_empty_is_honest(session):
    out = compute_alerts(session, snapshot=_snapshot([]))
    assert out["total"] == 0
    assert out["highest_tier"] is None
    assert out["method"] and out["caveat"]


# --------------------------------------------------------------------------- #
#  The producer emits schema-valid, score-free cards with a trigger
# --------------------------------------------------------------------------- #
def test_severity_alerts_producer_emits_valid_cards(session, data_dir):
    from src.briefing.card import Card, assert_no_score_fields
    from src.briefing.producers import severity_alerts
    from src.hazards.store import save_snapshot

    save_snapshot([
        {"source": "gdacs", "severity": "urgent", "type": "cyclone", "title": "Red cyclone", "url": "https://gdacs.org/1"},
    ])
    ids = _seed_convergence(session)
    _seed_fired_watch(session, [901, 902])

    cards = severity_alerts(session)
    assert cards, "expected at least one alert card"
    assert_no_score_fields(Card)
    by_tier = {c.signal["tier"]: c for c in cards}
    # S4.5 (row 17, 2026-07-18 field export): 'info' here is PURE convergences (no green
    # hazard, no fired watch of its own) -- the same space_time_convergence cards already
    # shown elsewhere in the feed, so this meta-card is suppressed as a pure re-count.
    assert set(by_tier) == {"urgent", "watch"}
    for c in cards:
        assert isinstance(c, Card)
        assert c.type == "severity_alert" and c.bucket == "watch"
        assert c.method and c.caveat
        assert "score" not in c.signal  # the metric is a real count
        assert c.trigger and c.trigger["plain"].strip()
        assert c.trigger["math"] and all(r.get("label") and "value" in r for r in c.trigger["math"])
    # 'urgent' comes ONLY from a provider red alert → no corpus articles, but real evidence.
    assert by_tier["urgent"].article_ids == []
    assert any(ev.get("url") for ev in by_tier["urgent"].evidence)
    # 'watch' carries the exact corpus article ids of its evidence.
    assert set(by_tier["watch"].article_ids) == {901, 902}
    _ = ids  # the convergence ids exist but 'info' is suppressed here — see the note above


def test_info_tier_still_fires_on_a_real_green_hazard(session, data_dir):
    """The suppression is PRECISE (row 17): a genuine green/relayed hazard is not a
    re-count of anything else in the feed, so the info tier must still fire."""
    from src.briefing.producers import severity_alerts
    from src.hazards.store import save_snapshot

    save_snapshot([
        {"source": "gdacs", "severity": "info", "type": "wildfire", "title": "Green wildfire watch", "url": "https://gdacs.org/2"},
    ])
    cards = severity_alerts(session)
    by_tier = {c.signal["tier"]: c for c in cards}
    assert "info" in by_tier
    assert by_tier["info"].signal["hazards"] == 1
    assert by_tier["info"].signal["convergences"] == 0


def test_info_tier_fires_with_both_a_hazard_and_convergences(session, data_dir):
    """Info is suppressed only when convergences are the WHOLE content -- with a real
    hazard alongside them, the tier is not a pure re-count and must still fire."""
    from src.briefing.producers import severity_alerts
    from src.hazards.store import save_snapshot

    save_snapshot([
        {"source": "gdacs", "severity": "info", "type": "wildfire", "title": "Green wildfire watch", "url": "https://gdacs.org/2"},
    ])
    ids = _seed_convergence(session)
    cards = severity_alerts(session)
    by_tier = {c.signal["tier"]: c for c in cards}
    assert "info" in by_tier
    assert by_tier["info"].signal["hazards"] == 1
    assert by_tier["info"].signal["convergences"] >= 1
    assert set(ids) <= set(by_tier["info"].article_ids)


def test_severity_alerts_producer_silent_when_nothing(session, data_dir):
    from src.briefing.producers import severity_alerts

    assert severity_alerts(session) == []  # no snapshot, no watches, no convergences


# --------------------------------------------------------------------------- #
#  The exploration endpoint
# --------------------------------------------------------------------------- #
def test_alerts_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.api.main import app

    with TestClient(app) as c:
        out = c.get("/api/signals/alerts").json()
    assert "tiers" in out and "highest_tier" in out
    assert "never invents urgency" in out["caveat"]
    assert set(out["tiers"]) == {"info", "watch", "urgent"}
