"""Resilient-write retry: no fetched data is lost to a transient lock.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers src/database/write.py (run_write_with_retry / is_locked_error) and proves
the field-log-2026-06-13 data-loss path is closed: a commodity import whose
commit loses the single-writer race once still stores its points instead of
discarding them with "database is locked".
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, CommodityPrice
from src.database.write import is_locked_error, run_write_with_retry


def _locked() -> OperationalError:
    # Mirrors how SQLAlchemy wraps SQLite's SQLITE_BUSY: the orig's text carries
    # "database is locked", and str(exc) includes it.
    return OperationalError("INSERT ...", {}, Exception("database is locked"))


def _db_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------- is_locked_error -------------------------------- #


def test_is_locked_error_matches_only_lock_contention():
    assert is_locked_error(_locked())
    assert is_locked_error(OperationalError("x", {}, Exception("database is busy")))
    # Other OperationalErrors are NOT retryable -- they must surface at once.
    assert not is_locked_error(OperationalError("x", {}, Exception("no such table")))
    assert not is_locked_error(IntegrityError("x", {}, Exception("UNIQUE failed")))
    assert not is_locked_error(ValueError("nope"))


# ------------------------- run_write_with_retry ----------------------------- #


class _FakeSession:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_retry_returns_on_first_success_without_rollback():
    s = _FakeSession()
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        return "ok"

    assert run_write_with_retry(work, session=s, base_delay_s=0) == "ok"
    assert calls["n"] == 1
    assert s.rollbacks == 0


def test_retry_recovers_after_transient_locks():
    s = _FakeSession()
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        if calls["n"] <= 2:  # locked twice, then succeeds
            raise _locked()
        return 42

    assert run_write_with_retry(work, session=s, attempts=5, base_delay_s=0) == 42
    assert calls["n"] == 3
    assert s.rollbacks == 2  # one rollback per locked attempt


def test_retry_does_not_swallow_non_lock_errors():
    s = _FakeSession()
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        raise OperationalError("x", {}, Exception("no such table: foo"))

    with pytest.raises(OperationalError, match="no such table"):
        run_write_with_retry(work, session=s, attempts=5, base_delay_s=0)
    assert calls["n"] == 1  # surfaced immediately, never retried
    assert s.rollbacks == 0


def test_retry_gives_up_and_reraises_after_exhausting_attempts():
    s = _FakeSession()
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        raise _locked()

    with pytest.raises(OperationalError, match="database is locked"):
        run_write_with_retry(work, session=s, attempts=3, base_delay_s=0)
    assert calls["n"] == 3
    assert s.rollbacks == 3


# --------------------- import_points: data is NOT lost ---------------------- #


def test_import_points_survives_a_transient_lock():
    """The field-log data-loss case: the first commit loses the writer race,
    the second succeeds -- the points must end up stored, not discarded."""
    from datetime import date

    from src.markets import csv_feeds

    session = _db_session()
    real_commit = session.commit
    state = {"calls": 0}

    def flaky_commit():
        state["calls"] += 1
        if state["calls"] == 1:
            raise _locked()
        return real_commit()

    session.commit = flaky_commit  # type: ignore[method-assign]

    points = [(date(2026, 6, 1), 100.0), (date(2026, 6, 2), 101.5)]
    res = csv_feeds.import_points(session, symbol="COPPER", points=points, market="LME")

    assert state["calls"] == 2  # failed once, retried, succeeded
    assert res["imported"] == 2
    # The decisive assertion: the data actually persisted (was NOT discarded).
    stored = session.query(CommodityPrice).filter_by(symbol="COPPER").count()
    assert stored == 2
