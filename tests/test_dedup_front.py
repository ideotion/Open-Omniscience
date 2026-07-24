"""
C12 (2026-07-24 throughput brief, A2): the in-memory dedup front's pure
BoundedSeenSet primitive.

The end-to-end "never a false negative" property (the mandatory
negative-space guarantee) is tested at the WIRING level in
``tests/test_pipeline_dedup_front.py`` — this file covers the standalone cache
primitive: exact hit/miss (no false positive, ever), LRU eviction + recency
touch on both ``__contains__`` and ``add``, and ``mark_stored``'s dual-front
population.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ingest.dedup_front import BoundedSeenSet, mark_stored, seen_canonical_url, seen_content_hash

# NOTE: the conftest.py autouse `_dedup_front_isolated` fixture already resets
# both fronts before/after EVERY test in the suite (the same order-dependent-
# pollution guard the write-gate/memory-guard fixtures use) -- no local reset
# needed here.


def test_maxsize_must_be_positive():
    with pytest.raises(ValueError):
        BoundedSeenSet(maxsize=0)


def test_miss_before_any_add():
    s = BoundedSeenSet(maxsize=10)
    assert "a" not in s
    assert len(s) == 0


def test_add_then_contains_is_an_exact_hit():
    s = BoundedSeenSet(maxsize=10)
    s.add("key-1")
    assert "key-1" in s
    assert "key-2" not in s  # never a false positive for an unadded key


def test_never_a_false_positive_for_a_similar_but_distinct_key():
    s = BoundedSeenSet(maxsize=10)
    s.add("https://example.test/a")
    assert "https://example.test/a/" not in s  # trailing slash -- a DIFFERENT string
    assert "https://example.test/a" in s


def test_empty_key_is_never_added_and_never_a_hit():
    s = BoundedSeenSet(maxsize=10)
    s.add("")
    assert "" not in s
    assert len(s) == 0


def test_eviction_drops_the_least_recently_seen_key():
    s = BoundedSeenSet(maxsize=3)
    s.add("a")
    s.add("b")
    s.add("c")
    s.add("d")  # exceeds maxsize -- must evict "a" (the oldest, never touched since)
    assert "a" not in s
    assert "b" in s and "c" in s and "d" in s
    assert len(s) == 3


def test_a_contains_check_refreshes_recency_and_protects_from_eviction():
    s = BoundedSeenSet(maxsize=3)
    s.add("a")
    s.add("b")
    s.add("c")
    assert "a" in s  # touch -- "a" is now the MOST recently seen
    s.add("d")  # must evict "b" (now the oldest), not "a"
    assert "a" in s
    assert "b" not in s
    assert "c" in s and "d" in s


def test_re_adding_an_existing_key_refreshes_recency_without_growing():
    s = BoundedSeenSet(maxsize=3)
    s.add("a")
    s.add("b")
    s.add("c")
    s.add("a")  # re-add -- refresh, not a new entry
    assert len(s) == 3
    s.add("d")  # must evict "b" (now oldest), not "a"
    assert "a" in s and "b" not in s


def test_mark_stored_populates_the_matching_front_only():
    mark_stored(canonical_url="https://example.test/x")
    assert "https://example.test/x" in seen_canonical_url()
    assert len(seen_content_hash()) == 0

    mark_stored(content_hash="deadbeef")
    assert "deadbeef" in seen_content_hash()
    assert "deadbeef" not in seen_canonical_url()


def test_mark_stored_can_populate_both_at_once():
    mark_stored(canonical_url="https://example.test/y", content_hash="cafebabe")
    assert "https://example.test/y" in seen_canonical_url()
    assert "cafebabe" in seen_content_hash()


def test_mark_stored_with_neither_argument_is_a_safe_no_op():
    mark_stored()  # must not raise
    assert len(seen_canonical_url()) == 0
    assert len(seen_content_hash()) == 0
