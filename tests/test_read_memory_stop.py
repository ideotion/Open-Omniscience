"""A deadlined read stops before the machine runs out of memory, not only after 60 seconds.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD CASE (crash bundle, 2026-09-26, a 3.9 GB machine): in its last half minute
the app gained 13.5 million Python objects and available memory fell from 1,065 MB to
135 MB in 25 seconds; the session ended there. Every heavy read already ran under
``statement_deadline``, whose only stop was a 60-second clock, so none of them could
have stopped in time.

Every test here drives the REAL ``statement_deadline`` over a REAL pooled engine, with
only the memory READING scripted. The reading is the one thing a test cannot make real
without starving the machine it runs on.
"""

from __future__ import annotations

import logging

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from src.database import maintenance
from src.database.maintenance import MemoryShort, StatementTimeout, statement_deadline
from src.scheduler import memguard

# ~400k iterations: comfortably past the 20,000-opcode granularity at which the
# progress handler fires (the same query tests/test_statement_deadline_pool.py uses).
_LONG = sa.text(
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<400000)"
    " SELECT count(*) FROM c"
)
# Long enough that a 50 ms deadline elapses inside it on any machine.
_LONGER = sa.text(
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<20000000)"
    " SELECT count(*) FROM c"
)


@pytest.fixture()
def session(tmp_path):
    from src.database.session import _disarm_progress_handler

    eng = sa.create_engine(
        f"sqlite:///{tmp_path / 'd.db'}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
    )
    event.listen(eng, "reset", _disarm_progress_handler)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        eng.dispose()


@pytest.fixture()
def memory(monkeypatch):
    """Script the available-memory READINGS; everything else stays real.

    Returns the list of readings handed out, so a test can prove the handler really
    read memory mid-statement rather than passing for a reason it never exercised.
    """
    monkeypatch.delenv("OO_READ_MEMORY_STOP", raising=False)
    monkeypatch.setattr(memguard.memory_guard, "avail_floor_mb", 256.0)
    # Re-read on every tick, and start from no cached reading.
    monkeypatch.setattr(maintenance, "_AVAIL_READ_EVERY_S", 0.0)
    monkeypatch.setattr(maintenance, "_AVAIL_CACHE", (float("-inf"), None))
    handed: list[float | None] = []
    script: dict = {"values": [], "then": None}

    def _reading() -> float | None:
        value = script["values"].pop(0) if script["values"] else script["then"]
        handed.append(value)
        return value

    monkeypatch.setattr(maintenance, "_available_mb_now", _reading)

    def set_script(*values: float | None, then: float | None) -> list[float | None]:
        script["values"] = list(values)
        script["then"] = then
        return handed

    return set_script


def test_a_read_that_drives_memory_to_the_floor_is_stopped_mid_flight(session, memory, caplog):
    """THE FIX. Plenty at the start and for the first ticks, then the floor: the read
    that was running is stopped, typed, with the reason and the numbers in its message."""
    handed = memory(2000.0, 2000.0, 2000.0, then=100.0)
    with (
        caplog.at_level(logging.WARNING, logger="database.maintenance"),
        pytest.raises(MemoryShort) as err,
        statement_deadline(session, seconds=60),
    ):
        session.execute(_LONG).scalar()
    msg = str(err.value)
    assert "stopped this read" in msg
    assert "100 MB available" in msg and "256 MB floor" in msg
    # ANTI-VACUITY: the stop came from a reading taken WHILE the statement ran (the
    # entry reading was 2000), not from a refusal at the door.
    assert len(handed) >= 4 and handed[0] == 2000.0 and handed[-1] == 100.0
    # A deadline handler that every caller already catches: the API's 503, a
    # diagnostics member's "skipped", a probe's "timed out".
    assert isinstance(err.value, StatementTimeout)
    assert any("memory stop: stopped a read" in r.getMessage() for r in caplog.records), (
        "a stop must leave a line in the error log, or the next bundle cannot see it"
    )


def test_a_read_is_refused_when_memory_is_already_at_the_floor(session, memory):
    memory(then=100.0)
    ran: list[bool] = []
    with pytest.raises(MemoryShort) as err, statement_deadline(session, seconds=60):
        ran.append(True)
    assert ran == [], "a refused read must not run its body at all"
    assert "did not start this read" in str(err.value)


def test_plenty_of_memory_never_stops_a_read(session, memory):
    """The negative twin: without it, a handler that always interrupts would pass the
    two tests above."""
    handed = memory(then=5000.0)
    with statement_deadline(session, seconds=60):
        assert session.execute(_LONG).scalar() == 400000
    assert len(handed) >= 2, "the handler must have read memory during the statement"


def test_a_missing_reading_never_stops_a_read(session, memory):
    """No reading is not a low reading: the memory guard's own rule."""
    memory(then=None)
    with statement_deadline(session, seconds=60):
        assert session.execute(_LONG).scalar() == 400000


def test_the_stop_can_be_switched_off_on_its_own(session, memory, monkeypatch):
    monkeypatch.setenv("OO_READ_MEMORY_STOP", "0")
    memory(then=100.0)
    with statement_deadline(session, seconds=60):
        assert session.execute(_LONG).scalar() == 400000


@pytest.mark.parametrize(
    ("available", "stopped"),
    [(400.0, True), (500.0, True), (500.1, False), (600.0, False)],
)
def test_the_floor_is_the_memory_guards_own(session, memory, monkeypatch, available, stopped):
    """The guard pauses collection at its floor and a read stops at the same line, so the
    two cannot disagree about what nearly out of memory means. At the floor counts as
    below it, as it does for the guard (``mem_avail_mb <= avail_floor_mb``). The first
    reading is plenty, so this is the MID-FLIGHT line; the door has its own test."""
    monkeypatch.setattr(memguard.memory_guard, "avail_floor_mb", 500.0)
    memory(2000.0, then=available)
    if stopped:
        with (
            pytest.raises(MemoryShort, match="stopped this read.*500 MB floor"),
            statement_deadline(session, seconds=60),
        ):
            session.execute(_LONG).scalar()
    else:
        with statement_deadline(session, seconds=60):
            assert session.execute(_LONG).scalar() == 400000


def test_at_the_floor_a_read_is_refused_at_the_door_too(session, memory, monkeypatch):
    monkeypatch.setattr(memguard.memory_guard, "avail_floor_mb", 500.0)
    memory(then=500.0)
    with (
        pytest.raises(MemoryShort, match="did not start this read"),
        statement_deadline(session, seconds=60),
    ):
        pass


def test_a_slow_read_with_memory_to_spare_is_still_a_timeout(session, memory):
    """The memory branch must not take over the clock's: a read that ran out of TIME
    says so, and is not reported as a memory stop."""
    memory(then=5000.0)
    with pytest.raises(StatementTimeout) as err, statement_deadline(session, seconds=0.05):
        session.execute(_LONGER).scalar()
    assert not isinstance(err.value, MemoryShort)
    assert "exceeded the" in str(err.value)


def test_a_guarded_endpoint_answers_503_with_the_reason(session, memory):
    """What the operator sees: the heavy-read wrapper every analytics endpoint uses turns
    the stop into an honest 503 that names memory, never a hung request or a dead app."""
    from fastapi import HTTPException

    from src.api import heavy

    heavy._reset_for_tests()
    memory(then=100.0)
    with pytest.raises(HTTPException) as err:
        heavy.guarded_read(session, "memory-stop-test", lambda: session.execute(_LONG).scalar())
    assert err.value.status_code == 503
    assert "nearly out of memory" in str(err.value.detail)
    heavy._reset_for_tests()


def test_the_reading_is_cached_between_ticks(monkeypatch):
    """The handler fires hundreds of times a second on a streaming read; the reading it
    consults is refreshed at most every ``_AVAIL_READ_EVERY_S``, not on every tick."""
    calls: list[int] = []

    def _reading() -> float:
        calls.append(1)
        return 1234.0

    monkeypatch.setattr(maintenance, "_available_mb_now", _reading)
    monkeypatch.setattr(maintenance, "_AVAIL_CACHE", (float("-inf"), None))
    monkeypatch.setattr(maintenance, "_AVAIL_READ_EVERY_S", 3600.0)
    assert [maintenance._available_mb() for _ in range(50)] == [1234.0] * 50
    assert len(calls) == 1
