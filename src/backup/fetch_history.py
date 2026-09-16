"""What "the fetch / scrape history" IS, and what trusting a backup's copy means.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING (Q701 NOTE, 2026-09-15, verbatim): *"we need to incorporate EVERY page
request and download and history in backups so that a fresh install with an old backup
doesn't re-downloads the same pages over and prioritizes other downloads / fetches,
THIS IS TRUE NOT ONLY FOR WIKIPEDIA BUT FOR EVERYTHING DOWNLOADED WITH THE APP, web
fetch/web scrapping history should be backed-up, and at install and import, users
should be given the choice to trust or not the history with a 'trust the backup
scrapping history' toggle"*.

WHAT WAS ALREADY TRUE BEFORE THIS SLICE, measured rather than assumed, because the
honest size of the remaining gap decides what to build:

* **Press articles already do not re-download.** ``ingest_url`` checks
  ``_exists(session, canonical_url=...)`` BEFORE fetching
  (``src/ingest/pipeline.py:131``), and ``articles`` has always merged. So a restored
  corpus already suppresses a re-fetch of every article it holds.
* **The Wikipedia lane already does not re-download.** ``wiki_pages`` /
  ``wiki_revisions`` merge (``merge.py``'s wiki step), carrying ``latest_revid``, which
  is what decides whether a fetched revision is new.
* **The per-FEED history did not ride at all.** ``feed_fetch_state`` sat in
  ``_MERGE_NOT_CARRIED`` as "per-feed ETag/Last-Modified + backoff, re-learned on the
  next pass" -- a correct reading of it as per-machine state, and the one the Q701 note
  overturns. On a fresh install restored from a backup, every feed was re-downloaded in
  full on the first pass even though the corpus knew exactly what each server had last
  served. That is the gap this module closes.

WHAT IS STILL MISSING, stated because a partial answer presented as a whole one is how
a future session comes to believe a feature works: **there is no per-URL request log.**
A URL that was fetched and yielded NO article (a 404, a paywall, a page the extractor
refused) leaves no trace anywhere, so a fresh install re-fetches it. Building that table
is a new write path on the ingest hot path AND a row-model decision, and brief S04-04
SS6 reserves "what history is at the row level (a per-URL request log, per-page latest
revision, the per-feed state -- or all three)" to the maintainer. So this module is the
MECHANISM -- a registry, a trust gate and a report -- with today's honest membership in
it; a ruling adds a table to :data:`FETCH_HISTORY_TABLES` and the toggle already covers
it. The same applies to the OSM and law lanes as they land.
"""

from __future__ import annotations

#: table -> (what it records, what ADOPTING it changes for the next pass).
#:
#: Membership is the answer to "which tables does the trust toggle gate?", and it is
#: deliberately SMALL: a table already merged unconditionally because it is CONTENT
#: (``articles``, ``wiki_pages``) is not fetch history even though it suppresses a
#: re-fetch as a side effect -- untrusting the history must not delete the operator's
#: corpus. What belongs here is state whose only purpose is to decide whether to ask a
#: server again.
FETCH_HISTORY_TABLES: dict[str, tuple[str, str]] = {
    "feed_fetch_state": (
        "per-feed HTTP conditional-GET validators (ETag / Last-Modified), the last "
        "status seen, and the de-churn backoff counter + deadline",
        "the next pass sends If-None-Match / If-Modified-Since and can be answered "
        "304 instead of re-downloading the whole feed, and a feed the source corpus "
        "found unchanged stays backed off until its capped deadline expires",
    ),
}

#: The columns of ``feed_fetch_state`` an adoption CARRIES, and the one it does not.
#:
#: ``last_checked_at`` is deliberately left NULL on an adopted row. It answers "when did
#: THIS instance last check this feed", and ``src/scheduler/coverage.py`` reads it as
#: exactly that -- the per-tag reach the task manager's Coverage subtab reports. Copying
#: a foreign timestamp there would claim a check this machine never made, which is the
#: ``articles.keyword_indexed_at`` inversion the ledger already records. Nothing is lost
#: by omitting it: ``feed_is_due`` (``src/ingest/pipeline.py:619``) reads ``skip_until``
#: and NOTHING else, and the conditional-GET headers read ``etag`` / ``last_modified``
#: -- verified by reading both call sites, not assumed. So the fetch DECISION is fully
#: carried and the reach MEASUREMENT stays honest.
FEED_FETCH_STATE_CARRIED = (
    "etag",
    "last_modified",
    "last_status",
    "consecutive_unchanged",
    "skip_until",
)
FEED_FETCH_STATE_OMITTED: dict[str, str] = {
    "last_checked_at": (
        "when THIS instance last checked the feed; the coverage report reads it as this "
        "machine's reach, so a foreign timestamp would claim a check that never "
        "happened here. No fetch decision reads it (feed_is_due reads skip_until only)"
    ),
}


def resolve_trust_fetch_history(override: bool | None = None) -> bool:
    """Should this restore ADOPT the incoming corpus's fetch history?

    ``override`` is the per-import choice (the import dialog's toggle); ``None`` means
    "the operator did not choose for this import", which falls back to the persisted
    first-launch answer. ONE resolution order, in one place, so the two surfaces the
    Q701 note names cannot disagree about what the operator asked for.

    A settings-store failure resolves to the SHIPPED DEFAULT rather than to ``True``
    or ``False`` picked here: the default is the documented answer, and a read error
    must not quietly change what the app does with somebody's data.
    """
    if override is not None:
        return bool(override)
    try:
        from src.config.app_settings import load_settings

        return bool(load_settings().trust_backup_fetch_history)
    except Exception:  # noqa: BLE001 - a settings read must never break a restore
        from src.config.app_settings import AppSettings

        return bool(AppSettings().trust_backup_fetch_history)
