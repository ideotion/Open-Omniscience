"""The soak window: five readings, each against the window it actually read.

0.3 gate row 7 and the 0.4 board both ask for a multi-day collector soak, and after the
2026-07 multi-hour stalls ended nothing in the app could say what had happened. The
instruments existed; none of them covers a soak. ``collect_perf.jsonl`` is a ring over
roughly one pass, the latency reservoir keeps 512 requests per route, the error log is a
rolling 2,000 records. A member that read one of those and reported on three days would
be the fabricated-pass shape.

So every assertion here is about a WINDOW and a DENOMINATOR, and each has its negative
space: an unknown window must withhold the rate rather than divide by a guess; a blind
memory guard's zero must not read as calm; a WAL series that spans restarts must be
filtered to this process and must not silently drop a reading that belongs to it; a
rolling log at capacity must publish its counts as a floor.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base
from src.monitoring import soak_window as sw

_BANNED_KEY_FRAGMENTS = ("score", "rating", "ranking", "grade")


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Forensics writes a session sentinel under ``data_dir()``; no test here may read
    the developer's real one, and none may leave one behind."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _uptime(monkeypatch, *, seconds: float | None, started_at: str | None = None):
    """Stub the soak clock. The accessor itself is driven for real further down."""
    from src.monitoring import forensics

    if seconds is None:
        payload = {
            "measured": False,
            "started_at": None,
            "seconds": None,
            "reason": "this process never called record_session_start()",
        }
    else:
        at = started_at or (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
            timespec="seconds"
        )
        payload = {"measured": True, "started_at": at, "seconds": seconds}
    monkeypatch.setattr(forensics, "session_uptime", lambda: payload)
    return payload


def _guard(monkeypatch, **over):
    """A memory guard that is a REAL one with named fields overridden.

    Subclassed rather than hand-rolled for two reasons the recorded stub-drift lesson
    names: the base payload is whatever the guard really publishes, so a field it gains
    appears here too and a field this module reads that the guard never had shows up as
    None instead of passing silently; and every OTHER method still exists, so the
    suite's own leak-guard fixture (which calls ``reset()`` at teardown) still works."""
    from src.scheduler import memguard

    class _Fake(memguard.MemoryGuard):
        def state(self) -> dict:
            return {**super().state(), **over}

    monkeypatch.setattr(memguard, "memory_guard", _Fake())


def _gate(monkeypatch, **over):
    """Same discipline for the write gate: a real gate with named counters overridden."""
    from src.database import writer

    class _Fake(writer.WriterGate):
        def stats(self) -> dict:
            return {**super().stats(), **over}

    monkeypatch.setattr(writer, "write_gate", _Fake())


def _series(monkeypatch, points):
    from src.database import snapshots

    monkeypatch.setattr(
        snapshots,
        "metric_history",
        lambda session, *, metric, days: {
            "metric": metric,
            "series": list(points),
            "recording_began_at": points[0]["t"] if points else None,
        },
    )


def _walk_keys(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            _walk_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_keys(v, out)


# --------------------------------------------------------------------------- #
# The clock                                                                    #
# --------------------------------------------------------------------------- #


def test_uptime_never_adopts_a_previous_sessions_timestamp_from_disk(monkeypatch, tmp_path):
    """The misattribution ``session_hwm`` was built to prevent, one file over.

    ``session_state.json`` is written by EVERY session. A reader that took ``started_at``
    from it would report the previous process's start as this one's uptime -- and would
    do it precisely when this process never stamped itself, i.e. when it has no claim to
    make at all."""
    from src.monitoring import forensics

    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session_state.json").write_text(
        json.dumps({"state": "running", "started_at": "2020-01-01T00:00:00+00:00", "pid": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(forensics, "_SESSION_STARTED_MONO", None)
    monkeypatch.setattr(forensics, "_SESSION_STARTED_AT", None)

    got = forensics.session_uptime()
    assert got["measured"] is False
    assert got["seconds"] is None
    assert "record_session_start" in got["reason"]
    assert got["started_at"] is None, "the file's timestamp must not leak in as ours"


def test_uptime_measures_from_this_processs_own_stamp(monkeypatch):
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "_SESSION_STARTED_MONO", None)
    monkeypatch.setattr(forensics, "_SESSION_STARTED_AT", None)
    forensics.record_session_start()

    got = forensics.session_uptime()
    assert got["measured"] is True
    assert got["started_at"]
    assert got["seconds"] is not None and got["seconds"] >= 0.0


@pytest.mark.parametrize(
    ("seconds", "reaches"),
    [(3600.0, False), (72 * 3600.0, True), (100 * 3600.0, True)],
)
def test_the_bar_is_a_fact_about_the_windows_length(monkeypatch, session, seconds, reaches):
    _uptime(monkeypatch, seconds=seconds)
    win = sw.soak_window(session)["window"]
    assert win["measured"] is True
    assert win["bar_hours"] == sw.SOAK_BAR_HOURS
    assert win["reaches_bar"] is reaches


def test_an_unknown_window_leaves_every_rate_unmeasured_and_names_them(monkeypatch, session):
    """Not-measurable must be reported, per block AND in one place, so a reader does not
    have to walk five blocks to discover the report could not speak."""
    _uptime(monkeypatch, seconds=None)
    _series(monkeypatch, [])
    got = sw.soak_window(session)

    assert got["window"]["measured"] is False
    assert got["window"]["reaches_bar"] is None
    for block in ("memory_guard", "wal", "write_gate"):
        assert got[block]["measured"] is False, block
        assert got[block]["reason"], block
        assert block in got["unmeasured"]


# --------------------------------------------------------------------------- #
# Memory guard                                                                 #
# --------------------------------------------------------------------------- #


def test_engagements_per_day_uses_the_window_as_its_denominator(monkeypatch, session):
    _uptime(monkeypatch, seconds=12 * 3600.0)
    _guard(monkeypatch, engagements=6, total_engaged_s=1800.0, readings_available=True)

    mg = sw.soak_window(session)["memory_guard"]
    assert mg["measured"] is True
    assert mg["engagements"] == 6
    assert mg["engagements_per_day"] == 12.0, "6 in half a day is 12 a day"
    assert mg["paused_share"] == pytest.approx(1800.0 / (12 * 3600.0), abs=1e-4)


def test_a_blind_guard_is_unmeasured_rather_than_a_clean_zero(monkeypatch, session):
    """An enabled guard with no psutil readings has engaged zero times and knows
    nothing. Publishing that zero as a measurement would be the fabricated pass."""
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _guard(monkeypatch, enabled=True, engagements=0, readings_available=False)

    mg = sw.soak_window(session)["memory_guard"]
    assert mg["measured"] is False
    assert "blind" in mg["reason"]


def test_a_seeing_guard_that_never_engaged_is_a_real_zero(monkeypatch, session):
    """The twin. Over-eager withholding would delete a genuine measurement -- the
    machine really was under no memory pressure, which is what a soak wants to hear."""
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _guard(
        monkeypatch,
        enabled=True,
        engagements=0,
        total_engaged_s=0.0,
        readings_available=True,
    )

    mg = sw.soak_window(session)["memory_guard"]
    assert mg["measured"] is True
    assert mg["engagements_per_day"] == 0.0
    assert mg["paused_share"] == 0.0


def test_a_window_under_the_rate_floor_keeps_the_counts_and_withholds_the_rate(
    monkeypatch, session
):
    """One engagement ten seconds in extrapolates to 8,640 a day. The COUNT is real and
    is published; the rate is not, and says why."""
    _uptime(monkeypatch, seconds=10.0)
    _guard(monkeypatch, engagements=1, total_engaged_s=2.0, readings_available=True)

    mg = sw.soak_window(session)["memory_guard"]
    assert mg["measured"] is False
    assert mg["engagements"] == 1, "the count survives -- only the rate is withheld"
    assert "engagements_per_day" not in mg
    assert "floor" in mg["reason"]


# --------------------------------------------------------------------------- #
# WAL                                                                          #
# --------------------------------------------------------------------------- #


def _hour(dt: datetime) -> str:
    return dt.replace(minute=0, second=0, microsecond=0).isoformat()


def test_the_wal_maximum_is_taken_over_the_window_not_the_whole_series(monkeypatch, session):
    """The series has infinite retention and spans restarts, so a spike from a previous
    session is real history and is NOT this soak's maximum."""
    start = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    _uptime(monkeypatch, seconds=3 * 3600.0, started_at=start.isoformat(timespec="seconds"))
    _series(
        monkeypatch,
        [
            {"t": _hour(start - timedelta(days=4)), "n": 9_000_000_000},
            {"t": _hour(start + timedelta(hours=1)), "n": 111},
            {"t": _hour(start + timedelta(hours=2)), "n": 222},
        ],
    )

    wal = sw.soak_window(session)["wal"]
    assert wal["measured"] is True
    assert wal["max_bytes"] == 222, "the previous session's 9 GB is not this window's max"
    assert wal["points_in_window"] == 2
    assert wal["series_points_read"] == 3, "the wider history is still reported beside it"


def test_a_reading_in_the_start_hour_is_kept_and_the_widening_is_disclosed(
    monkeypatch, session
):
    """The series is bucketed to the top of the hour, so a snapshot genuinely taken at
    10:45 by a process that started at 10:30 carries the stamp 10:00. Dropping it would
    UNDER-report a WAL maximum, which is the dangerous direction for a growth hazard --
    so the boundary is widened to the containing hour and the widening is stated."""
    start = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    _uptime(monkeypatch, seconds=2 * 3600.0, started_at=start.isoformat(timespec="seconds"))
    _series(monkeypatch, [{"t": _hour(start), "n": 777}])

    wal = sw.soak_window(session)["wal"]
    assert wal["measured"] is True
    assert wal["max_bytes"] == 777
    assert "59 minutes" in wal["boundary_note"]


def test_no_snapshot_since_the_process_started_is_unmeasured_not_zero(monkeypatch, session):
    start = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    _uptime(monkeypatch, seconds=3600.0, started_at=start.isoformat(timespec="seconds"))
    _series(monkeypatch, [{"t": _hour(start - timedelta(days=2)), "n": 500}])

    wal = sw.soak_window(session)["wal"]
    assert wal["measured"] is False
    assert "max_bytes" not in wal
    assert "since this process started" in wal["reason"]


def test_a_never_recorded_wal_says_so_rather_than_reporting_a_healthy_series(
    monkeypatch, session
):
    _uptime(monkeypatch, seconds=3600.0)
    _series(monkeypatch, [])

    wal = sw.soak_window(session)["wal"]
    assert wal["measured"] is False
    assert "never been recorded" in wal["reason"]


def test_the_wal_read_window_is_bounded_even_for_a_very_long_uptime(monkeypatch, session):
    """Infinite retention is a storage property; the RESPONSE is always bounded."""
    seen: dict[str, int] = {}
    from src.database import snapshots

    def _fake(session, *, metric, days):
        seen["days"] = days
        return {"metric": metric, "series": [], "recording_began_at": None}

    monkeypatch.setattr(snapshots, "metric_history", _fake)
    _uptime(monkeypatch, seconds=400 * 86400.0)
    sw.soak_window(session)
    assert seen["days"] == sw._WAL_DAYS_MAX


# --------------------------------------------------------------------------- #
# Write gate                                                                   #
# --------------------------------------------------------------------------- #


def test_busy_share_divides_held_time_and_deliberately_does_not_divide_wait_time(
    monkeypatch, session
):
    """The gate is exclusive, so held time is bounded by wall time and really is a
    share. ``total_wait_s`` sums ACROSS waiters and can exceed the window -- dividing it
    would publish a 'share' above 1, which is not a share."""
    _uptime(monkeypatch, seconds=1000.0)
    _gate(monkeypatch, total_held_s=250.0, total_wait_s=4000.0, grants=200, contended=50)

    wg = sw.soak_window(session)["write_gate"]
    assert wg["measured"] is True
    assert wg["busy_share"] == 0.25
    assert wg["contended_share_of_grants"] == 0.25
    assert wg["total_wait_s"] == 4000.0
    assert not any(k for k in wg if k.startswith("wait_share")), (
        "aggregate waiting must not be published as a share of the window"
    )


def test_a_gate_with_no_accumulated_hold_time_is_unmeasured(monkeypatch, session):
    _uptime(monkeypatch, seconds=1000.0)
    _gate(monkeypatch, total_held_s=None)

    wg = sw.soak_window(session)["write_gate"]
    assert wg["measured"] is False
    assert "busy_share" not in wg


# --------------------------------------------------------------------------- #
# /api/database/stats latency                                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _clean_latency():
    from src.monitoring import latency

    latency._reset_for_tests()
    yield latency
    latency._reset_for_tests()


def test_the_p95_is_read_from_the_real_reservoir_and_states_it_is_not_the_soak_window(
    monkeypatch, session, _clean_latency
):
    """Driven through the production recorder, not a double: the shape of a route row is
    the latency module's to define."""
    for i, ms in enumerate([5.0, 6.0, 7.0, 400.0]):
        _clean_latency.record(i, sw._DB_STATS_ROUTE, 200, ms)
    _uptime(monkeypatch, seconds=80 * 3600.0)

    lat = sw.soak_window(session)["database_stats_latency"]
    assert lat["measured"] is True
    assert lat["requests_total"] == 4
    assert lat["window_n"] == 4
    assert lat["p95_ms"] is not None
    assert "NOT the soak window" in lat["window_basis"]


def test_an_uncalled_route_is_unmeasured_rather_than_fast(monkeypatch, session, _clean_latency):
    """A route nobody called has no p95. Reporting one -- or a 0 -- would be a
    measurement of nothing."""
    _uptime(monkeypatch, seconds=80 * 3600.0)

    lat = sw.soak_window(session)["database_stats_latency"]
    assert lat["measured"] is False
    assert "p95_ms" not in lat
    assert "not been called" in lat["reason"]


# --------------------------------------------------------------------------- #
# Interrupted statements                                                       #
# --------------------------------------------------------------------------- #


def _errlog(monkeypatch, **over):
    from src.monitoring import errorlog

    base = {
        "records": 12,
        "records_cap": 2000,
        "last_session_started_at": "2026-09-07T00:00:00+00:00",
        "interrupted_errors_this_session": 3,
        "interrupted_errors_total": 5,
    }
    monkeypatch.setattr(errorlog, "summary", lambda: {**base, **over})


def test_a_full_error_log_publishes_the_interrupted_count_as_a_floor(monkeypatch, session):
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _errlog(monkeypatch, records=2000, records_cap=2000)

    it = sw.soak_window(session)["interrupted"]
    assert it["at_capacity"] is True
    assert "floor" in it["floor_note"]


def test_a_log_below_capacity_carries_no_floor_note(monkeypatch, session):
    """The twin: a census that is a census must not be labelled a floor."""
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _errlog(monkeypatch, records=12, records_cap=2000)

    it = sw.soak_window(session)["interrupted"]
    assert it["at_capacity"] is False
    assert "floor_note" not in it
    assert it["this_session"] == 3


def test_a_log_with_no_boot_marker_says_nothing_is_attributed_to_this_session(
    monkeypatch, session
):
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _errlog(monkeypatch, last_session_started_at=None)

    it = sw.soak_window(session)["interrupted"]
    assert "session_note" in it


def test_the_error_log_publishes_its_own_retention_beside_its_counts(tmp_path):
    """The denominator travels WITH the counts, in the log's own payload, so every
    reader of it sees the ceiling -- not just this one.

    The log must be NON-EMPTY: ``summary()`` has an early-return branch for an empty log,
    and a test run against the sandbox's empty log takes that branch and never reaches the
    counts. The first mutation run passed for exactly that reason.
    """
    from src.monitoring.errorlog import _log_path, summary

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"at": "2026-09-07T00:00:00+00:00", "level": "BOOT", "message": "start"},
                {"at": "2026-09-07T00:01:00+00:00", "level": "ERROR", "message": "interrupted"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    got = summary()
    assert got["records"] == 2, "the counts branch must be the one under test"
    assert "records_cap" in got
    assert isinstance(got["records_cap"], int) and got["records_cap"] > 0


# --------------------------------------------------------------------------- #
# Shape                                                                        #
# --------------------------------------------------------------------------- #


def test_no_score_shaped_keys_anywhere(monkeypatch, session):
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _series(monkeypatch, [{"t": _hour(datetime.now(UTC)), "n": 1}])
    keys: list[str] = []
    _walk_keys(sw.soak_window(session), keys)
    bad = [k for k in keys if any(f in k.lower() for f in _BANNED_KEY_FRAGMENTS)]
    assert not bad, bad


def test_the_report_publishes_no_verdict(monkeypatch, session):
    """Whether a soak passed is the maintainer's reading. ``reaches_bar`` is a fact about
    the window's LENGTH and is deliberately the only bar-shaped key in the payload."""
    _uptime(monkeypatch, seconds=80 * 3600.0)
    _series(monkeypatch, [])
    keys: list[str] = []
    _walk_keys(sw.soak_window(session), keys)
    lowered = [k.lower() for k in keys]
    for word in ("verdict", "passed", "healthy", "status"):
        assert word not in lowered, word
    assert lowered.count("reaches_bar") == 1


def test_the_bundle_member_produces_a_real_report(session, monkeypatch):
    """Behavioural, through the REAL member generator.

    Asserting only that the payload is a dict with the right keys is NOT enough, and the
    mutation matrix said so: handing the route its ``Depends`` sentinel instead of a
    Session still returns that shape, because every block degrades honestly and the
    degrade becomes the hiding place for the bug. So the assertion is on a value only a
    real Session can produce -- a wal_bytes row read back out of this database.
    """
    from src.database.models import StatSnapshot
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "_SESSION_STARTED_MONO", None)
    monkeypatch.setattr(forensics, "_SESSION_STARTED_AT", None)
    forensics.record_session_start()
    session.add(
        StatSnapshot(
            metric="wal_bytes",
            taken_at=datetime.now(UTC).replace(minute=0, second=0, microsecond=0, tzinfo=None),
            value=4242,
        )
    )
    session.commit()

    import src.api.diagnostics as diag

    members = dict(diag._all_diagnostics_members(session))
    assert "soak-window.json" in members
    payload = members["soak-window.json"]()
    assert isinstance(payload, dict)
    assert "window" in payload and "unmeasured" in payload
    assert payload["window"]["bar_hours"] == sw.SOAK_BAR_HOURS
    assert payload["wal"]["measured"] is True, payload["wal"]
    assert payload["wal"]["max_bytes"] == 4242


# --------------------------------------------------------------------------- #
# The counters the report reads                                                #
#                                                                              #
# Every block above drives a double, which proves the report's arithmetic and  #
# nothing about whether the numbers it divides are real. These three drive the #
# production accumulators instead. Each uses a FRESH instance rather than the  #
# process singleton: the counters are cumulative by contract, so a test that   #
# advanced the shared one would leave residue for the rest of the suite.       #
# --------------------------------------------------------------------------- #


def test_the_write_gate_accumulates_held_time_and_excludes_the_hold_in_flight():
    """``total_held_s`` is the soak's busy-share numerator, and it is accumulated on
    RELEASE. A hold in flight is deliberately not in it -- ``held_for_s`` is that hold,
    and adding them would be the reader's decision, not the gate's."""
    import time

    from src.database.writer import WriterGate

    gate = WriterGate()
    assert gate.stats()["total_held_s"] == 0.0

    assert gate.acquire(timeout=5.0) is True
    time.sleep(0.02)
    during = gate.stats()
    assert during["total_held_s"] == 0.0, "an open hold is not yet accumulated"
    assert during["held_for_s"] is not None and during["held_for_s"] > 0.0
    gate.release()

    after = gate.stats()
    assert after["total_held_s"] > 0.0
    assert after["held_for_s"] is None
    assert after["total_held_s"] >= 0.02


def test_the_memory_guard_counts_engagements_and_accumulates_paused_time():
    """The soak's engage-cycle numerator. An OPEN episode is not folded into
    ``total_engaged_s`` -- a machine still paused has not finished serving that
    duration, and reporting it as completed would over-state the paused share."""
    import time

    from src.scheduler.memguard import MemoryGuard

    g = MemoryGuard(trip_after=1, release_fn=lambda: {})
    assert g.state()["engagements"] == 0

    g.observe(rss_mb=900.0, mem_avail_mb=10.0, mem_total_mb=1000.0)
    engaged = g.state()
    assert engaged["engaged"] is True
    assert engaged["engagements"] == 1
    assert engaged["total_engaged_s"] == 0.0, "the episode is still open"

    # Long enough to survive state()'s own rounding to a tenth of a second: the
    # assertion is about the figure the report PUBLISHES, not an unrounded internal.
    time.sleep(0.15)
    g.reset(reason="test")
    resumed = g.state()
    assert resumed["engaged"] is False
    assert resumed["total_engaged_s"] >= 0.1

    g.observe(rss_mb=900.0, mem_avail_mb=10.0, mem_total_mb=1000.0)
    assert g.state()["engagements"] == 2, "a second episode is a second cycle"


def test_both_shapes_of_an_aborted_statement_count_and_an_unrelated_error_does_not():
    """Two things abort a statement and both matter to the same reader: the typed
    ``StatementTimeout`` a deadline raises, and the raw "interrupted" SQLite surfaces when
    a progress handler returns non-zero -- which is also how a handler left armed on a
    POOLED connection cuts short the NEXT checkout. The negative space is the point: an
    ordinary error must not be counted, or the soak's interrupt figure means nothing."""
    from src.monitoring.errorlog import _log_path, summary

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"at": "2026-09-07T00:00:00+00:00", "level": "BOOT", "message": "start"},
                {
                    "at": "2026-09-07T00:01:00+00:00",
                    "level": "ERROR",
                    # The deadline's own words (src/database/maintenance.py), not invented.
                    "message": "statement exceeded the 60s deadline and was aborted",
                },
                {
                    "at": "2026-09-07T00:02:00+00:00",
                    "level": "ERROR",
                    "message": "OperationalError: interrupted",
                },
                {
                    "at": "2026-09-07T00:03:00+00:00",
                    "level": "ERROR",
                    "message": "database is locked",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    got = summary()
    assert got["interrupted_errors_total"] == 2
    assert got["interrupted_errors_this_session"] == 2
    assert got["locked_errors_total"] == 1, "the lock error is its own count, not an abort"
