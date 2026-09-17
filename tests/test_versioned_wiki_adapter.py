"""The wiki lane adapter's CURSOR, and the identifier it is built from.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT THIS FILE WAS WRITTEN FROM. The adapter's first version resumed on the
revision id alone, which assumes a source's ids rise with time — an unverifiable
claim about somebody else's counter. The cost was measured, not imagined: three of
the fixture's five pages silently stopped receiving changes, every counter read
zero, and nothing anywhere reported a fault. The cursor is now a
``"<iso8601>|<revid>"`` token mirroring MediaWiki's own ``rccontinue`` shape, and
these tests pin the properties that made the failure silent.

``make_token`` / ``parse_token`` are pure, so they are exercised with no lane and no
client at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.testing.wiki_fixture import FixtureNetworkAttempt, FixtureWikiClient
from src.versioned.adapters.base import ReadBudget
from src.versioned.adapters.wiki import (
    WikiLaneAdapter,
    external_id_for,
    make_token,
    parse_token,
    split_external_id,
)

WHEN = datetime(2026, 3, 4, 12, 30, tzinfo=UTC)


def test_a_token_ROUND_TRIPS_through_its_own_parser():
    token = make_token(WHEN, 4242)
    parsed = parse_token(token)
    assert parsed is not None
    when, revid = parsed
    assert when == WHEN
    assert revid == 4242


def test_the_token_ORDERS_BY_TIME_even_when_the_revision_ids_do_not():
    """The whole reason the cursor is not a bare revid.

    A source's id counter is the source's business: ids may be per-wiki, reused after
    a merge, or simply not monotonic in time. Ordering on one is an assumption about
    somebody else's database, and when it is wrong the lane goes quiet rather than
    loud.
    """
    older = parse_token(make_token(WHEN, 9999))
    newer = parse_token(make_token(WHEN + timedelta(days=1), 1))
    assert older is not None and newer is not None
    assert newer[0] > older[0], "the later change did not sort later"


def test_an_UNREADABLE_token_is_REFUSED_and_never_guessed_at():
    """``None`` means "treat this as no cursor", which re-reads a covered stretch.

    The alternative — inventing a position, e.g. "now" — SKIPS everything between the
    real position and the guess, permanently and silently. Re-reading is free (the
    feed dedups on the source's own change id); skipping is not recoverable.
    """
    for bad in (None, "", "|", "|123", "not-a-timestamp|1", "   "):
        assert parse_token(bad) is None, f"{bad!r} was parsed into a cursor position"


def test_a_token_whose_TIME_IS_UNKNOWN_cannot_become_a_cursor_position():
    """``make_token(None, revid)`` is deliberately unparseable.

    A change the source gave no timestamp for is a real thing; letting it BECOME the
    resume point is not, because the next pass would have no idea where to start.
    """
    assert parse_token(make_token(None, 55)) is None


def test_a_token_with_no_zone_is_read_as_UTC_rather_than_as_local_time():
    """A naive timestamp compared against an aware one raises; compared against
    another naive one from a different zone, it silently answers wrongly."""
    parsed = parse_token("2026-03-04T12:30:00|7")
    assert parsed is not None
    assert parsed[0] == WHEN
    assert parsed[0].tzinfo is not None


def test_a_MISSING_revid_half_does_not_lose_the_timestamp():
    """The time half is what orders the feed; the id half is a tie-break.

    Refusing the whole token because the id is missing would throw away a usable
    position over the less important half of it.
    """
    parsed = parse_token("2026-03-04T12:30:00+00:00|")
    assert parsed is not None
    assert parsed[0] == WHEN
    assert parsed[1] == 0


# ------------------------------------------------------------------- identifiers


def test_the_external_id_splits_on_the_FIRST_colon_so_titles_may_contain_colons():
    """``en:Wikipedia:Village pump`` is an ordinary page title.

    Splitting on the last colon, or refusing the title, would drop every namespaced
    page on every wiki — silently, as a page that simply never appears.
    """
    external_id = external_id_for("en", "Wikipedia:Village pump")
    assert external_id == "en:Wikipedia:Village pump"
    assert split_external_id(external_id) == ("en", "Wikipedia:Village pump")


def test_a_round_trip_survives_a_title_that_is_ONLY_punctuation():
    for title in ("A", "A:B:C", "—", "Ünicode: ok"):
        assert split_external_id(external_id_for("oo", title)) == ("oo", title)


# ----------------------------------------------------------------- the fixture


def test_the_adapter_REQUIRES_its_editions_rather_than_defaulting_to_one():
    """A default edition is a fetch nobody asked for.

    ``editions`` is keyword-only and required, so an adapter can never be constructed
    that quietly reads ``en`` — the largest wiki in the world — because a caller
    forgot an argument.
    """
    with pytest.raises(TypeError):
        WikiLaneAdapter(client=FixtureWikiClient())  # type: ignore[call-arg]


def test_the_adapter_lists_ONE_FEED_PER_EDITION_and_nothing_else():
    adapter = WikiLaneAdapter(client=FixtureWikiClient(), editions=("oo", "zz"))
    assert adapter.feeds() == ("recentchanges:oo", "recentchanges:zz")


def test_the_fixture_client_REFUSES_a_call_it_cannot_serve_OFFLINE():
    """The fixture must fail LOUDLY rather than answer emptily.

    An empty answer reads as "that wiki had no changes" — a fabricated quiet result a
    test would believe — and the same call in production would be a real fetch.
    """
    client = FixtureWikiClient()
    with pytest.raises(FixtureNetworkAttempt):
        client.fetch_recentchanges("en")
    with pytest.raises(FixtureNetworkAttempt):
        client.fetch_compare("oo", 1, 2)


def test_the_fixture_counts_every_call_it_serves():
    """The counters are what let a budget test assert REQUESTS rather than results."""
    client = FixtureWikiClient()
    assert client.calls == {}
    client.fetch_recentchanges("oo")
    client.fetch_current_text("oo", "Fixture Alpha")
    assert client.calls["fetch_recentchanges"] == 1
    assert client.calls["fetch_current_text"] == 1


# ------------------------------------------------- what the cursor must not drop


class _RowClient:
    """A client that serves prepared recentchanges rows, in the REAL client's shape.

    ``src/wiki/mediawiki.py::parse_recentchanges`` hands back a ``datetime`` under
    ``timestamp``, not a string — and a first draft of these tests passed ISO strings,
    which ``_aware`` correctly rejects, so every row lost its timestamp and the
    comparison under test never ran at all. The tests passed and proved nothing. The
    shape is matched here deliberately.
    """

    def __init__(self, rows):
        self.rows = rows
        self.limits: list[int] = []

    def fetch_recentchanges(self, wiki, *, namespace=0, limit=50):
        self.limits.append(limit)
        return self.rows[:limit]


def _rc(revid, when, title="Page"):
    return {"revid": revid, "timestamp": when, "title": title, "type": "edit"}


def test_a_SAME_INSTANT_change_with_a_LOWER_id_is_NOT_dropped():
    """The cursor compares TIME, never the id it also carries.

    An earlier version treated ``(time, revid)`` as an ordering and skipped anything
    ``<=`` the mark. A genuinely new change at the mark's own instant with a lower id
    was then skipped, never recorded, produced no gap, and could never resurface — the
    mark only moves forward. This is the assertion that separates the two designs.
    """
    rows = [_rc(101, WHEN), _rc(100, WHEN), _rc(99, WHEN)]
    adapter = WikiLaneAdapter(client=_RowClient(rows), editions=("oo",))
    batch = adapter.read_changes(
        feed="recentchanges:oo", since=make_token(WHEN, 100), budget=ReadBudget()
    )
    kept = {c.change_ref for c in batch.changes}
    assert "oo:99" in kept, f"a same-instant change with a lower id was dropped: {kept}"
    # The already-held ones come back too and are deduped downstream, which is the
    # trade: a handful of re-offered rows can never lose one.
    assert kept == {"oo:99", "oo:100", "oo:101"}, kept


def test_a_change_STRICTLY_OLDER_than_the_cursor_is_still_skipped():
    """The other half: the comparison must still do its job, or it is not a cursor."""
    older = WHEN - timedelta(days=1)
    rows = [_rc(200, WHEN + timedelta(days=1)), _rc(1, older)]
    adapter = WikiLaneAdapter(client=_RowClient(rows), editions=("oo",))
    batch = adapter.read_changes(
        feed="recentchanges:oo", since=make_token(WHEN, 100), budget=ReadBudget()
    )
    assert {c.change_ref for c in batch.changes} == {"oo:200"}


def test_an_UNREADABLE_stored_token_is_reported_as_a_GAP():
    """Both of this lane's gap layers go quiet on this input at once.

    The retention check is gated on a parseable mark, and ``detect_gap``'s remaining
    cases compare ``resumed_from`` against the stored token — which for this adapter are
    the same string by construction. So a legacy or hand-edited token produced NO signal
    anywhere and the lane resumed as though nothing were missing.
    """
    rows = [_rc(5000, WHEN), _rc(4999, WHEN - timedelta(days=1))]
    adapter = WikiLaneAdapter(client=_RowClient(rows), editions=("oo",))
    batch = adapter.read_changes(feed="recentchanges:oo", since="4242", budget=ReadBudget())
    assert batch.gap is not None, "an unreadable cursor produced no signal at all"
    assert batch.gap.reason == "disconnect", batch.gap
    assert batch.gap.from_token == "4242", "the unreadable token is not named"
    assert batch.gap.to_token, "the far end of the gap is not named"


def test_a_COLD_START_is_not_reported_as_a_gap():
    """Anti-vacuity for the test above: no cursor at all is not the same as a broken one."""
    rows = [_rc(5000, WHEN)]
    adapter = WikiLaneAdapter(client=_RowClient(rows), editions=("oo",))
    batch = adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget())
    assert batch.gap is None


def test_the_read_BUDGET_sets_the_window_the_client_is_asked_for():
    """``max_requests`` was accepted and ignored — the literal 50 stood where it belonged.

    It matters past the wasted knob: the window size is the input to the retention-gap
    arithmetic, so a caller widening the window after downtime (to avoid a FALSE gap) or
    narrowing it for cost silently got neither.
    """
    client = _RowClient([_rc(i, WHEN) for i in range(600)])
    adapter = WikiLaneAdapter(client=client, editions=("oo",))
    adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget())
    adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget(max_requests=200))
    adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget(max_requests=1))
    adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget(max_requests=99999))
    assert client.limits == [50, 200, 1, 500], client.limits


def test_an_UNDATED_change_carries_no_unreadable_cursor_token():
    """``make_token(None, revid)`` is ``"|<revid>"`` — truthy AND unparseable.

    Stored, it defeats its own fallback: ``change.cursor_token or batch.next_token``
    never reaches the batch's real token, and the row keeps a position nothing can read.
    """
    rows = [_rc(7, None), _rc(8, WHEN)]
    adapter = WikiLaneAdapter(client=_RowClient(rows), editions=("oo",))
    batch = adapter.read_changes(feed="recentchanges:oo", since=None, budget=ReadBudget())
    undated = next(c for c in batch.changes if c.change_ref == "oo:7")
    assert undated.occurred_at is None
    assert undated.cursor_token is None, f"stored an unreadable position: {undated.cursor_token!r}"
    dated = next(c for c in batch.changes if c.change_ref == "oo:8")
    assert parse_token(dated.cursor_token) is not None
