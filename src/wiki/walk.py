"""The ``allpages`` walk: every article title of each edition, 50 per request, one at a time.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q701 = c, verbatim: «Stream-forward plus a slow ``allpages`` walk for the tail, batched 50
per request, serial, under the storage budget (Q707), coverage reported per edition.» The
stream covers what CHANGES; the walk reaches the tail that does not, which is most of an
encyclopedia. It is 0.5's row F, S2 + S3 of ``S05-06``.

WHAT IT STORES. Metadata only -- Q707's COLD tier, "metadata now; text as budget allows":
each page's id, title, Wikidata item, size and newest revision, in ``wiki_walk_pages``. No
text, and never a ``versioned_entities`` row, so a walked page can never become a page the
lane follows and fetches in full (see ``src/wiki/lane_models.py``). COLD text is later work.

SERIAL, AND ON THE LANE'S OWN CLIENT. The walk runs on the drain thread, in the time between
two drains, through the SAME ``WikiClient`` the drain fetches text with. So there is one
request in flight at a time, one second between the end of one and the start of the next
(the client's own interval), and one fetch path: the kill switch, the protected-mode proxy
and the honest bot User-Agent apply to every walk request because they apply to that
client's session. The walk owns no session of its own, on purpose.

IT WAITS, IT NEVER SWITCHES (Q722 = b, S3). A refusal from the operator's own airplane
switch (``NetworkBlocked``) or from protected mode with no usable proxy
(``TransportUnavailable``) pauses the whole walk under a NAMED reason, and the next window
asks again. Nothing here builds another session or retries "direct": a walk that fell back
to clearnet when Tor was down would be the silent transport downgrade the non-negotiables
forbid.

A REFUSAL IS A RECORD, NOT A RETRY STORM. A refusal that belongs to one edition -- the wiki
asked clients to wait (``maxlag``, 429, 503), refused the request, dropped the connection,
or answered something that is not a walk batch -- is written on that edition's bookmark
row with its token and time, the bookmark does NOT move, and the edition waits a doubling
delay (one minute to one hour) before it is asked again. The other editions carry on.

THE ORDER IS ROUND-ROBIN OVER THE OPERATOR'S EDITIONS, one batch each in turn. S05-06's §6
leaves the order unruled and asks for a proposal: round-robin makes every edition move at
once, so a run cut short by a restart leaves twelve partly-walked editions rather than one
finished English edition and eleven untouched ones, and the small editions (a few thousand
requests each) finish early on their own.

NOTHING HERE ESTIMATES. It counts what it was answered, measures how long the answers took,
and reads the edition's own article count as the denominator. No ETA: a rate measured over
one hour of a multi-day walk is not a promise about the next six days.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from src.safety.fetcher import NetworkBlocked, TransportUnavailable
from src.wiki.mediawiki import MAX_PAGES_PER_REQUEST

_LOG = logging.getLogger("wiki.walk")

#: The whole walk waits: the operator's airplane switch is on. Same token the lane's
#: other surfaces use for it, so one translation says it everywhere.
PAUSED_NETWORK_OFF = "network_off"
#: The whole walk waits: protected mode is on and no usable proxy is set. The walk is
#: refused rather than sent direct, and waits for the transport the operator chose.
PAUSED_TRANSPORT_UNAVAILABLE = "transport_unavailable"
#: The whole walk waits: the lane's storage budget is spent. The same token the drain
#: records for text it did not store (``src/wiki/runner.py:BUDGET_FULL``); a test pins
#: the two together.
PAUSED_BUDGET = "storage_budget_spent"
#: One edition waits: the connection, or the proxy, did not answer.
WAIT_CONNECTION = "connection_failed"
#: One edition waits: the wiki asked clients to slow down (``maxlag``, 429 or 503).
WAIT_SERVICE_BUSY = "service_busy"
#: One edition waits: any other refusal (another HTTP status, another API error code).
WAIT_REFUSED = "request_refused"
#: One edition waits: the answer could not be read as a walk batch.
WAIT_MALFORMED = "malformed_response"

GLOBAL_PAUSES: tuple[str, ...] = (PAUSED_NETWORK_OFF, PAUSED_TRANSPORT_UNAVAILABLE, PAUSED_BUDGET)
EDITION_WAITS: tuple[str, ...] = (WAIT_CONNECTION, WAIT_SERVICE_BUSY, WAIT_REFUSED, WAIT_MALFORMED)

#: What the walk is doing, as one token for a status surface.
STATE_OFF = "off"              # the operator's switch is off
STATE_WALKING = "walking"      # the last window made at least one request
STATE_PAUSED = "paused"        # one of GLOBAL_PAUSES holds the whole walk
STATE_WAITING = "waiting"      # every unfinished edition is waiting out a refusal
STATE_COMPLETE = "complete"    # every edition's pass has finished
STATE_NOT_STARTED = "not_started"
WALK_STATES: tuple[str, ...] = (
    STATE_OFF, STATE_WALKING, STATE_PAUSED, STATE_WAITING, STATE_COMPLETE, STATE_NOT_STARTED,
)

#: The wait after an edition's first refusal, doubling per refusal in a row, capped.
BACKOFF_FIRST_S: float = 60.0
BACKOFF_MAX_S: float = 3600.0

#: API error codes that mean "slow down" rather than "no". ``maxlag`` is MediaWiki's own
#: (the client sends ``maxlag=5`` on every request); ``ratelimited`` its rate limiter's.
_BUSY_CODES = frozenset({"maxlag", "ratelimited"})
_BUSY_STATUSES = frozenset({429, 503})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(failures: int) -> float:
    """The wait after ``failures`` refusals in a row: 60 s, 120 s, 240 s ... at most an hour."""
    if failures <= 0:
        return 0.0
    return min(BACKOFF_MAX_S, BACKOFF_FIRST_S * (2 ** min(failures - 1, 16)))


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status an exception carries, when it is an answer the server refused."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _is_json_error(exc: BaseException) -> bool:
    """A body that did not parse as JSON. ``requests`` raises its own ``JSONDecodeError``,
    built on the stdlib's (or on simplejson's when that is installed); both carry the
    document and the position, and no other ``requests`` error does."""
    return isinstance(exc, json.JSONDecodeError) or (hasattr(exc, "doc") and hasattr(exc, "pos"))


def refusal_token(exc: BaseException) -> str:
    """The named reason for an exception a walk request raised. Order matters.

    ``TransportUnavailable`` IS a ``requests.ConnectionError`` (so every older caller treats
    it as "the proxy did not answer"), and it has to be recognised FIRST: it means protected
    mode has nothing to route through, which is the operator's setting to fix, not a flaky
    line to retry.

    CLASSIFIED BY SHAPE, WITHOUT IMPORTING ``requests``. This module opens no socket, and
    importing an HTTP library for three exception types would put it on the socket-importer
    allowlist (``tests/test_network_consent.py``) that exists to list the modules that CAN
    reach the network. Every ``requests`` exception is an ``OSError`` (its base class derives
    from ``IOError``), an HTTP refusal is the one carrying a response with a status, and a
    body that is not JSON is the one carrying the document it could not read.
    """
    if isinstance(exc, NetworkBlocked):
        return PAUSED_NETWORK_OFF
    if isinstance(exc, TransportUnavailable):
        return PAUSED_TRANSPORT_UNAVAILABLE
    status = _http_status(exc)
    if status is not None:
        return WAIT_SERVICE_BUSY if status in _BUSY_STATUSES else WAIT_REFUSED
    if isinstance(exc, ValueError) and (not isinstance(exc, OSError) or _is_json_error(exc)):
        # An answer, but not one this walk can read. A ``ValueError`` that is ALSO a
        # ``requests`` error and not a JSON one (a malformed proxy URL, a missing SOCKS
        # dependency) is the transport's, and falls through to the connection below.
        return WAIT_MALFORMED
    if isinstance(exc, OSError):
        return WAIT_CONNECTION
    raise exc


def refusal_detail(exc: BaseException) -> str:
    """A refusal's detail for a log reader: the exception's TYPE, and an HTTP status when
    there is one. Never its message, which can carry a URL, and a proxy error's can carry
    the proxy's address -- neither belongs on a status surface."""
    status = _http_status(exc)
    return f"{type(exc).__name__}" + (f" HTTP {status}" if status is not None else "")


@dataclass(slots=True)
class WindowReport:
    """What one walk window did. Counts and named refusals, never a verdict."""

    requests: int = 0
    pages: int = 0
    new_pages: int = 0
    response_bytes: int = 0
    refusals: dict[str, int] = field(default_factory=dict)
    paused: str | None = None
    completed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "pages": self.pages,
            "new_pages": self.new_pages,
            "response_bytes": self.response_bytes,
            "refusals": dict(self.refusals),
            "paused": self.paused,
            "completed": list(self.completed),
        }


class WikiWalker:
    """Walks each edition's ``allpages`` list, one batch per call, keeping a bookmark per edition.

    Every moving part is injected -- the client, the lane session, the budget, the switch,
    the transport token and both clocks -- for the reason ``WikiLaneRunner`` gives: the
    interesting behaviour is over time, and a walker that owned its own clock could only be
    tested by waiting.
    """

    def __init__(
        self,
        *,
        client: Any,
        editions: Sequence[str],
        lane_session: Callable[[], Any],
        budget: Callable[[], Any],
        enabled: Callable[[], bool],
        transport: Callable[[], str],
        batch: int = MAX_PAGES_PER_REQUEST,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        if isinstance(editions, (str, bytes)):
            raise TypeError("editions is a sequence of edition codes, not one string")
        if not 1 <= int(batch) <= MAX_PAGES_PER_REQUEST:
            raise ValueError(f"a walk batch is 1 to {MAX_PAGES_PER_REQUEST} pages, not {batch}")
        self._client = client
        self._editions = tuple(dict.fromkeys(e for e in editions if e))
        self._lane_session = lane_session
        self._budget = budget
        self._enabled = enabled
        self._transport = transport
        self._batch = int(batch)
        self._monotonic = monotonic
        self._now = now
        #: Per edition, the monotonic time before which it is not asked again.
        self._not_before: dict[str, float] = {}
        #: The in-memory copy of each edition's bookmark (see :meth:`_load`). This walker is
        #: the only writer of those rows, so the copy cannot go stale behind its back.
        self._cursors: dict[str, dict] | None = None
        self._turn = 0
        self.state: str = STATE_NOT_STARTED
        self.reason: str | None = None
        #: The latest refusal's detail for a log reader (an HTTP status, an error code);
        #: never shown as a sentence -- the TOKEN is what surfaces translate.
        self.last_detail: str | None = None
        self.last_request_at: datetime | None = None
        self.requests_this_process = 0

    # -- the bookmark ------------------------------------------------------- #
    def _load(self) -> dict[str, dict]:
        from src.wiki.lane_models import WikiWalkCursor

        if self._cursors is None:
            with self._lane_session() as lane:
                rows = lane.execute(select(WikiWalkCursor)).scalars().all()
                self._cursors = {
                    r.edition: {
                        "pass_no": int(r.pass_no),
                        "continue": json.loads(r.continue_json) if r.continue_json else None,
                        "complete": r.completed_at is not None,
                        "has_count": r.edition_articles_read_at is not None,
                        "failures": int(r.consecutive_failures or 0),
                    }
                    for r in rows
                }
        return self._cursors

    def _cursor_row(self, lane: Any, edition: str):
        from src.wiki.lane_models import WikiWalkCursor

        row = lane.get(WikiWalkCursor, edition)
        if row is None:
            at = self._now()
            row = WikiWalkCursor(edition=edition, pass_no=1, started_at=at, updated_at=at)
            lane.add(row)
            lane.flush()
        return row

    # -- choosing what to ask next ------------------------------------------ #
    def _unfinished(self) -> list[str]:
        cursors = self._load()
        return [e for e in self._editions if not cursors.get(e, {}).get("complete")]

    def _any_due(self) -> bool:
        """Whether an unfinished edition may be asked now. No side effect on the turn."""
        clock = self._monotonic()
        return any(self._not_before.get(e, 0.0) <= clock for e in self._unfinished())

    def _next_edition(self) -> str | None:
        """Round-robin over the unfinished editions that are not waiting out a refusal."""
        pending = self._unfinished()
        if not pending:
            return None
        clock = self._monotonic()
        for offset in range(len(pending)):
            edition = pending[(self._turn + offset) % len(pending)]
            if self._not_before.get(edition, 0.0) <= clock:
                self._turn = (self._turn + offset + 1) % len(pending)
                return edition
        return None

    # -- one window ----------------------------------------------------------- #
    def walk_for(
        self,
        seconds: float,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        max_requests: int | None = None,
    ) -> WindowReport:
        """Ask for batches until ``seconds`` pass, nothing is due, or ``should_stop()``.

        The switch and the budget are read ONCE, at the start, exactly as a drain reads the
        budget once (``runner.make_text_policy`` says why): a window is at most one drain
        interval long, and fifty pages of metadata a request cannot move the lane file
        enough within it to matter.
        """
        report = WindowReport()
        try:
            on = bool(self._enabled())
        except Exception:  # noqa: BLE001 - an unreadable switch is an OFF switch
            _LOG.warning("could not read the walk switch; not walking", exc_info=True)
            on = False
        if not on:
            self._set(STATE_OFF, None)
            return report
        if not self._editions:
            self._set(STATE_COMPLETE, None)
            return report
        budget = self._budget()
        if getattr(budget, "exhausted", False):
            report.paused = PAUSED_BUDGET
            self._set(STATE_PAUSED, PAUSED_BUDGET)
            return report
        deadline = self._monotonic() + max(0.0, float(seconds))
        made = 0
        while not should_stop():
            if max_requests is not None and made >= max_requests:
                break
            if self._monotonic() >= deadline:
                break
            edition = self._next_edition()
            if edition is None:
                break
            outcome = self.step(edition)
            made += 1
            report.requests += int(outcome.get("answered", 0))
            report.pages += int(outcome.get("pages", 0))
            report.new_pages += int(outcome.get("new_pages", 0))
            report.response_bytes += int(outcome.get("response_bytes") or 0)
            if outcome.get("completed"):
                report.completed.append(edition)
            token = outcome.get("refused")
            if token:
                report.refusals[token] = report.refusals.get(token, 0) + 1
                if token in GLOBAL_PAUSES:
                    report.paused = token
                    break
        self._settle(report)
        return report

    def _set(self, state: str, reason: str | None) -> None:
        if (state, reason) != (self.state, self.reason):
            _LOG.info("the Wikipedia walk is %s%s", state, f" ({reason})" if reason else "")
        self.state, self.reason = state, reason

    def _settle(self, report: WindowReport) -> None:
        """The state a status surface reads after a window, from what the window saw.

        WAITING is read BEFORE walking: a window that was answered twice and then refused on
        its only edition ends with nothing it may ask, and "walking" would describe the
        first half of the window rather than where the walk now stands.
        """
        if report.paused:
            self._set(STATE_PAUSED, report.paused)
        elif not self._unfinished():
            self._set(STATE_COMPLETE, None)
        elif not self._any_due():
            self._set(STATE_WAITING, None)
        elif report.requests:
            self._set(STATE_WALKING, None)

    # -- one request ---------------------------------------------------------- #
    def step(self, edition: str) -> dict:
        """One request for ``edition``: its article count at the start of a pass, else a batch.

        Returns what happened as counts plus ``refused`` (a token) when it was refused. The
        bookmark moves only on an answer that was read in full.
        """
        cursors = self._load()
        state = cursors.get(edition)
        if state is None:
            with self._lane_session() as lane:
                self._cursor_row(lane, edition)
            state = cursors[edition] = {
                "pass_no": 1, "continue": None, "complete": False, "has_count": False, "failures": 0,
            }
        if not state["has_count"]:
            return self._read_count(edition, state)
        return self._read_batch(edition, state)

    def _read_count(self, edition: str, state: dict) -> dict:
        from src.wiki.lane_models import WikiWalkCursor

        try:
            stats = self._client.fetch_edition_statistics(edition)
        except Exception as exc:  # noqa: BLE001 - classified, never swallowed
            return self._refused(edition, state, refusal_token(exc), refusal_detail(exc))
        self._note_request()
        with self._lane_session() as lane:
            row = lane.get(WikiWalkCursor, edition) or self._cursor_row(lane, edition)
            # A malformed statistics answer is RECORDED as absent and the walk goes on:
            # the count is the denominator, not the work, and an edition whose total is
            # unknown can still be walked honestly -- it just says "of an unknown total".
            articles = stats.get("articles") if isinstance(stats, dict) else None
            row.edition_articles = articles if isinstance(articles, int) else None
            row.edition_articles_read_at = self._now()
            row.updated_at = self._now()
        state["has_count"] = True
        return {"answered": 1}

    def _read_batch(self, edition: str, state: dict) -> dict:
        started = self._monotonic()
        try:
            result = self._client.fetch_walk_batch(
                edition, continue_params=state["continue"], limit=self._batch
            )
        except Exception as exc:  # noqa: BLE001 - classified, never swallowed
            return self._refused(edition, state, refusal_token(exc), refusal_detail(exc))
        busy_ms = max(0, int((self._monotonic() - started) * 1000))
        self._note_request()
        if result.get("error"):
            code = str(result["error"])
            token = WAIT_SERVICE_BUSY if code in _BUSY_CODES else WAIT_REFUSED
            return self._refused(edition, state, token, code)
        if result.get("malformed"):
            return self._refused(edition, state, WAIT_MALFORMED, str(result["malformed"]))
        return self._store(edition, state, result, busy_ms)

    def _note_request(self) -> None:
        self.requests_this_process += 1
        self.last_request_at = self._now()

    def _store(self, edition: str, state: dict, result: dict, busy_ms: int) -> dict:
        """Write one answered batch, its bookmark and its throughput sample in ONE transaction."""
        from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage

        pages = result.get("pages") or []
        size = result.get("response_bytes")
        size = int(size) if isinstance(size, int) and size >= 0 else 0
        at = self._now()
        pass_no = int(state["pass_no"])
        props_complete = bool(result.get("props_complete"))
        new_in_pass = 0
        with self._lane_session() as lane:
            ids = [p["page_id"] for p in pages]
            existing: dict[int, WikiWalkPage] = {}
            if ids:
                existing = {
                    row.page_id: row
                    for row in lane.execute(
                        select(WikiWalkPage).where(
                            WikiWalkPage.edition == edition, WikiWalkPage.page_id.in_(ids)
                        )
                    ).scalars()
                }
            done: set[int] = set()
            for page in pages:
                if page["page_id"] in done:
                    continue  # listed twice in one answer: one page, counted once
                done.add(page["page_id"])
                row = existing.get(page["page_id"])
                if row is None:
                    lane.add(
                        WikiWalkPage(
                            edition=edition,
                            page_id=page["page_id"],
                            title=page["title"][:512],
                            qid=page["qid"],
                            length_bytes=page["length_bytes"],
                            last_revid=page["last_revid"],
                            walked_at=at,
                            pass_no=pass_no,
                        )
                    )
                    new_in_pass += 1
                    continue
                if int(row.pass_no) < pass_no:
                    new_in_pass += 1
                row.title = page["title"][:512]
                # A QID the API did not answer in THIS batch (its props continue in the
                # next one) is not a QID that went away; only a batch whose props are
                # complete may clear one.
                if page["qid"] is not None or props_complete:
                    row.qid = page["qid"]
                if page["length_bytes"] is not None:
                    row.length_bytes = page["length_bytes"]
                if page["last_revid"] is not None:
                    row.last_revid = page["last_revid"]
                row.walked_at = at
                row.pass_no = pass_no
            cursor = lane.get(WikiWalkCursor, edition) or self._cursor_row(lane, edition)
            cursor.pages_seen = int(cursor.pages_seen or 0) + new_in_pass
            cursor.requests = int(cursor.requests or 0) + 1
            cursor.response_bytes = int(cursor.response_bytes or 0) + size
            cursor.updated_at = at
            cursor.consecutive_failures = 0
            completed = bool(result.get("complete"))
            if completed:
                cursor.completed_at = at
                cursor.continue_json = None
            else:
                cursor.continue_json = json.dumps(result.get("continue"), sort_keys=True)
            self._sample(lane, at, pages=len(pages), size=size, busy_ms=busy_ms)
        state["continue"] = None if completed else result.get("continue")
        state["complete"] = completed
        state["failures"] = 0
        self._not_before.pop(edition, None)
        return {
            "answered": 1,
            "pages": len(pages),
            "new_pages": new_in_pass,
            "response_bytes": size,
            "completed": completed,
        }

    def _sample(self, lane: Any, at: datetime, *, pages: int, size: int, busy_ms: int) -> None:
        from src.wiki.lane_models import WikiWalkSample

        try:
            transport = str(self._transport() or "unknown")[:16]
        except Exception:  # noqa: BLE001 - the sample says it could not tell
            transport = "unknown"
        hour = at.replace(minute=0, second=0, microsecond=0)
        row = lane.execute(
            select(WikiWalkSample).where(
                WikiWalkSample.hour_start == hour, WikiWalkSample.transport == transport
            )
        ).scalar_one_or_none()
        if row is None:
            row = WikiWalkSample(
                hour_start=hour, transport=transport, requests=0, pages=0, response_bytes=0, busy_ms=0
            )
            lane.add(row)
        row.requests = int(row.requests or 0) + 1
        row.pages = int(row.pages or 0) + pages
        row.response_bytes = int(row.response_bytes or 0) + size
        row.busy_ms = int(row.busy_ms or 0) + busy_ms

    def _refused(self, edition: str, state: dict, token: str, detail: Any) -> dict:
        """Name a refusal. A global one holds the walk; an edition's is written on its bookmark."""
        from src.wiki.lane_models import WikiWalkCursor

        self.last_detail = f"{edition}: {detail}"[:300]
        if token in GLOBAL_PAUSES:
            # The operator's own switch or setting, not the edition's fault: nothing is
            # written against the edition, and the next window asks again (for free --
            # both refusals happen before any socket opens).
            return {"refused": token}
        _LOG.warning("the %s walk was refused (%s): %s", edition, token, detail)
        failures = int(state.get("failures", 0)) + 1
        state["failures"] = failures
        self._not_before[edition] = self._monotonic() + backoff_seconds(failures)
        at = self._now()
        with self._lane_session() as lane:
            row = lane.get(WikiWalkCursor, edition) or self._cursor_row(lane, edition)
            row.consecutive_failures = failures
            row.last_error = token
            row.last_error_at = at
            row.updated_at = at
        return {"refused": token}

    # -- for a status surface ------------------------------------------------- #
    def is_on(self) -> bool:
        """Whether the operator's switch reads ON now. An unreadable switch is OFF.

        Read from the switch itself, never from the last reported state: that state stays
        ``off`` until a window runs, and a window the runner sized by it would never run.
        """
        try:
            return bool(self._enabled())
        except Exception:  # noqa: BLE001 - an unreadable switch is an OFF switch
            return False

    def status(self) -> dict:
        """What this process's walker is doing now. The COUNTS are the lane's rows, read
        by :func:`walk_coverage`; this is only what is not in a row."""
        clock = self._monotonic()
        # A COPY first: the drain thread writes this map while a request thread reads it.
        waiting = {
            e: max(0, int(t - clock)) for e, t in dict(self._not_before).items() if t > clock
        }
        return {
            "state": self.state,
            "reason": self.reason,
            "editions": list(self._editions),
            "waiting_seconds": waiting,
            "requests_this_process": self.requests_this_process,
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
            "last_detail": self.last_detail,
        }


def walk_coverage(lane: Any, *, window_days: int = 7, now: datetime | None = None) -> dict:
    """The walk's own counters, from its rows: per edition, pages seen of the edition's count.

    ONE read of twelve bookmark rows plus the hourly samples in the window, never a count
    over millions of page rows: the bookmark's counts are written in the same transaction as
    the pages they count (``WikiWalkCursor``'s docstring), so they are the rows' own figure.
    Absent with a reason when the walk has never run on this lane.
    """
    from datetime import timedelta

    from sqlalchemy import inspect as sa_inspect

    from src.wiki.lane_models import WikiWalkCursor, WikiWalkSample

    # On the session's OWN connection: a lane file written by a 0.4 build has no walk
    # tables until this build's ``create_schema`` runs, and a query against a missing
    # table would fail the whole counters read rather than this one block.
    if not sa_inspect(lane.connection()).has_table(WikiWalkCursor.__tablename__):
        return {"measured": False, "reason": "walk-never-run"}
    rows = lane.execute(select(WikiWalkCursor).order_by(WikiWalkCursor.edition)).scalars().all()
    if not rows:
        return {"measured": False, "reason": "walk-never-run"}

    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    editions = [
        {
            "edition": r.edition,
            "pass_no": int(r.pass_no),
            "pages_seen": int(r.pages_seen or 0),
            "edition_articles": r.edition_articles,
            "edition_articles_read_at": _iso(r.edition_articles_read_at),
            "requests": int(r.requests or 0),
            "response_bytes": int(r.response_bytes or 0),
            "started_at": _iso(r.started_at),
            "updated_at": _iso(r.updated_at),
            "completed_at": _iso(r.completed_at),
            "consecutive_failures": int(r.consecutive_failures or 0),
            "last_error": r.last_error,
            "last_error_at": _iso(r.last_error_at),
        }
        for r in rows
    ]
    at = now or _utcnow()
    since = at - timedelta(days=window_days)
    by_transport: dict[str, dict] = {}
    for s in lane.execute(
        select(WikiWalkSample).where(WikiWalkSample.hour_start >= since)
    ).scalars():
        block = by_transport.setdefault(
            s.transport, {"hours": 0, "requests": 0, "pages": 0, "response_bytes": 0, "busy_ms": 0}
        )
        block["hours"] += 1
        block["requests"] += int(s.requests or 0)
        block["pages"] += int(s.pages or 0)
        block["response_bytes"] += int(s.response_bytes or 0)
        block["busy_ms"] += int(s.busy_ms or 0)
    return {
        "measured": True,
        "editions": editions,
        "pages_seen": sum(e["pages_seen"] for e in editions),
        "requests": sum(e["requests"] for e in editions),
        "response_bytes": sum(e["response_bytes"] for e in editions),
        "complete": [e["edition"] for e in editions if e["completed_at"]],
        "throughput": {
            "window_days": window_days,
            "by_transport": by_transport,
            "method": (
                "wiki_walk_samples: per hour and per transport, the requests answered, the "
                "pages they listed, the bytes of JSON they weighed and the milliseconds spent "
                "inside them. The one-second pause between requests is etiquette and is not "
                "counted in busy_ms; 'hours' is how many hours had at least one request."
            ),
        },
        "method": (
            "wiki_walk_cursors: one row per edition, its counts written in the same "
            "transaction as the page rows they count. pages_seen is the distinct pages this "
            "pass listed; edition_articles is the edition's own article count, read from "
            "its siteinfo statistics at the start of the pass."
        ),
        "caveat": (
            "The edition counts its articles its own way, which is not exactly the set the "
            "walk lists (namespace 0, redirects excluded), so pages seen can pass the "
            "edition's count. A page the walk listed and the edition later deleted keeps its "
            "row; it reads as not seen since its pass, never as deleted."
        ),
    }
