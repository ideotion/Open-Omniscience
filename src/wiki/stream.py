"""The EventStreams client: one long-lived SSE connection per run, resumed and honest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q108 = a: "0.4: the stream (metadata for every edit, all twelve editions) + HOT full
text". This module is the stream. It holds one connection to Wikimedia EventStreams,
decodes it with :mod:`src.wiki.sse`, filters it to the editions and namespace the
rulings name, and hands each surviving change to a callback. It stores nothing and
decides no tier — the substrate above it does that.

THE KILL SWITCH IS CHECKED ON EVERY READ, NOT ONLY AT CONNECT, AND THAT IS THE WHOLE
REASON THIS CLASS EXISTS RATHER THAN A LOOP AT A CALL SITE. ``GuardedSession``
consults the kill switch inside ``request()`` — the verb — which for every other
caller in this tree is exactly right, because their requests are short. A stream is
not: ``request()`` returns in milliseconds and the connection then delivers bytes for
hours. An operator who engages airplane mode during a stream would, with a naive
loop, keep receiving and storing edits from a connection whose permission was
withdrawn — the app's most visible promise, broken by the one network path shaped
differently from all the others. So the read loop re-checks before every event it
acts on and raises :class:`StreamStopped` naming the kill switch, per invariant
#14e's corollary that "a refusal BY THE KILL SWITCH must be named as such wherever it
can surface".

The socket-level airplane guard (``src/ingest/airplane.py``) would refuse the next
CONNECT, so a reconnect could never re-establish. It cannot tear down a socket that
is already open, which is precisely the hole this loop closes from above.

WHAT IT DOES NOT DO, and why each absence is deliberate:

* **It builds no session.** The caller passes one. In production that is
  ``guarded_session(user_agent=WIKI_USER_AGENT)`` — the kill switch, the
  protected-mode proxy (so Q722/Q1014's "never a silent Tor -> clearnet downgrade"
  holds by construction) and the honest bot UA. In CI it is a fixture that reads a
  file, which is what lets the whole path run under the airplane socket guard with
  zero name resolutions.
* **It never widens what it was asked for.** The editions are a required argument.
  A default of "all twelve" would make a first run's blast radius a property of a
  constant instead of the operator's choice in the wizard (Q725).
* **It does not retry forever in silence.** Every reconnect is counted and the
  reason recorded; a caller reading :class:`StreamCounters` can tell a healthy
  long-lived connection from one that is flapping, which a "it is still running"
  boolean cannot.
* **It fabricates no heartbeat.** If the server sends nothing, the counters say the
  connection has been idle for N seconds. They never say "no changes" — those are
  different facts, and only the server knows which one is true.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from src.ingest import kill_switch_active
from src.wiki.sse import SseEvent, SseParser

_LOG = logging.getLogger("wiki.stream")

#: The stream this lane reads. SEARCH-VERIFIED 2026-09-12 in the roadmap intake
#: (docs/design/ROADMAP_INTAKE_2026-09-12_BETA_PATHWAY.md:419) and registered in
#: docs/SECURITY.md + src/static/net-hosts.js in the same diff that added it
#: (Q1001). NOT reachable from this sandbox: every Wikimedia host answers 000 here,
#: so the URL is carried as the documented constant it is and the operator's own
#: >= 72 h run is what confirms it against the live service (row V).
EVENTSTREAMS_URL: str = "https://stream.wikimedia.org/v2/stream/recentchange"

#: The event type EventStreams names for a recent change.
RECENTCHANGE_EVENT: str = "message"

#: Namespace 0 only (Q703 = a: "Namespace 0 (articles), excluding redirects,
#: including disambiguation and list pages"). The redirect exclusion is a separate
#: test below, because a redirect lives in namespace 0 too.
ARTICLE_NAMESPACE: int = 0

#: How long one connection may sit with no bytes before we treat it as dead and
#: reconnect. EventStreams sends keep-alive comments, so silence for this long is a
#: broken connection rather than a quiet wiki -- but the counters record it as a
#: TIMEOUT, never as "no changes".
READ_TIMEOUT_S: float = 60.0

#: The ceiling on exponential reconnect backoff. A stream that cannot connect must
#: not hammer the service, and must not go so quiet that an operator watching the
#: counters thinks it gave up.
MAX_BACKOFF_S: float = 300.0


#: Every stream currently inside its read loop, by the editions it is reading.
#:
#: WHY A REGISTRY AND NOT A BOOLEAN SOMEWHERE ELSE. A surface has to be able to answer
#: "is this lane actually collecting?", and the only honest source for that is the
#: loop itself. The alternative -- a constant in the API layer saying "no collector
#: yet" -- is true today and becomes a LIE the day someone wires one and does not
#: think to update it, which is the worse direction: an operator told nothing is
#: happening while their machine streams. Registering here makes the answer true by
#: construction in both directions.
#:
#: Module-level and guarded by a lock because the collector will run on its own
#: thread while an HTTP handler reads this on another.
_LIVE: dict[int, tuple[str, ...]] = {}
_LIVE_LOCK = threading.Lock()


def live_streams() -> tuple[tuple[str, ...], ...]:
    """The editions each currently-running stream is reading. Empty when none is."""
    with _LIVE_LOCK:
        return tuple(_LIVE.values())


class StreamStopped(RuntimeError):
    """The stream was REFUSED. Raised only by the kill switch.

    A distinct type from a transport error because the two lead to opposite
    decisions: a transport error is retried, and a refusal is not.

    It is deliberately NOT what a caller's own ``should_stop`` produces. An operator
    asking the lane to stop is an ordinary end and :meth:`WikiEventStream.run`
    RETURNS its counters; airplane mode is a refusal, and a caller that treated the
    two the same would log "stream ended" for a withheld permission. One signal for
    two meanings is how a refusal becomes invisible.
    """


class _CallerStop(RuntimeError):
    """Internal: unwinds the read loop when ``should_stop`` goes true mid-connection.

    Private because it never crosses ``run``'s boundary — it is caught there and
    turned into a normal return, so the public contract stays "a stop returns, a
    refusal raises".
    """


@dataclass(slots=True)
class StreamCounters:
    """What the run can honestly say about itself.

    Every field here is something this module MEASURED. There is no field for a rate,
    an ETA or a completion percentage, because this module cannot know the size of
    what it is streaming — the recorded rule that an unmeasurable quantity is ABSENT
    with a reason rather than published as a zero.
    """

    #: Events the parser dispatched, before any filtering.
    events_seen: int = 0
    #: Events that survived the edition + namespace + redirect filters.
    events_kept: int = 0
    #: Events dropped because their ``data`` was not JSON, or was JSON of the wrong
    #: shape. COUNTED, never silent: a stream whose payload changed shape would
    #: otherwise look exactly like a quiet wiki.
    events_malformed: int = 0
    #: Events for an edition this run does not watch. Not a defect — the stream
    #: carries every wiki there is — but the ratio is how an operator sees that the
    #: filter is doing what they chose.
    events_other_edition: int = 0
    #: Events in a namespace other than 0 (Q703).
    events_other_namespace: int = 0
    #: Namespace-0 events that are redirects (Q703 excludes them).
    events_redirect: int = 0
    #: Connections opened, including the first. ``reconnects`` is this minus one.
    connections: int = 0
    #: Connections that ended on a read timeout rather than an error or a stop.
    read_timeouts: int = 0
    #: Transport failures. Each is logged with its exception type.
    transport_errors: int = 0
    #: Failures since the last connection that delivered anything. The recorded rule
    #: is that a worker whose per-item step degrades instead of raising "will finish
    #: complete on a dead backend" — here the equivalent is a stream that reconnects
    #: forever against a service that is gone. A total count cannot tell that from a
    #: run that had one blip on its first day; a consecutive count can, and it is
    #: what the diagnostics member reports.
    consecutive_failures: int = 0
    #: WHY the stream is waiting, as ``Type: message`` of the latest transport failure,
    #: cleared by the next event that arrives -- so it is set exactly while
    #: ``consecutive_failures`` is. Q1014: a lane whose transport is unavailable WAITS
    #: with a named reason (S04-08's S5). Before, a stream held off by a refused or dead
    #: proxy was registered as live and reported nothing, so the lane read "running"
    #: while every connection failed; the reason was only in the log.
    last_failure: str | None = None
    #: The id we would resume from right now.
    last_event_id: str | None = None
    #: When the last event of ANY kind arrived, on the monotonic clock. ``None``
    #: until one does. Stored as an INSTANT rather than as an elapsed figure: see
    #: :meth:`idle_seconds`.
    last_event_at: float | None = None
    #: The clock this reads. Injectable so a test can drive a stall without waiting
    #: for one.
    clock: Callable[[], float] = time.monotonic
    #: Per-edition kept counts, for the diagnostics member the >= 72 h run reads.
    per_edition: dict[str, int] = field(default_factory=dict)

    def idle_seconds(self) -> float | None:
        """Seconds since the last event, computed AGAINST A FRESH CLOCK at read time.

        THE RECORDED DEFECT THIS AVOIDS, in a different subsystem and the same shape:
        a rate sampler that only updated its window when new bytes arrived "keeps
        reporting the last healthy rate forever once a transfer stalls". An idle
        figure written when an event arrives has exactly that property — it is 0.0
        for as long as the stream is stuck, which is the one moment an operator is
        looking at it. Reading the clock here means a stall shows as a growing number
        by construction.

        ``None`` until the first event. "Never" and "just now" are different facts,
        and a 0.0 would make a stream that has never delivered anything look healthy.
        """
        if self.last_event_at is None:
            return None
        return max(0.0, self.clock() - self.last_event_at)

    def as_dict(self) -> dict[str, Any]:
        """A payload with no key containing a banned no-score substring.

        Walked deliberately rather than assumed: the recorded lesson is that
        ``"degraded"`` contains ``"grade"``, so a status here would be a VALUE and
        never a key. Every key below is a count or an id.
        """
        return {
            "events_seen": self.events_seen,
            "events_kept": self.events_kept,
            "events_malformed": self.events_malformed,
            "events_other_edition": self.events_other_edition,
            "events_other_namespace": self.events_other_namespace,
            "events_redirect": self.events_redirect,
            "connections": self.connections,
            "reconnects": max(0, self.connections - 1),
            "read_timeouts": self.read_timeouts,
            "transport_errors": self.transport_errors,
            "last_event_id": self.last_event_id,
            "idle_seconds": self.idle_seconds(),
            "consecutive_failures": self.consecutive_failures,
            "last_failure": self.last_failure,
            "per_edition": dict(self.per_edition),
        }


@dataclass(frozen=True, slots=True)
class StreamChange:
    """One recentchange event, in this lane's vocabulary rather than Wikimedia's.

    ``page_id`` is the reason this lane can key on Q715's ``(wiki, pageid)`` at all:
    the stream carries it on every event, so identity survives a page MOVE without a
    second request. Absent where the event genuinely omits it (some log events do) —
    ``None``, never 0, because 0 is a page id.
    """

    wiki: str
    page_id: int | None
    title: str
    namespace: int
    change_kind: str
    revid: int | None
    parent_revid: int | None
    timestamp_ms: int | None
    user: str | None
    bot: bool
    minor: bool
    comment: str | None
    length_new: int | None
    length_old: int | None
    log_type: str | None
    log_action: str | None
    event_id: str | None
    #: The event's own ``page_is_redirect``. CARRIED rather than re-derived: asking
    #: for it meant a THIRD ``json.loads`` of the same bytes, and on a firehose read
    #: for days that is not a rounding error. ``False`` when the field is absent,
    #: which is the honest direction -- excluding a page on a field the service did
    #: not send would silently narrow the corpus.
    is_redirect: bool = False

    @property
    def delta_bytes(self) -> int | None:
        """New minus old, or ``None`` when either side is absent.

        A page CREATION has no old length; reporting its delta as its full size
        would be a different claim from the one the event makes, and reporting 0
        would be false. ``None`` says what is true: there is no previous length.
        """
        if self.length_new is None or self.length_old is None:
            return None
        return self.length_new - self.length_old


def parse_change(payload: str) -> StreamChange | None:
    """Decode one event body. ``None`` for anything that is not a usable change.

    Returns ``None`` rather than raising because a malformed event is an ordinary
    fact about a public firehose, not an error condition for the run — the caller
    counts it. What is NOT tolerated is a silently WRONG change: every field is read
    by name and a missing one becomes ``None``, so no default ever stands in for a
    value the service did not send.
    """
    try:
        raw = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    wiki = raw.get("wiki")
    title = raw.get("title")
    if not isinstance(wiki, str) or not isinstance(title, str):
        # Without these two the event cannot be attributed to a page at all.
        return None
    namespace = raw.get("namespace")
    raw_revision = raw.get("revision")
    revision: dict = raw_revision if isinstance(raw_revision, dict) else {}
    raw_length = raw.get("length")
    length: dict = raw_length if isinstance(raw_length, dict) else {}
    return StreamChange(
        wiki=wiki,
        page_id=_as_int(raw.get("page_id")),
        title=title,
        namespace=namespace if isinstance(namespace, int) else -1,
        change_kind=str(raw.get("type") or "edit"),
        revid=_as_int(revision.get("new")),
        parent_revid=_as_int(revision.get("old")),
        timestamp_ms=_timestamp_ms(raw),
        user=raw.get("user") if isinstance(raw.get("user"), str) else None,
        bot=bool(raw.get("bot")),
        minor=bool(raw.get("minor")),
        comment=raw.get("comment") if isinstance(raw.get("comment"), str) else None,
        length_new=_as_int(length.get("new")),
        length_old=_as_int(length.get("old")),
        log_type=raw.get("log_type") if isinstance(raw.get("log_type"), str) else None,
        log_action=raw.get("log_action") if isinstance(raw.get("log_action"), str) else None,
        event_id=None,
        is_redirect=bool(raw.get("page_is_redirect")),
    )


def is_redirect_event(payload: str) -> bool:
    """True when the event says the page is a redirect (Q703 excludes them).

    Read from the event's own ``page_is_redirect`` field. When the field is ABSENT
    this returns False — the honest direction, because excluding a page on a field
    the service did not send would silently narrow the corpus, and the recorded
    ruling on that trade ("emphasis is not exclusion") points the same way.
    """
    try:
        raw = json.loads(payload)
    except (ValueError, TypeError):
        return False
    return bool(isinstance(raw, dict) and raw.get("page_is_redirect"))


class WikiEventStream:
    """One resumable SSE connection over an injected session."""

    def __init__(
        self,
        *,
        session: Any,
        editions: tuple[str, ...],
        url: str = EVENTSTREAMS_URL,
        read_timeout_s: float = READ_TIMEOUT_S,
        max_backoff_s: float = MAX_BACKOFF_S,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not editions:
            raise ValueError("a wiki event stream needs at least one edition")
        self._session = session
        # The stream's ``wiki`` field is a DATABASE name (``enwiki``), not a
        # language code. Built once, here, so no comparison anywhere else has to
        # remember the suffix.
        self._editions = tuple(editions)
        self._dbnames = {f"{code}wiki": code for code in editions}
        self._url = url
        self._read_timeout_s = read_timeout_s
        self._max_backoff_s = max_backoff_s
        self._sleep = sleep
        self._monotonic = monotonic
        self.parser = SseParser()
        self.counters = StreamCounters(clock=monotonic)

    # -- the loop ----------------------------------------------------------- #
    def run(
        self,
        on_change: Callable[[StreamChange], None],
        *,
        should_stop: Callable[[], bool] | None = None,
        max_connections: int | None = None,
        resume_from: str | None = None,
        on_position: Callable[[str | None, str | None], None] | None = None,
    ) -> StreamCounters:
        """Stream until ``should_stop`` says so, the kill switch trips, or an end.

        ``resume_from`` is a stored ``Last-Event-ID``. It is handed to the parser as
        its starting state rather than to the request directly, so that a run which
        reconnects several times keeps advancing from the same one place — the
        recorded rule that a resumable job's position is captured once and persisted,
        never recomputed per invocation.
        """
        if resume_from:
            self.parser.last_event_id = resume_from
            self.counters.last_event_id = resume_from
        with _LIVE_LOCK:
            _LIVE[id(self)] = self._editions
        try:
            return self._run(on_change, should_stop, max_connections, on_position)
        finally:
            # A ``finally`` is not a cleanup GUARANTEE -- a SIGKILL or an OOM skips it
            # -- but this registry lives in the process that would die with it, so
            # there is nothing to leak across a restart. What it does cover is every
            # ordinary exit: a refusal, a caller stop, an exception, a return.
            with _LIVE_LOCK:
                _LIVE.pop(id(self), None)

    def _run(
        self,
        on_change: Callable[[StreamChange], None],
        should_stop: Callable[[], bool] | None,
        max_connections: int | None,
        on_position: Callable[[str | None, str | None], None] | None,
    ) -> StreamCounters:
        backoff = 0.0
        while True:
            if should_stop is not None and should_stop():
                return self.counters
            self._refuse_if_offline("opening the Wikipedia change stream")
            if max_connections is not None and self.counters.connections >= max_connections:
                return self.counters
            self.counters.connections += 1
            try:
                self._one_connection(on_change, should_stop, on_position)
                backoff = 0.0
            except _CallerStop:
                # An ordinary, requested end: the counters are the answer.
                return self.counters
            except StreamStopped:
                raise
            except Exception as exc:  # noqa: BLE001 - every transport fault is a retry
                self.counters.transport_errors += 1
                self.counters.consecutive_failures += 1
                self.counters.last_failure = f"{type(exc).__name__}: {exc}"[:300]
                _LOG.warning("wiki stream connection failed: %s: %s", type(exc).__name__, exc)
                backoff = self._next_backoff(backoff)
            if should_stop is not None and should_stop():
                return self.counters
            if max_connections is not None and self.counters.connections >= max_connections:
                return self.counters
            if backoff:
                self._wait(backoff, should_stop)

    #: The longest a stop or airplane mode waits to be noticed during a backoff.
    WAIT_SLICE_S: float = 1.0

    def _wait(self, seconds: float, should_stop: Callable[[], bool] | None) -> None:
        """Sleep a backoff in slices, ending early on a stop or on airplane mode.

        One uninterrupted ``sleep`` of up to :data:`MAX_BACKOFF_S` kept a stream that was
        waiting behind a dead proxy registered as LIVE for as long as five minutes after
        the operator stopped the lane or engaged airplane mode, so the lane status read
        "running" in airplane mode (found by S04-08's S5 walk, 2026-09-25). Now the loop
        re-checks within a slice, and airplane mode is then refused BY NAME at the top of
        the next iteration rather than waited out.
        """
        remaining = seconds
        while remaining > 0:
            step = min(self.WAIT_SLICE_S, remaining)
            self._sleep(step)
            remaining -= step
            if (should_stop is not None and should_stop()) or kill_switch_active():
                return

    def _one_connection(
        self,
        on_change: Callable[[StreamChange], None],
        should_stop: Callable[[], bool] | None,
        on_position: Callable[[str | None, str | None], None] | None = None,
    ) -> None:
        headers = {"Accept": "text/event-stream"}
        if self.parser.last_event_id:
            headers["Last-Event-ID"] = self.parser.last_event_id
        # ``stream=True`` is what makes this a stream rather than a download: the
        # body is not materialised, so a firehose never becomes a memory figure.
        response = self._session.get(
            self._url,
            headers=headers,
            stream=True,
            timeout=(self._read_timeout_s, self._read_timeout_s),
        )
        try:
            raise_for_status = getattr(response, "raise_for_status", None)
            if callable(raise_for_status):
                raise_for_status()
            self._consume(response, on_change, should_stop, on_position)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _consume(
        self,
        response: Any,
        on_change: Callable[[StreamChange], None],
        should_stop: Callable[[], bool] | None,
        on_position: Callable[[str | None, str | None], None] | None = None,
    ) -> None:
        last_seen = self._monotonic()
        for event in self._events(response):
            # THE MID-STREAM CHECK. Before this event is acted on, not after: an
            # operator who engaged airplane mode a moment ago must not have one more
            # edit stored because it was already decoded.
            self._refuse_if_offline("reading the Wikipedia change stream")
            if should_stop is not None and should_stop():
                raise _CallerStop()
            now = self._monotonic()
            last_seen = now
            self.counters.last_event_at = now
            self.counters.consecutive_failures = 0
            self.counters.last_failure = None
            self.counters.events_seen += 1
            self.counters.last_event_id = self.parser.last_event_id
            # ONE decode per event, here. Three call sites used to parse the same
            # bytes separately -- the position hint, the filter and the redirect
            # check -- which on a stream read for days triples the only CPU cost this
            # loop has. The type filter comes FIRST so an event that is not a
            # recentchange is never decoded at all.
            if event.event != RECENTCHANGE_EVENT:
                continue
            change = parse_change(event.data)
            if change is None:
                self.counters.events_malformed += 1
                continue
            if on_position is not None:
                # EVERY decoded event, before the edition and namespace filters. The
                # lane's cursor has to be able to move past what we chose not to keep;
                # see ``src/wiki/lane.py``'s ``read_changes`` for the measured reason.
                on_position(self._dbnames.get(change.wiki), self.parser.last_event_id)
            kept = self._accept(change, event.last_event_id)
            if kept is not None:
                on_change(kept)
        _ = last_seen

    def _events(self, response: Any) -> Iterator[SseEvent]:
        """Decoded events from one response, through the hand-rolled parser."""
        lines = response.iter_lines(decode_unicode=True)
        yield from self.parser.feed(lines)

    def _accept(self, change: StreamChange, event_id: str | None) -> StreamChange | None:
        """Filter one DECODED change onto this run's editions and Q703's namespace rule."""
        code = self._dbnames.get(change.wiki)
        if code is None:
            self.counters.events_other_edition += 1
            return None
        if change.namespace != ARTICLE_NAMESPACE:
            self.counters.events_other_namespace += 1
            return None
        if change.is_redirect:
            self.counters.events_redirect += 1
            return None
        self.counters.events_kept += 1
        self.counters.per_edition[code] = self.counters.per_edition.get(code, 0) + 1
        return StreamChange(
            wiki=code,
            page_id=change.page_id,
            title=change.title,
            namespace=change.namespace,
            change_kind=change.change_kind,
            revid=change.revid,
            parent_revid=change.parent_revid,
            timestamp_ms=change.timestamp_ms,
            user=change.user,
            bot=change.bot,
            minor=change.minor,
            comment=change.comment,
            length_new=change.length_new,
            length_old=change.length_old,
            log_type=change.log_type,
            log_action=change.log_action,
            event_id=event_id,
            is_redirect=change.is_redirect,
        )

    # -- helpers ------------------------------------------------------------ #
    def _refuse_if_offline(self, doing: str) -> None:
        """Raise NAMING the kill switch, per invariant #14e's corollary.

        The message says which mechanism refused, because the recorded breach was a
        probe that reported airplane mode as "size check failed" and pointed an
        operator at someone else's server for their own setting.
        """
        if kill_switch_active():
            raise StreamStopped(
                f"network kill switch is active (airplane mode) -- {doing} was refused "
                "by this app, not by Wikimedia"
            )

    def _next_backoff(self, current: float) -> float:
        """Exponential from the server's own ``retry``, capped.

        Starts at what the SERVER asked for rather than a number of ours: a service
        that publishes a reconnection time has told us what it wants, and ignoring
        it is the impolite half of a politeness policy.
        """
        base = max(0.5, self.parser.retry_ms / 1000.0)
        nxt = base if current <= 0 else current * 2
        return min(nxt, self._max_backoff_s)


def _as_int(value: Any) -> int | None:
    """Best-effort int, ``None`` on anything else. Never raises on foreign input."""
    if isinstance(value, bool):
        # ``bool`` is an ``int`` in Python, and a boolean in a numeric field is a
        # shape change we want counted as absent rather than read as 0 or 1.
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _timestamp_ms(raw: dict) -> int | None:
    """Milliseconds since the epoch, from whichever field the event carries.

    EventStreams sends a unix ``timestamp`` in SECONDS and a ``meta.dt`` ISO-8601
    string. Seconds are preferred because they need no parsing; the ISO field is the
    fallback. Neither present -> ``None``, and the caller records a change it cannot
    place in time rather than inventing one.
    """
    seconds = _as_int(raw.get("timestamp"))
    if seconds is not None:
        return seconds * 1000
    meta = raw.get("meta")
    dt = meta.get("dt") if isinstance(meta, dict) else None
    if not isinstance(dt, str):
        return None
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)
