"""The SSE wire format, hand-rolled and pure. No sockets, no session, no I/O.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1015 = a rules that SSE is "hand-rolled over the guarded session (no new client
library)". This module is the hand-rolled half, and it is deliberately the half with
NO network in it: it turns an iterable of decoded lines into events and nothing else.

WHY THE PARSER IS A SEPARATE MODULE FROM THE CLIENT. Every defect an SSE client can
have that a test can actually reach lives in the parsing: a multi-line ``data`` that
loses its newlines, a comment mistaken for a field, an ``id`` that is remembered
after the event that carried it was discarded, a ``retry`` that is not a number. A
parser over an iterable can be driven with a list of strings, so those cases are
ordinary unit tests rather than a socket fixture. The client above it then has one
job — keep a connection alive and hand its lines here — and that job is what the
fixture and the kill-switch tests exercise.

THE FORMAT, as the WHATWG HTML standard's "server-sent events" section defines it
and as this module implements it:

* A line is a field when it contains a colon. The field name is everything before
  the FIRST colon; the value is everything after it, with ONE leading space removed
  (one, not all — a value may legitimately begin with a space).
* A line that STARTS with a colon is a comment and is ignored. Wikimedia's stream
  sends these as keep-alives, so treating one as data would inject an empty event
  into the corpus every few seconds.
* A line with no colon at all is a field with that name and an EMPTY value.
* ``data`` ACCUMULATES: several ``data:`` lines in one event join with ``"\\n"``.
* A blank line DISPATCHES the accumulated event.
* ``id`` is remembered as the LAST EVENT ID across events — including for an event
  that carries no ``data`` and is therefore never dispatched. That is what makes a
  resume correct after a keep-alive-only stretch.
* ``id`` containing a NUL is IGNORED per the standard (and would break a header).
* ``retry`` sets the reconnection time when its value is all digits; anything else
  is ignored rather than guessed at.
* An event with no ``data`` at all is NOT dispatched.

WHAT THIS MODULE REFUSES TO DO. It does not parse JSON, does not know what a
Wikimedia change looks like, and does not decide what to keep. A parser that also
filtered would make "the stream sent nothing" and "we dropped everything" the same
observation, and those two lead to opposite decisions.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

#: The default reconnection delay when the server has never sent a ``retry``. Three
#: seconds is the WHATWG-suggested order and Wikimedia's own stream sends its own
#: value early, so this is what covers the first few seconds of a first connection.
DEFAULT_RETRY_MS: int = 3000


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One dispatched event.

    ``event`` is the type the server named, defaulting to ``"message"`` exactly as
    the standard requires — a server that names no type is not sending an untyped
    event, it is sending a ``message``.
    """

    data: str
    event: str = "message"
    last_event_id: str | None = None


@dataclass(slots=True)
class SseParser:
    """Line-by-line SSE state, kept explicitly so a reconnect can resume from it.

    STATEFUL ON PURPOSE. ``last_event_id`` and ``retry_ms`` outlive any single
    event — that is the whole mechanism by which a dropped connection resumes where
    it stopped — so they belong to an object the caller keeps, never to a function
    call that forgets them.
    """

    #: The most recent ``id:`` the server sent, whatever became of its event. Sent
    #: back as the ``Last-Event-ID`` header on the next connection.
    last_event_id: str | None = None
    #: The server's requested reconnection delay, in milliseconds.
    retry_ms: int = DEFAULT_RETRY_MS
    #: Lines that were not a comment, not a known field and not blank. COUNTED
    #: rather than dropped silently: a stream that starts sending a field we do not
    #: understand is a fact about the service, and a counter is how it surfaces.
    unknown_fields: int = 0
    #: Events the server sent with an id we had to ignore (it contained a NUL).
    refused_ids: int = 0

    _data: list[str] = field(default_factory=list)
    _event_type: str = ""
    _saw_field: bool = False

    def feed(self, lines: Iterable[str]) -> Iterator[SseEvent]:
        """Turn decoded lines into events. Yields nothing for a keep-alive.

        ``lines`` are WITHOUT their terminators. A ``None`` line — which
        ``requests``' ``iter_lines`` emits for a keep-alive newline — is treated as
        a blank line, because that is exactly what it is on the wire.
        """
        for raw in lines:
            line = "" if raw is None else raw
            # A BOM may only appear once, at the very start of the stream. Stripping
            # it per line is harmless and covers a reconnect whose server re-sends it.
            if line.startswith("﻿"):
                line = line[1:]
            if line == "":
                event = self._dispatch()
                if event is not None:
                    yield event
                continue
            if line.startswith(":"):
                # A comment. Wikimedia keep-alives arrive as bare ``:`` lines; they
                # must NOT dispatch, must NOT clear the buffer, and must NOT count
                # as an unknown field.
                continue
            name, sep, value = line.partition(":")
            if not sep:
                # No colon anywhere: the whole line is a field name with an empty
                # value. The standard says so explicitly.
                name, value = line, ""
            elif value.startswith(" "):
                value = value[1:]
            self._field(name, value)

    # -- internals ---------------------------------------------------------- #
    def _field(self, name: str, value: str) -> None:
        if name == "data":
            self._data.append(value)
            self._saw_field = True
        elif name == "event":
            self._event_type = value
            self._saw_field = True
        elif name == "id":
            if "\x00" in value:
                # The standard ignores an id containing a NUL, and so must we for a
                # second reason of our own: it becomes an HTTP header on reconnect.
                self.refused_ids += 1
            else:
                self.last_event_id = value
            self._saw_field = True
        elif name == "retry":
            if value.isdigit():
                self.retry_ms = int(value)
            self._saw_field = True
        else:
            self.unknown_fields += 1

    def _dispatch(self) -> SseEvent | None:
        """Emit the buffered event, or ``None`` when there is nothing to emit."""
        data = self._data
        event_type = self._event_type or "message"
        self._data = []
        self._event_type = ""
        had_field = self._saw_field
        self._saw_field = False
        if not data:
            # No ``data`` means no event — but an ``id`` or ``retry`` that arrived
            # with it HAS already been kept, which is the point of storing them on
            # the parser rather than on the event.
            _ = had_field
            return None
        return SseEvent(
            data="\n".join(data),
            event=event_type,
            last_event_id=self.last_event_id,
        )
