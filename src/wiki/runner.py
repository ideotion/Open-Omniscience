"""What makes the lane COLLECT: the stream held open, and the drain that stores it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-09's brief builds the SSE client, the storage shape and the toggle. This is the
part that connects them — and its absence was the largest gap the slice's first PR
listed by name: *"nothing schedules the stream, so the lane does not collect, and the
≥ 72 h run is not merely un-run, it is not yet startable"*. It is startable from here.

TWO THREADS AND ONE RULE ABOUT THEM. The stream thread does exactly one thing: decode
events and hand them to the adapter's in-memory buffer. It NEVER touches a database.
The drain runs on the caller's thread, opens the lane and the corpus, and stores what
the buffer holds. A SQLite handle is not safe to share across threads and an encrypted
one is no safer; keeping the split at the buffer means the rule is structural rather
than remembered.

THE RUNNER OBEYS THE OPERATOR'S SETTING AND NOTHING ELSE. It starts only for
``wiki_lane_state == "running"``, and it re-reads that setting on every tick, so
"halt" and "stop" take effect at the next check rather than at the next reconnect,
which on a healthy stream could be hours. It performs NO consent of its own: the
toggle in the top bar passes ``ensureOnline`` before it ever writes ``running``
(invariant #14), and the kill switch is checked on every read inside the stream and
named in the refusal (invariant #14e's corollary). A runner that could bring a lane
online would be a second consent path beside the one popup.

WHAT STOPS AT THE BUDGET, AND WHAT DOES NOT. Q707's budget is a STORAGE cap (see
``src/wiki/tiers.py`` for why it is not a second rate authority beside the governor).
When it is spent, TEXT stops and the reason is recorded per change — and the METADATA
keeps flowing, because Q108 = a makes "metadata for every edit in all twelve editions"
the lane's whole purpose and a change row is a few hundred bytes against a page's
entire wikitext. An operator who wants everything to stop has the toggle, which says
plainly what it does. This is a choice, it is the kind a budget surface must not make
silently, and it is stated here and shown there.

NOTHING HERE ESTIMATES. Every number this module reports it either counted itself or
read from a counter something else measured.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.versioned.adapters.base import ReadBudget
from src.versioned.pipeline import Admission, LaneTransactionLost, PassResult, run_feed_once
from src.wiki.counters import record_size_sample
from src.wiki.history import (
    HistoryBuffer,
    per_edition_deltas,
    percentile,
    stream_deltas,
)
from src.wiki.identity import parse_external_id
from src.wiki.lane import WikiStreamAdapter, edition_of
from src.wiki.tiers import BudgetState, HotSet

_LOG = logging.getLogger("wiki.runner")

#: The named reason a text was not fetched because the lane's storage budget is spent.
#: Distinct from ``tiers.DEFERRED_UNTIL_WARM_TIER`` — a full disk and a tier this
#: release does not ingest need opposite responses from the operator.
BUDGET_FULL: str = "storage_budget_spent"

#: How many buffered changes one drain takes per edition. A bound, not a tuning knob:
#: a drain that took an unbounded buffer would hold one transaction open across an
#: arbitrary amount of work, and the operator's Stop would wait for it.
DRAIN_LIMIT: int = 2000

#: How many drains may fail in a row before the loop reports itself degraded and starts waiting
#: longer between tries (it no longer ends there: see FAILING_RETRY_CEILING_S). Not a tuning
#: number: a loop that retries at full speed forever burns a core on an error that is not going
#: to clear and buries the one log line that said why, and a loop that reports on the first
#: failure cries wolf at a moment's contention. Three is enough to ride out a lock and few
#: enough that a real breakage is reported while anyone is still watching.
MAX_CONSECUTIVE_FAILURES: int = 3

#: The longest the loop waits between two tries once MAX_CONSECUTIVE_FAILURES drains have
#: failed in a row (the wait doubles from one drain interval up to this). The lane no longer
#: ENDS there -- an ended loop left the setting saying ``running`` over a lane that collected
#: nothing, with no way back short of a restart. The ceiling protects two things at once: how
#: long a lane whose cause has cleared (a lock, WAL pressure, a full disk freed) can sit idle
#: before its next try, and how long the corpus's single writer is left alone by a lane that
#: keeps failing against it. It is a choice about those two, not a buffer limit: the stream's
#: buffer holds 20,000 changes per edition (several hours of events, ``lane.DEFAULT_BUFFER_MAX``).
FAILING_RETRY_CEILING_S: float = 300.0

#: Seconds one drain may spend FETCHING page texts, shared out between the feeds. The drain
#: records every change first and then fetches one polite request per touched page; behind a
#: backlog (a stream resumed hours back) that is thousands of requests, and the walk, WARM and
#: the search index run only AFTER the drain, so an unbounded drain starves all three. Texts
#: not fetched in time are counted as deferred, and the NEXT drain fetches them first (the
#: catch-up below), so a bound costs a page its text for a drain or two, never for good.
#: The bound limits when a fetch may START: one already in flight finishes, so the worst
#: case is this plus one request's own timeout (30 s) per feed, stated in the manual.
DRAIN_TEXT_SECONDS: float = 20.0

#: Followed pages per feed whose text an earlier drain left unfetched, tried again before the
#: feed's new changes, oldest-waiting first (``src/versioned/pipeline.py``). A cap on the
#: backlog READ, not on the backlog: what this does not reach waits for the next drain.
CATCH_UP_LIMIT: int = 200

#: The share of the idle window kept for the page walk when the walk is on. WARM would
#: otherwise take the whole window behind the index (it is lazy and never runs out of
#: changed pages on a busy lane) and the walk, the last tier, would never run.
WALK_RESERVE: float = 0.3

#: Seconds between drains when the runner drives its own loop. The stream keeps
#: buffering in between, so this is a latency-versus-transaction-size choice and not
#: a rate: nothing about the network depends on it.
DRAIN_INTERVAL_S: float = 30.0

#: How many drain durations the runner keeps for its p50 and p95. Not a tuning number: it is
#: the ticks of a 72-hour run (3 days at one drain every 30 s plus the drain itself is under
#: 8,640), the run the operator asked these figures for, and 10,000 floats are 80 KB.
DRAIN_RING: int = 10_000

#: How many recent ticks the status lists with their parts. Enough to see one stuck tick and the
#: ones around it; the hourly history carries the rest.
TICK_RING: int = 20


@dataclass(slots=True)
class DrainReport:
    """What one drain across every feed did. Counts and named refusals, never a verdict."""

    passes: dict[str, dict] = field(default_factory=dict)
    entities_admitted: int = 0
    changes_recorded: int = 0
    revisions_stored: int = 0
    articles_indexed: int = 0
    text_withheld: int = 0
    text_withheld_reasons: dict[str, int] = field(default_factory=dict)
    #: Texts not fetched in this drain because its time bound (or a count bound) ran out.
    #: Distinct from ``text_withheld``: withheld is a POLICY refusal with a reason, deferred
    #: is "not yet", and the two need opposite responses.
    text_deferred: int = 0
    #: Pages the catch-up FOUND waiting this drain (an earlier drain left their text), as far as
    #: the per-feed cap sees: found, not necessarily fetched. 0 while every waiting page is
    #: cooling off, or once a feed's time is spent.
    text_backlog: int = 0
    gaps_recorded: int = 0
    #: Whether this drain recorded a lane-file size sample. At most one an hour, so
    #: ``False`` is the ordinary case and not a failure.
    size_sampled: bool = False
    errors: list[str] = field(default_factory=list)
    #: The budget as it was read at the START of this drain, never recomputed after —
    #: a report whose budget line was measured after the writes it describes would
    #: attribute this drain's growth to the state it began in.
    budget: dict | None = None

    def add(self, feed: str, result: PassResult) -> None:
        self.passes[feed] = result.as_dict()
        self.entities_admitted += result.entities_admitted
        self.changes_recorded += result.changes_recorded
        self.revisions_stored += result.revisions_stored
        self.articles_indexed += result.articles_indexed
        self.text_withheld += result.text_withheld
        self.text_deferred += result.text_deferred
        self.text_backlog += result.text_backlog
        for reason, n in result.text_withheld_reasons.items():
            self.text_withheld_reasons[reason] = self.text_withheld_reasons.get(reason, 0) + n
        if result.gap_recorded:
            self.gaps_recorded += 1
        self.errors.extend(result.errors)

    def as_dict(self) -> dict:
        return {
            "passes": dict(self.passes),
            "entities_admitted": self.entities_admitted,
            "changes_recorded": self.changes_recorded,
            "revisions_stored": self.revisions_stored,
            "articles_indexed": self.articles_indexed,
            "text_withheld": self.text_withheld,
            "text_deferred": self.text_deferred,
            "text_backlog": self.text_backlog,
            "text_withheld_reasons": dict(self.text_withheld_reasons),
            "gaps_recorded": self.gaps_recorded,
            "size_sampled": self.size_sampled,
            "errors": list(self.errors),
            "budget": self.budget,
        }


def make_admit(
    adapter: WikiStreamAdapter, hot_sets: Mapping[str, HotSet]
) -> Callable[[Any], Admission | None]:
    """The ``admit`` callback: follow a changed page when Q707 says it is HOT.

    IT IS THE ONLY PLACE THE TIER ADMITS ANYTHING, and it admits — it never demotes.
    A page that leaves the pageview top-1,000 keeps being followed, deliberately: a
    rule that could stop following a page would quietly drop one an operator has been
    reading, and the control for that is the operator's own (``watching``), not a
    ranking that moves every day.
    """

    def _admit(change: Any) -> Admission | None:
        external_id = getattr(change, "external_id", None)
        if not external_id:
            return None
        try:
            ident = parse_external_id(external_id)
        except ValueError:
            return None
        hot = hot_sets.get(ident.wiki)
        if hot is None:
            return None
        titles, page_id = adapter.seen(external_id)
        candidates = list(titles) or ([ident.title] if ident.title else [])
        decision = hot.decide(titles=candidates, page_id=page_id)
        if decision.tier != "hot":
            return None
        return Admission(
            # The NEWEST name the source used, because that is what the page is
            # called now — while the decision above was allowed every name it has
            # had in this batch. Two different questions about the same page.
            title=(candidates[-1] if candidates else None),
            # The edition code IS the language for a Wikipedia edition, and this is
            # the one place both are in hand — a later read would have to re-derive it
            # from the id it is already carrying.
            language=ident.wiki,
            reason=decision.reason,
        )

    return _admit


def make_text_policy(budget: BudgetState) -> Callable[[Any], tuple[bool, str | None]]:
    """The ``text_policy`` callback: fetch a followed entity's text unless the budget is spent.

    The budget is read ONCE, at the start of a drain, and this closure holds that
    reading. Re-measuring the file per entity would charge a page for the bytes the
    page before it wrote, turning one drain into a race against itself; the cap is
    re-read on the next drain, which is soon and is honest about which drain it
    measured.
    """

    def _policy(_entity: Any) -> tuple[bool, str | None]:
        if budget.exhausted:
            return False, BUDGET_FULL
        return True, None

    return _policy


def drain_once(
    lane: Any,
    adapter: WikiStreamAdapter,
    *,
    hot_sets: Mapping[str, HotSet],
    budget: BudgetState,
    corpus: Any | None = None,
    limit: int = DRAIN_LIMIT,
    text_seconds: float | None = DRAIN_TEXT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    on_feed: Callable[[str], None] | None = None,
    rotate: int = 0,
    catch_up: int = CATCH_UP_LIMIT,
    attempts: dict[int, float] | None = None,
) -> DrainReport:
    """Drain every feed's buffer into the lane once. No network of its own.

    The only outbound calls are the adapter's, for the text of pages the tier admitted
    — which is why this whole function runs in a test with the airplane socket guard
    armed and a fixture client, resolving no names at all.
    """
    report = DrainReport(budget=budget.as_dict())
    # THE GROWTH SERIES IS FED FROM THE MEASUREMENT ALREADY IN HAND. ``budget`` was
    # built from one ``lane_file_bytes`` call at the start of this drain; sampling
    # from it costs nothing and, crucially, records the SAME number the budget
    # decision was made on. A second stat here would produce a slightly different
    # figure and the two surfaces would disagree about one quantity.
    try:
        report.size_sampled = record_size_sample(lane, budget.disk_bytes)
    except Exception as exc:  # noqa: BLE001 - a missing sample must not end a drain
        _LOG.debug("could not record a lane size sample", exc_info=True)
        report.errors.append(f"size sample: {type(exc).__name__}: {exc}")
    admit = make_admit(adapter, hot_sets)
    policy = make_text_policy(budget)
    feeds = list(adapter.feeds())
    if feeds:
        # THE STARTING FEED ROTATES drain by drain, so the edition that goes last (and gets
        # whatever time the others left) is not always the same one.
        turn = rotate % len(feeds)
        feeds = feeds[turn:] + feeds[:turn]
    started = monotonic()
    for index, feed in enumerate(feeds):
        if on_feed is not None:
            on_feed(feed)
        # EACH FEED GETS AN EQUAL SHARE OF WHAT IS LEFT (time a feed does not use rolls
        # forward to the next), so a busy first edition cannot spend the whole bound and
        # leave the last eleven with no text at all.
        deadline = None
        if text_seconds is not None:
            left = max(0.0, text_seconds - (monotonic() - started))
            deadline = monotonic() + left / max(1, len(feeds) - index)
        try:
            result = run_feed_once(
                lane,
                adapter,
                feed,
                corpus=corpus,
                budget=ReadBudget(max_requests=limit),
                admit=admit,
                text_policy=policy,
                fetch_deadline=deadline,
                monotonic=monotonic,
                catch_up=catch_up if text_seconds is not None else 0,
                attempts=attempts,
            )
        except LaneTransactionLost:
            # The lane's transaction is gone: go on and a later feed's commit would hide the
            # rows an earlier feed lost. Fail the drain, loudly and counted.
            raise
        except Exception as exc:  # noqa: BLE001 - one edition must not end the drain
            # NAMED, and the drain continues. Eleven editions still collecting while
            # one is broken is the honest outcome; a drain that died on the first
            # would lose the other eleven's buffers to the next overflow.
            _LOG.warning("the %s feed failed this drain", feed, exc_info=True)
            report.errors.append(f"{edition_of(feed)}: {type(exc).__name__}: {exc}")
            continue
        report.add(feed, result)
    return report


class WikiLaneRunner:
    """Holds the stream open while the setting says ``running``, and drains it.

    EVERY MOVING PART IS INJECTED — the stream, the adapter, the sessions, the clock
    and the sleep — because the thing most worth testing about a runner is what it
    does over TIME, and a runner that owned its own clock could only be tested by
    waiting. The production wiring passes the real ones.
    """

    def __init__(
        self,
        *,
        adapter: WikiStreamAdapter,
        stream: Any,
        lane_session: Callable[[], Any],
        state_of: Callable[[], str],
        hot_sets: Callable[[], Mapping[str, HotSet]],
        budget: Callable[[], BudgetState],
        corpus_session: Callable[[], Any] | None = None,
        resume_from: Callable[[], str | None] | None = None,
        pageviews: Callable[[], str | None] | None = None,
        walker: Any | None = None,
        warm: Any | None = None,
        indexer: Any | None = None,
        max_connections: int | None = None,
        drain_interval_s: float = DRAIN_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter = adapter
        self._stream = stream
        self._lane_session = lane_session
        self._corpus_session = corpus_session
        self._state_of = state_of
        self._hot_sets = hot_sets
        self._budget = budget
        self._resume_from = resume_from
        #: Q706's once-a-day attention signal, injected so the runner never owns a
        #: fetch of its own. ``None`` disables it entirely, which is what every test
        #: that is not about the cadence passes.
        self._pageviews = pageviews
        #: Q701 = c's ``allpages`` walk (``src/wiki/walk.py``), run in the time between two
        #: drains on THIS thread, so it shares the drain's client and never overlaps a
        #: drain's writes. ``None`` disables it, which is what every test that is not about
        #: the walk passes.
        self._walker = walker
        #: The last walk window's report, for a status surface. ``None`` before the first.
        self.last_walk: dict | None = None
        #: Q707's WARM tier (``src/wiki/warm.py``), run in the same idle time BEFORE the
        #: walk: HOT is the drain's, then WARM, then COLD, which is the ruling's own order.
        #: ``None`` disables it, which is what every test not about WARM passes.
        self._warm = warm
        self.last_warm: dict | None = None
        #: The lane's own search index (``R52``, ``src/wiki/lane_search.py``), run FIRST in
        #: the idle time and for at most ``INDEX_SHARE`` of it: indexing is local and costs
        #: no request, and a text fetched but not yet findable is the one thing WARM's
        #: requests are for. ``None`` disables it, which is what every test not about the
        #: index passes.
        self._indexer = indexer
        self.last_index: dict | None = None
        #: A ceiling on how many times the stream may (re)connect in one run. ``None``
        #: — the production value — means "as long as the setting says running", which
        #: is what a stream held open for days needs. A number is for a caller that
        #: wants a bounded run, and it is the only thing that makes this class drivable
        #: in a test without a clock: the fixture stream replays and reconnects
        #: forever otherwise, which is CORRECT behaviour and untestable behaviour at
        #: the same time.
        self._max_connections = max_connections
        self._interval = drain_interval_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # ONE start at a time: the drain thread's revive and the service's start (Start, Run-now,
        # the airplane button) can land together, and two passes through the alive check would
        # each build a stream thread, the second orphaning the first.
        self._start_lock = threading.RLock()
        #: The last drain's report, for a status surface to read. ``None`` before the
        #: first drain — which is an ABSENCE and never a report of zero.
        self.last_drain: dict | None = None
        self.drains = 0
        #: Consecutive failed drains, and the last one's reason. Both live on the runner
        #: rather than only in the log, because a status surface cannot read a log.
        self.consecutive_failures = 0
        self.last_error: str | None = None
        #: The wait the loop chose after its latest failure once it is past
        #: MAX_CONSECUTIVE_FAILURES, else ``None``; for a status surface.
        self._retry_wait_s: float | None = None
        #: How many times the loop started the stream thread again after it ended without
        #: the operator asking (the kill switch refused a reconnect and was cleared since,
        #: or the thread died), and when the last one was.
        self.stream_restarts = 0
        self.last_stream_restart_at: str | None = None
        #: Why the stream thread last ended and when (the kill switch's named refusal, or an
        #: unexpected fault), and why the loop's latest attempt to start it again failed.
        self.last_stream_end: str | None = None
        self.last_stream_end_at: str | None = None
        self.last_restart_error: str | None = None
        #: When the latest failed drain was seen, and when the next try is due.
        self.last_error_at: str | None = None
        self._retry_due_at: str | None = None
        #: WHERE THE DRAIN IS, for a status surface. A status that said only ``drains: 0``
        #: could not tell a drain that had not started from one stuck in its first hot-set
        #: read, or fetching texts behind a backlog, or failing and retrying: four different
        #: problems with one symptom. ``stage`` is one of ``idle`` / ``hot-sets`` / ``feeds``,
        #: ``feed`` the edition being drained, and ``since`` the monotonic start of this drain.
        self.drain_stage: str = "idle"
        self.drain_feed: str | None = None
        self._drain_since: float | None = None
        #: Entity id -> monotonic time of the catch-up's last attempt at it, this process only
        #: (the pipeline's backoff; a restart forgets it, which costs one more try).
        self._attempts: dict[int, float] = {}
        #: When the last drain COMPLETED. A failed drain leaves it alone (it shows in
        #: ``consecutive_failures``), so "since last drain" never counts a failure as one.
        self._last_drain_ended: float | None = None
        #: THE LANE'S OWN HISTORY (src/wiki/history.py): hourly aggregates of what this loop did,
        #: noted in memory and written once per tick. The ring holds each drain's duration for the
        #: p50 and p95 the status reports; the tick parts say where each tick's seconds went.
        self._history = HistoryBuffer()
        self._drain_ms: deque[float] = deque(maxlen=DRAIN_RING)
        self._stage_totals_ms: dict[str, int] = {}
        #: What THIS drain thread held of the corpus's write gate, summed over drains that could be
        #: measured (the gate keeps a thread's holds by its ident, src/database/writer.py ``watch``).
        self._gate_totals: dict[str, int] = {"measured": 0, "grants": 0, "held_ms": 0, "longest_ms": 0}
        self._tick_parts: dict[str, int] = {}
        self._tick_totals_ms: dict[str, int] = {}
        self._tick_last: deque[dict[str, int]] = deque(maxlen=TICK_RING)
        self.ticks = 0
        self._stream_base: dict[str, int] | None = None
        self._edition_base: dict[str, int] | None = None

    def _ms_since(self, t0: float) -> int:
        return max(0, int((self._monotonic() - t0) * 1000))

    def _tick_part(self, name: str, ms: int) -> None:
        """Add ``ms`` to the part ``name`` of the tick in progress."""
        self._tick_parts[name] = self._tick_parts.get(name, 0) + int(ms)

    def _close_tick(self) -> None:
        """End a tick: record its parts, the stream's per-tick differences, and flush the history.

        Never raises: the history is a record of the lane, not part of its work.
        """
        parts, self._tick_parts = self._tick_parts, {}
        if parts:
            self.ticks += 1
            self._tick_last.append(dict(parts))
            for name, ms in parts.items():
                self._tick_totals_ms[name] = self._tick_totals_ms.get(name, 0) + ms
                self._history.note("tick", kind=name, ms=ms)
        try:
            counters = self.stream_counters()
            deltas, self._stream_base = stream_deltas(self._stream_base, counters)
            for key, n in deltas.items():
                self._history.note("stream", kind=key, n=n)
            kept, self._edition_base = per_edition_deltas(
                self._edition_base, (counters or {}).get("per_edition")
            )
            for edition, n in kept.items():
                self._history.note("stream", edition=edition, kind="kept", n=n)
        except Exception:  # noqa: BLE001 - a stream that keeps no counters has no differences
            _LOG.debug("could not read the stream's counters for the history", exc_info=True)
        if self._history.pending():
            try:
                with self._lane_session() as lane:
                    self._history.flush(lane)
            except Exception as exc:  # noqa: BLE001 - kept in the buffer for the next tick
                _LOG.debug("the lane history could not be written this tick: %s", exc)

    def drain_status(self) -> dict:
        """Where the drain loop is right now, measured on this runner. Never raises."""
        since = self._drain_since
        ended = self._last_drain_ended
        now = self._monotonic()
        return {
            "stage": self.drain_stage,
            "feed": self.drain_feed,
            "running_for_s": round(now - since, 1) if since is not None else None,
            "since_last_drain_s": round(now - ended, 1) if ended is not None else None,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "stopped": self._stop.is_set(),
            # PAST MAX_CONSECUTIVE_FAILURES THE LOOP KEEPS TRYING, and says so. ``retry_in_s``
            # is the wait it chose after the latest failure; the ceiling and what it protects
            # travel with it so a reader of the status needs no source to interpret the number.
            "degraded": self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES,
            "retry_in_s": self._retry_wait_s,
            "retry_in_s_note": "the wait chosen after the latest failure, not a countdown; retry_due_at is when it ends",
            "retry_due_at": self._retry_due_at,
            "last_error_at": self.last_error_at,
            "last_stream_end": self.last_stream_end,
            "last_stream_end_at": self.last_stream_end_at,
            "last_restart_error": self.last_restart_error,
            "retry_ceiling_s": FAILING_RETRY_CEILING_S,
            "retry_ceiling_protects": (
                "how long a lane whose cause has cleared can sit idle before its next try, and how "
                "long the corpus's single writer is left alone by a lane that keeps failing"
            ),
            "stream_restarts": self.stream_restarts,
            "last_stream_restart_at": self.last_stream_restart_at,
            # WHERE THE TIME GOES, since this runner started (src/wiki/history.py keeps the hourly
            # record across restarts). ``tick`` parts are seconds spent in the drain, the
            # pageview top-up, the search index, WARM, the walk, the sleep and, for a lane that is
            # failing, the failure wait; a tick is all of them, and the walk's pace is whatever the others leave of its 30 s window.
            "tick": {
                "ticks": self.ticks,
                "totals_s": {k: round(v / 1000, 1) for k, v in sorted(self._tick_totals_ms.items())},
                "last": list(self._tick_last),
                "last_unit": "milliseconds, one entry per tick, newest last",
            },
            "drain_duration": self._drain_duration(),
            "history": {
                "pending_rows": self._history.pending(),
                "flush_failures": self._history.flush_failures,
                "dropped_rows": self._history.dropped_rows,
                "last_flush_error": self._history.last_flush_error,
            },
        }

    def _drain_duration(self) -> dict:
        """The measured durations of this runner's drains: count, p50, p95 and the longest.

        ``stage_totals_s`` is the wall time of each stage, summed: ``feeds-wall`` includes opening
        the lane, waiting for a connection and the HTTP text fetches between stores, so it is an
        upper bound on how long the corpus was occupied and NOT that figure. The figure itself is
        ``write_gate``: the holds this drain thread took of the corpus's single writer, from the
        gate's own accounting of that one thread. Failed drains are in the durations. Absent
        figures are ``None`` with the count beside them, never a zero.
        """
        data = list(self._drain_ms)
        p50 = percentile(data, 0.5)
        p95 = percentile(data, 0.95)
        return {
            "measured": len(data),
            "p50_s": None if p50 is None else round(p50 / 1000, 2),
            "p95_s": None if p95 is None else round(p95 / 1000, 2),
            "max_s": None if not data else round(max(data) / 1000, 2),
            "window": f"the last {DRAIN_RING} drains this process ran, failed ones included",
            "stage_totals_note": (
                "wall time summed over every drain this process ran: hot-sets, and feeds-wall (the "
                "feeds stage including its HTTP waits, an upper bound on how long the corpus was "
                "occupied; the hold itself is write_gate)"
            ),
            "stage_totals_s": {k: round(v / 1000, 1) for k, v in sorted(self._stage_totals_ms.items())},
            "write_gate": self._gate_block(),
        }

    def _gate_block(self) -> dict:
        g = self._gate_totals
        measured = g["measured"]
        return {
            "measured_drains": measured,
            "grants": g["grants"] if measured else None,
            "held_s": round(g["held_ms"] / 1000, 2) if measured else None,
            "longest_hold_s": round(g["longest_ms"] / 1000, 2) if measured else None,
            "method": (
                "the corpus write gate's own accounting of THIS drain thread's holds, read and cleared "
                "around each drain (a hold in flight at the end is not in it); another thread's holds "
                "are never in these figures"
            ),
        }

    # -- the stream half ---------------------------------------------------- #
    def _should_stop(self) -> bool:
        """True when the operator's setting no longer says ``running``, or we were told to stop."""
        if self._stop.is_set():
            return True
        try:
            return self._state_of() != "running"
        except Exception:  # noqa: BLE001 - an unreadable setting stops the stream
            # STOPS rather than continues. A runner that kept streaming because it
            # could not read the setting would be collecting without a permission it
            # can no longer confirm, which is the one direction this must not fail in.
            _LOG.warning("could not read the lane state; stopping the stream", exc_info=True)
            self.last_error = "the lane setting could not be read; the loop stopped (the next Start or online click restarts it)"
            return True

    def _stream_body(self) -> None:
        resume = None
        if self._resume_from is not None:
            try:
                resume = self._resume_from()
            except Exception:  # noqa: BLE001 - an unreadable cursor is a cold start
                _LOG.warning("could not read the stored stream position", exc_info=True)
                resume = None
        try:
            self._stream.run(
                self._adapter.offer,
                should_stop=self._should_stop,
                max_connections=self._max_connections,
                resume_from=resume,
                on_position=self._adapter.note_position,
            )
        except Exception as exc:  # noqa: BLE001 - including the kill switch's refusal
            # The kill switch raises ``StreamStopped`` with its own named message; it
            # is logged as the ordinary end it is, not as a crash. Anything else is a
            # transport fault the stream itself already exhausted its retries on.
            # The reason is kept on the runner (the status and the bundle carry it): an unexpected
            # end read as ``streaming: false`` with nothing to say why, in INFO logs only.
            self.last_stream_end = f"{type(exc).__name__}: {exc}"[:300]
            self.last_stream_end_at = datetime.now(UTC).isoformat()
            if type(exc).__name__ == "StreamStopped":
                _LOG.info("the Wikipedia stream ended: %s", exc)
            else:
                _LOG.warning("the Wikipedia stream ended unexpectedly: %s", exc, exc_info=True)

    def start(self) -> bool:
        """Start the stream thread. ``False`` when the setting does not say ``running``."""
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            if self._state_of() != "running":
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._stream_body, name="oo-wiki-stream", daemon=True
            )
            self._thread.start()
            return True

    def revive_stream(self) -> bool:
        """Start the stream thread again when it ended and nobody asked it to. ``True`` if started.

        The stream thread ends for good on any refusal by the kill switch (the Stop button,
        airplane mode) and on any unforeseen death, and NOTHING started it again: the drain
        loop beside it kept running over a lane that no longer listened, the setting still
        said ``running``, and the only ways back were the airplane button, a settings write
        or a restart (seen in the October bundles: no lane row for 40 hours with the app
        online on one machine; what ended that lane could not be read from them). The drain loop calls this each tick and the collection Start button calls it
        through the service, so ONE rule decides: the setting says running, the kill switch is
        clear, the operator did not stop this runner, and a thread that was started is dead.

        It never starts a runner that was never started (that is ``start``'s, behind the one
        consent), never overrides ``stop()``, and does nothing for a bounded run
        (``max_connections``), whose stream ends on purpose.
        """
        from src.ingest import kill_switch_active

        if self._max_connections is not None:
            return False
        with self._start_lock:
            if self._stop.is_set() or self._thread is None or self.streaming:
                return False
            try:
                if self._state_of() != "running" or kill_switch_active():
                    return False
            except Exception:  # noqa: BLE001 - an unreadable setting is a lane that stays down
                return False
            # ``start`` treats a dead thread as restartable, and a failed start leaves the
            # dead thread in place, so the next tick tries again.
            if not self.start():
                return False
            self.stream_restarts += 1
            self.last_stream_restart_at = datetime.now(UTC).isoformat()
        _LOG.warning(
            "the Wikipedia stream had ended without being stopped; started it again (restart %d)",
            self.stream_restarts,
        )
        return True

    def stop(self, *, timeout: float = 5.0) -> None:
        """Ask the stream thread to end and wait briefly. Idempotent.

        Under the start lock, so a stop that lands while ``revive_stream`` is starting a thread
        is ordered after it: the revive's ``start`` clears the stop flag, and a stop that set it
        a moment earlier would be erased, leaving a stream and a drain loop nobody holds.
        """
        with self._start_lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._start_lock:
            if self._thread is thread:
                self._thread = None

    @property
    def stopped(self) -> bool:
        """Whether this runner was told to stop (by ``stop`` or by its own loop)."""
        return self._stop.is_set()

    @property
    def streaming(self) -> bool:
        """Whether the stream thread is alive. MEASURED, never the stored setting."""
        return self._thread is not None and self._thread.is_alive()

    def stream_counters(self) -> dict | None:
        """The stream's own counters, or ``None`` for a stream that keeps none."""
        counters = getattr(self._stream, "counters", None)
        as_dict = getattr(counters, "as_dict", None)
        return as_dict() if callable(as_dict) else None

    # -- the drain half ----------------------------------------------------- #
    def drain(self) -> DrainReport:
        """One drain, on the CALLER's thread. Opens the lane, stores, closes."""
        self._drain_since = self._monotonic()
        started = self._drain_since
        hot_ms = 0
        ok = False
        self.drain_stage, self.drain_feed = "hot-sets", None
        gate_ident = self._watch_gate()
        try:
            budget = self._budget()
            hot = self._hot_sets()
            hot_ms = self._ms_since(started)
            lane_cm = self._lane_session()
            corpus_cm = self._corpus_session() if self._corpus_session is not None else None
            self.drain_stage = "feeds"

            def _note_feed(feed: str) -> None:
                self.drain_feed = feed

            with lane_cm as lane:
                if corpus_cm is None:
                    report = drain_once(
                        lane, self._adapter, hot_sets=hot, budget=budget,
                        monotonic=self._monotonic, on_feed=_note_feed, rotate=self.drains,
                        attempts=self._attempts,
                    )
                else:
                    with corpus_cm as corpus:
                        report = drain_once(
                            lane, self._adapter, hot_sets=hot, budget=budget, corpus=corpus,
                            monotonic=self._monotonic, on_feed=_note_feed, rotate=self.drains,
                            attempts=self._attempts,
                        )
            ok = True
        finally:
            # A drain that failed while still building its hot sets spent that time THERE, not
            # holding the corpus connection: the stage it died in says where the time went.
            died_in_hot_sets = not ok and self.drain_stage == "hot-sets"
            self.drain_stage, self.drain_feed = "idle", None
            self._drain_since = None
            total_ms = self._ms_since(started)
            if died_in_hot_sets:
                hot_ms = total_ms
            self._note_drain(
                ok, total_ms, hot_ms, report if ok else None,
                gate=self._take_gate(gate_ident), died_in_hot_sets=died_in_hot_sets,
            )
        self._last_drain_ended = self._monotonic()
        self.last_drain = report.as_dict()
        self.drains += 1
        return report

    def _watch_gate(self) -> int | None:
        """Ask the corpus write gate to keep this thread's holds for the drain about to run."""
        try:
            from src.database.writer import watch_holder

            ident = threading.get_ident()
            watch_holder(ident)
            return ident
        except Exception:  # noqa: BLE001 - the record is not the work
            _LOG.debug("could not watch the write gate", exc_info=True)
            return None

    def _take_gate(self, ident: int | None) -> dict | None:
        """What this thread held of the write gate during the drain that just ended, or ``None``."""
        if ident is None:
            return None
        try:
            from src.database.writer import take_watched_holder

            return take_watched_holder(ident)
        except Exception:  # noqa: BLE001 - the record is not the work
            _LOG.debug("could not read the write gate's per-thread figures", exc_info=True)
            return None

    def _note_drain(
        self,
        ok: bool,
        total_ms: int,
        hot_ms: int,
        report: DrainReport | None,
        gate: dict | None = None,
        died_in_hot_sets: bool = False,
    ) -> None:
        """Record one drain's duration, its stages, its gate holds and what it stored. Never raises."""
        try:
            feeds_ms = max(0, total_ms - hot_ms)
            self._drain_ms.append(float(total_ms))
            self._stage_totals_ms["hot-sets"] = self._stage_totals_ms.get("hot-sets", 0) + hot_ms
            if not died_in_hot_sets:
                self._stage_totals_ms["feeds-wall"] = self._stage_totals_ms.get("feeds-wall", 0) + feeds_ms
            self._tick_part("drain", total_ms)
            self._history.note(
                "drain", kind="ok" if ok else "failed", ms=total_ms,
                pages=report.revisions_stored if report is not None else 0,
            )
            self._history.note("drain_stage", kind="hot-sets", ms=hot_ms)
            if not died_in_hot_sets:
                # WALL time of the stage, an upper bound on the corpus connection's hold (see
                # ``_drain_duration``); the hold itself is the ``drain_gate`` rows below.
                self._history.note("drain_stage", kind="feeds-wall", ms=feeds_ms)
            if gate is not None:
                held_ms = int(round(gate["held_s"] * 1000))
                longest_ms = int(round(gate["longest_s"] * 1000))
                grants = int(gate["grants"])
                self._history.note("drain_gate", kind="held", ms=held_ms)
                self._history.note("drain_gate", kind="longest", ms=longest_ms)
                self._history.note("drain_gate", kind="grants", n=grants)
                g = self._gate_totals
                g["measured"] += 1
                g["grants"] += grants
                g["held_ms"] += held_ms
                g["longest_ms"] = max(g["longest_ms"], longest_ms)
            if report is not None and report.gaps_recorded:
                self._history.note("drain", kind="gaps", n=report.gaps_recorded)
        except Exception:  # noqa: BLE001 - the record is not the work
            _LOG.debug("could not record a drain's timing", exc_info=True)

    def refresh_one_pageview_top(self) -> str | None:
        """Fetch ONE edition's daily top-1,000 if any is due. Returns the edition, or None.

        ONE PER TICK, NOT TWELVE. Q706's budget is twelve requests a day, and this
        spends them one at a time so they spread across the day's drains instead of
        arriving as a burst the moment the app starts — which is what a loop over
        twelve editions would do, twelve times harder on the service and no faster for
        the operator.

        It is a NO-OP while offline, and says so through the client's own refusal
        rather than by checking a flag here: the guarded session refuses under the kill
        switch and names it (invariant #14e's corollary), and a second check here would
        be a second place to keep that behaviour in step.

        Returns ``None`` when nothing was due, which is the ordinary case — the
        difference between "nothing was due" and "it failed" is in the log and in the
        caller's own report, never collapsed into one silent return.
        """
        if self._pageviews is None:
            return None
        try:
            return self._pageviews()
        except Exception as exc:  # noqa: BLE001 - an attention signal must not end a drain
            _LOG.warning("the daily pageview top-up failed: %s", exc, exc_info=True)
            return None

    def idle(self, seconds: float) -> None:
        """The time between two drains: the index's, WARM's and the walk's windows, then sleep.

        THE TIERS TAKE THE IDLE TIME, NEVER THE DRAIN'S. The drain stores what the stream
        already handed over (and HOT's text with it); WARM fetches the other changed pages
        lazily; the walk reaches pages nothing is waiting for. Q707's order is HOT, WARM,
        COLD, so WARM goes first and the walk has whatever time WARM leaves, and a tier
        with nothing to do (caught up, switched off, paused, waiting, finished) leaves its
        time to the next, and the last to the sleep, exactly as before either existed.

        THE SEARCH INDEX GOES FIRST (``R52``), for at most ``INDEX_SHARE`` of the window: it
        makes the texts already fetched findable, costs no request, and a backlog of it (a
        0.4 lane's every older version, on its first open) must not starve the tiers.

        A TIER'S FAILURE NEVER ENDS THE LANE. Refusals are named inside each tier; what
        reaches here is a fault in the tier itself, and it is logged and left for the next
        window rather than allowed to stop the drain loop.
        """
        start = self._monotonic()

        def left() -> float:
            return seconds - (self._monotonic() - start)

        if self._indexer is not None and not self._should_stop():
            from src.wiki.lane_search import INDEX_SHARE

            index_t0 = self._monotonic()
            try:
                index_report = self._indexer.index_for(
                    max(0.0, min(left(), seconds * INDEX_SHARE)), should_stop=self._should_stop
                )
                self.last_index = index_report.as_dict()
            except Exception as exc:  # noqa: BLE001 - the index must not end the lane
                _LOG.warning("the Wikipedia lane search index window failed: %s", exc, exc_info=True)
                self.last_index = {"error": f"{type(exc).__name__}"}
            self._tick_part("index", self._ms_since(index_t0))
        if self._warm is not None and not self._should_stop():
            # WARM'S WINDOW LEAVES THE WALK ITS RESERVE while the walk is on: WARM is lazy and
            # takes whatever it is given, so without a reserve the last tier never ran.
            warm_window = max(0.0, left())
            if self._walk_is_on():
                warm_window *= 1.0 - WALK_RESERVE
            warm_t0 = self._monotonic()
            try:
                warm_report = self._warm.warm_for(warm_window, should_stop=self._should_stop)
                self.last_warm = warm_report.as_dict()
            except Exception as exc:  # noqa: BLE001 - WARM must not end the lane
                _LOG.warning("the Wikipedia window for fetching other changed pages failed: %s", exc, exc_info=True)
                self.last_warm = {"error": f"{type(exc).__name__}"}
            self._tick_part("warm", self._ms_since(warm_t0))
        if self._walker is not None and not self._should_stop() and left() > 0:
            walk_t0 = self._monotonic()
            try:
                report = self._walker.walk_for(left(), should_stop=self._should_stop)
                self.last_walk = report.as_dict()
            except Exception as exc:  # noqa: BLE001 - the walk must not end the lane
                _LOG.warning("the Wikipedia walk window failed: %s", exc, exc_info=True)
                self.last_walk = {"error": f"{type(exc).__name__}"}
            self._tick_part("walk", self._ms_since(walk_t0))
        remaining = left()
        if remaining > 0 and not self._should_stop():
            sleep_t0 = self._monotonic()
            self._wait(remaining)
            self._tick_part("sleep", self._ms_since(sleep_t0))
        self._close_tick()

    def _walk_is_on(self) -> bool:
        """Whether a walker is wired and its switch reads ON (asked of the switch itself)."""
        is_on = getattr(self._walker, "is_on", None)
        if not callable(is_on):
            return self._walker is not None
        try:
            return bool(is_on())
        except Exception:  # noqa: BLE001 - a switch read must not end the window
            return True

    def walk_status(self) -> dict | None:
        """The walker's own status, or ``None`` for a runner built without one."""
        if self._walker is None:
            return None
        try:
            return {**self._walker.status(), "last_window": self.last_walk}
        except Exception:  # noqa: BLE001 - a status read must not fail the status surface
            _LOG.debug("could not read the walk status", exc_info=True)
            return None

    def index_status(self) -> dict | None:
        """The search indexer's in-process status, or ``None`` for a runner built without it."""
        if self._indexer is None:
            return None
        try:
            return {**self._indexer.status(), "last_window": self.last_index}
        except Exception:  # noqa: BLE001 - a status read must not fail the status surface
            _LOG.debug("could not read the search index status", exc_info=True)
            return None

    def warm_status(self) -> dict | None:
        """WARM's own in-process status, or ``None`` for a runner built without it."""
        if self._warm is None:
            return None
        try:
            return {**self._warm.status(), "last_window": self.last_warm}
        except Exception:  # noqa: BLE001 - a status read must not fail the status surface
            _LOG.debug("could not read the status of fetching other changed pages", exc_info=True)
            return None

    def _failure_wait(self) -> float:
        """Seconds to wait after a failed drain: one interval for the first two, then doubling, capped."""
        over = self.consecutive_failures - MAX_CONSECUTIVE_FAILURES
        if over < 0:
            return float(self._interval)
        # The exponent is capped: ``2 ** 1024`` does not convert to a float, and a lane that fails
        # every drain reaches it in about 85 hours. 16 doublings pass any ceiling a sane interval
        # has, and the min() below still decides the wait.
        doublings = min(over + 1, 16)
        return float(min(self._interval * (2**doublings), max(FAILING_RETRY_CEILING_S, self._interval)))

    def _wait(self, seconds: float) -> None:
        """Wait in one-second slices, ending early when the runner is stopped.

        One uninterrupted sleep of up to FAILING_RETRY_CEILING_S would leave a stopped runner's
        drain thread alive for minutes, beside the next runner's.
        """
        remaining = float(seconds)
        while remaining > 0 and not self._stop.is_set():
            step = min(1.0, remaining)
            self._sleep(step)
            remaining -= step

    def run_until_stopped(self, *, max_drains: int | None = None) -> int:
        """Drain every ``drain_interval_s`` until the setting stops saying ``running``.

        ``max_drains`` is for tests and for a caller that wants one tick; ``None``
        means "until told to stop", which is what the scheduler passes.
        """
        done = 0
        while not self._should_stop():
            if max_drains is not None and done >= max_drains:
                break
            try:
                self.revive_stream()
            except Exception as exc:  # noqa: BLE001 - a failed restart is retried next tick
                self.last_restart_error = f"{type(exc).__name__}: {exc}"[:300]
                _LOG.warning("the Wikipedia stream could not be restarted: %s", exc, exc_info=True)
            try:
                self.drain()
                self.consecutive_failures = 0
                self._retry_wait_s = None
                self._retry_due_at = None
            except Exception as exc:  # noqa: BLE001 - one bad drain must not end the lane
                # A LOOP THAT LETS ONE FAILURE END THE THREAD stops collecting for the
                # rest of the process with no record anywhere -- measured: an absent
                # lane file killed this thread and the stream kept filling a buffer
                # nobody was draining.
                self.consecutive_failures += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_error_at = datetime.now(UTC).isoformat()
                _LOG.warning(
                    "the wiki lane drain failed (%d in a row): %s",
                    self.consecutive_failures, exc, exc_info=True,
                )
                if self.consecutive_failures == MAX_CONSECUTIVE_FAILURES:
                    _LOG.error(
                        "the wiki lane has failed %d drains in a row (%s); it keeps trying, "
                        "waiting up to %d s between tries",
                        self.consecutive_failures, self.last_error, int(FAILING_RETRY_CEILING_S),
                    )
                # AND A LOOP THAT ENDS AT THREE IS THE OPPOSITE FAULT: three failed drains
                # are about two minutes of contention, and the lane then stayed dead for the
                # rest of the process with its setting still saying ``running``. Past three
                # the wait doubles up to FAILING_RETRY_CEILING_S: not a spin, and not an end.
                wait = self._failure_wait()
                degraded = self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                self._retry_wait_s = wait if degraded else None
                self._retry_due_at = (
                    (datetime.now(UTC) + timedelta(seconds=wait)).isoformat() if degraded else None
                )
                wait_t0 = self._monotonic()
                self._wait(wait)
                # A lane that keeps failing is the one whose record matters most: close the
                # tick here too, so its drains and its waits reach the history while it is
                # still failing, not only after it recovers.
                self._tick_part("failure-wait", self._ms_since(wait_t0))
                self._close_tick()
                continue
            # AFTER the drain, deliberately. The drain is the lane's job; the attention
            # signal is a top-up for the NEXT one, and running it first would delay
            # storing what the stream already handed us in order to fetch something
            # nothing is waiting for.
            pageviews_t0 = self._monotonic()
            self.refresh_one_pageview_top()
            self._tick_part("pageviews", self._ms_since(pageviews_t0))
            done += 1
            if self._should_stop():
                self._close_tick()
                break
            if max_drains is not None and done >= max_drains:
                self._close_tick()
                break
            self.idle(self._interval)
        return done
