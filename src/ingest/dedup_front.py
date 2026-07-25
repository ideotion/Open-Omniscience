"""
In-memory dedup front — a bounded, LRU-evicted EXACT seen-set placed in front of
the DB dedup read (2026-07-24 throughput brief, C12/A2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

At the field-measured ~90-92% duplicate rate (the same article re-served across
successive RSS polls), the existing dedup check (``pipeline._exists``) pays a
SQLCipher codec decrypt on EVERY check, even though the answer is almost always
"yes, already stored" for content ingested minutes-to-hours ago. This module is
a cheap, in-process front cache letting that overwhelming common case skip the
DB round-trip entirely.

THE SAFETY GUARANTEE (mandatory negative-space property — NEVER a false
negative, so dedup can never silently be lost and a duplicate article can never
be stored twice): the structure is an EXACT set (never a probabilistic Bloom
filter) — a key enters it ONLY once CONFIRMED to exist (either a fresh store,
or a DB read that found it), so a HIT is unconditionally trustworthy and may
skip the real check without any further verification. It is bounded +
LRU-evicted, so a MISS is NEVER trusted as proof of absence: eviction is the
only imprecision this structure can introduce, and it only ever produces a
false NEGATIVE (a genuinely-stored older item aged out of the front), never a
false positive. Every caller MUST treat a miss as "unknown — go verify", never
as "definitely new"; this is what keeps the combined (front + authoritative DB
check) system exact — a Bloom filter's own false-positive risk (which COULD
silently suppress a genuinely new article) is deliberately avoided by choosing
an exact structure instead, at negligible extra memory cost for compact
URL/hash keys.

KNOWN, BOUNDED, SELF-HEALING LIMITATION (disclosed, not hidden): the front is
purely in-PROCESS memory (never persisted), so it is empty after every
restart -- staleness can only ever accumulate WITHIN one running process. A
live bulk-delete of Article rows (e.g. the operator-triggered "remove imported
newsletters" action) does not invalidate this front, so a key for a
just-deleted row could still read as a front HIT until it naturally ages out
of the bounded LRU window or the app restarts -- a re-scrape of that exact URL/
content would be transiently (and incorrectly) treated as an existing
duplicate for that narrow window. This is a deliberate scope choice: coupling
every bulk-delete path across the codebase to this cache would widen C12 far
beyond its ingest-hot-path brief, and the failure mode here is bounded + self-
healing (never permanent data loss -- the source is retried every future pass
regardless) rather than the silent-permanent-loss class this project's other
data-safety guards exist to prevent.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict


class BoundedSeenSet:
    """A thread-safe, exact, LRU-bounded "have we seen this key before" cache.

    ``__contains__`` is a hit-only-if-actually-added lookup (never a false
    positive); a miss is NOT proof of absence (see the module docstring) — the
    caller must always fall back to an authoritative check on a miss.
    """

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._data: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def __contains__(self, key: str) -> bool:
        if not key:
            return False
        with self._lock:
            hit = key in self._data
            if hit:
                self._data.move_to_end(key)  # LRU touch: keep hot keys warm
            return hit

    def add(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return
            self._data[key] = None
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)  # evict the least-recently-seen key

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


def _front_size() -> int:
    try:
        return max(1, int(os.getenv("OO_DEDUP_FRONT_SIZE", "50000")))
    except (TypeError, ValueError):
        return 50000


# Two SEPARATE fronts: canonical URLs and content hashes are different keyspaces
# (they never collide by construction, but keeping them apart also matches
# pipeline._exists's two distinct filter shapes exactly — no key ever needs to
# carry which kind it is).
_seen_canonical_url = BoundedSeenSet(maxsize=_front_size())
_seen_content_hash = BoundedSeenSet(maxsize=_front_size())


def seen_canonical_url() -> BoundedSeenSet:
    return _seen_canonical_url


def seen_content_hash() -> BoundedSeenSet:
    return _seen_content_hash


def mark_stored(*, canonical_url: str | None = None, content_hash: str | None = None) -> None:
    """Populate the front(s) for a key JUST CONFIRMED to exist — either a fresh
    store or an authoritative DB read that found it. Either argument may be
    omitted (a caller checking only one keyspace need not populate the other)."""
    if canonical_url:
        _seen_canonical_url.add(canonical_url)
    if content_hash:
        _seen_content_hash.add(content_hash)


def _reset_for_tests() -> None:
    """Drop both in-process fronts (test hook) — module-level state would
    otherwise leak seen-keys across tests."""
    _seen_canonical_url._data.clear()
    _seen_content_hash._data.clear()
