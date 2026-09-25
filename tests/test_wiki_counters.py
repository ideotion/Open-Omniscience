"""The lane's counters: what the operator's ≥ 72 h run is read from.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The figures matter less than the ABSENCES. A counters block that reports 0 where it
has no reading turns "we never measured" into "nothing happened", and a 72-hour run is
exactly where the two are hardest to tell apart afterwards. Every block here is
checked for what it says when it has nothing to say.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.versioned.models import VersionedChange, VersionedGap, VersionedSizeSample
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.counters import (
    SAMPLE_INTERVAL_S,
    bytes_per_day,
    changes_per_day,
    entity_counts,
    gap_history,
    lane_counters,
    record_size_sample,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


def _changes(db, *, day_offsets):
    for i, offset in enumerate(day_offsets):
        db.add(
            VersionedChange(
                change_ref=f"r{i}",
                feed="stream:oo",
                change_kind="edit",
                recorded_at=NOW - timedelta(days=offset),
            )
        )
    db.flush()


# --------------------------------------------------------------------------- #
# Rows per day.
# --------------------------------------------------------------------------- #
def test_an_empty_lane_reports_UNMEASURED_rather_than_a_row_of_zeros(lane):
    with lane_session("wiki") as db:
        block = changes_per_day(db, window_days=7, now=NOW)
    assert block["measured"] is False
    assert block["total"] == 0


def test_rows_are_counted_by_OUR_clock_not_the_editions(lane):
    """A resumed stream replays yesterday's edits; counting by the source's own time
    would report a quiet day this app in fact spent working."""
    with lane_session("wiki") as db:
        db.add(
            VersionedChange(
                change_ref="replayed",
                feed="stream:oo",
                change_kind="edit",
                occurred_at=NOW - timedelta(days=5),
                recorded_at=NOW,
            )
        )
        db.flush()
        block = changes_per_day(db, window_days=7, now=NOW)
    today = NOW.date().isoformat()
    assert [p for p in block["series"] if p["day"] == today][0]["changes"] == 1
    assert "recorded" in block["method"]


def test_a_day_inside_the_window_with_no_rows_is_a_real_zero(lane):
    with lane_session("wiki") as db:
        _changes(db, day_offsets=[0, 0, 3])
        block = changes_per_day(db, window_days=7, now=NOW)
    assert block["measured"] is True
    assert block["total"] == 3
    assert any(p["changes"] == 0 for p in block["series"]), "quiet days are still days"


# --------------------------------------------------------------------------- #
# Bytes per day -- a rate needs two readings.
# --------------------------------------------------------------------------- #
def test_ONE_sample_is_not_a_small_rate_it_is_NO_rate(lane):
    with lane_session("wiki") as db:
        db.add(VersionedSizeSample(measured_at=NOW, file_bytes=1000))
        db.flush()
        block = bytes_per_day(db, window_days=7, now=NOW)
    assert block["measured"] is False
    assert "not a rate of zero" in block["reason"]
    assert "bytes_per_day" not in block, "no number at all, rather than a zero"


def test_two_samples_give_a_rate_from_the_files_OWN_measured_size(lane):
    with lane_session("wiki") as db:
        db.add(VersionedSizeSample(measured_at=NOW - timedelta(days=2), file_bytes=1_000))
        db.add(VersionedSizeSample(measured_at=NOW, file_bytes=3_000))
        db.flush()
        block = bytes_per_day(db, window_days=7, now=NOW)
    assert block["measured"] is True
    assert block["bytes_per_day"] == pytest.approx(1000.0)
    assert "stat" in block["method"]


def test_two_samples_at_the_SAME_instant_report_no_interval_rather_than_dividing(lane):
    with lane_session("wiki") as db:
        db.add(VersionedSizeSample(measured_at=NOW, file_bytes=1))
        db.add(VersionedSizeSample(measured_at=NOW, file_bytes=2))
        db.flush()
        block = bytes_per_day(db, window_days=7, now=NOW)
    assert block["measured"] is False
    assert "interval" in block["reason"]


def test_a_sample_is_recorded_at_most_once_an_hour(lane):
    with lane_session("wiki") as db:
        assert record_size_sample(db, 500, now=NOW) is True
        assert record_size_sample(db, 600, now=NOW + timedelta(seconds=60)) is False
        assert (
            record_size_sample(db, 700, now=NOW + timedelta(seconds=SAMPLE_INTERVAL_S + 1))
            is True
        )
        assert db.query(VersionedSizeSample).count() == 2


def test_an_UNMEASURABLE_file_size_is_not_stored_as_a_zero(lane):
    """A zero in the series would show up later as a lane that shrank to nothing."""
    with lane_session("wiki") as db:
        assert record_size_sample(db, None, now=NOW) is False
        assert db.query(VersionedSizeSample).count() == 0


# --------------------------------------------------------------------------- #
# Gaps.
# --------------------------------------------------------------------------- #
def test_gaps_are_reported_as_ROWS_with_reasons_and_never_as_a_percentage(lane):
    with lane_session("wiki") as db:
        db.add(
            VersionedGap(feed="stream:oo", reason="retention", detected_at=NOW - timedelta(days=1))
        )
        db.add(VersionedGap(feed="stream:oo", reason="budget", detected_at=NOW))
        db.flush()
        block = gap_history(db, window_days=7, now=NOW)
    assert block["by_reason"] == {"retention": 1, "budget": 1}
    assert block["gaps"][0]["reason"] == "budget", "newest first"
    assert not any("percent" in str(k).lower() for k in block), block.keys()
    assert "never a percentage" in block["caveat"]


def test_a_long_gap_history_says_it_was_TRUNCATED(lane):
    with lane_session("wiki") as db:
        for i in range(6):
            db.add(
                VersionedGap(
                    feed="stream:oo", reason="disconnect", detected_at=NOW - timedelta(hours=i)
                )
            )
        db.flush()
        block = gap_history(db, window_days=7, now=NOW, limit=3)
    assert block["n"] == 3
    assert block["truncated"] is True


# --------------------------------------------------------------------------- #
# Entities.
# --------------------------------------------------------------------------- #
def test_an_entity_with_no_recorded_reason_is_UNRECORDED_and_says_what_that_means(lane):
    from src.versioned.pipeline import ensure_entity

    with lane_session("wiki") as db:
        ensure_entity(db, "oo:p1")
        ensure_entity(db, "oo:p2", admitted_reason="pinned")
        block = entity_counts(db)
    assert block["by_admitted_reason"] == {"unrecorded": 1, "pinned": 1}
    assert "predates the column" in block["caveat"]


# --------------------------------------------------------------------------- #
# The whole reading, and the soak-window seam.
# --------------------------------------------------------------------------- #
def test_the_reading_names_every_block_that_has_NOTHING_to_say(lane):
    with lane_session("wiki") as db:
        out = lane_counters(db, now=NOW)
    assert set(out["unmeasured"]) == {"rows_per_day", "bytes_per_day"}
    assert "no counters file" in out["method"]


def test_no_block_is_flattened_into_a_single_verdict(lane):
    with lane_session("wiki") as db:
        _changes(db, day_offsets=[0])
        out = lane_counters(db, now=NOW)
    assert out["rows_per_day"]["measured"] is True
    assert out["bytes_per_day"]["measured"] is False, (
        "a present row count must not make an absent growth series look measured"
    )


def test_the_soak_window_reports_a_lane_that_has_NEVER_RUN_as_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    try:
        from src.monitoring.soak_window import _wiki_lane

        block = _wiki_lane(72.0)
    finally:
        dispose_all()
    assert block["measured"] is False
    assert "never run" in block["reason"]
    assert "not a reading of zero" in block["reason"]


def test_the_soak_window_reads_a_lane_that_HAS_run(lane, monkeypatch):
    # _wiki_lane reads the counters on the real clock, and these rows sit at the fixed NOW.
    # Unfrozen, the test passed only while the real date stayed inside the 7-day window:
    # it failed on every run from 2026-09-25 00:00 UTC, when the day-1 row fell out, and
    # would have read no rows at all a day later. So the counters' clock is frozen at NOW.
    import src.wiki.counters as counters_mod

    monkeypatch.setattr(counters_mod, "_utcnow", lambda: NOW)
    with lane_session("wiki") as db:
        _changes(db, day_offsets=[0, 1])
    from src.monitoring.soak_window import _wiki_lane

    block = _wiki_lane(72.0)
    assert block["measured"] is True
    assert block["rows_per_day"]["total"] == 2
    assert block["file_bytes"] and block["file_bytes"] > 0, "the file on disk, measured"


def test_the_soak_windows_own_method_line_names_the_lane(lane):
    from src.database.session import SessionLocal, init_db

    init_db()
    from src.monitoring.soak_window import soak_window

    with SessionLocal() as db:
        report = soak_window(db)
    assert "wiki_lane" in report
    assert "Wikipedia lane" in report["method"]
