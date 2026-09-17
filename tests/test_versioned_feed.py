"""The change feed: the cursor, dedup, and gap detection that must not invent a gap.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``detect_gap`` is PURE, so this file drives every combination of (stored token,
resumed-from, reported gap) directly rather than inferring the decision from a
store's behaviour. That matters because the two failure directions are equally
dishonest and only one of them is loud: a MISSED gap publishes a corpus with holes
as complete, and an INVENTED gap manufactures a hole out of somebody else's
bookkeeping. Both get tests.

The negative space is the point of the file. Three inputs LOOK like gaps and are
not — an empty batch, a batch of nothing but duplicates, and a jump in the source's
own change ids — and each has a named test, because an over-eager detector reads as
conservative while quietly filling the Living sources view with holes that never
happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.versioned import store
from src.versioned.feed import (
    ChangeBatch,
    FeedChange,
    GapReport,
    close_gap,
    cursor_row,
    detect_gap,
    open_gaps,
    record_batch,
    stored_token,
)

T0 = datetime(2026, 5, 1, tzinfo=UTC)
FEED = "recentchanges:oo"


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A plaintext lane file. The at-rest state is S2's subject, not this file's."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.create_lane("wiki")
    try:
        yield
    finally:
        store.dispose_all()


def _change(ref: str, *, days: int = 1, kind: str = "edit", ext: str | None = None):
    return FeedChange(
        change_ref=ref,
        change_kind=kind,
        external_id=ext,
        occurred_at=T0 + timedelta(days=days),
        cursor_token=ref,
    )


# --------------------------------------------------------------------------- #
# detect_gap — the pure decision, every combination.
# --------------------------------------------------------------------------- #
def test_a_reported_gap_is_believed_verbatim():
    """When the source (or the caller) says a stretch was skipped, we record THAT.

    Including the reason: ``retention``, ``budget``, ``disconnect`` and ``refused``
    lead a reader to different conclusions, so the detector must not re-derive one.
    """
    said = GapReport(reason="retention", from_token="a", to_token="b")
    out = detect_gap(stored_token="a", batch=ChangeBatch(feed=FEED, gap=said))
    assert out is said


def test_a_first_read_is_not_a_gap():
    """Nothing stored means nothing was skipped.

    The inverse would put every fresh install's lane permanently in a state it could
    never leave — a hole behind a feed that has not started.
    """
    batch = ChangeBatch(feed=FEED, changes=(_change("c1"),), next_token="t1")
    assert detect_gap(stored_token=None, batch=batch) is None


def test_a_cold_start_against_a_LIVE_cursor_IS_a_gap():
    """Resuming from nowhere while holding a position skips everything in between.

    Nothing else in the system notices this: the cursor simply advances, the batch
    looks healthy, and the changes between the two tokens are never mentioned again.
    """
    batch = ChangeBatch(feed=FEED, changes=(_change("c9"),), next_token="t9", resumed_from=None)
    out = detect_gap(stored_token="t3", batch=batch)
    assert out is not None
    assert (out.reason, out.from_token, out.to_token) == ("disconnect", "t3", "t9")


def test_resuming_from_somewhere_ELSE_is_a_gap_with_both_ends_named():
    """A read that began at a point we did not leave off at.

    Direction is deliberately NOT claimed: the token is opaque, so "ahead" and
    "behind" are not knowable here, and a reason that guessed would be a fabricated
    mechanism inside an honesty record.
    """
    batch = ChangeBatch(feed=FEED, changes=(), next_token="t9", resumed_from="t7")
    out = detect_gap(stored_token="t3", batch=batch)
    assert out is not None
    assert (out.from_token, out.to_token) == ("t3", "t7")


def test_a_correct_resume_is_NOT_a_gap():
    batch = ChangeBatch(feed=FEED, changes=(_change("c4"),), next_token="t4", resumed_from="t3")
    assert detect_gap(stored_token="t3", batch=batch) is None


def test_an_EMPTY_batch_on_a_correct_resume_is_NOT_a_gap():
    """A quiet feed is the common case and the honest reading. THE NEGATIVE SPACE."""
    batch = ChangeBatch(feed=FEED, changes=(), next_token="t3", resumed_from="t3")
    assert detect_gap(stored_token="t3", batch=batch) is None


def test_a_JUMP_IN_CHANGE_IDS_IS_NOT_A_GAP():
    """THE NEGATIVE SPACE THAT MATTERS MOST.

    Sources skip their own ids for their own reasons — a deleted revision, a
    suppressed edit, a sharded counter. A substrate that read a numeric hole as a
    coverage hole would manufacture gaps out of someone else's bookkeeping, on every
    pass, for ever. Ids 1, 2 and 900 in one batch must produce nothing.
    """
    batch = ChangeBatch(
        feed=FEED,
        changes=(_change("c1", days=1), _change("c2", days=2), _change("c900", days=3)),
        next_token="t900",
        resumed_from="t0",
    )
    assert detect_gap(stored_token="t0", batch=batch) is None


# --------------------------------------------------------------------------- #
# record_batch — dedup, ordering, and what the cursor may claim.
# --------------------------------------------------------------------------- #
def test_dedup_is_on_the_sources_own_id_so_a_replay_is_free(lane):
    """A reconnect that replays costs a few ignored rows and nothing else."""
    with store.lane_session("wiki") as session:
        first = record_batch(
            session,
            ChangeBatch(feed=FEED, changes=(_change("c1"), _change("c2")), next_token="t2"),
        )
    assert (first.recorded, first.duplicates) == (2, 0)

    with store.lane_session("wiki") as session:
        again = record_batch(
            session,
            ChangeBatch(
                feed=FEED,
                changes=(_change("c2"), _change("c3", days=3)),
                next_token="t3",
                resumed_from="t2",
            ),
        )
    assert (again.recorded, again.duplicates) == (1, 1)


def test_a_ref_repeated_INSIDE_one_batch_does_not_roll_the_batch_back(lane):
    """A source that repeats a ref in one delivery must not cost the whole batch.

    Without in-batch dedup this hits the unique constraint at flush time and takes
    every sibling change with it — the recorded "a bulk statement makes every row
    share one fate" shape.
    """
    with store.lane_session("wiki") as session:
        out = record_batch(
            session,
            ChangeBatch(
                feed=FEED,
                changes=(_change("c1"), _change("c1"), _change("c2", days=2)),
                next_token="t2",
            ),
        )
    assert (out.recorded, out.duplicates) == (2, 1)


def test_an_unknown_change_kind_is_stored_verbatim_and_COUNTED(lane):
    """Mapping an unrecognised kind onto the nearest known one invents a fact."""
    from src.versioned.models import VersionedChange

    with store.lane_session("wiki") as session:
        out = record_batch(
            session,
            ChangeBatch(feed=FEED, changes=(_change("c1", kind="frobnicate"),), next_token="t1"),
        )
        assert out.unknown_kind == 1
        assert session.query(VersionedChange).one().change_kind == "frobnicate"


def test_contiguity_does_NOT_advance_through_a_gap(lane):
    """The load-bearing separation: ``token`` moves, ``contiguous_through`` does not.

    Conflating them is how a gap disappears — an advanced cursor past a refused
    resume looks exactly like a healthy one, and every freshness reading downstream
    then describes a holed corpus as complete.
    """
    with store.lane_session("wiki") as session:
        record_batch(session, ChangeBatch(feed=FEED, changes=(_change("c1"),), next_token="t1"))
    with store.lane_session("wiki") as session:
        before = cursor_row(session, FEED).contiguous_through

    with store.lane_session("wiki") as session:
        out = record_batch(
            session,
            ChangeBatch(
                feed=FEED,
                changes=(_change("c9", days=9),),
                next_token="t9",
                resumed_from=None,  # cold start against a live cursor
            ),
        )
        assert out.gap_recorded is True
        assert out.contiguous_advanced is False
        row = cursor_row(session, FEED)
        assert row.token == "t9", "the cursor must still follow the feed"
        assert row.contiguous_through == before, "contiguity advanced through a gap"


def test_an_empty_batch_does_not_stamp_a_contiguity_claim(lane):
    """A quiet feed tells us nothing new about coverage.

    Stamping the clock here would claim we had seen everything up to now, which
    nobody said — the fabricated-completeness direction of the same defect.
    """
    with store.lane_session("wiki") as session:
        record_batch(session, ChangeBatch(feed=FEED, changes=(), next_token="t0"))
        assert cursor_row(session, FEED).contiguous_through is None


def test_contiguity_only_ever_moves_FORWARD(lane):
    """A backfill of older changes must not REDUCE a claim already earned."""
    with store.lane_session("wiki") as session:
        record_batch(
            session, ChangeBatch(feed=FEED, changes=(_change("c9", days=9),), next_token="t9")
        )
        high = cursor_row(session, FEED).contiguous_through
    with store.lane_session("wiki") as session:
        record_batch(
            session,
            ChangeBatch(
                feed=FEED,
                changes=(_change("c2", days=2),),
                next_token="t9",
                resumed_from="t9",
            ),
        )
        assert cursor_row(session, FEED).contiguous_through == high


def test_a_gap_and_its_cursor_land_in_ONE_transaction_or_neither_does(lane):
    """The gap and the cursor advance are ATOMIC. Named for what it proves.

    An earlier draft of this test was called "a gap is written BEFORE the cursor
    advances" — which it does not show. Both statements are inside one transaction,
    so a rollback takes both whatever order they were issued in, and a verdict must
    map to the bar it actually tested. What IS proved here is the property that
    makes the order safe to reason about at all: there is no observable state in
    which one landed and the other did not. (The ORDER still matters for a torn
    write below the transaction, and is stated in ``record_batch``'s own docstring;
    nothing in a single-file SQLite test can exhibit it.)
    """
    from src.versioned.models import VersionedGap

    with pytest.raises(RuntimeError, match="deliberate"), store.lane_session("wiki") as session:
        record_batch(session, ChangeBatch(feed=FEED, changes=(_change("c1"),), next_token="t1"))
        record_batch(
            session,
            ChangeBatch(feed=FEED, changes=(_change("c9", days=9),), next_token="t9"),
        )
        raise RuntimeError("deliberate: roll the pass back mid-flight")

    with store.lane_session("wiki") as session:
        assert session.query(VersionedGap).count() == 0
        assert stored_token(session, FEED) is None


def test_a_gap_is_closed_only_by_a_caller_that_refilled_it(lane):
    """No path closes a gap because time passed or later changes arrived."""
    with store.lane_session("wiki") as session:
        record_batch(session, ChangeBatch(feed=FEED, changes=(_change("c1"),), next_token="t1"))
    with store.lane_session("wiki") as session:
        record_batch(
            session,
            ChangeBatch(
                feed=FEED, changes=(_change("c9", days=9),), next_token="t9", resumed_from=None
            ),
        )
    with store.lane_session("wiki") as session:
        gaps = open_gaps(session, FEED)
        assert len(gaps) == 1
        assert close_gap(session, gaps[0].id) is True
        assert close_gap(session, gaps[0].id) is False, "a closed gap closed twice"
    with store.lane_session("wiki") as session:
        assert open_gaps(session, FEED) == []


def test_later_changes_do_NOT_close_an_open_gap(lane):
    """The negative-space twin of the test above, and the one that matters.

    A gap that ages out silently is the whole failure this table exists to prevent.
    """
    with store.lane_session("wiki") as session:
        record_batch(session, ChangeBatch(feed=FEED, changes=(_change("c1"),), next_token="t1"))
    with store.lane_session("wiki") as session:
        record_batch(
            session,
            ChangeBatch(
                feed=FEED, changes=(_change("c9", days=9),), next_token="t9", resumed_from=None
            ),
        )
    for day in (10, 11, 12):
        with store.lane_session("wiki") as session:
            record_batch(
                session,
                ChangeBatch(
                    feed=FEED,
                    changes=(_change(f"c{day}", days=day),),
                    next_token=f"t{day}",
                    resumed_from=f"t{day - 1}" if day > 10 else "t9",
                ),
            )
    with store.lane_session("wiki") as session:
        still = open_gaps(session, FEED)
    assert len(still) >= 1, "an open gap was closed by nothing but the passage of changes"
