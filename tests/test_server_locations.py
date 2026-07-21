"""Server-location aggregation for the ooMap server-IP layer (Slice 6c backend).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Aggregates captured server IPs (6a) through the offline geolocator (6b): per-country
counts, IP/host CLUSTERING (a shape to investigate, never a verdict), and honest
unavailable buckets (Tor/proxy, not-captured, unknown-IP). Counts only, no score.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Source
from src.geo import ip_geo


@pytest.fixture()
def db(tmp_path, monkeypatch):
    # A labeled documentation-IP fixture (not real geolocation data).
    geo = tmp_path / "country.csv"
    geo.write_text("203.0.113.0,203.0.113.255,fr\n", encoding="utf-8")
    monkeypatch.setenv("OO_IP_GEO_DB", str(geo))
    ip_geo._country_ranges.cache_clear()

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all([Source(id=1, name="Alpha", domain="a.test"), Source(id=2, name="Beta", domain="b.test")])
    s.commit()
    yield s
    ip_geo._country_ranges.cache_clear()


def _add(db, i, source_id, **kw):
    db.add(Article(
        url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=source_id,
        title="T", content="body", hash=f"h{i}", language="en", created_at=datetime.now(UTC), **kw,
    ))
    db.commit()


def test_server_locations_aggregates_clusters_and_buckets(db):
    # fr from two DISTINCT sources on the SAME ip -> a cluster.
    _add(db, 1, 1, server_ip="203.0.113.10")
    _add(db, 2, 1, server_ip="203.0.113.10")
    _add(db, 3, 2, server_ip="203.0.113.10")  # different source, same IP
    # honest unavailable buckets
    _add(db, 4, 1, server_ip=None, server_ip_reason="unavailable (proxy/Tor)")
    _add(db, 5, 1, server_ip=None, server_ip_reason=None)
    _add(db, 6, 1, server_ip="8.8.8.8")  # not in the fixture DB

    out = q.server_locations(db)

    fr = next(c for c in out["countries"] if c["country"] == "fr")
    assert fr["articles"] == 3
    assert fr["distinct_ips"] == 1
    assert fr["distinct_sources"] == 2

    assert len(out["clusters"]) == 1
    cl = out["clusters"][0]
    assert cl["ip"] == "203.0.113.10"
    assert cl["distinct_sources"] == 2
    assert set(cl["sources"]) == {"Alpha", "Beta"}

    assert out["unavailable"] == {"tor_or_proxy": 1, "not_captured": 1, "unknown_ip": 1}
    assert out["db_vintage"] == ip_geo.IP_GEO_AS_OF
    assert "DB-IP" in out["attribution"]
    assert "not proof of the publisher" in out["caveat"].lower()


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_no_score_shaped_field_names(db):
    # The ban is on FIELD NAMES (the prose "Counts only, no score." is allowed).
    _add(db, 1, 1, server_ip="203.0.113.10")
    out = q.server_locations(db)
    for key in _all_keys(out):
        name = key.lower()
        assert name not in {"score", "rating", "rank", "trust"}
        assert not any(
            frag in name for frag in ("trust_score", "credibility", "verdict", "_score")
        ), f"score-shaped field name: {key}"


def test_empty_corpus_is_honest(db):
    out = q.server_locations(db)
    assert out["countries"] == []
    assert out["clusters"] == []
    assert out["unavailable"] == {"tor_or_proxy": 0, "not_captured": 0, "unknown_ip": 0}


# --- source_observed_ips (SOURCE IPs ruling, ask 2: per-source aggregated view) --- #


def test_source_observed_ips_aggregates_distinct_ips_first_last_seen_and_country(db):
    _add(db, 1, 1, server_ip="203.0.113.10", ip_observed_at=datetime(2026, 1, 1, tzinfo=UTC))
    _add(db, 2, 1, server_ip="203.0.113.10", ip_observed_at=datetime(2026, 3, 1, tzinfo=UTC))
    _add(db, 3, 1, server_ip="8.8.8.8", ip_observed_at=datetime(2026, 2, 1, tzinfo=UTC))
    _add(db, 4, 1, server_ip=None, server_ip_reason="unavailable (proxy/Tor)")
    _add(db, 5, 1, server_ip=None, server_ip_reason=None)
    _add(db, 6, 2, server_ip="203.0.113.10")  # a DIFFERENT source -- must not leak in

    out = q.source_observed_ips(db, source_id=1)

    assert out["source_id"] == 1
    assert out["distinct_ips"] == 2
    assert out["total_articles"] == 5  # source 1's rows only, including unavailable ones
    by_ip = {row["ip"]: row for row in out["ips"]}
    assert by_ip["203.0.113.10"]["articles"] == 2
    assert by_ip["203.0.113.10"]["country"] == "fr"
    # SQLite round-trips a stored datetime without its tz suffix (naive) -- match that.
    assert by_ip["203.0.113.10"]["first_seen"].startswith("2026-01-01T00:00:00")
    assert by_ip["203.0.113.10"]["last_seen"].startswith("2026-03-01T00:00:00")
    assert by_ip["8.8.8.8"]["articles"] == 1
    assert out["unavailable"] == {"tor_or_proxy": 1, "not_captured": 1}
    assert out["db_vintage"] == ip_geo.IP_GEO_AS_OF
    assert "not proof of the publisher" in out["caveat"].lower()


def test_source_observed_ips_empty_source_is_honest(db):
    out = q.source_observed_ips(db, source_id=1)
    assert out["ips"] == []
    assert out["distinct_ips"] == 0
    assert out["total_articles"] == 0
    assert out["unavailable"] == {"tor_or_proxy": 0, "not_captured": 0}
