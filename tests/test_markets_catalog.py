"""
Tests for the packaged worldwide markets source catalog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Verifies the shipped catalog parses, is well-formed, covers the three market
source types, and is actually folded into the default seeding so the app is
ready to ingest market coverage out of the box.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import (
    MARKETS_SOURCES_PATH,
    load_sources_from_yaml,
    seed_default_sources,
)

_VALID_TYPES = {"stock_exchange", "commodity", "financial"}


def test_markets_catalog_parses_and_is_wellformed():
    rows = load_sources_from_yaml(MARKETS_SOURCES_PATH)
    assert len(rows) >= 80
    # Every entry has a name + domain, and a recognised market source_type.
    assert all(r.get("name") and r.get("domain") for r in rows)
    assert all(r.get("source_type") in _VALID_TYPES for r in rows)
    # Domains are unique within the file.
    domains = [r["domain"] for r in rows]
    assert len(domains) == len(set(domains))
    # All three categories are represented.
    types = {r["source_type"] for r in rows}
    assert types >= _VALID_TYPES


def _session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_default_seed_includes_market_sources():
    s = _session()
    seed_default_sources(s)
    # Representative exchanges/commodity sources are present after default seeding.
    for domain in ("nyse.com", "lme.com", "metal.com", "gfex.com.cn", "jpx.co.jp"):
        assert s.query(Source).filter_by(domain=domain).first() is not None, domain
    # A healthy number of stock exchanges made it in.
    n_exchanges = s.query(Source).filter_by(source_type="stock_exchange").count()
    assert n_exchanges >= 40
    s.close()


def test_market_sources_carry_markets_tag():
    s = _session()
    seed_default_sources(s)
    lme = s.query(Source).filter_by(domain="lme.com").one()
    assert "markets" in (lme.tags or "")
    assert "commodity" in lme.source_type
    s.close()
