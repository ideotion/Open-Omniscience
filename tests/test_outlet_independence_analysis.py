"""The analysis window's coordination clusters, the server-location clusters and the card audit count OUTLETS (row J, R146).

Three places the J2 walk named and left until the keyword-rollup PR (the owner of ``queries.py``) merged: a cluster of
near-identical copies is "one voice" only if its copies share an OUTLET, and a shared server address is a shape to
investigate only if two OUTLETS sit on it (two feeds of one site share a host by construction). Each test builds the
sibling case and the positive control; the mutation check is reverting the count.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Source
from src.geo import ip_geo

_TEXT = (
    "The ministry announced a sweeping new policy on coastal infrastructure funding today, citing climate resilience "
    "and regional development goals as the central justification for the multi-year program of public works it "
    "intends to deliver across the northern provinces over the coming decade and beyond."
)


@pytest.fixture()
def s(tmp_path, monkeypatch):
    geo = tmp_path / "country.csv"
    geo.write_text("203.0.113.0,203.0.113.255,fr\n", encoding="utf-8")
    monkeypatch.setenv("OO_IP_GEO_DB", str(geo))
    ip_geo._country_ranges.cache_clear()
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()
    ip_geo._country_ranges.cache_clear()


def _feed(s, name, domain, feed, *, ip=None, text=_TEXT):
    src = Source(name=name, domain=domain, rss_url=feed)
    s.add(src)
    s.flush()
    s.add(Article(url=f"https://{domain}/{src.id}", canonical_url=f"https://{domain}/{src.id}", source_id=src.id,
                  title="Policy announced", content=text, hash=f"h{src.id}", language="en",
                  server_ip=ip, created_at=datetime.now(UTC)))
    s.flush()
    return src.id


def test_a_cluster_of_copies_from_two_feeds_of_one_outlet_is_one_voice(s):
    _feed(s, "BBC News", "bbc.com", "https://bbc.com/en")
    _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar")
    s.commit()
    ids = [a.id for a in s.query(Article).all()]
    (cluster,) = q.corpus_coordination(s, article_ids=ids)["clusters"]
    assert cluster["size"] == 2 and cluster["distinct_sources"] == 1 and cluster["single_source"] is True
    assert cluster["sources"] == ["BBC News"]  # the outlet's own label, the oldest feed's name


def test_a_cluster_of_copies_across_two_outlets_is_two_voices(s):
    _feed(s, "BBC News", "bbc.com", "https://bbc.com/en")
    _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar")
    _feed(s, "DW", "dw.com", "https://dw.com/rss")
    s.commit()
    ids = [a.id for a in s.query(Article).all()]
    (cluster,) = q.corpus_coordination(s, article_ids=ids)["clusters"]
    assert cluster["size"] == 3 and cluster["distinct_sources"] == 2 and cluster["single_source"] is False
    assert cluster["sources"] == ["BBC News", "DW"]


def test_two_feeds_of_one_outlet_on_one_host_are_not_a_shared_hosting_cluster(s):
    _feed(s, "BBC News", "bbc.com", "https://bbc.com/en", ip="203.0.113.10")
    _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar", ip="203.0.113.10")
    s.commit()
    out = q.server_locations(s)
    assert out["clusters"] == []
    assert [(c["country"], c["distinct_sources"]) for c in out["countries"]] == [("fr", 1)]


def test_two_outlets_on_one_host_are_a_shared_hosting_cluster_of_two(s):
    _feed(s, "BBC News", "bbc.com", "https://bbc.com/en", ip="203.0.113.10")
    _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar", ip="203.0.113.10")
    _feed(s, "DW", "dw.com", "https://dw.com/rss", ip="203.0.113.10")
    s.commit()
    out = q.server_locations(s)
    (cluster,) = out["clusters"]
    assert cluster["distinct_sources"] == 2 and sorted(cluster["sources"]) == ["BBC News", "DW"]
    assert [(c["country"], c["distinct_sources"]) for c in out["countries"]] == [("fr", 2)]


def test_the_card_audit_names_what_it_counts_and_the_leads_alias_is_gone():
    from src.briefing import leads
    from src.briefing.card import Card
    from src.briefing.card_audit import _independence

    ev = [{"title": "a", "source": "BBC News", "outlet": "bbc.com"}, {"title": "b", "source": "BBC Arabic", "outlet": "bbc.com"}]
    card = Card(type="rising", title="t", summary="s", bucket="rising", method="m", caveat="c", key="k", n=2, evidence=ev)
    out = _independence(None, card, [], max_articles=10)
    assert out["distinct_evidence_outlets"] == 1 and "distinct_evidence_sources" not in out
    assert not hasattr(leads, "_distinct_sources")
