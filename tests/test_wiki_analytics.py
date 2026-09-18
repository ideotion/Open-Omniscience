"""Q712's analytics 1-3: counts, their limits, and the two that are NOT here.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The block that matters most is analytic 2. The ruling calls it "contested pages"; this
lane stores no editor, so one person editing ten times and ten people disagreeing are
identical rows — and a surface that said "contested" would be making a claim about
people from data about bytes. The tests below pin the honest name, the honest caveat,
and the absence of anything resembling a score.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.versioned.models import VersionedChange
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.analytics import (
    SPARSE_BAR_MAX,
    analytics,
    edit_concentration,
    edit_velocity,
    newly_created,
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


def _change(db, *, ref, edition="en", kind="edit", days_ago=0, delta=None, minutes=0):
    db.add(
        VersionedChange(
            change_ref=ref,
            feed=f"stream:{edition}",
            change_kind=kind,
            external_id=f"{edition}:p1",
            recorded_at=NOW - timedelta(days=days_ago, minutes=-minutes),
            byte_delta=delta,
        )
    )


# --------------------------------------------------------------------------- #
# 1. Edit velocity.
# --------------------------------------------------------------------------- #
def test_an_empty_window_is_UNMEASURED_rather_than_a_row_of_zeros(lane):
    with lane_session("wiki") as db:
        block = edit_velocity(db, now=NOW)
    assert block["measured"] is False
    assert block["total"] == 0


def test_velocity_counts_per_day_AND_per_edition_without_blending_them(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", edition="en")
        _change(db, ref="b", edition="en", days_ago=1)
        _change(db, ref="c", edition="fr")
        db.flush()
        block = edit_velocity(db, now=NOW)
    assert block["total"] == 3
    assert set(block["per_edition"]) == {"en", "fr"}
    assert sum(p["changes"] for p in block["per_edition"]["fr"]) == 1


def test_velocity_names_the_GAP_beside_it_rather_than_reading_a_hole_as_quiet(lane):
    with lane_session("wiki") as db:
        block = edit_velocity(db, now=NOW)
    assert "published gap, not a quiet day" in block["caveat"]


def test_a_short_series_is_marked_SPARSE_so_it_renders_as_bars(lane):
    """Invariant #16, app-wide: fewer than ten points is bars, never a line
    interpolated through them."""
    with lane_session("wiki") as db:
        short = edit_velocity(db, window_days=3, now=NOW)
        long = edit_velocity(db, window_days=SPARSE_BAR_MAX + 5, now=NOW)
    assert short["sparse"] is True
    assert long["sparse"] is False


# --------------------------------------------------------------------------- #
# 2. Edit concentration -- named for what it measures.
# --------------------------------------------------------------------------- #
def test_the_block_is_NOT_called_contested_anywhere_in_its_payload(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a")
        db.flush()
        block = edit_concentration(db, now=NOW)
    flat = str(block).lower()
    assert "contested" in block["caveat"].lower(), "the gap from the ruling's word is STATED"
    for key in block:
        assert "contested" not in key.lower(), key
    assert "cannot show that a page is contested" in " ".join(block["caveat"].split())
    assert flat.count("contested") == 1, "named once, in the caveat, and nowhere else"


def test_a_SIZE_REVERSAL_is_counted_and_the_first_change_can_never_be_one(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", delta=500, minutes=1)
        _change(db, ref="b", delta=-500, minutes=2)
        _change(db, ref="c", delta=500, minutes=3)
        db.flush()
        block = edit_concentration(db, now=NOW)
    page = block["pages"][0]
    assert page["changes"] == 3
    assert page["reversals"] == 2, "there is nothing before the first change to reverse"
    assert page["bytes_added"] == 1000 and page["bytes_removed"] == 500


def test_a_ZERO_delta_is_not_a_direction_and_neither_counts_nor_resets(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", delta=100, minutes=1)
        _change(db, ref="b", delta=0, minutes=2)
        _change(db, ref="c", delta=100, minutes=3)
        db.flush()
        block = edit_concentration(db, now=NOW)
    assert block["pages"][0]["reversals"] == 0


def test_nothing_in_the_payload_is_normalised_weighted_or_named_like_a_score(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", delta=10)
        db.flush()
        block = edit_concentration(db, now=NOW)
    banned = ("score", "ranking", "rating", "grade", "index", "severity")
    for key in block:
        assert not any(b in key.lower() for b in banned), key
    for page in block["pages"]:
        for key in page:
            assert not any(b in key.lower() for b in banned), key
        for key, value in page.items():
            if isinstance(value, float):
                raise AssertionError(f"{key} is a float -- every figure here is a count")


# --------------------------------------------------------------------------- #
# 3. Newly created.
# --------------------------------------------------------------------------- #
def test_only_creations_the_lane_was_TOLD_about_are_counted(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", kind="create")
        _change(db, ref="b", kind="edit")
        db.flush()
        block = newly_created(db, now=NOW)
    assert block["total"] == 1
    assert block["per_edition"] == {"en": 1}
    assert "published gap" in block["caveat"]


def test_creations_report_the_recent_ones_by_id_so_a_reader_can_open_them(lane):
    with lane_session("wiki") as db:
        _change(db, ref="a", kind="create")
        db.flush()
        block = newly_created(db, now=NOW)
    assert block["recent"][0]["external_id"] == "en:p1"


# --------------------------------------------------------------------------- #
# The two that are 0.5's are ABSENT, not stubbed.
# --------------------------------------------------------------------------- #
def test_divergence_and_attention_are_NOT_in_the_payload_at_all(lane):
    """Not stubbed, not listed as pending. A surface that named them would be
    advertising a feature; a stub would be building one 0.4 is not meant to have."""
    with lane_session("wiki") as db:
        out = analytics(db, now=NOW)
    flat = str(out).lower()
    assert "divergence" not in flat
    assert "attention" not in flat
    assert set(out) >= {"edit_velocity", "edit_concentration", "newly_created"}


def test_the_composition_carries_no_verdict_of_its_own(lane):
    with lane_session("wiki") as db:
        out = analytics(db, now=NOW)
    assert "nothing is normalised" in out["method"].lower()
    assert set(out["unmeasured"]) == {"edit_velocity", "edit_concentration", "newly_created"}
