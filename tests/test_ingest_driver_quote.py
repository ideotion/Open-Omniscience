"""A fetch-layer failure that quotes a database driver's text never reaches the outcome's detail with that text."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest import FetchFailed
from src.ingest.pipeline import IngestResult, ingest_url
from src.monitoring.secret_scrub import record_text

FRAGMENT = "horse-battery"


def _driver_quoting_fetch_failed() -> FetchFailed:
    try:
        try:
            raise sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
        except sqlite3.OperationalError as driver:
            raise FetchFailed(f"request error for http://x/: {driver}") from driver
    except FetchFailed as exc:
        return exc


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def test_the_helper_at_every_converted_site_withholds_a_quoted_driver():
    assert FRAGMENT not in record_text(_driver_quoting_fetch_failed(), typed=False)


def test_the_outcome_detail_of_a_failed_fetch_carries_no_driver_text(session):
    source = Source(name="Test Source", domain="test.example")
    session.add(source)
    session.commit()
    failure = _driver_quoting_fetch_failed()

    class _Fetcher:
        def fetch(self, *args, **kwargs):
            raise failure

    outcome = ingest_url(session, source, "http://test.example/a", fetcher=_Fetcher())
    assert outcome.result == IngestResult.FETCH_FAILED
    assert FRAGMENT not in (outcome.detail or ""), outcome.detail
