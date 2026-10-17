"""The first-install refresh in ``seed_sources`` (row J, R170): one SELECT after the commit that created rows, not one per row.

A commit expires every row the session holds; each is then re-read with its own SELECT the first time a later step
touches it (13,837 of them on a first install of the shipped catalogue). ``seed_sources`` therefore reads the table
once, right after each commit that follows a creation (the one that creates the rows and the one that records the merged
feed-less tags), and only in a call that created rows: a steady boot creates nothing, has nothing expired, and must
not pay for a table read it does not need. The refresh must also change no row: the same seed, with the refresh turned off,
produces the same rows.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine, event, false
from sqlalchemy.orm import Query, sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import seed_sources

_N = 60


def _entries(n: int = _N, start: int = 0) -> list[dict]:
    return [
        {"name": f"Outlet {i}", "domain": f"outlet{i}.example", "rss_url": f"https://outlet{i}.example/feed.xml",
         "tags": ["a", "b"], "country": "FR", "language": "fr", "reliability_score": 7}
        for i in range(start, start + n)
    ]


def _session():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True)()


def _spy_refresh(monkeypatch) -> list[int]:
    """Count the ``populate_existing`` reads ``seed_sources`` issues (it is the only caller in ``src/``)."""
    calls: list[int] = []
    real = Query.populate_existing

    def counted(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(Query, "populate_existing", counted)
    return calls


def _refresh_off(monkeypatch) -> None:
    """Make the refresh read nothing. (``.all()`` on a query that matches no row refreshes no expired row; a bare
    ``lambda self: self`` would not switch it off, since ``.all()`` alone also reloads every expired instance.)"""
    monkeypatch.setattr(Query, "populate_existing", lambda self: self.filter(false()))


def _digest(session) -> str:
    h = hashlib.sha256()
    for r in session.query(Source).order_by(Source.id):
        h.update(repr((r.id, r.domain, r.name, r.source_type, r.rss_url, r.feed_key, r.country, r.language, r.region,
                       r.status, r.catalog_baseline)).encode())
    return h.hexdigest()


def test_refresh_runs_once_for_a_call_that_created_rows_and_not_on_a_steady_boot(monkeypatch):
    calls = _spy_refresh(monkeypatch)
    _engine, session = _session()
    first = seed_sources(session, _entries())
    assert first["created"] == _N
    assert len(calls) == 1, "a call that committed new rows refreshes once, not once per row"
    seed_sources(session, _entries())          # the steady boot: every entry is already a row
    assert len(calls) == 1, "a boot that created nothing must not read the table again"
    seed_sources(session, _entries(1, start=_N))   # one new entry: the next call that creates a row refreshes again
    assert len(calls) == 2


def _row_reads(entries, monkeypatch=None, refresh=True) -> int:
    """SELECTs of one ``sources`` row by id issued by ``seed_sources`` (the per-row re-read an expired row costs)."""
    engine, session = _session()
    reads: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cur, statement, params, context, many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM sources" in statement and "sources.id = ?" in statement:
            reads.append(statement)

    if not refresh:
        _refresh_off(monkeypatch)
    seed_sources(session, entries)
    return len(reads)


def test_first_install_reads_the_created_rows_back_in_one_statement_not_one_each(monkeypatch):
    with_refresh = _row_reads(_entries())
    without = _row_reads(_entries(), monkeypatch, refresh=False)
    # Later steps still read some rows by id (a second commit expires them again), so the claim is the DIFFERENCE: the
    # refresh saves one read per created row. Half of _N is the bound, and it names what it protects.
    assert without - with_refresh >= _N // 2, f"{without} reads without the refresh, {with_refresh} with it, for {_N} created rows"


def test_the_refresh_changes_no_row(monkeypatch):
    _e1, with_refresh = _session()
    seed_sources(with_refresh, _entries())
    kept = _digest(with_refresh)

    _refresh_off(monkeypatch)
    _e2, without = _session()
    seed_sources(without, _entries())
    assert _digest(without) == kept
    assert without.query(Source).count() == _N


@pytest.mark.parametrize("second", ["same", "grown"])
def test_a_reseed_after_the_refresh_matches_a_cold_run(second):
    """The refreshed rows are the committed rows: a second pass over the same session sees no drift from the first."""
    _engine, session = _session()
    seed_sources(session, _entries())
    before = _digest(session)
    entries = _entries() if second == "same" else _entries() + _entries(5, start=_N)
    seed_sources(session, entries)
    _e, cold = _session()
    seed_sources(cold, entries)
    assert _digest(session) == _digest(cold)
    if second == "same":
        assert _digest(session) == before

