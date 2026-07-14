"""
Q4a — wire the dormant external_sources as the discovery funnel's RESOLUTION table.

A cited/discovered domain now resolves to an external_sources row carrying WHICH channel first found
it (discovered_via). Honesty: descriptive provenance only, first-writer-wins, and the legacy
credibility_score column is NEVER written (it stays NULL).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, ExternalSource, SourceCandidate
from src.discovery.channels import _add_candidate, resolve_external_source


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_resolve_inserts_a_registry_row_with_provenance_and_no_score():
    s = _session()
    resolve_external_source(s, domain="Reuters.com", name=None, discovered_via="wikipedia")
    s.flush()
    row = s.query(ExternalSource).filter_by(domain="reuters.com").one()
    assert row.discovered_via == "wikipedia"
    assert row.source_type == "unknown"
    assert row.name == "reuters.com"  # falls back to the domain when no name is known
    # the legacy composite-score columns are NEVER written by discovery (honesty)
    assert row.credibility_score is None and row.political_bias is None


def test_resolve_is_idempotent_and_first_writer_wins_on_provenance():
    s = _session()
    resolve_external_source(s, domain="x.example", name=None, discovered_via="citation")
    s.flush()
    # a later channel re-resolving the same domain does NOT create a duplicate and does NOT
    # overwrite the first provenance (first-writer-wins), but backfills a missing name.
    resolve_external_source(s, domain="x.example", name="X News", discovered_via="wikipedia")
    s.flush()
    rows = s.query(ExternalSource).filter_by(domain="x.example").all()
    assert len(rows) == 1
    assert rows[0].discovered_via == "citation"  # first wins
    assert rows[0].name == "X News"  # missing name backfilled


def test_resolve_backfills_a_null_provenance_on_a_preexisting_row():
    s = _session()
    s.add(ExternalSource(domain="legacy.example", name="Legacy", source_type="news"))  # no discovered_via
    s.flush()
    resolve_external_source(s, domain="legacy.example", name=None, discovered_via="citation")
    s.flush()
    row = s.query(ExternalSource).filter_by(domain="legacy.example").one()
    assert row.discovered_via == "citation"  # a NULL provenance is filled
    assert row.name == "Legacy"  # existing name untouched


def test_adding_a_candidate_also_resolves_the_external_source():
    s = _session()
    _add_candidate(s, domain="newfound.example", name=None, channel="citation",
                   evidence={"reason": "test"})
    s.flush()
    # the funnel candidate AND the registry row are both created, with matching provenance
    assert s.query(SourceCandidate).filter_by(domain="newfound.example").one().channel == "citation"
    reg = s.query(ExternalSource).filter_by(domain="newfound.example").one()
    assert reg.discovered_via == "citation" and reg.credibility_score is None
