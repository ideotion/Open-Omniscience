"""0.5.1 item 37: the Library figures' carried mentions count is about the file it was counted over, not about the engine object.

``/api/database/figures`` carries a finished whole-table count for ten times its own duration, keyed on the session's bind. A restore
swaps the file under the ONE module-level engine (and a VACUUM or a panic wipe changes the file the same way), so the bind alone said
"same database" about a different corpus. The count now rides the shape ``/api/insights/status`` has: engine object AND corpus epoch
AND a generation ``served_cache.invalidate()`` bumps, and a count that was running when the corpus was swapped is neither carried nor
cached.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.api import database as dbmod
from src.api import served_cache
from src.database.maintenance import StatementTimeout
from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db


def setup_module(_module):
    init_db()


@pytest.fixture(autouse=True)
def _clean():
    served_cache.invalidate()
    yield
    served_cache.invalidate()


def _seed_article():
    s = SessionLocal()
    try:
        if s.query(Article).count():
            return
        src = Source(name="ident-src", domain="ident.test")
        s.add(src)
        s.flush()
        s.add(Article(title="t", url="http://ident.test/1", canonical_url="http://ident.test/1", source_id=src.id,
                      content="c", hash="ident-h1", word_count=10))
        s.commit()
    finally:
        s.close()


def _count(monkeypatch, value=12):
    calls: list[int] = []

    def count(_db):
        calls.append(1)
        return value

    monkeypatch.setattr(dbmod, "_mentions_count", count)
    return calls


def _compute(s):
    return dbmod._compute_figures_counted(s, dbmod.datetime.now(dbmod.UTC))


def test_an_invalidate_forgets_the_carried_count_so_a_swapped_corpus_is_counted_afresh(monkeypatch):
    """A restore's swap keeps the engine object, so the bind check alone carried the old file's count as the new file's."""
    _seed_article()
    calls = _count(monkeypatch)
    s = SessionLocal()
    try:
        _compute(s)
        dbmod._MENTIONS_MEMO["count"] = 999_999  # stands in for the replaced corpus's count on the same engine object
        served_cache.invalidate()  # what run_restore's swap, a VACUUM and the panic wipe do
        assert dbmod._MENTIONS_MEMO == {}
        out = _compute(s)
    finally:
        s.close()
    assert out["keyword_mentions"] == 12 and len(calls) == 2, "the swapped corpus inherited the old count"


def test_a_count_made_at_another_corpus_epoch_is_not_carried(monkeypatch):
    from src.analytics.corpus_epoch import bump_corpus_epoch

    _seed_article()
    calls = _count(monkeypatch)
    s = SessionLocal()
    try:
        _compute(s)
        dbmod._MENTIONS_MEMO["count"] = 888_888
        with SessionLocal() as other:
            bump_corpus_epoch(other, reason="test")
            other.commit()
        out = _compute(s)
    finally:
        s.close()
    assert out["keyword_mentions"] == 12 and len(calls) == 2, "a count made at another epoch was carried"


def test_the_same_database_and_epoch_still_carries_the_count(monkeypatch):
    """Negative space: the identity is no stricter than it was where nothing changed."""
    _seed_article()
    calls = _count(monkeypatch)
    s = SessionLocal()
    try:
        _compute(s)
        dbmod._MENTIONS_MEMO["duration_s"] = 55.0
        out = _compute(s)
    finally:
        s.close()
    assert out["keyword_mentions"] == 12 and len(calls) == 1


def test_a_count_that_was_running_when_the_corpus_was_swapped_is_neither_carried_nor_cached(monkeypatch):
    _seed_article()
    calls: list[int] = []

    def swap_then_count(_db):
        calls.append(1)
        served_cache.invalidate()  # the restore's swap happens while this count is reading the old file
        return 12

    monkeypatch.setattr(dbmod, "_mentions_count", swap_then_count)
    s = SessionLocal()
    try:
        out = _compute(s)
    finally:
        s.close()
    assert dbmod._MENTIONS_MEMO == {}, "the count was taken over the file that was swapped out"
    assert out["__discard__"] is True and out["keyword_mentions"] == 12, "the asker still gets its answer, uncached"


def test_the_route_does_not_cache_a_count_that_was_running_across_a_swap(monkeypatch):
    import time

    _seed_article()

    def swap_then_count(_db):
        served_cache.invalidate()
        return 12

    monkeypatch.setattr(dbmod, "_mentions_count", swap_then_count)
    s = SessionLocal()
    try:
        dbmod.library_figures(s)
        end = time.monotonic() + 10
        while time.monotonic() < end and served_cache._build_lock("db:figures").locked():
            time.sleep(0.02)
        time.sleep(0.2)
    finally:
        s.close()
    with served_cache._LOCK:
        assert "db:figures" not in served_cache._CACHE, "the payload was served as 'counted' for a TTL"
    assert dbmod._MENTIONS_MEMO == {}


def test_the_generation_is_read_before_the_first_read_of_the_database(monkeypatch):
    """An invalidate between the cheap figures and the count must not leave the count looking current."""
    _seed_article()
    _count(monkeypatch)
    real = dbmod._cheap_figures
    fired: list[int] = []

    def swap_after_cheap(db, now):
        out = real(db, now)
        if not fired:
            fired.append(1)
            served_cache.invalidate()
        return out

    monkeypatch.setattr(dbmod, "_cheap_figures", swap_after_cheap)
    s = SessionLocal()
    try:
        _compute(s)
    finally:
        s.close()
    assert dbmod._MENTIONS_MEMO == {}


def test_a_failure_recorded_across_a_swap_is_not_cached_but_an_ordinary_one_still_is(monkeypatch):
    _seed_article()

    def timeout_after_swap(_db):
        served_cache.invalidate()
        raise StatementTimeout("past its deadline")

    monkeypatch.setattr(dbmod, "_mentions_count", timeout_after_swap)
    s = SessionLocal()
    try:
        across = _compute(s)

        def timeout(_db):
            raise StatementTimeout("past its deadline")

        monkeypatch.setattr(dbmod, "_mentions_count", timeout)
        plain = _compute(s)
    finally:
        s.close()
    assert across["keyword_mentions_state"] == "failed" and across["__discard__"] is True
    assert plain["keyword_mentions_state"] == "failed" and "__discard__" not in plain and plain["__ttl_s__"] == dbmod._FIGURES_FAILURE_WINDOW_S
