"""Q707's WARM tier: the latest text of every other changed page, fetched lazily under the budget.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q707 = a, verbatim: «WARM = every other changed page (full text, indexed lazily under the
daily budget)». Q710 🔒 = a: «WARM: latest + previous». It is 0.5's row F, S1 of
``S05-06``. HOT (the pages the corpus mentions, the tracked ones, the pageview top-1,000)
is the drain's; WARM is every OTHER page the stream reported changed.

WHERE THE QUEUE COMES FROM. The drain already records every edit of every page as a
``versioned_changes`` row (Q708 = b), with the page id and the revision id the stream gave.
WARM reads that log forward from its own bookmark (``wiki_warm_scan``) and marks each
changed page DUE in ``wiki_warm_pages``. So there is ONE record of what the wiki reported,
and WARM is a reader of it rather than a second listener on the stream. A change the drain
linked to a followed page (``entity_id`` set) is HOT's and never queued here; a page that
becomes HOT after it was queued is not asked for again from its next turn, before any
request is made, and keeps the texts WARM held -- its history from before it was followed.

LAZILY, AND WHAT THAT MEANS HERE. WARM runs in the drain thread's IDLE time, after the drain
and before the walk (HOT, then WARM, then COLD -- Q707's order). It asks for the pages that
have waited LONGEST first, 50 to a request, and it asks for each page's NEWEST text rather
than for the revision the stream named: a page edited ten times while it waited costs one
fetch, of where the page stands now. The rate is the lane client's (one request at a time,
one second apart) and never a second rate authority beside the collection-speed governor
(Q1012; ``src/wiki/tiers.py`` says why "daily" is read as the storage cap).

THE BUDGET, AND THE SHARE WARM LEAVES TO HOT. Q707's budget is one storage cap for the whole
lane, and HOT's text stops when it is spent (``runner.make_text_policy``). A lower tier that
filled it would starve the tier above: the pages the operator's own corpus is about would
stop getting text so that pages nobody asked about could keep theirs. So WARM stops at
:data:`WARM_BUDGET_SHARE` of the budget, under its own named reason, and the rest is left to
HOT. The share is a PROPOSED default (S05-06 does not rule one) and is stated wherever the
pause is shown.

WHERE IT RUNS: only where the operator switches it on (Settings -> Wikipedia,
``wiki_warm_enabled``), OFF by default, for the walk's reason (``R51``): an update must not
start filling most of a lane's budget on every machine that has the lane on. Off means
nothing at all -- no scan, no request, no row -- and the scan's bookmark waits where it is.

A REFUSAL IS A RECORD, NOT A RETRY STORM -- the walk's rule and the walk's tokens
(``src/wiki/walk.py``): airplane mode, protected mode with no usable proxy and a spent budget
pause WARM as a whole and it never goes direct (Q722 = b); a refusal from one edition backs
that edition off alone, 60 s doubling to an hour.

NOTHING HERE ESTIMATES. It counts what it stored and what it was answered, and a page whose
text the wiki hid, or that left the main namespace, is recorded under that reason rather than
counted as a text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import defer

from src.wiki.mediawiki import MAX_PAGES_PER_REQUEST
from src.wiki.walk import (
    _BUSY_CODES,
    GLOBAL_PAUSES,
    PAUSED_BUDGET,
    WAIT_MALFORMED,
    WAIT_REFUSED,
    WAIT_SERVICE_BUSY,
    backoff_seconds,
    refusal_detail,
    refusal_token,
)

_LOG = logging.getLogger("wiki.warm")

#: WARM stops when the lane file holds this share of the budget; the rest is HOT's. A
#: PROPOSED default, not a ruling (see the module docstring), and one number so every
#: surface that explains the pause quotes the same one.
WARM_BUDGET_SHARE: float = 0.9

#: WARM as a whole waits: the lane holds WARM's share of the budget, and the rest is kept
#: for HOT. Distinct from ``storage_budget_spent``, which stops every tier's text.
PAUSED_WARM_SHARE = "warm_share_spent"
WARM_PAUSES: tuple[str, ...] = (*GLOBAL_PAUSES, PAUSED_WARM_SHARE)

#: What WARM is doing, as one token for a status surface.
STATE_FETCHING = "fetching"      # pages are due, and the last window was answered
STATE_PAUSED = "paused"          # one of WARM_PAUSES holds all of WARM
STATE_WAITING = "waiting"        # every edition with pages due is waiting out a refusal
STATE_CAUGHT_UP = "caught_up"    # no page is waiting for text
STATE_NOT_STARTED = "not_started"
STATE_OFF = "off"                # the operator's switch is off: nothing is queued or asked
WARM_STATES: tuple[str, ...] = (
    STATE_OFF, STATE_FETCHING, STATE_PAUSED, STATE_WAITING, STATE_CAUGHT_UP, STATE_NOT_STARTED,
)

#: Why a page's latest answer stored no text, as stored on ``wiki_warm_pages``.
NO_TEXT_NOT_AN_ARTICLE = "not_an_article"
NO_TEXT_HIDDEN = "text_hidden"
#: A COMPLETE answer that named the page in a shape this app cannot read as a text. Recorded
#: and not asked again until the stream reports another change: asking again at once would
#: put the same unreadable page at the head of the queue in every window, forever.
NO_TEXT_UNREADABLE = "unreadable"

#: How many change rows one window reads from the lane's log. A bound on one window's
#: transaction, not a rate: a lane that has recorded a day of edits catches up over a few
#: windows rather than holding one open across all of them.
SCAN_LIMIT: int = 5000

#: How long after a change WARM still expects the wiki to answer with that revision. Past
#: it, an older answer is accepted as the page's latest: the revision the stream named was
#: removed (a revision deletion), and asking again forever would be a retry loop. Inside
#: it, an older answer is the API's replication lag and the page goes to the back of the
#: queue to be asked again.
LAG_GRACE: timedelta = timedelta(minutes=10)

#: The change kinds that put a page in the queue, and the one that takes it out.
_WANTS_TEXT = frozenset({"edit", "create"})
_DELETION = "delete"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _holds_text(row: Any) -> bool:
    """Whether a WARM row holds a stored text, read from the sizes so no text is loaded."""
    return row.latest_bytes is not None or row.previous_bytes is not None


def revid_of(change_ref: str | None) -> int | None:
    """The revision id in a change ref the lane wrote (``"{wiki}:r{revid}"``), else ``None``.

    ``src/wiki/lane.py:_change_ref`` writes that form for every change carrying a revision
    and a different one for log events, so anything else is not a revision and is never
    guessed into one.
    """
    if not isinstance(change_ref, str):
        return None
    _wiki, sep, rest = change_ref.partition(":")
    if not sep or not rest.startswith("r") or not rest[1:].isdigit():
        return None
    value = int(rest[1:])
    return value if value > 0 else None


def budget_pause(budget: Any) -> str | None:
    """The reason WARM may not fetch under ``budget``, or ``None``.

    A budget that has not been MEASURED (no lane file yet) pauses nothing, for the reason
    ``BudgetState.exhausted`` gives: refusing before anything was measured would stop the
    tier on its first pass, forever.
    """
    if getattr(budget, "exhausted", False):
        return PAUSED_BUDGET
    disk = getattr(budget, "disk_bytes", None)
    total = getattr(budget, "total_bytes", None)
    if (
        isinstance(disk, int)
        and isinstance(total, int)
        and total > 0
        and disk >= total * WARM_BUDGET_SHARE
    ):
        return PAUSED_WARM_SHARE
    return None


@dataclass(slots=True)
class WarmReport:
    """What one WARM window did. Counts and named reasons, never a verdict."""

    scanned: int = 0
    queued: int = 0
    requests: int = 0
    texts: int = 0
    response_bytes: int = 0
    promoted: int = 0
    deleted: int = 0
    unanswered: int = 0
    no_text: dict[str, int] = field(default_factory=dict)
    refusals: dict[str, int] = field(default_factory=dict)
    paused: str | None = None

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "queued": self.queued,
            "requests": self.requests,
            "texts": self.texts,
            "response_bytes": self.response_bytes,
            "promoted": self.promoted,
            "deleted": self.deleted,
            "unanswered": self.unanswered,
            "no_text": dict(self.no_text),
            "refusals": dict(self.refusals),
            "paused": self.paused,
        }


class WarmFetcher:
    """Reads the lane's change log into WARM's queue and fetches the latest texts, 50 at a time.

    Every moving part is injected -- the client, the lane session, the budget and both
    clocks -- for the reason ``WikiLaneRunner`` gives.
    """

    def __init__(
        self,
        *,
        client: Any,
        editions: Sequence[str],
        lane_session: Callable[[], Any],
        budget: Callable[[], Any],
        enabled: Callable[[], bool],
        batch: int = MAX_PAGES_PER_REQUEST,
        scan_limit: int = SCAN_LIMIT,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        if isinstance(editions, (str, bytes)):
            raise TypeError("editions is a sequence of edition codes, not one string")
        if not 1 <= int(batch) <= MAX_PAGES_PER_REQUEST:
            raise ValueError(f"a WARM batch is 1 to {MAX_PAGES_PER_REQUEST} pages, not {batch}")
        if int(scan_limit) < 1:
            raise ValueError("a WARM scan reads at least one change row")
        self._client = client
        self._editions = tuple(dict.fromkeys(e for e in editions if e))
        self._lane_session = lane_session
        self._budget = budget
        self._enabled = enabled
        self._batch = int(batch)
        self._scan_limit = int(scan_limit)
        self._monotonic = monotonic
        self._now = now
        #: Per edition, the monotonic time before which it is not asked again, and how
        #: many refusals in a row it has had.
        self._not_before: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        #: Per edition, the latest refusal's TOKEN, for a status surface to explain a wait.
        self.last_refusal: dict[str, str] = {}
        self._turn = 0
        #: Per edition, the pages asked in the CURRENT window. Each is asked at most once a
        #: window: a page sent back to wait out replication lag, or left unanswered by a
        #: partial answer, is asked again in the next window, never in a loop inside this one.
        self._asked_now: dict[str, set[int]] = {}
        self.state: str = STATE_NOT_STARTED
        self.reason: str | None = None
        self.last_detail: str | None = None
        self.last_request_at: datetime | None = None
        self.requests_this_process = 0

    # -- the queue, from the lane's own change log --------------------------- #
    def scan(self) -> dict[str, int]:
        """Read up to ``scan_limit`` change rows past the bookmark and queue what they name.

        Returns ``{"scanned", "queued", "deleted"}``. The bookmark and every row it queued
        are written in ONE transaction, so a crash can neither skip changes nor queue them
        twice.
        """
        from src.versioned.models import VersionedChange
        from src.wiki.identity import parse_external_id
        from src.wiki.lane_models import WikiWarmPage, WikiWarmScan

        out = {"scanned": 0, "queued": 0, "deleted": 0}
        wanted_editions = set(self._editions)
        with self._lane_session() as lane:
            mark = lane.get(WikiWarmScan, "changes")
            if mark is None:
                mark = WikiWarmScan(key="changes", last_change_id=0, updated_at=self._now())
                lane.add(mark)
                lane.flush()
            rows = lane.execute(
                select(
                    VersionedChange.id,
                    VersionedChange.external_id,
                    VersionedChange.change_ref,
                    VersionedChange.change_kind,
                    VersionedChange.recorded_at,
                    VersionedChange.entity_id,
                )
                .where(VersionedChange.id > mark.last_change_id)
                .order_by(VersionedChange.id)
                .limit(self._scan_limit)
            ).all()
            if not rows:
                return out
            out["scanned"] = len(rows)
            # Per page, in log order: the newest revision named, the first and last time
            # it was reported, and whether the LAST event in this stretch was a deletion.
            seen: dict[tuple[str, int], dict] = {}
            for _cid, external_id, change_ref, kind, recorded_at, entity_id in rows:
                if entity_id is not None or not external_id:
                    continue  # HOT's, or not a page
                try:
                    ident = parse_external_id(external_id)
                except ValueError:
                    continue
                if ident.page_id is None or ident.wiki not in wanted_editions:
                    continue
                at = _aware(recorded_at) or self._now()
                acc = seen.setdefault(
                    (ident.wiki, ident.page_id),
                    {"revid": None, "first": None, "last": None, "deleted_at": None},
                )
                if kind in _WANTS_TEXT:
                    revid = revid_of(change_ref)
                    if revid is not None and (acc["revid"] is None or revid > acc["revid"]):
                        acc["revid"] = revid
                    acc["first"] = acc["first"] or at
                    acc["last"] = at
                    acc["deleted_at"] = None  # re-created after a deletion
                elif kind == _DELETION:
                    acc["deleted_at"] = at
                    acc["first"] = None
                    acc["last"] = None
            by_edition: dict[str, list[int]] = {}
            for edition, page_id in seen:
                by_edition.setdefault(edition, []).append(page_id)
            existing: dict[tuple[str, int], WikiWarmPage] = {}
            for edition, ids in by_edition.items():
                for start in range(0, len(ids), 500):
                    chunk = ids[start : start + 500]
                    for row in lane.execute(
                        select(WikiWarmPage).where(
                            WikiWarmPage.edition == edition, WikiWarmPage.page_id.in_(chunk)
                        )
                    ).scalars():
                        existing[(row.edition, row.page_id)] = row
            for key, acc in seen.items():
                row = existing.get(key)
                if acc["deleted_at"] is not None:
                    if row is not None:
                        row.deleted_at = acc["deleted_at"]
                        row.due_since = None
                        out["deleted"] += 1
                    continue  # nothing held and nothing to ask for
                if acc["last"] is None:
                    continue
                if row is not None and row.promoted_at is not None:
                    continue  # HOT's now; its changes are the drain's
                if row is None:
                    row = WikiWarmPage(edition=key[0], page_id=key[1], wanted_at=acc["last"])
                    lane.add(row)
                revid = acc["revid"]
                if revid is not None and (row.wanted_revid is None or revid > row.wanted_revid):
                    row.wanted_revid = revid
                row.wanted_at = max(_aware(row.wanted_at) or acc["last"], acc["last"])
                row.deleted_at = None
                newer = revid is None or row.latest_revid is None or revid > row.latest_revid
                if newer and row.due_since is None:
                    row.due_since = acc["first"]
                    out["queued"] += 1
            mark.last_change_id = int(rows[-1][0])
            mark.updated_at = self._now()
        return out

    # -- one window ------------------------------------------------------------ #
    def warm_for(
        self,
        seconds: float,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        max_requests: int | None = None,
    ) -> WarmReport:
        """Queue what the log reported, then fetch until ``seconds`` pass or nothing is due.

        The switch and the budget are read ONCE, at the start, as the drain and the walk read
        the budget: a window is at most one drain interval long, so the lane can pass the
        share by at most one window's texts, and the next window pauses.
        """
        report = WarmReport()
        self._asked_now = {}
        try:
            on = bool(self._enabled())
        except Exception:  # noqa: BLE001 - an unreadable switch is an OFF switch
            _LOG.warning("could not read the switch for fetching other changed pages; not fetching", exc_info=True)
            on = False
        if not on:
            # OFF MEANS NOTHING: no scan either. The bookmark stays where it is, so turning
            # the switch on later reads the log forward from there rather than skipping it.
            self._set(STATE_OFF, None)
            return report
        if not self._editions:
            self._set(STATE_CAUGHT_UP, None)
            return report
        paused = budget_pause(self._budget())
        if paused:
            report.paused = paused
            self._set(STATE_PAUSED, paused)
            return report
        scanned = self.scan()
        report.scanned = scanned["scanned"]
        report.queued = scanned["queued"]
        report.deleted += scanned["deleted"]
        deadline = self._monotonic() + max(0.0, float(seconds))
        empty: set[str] = set()
        later: set[str] = set()
        made = 0
        while not should_stop():
            if max_requests is not None and made >= max_requests:
                break
            if self._monotonic() >= deadline:
                break
            edition = self._next_edition(empty)
            if edition is None:
                break
            outcome = self.step(edition)
            if outcome.get("empty"):
                empty.add(edition)
                if outcome.get("later"):
                    later.add(edition)
                continue
            if outcome.get("answered") or outcome.get("refused"):
                made += 1  # a batch whose pages all turned HOT asked nothing
            report.requests += int(outcome.get("answered", 0))
            report.texts += int(outcome.get("texts", 0))
            report.response_bytes += int(outcome.get("response_bytes") or 0)
            report.promoted += int(outcome.get("promoted", 0))
            report.deleted += int(outcome.get("deleted", 0))
            report.unanswered += int(outcome.get("unanswered", 0))
            for reason, n in (outcome.get("no_text") or {}).items():
                report.no_text[reason] = report.no_text.get(reason, 0) + int(n)
            token = outcome.get("refused")
            if token:
                report.refusals[token] = report.refusals.get(token, 0) + 1
                if token in GLOBAL_PAUSES:
                    report.paused = token
                    break
        self._settle(report, empty, later)
        return report

    def _next_edition(self, empty: set[str]) -> str | None:
        """Round-robin over the editions not known empty this window and not backing off."""
        pending = [e for e in self._editions if e not in empty]
        if not pending:
            return None
        clock = self._monotonic()
        for offset in range(len(pending)):
            edition = pending[(self._turn + offset) % len(pending)]
            if self._not_before.get(edition, 0.0) <= clock:
                self._turn = (self._turn + offset + 1) % len(pending)
                return edition
        return None

    def _set(self, state: str, reason: str | None) -> None:
        if (state, reason) != (self.state, self.reason):
            _LOG.info("Wikipedia: fetching other changed pages is %s%s", state, f" ({reason})" if reason else "")
        self.state, self.reason = state, reason

    def _settle(
        self, report: WarmReport, empty: set[str], later: set[str] | frozenset[str] = frozenset()
    ) -> None:
        """The state after a window, from what the window saw (WAITING before FETCHING, for
        the reason the walk's ``_settle`` gives)."""
        if report.paused:
            self._set(STATE_PAUSED, report.paused)
            return
        clock = self._monotonic()
        waiting = [
            e for e in self._editions
            if e not in empty and self._not_before.get(e, 0.0) > clock
        ]
        if len(empty) == len(self._editions) and not later:
            self._set(STATE_CAUGHT_UP, None)
        elif waiting and len(waiting) + len(empty) == len(self._editions):
            self._set(STATE_WAITING, None)
        elif report.requests or report.promoted or later:
            self._set(STATE_FETCHING, None)

    # -- one request ------------------------------------------------------------ #
    def step(self, edition: str) -> dict:
        """One batch for ``edition``: the pages that waited longest, minus those now HOT.

        Returns counts plus ``refused`` (a token) when the request was refused, or
        ``{"empty": True}`` when the edition has nothing due.
        """
        from src.versioned.models import VersionedEntity
        from src.wiki.identity import external_id_for
        from src.wiki.lane_models import WikiWarmEdition, WikiWarmPage

        promoted = 0
        asked_now = self._asked_now.setdefault(edition, set())
        with self._lane_session() as lane:
            # The texts are not loaded to choose a batch: fifty rows of whole wikitexts,
            # decompressed only to be put back, would be most of this query's cost.
            query = (
                select(WikiWarmPage)
                .options(defer(WikiWarmPage.latest_text), defer(WikiWarmPage.previous_text))
                .where(WikiWarmPage.edition == edition, WikiWarmPage.due_since.is_not(None))
            )
            if asked_now:
                query = query.where(WikiWarmPage.page_id.not_in(sorted(asked_now)))
            due = list(
                lane.execute(
                    query.order_by(WikiWarmPage.due_since, WikiWarmPage.page_id).limit(self._batch)
                ).scalars()
            )
            if not due:
                # Nothing more to ask in THIS window; ``later`` says whether a page asked in
                # it is still due, so the edition is not reported caught up while it waits.
                held = bool(asked_now) and lane.execute(
                    select(WikiWarmPage.id)
                    .where(
                        WikiWarmPage.edition == edition,
                        WikiWarmPage.due_since.is_not(None),
                        WikiWarmPage.page_id.in_(sorted(asked_now)),
                    )
                    .limit(1)
                ).first() is not None
                return {"empty": True, "later": held}
            # PROMOTION FIRST, BEFORE ANY REQUEST. A page the drain now follows is HOT's,
            # and HOT keeps every version of it from here on (Q710). WARM stops asking for
            # it and KEEPS what it held: those texts are the page's history from before it
            # was followed, and nowhere else on this machine.
            ids = {external_id_for(edition, row.page_id): row for row in due}
            hot = set(
                lane.execute(
                    select(VersionedEntity.external_id).where(
                        VersionedEntity.external_id.in_(list(ids))
                    )
                ).scalars()
            )
            if hot:
                counts = lane.get(WikiWarmEdition, edition) or self._edition_row(lane, edition)
                at = self._now()
                for external_id in hot:
                    row = ids[external_id]
                    row.due_since = None
                    if row.promoted_at is None:
                        row.promoted_at = at
                        promoted += 1
                counts.promoted = int(counts.promoted or 0) + promoted
                counts.updated_at = at
            ask = [row.page_id for key, row in ids.items() if key not in hot]
        if not ask:
            return {"promoted": promoted}
        asked_now.update(ask)
        try:
            result = self._client.fetch_warm_texts(edition, ask)
        except Exception as exc:  # noqa: BLE001 - classified, never swallowed
            return {**self._refused(edition, refusal_token(exc), refusal_detail(exc)), "promoted": promoted}
        self._note_request()
        if result.get("error"):
            code = str(result["error"])
            token = WAIT_SERVICE_BUSY if code in _BUSY_CODES else WAIT_REFUSED
            return {**self._refused(edition, token, code), "promoted": promoted}
        if result.get("malformed"):
            return {
                **self._refused(edition, WAIT_MALFORMED, str(result["malformed"])),
                "promoted": promoted,
            }
        stored = self._store(edition, ask, result)
        if result.get("partial") and not stored["settled"]:
            # A continuation that settled NOTHING would ask for the same pages forever:
            # named, and the edition waits, like any answer this cannot use.
            return {
                **self._refused(edition, WAIT_MALFORMED, "partial-answer-settled-nothing"),
                "promoted": promoted,
            }
        self._failures.pop(edition, None)
        self._not_before.pop(edition, None)
        self.last_refusal.pop(edition, None)
        return {**stored, "answered": 1, "promoted": promoted}

    def _note_request(self) -> None:
        self.requests_this_process += 1
        self.last_request_at = self._now()

    def _edition_row(self, lane: Any, edition: str):
        from src.wiki.lane_models import WikiWarmEdition

        row = WikiWarmEdition(edition=edition, updated_at=self._now())
        lane.add(row)
        lane.flush()
        return row

    def _store(self, edition: str, asked: list[int], result: dict) -> dict:
        """Write one answer: texts shifted latest -> previous (Q710), queue cleared, counts."""
        from src.wiki.lane_models import WikiWarmEdition, WikiWarmPage

        pages = result.get("pages") or {}
        size = result.get("response_bytes")
        size = int(size) if isinstance(size, int) and size >= 0 else 0
        at = self._now()
        out: dict[str, Any] = {
            "texts": 0, "deleted": 0, "unanswered": 0, "no_text": {}, "settled": 0,
            "response_bytes": size,
        }
        partial = bool(result.get("partial"))
        with self._lane_session() as lane:
            # ``previous_text`` is only ever overwritten here, never read, so it is not loaded.
            rows = {
                row.page_id: row
                for row in lane.execute(
                    select(WikiWarmPage)
                    .options(defer(WikiWarmPage.previous_text))
                    .where(WikiWarmPage.edition == edition, WikiWarmPage.page_id.in_(asked))
                ).scalars()
            }
            counts = lane.get(WikiWarmEdition, edition) or self._edition_row(lane, edition)
            for page_id in asked:
                row = rows.get(page_id)
                if row is None:
                    continue
                answer = pages.get(page_id)
                if answer is None and partial:
                    # Not reached before the wiki's result limit: it keeps its place at the
                    # head of the queue and is in the next batch (see parse_warm_texts).
                    out["unanswered"] += 1
                    continue
                out["settled"] += 1
                if answer is None:
                    row.no_text_reason = NO_TEXT_UNREADABLE
                    row.due_since = None
                    row.fetched_at = at
                    out["no_text"][NO_TEXT_UNREADABLE] = out["no_text"].get(NO_TEXT_UNREADABLE, 0) + 1
                    continue
                if answer.get("missing"):
                    row.deleted_at = row.deleted_at or at
                    row.due_since = None
                    out["deleted"] += 1
                    continue
                title = answer.get("title")
                if isinstance(title, str) and title:
                    row.title = title[:512]
                if answer.get("not_an_article") or answer.get("text_hidden"):
                    reason = NO_TEXT_NOT_AN_ARTICLE if answer.get("not_an_article") else NO_TEXT_HIDDEN
                    row.no_text_reason = reason
                    row.due_since = None
                    row.fetched_at = at
                    out["no_text"][reason] = out["no_text"].get(reason, 0) + 1
                    continue
                revid = int(answer["revid"])
                text = answer["text"]
                row.fetched_at = at
                row.no_text_reason = None
                row.deleted_at = None
                if row.latest_revid is None or revid > row.latest_revid:
                    held_text = _holds_text(row)
                    if row.latest_bytes is not None:
                        # Q710: the latest becomes the previous, and the older one goes.
                        row.previous_revid = row.latest_revid
                        row.previous_text = row.latest_text
                        row.previous_bytes = row.latest_bytes
                        row.previous_revised_at = row.latest_revised_at
                    row.latest_revid = revid
                    row.latest_text = text
                    row.latest_bytes = len(text.encode("utf-8"))
                    row.latest_revised_at = answer.get("timestamp")
                    if not held_text:
                        counts.pages_with_text = int(counts.pages_with_text or 0) + 1
                    counts.texts_fetched = int(counts.texts_fetched or 0) + 1
                    out["texts"] += 1
                caught_up = row.wanted_revid is None or (row.latest_revid or 0) >= row.wanted_revid
                waited = at - (_aware(row.wanted_at) or at)
                if caught_up or waited > LAG_GRACE:
                    row.due_since = None
                else:
                    # The wiki answered with an older revision than the stream named, inside
                    # the replication-lag grace: to the back of the queue, asked again later.
                    row.due_since = at
            counts.requests = int(counts.requests or 0) + 1
            counts.response_bytes = int(counts.response_bytes or 0) + size
            counts.updated_at = at
        return out

    def _refused(self, edition: str, token: str, detail: str) -> dict:
        """Name a refusal. A whole-tier pause moves nothing; an edition's own waits alone."""
        self.last_detail = detail
        if token in GLOBAL_PAUSES:
            return {"refused": token}
        failures = self._failures.get(edition, 0) + 1
        self._failures[edition] = failures
        self._not_before[edition] = self._monotonic() + backoff_seconds(failures)
        self.last_refusal[edition] = token
        _LOG.info("Wikipedia: fetching other changed pages: %s refused (%s, %s); waiting", edition, token, detail)
        return {"refused": token}

    def status(self) -> dict:
        """This process's WARM state, and which editions are waiting and why. No row read."""
        clock = self._monotonic()
        return {
            "state": self.state,
            "reason": self.reason,
            "waiting": {
                e: self.last_refusal.get(e)
                for e in self._editions
                if self._not_before.get(e, 0.0) > clock
            },
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
            "requests_this_process": self.requests_this_process,
            "share": WARM_BUDGET_SHARE,
        }


def warm_coverage(lane: Any) -> dict[str, Any]:
    """WARM's counts, per edition, from the lane's own rows -- or a named absence.

    The ONE reader of WARM's rows: the counters artifact and Living sources both call it, so
    they cannot disagree about a number. ``due`` is counted over the queue's own index; the
    rest are the counts ``wiki_warm_editions`` keeps beside the rows they count.
    """
    from src.wiki.lane_models import WikiWarmEdition, WikiWarmPage

    editions = {row.edition: row for row in lane.execute(select(WikiWarmEdition)).scalars()}
    due = {
        edition: int(n)
        for edition, n in lane.execute(
            select(WikiWarmPage.edition, func.count(WikiWarmPage.id))
            .where(WikiWarmPage.due_since.is_not(None))
            .group_by(WikiWarmPage.edition)
        ).all()
    }
    names = sorted(set(editions) | set(due))
    if not names:
        return {"measured": False, "reason": "warm-never-run"}
    rows = []
    for name in names:
        row = editions.get(name)
        rows.append(
            {
                "edition": name,
                "pages_with_text": int(row.pages_with_text) if row else 0,
                "texts_fetched": int(row.texts_fetched) if row else 0,
                "requests": int(row.requests) if row else 0,
                "response_bytes": int(row.response_bytes) if row else 0,
                "promoted": int(row.promoted) if row else 0,
                "due": due.get(name, 0),
            }
        )
    return {
        "measured": True,
        "editions": rows,
        "pages_with_text": sum(r["pages_with_text"] for r in rows),
        "texts_fetched": sum(r["texts_fetched"] for r in rows),
        "requests": sum(r["requests"] for r in rows),
        "response_bytes": sum(r["response_bytes"] for r in rows),
        "promoted": sum(r["promoted"] for r in rows),
        "due": sum(r["due"] for r in rows),
        "share": WARM_BUDGET_SHARE,
        "method": (
            "wiki_warm_pages rows (the pages waiting for text, counted over the queue's own "
            "index) and wiki_warm_editions counts written in the same transaction as the "
            "texts they count"
        ),
        "caveat": (
            "A page holds at most its latest and previous text (Q710). The fetch of other "
            f"changed pages stops at {int(WARM_BUDGET_SHARE * 100)}% of the lane's budget and "
            "leaves the rest to the pages the stream follows; that share is a ruled default (R55)."
        ),
    }
