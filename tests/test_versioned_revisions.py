"""S1: the diff, the baseline's one-writeness, and the point-in-time read's caveat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_versioned_lane.py`` drives these through a whole pass, which proves
they compose. This file drives them DIRECTLY, because a property that only ever
appears at the end of a pipeline is a property whose failure arrives as a wrong
number somewhere else: an off-by-one in the diff counter reads as rounding, an
overwritable baseline reads as a corrected record, and a point-in-time answer that
drops its ``newer_unheld`` context reads as a complete history.

``compute_diff`` and ``content_hash`` are pure, so they are exercised with no
database at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import StatementError

from src.versioned import revisions as rev
from src.versioned import store
from src.versioned.models import VersionedChange, VersionedEntity

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
T2 = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A lane file of this test's own, disposed on both edges."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.create_lane("wiki")
    try:
        yield
    finally:
        store.dispose_all()


def _entity(session, external_id="oo:Page"):
    row = VersionedEntity(external_id=external_id, title="Page", watching=True)
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------- diff


def test_the_diff_counters_EXCLUDE_the_unified_diff_file_headers():
    """``+++ current`` and ``--- previous`` are headers, not edits.

    Counting them inflates EVERY diff by exactly one add and one remove — an error
    small enough to pass for rounding and therefore never questioned. A one-line
    change must read as one added and one removed, and nothing else.
    """
    out = rev.compute_diff("alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n")
    assert out.method == rev.DIFF_UNIFIED
    assert (out.added, out.removed) == (1, 1), out
    assert out.text is not None and out.text.startswith("---"), "not a unified diff"


def test_an_APPEND_is_counted_as_an_add_and_no_removal():
    out = rev.compute_diff("one\n", "one\ntwo\n")
    assert (out.added, out.removed) == (1, 0), out
    assert out.byte_delta == 4


def test_IDENTICAL_texts_diff_to_nothing_rather_than_to_a_header_pair():
    """The degenerate case the header bug hides in: zero must be zero."""
    out = rev.compute_diff("same\n", "same\n")
    assert (out.added, out.removed) == (0, 0), out
    assert out.byte_delta == 0
    assert out.text == ""


def test_NO_PREVIOUS_TEXT_is_its_own_method_and_never_a_fabricated_delta():
    """A lane holding a change's metadata without its text is a REAL state.

    The byte delta then is the whole of the new text, because there is nothing to
    subtract — and the method says so, so a reader is never shown a "+412 bytes"
    that silently means "we have no idea what it was before".
    """
    out = rev.compute_diff(None, "hello\n")
    assert out.method == rev.DIFF_NO_PREVIOUS
    assert out.added is None and out.removed is None, out
    assert out.byte_delta == 6
    assert out.text is None


def test_a_TOO_LARGE_pair_publishes_its_bound_and_leaves_the_counters_NULL():
    """Past the bound the counters are absent, never filled from a cheaper method.

    A line count taken a different way is a different measurement under the same
    field name — the exact shape of dishonesty the no-composite-scores rule exists
    to prevent, arriving as an optimisation.
    """
    big = "x\n" * (rev._MAX_DIFF_LINES + 1)
    out = rev.compute_diff(big, big + "y\n")
    assert out.method == rev.DIFF_TOO_LARGE
    assert out.added is None and out.removed is None, out
    assert out.text is None
    # The delta is subtraction, so it stays exact even here.
    assert out.byte_delta == 2


def test_the_content_hash_tells_a_NULL_EDIT_from_a_rewrite():
    """A new revision id proves nothing about the text; the hash is what does."""
    assert rev.content_hash("body\n") == rev.content_hash("body\n")
    assert rev.content_hash("body\n") != rev.content_hash("body \n")


# ----------------------------------------------------------------------- baseline


def test_a_SECOND_baseline_is_refused_BY_NAME(lane):
    """The anchor is written once. Moving it rewrites the past.

    Every diff in the lane is ultimately taken against the baseline, so a baseline
    that can be replaced makes "what changed since we started watching" stop meaning
    anything — silently, and retroactively.
    """
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="first\n", revised_at=T0)
        with pytest.raises(rev.BaselineExistsError) as excinfo:
            rev.capture_baseline(session, entity, revision_ref="2", text="second\n", revised_at=T1)
        message = str(excinfo.value)
        assert "oo:Page" in message, message
        assert "'1'" in message, message
        # ...and the original survived the attempt.
        assert rev.baseline_for(session, entity.id).content == "first\n"


def test_the_previous_version_is_the_newest_by_REVISED_AT_not_by_insertion_order(lane):
    """A backfill inserts an OLDER version LATER. Ordering by id would diff against it.

    The result would be a diff describing an edit that runs backwards in time, under
    a ``diff_from_ref`` that names a version the reader can open and see is older.
    """
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=T0)
        rev.record_revision(session, entity, revision_ref="9", text="c\n", revised_at=T2)
        # Inserted last, dated in between: the backfill case.
        rev.record_revision(session, entity, revision_ref="5", text="b\n", revised_at=T1)
        ref, text = rev.previous_ingested(session, entity.id)
        assert ref == "9", f"the previous version was taken by insertion order: {ref}"
        assert text == "c\n"


def test_re_offering_a_held_revision_is_IDEMPOTENT_and_fills_a_late_article_link(lane):
    """A retry after a partial pass is the normal case, not an error.

    A unique violation here would roll back the whole batch — losing the changes
    that DID land to re-learn something the lane already knew.
    """
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=T0)
        first, created = rev.record_revision(
            session, entity, revision_ref="2", text="b\n", revised_at=T1
        )
        assert created is True
        again, created = rev.record_revision(
            session, entity, revision_ref="2", text="b\n", revised_at=T1, article_id=77
        )
        assert created is False
        assert again.id == first.id, "a second row was written for one version"
        assert again.article_id == 77, "an article link learned later was dropped"

        # ...but a link already held is never overwritten by a later, different one.
        third, _ = rev.record_revision(
            session, entity, revision_ref="2", text="b\n", revised_at=T1, article_id=99
        )
        assert third.article_id == 77, "an existing article link was overwritten"


def test_the_first_revision_after_a_baseline_diffs_AGAINST_THE_BASELINE(lane):
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\nb\n", revised_at=T0)
        row, _ = rev.record_revision(
            session, entity, revision_ref="2", text="a\nB\n", revised_at=T1
        )
        assert row.diff_from_ref == "1"
        assert row.diff_method == rev.DIFF_UNIFIED
        assert (row.diff_added, row.diff_removed) == (1, 1)


# ------------------------------------------------------------------ point in time


def test_a_point_in_time_read_carries_the_COUNT_OF_WHAT_IT_DOES_NOT_HOLD(lane):
    """``newer_unheld`` is what turns a text into an honest answer.

    Without it the read says "here is what was in force", when the truthful
    statement is "here is the newest version we hold, and N changes we were TOLD
    about happened between it and the instant you asked for".
    """
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=T0)
        for i, when in enumerate((T1, T2), start=1):
            session.add(
                VersionedChange(
                    feed="recentchanges:oo",
                    change_ref=f"c{i}",
                    change_kind="edit",
                    entity_id=entity.id,
                    external_id=entity.external_id,
                    occurred_at=when,
                )
            )
        session.flush()

        answer = rev.version_at(session, entity.id, datetime(2026, 3, 15, tzinfo=UTC))
        assert answer.is_baseline is True
        assert answer.held.revision_ref == "1"
        assert answer.newer_unheld == 2, "the read claimed a completeness it does not have"

        # An instant BEFORE the later change counts only what preceded it.
        earlier = rev.version_at(session, entity.id, datetime(2026, 2, 15, tzinfo=UTC))
        assert earlier.newer_unheld == 1


def test_changes_OLDER_than_the_held_version_are_not_counted_as_unheld(lane):
    """A change that predates the version we hold is already IN it.

    The held text incorporates everything that happened before it was written, so
    counting those changes would inflate the caveat — telling the reader we are
    missing edits that are, demonstrably, in the very text they are looking at. This
    is the assertion that distinguishes the bound from its absence: a matrix run
    without it left "count every change up to the instant" alive, because in the
    ordinary case every recorded change happens to be newer than the baseline.
    """
    from src.versioned.models import VersionedChange

    with store.lane_session("wiki") as session:
        entity = _entity(session)
        # The baseline sits in the MIDDLE: one change before it, one after.
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=T1)
        for ref, when in (("before", T0), ("after", T2)):
            session.add(
                VersionedChange(
                    feed="recentchanges:oo",
                    change_ref=ref,
                    change_kind="edit",
                    entity_id=entity.id,
                    external_id=entity.external_id,
                    occurred_at=when,
                )
            )
        session.flush()

        answer = rev.version_at(session, entity.id, datetime(2026, 3, 15, tzinfo=UTC))
        assert answer.held.revision_ref == "1"
        assert answer.newer_unheld == 1, (
            "a change older than the held version was counted as missing from it"
        )


def test_an_UNDATED_version_never_answers_a_point_in_time_question(lane):
    """An unknown date is not a date. Admitting it lets one version answer for any
    instant at all — including instants before the source published it."""
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=None)
        rev.record_revision(session, entity, revision_ref="2", text="b\n", revised_at=None)
        answer = rev.version_at(session, entity.id, T2)
        assert answer.held is None, "an undated version was served as in force"
        assert answer.is_baseline is False


def test_the_timeline_total_is_COUNTED_never_the_length_of_the_page(lane):
    """The anti-capping rule: a displayed figure must never secretly be a cap."""
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="0", text="a\n", revised_at=T0)
        for i in range(1, 8):
            rev.record_revision(
                session,
                entity,
                revision_ref=str(i),
                text="a\n" * i,
                revised_at=datetime(2026, 4, i, tzinfo=UTC),
            )
        rows, total = rev.timeline(session, entity.id, limit=3)
        assert len(rows) == 3
        assert total == 7, f"the total is the page length, not the count: {total}"
        assert [r.revision_ref for r in rows] == ["7", "6", "5"], "not newest first"


# ------------------------------------------------------------------- the timestamp


def test_a_NAIVE_timestamp_is_REFUSED_ON_WRITE_rather_than_assumed_to_be_UTC(lane):
    """MEASURED: SQLite has no aware storage, so ``timezone=True`` is intent only.

    Assuming UTC would put the guess in the one place nobody can audit later, and
    "the caller had a naive datetime" and "the caller had a UTC one" are different
    facts about someone else's data. The refusal names the value.

    AND IT ARRIVES WRAPPED. A bind processor runs inside the flush, so the
    ``ValueError`` reaches the caller as ``sqlalchemy.exc.StatementError`` — which is
    NOT a ``ValueError``, so ``except ValueError`` around a flush does not catch it.
    This test asserts the shape that actually surfaces rather than the one the
    ``raise`` line reads like, because that difference is what a caller writing an
    error path would get wrong.
    """
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        with pytest.raises(StatementError) as excinfo:
            rev.capture_baseline(
                session,
                entity,
                revision_ref="1",
                text="a\n",
                revised_at=datetime(2026, 1, 1),  # noqa: DTZ001 - the point of the test
            )
        assert isinstance(excinfo.value.orig, ValueError), excinfo.value.orig
        assert "timezone-aware" in str(excinfo.value), str(excinfo.value)
        assert "2026, 1, 1" in str(excinfo.value), "the refusal does not name the value"
        # The failed flush poisoned the transaction, so this block must not be
        # allowed to reach ``lane_session``'s commit: SWALLOWING a flush failure and
        # carrying on is the caller bug, and the session raises PendingRollbackError
        # rather than committing whatever else was pending. Rolled back here so this
        # test exercises the refusal instead of that second, separate refusal.
        session.rollback()

    # ...and the refusal left NOTHING behind: no half-written baseline to be read
    # later as a real one with a missing date.
    with store.lane_session("wiki") as session:
        assert rev.baseline_for(session, 1) is None


def test_a_stored_timestamp_comes_BACK_timezone_aware(lane):
    """The failure this prevents is a comparison of two naive values from different
    zones: it does not raise, and it answers wrongly."""
    with store.lane_session("wiki") as session:
        entity = _entity(session)
        rev.capture_baseline(session, entity, revision_ref="1", text="a\n", revised_at=T0)
    store.dispose_all()
    with store.lane_session("wiki") as session:
        row = rev.baseline_for(session, 1)
        assert row.revised_at.tzinfo is not None, "a naive datetime came back out of the lane"
        assert row.revised_at == T0
