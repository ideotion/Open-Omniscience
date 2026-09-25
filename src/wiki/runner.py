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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.versioned.adapters.base import ReadBudget
from src.versioned.pipeline import Admission, PassResult, run_feed_once
from src.wiki.counters import record_size_sample
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

#: How many drains may fail in a row before the loop gives up. Not a tuning number: a
#: loop that retries forever burns a core on an error that is not going to clear and
#: buries the one log line that said why, and a loop that stops on the first failure
#: loses the lane to a moment's contention. Three is enough to ride out a lock and few
#: enough that a real breakage is reported while anyone is still watching.
MAX_CONSECUTIVE_FAILURES: int = 3

#: Seconds between drains when the runner drives its own loop. The stream keeps
#: buffering in between, so this is a latency-versus-transaction-size choice and not
#: a rate: nothing about the network depends on it.
DRAIN_INTERVAL_S: float = 30.0


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
    for feed in adapter.feeds():
        try:
            result = run_feed_once(
                lane,
                adapter,
                feed,
                corpus=corpus,
                budget=ReadBudget(max_requests=limit),
                admit=admit,
                text_policy=policy,
            )
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
        #: The last drain's report, for a status surface to read. ``None`` before the
        #: first drain — which is an ABSENCE and never a report of zero.
        self.last_drain: dict | None = None
        self.drains = 0
        #: Consecutive failed drains, and the last one's reason. Both live on the runner
        #: rather than only in the log, because a status surface cannot read a log.
        self.consecutive_failures = 0
        self.last_error: str | None = None

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
            _LOG.info("the Wikipedia stream ended: %s", exc)

    def start(self) -> bool:
        """Start the stream thread. ``False`` when the setting does not say ``running``."""
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

    def stop(self, *, timeout: float = 5.0) -> None:
        """Ask the stream thread to end and wait briefly. Idempotent."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

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
        budget = self._budget()
        hot = self._hot_sets()
        lane_cm = self._lane_session()
        corpus_cm = self._corpus_session() if self._corpus_session is not None else None
        with lane_cm as lane:
            if corpus_cm is None:
                report = drain_once(lane, self._adapter, hot_sets=hot, budget=budget)
            else:
                with corpus_cm as corpus:
                    report = drain_once(
                        lane, self._adapter, hot_sets=hot, budget=budget, corpus=corpus
                    )
        self.last_drain = report.as_dict()
        self.drains += 1
        return report

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
                self.drain()
                self.consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001 - one bad drain must not end the lane
                # A LOOP THAT LETS ONE FAILURE END THE THREAD stops collecting for the
                # rest of the process with no record anywhere -- measured: an absent
                # lane file killed this thread and the stream kept filling a buffer
                # nobody was draining. Named, counted, and retried.
                self.consecutive_failures += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                _LOG.warning(
                    "the wiki lane drain failed (%d in a row): %s",
                    self.consecutive_failures, exc, exc_info=True,
                )
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    # AND A LOOP THAT RETRIES FOREVER is the same failure wearing the
                    # opposite face: it burns a core on an error that is not going to
                    # clear and buries the one log line that said why. Stopping with the
                    # reason on the runner is what a status surface can show.
                    _LOG.error(
                        "the wiki lane stopped after %d consecutive failed drains: %s",
                        self.consecutive_failures, self.last_error,
                    )
                    self._stop.set()
                    break
                self._sleep(self._interval)
                continue
            # AFTER the drain, deliberately. The drain is the lane's job; the attention
            # signal is a top-up for the NEXT one, and running it first would delay
            # storing what the stream already handed us in order to fetch something
            # nothing is waiting for.
            self.refresh_one_pageview_top()
            done += 1
            if self._should_stop():
                break
            if max_drains is not None and done >= max_drains:
                break
            self._sleep(self._interval)
        return done
