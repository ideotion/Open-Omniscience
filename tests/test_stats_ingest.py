"""
Ingest the official-statistics agency directory as DISABLED Source rows (Group N,
official-statistics ingestion — first "ingest as sources" slice).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Asserts the honesty contract: sources land DISABLED (registered, not scraped),
source_type="statistics", carry the official-statistics + region tags (NO
"controversial" verdict tag — ruling #50),
NEVER a fabricated reliability_score; national producers carry a lowercase ISO-2
country while IGOs carry none; and the whole thing is idempotent / never clobbers
an existing source. No network anywhere (home_url is reduced to a domain locally).

The suite shares ONE temp DB, so assertions scope to the rows this ingest creates
(source_type="statistics" / the agency domains) rather than absolute counts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.catalog.normalize import registrable_domain
from src.stats.agencies import get_agency, list_agencies


@pytest.fixture()
def client():
    # TestClient's lifespan runs init_db() so the tables exist.
    from src.api.main import app

    with TestClient(app) as c:
        yield c


# Domains the curated directory yields for two reference agencies. registrable_domain
# does NOT strip subdomains, so the World Bank domain keeps its "data." label.
_BLS_DOMAIN = registrable_domain(get_agency("us-bls").home_url)  # national (US)
_WB_DOMAIN = registrable_domain(get_agency("worldbank").home_url)  # IGO (no country)


def _stat_sources(session):
    from src.database.models import Source

    return session.query(Source).filter(Source.source_type == "statistics").all()


def test_ingest_creates_disabled_sources(client):
    from src.database.session import session_scope
    from src.stats.ingest import ingest_agencies_as_sources

    # On a fresh DB this creates the whole directory; under the shared suite DB a
    # prior test may have created them already (idempotent). Either way the rows
    # must satisfy the contract below — so assert created+skipped covers the full
    # directory rather than created>0 (which is order-dependent).
    with session_scope() as s:
        tally = ingest_agencies_as_sources(s)

    assert tally["total_agencies"] == len(list_agencies())
    assert tally["skipped_no_domain"] == 0  # every curated agency has a usable URL
    assert tally["created"] + tally["skipped_existing"] == tally["total_agencies"]
    # No composite/credibility score field on the returned tally.
    assert not any("score" in k.lower() for k in tally)

    with session_scope() as s:
        rows = _stat_sources(s)
        by_domain = {r.domain: r for r in rows}

        for r in rows:
            assert r.enabled is False  # registered, NOT scraped
            assert r.source_type == "statistics"
            assert r.reliability_score is None  # never a fabricated score
            tags = (r.tags or "").split(",")
            assert "controversial" not in tags  # no verdict tag (ruling #50)
            assert "official-statistics" in tags

        # A national agency carries a lowercase ISO-2 country.
        bls = by_domain[_BLS_DOMAIN]
        assert bls.country == "us"
        assert bls.country == bls.country.lower()

        # An IGO carries NO country.
        wb = by_domain[_WB_DOMAIN]
        assert wb.country is None


def test_ingest_is_idempotent(client):
    # The suite shares one DB and another test may have already ingested, so this
    # asserts idempotence WITHOUT assuming a clean start: after one ingest, a
    # SECOND ingest must create nothing and report every agency as already-present,
    # with the statistics-source count unchanged (no duplicates).
    from src.database.session import session_scope
    from src.stats.ingest import ingest_agencies_as_sources

    with session_scope() as s:
        ingest_agencies_as_sources(s)  # ensure the directory is fully present
        count_after_first = len(_stat_sources(s))

    with session_scope() as s:
        second = ingest_agencies_as_sources(s)
        count_after_second = len(_stat_sources(s))

    assert second["created"] == 0  # nothing new on a repeat call
    # Every agency with a domain is now an existing row (none created, none
    # missing a domain): created + skipped_existing + skipped_no_domain == total.
    assert second["skipped_existing"] == second["total_agencies"] - second["skipped_no_domain"]
    assert count_after_second == count_after_first  # no duplicates


def test_ingest_skips_an_existing_source_without_clobbering(client):
    from src.database.models import Source
    from src.database.session import session_scope
    from src.stats.ingest import ingest_agencies_as_sources

    igbe_domain = registrable_domain(get_agency("br-ibge").home_url)

    # Pre-insert a DIFFERENT source on one agency's domain (operator curation):
    # enabled, with its own name/type. Ingest must leave it exactly as-is.
    # (The suite shares one DB; remove any prior row on this domain first so the
    # pre-insert is deterministic regardless of test ordering.)
    with session_scope() as s:
        for existing in s.query(Source).filter(Source.domain == igbe_domain).all():
            s.delete(existing)
    with session_scope() as s:
        s.add(
            Source(
                name="Pre-existing IBGE entry",
                domain=igbe_domain,
                enabled=True,
                source_type="news",
            )
        )

    with session_scope() as s:
        tally = ingest_agencies_as_sources(s)

    assert tally["skipped_existing"] >= 1

    with session_scope() as s:
        rows = s.query(Source).filter(Source.domain == igbe_domain).all()
        assert len(rows) == 1  # not duplicated
        kept = rows[0]
        # Untouched: our pre-existing curation survives verbatim.
        assert kept.name == "Pre-existing IBGE entry"
        assert kept.enabled is True
        assert kept.source_type == "news"


def test_ingest_endpoint_returns_tally(client):
    r = client.post("/api/stats/sources/ingest")
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("created", "skipped_existing", "skipped_no_domain", "total_agencies", "method", "caveat"):
        assert key in data
    assert data["total_agencies"] == len(list_agencies())
    assert "stanced" in data["caveat"].lower()
    # No score field anywhere in the response.
    assert not any("score" in k.lower() for k in data)
