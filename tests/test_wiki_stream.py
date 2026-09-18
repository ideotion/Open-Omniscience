"""The EventStreams client: the filters, the resume, and the refusals.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q108 = a (the stream), Q703 = a (namespace 0, no redirects), Q727 = a (a gap the
lane PUBLISHES rather than infers away), and the airplane-mode non-negotiable.

THE CASE THIS FILE EXISTS FOR IS THE LAST ONE. ``GuardedSession`` consults the kill
switch inside ``request()``; for every other caller in this tree that is exactly
right, because their requests are short. A stream's ``request()`` returns in
milliseconds and then delivers bytes for hours, so an operator who engages airplane
mode mid-stream would keep receiving and storing edits from a connection whose
permission was withdrawn. ``test_the_kill_switch_stops_a_stream_ALREADY_RUNNING``
drives exactly that, through the REAL kill switch rather than a monkeypatched
binding — the recorded lesson that patching this module's own name makes the two
gates disagree and silently stops testing the refusal.
"""

from __future__ import annotations

import json

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch
from src.testing.wiki_stream_fixture import FixtureStreamSession, UnexpectedFixtureRequest
from src.versioned.adapters.base import ReadBudget
from src.versioned.models import VersionedChange, VersionedCursor
from src.wiki.lane import CURSOR_TOKEN_MAX, StreamBuffer, WikiStreamAdapter, change_token
from src.wiki.stream import (
    ARTICLE_NAMESPACE,
    StreamChange,
    StreamStopped,
    WikiEventStream,
    is_redirect_event,
    parse_change,
)

FIXTURE_EDITION = "oo"


# --------------------------------------------------------------------------- #
# Helpers: a session that serves lines we write here, for the cases the recorded
# fixture deliberately does not contain.
# --------------------------------------------------------------------------- #
class _Response:
    def __init__(self, lines, *, raises=None):
        self._lines = lines
        self._raises = raises
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False, **_kw):
        yield from self._lines
        if self._raises is not None:
            raise self._raises

    def close(self):
        self.closed = True


class _Session:
    """Serves a scripted list of responses, recording every request's headers."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def get(self, url, headers=None, stream=False, timeout=None, **_kw):
        self.requests.append(dict(headers or {}))
        if not self._responses:
            raise AssertionError("the client asked for more connections than were scripted")
        return self._responses.pop(0)


def _body(**over):
    base = {
        "wiki": f"{FIXTURE_EDITION}wiki",
        "namespace": ARTICLE_NAMESPACE,
        "page_id": 101,
        "title": "Fixture Alpha",
        "type": "edit",
        "page_is_redirect": False,
        "revision": {"new": 5, "old": 4},
        "length": {"new": 120, "old": 100},
        "timestamp": 1772366400,
        "user": "FixtureEditorOne",
        "bot": False,
        "minor": False,
        "comment": "c",
    }
    base.update(over)
    return json.dumps(base)


def _event_lines(body, event_id="1"):
    return [f"id: {event_id}", "event: message", f"data: {body}", ""]


def _stream(session, **kw):
    return WikiEventStream(session=session, editions=(FIXTURE_EDITION,), **kw)


# --------------------------------------------------------------------------- #
# The recorded fixture, end to end.
# --------------------------------------------------------------------------- #
def test_the_recorded_fixture_replays_with_the_counters_it_was_built_to_produce():
    """The whole file, one connection. Every number here is a WRITTEN-IN case."""
    session = FixtureStreamSession()
    stream = _stream(session)
    kept: list[StreamChange] = []
    stream.run(kept.append, max_connections=1)
    counters = stream.counters.as_dict()
    assert counters["events_kept"] == len(kept)
    assert counters["events_other_edition"] == 1, "the zzwiki event must be filtered"
    assert counters["events_other_namespace"] == 1, "Category: is namespace 14 (Q703)"
    assert counters["events_redirect"] == 1, "Q703 excludes redirects specifically"
    assert counters["events_malformed"] == 1, "the truncated body, counted not crashed"
    assert counters["per_edition"] == {FIXTURE_EDITION: counters["events_kept"]}


def test_a_multi_line_data_payload_is_rejoined_before_it_is_parsed():
    """Written into the fixture as a JSON body split across two ``data:`` lines."""
    session = FixtureStreamSession()
    stream = _stream(session)
    kept: list[StreamChange] = []
    stream.run(kept.append, max_connections=1)
    assert any(c.revid == 9100 for c in kept), (
        "the split payload never reassembled; a parser that joined without the "
        "newline, or not at all, would report it as malformed instead"
    )


def test_a_MALFORMED_event_is_counted_and_neither_stored_nor_fatal():
    session = _Session([_Response(_event_lines("{not json") + _event_lines(_body(), "2"))])
    stream = _stream(session)
    kept: list[StreamChange] = []
    stream.run(kept.append, max_connections=1)
    assert stream.counters.events_malformed == 1
    assert len(kept) == 1, "the event AFTER the malformed one must still arrive"


def test_an_event_missing_wiki_or_title_cannot_be_attributed_and_is_refused():
    assert parse_change(json.dumps({"namespace": 0, "page_id": 1})) is None
    assert parse_change(json.dumps({"wiki": "oowiki", "namespace": 0})) is None
    assert parse_change("[]") is None


# --------------------------------------------------------------------------- #
# Q703: what is kept.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("over", "counter"),
    [
        ({"wiki": "zzwiki"}, "events_other_edition"),
        ({"namespace": 14}, "events_other_namespace"),
        ({"page_is_redirect": True}, "events_redirect"),
    ],
)
def test_Q703_keeps_namespace_zero_non_redirects_of_watched_editions_only(over, counter):
    session = _Session([_Response(_event_lines(_body(**over)))])
    stream = _stream(session)
    kept = []
    stream.run(kept.append, max_connections=1)
    assert kept == []
    assert getattr(stream.counters, counter) == 1


def test_a_disambiguation_or_list_page_is_KEPT_because_Q703_includes_them():
    """Negative space for the filter: it must not over-reach."""
    session = _Session([_Response(_event_lines(_body(title="List of fixtures")))])
    stream = _stream(session)
    kept = []
    stream.run(kept.append, max_connections=1)
    assert len(kept) == 1


def test_an_ABSENT_redirect_flag_does_not_exclude_the_page():
    """Excluding on a field the service did not send would silently narrow the corpus."""
    body = json.loads(_body())
    body.pop("page_is_redirect")
    assert is_redirect_event(json.dumps(body)) is False


# --------------------------------------------------------------------------- #
# Resume.
# --------------------------------------------------------------------------- #
def test_a_reconnect_sends_the_LAST_EVENT_ID_it_actually_received():
    session = _Session(
        [
            _Response(_event_lines(_body(), "abc"), raises=OSError("connection reset")),
            _Response(_event_lines(_body(), "def")),
        ]
    )
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=2)
    assert "Last-Event-ID" not in session.requests[0], "a first connection resumes from nothing"
    assert session.requests[1]["Last-Event-ID"] == "abc"


def test_a_stored_cursor_is_sent_on_the_FIRST_connection():
    session = _Session([_Response(_event_lines(_body()))])
    stream = _stream(session)
    stream.run(lambda _c: None, max_connections=1, resume_from="stored-token")
    assert session.requests[0]["Last-Event-ID"] == "stored-token"


def test_a_cut_stream_resumes_from_where_it_stopped_and_loses_nothing():
    """The fixture session REFUSES a reconnect that arrives with no resume header."""
    whole = FixtureStreamSession()
    all_kept: list[StreamChange] = []
    _stream(whole).run(all_kept.append, max_connections=1)

    cut = FixtureStreamSession(cut_after=12)
    resumed: list[StreamChange] = []
    _stream(cut, sleep=lambda _s: None).run(resumed.append, max_connections=2)

    assert [c.revid for c in resumed] == [c.revid for c in all_kept], (
        "a cut-and-resumed run must see exactly the changes an uninterrupted one saw"
    )
    assert len(cut.requests) == 2
    assert "Last-Event-ID" in cut.requests[1]


def test_a_reconnect_WITHOUT_a_resume_header_is_refused_by_the_fixture_itself():
    """Proves the test above is testing something: a client that forgot the header fails."""
    cut = FixtureStreamSession(cut_after=12)
    cut.get("u", headers={}, stream=True)
    with pytest.raises(UnexpectedFixtureRequest, match="no Last-Event-ID"):
        cut.get("u", headers={}, stream=True)


def test_a_transport_failure_is_COUNTED_and_retried_never_silently_ended():
    session = _Session(
        [
            _Response([], raises=OSError("reset")),
            _Response(_event_lines(_body())),
        ]
    )
    stream = _stream(session, sleep=lambda _s: None)
    kept = []
    stream.run(kept.append, max_connections=2)
    assert stream.counters.transport_errors == 1
    assert stream.counters.connections == 2
    assert len(kept) == 1


def test_the_backoff_starts_from_the_SERVERS_own_retry_and_is_capped():
    session = _Session([_Response([])])
    stream = _stream(session, max_backoff_s=10.0)
    stream.parser.retry_ms = 4000
    first = stream._next_backoff(0.0)
    assert first == pytest.approx(4.0)
    assert stream._next_backoff(8.0) == pytest.approx(10.0), "capped, never unbounded"


# --------------------------------------------------------------------------- #
# The refusals.
# --------------------------------------------------------------------------- #
def test_the_kill_switch_refuses_a_stream_BEFORE_it_opens_and_names_itself():
    session = _Session([])
    stream = _stream(session)
    activate_kill_switch()
    try:
        with pytest.raises(StreamStopped, match="kill switch"):
            stream.run(lambda _c: None, max_connections=1)
    finally:
        clear_kill_switch()
    assert session.requests == [], "nothing may reach the session while offline"


def test_the_kill_switch_stops_a_stream_ALREADY_RUNNING_mid_connection():
    """THE CASE THIS MODULE EXISTS FOR. See the module docstring.

    The real switch, not a monkeypatched binding: patching this module's own name
    makes the app-level and socket-level gates disagree and stops testing the refusal.
    """
    lines = _event_lines(_body(), "1") + _event_lines(_body(), "2") + _event_lines(_body(), "3")
    session = _Session([_Response(lines)])
    stream = _stream(session)
    seen: list[StreamChange] = []

    def on_change(change):
        seen.append(change)
        activate_kill_switch()  # the operator hits airplane mode, mid-stream

    try:
        with pytest.raises(StreamStopped, match="kill switch"):
            stream.run(on_change, max_connections=1)
    finally:
        clear_kill_switch()
    assert len(seen) == 1, (
        "the stream kept delivering after the kill switch engaged; a connection "
        "already open is exactly what the socket guard cannot close"
    )


def test_the_refusal_says_it_was_THIS_APP_not_the_service():
    """Invariant #14e's corollary: a kill-switch refusal must name itself.

    The recorded breach reported airplane mode as "size check failed" and pointed an
    operator at somebody else's server for their own setting.
    """
    stream = _stream(_Session([]))
    activate_kill_switch()
    try:
        with pytest.raises(StreamStopped) as caught:
            stream.run(lambda _c: None, max_connections=1)
    finally:
        clear_kill_switch()
    message = str(caught.value)
    assert "airplane mode" in message
    assert "not by Wikimedia" in message


def test_a_caller_stop_RETURNS_rather_than_raising_a_refusal():
    """A requested stop and a withheld permission must not share one signal.

    Driven mid-connection (the stop goes true after the first event), because a stop
    checked only at the top of the loop would never exercise the unwinding path.
    """
    session = _Session([_Response(_event_lines(_body(), "1") + _event_lines(_body(), "2"))])
    stream = _stream(session)
    seen: list[StreamChange] = []
    stop = {"now": False}

    def on_change(change):
        seen.append(change)
        stop["now"] = True

    counters = stream.run(on_change, should_stop=lambda: stop["now"], max_connections=1)
    assert counters is stream.counters
    assert len(seen) == 1
    assert stream.counters.transport_errors == 0


def test_a_stop_that_is_already_true_opens_no_connection_at_all():
    session = _Session([])
    stream = _stream(session)
    stream.run(lambda _c: None, should_stop=lambda: True, max_connections=1)
    assert session.requests == []


def test_the_stream_is_read_with_stream_True_so_a_firehose_never_becomes_a_figure():
    """The fixture session refuses a buffered read, which is what pins this."""
    session = FixtureStreamSession()
    with pytest.raises(UnexpectedFixtureRequest, match="stream=True"):
        session.get("u", headers={}, stream=False)


# --------------------------------------------------------------------------- #
# The buffer between the firehose and the substrate.
# --------------------------------------------------------------------------- #
def _change(n):
    return StreamChange(
        wiki=FIXTURE_EDITION, page_id=n, title=f"P{n}", namespace=0, change_kind="edit",
        revid=n, parent_revid=None, timestamp_ms=1, user="u", bot=False, minor=False,
        comment=None, length_new=1, length_old=0, log_type=None, log_action=None,
        event_id=f"e{n}",
    )


def test_an_OVERFLOWING_buffer_publishes_a_gap_instead_of_losing_changes_in_silence():
    buf = StreamBuffer(maxlen=3)
    for i in range(6):
        buf.push(_change(i))
    assert len(buf) == 3
    gap = buf.take_gap()
    assert gap is not None and gap.reason == "budget"
    assert gap.from_token is not None, "the hole must name where it started"


def test_a_gap_is_reported_exactly_ONCE_then_cleared():
    buf = StreamBuffer(maxlen=1)
    buf.push(_change(1))
    buf.push(_change(2))
    assert buf.take_gap() is not None
    assert buf.take_gap() is None, "a gap re-reported every pass would read as an ongoing loss"


def test_a_buffer_that_never_overflowed_reports_NO_gap():
    buf = StreamBuffer(maxlen=10)
    buf.push(_change(1))
    assert buf.take_gap() is None


def test_a_cursor_token_too_long_for_its_column_is_REFUSED_not_truncated():
    """A truncated resume token looks like a position and is not one."""
    long_id = "x" * (CURSOR_TOKEN_MAX + 1)
    change = StreamChange(
        wiki=FIXTURE_EDITION, page_id=1, title="T", namespace=0, change_kind="edit",
        revid=1, parent_revid=None, timestamp_ms=1, user=None, bot=False, minor=False,
        comment=None, length_new=None, length_old=None, log_type=None, log_action=None,
        event_id=long_id,
    )
    assert change_token(change) is None


def test_the_refusal_threshold_EQUALS_the_column_it_protects():
    assert VersionedCursor.__table__.c.token.type.length == CURSOR_TOKEN_MAX
    assert VersionedChange.__table__.c.cursor_token.type.length == CURSOR_TOKEN_MAX


def test_every_change_ref_fits_the_column_that_stores_it():
    session = FixtureStreamSession()
    adapter = WikiStreamAdapter(client=object(), editions=(FIXTURE_EDITION,))
    _stream(session).run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    batch = adapter.read_changes(feed=f"stream:{FIXTURE_EDITION}", since=None, budget=ReadBudget())
    width = VersionedChange.__table__.c.change_ref.type.length
    assert batch.changes
    for change in batch.changes:
        assert len(change.change_ref) <= width


def test_two_LOG_events_on_one_page_never_share_a_change_ref():
    """The measured defect: a delete and a move both carried revid 0 and deduped to one."""
    session = FixtureStreamSession()
    adapter = WikiStreamAdapter(client=object(), editions=(FIXTURE_EDITION,))
    _stream(session).run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    batch = adapter.read_changes(feed=f"stream:{FIXTURE_EDITION}", since=None, budget=ReadBudget())
    kinds = {c.change_kind for c in batch.changes}
    assert {"delete", "move"} <= kinds, "the fixture carries one of each (Q713)"
    refs = [c.change_ref for c in batch.changes]
    assert len(set(refs)) == len(refs)


def test_the_cursor_advances_past_events_we_deliberately_FILTERED():
    """Otherwise a quiet edition's cursor falls out of retention and fabricates a gap."""
    adapter = WikiStreamAdapter(client=object(), editions=(FIXTURE_EDITION,))
    adapter.note_position(FIXTURE_EDITION, "position-after-filtered-events")
    batch = adapter.read_changes(feed=f"stream:{FIXTURE_EDITION}", since="old", budget=ReadBudget())
    assert batch.changes == ()
    assert batch.next_token == "position-after-filtered-events"


def test_an_empty_drain_with_no_position_keeps_the_cursor_rather_than_resetting_it():
    """``None`` would read to the substrate as a deliberate cold start."""
    adapter = WikiStreamAdapter(client=object(), editions=(FIXTURE_EDITION,))
    batch = adapter.read_changes(feed=f"stream:{FIXTURE_EDITION}", since="keep-me", budget=ReadBudget())
    assert batch.next_token == "keep-me"


# --------------------------------------------------------------------------- #
# The instrument must not freeze. (The recorded rate-sampler lesson, same shape.)
# --------------------------------------------------------------------------- #
def test_idle_seconds_is_None_before_anything_has_ever_arrived():
    """"Never" and "just now" are different facts; a 0.0 would conflate them."""
    from src.wiki.stream import StreamCounters

    assert StreamCounters().idle_seconds() is None


def test_idle_seconds_GROWS_during_a_stall_with_no_new_event_to_update_it():
    """A figure written only when an event arrives reads 0.0 for as long as the
    stream is stuck — which is the one moment an operator is looking at it."""
    from src.wiki.stream import StreamCounters

    now = [100.0]
    counters = StreamCounters(clock=lambda: now[0])
    counters.last_event_at = 100.0
    assert counters.idle_seconds() == 0.0
    now[0] = 460.0
    assert counters.idle_seconds() == pytest.approx(360.0)


def test_consecutive_failures_resets_on_a_connection_that_DELIVERS_something():
    """A total count cannot tell a dead service from one blip on the first day."""
    session = _Session(
        [
            _Response([], raises=OSError("reset")),
            _Response([], raises=OSError("reset")),
            _Response(_event_lines(_body())),
        ]
    )
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=3)
    assert stream.counters.transport_errors == 2
    assert stream.counters.consecutive_failures == 0


def test_consecutive_failures_CLIMBS_while_nothing_is_delivered():
    session = _Session([_Response([], raises=OSError("reset")) for _ in range(3)])
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=3)
    assert stream.counters.consecutive_failures == 3


def test_the_counters_payload_carries_no_key_with_a_banned_no_score_substring():
    """The recorded trap: ``"degraded"`` contains ``"grade"``. Walk your own keys."""
    from src.wiki.stream import StreamCounters

    banned = ("score", "ranking", "rating", "grade")
    for key in StreamCounters().as_dict():
        assert not any(b in key.lower() for b in banned), key


def test_a_change_ref_NEVER_derives_from_a_revid_of_zero():
    """A surviving mutant found this gap, and the gap is the point.

    The fixture used to emit ``revision.new = 0`` on its log events, which is how the
    collision was discovered — two log events sharing ``oo:r0`` and one being deduped
    away. The fixture was then corrected to omit ``revision`` entirely, as a real
    service does. That correction left the GUARD untested: with the fixture no longer
    producing a zero, removing ``> 0`` from ``_change_ref`` changed nothing anywhere
    and every test stayed green.

    So this drives the guard DIRECTLY. A service that does send a zero — or a parser
    change that turns an absent field into one — must not collapse two changes into
    one, and only an assertion at this level can say so.
    """
    from src.wiki.lane import _change_ref

    def _log(revid, event_id):
        return StreamChange(
            wiki=FIXTURE_EDITION, page_id=1, title="T", namespace=0, change_kind="log",
            revid=revid, parent_revid=None, timestamp_ms=1, user=None, bot=False,
            minor=False, comment=None, length_new=None, length_old=None,
            log_type="delete", log_action="delete", event_id=event_id,
        )

    deleted = _change_ref(_log(0, "e-delete"))
    moved = _change_ref(_log(0, "e-move"))
    assert deleted != moved, "two log events with a zero revid collapsed into one ref"
    assert "r0" not in deleted, "a revision id of 0 is not a revision id"


def test_a_change_ref_DOES_use_a_real_revid_when_there_is_one():
    """The negative space's twin: the guard must not reject a legitimate id."""
    from src.wiki.lane import _change_ref

    change = StreamChange(
        wiki=FIXTURE_EDITION, page_id=1, title="T", namespace=0, change_kind="edit",
        revid=4242, parent_revid=None, timestamp_ms=1, user=None, bot=False, minor=False,
        comment=None, length_new=None, length_old=None, log_type=None, log_action=None,
        event_id="e1",
    )
    assert _change_ref(change) == f"{FIXTURE_EDITION}:r4242"
