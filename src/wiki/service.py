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
        total_gb=int(getattr(settings, "wiki_lane_budget_gb", 20)),
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
    from src.wiki.runner import WikiLaneRunner
    from src.wiki.stream import WikiEventStream

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
    )


def start_wiki_lane() -> bool:
    """Start the lane if the operator's setting says ``running``. Idempotent.

    Returns whether a runner is streaming afterwards. Never raises.
    """
    global _RUNNER, _DRAIN_THREAD
    with _LOCK:
        try:
            if _state_of() != "running":
                _LOG.info("the Wikipedia lane is not started: its setting does not say running")
                return False
            if _RUNNER is not None and _RUNNER.streaming:
                return True
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


def stop_wiki_lane(*, timeout: float = 5.0) -> None:
    """Stop the lane and forget the runner. Idempotent, and never raises."""
    global _RUNNER, _DRAIN_THREAD
    with _LOCK:
        runner, _RUNNER = _RUNNER, None
        thread, _DRAIN_THREAD = _DRAIN_THREAD, None
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


def lane_runner() -> Any:
    """The current runner, or ``None``. For a status surface; never for starting one."""
    with _LOCK:
        return _RUNNER


def lane_service_status() -> dict:
    """What THIS PROCESS is doing about the lane, measured rather than stored."""
    with _LOCK:
        runner = _RUNNER
        drain_alive = bool(_DRAIN_THREAD is not None and _DRAIN_THREAD.is_alive())
    if runner is None:
        return {"streaming": False, "draining": False, "drains": 0, "last_drain": None,
                "stream": None}
    return {
        "streaming": bool(runner.streaming),
        "draining": drain_alive,
        "drains": int(runner.drains),
        "last_drain": runner.last_drain,
        # The stream's own counters (connections, failures in a row, the latest
        # failure, idle seconds): what the lane's status reads to say it is WAITING
        # and on what, rather than "running" while every connection fails.
        "stream": runner.stream_counters(),
    }
