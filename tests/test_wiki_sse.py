"""The SSE wire format, driven line by line. No sockets, no session, no fixtures.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1015 = a rules the SSE client hand-rolled. A hand-rolled parser of somebody else's
wire format is exactly the kind of code that passes a happy-path test and then loses
data in the field, so most of what is asserted here is NEGATIVE SPACE: what must NOT
be dispatched, what must NOT be remembered, what must NOT be guessed.

Every case below is a line shape the WHATWG "server-sent events" section defines, and
each one is a way a naive implementation goes wrong:

* a comment dispatched as an empty event (Wikimedia sends keep-alives constantly);
* multi-line ``data`` joined without its newline (silently corrupts a payload);
* ``id`` forgotten when its event carried no ``data`` (a resume that skips);
* a value's leading space eaten twice, or not at all;
* a line with no colon treated as malformed rather than as an empty-valued field;
* ``retry`` guessed at when it is not a number.
"""

from __future__ import annotations

from src.wiki.sse import DEFAULT_RETRY_MS, SseEvent, SseParser


def _events(lines):
    return list(SseParser().feed(lines))


def test_a_comment_NEVER_dispatches_an_event():
    """The keep-alive case. Wikimedia sends these every few seconds."""
    assert _events([":", ":ok", ": a longer comment", ""]) == []


def test_a_keepalive_between_two_events_does_not_split_or_merge_them():
    events = _events(["data: one", "", ":", "", "data: two", ""])
    assert [e.data for e in events] == ["one", "two"]


def test_several_data_lines_join_with_a_NEWLINE_not_a_space_and_not_nothing():
    events = _events(["data: a", "data: b", "data: c", ""])
    assert [e.data for e in events] == ["a\nb\nc"]


def test_exactly_ONE_leading_space_is_removed_from_a_value():
    """Two spaces means the value genuinely starts with a space."""
    events = _events(["data:  padded", ""])
    assert [e.data for e in events] == [" padded"]


def test_a_value_with_no_space_after_the_colon_is_kept_whole():
    assert [e.data for e in _events(["data:x", ""])] == ["x"]


def test_a_line_with_NO_colon_is_a_field_with_an_empty_value():
    """``data`` alone is a data line whose value is the empty string."""
    assert [e.data for e in _events(["data", "data: second", ""])] == ["\nsecond"]


def test_an_event_with_no_data_is_NOT_dispatched_however_many_other_fields_it_had():
    parser = SseParser()
    assert list(parser.feed(["event: ping", "id: 7", "retry: 5000", ""])) == []


def test_the_id_of_an_UNDISPATCHED_event_is_still_remembered():
    """The resume-correctness case, and the reason ``id`` lives on the parser.

    A stretch of id-only events (a service marking position with no payload) must
    still move the resume point, or a reconnect replays from before them.
    """
    parser = SseParser()
    list(parser.feed(["id: 100", "", "id: 101", ""]))
    assert parser.last_event_id == "101"


def test_an_id_containing_a_NUL_is_REFUSED_and_counted_never_stored():
    """The standard ignores it; it would also be an invalid HTTP header on resume."""
    parser = SseParser()
    list(parser.feed(["id: good", "", "id: ba\x00d", "data: x", ""]))
    assert parser.last_event_id == "good"
    assert parser.refused_ids == 1


def test_the_event_TYPE_defaults_to_message_and_is_reset_between_events():
    events = _events(["event: custom", "data: a", "", "data: b", ""])
    assert [(e.event, e.data) for e in events] == [("custom", "a"), ("message", "b")]


def test_retry_is_taken_only_when_it_is_all_digits():
    parser = SseParser()
    list(parser.feed(["retry: 9000", ""]))
    assert parser.retry_ms == 9000
    list(parser.feed(["retry: soon", ""]))
    assert parser.retry_ms == 9000, "a non-numeric retry must be ignored, never guessed at"


def test_the_default_retry_is_used_until_the_server_names_one():
    assert SseParser().retry_ms == DEFAULT_RETRY_MS


def test_an_unknown_field_is_COUNTED_rather_than_dropped_in_silence():
    parser = SseParser()
    list(parser.feed(["ping: 1", "data: x", ""]))
    assert parser.unknown_fields == 1


def test_a_leading_BOM_is_stripped_so_the_first_field_still_parses():
    assert [e.data for e in _events(["﻿data: first", ""])] == ["first"]


def test_a_None_line_is_treated_as_a_blank_line():
    """``requests``' ``iter_lines`` yields ``None`` for a keep-alive newline."""
    assert [e.data for e in _events(["data: x", None, "data: y", None])] == ["x", "y"]


def test_an_event_still_buffered_when_the_lines_run_out_is_NOT_dispatched():
    """A cut connection must not deliver half an event as though it were whole."""
    assert _events(["data: {\"a\":"]) == []


def test_the_parser_carries_its_id_ACROSS_a_feed_call_so_a_reconnect_resumes():
    """``feed`` is called once per connection; the position outlives the call."""
    parser = SseParser()
    list(parser.feed(["id: 5", "data: a", ""]))
    list(parser.feed(["data: b", ""]))
    events = list(parser.feed(["data: c", ""]))
    assert parser.last_event_id == "5"
    assert events == [SseEvent(data="c", event="message", last_event_id="5")]
