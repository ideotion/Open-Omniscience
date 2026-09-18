"""Replay a recorded SSE file as if it were EventStreams. Zero sockets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a: the lane's pipeline must run end to end in CI *without a socket*. This is
the session that makes that true for the STREAM half, as ``wiki_fixture`` already
does for the Action API half. It answers ``get(..., stream=True)`` with an object
whose ``iter_lines`` walks ``tests/fixtures/wiki/recentchange_stream.sse``.

IT CAN CUT THE CONNECTION, AND THAT IS THE POINT. A replay that always delivers the
whole file proves nothing about the property this lane's correctness rests on:
resuming. ``cut_after`` ends the response mid-file, exactly as a dropped connection
does; the client then reconnects, and this session ASSERTS that it was handed a
``Last-Event-ID`` and serves the remainder from that id. A fixture that ignored the
header would let a client that never sends one pass the test.

IT LIVES IN ``src/`` for the same reason ``wiki_fixture`` does: a driver that several
test files and a script all need is not a test, and copying it into each of them is
how fifteen hand-rolled copies of one path came to exist once before.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "wiki" / "recentchange_stream.sse"
)


class UnexpectedFixtureRequest(RuntimeError):
    """Something asked this session for a URL or a verb it does not serve.

    LOUD rather than an empty stream: an empty response reads as "the wiki was quiet",
    which is the fabricated-quiet result a test would believe.
    """


class FixtureResponse:
    """A ``requests.Response``-shaped reader over a slice of the recorded file."""

    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = False, **_kw) -> Iterator[str]:
        yield from self._lines

    def close(self) -> None:
        self.closed = True


class FixtureStreamSession:
    """A session that replays the recorded stream, optionally cutting it short.

    ``cut_after`` is the number of LINES the first response delivers before ending.
    ``None`` delivers everything in one response.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        url: str | None = None,
        cut_after: int | None = None,
    ) -> None:
        self._path = path or FIXTURE_PATH
        text = self._path.read_text(encoding="utf-8")
        # ``splitlines()`` on the raw text gives exactly what ``iter_lines`` gives a
        # real client: terminators removed, blank lines preserved as "".
        self._lines = text.split("\n")
        if self._lines and self._lines[-1] == "":
            self._lines.pop()
        self._url = url
        self._cut_after = cut_after
        self.headers: dict[str, str] = {}
        #: Every request's headers, in order. A test reads this to assert the resume
        #: header was actually sent rather than trusting that it was.
        self.requests: list[dict[str, str]] = []
        self._served = 0

    def get(self, url, headers=None, stream=False, timeout=None, **_kw) -> FixtureResponse:
        if self._url is not None and url != self._url:
            raise UnexpectedFixtureRequest(f"this fixture serves {self._url!r}, not {url!r}")
        if not stream:
            raise UnexpectedFixtureRequest(
                "EventStreams must be read with stream=True; a buffered read would "
                "materialise a firehose"
            )
        sent = dict(headers or {})
        self.requests.append(sent)
        first = self._served == 0
        self._served += 1
        if first and self._cut_after is not None:
            return FixtureResponse(self._lines[: self._cut_after])
        if first:
            return FixtureResponse(list(self._lines))
        resume = sent.get("Last-Event-ID")
        if resume is None:
            raise UnexpectedFixtureRequest(
                "a reconnect arrived with no Last-Event-ID: the stream would silently "
                "replay from the service's own head and lose everything in between"
            )
        return FixtureResponse(self._after(resume))

    def _after(self, last_event_id: str) -> list[str]:
        """Every line after the event carrying ``last_event_id``.

        Matched on the LITERAL id line, because the id is opaque to this app: a
        fixture that parsed it would be asserting a format the service is free to
        change, which is the assumption this lane has already been corrected for.
        """
        needle = f"id: {last_event_id}"
        for i, line in enumerate(self._lines):
            if line == needle:
                # Resume AFTER that event's blank-line dispatch.
                j = i
                while j < len(self._lines) and self._lines[j] != "":
                    j += 1
                return self._lines[j + 1 :]
        # An id we do not hold. The service would answer from its own head; saying so
        # out loud is better than pretending we resumed.
        raise UnexpectedFixtureRequest(
            f"the recorded stream does not contain the id {last_event_id!r}; a real "
            "service would restart from its head and the lane would have a gap"
        )
