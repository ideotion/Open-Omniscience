"""The process's ONE Wikipedia lane runner, assembled from the operator's settings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``runner.py`` is the mechanism with every moving part injected; this is the single
place that injects the REAL ones — the guarded session, the live ``WikiClient``, the
lane and corpus session factories, the HOT sets built from the operator's own corpus,
and the budget from their own setting. Keeping the assembly here is what lets the
runner be driven in a test from a recorded fixture with no sockets at all.

ONE RUNNER PER PROCESS, AND IT IS A SINGLETON FOR A REASON RATHER THAN A HABIT. Two
runners would hold two EventStreams connections to the same twelve editions, which is
rude to Wikimedia, double the bytes on the operator's line, and would have the two
drains racing to store the same changes. The lock is around construction AND teardown
so a start arriving during a stop cannot leave an orphan thread holding a socket.

IT IS NEVER STARTED BY THE BOOT PATH. The app boots into airplane mode and makes zero
calls; a lane that connected at boot would break that, and no consent popup would have
been shown. Starting is bound to the operator CROSSING ONLINE, which is the seam
``POST /api/system/network`` already calls "Online ⟺ collecting" — the same click that
starts the article collector starts this, under the same one consent popup (invariant
#14). Crossing offline stops it. So the lane's DEFAULT-ON setting (Q702's NOTE) is a
statement about what happens when the operator goes online, never a reason to go
online on their behalf.

WHAT IT DOES WHEN IT CANNOT RUN. An absent lane file, an unreadable setting or a
state that is not ``running`` all return ``False`` from :func:`start_wiki_lane` and
say why in the log. Nothing here raises into the caller: the network toggle must not
fail because a lane could not start, and it already treats the article scheduler the
same way.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_LOG = logging.getLogger("wiki.service")

_LOCK = threading.RLock()
# Held across a whole stop (detach AND join) and taken first by a start, so a start does not build
# a runner while a stop is still joining the old one. The join is bounded, so a drain already in
# progress (it is not interruptible: up to its fetch bound plus a request timeout) can still
# outlive it; the old thread then ends at its next stop check. Always taken before ``_LOCK``.
_STOP_LOCK = threading.RLock()
_RUNNER: Any = None
_DRAIN_THREAD: threading.Thread | None = None


def _settings():
    from src.scheduler.settings import load_settings

    return load_settings()


def _state_of() -> str:
    return str(getattr(_settings(), "wiki_lane_state", "stopped"))


def _editions() -> tuple[str, ...]:
    return tuple(getattr(_settings(), "wiki_lane_editions", ()) or ())


def _budget():
    """The budget as it stands right now: the operator's total, the file's real size."""
    from src.versioned.store import lane_file_bytes
    from src.wiki.tiers import budget_state

    settings = _settings()
    editions = tuple(getattr(settings, "wiki_lane_editions", ()) or ()) or ("en",)
    return budget_state(
        total_gb=int(getattr(settings, "wiki_lane_budget_gb", 150)),
        disk_bytes=lane_file_bytes("wiki"),
        editions=len(editions),
    )


@contextmanager
def wiki_lane_session() -> Iterator[Any]:
    """A session on the wiki lane, creating the lane WITH its schema on first use.

    Every wiki path opens its lane through here. They used to call
    ``lane_session("wiki", create=True)``, which brings the FILE into existence and
    nothing else (``src/law/lane_sync.py`` says so and calls ``create_lane``). On a
    fresh install that nothing had created the lane for, going online therefore left
    an EMPTY ``wiki.db``: every drain, hot-set build and pin failed on "no such table:
    versioned_entities", and the lane status and the briefing answered 500. It also
    stepped around ``create_lane``'s refusal to write a plaintext lane beside an
    encrypted corpus (Q1005). Found by S04-08's S5 walk, 2026-09-25.

    ``create_lane`` is idempotent, and it repairs an empty file an earlier build left.
    """
    from src.versioned.store import create_lane, lane_session

    create_lane("wiki")
    with lane_session("wiki") as lane:
        yield lane


#: The lane path whose schema THIS process has already ensured for the walk. Keyed on the
#: path, not a bare flag, for the reason ``store._engines`` is: a data folder that moves
#: (or a test that re-points ``OO_DATA_DIR``) is a different lane file.
_WALK_SCHEMA_READY: str | None = None


@contextmanager
def walk_lane_session() -> Iterator[Any]:
    """A session on the wiki lane for the walk: the schema ensured ONCE, then a plain session.

    ``wiki_lane_session`` runs ``create_lane`` on every open, which is right for a drain
    every thirty seconds and wasteful for a walk step every second or two -- it re-inspects
    every table each time. A lane file a 0.4 build wrote has no walk tables until this
    build's ``create_schema`` runs, so the first open still goes through it.
    """
    global _WALK_SCHEMA_READY
    from src.versioned.store import create_lane, lane_path, lane_session

    here = str(lane_path("wiki"))
    if here != _WALK_SCHEMA_READY:
        create_lane("wiki")
        _WALK_SCHEMA_READY = here
    with lane_session("wiki") as lane:
        yield lane


def _warm_enabled() -> bool:
    """WARM's switch, re-read every window, so turning it on or off needs no restart."""
    return bool(getattr(_settings(), "wiki_warm_enabled", False))


def _walk_enabled() -> bool:
    """The operator's walk switch, re-read every window so a change needs no restart."""
    return bool(getattr(_settings(), "wiki_walk_enabled", False))


def session_transport(session: Any) -> str:
    """How THIS session leaves the machine, in ``transport_summary``'s own tokens.

    Read from the session the walk actually uses rather than from the settings file: the
    session's transport was fixed when it was built, and a sample recorded under the
    setting as it reads NOW would misname every request made before a change.
    """
    if getattr(session, "transport_refusal", None):
        return "refused"
    if getattr(session, "proxy_pool", ()):
        return "pool"
    if getattr(session, "transport_proxy", None):
        return "proxy"
    return "direct"


def _hot_sets():
    """Rebuilt each drain from the operator's own corpus and lane. No network."""
    from src.config.kv_store import kv_get_json
    from src.database.session import SessionLocal
    from src.wiki.hotset import build_hot_sets, pageview_kv_key

    editions = _editions()
    tops: dict[str, set[str]] = {}
    for edition in editions:
        blob = kv_get_json(pageview_kv_key(edition)) or {}
        titles = blob.get("titles")
        if isinstance(titles, list):
            tops[edition] = {str(t) for t in titles if t}
    # Through ``wiki_lane_session``, like every lane session in this module: the FIRST
    # drain on a fresh install must find a lane with its schema (see that function).
    with SessionLocal() as corpus, wiki_lane_session() as lane:
        sets, _report = build_hot_sets(
            corpus=corpus, lane=lane, editions=editions, pageview_tops=tops
        )
    return sets


def _resume_from() -> str | None:
    """The stored stream position, so a restart resumes instead of replaying.

    ONE token for the whole stream, because EventStreams is one connection carrying
    every edition: the per-edition cursors in ``versioned_cursors`` say where each
    FEED was stored, and the ``Last-Event-ID`` says where the CONNECTION was. The
    newest stored token is the honest resume point — an older one replays, which the
    substrate's ``change_ref`` dedup makes free, while a newer one would skip.
    """
    from sqlalchemy import select

    from src.versioned.models import VersionedCursor
    from src.versioned.store import lane_path, lane_session

    if not lane_path("wiki").is_file():
        return None
    try:
        with lane_session("wiki") as lane:
            rows = lane.execute(
                select(VersionedCursor.token, VersionedCursor.updated_at)
                .where(VersionedCursor.token.is_not(None))
                .order_by(VersionedCursor.updated_at.desc())
                .limit(1)
            ).first()
        return str(rows[0]) if rows and rows[0] else None
    except Exception:  # noqa: BLE001 - an unreadable cursor is a cold start, not a crash
        _LOG.warning("could not read a stored stream position; starting cold", exc_info=True)
        return None


def _refresh_one_pageview_top(client: Any) -> str | None:
    """Q706's cadence in production: ONE due edition's top-1,000, at most once a day.

    THE STORE IS THE CORPUS KEY-VALUE TABLE, so the cached list inherits the corpus's
    encryption instead of sitting beside it as a plaintext file. The list itself is
    public — it is the same list for every reader in the world — but a file naming what
    this machine asked Wikimedia about is still one more thing on an operator's disk
    that nothing required.

    The DUE DAY is yesterday's, UTC (see ``pageviews.due_day``): the service aggregates
    a day after it ends, and asking for today returns nothing that a caller could tell
    apart from "nobody read anything".
    """
    from datetime import UTC, datetime

    from src.config.kv_store import kv_get_json, kv_set_json
    from src.wiki.hotset import pageview_kv_key
    from src.wiki.pageviews import due_day, fetch_top, is_due

    want = due_day(datetime.now(UTC))
    for edition in _editions():
        key = pageview_kv_key(edition)
        blob = kv_get_json(key) or {}
        stored = blob.get("day")
        try:
            last = datetime.strptime(str(stored), "%Y-%m-%d").date() if stored else None
        except ValueError:
            # An unreadable stored day is treated as NEVER FETCHED rather than as
            # today's: the cost of being wrong that way is one request, and the cost of
            # the other way is an edition that never refreshes again.
            last = None
        if not is_due(last, want):
            continue
        rows = fetch_top(client.session, edition, want)
        kv_set_json(
            key,
            {
                "day": want.isoformat(),
                "titles": [r["title"] for r in rows if r.get("title")],
                # The SOURCE's own figures, kept beside the titles rather than folded
                # into them: a rank is the service's ordinal and a view count is its
                # measurement, and this app computes neither.
                "rows": rows[:50],
                "n": len(rows),
            },
        )
        _LOG.info("refreshed the %s top-1,000 for %s (%d titles)", edition, want, len(rows))
        return edition
    return None


def _build():
    """Construct the runner with the real client, stream and sessions."""
    from src.database.session import SessionLocal
    from src.wiki.client import WikiClient
    from src.wiki.lane import WikiStreamAdapter
    from src.wiki.lane_search import LaneIndexer
    from src.wiki.runner import WikiLaneRunner
    from src.wiki.stream import WikiEventStream
    from src.wiki.walk import WikiWalker
    from src.wiki.warm import WarmFetcher

    editions = _editions()
    if not editions:
        raise ValueError("the Wikipedia lane has no editions configured")
    client = WikiClient()
    adapter = WikiStreamAdapter(client=client, editions=editions)
    # THE STREAM SHARES THE CLIENT'S GUARDED SESSION. Not a convenience: a second
    # session would be a second place the kill switch, the protected-mode proxy and
    # the honest User-Agent have to be wired, and the one that was forgotten is the
    # one that egresses. The non-negotiable is a SINGLE fetch path.
    stream = WikiEventStream(session=client.session, editions=editions)
    # THE WALK SHARES THE CLIENT TOO (Q701 = c, Q722 = b): the same session, so the same
    # transport and kill switch, and the same one-second interval between requests, so the
    # walk and the drain's text fetches are one polite client rather than two.
    walker = WikiWalker(
        client=client,
        editions=editions,
        lane_session=walk_lane_session,
        budget=_budget,
        enabled=_walk_enabled,
        transport=lambda: session_transport(client.session),
    )
    # WARM TOO (Q707): the same client, so one request at a time across the drain's text,
    # WARM and the walk, and one transport for all three.
    warm = WarmFetcher(
        client=client,
        editions=editions,
        lane_session=walk_lane_session,
        budget=_budget,
        enabled=_warm_enabled,
    )
    # THE SEARCH INDEX (R52) reads what the drain and WARM stored and requests nothing, so
    # it needs no client; it pays for its entries from the same budget as the texts. It also
    # reads the old page tracker's versions in ``corpus.db`` (R54), and only reads them.
    indexer = LaneIndexer(
        lane_session=walk_lane_session, budget=_budget, tracker_session=SessionLocal
    )
    return WikiLaneRunner(
        adapter=adapter,
        stream=stream,
        lane_session=wiki_lane_session,
        corpus_session=SessionLocal,
        state_of=_state_of,
        hot_sets=_hot_sets,
        budget=_budget,
        resume_from=_resume_from,
        pageviews=lambda: _refresh_one_pageview_top(client),
        walker=walker,
        warm=warm,
        indexer=indexer,
    )


def start_wiki_lane() -> bool:
    """Start the lane if the operator's setting says ``running``. Idempotent.

    Returns whether a runner is streaming afterwards. Never raises.

    EVERY WAY THE UI GOES ONLINE CALLS THIS (the airplane button, the collection Start and
    Run-now buttons, a settings write), so it has to be right for a lane in any state: not
    built (build it), streaming (nothing to do), built with its drain loop alive but its
    stream ended (start the stream again, keeping the loop and its counters), or built with
    nothing alive (tear the leftover down, then build). A second call that built a new runner
    beside a live drain thread would put two writers on one lane.
    """
    global _RUNNER, _DRAIN_THREAD
    with _STOP_LOCK, _LOCK:
        try:
            if _state_of() != "running":
                _LOG.info("the Wikipedia lane is not started: its setting does not say running")
                return False
            if _RUNNER is not None:
                drain_alive = _DRAIN_THREAD is not None and _DRAIN_THREAD.is_alive()
                # A live stream beside a DEAD drain loop is not a healthy lane: the stream fills
                # its bounded buffer and nothing stores it. It falls through to the teardown and
                # the rebuild below, with a fresh drain thread.
                if _RUNNER.streaming and drain_alive:
                    return True
                if drain_alive:
                    if _RUNNER.revive_stream():
                        return True
                    # Its loop is alive but it would not restart the stream (it was stopped,
                    # or the kill switch is engaged): rebuild only when it was stopped.
                    if not _RUNNER.stopped:
                        return False
                _finish(*_detach_locked(), 5.0)
            _RUNNER = _build()
            if not _RUNNER.start():
                return False
            _DRAIN_THREAD = threading.Thread(
                target=_RUNNER.run_until_stopped, name="oo-wiki-drain", daemon=True
            )
            _DRAIN_THREAD.start()
            _LOG.info("the Wikipedia lane is streaming %d editions", len(_editions()))
            return True
        except Exception:  # noqa: BLE001 - a lane that cannot start must not fail the toggle
            _LOG.warning("the Wikipedia lane could not start", exc_info=True)
            return False


def _detach_locked() -> tuple[Any, threading.Thread | None]:
    """Forget the runner and its drain thread, returning them. The caller holds ``_LOCK``."""
    global _RUNNER, _DRAIN_THREAD
    runner, _RUNNER = _RUNNER, None
    thread, _DRAIN_THREAD = _DRAIN_THREAD, None
    return runner, thread


def _finish(runner: Any, thread: threading.Thread | None, timeout: float) -> None:
    """Stop a detached runner and wait briefly for its drain thread. Never raises."""
    if runner is not None:
        try:
            runner.stop(timeout=timeout)
        except Exception:  # noqa: BLE001
            _LOG.warning("stopping the Wikipedia lane failed", exc_info=True)
    if thread is not None and thread.is_alive():
        # The drain loop ends at its next ``_should_stop`` check, which reads the
        # runner's own stop event. Joining briefly keeps a restart from overlapping
        # with the tail of the previous drain.
        thread.join(timeout=timeout)


def stop_wiki_lane(*, timeout: float = 5.0) -> None:
    """Stop the lane and forget the runner. Idempotent, and never raises.

    ``_LOCK`` is held only to detach: the join can take seconds and a status read must not
    wait behind it. ``_STOP_LOCK`` is held throughout, so a start waits for the old lane's tail.
    """
    with _STOP_LOCK:
        with _LOCK:
            runner, thread = _detach_locked()
        _finish(runner, thread, timeout)


def lane_runner() -> Any:
    """The current runner, or ``None``. For a status surface; never for starting one."""
    with _LOCK:
        return _RUNNER


def lane_history() -> dict:
    """The lane's own hourly history, whole, for a diagnostics bundle. Never raises.

    A lane that has no file, or an empty one, says so with a reason, which is not a reading of
    zero: the same refusal the soak window's lane block makes (``src/wiki/history.py``).
    """
    from src.versioned.store import lane_file_bytes, lane_path, lane_session
    from src.wiki import history

    base = {"retention_days": history.RETENTION_DAYS, "rows": []}
    try:
        if not lane_path("wiki").is_file() or not lane_file_bytes("wiki"):
            return {**base, "measured": False,
                    "reason": "the Wikipedia lane has never stored anything, so it has no history"}
        with lane_session("wiki") as lane:
            snap = history.snapshot(lane)
            # A lane file from before this build has no table yet: that is an unmeasured history
            # with a reason, never a measured one with no rows.
            return {"measured": "reason" not in snap, **snap}
    except Exception as exc:  # noqa: BLE001 - a diagnostic never fails the caller
        _LOG.warning("could not read the Wikipedia lane history", exc_info=True)
        return {**base, "measured": False, "reason": f"unreadable: {type(exc).__name__}"}


def lane_service_status() -> dict:
    """What THIS PROCESS is doing about the lane, measured rather than stored."""
    with _LOCK:
        runner = _RUNNER
        drain_alive = bool(_DRAIN_THREAD is not None and _DRAIN_THREAD.is_alive())
    if runner is None:
        return {"streaming": False, "draining": False, "drains": 0, "last_drain": None,
                "stream": None, "drain": None, "walk": None, "warm": None, "index": None}
    return {
        "streaming": bool(runner.streaming),
        "draining": drain_alive,
        "drains": int(runner.drains),
        "last_drain": runner.last_drain,
        # The stream's own counters (connections, failures in a row, the latest
        # failure, idle seconds): what the lane's status reads to say it is WAITING
        # and on what, rather than "running" while every connection fails.
        "stream": runner.stream_counters(),
        # Where the drain loop is (stage, edition, how long it has been in this drain, how
        # many failed in a row and why). ``drains: 0`` alone cannot say whether the first
        # drain is stuck, slow or failing.
        "drain": runner.drain_status(),
        # The walk's in-process state (walking, paused and why, waiting). Its COUNTS are
        # rows in the lane, read by ``src.wiki.walk.walk_coverage``; this is only what no
        # row holds. ``None`` for a runner built without a walker.
        "walk": runner.walk_status(),
        # WARM's in-process state, likewise; its counts are rows read by
        # ``src.wiki.warm.warm_coverage``.
        "warm": runner.warm_status(),
        # The search indexer's in-process state; its counts are rows read by
        # ``src.wiki.lane_search.index_status``.
        "index": runner.index_status(),
    }
