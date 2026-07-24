"""
Archive backfill — a source's sitemap-enumerated HISTORY, as a scheduler
ride-along (2026-07-24 throughput brief, C15 / S-E slice 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A feed only ever shows the latest 10-50 items; the day a source QUALIFIES it
still has its entire prior publication history sitting in its sitemap,
invisible to every future RSS poll. This module offers a BOUNDED auto-backfill
(the sitemap module's own ~500-page default) for every newly-qualified source,
plus an explicit, separately-invoked FULL-HISTORY option — never triggered
automatically, since a full sitemap can run into the tens of thousands of URLs.

Design, mirroring the house pattern (src.catalog.discover_job's world-discovery
ride-along, src.ingest.import_job's persisted-cursor folder import):

  * a PERSISTED JSON cursor (data_dir()/archive_backfill.json) -- a FIFO queue
    of sources awaiting backfill, plus the one currently-ACTIVE source's own
    enumerated URL list + cursor into it. Both survive an app restart (the
    ride-along is a stateless function re-reading the file every call, so
    there is no separate in-memory manager object to lose);
  * ONE bounded slice of work per call (``per_pass``): either enumerating ONE
    newly-active source's sitemap, OR fetching up to ``per_pass`` of its
    URLs -- never both in the same call, so every tick's cost stays bounded;
  * every fetch runs through the STANDARD ingest_url()/store_fetched() pipeline
    (never a bypass) -- so per-host politeness (the fetcher's own host lock),
    robots (fail-closed), the non-article gate, dedup, and paywall/extraction
    failures are all inherited for free, exactly as they are for live
    collection. A paywalled/thin page is honestly tallied as a failure, never
    silently accepted as "stored" (no circumvention);
  * ``created_at`` (ingest time = now) vs ``published_at`` (the page's own
    declared date, parsed by the SAME extractor every live-collected article
    uses) keeps backfilled history honestly distinct from live collection --
    no special-casing needed, it falls out of using the same store path;
  * scheduled on the KindLadder's LOWEST rung (src.scheduler.runner, below
    even the crawl-supplement rung) -- live collection is never starved by a
    newly-qualified source's multi-hundred-page history.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

_STATE_FILENAME = "archive_backfill.json"


def _default_state_path() -> Path:
    from src.paths import data_dir

    return data_dir() / _STATE_FILENAME


def load_state(state_path: Path | None = None) -> dict:
    """The persisted queue/cursor ({} when nothing has ever been enqueued or
    the file is unreadable -- a missing/corrupt state file just means "start
    fresh with an empty queue", never a fabricated backlog)."""
    p = state_path or _default_state_path()
    try:
        data = json.loads(p.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - a missing/corrupt cursor just means "start fresh"
        return {}


def _save_state(state: dict, state_path: Path | None = None) -> None:
    """Atomic write (tmp + os.replace) so a crash mid-save never corrupts the cursor."""
    p = state_path or _default_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, p)


def enqueue_source(
    source_id: int, *, full_history: bool = False, state_path: Path | None = None
) -> dict:
    """Queue ``source_id`` for a backfill. Idempotent -- a source already
    queued, actively backfilling, or already done is left untouched (never a
    duplicate entry, never restarting a completed backfill silently).

    ``full_history`` (explicit per-source consent, NEVER set by the automatic
    qualification-success caller) requests the sitemap module's own larger
    enumeration ceiling instead of the bounded ~500-page default -- still
    size-bounded (see ``_enumerate``), never literally unbounded.
    """
    state = load_state(state_path)
    queue: list[dict] = list(state.get("queue", []))
    active = state.get("active") or {}
    done: set[int] = {int(x) for x in state.get("done_sources", [])}
    if source_id in done or active.get("source_id") == source_id:
        return {"enqueued": False, "reason": "already backfilled or in progress"}
    if any(int(q["source_id"]) == source_id for q in queue):
        return {"enqueued": False, "reason": "already queued"}
    queue.append({"source_id": int(source_id), "full_history": bool(full_history)})
    state["queue"] = queue
    _save_state(state, state_path)
    return {"enqueued": True, "queue_position": len(queue)}


def _enumerate(fetcher, source, *, full_history: bool) -> list[str]:
    """Sitemap-enumerate one source's history, bounded. ``full_history`` raises
    the ceiling well above the module default but stays FINITE (never a
    pathological huge sitemap index consuming unbounded memory/time in one
    enumeration call -- the brief's own stated risk)."""
    from src.ingest.sitemap import discover_sitemap_urls

    if full_history:
        report = discover_sitemap_urls(fetcher, source.domain, max_sitemaps=50, max_urls=5000)
    else:
        report = discover_sitemap_urls(fetcher, source.domain)  # the module's own ~500-page default
    return list(report.urls)


def advance_backfill(
    session,
    fetcher,
    *,
    per_pass: int,
    state_path: Path | None = None,
    ingest_fn=None,
    discover_fn=None,
) -> dict:
    """The scheduler RIDE-ALONG: advance the persisted backfill queue/cursor a
    bounded amount per online collection pass, through the SAME guarded
    transport the pass itself uses.

    Skips honestly (named in the returned dict) when: the budget is 0 (the
    off switch, ``archive_backfill_per_pass=0``) or airplane mode is engaged.
    Best-effort by contract -- the caller wraps this so a failure never breaks
    a scrape. ``ingest_fn``/``discover_fn`` are test seams (default to the real
    ``ingest_url``/``_enumerate``).
    """
    if per_pass <= 0:
        return {"enabled": False}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode engaged"}

    from src.database.models import Source

    ingest = ingest_fn or _real_ingest
    discover = discover_fn or _enumerate

    state = load_state(state_path)
    queue: list[dict] = list(state.get("queue", []))
    active: dict | None = state.get("active") or None
    done: list[int] = list(state.get("done_sources", []))

    if not active:
        if not queue:
            return {"enabled": True, "skipped": "queue is empty"}
        entry = queue.pop(0)
        state["queue"] = queue
        sid = int(entry["source_id"])
        source = session.query(Source).filter_by(id=sid).first()
        if source is None:
            # The source vanished since it was queued -- nothing to backfill;
            # move on (bounded to ONE queue advance this tick, never a spin
            # through a possibly-large stale backlog in one call).
            _save_state(state, state_path)
            return {"enabled": True, "source_id": sid, "skipped": "source no longer exists"}
        try:
            urls = discover(fetcher, source, full_history=bool(entry.get("full_history")))
        except Exception:  # noqa: BLE001 - one source's enumeration failure must not abort the queue
            _LOG.warning("archive backfill: sitemap enumeration failed for %r", source.domain,
                         exc_info=True)
            urls = []
        if not urls:
            done.append(sid)
            state["done_sources"] = done
            _save_state(state, state_path)
            return {"enabled": True, "source_id": sid, "urls_found": 0, "done": True}
        state["active"] = {
            "source_id": sid, "urls": urls, "cursor": 0,
            "full_history": bool(entry.get("full_history")), "tally": {},
        }
        _save_state(state, state_path)
        # Enumeration alone fills this tick's bounded work -- fetching starts
        # on the NEXT call, keeping every tick's cost predictable.
        return {"enabled": True, "source_id": sid, "urls_found": len(urls), "enumerated": True}

    sid = int(active["source_id"])
    source = session.query(Source).filter_by(id=sid).first()
    if source is None:
        done.append(sid)
        state["done_sources"] = done
        state["active"] = None
        _save_state(state, state_path)
        return {"enabled": True, "source_id": sid, "skipped": "source no longer exists", "done": True}

    active_urls: list[str] = active["urls"]
    cursor = int(active["cursor"])
    tally: dict[str, int] = dict(active.get("tally", {}))
    attempted = 0
    for url in active_urls[cursor : cursor + per_pass]:
        if kill_switch_active():
            break  # airplane mid-tick -- progress already made this loop is kept
        try:
            outcome = ingest(session, source, url, fetcher=fetcher)
            key = outcome.result.value if hasattr(outcome.result, "value") else str(outcome.result)
        except Exception:  # noqa: BLE001 - one URL's failure must not abort the tick
            key = "error"
            _LOG.warning("archive backfill: fetching %r failed", url, exc_info=True)
        tally[key] = tally.get(key, 0) + 1
        attempted += 1
    cursor += attempted
    done_now = cursor >= len(active_urls)
    if done_now:
        done.append(sid)
        state["done_sources"] = done
        state["active"] = None
    else:
        state["active"] = {**active, "cursor": cursor, "tally": tally}
    _save_state(state, state_path)
    return {
        "enabled": True, "source_id": sid, "attempted": attempted,
        "cursor": cursor, "total": len(active_urls), "tally": tally, "done": done_now,
    }


def _real_ingest(session, source, url, *, fetcher):
    from src.ingest.pipeline import ingest_url

    return ingest_url(session, source, url, fetcher=fetcher)
