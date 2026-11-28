"""What the last few passes did with each feed: a rolling per-source outcome counter (row 465, the field report's Q3 and Q11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. ``feed_fetch_state`` keeps the feed's last HTTP status and nothing about the entries behind it, so the November
field analysis could see 301 feeds that answer 200 and have never stored an article, and could not say why: every entry a
duplicate, every page a non-article, every fetch refused, or every extraction failing all look the same from the feed's row.

WHAT IT KEEPS. For each of the last :data:`OUTCOME_PASSES` passes that checked the feed, one short list of counts: how the
feed itself answered (one of :data:`FEED_OUTCOMES`) and how its entries ended (:data:`ENTRY_OUTCOMES`). Counts only: never
an address, a title, a status text or an exception's words. Stored as a compact JSON text in
``feed_fetch_state.recent_outcomes``, newest pass last. A pass that the de-churn back-off skipped, or whose feed request the
kill switch refused, or that a host's Crawl-delay put off, is not a pass for that feed (nothing was asked, Q1013 = a); a pass
a Stop cut short is not recorded either, since a Stop is the person's own setting and never writes the feed's row (R614). So
"offline" is never one of the counts: a pass the switch touched is not in the window at all.

WHY 8. A collection pass revisits a feed every few minutes to every few hours (the back-off caps at 6 h), so 8 checks span
from under an hour to about two days: long enough that one bad pass does not define a feed, short enough that a feed that
started working again stops reading as broken within a day or two. A stored value longer than 8 is cut to the newest 8 on the
next write.

THIS MACHINE'S OWN OBSERVATION. Like ``last_checked_at``, the counter says what THIS instance saw, so a restore never adopts
another instance's value (``src/backup/fetch_history.py`` lists it as omitted). A value that does not parse as this module
writes it reads as unreadable (:func:`parse` returns ``None``), never as zero passes.
"""

from __future__ import annotations

import json
from typing import Any

#: How many of a feed's most recent checked passes are kept (see the module docstring for why 8).
OUTCOME_PASSES = 8

#: How the feed itself answered on a pass. ``read`` = a 200 that was parsed; ``not_modified`` = a 304; ``http_4xx`` /
#: ``http_5xx`` = a failed check with that class of HTTP status; ``http_none`` = a failed check that named no HTTP status
#: (DNS, connect, TLS, timeout, a size or type refusal); ``robots`` = robots.txt refused the feed or could not be read. A
#: feed the kill switch refused, or a host's Crawl-delay put off, was not asked at all (Q1013 = a), so that pass is not one of
#: its passes, as a backed-off one is not.
FEED_OUTCOMES = ("read", "not_modified", "http_4xx", "http_5xx", "http_none", "robots")

#: How the feed's entries ended on a pass, counted. ``http_none`` is an entry fetch that failed with no 4xx or 5xx status;
#: ``robots`` sums a robots refusal and an unreadable robots.txt; ``deferred`` is a Crawl-delay deferral; ``store_error`` is
#: this app's own failure to store a page it fetched. There is no ``offline`` count: an entry the kill switch refused means
#: the switch was engaged during the pass, and such a pass is never recorded (R614), so the column could only ever read 0.
ENTRY_OUTCOMES = (
    "stored", "duplicate", "non_article", "extract_failed", "http_4xx", "http_5xx", "http_none", "robots", "deferred",
    "store_error",
)

#: One pass as stored: the feed outcome's index into :data:`FEED_OUTCOMES`, then one count per :data:`ENTRY_OUTCOMES`.
_PASS_LEN = 1 + len(ENTRY_OUTCOMES)
#: The longest text :func:`parse` reads: 8 passes of 12 numbers of up to 8 digits each, with room to spare.
MAX_TEXT = 1200

#: The method, as an identifier (it goes into report files; see collect_perf's METHOD for why not a sentence).
METHOD = (
    f"last_{OUTCOME_PASSES}_checked_passes;this_instance_only;backed_off_deferred_switch_refused_and_stopped_passes_not_counted;"
    "counts_only"
)


def _int(tally: dict, key: str) -> int:
    v = tally.get(key, 0)
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def entry_counts(tally: dict) -> list[int]:
    """One pass's entry counts in :data:`ENTRY_OUTCOMES` order, from :func:`src.ingest.pipeline.ingest_source`'s tally."""
    failed = _int(tally, "fetch_failed")
    # The per-reason keys (``ff:http_401``, ``ff:http_403``, ``ff:http_429``, ``ff:http_4xx``, ``ff:http_5xx``, ...) sum to
    # ``fetch_failed``, so the status classes are read from their prefixes and the rest is what named no such status.
    four = sum(_int(tally, k) for k in tally if isinstance(k, str) and k.startswith("ff:http_4"))
    five = sum(_int(tally, k) for k in tally if isinstance(k, str) and k.startswith("ff:http_5"))
    offline_failed = _int(tally, "ff:offline")
    counts = {
        "stored": _int(tally, "stored"),
        "duplicate": _int(tally, "duplicate"),
        "non_article": _int(tally, "non_article"),
        "extract_failed": _int(tally, "extract_failed"),
        "http_4xx": four,
        "http_5xx": five,
        "http_none": max(0, failed - four - five - offline_failed),
        "robots": _int(tally, "blocked_robots") + _int(tally, "robots_unavailable"),
        "deferred": _int(tally, "crawl_delay_deferred"),
        "store_error": _int(tally, "errors"),
    }
    return [counts[k] for k in ENTRY_OUTCOMES]


def feed_outcome_of_status(status: int) -> str:
    """The :data:`FEED_OUTCOMES` code of a failed feed check's recorded status (``0`` = no HTTP status)."""
    if 400 <= status < 500:
        return "http_4xx"
    if 500 <= status < 600:
        return "http_5xx"
    return "http_none"


def parse(raw: Any) -> list[list[int]] | None:
    """The stored passes, oldest first, or ``None`` when ``raw`` is absent or is not what :func:`appended` writes.

    Strict on purpose: a value is read only when it is a JSON list of at most :data:`OUTCOME_PASSES` lists, each of exactly
    the stored length, of non-negative integers, the first a valid feed-outcome index. Anything else is unreadable, never a
    partial or a guessed reading."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_TEXT:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, list) or len(value) > OUTCOME_PASSES:
        return None
    out: list[list[int]] = []
    for p in value:
        if not isinstance(p, list) or len(p) != _PASS_LEN:
            return None
        if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in p):
            return None
        if p[0] >= len(FEED_OUTCOMES):
            return None
        out.append([int(n) for n in p])
    return out


def appended(raw: Any, feed: str, counts: list[int] | None = None) -> str:
    """The stored text after one more pass: ``raw``'s passes (an unreadable value starts again empty) with this pass
    appended and only the newest :data:`OUTCOME_PASSES` kept. ``feed`` is a :data:`FEED_OUTCOMES` code; ``counts`` the
    entry counts (:func:`entry_counts`), all zero when the feed was never read."""
    passes = parse(raw) or []
    entries = list(counts) if counts is not None else [0] * len(ENTRY_OUTCOMES)
    if len(entries) != len(ENTRY_OUTCOMES):
        raise ValueError("entry counts must follow ENTRY_OUTCOMES")
    passes.append([FEED_OUTCOMES.index(feed), *(max(0, int(n)) for n in entries)])
    return json.dumps(passes[-OUTCOME_PASSES:], separators=(",", ":"))


def summary(raw: Any) -> list[int] | None:
    """The window summed, for an export row: ``[passes, <one count per FEED_OUTCOMES>, <one sum per ENTRY_OUTCOMES>]``;
    ``None`` when nothing is recorded or the value is unreadable (:func:`summary_columns` names the positions)."""
    passes = parse(raw)
    if not passes:
        return None
    feeds = [0] * len(FEED_OUTCOMES)
    entries = [0] * len(ENTRY_OUTCOMES)
    for p in passes:
        feeds[p[0]] += 1
        for i, n in enumerate(p[1:]):
            entries[i] += n
    return [len(passes), *feeds, *entries]


def summary_columns() -> list[str]:
    """The names of :func:`summary`'s positions, written once in an export beside the rows."""
    return ["passes", *(f"feed_{k}" for k in FEED_OUTCOMES), *ENTRY_OUTCOMES]


def main_outcome(raw: Any) -> str | None:
    """One short code for a class table: the entry outcome with the largest count over the window (ties go to the one
    listed first in :data:`ENTRY_OUTCOMES`); when no entry was counted at all, ``feed:<code>`` for the feed outcome seen
    most often. ``None`` when nothing is recorded or the value is unreadable."""
    s = summary(raw)
    if s is None:
        return None
    feeds = s[1:1 + len(FEED_OUTCOMES)]
    entries = s[1 + len(FEED_OUTCOMES):]
    if any(entries):
        best = max(range(len(entries)), key=lambda i: (entries[i], -i))
        return ENTRY_OUTCOMES[best]
    best = max(range(len(feeds)), key=lambda i: (feeds[i], -i))
    return "feed:" + FEED_OUTCOMES[best]
