"""A compute that straddles a corpus swap is not cached, whatever its own checks said (the reader's race on #1500).

``served_cache.invalidate()`` clears the cache and runs the hooks that forget what a module carried beside it, but a compute that was
already running stored its payload afterwards: the window between a compute's last own check and ``_store`` is microseconds, yet a
swap (a restore, the panic wipe) that lands in it left the OLD file's numbers cached under a bind that is the same engine object, and
with no write since, the entry was then re-stamped ``verified_current`` on every poll. ``invalidate()`` now bumps a generation under
the cache's lock, ``refresh`` and the inline cold path capture it before the compute reads anything, and ``_store`` refuses under the
same lock when it has moved. These tests put the swap AFTER the compute's last statement (a wrapper around the compute), which is the
only place the per-module checks cannot see, for the key families that carry no check of their own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time

import pytest

from src.api import database as dbmod
from src.api import library as libmod
from src.api import served_cache
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
        src = Source(name="gen-src", domain="gen.test")
        s.add(src)
        s.flush()
        s.add(Article(title="t", url="http://gen.test/1", canonical_url="http://gen.test/1", source_id=src.id,
                      content="c", hash="gen-h1", word_count=10))
        s.commit()
    finally:
        s.close()


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _entry(key):
    with served_cache._LOCK:
        e = served_cache._CACHE.get(key)
        return dict(e) if e else None


def _swap_after(compute):
    """The compute, then the swap: the invalidate lands after the compute's last statement and before the store."""

    def wrapped(session):
        out = compute(session)
        served_cache.invalidate()  # what swap_in_corpus and the panic wipe do
        return out

    return wrapped


def test_a_normal_compute_is_still_stored_and_a_background_one_too():
    """Negative space: the generation changes nothing where nothing was invalidated."""
    s = SessionLocal()
    try:
        out = served_cache.cached("t:plain", lambda _s: {"n": 1}, s, ttl_s=60)
        assert out["n"] == 1 and _entry("t:plain") is not None
        assert served_cache.refresh("t:bg", lambda _s: {"n": 2}) == {"n": 2}
        assert _entry("t:bg") is not None
    finally:
        s.close()


def test_the_inline_cold_path_answers_the_asker_but_does_not_cache_a_compute_a_swap_straddled():
    s = SessionLocal()
    try:
        out = served_cache.cached("t:inline", _swap_after(lambda _s: {"n": 7}), s, ttl_s=60)
    finally:
        s.close()
    assert out["n"] == 7, "the asker still gets its answer"
    assert _entry("t:inline") is None, "the old file's payload was cached after the swap"


def test_the_background_refresh_does_not_cache_a_compute_a_swap_straddled():
    served_cache.refresh("t:bg-swap", _swap_after(lambda _s: {"n": 3}))
    assert _entry("t:bg-swap") is None


def test_invalidating_one_key_leaves_another_keys_compute_alone():
    """A keyed invalidate bumps only that key's generation in the served cache, so another key's store is not refused for it (the module hooks run whatever the key, and no caller uses a keyed invalidate today)."""

    def other_key_swap(session):
        served_cache.invalidate("t:a")
        return {"n": 5}

    served_cache.refresh("t:b", other_key_swap)
    assert _entry("t:b") is not None
    served_cache.refresh("t:a", other_key_swap)
    assert _entry("t:a") is None


def test_database_stats_does_not_cache_a_compute_a_swap_straddled(monkeypatch):
    _seed_article()
    real = dbmod._cached
    monkeypatch.setattr(dbmod, "_cached", lambda key, compute, db: real(key, _swap_after(compute), db))
    s = SessionLocal()
    try:
        out = dbmod.database_stats(s)
    finally:
        s.close()
    assert out["counts"], "the asker got the numbers"
    assert _entry("db:stats") is None, "db:stats cached the swapped-out file's counts"


def test_library_overview_does_not_cache_a_compute_a_swap_straddled(monkeypatch):
    real = libmod._cached
    monkeypatch.setattr(libmod, "_cached", lambda key, compute, db: real(key, _swap_after(compute), db))
    s = SessionLocal()
    try:
        out = libmod.library_overview(s)
    finally:
        s.close()
    assert isinstance(out, dict)
    assert _entry("library:overview") is None, "library:overview cached the swapped-out file's counts"


def test_the_library_figures_do_not_cache_a_count_a_swap_straddled_after_the_modules_own_check(monkeypatch):
    """The figures' own generation guards the count; this is the gap after it, between the finished compute and the store."""
    _seed_article()
    dbmod._MENTIONS_MEMO.clear()
    real = dbmod._compute_figures_counted

    def swap_after_all_checks(session, now):
        out = real(session, now)
        served_cache.invalidate()
        return out

    monkeypatch.setattr(dbmod, "_compute_figures_counted", swap_after_all_checks)
    monkeypatch.setattr(dbmod, "_mentions_count", lambda _db: 12)
    s = SessionLocal()
    try:
        dbmod.library_figures(s)
        assert _wait(lambda: not served_cache._build_lock("db:figures").locked())
        time.sleep(0.2)
    finally:
        s.close()
    assert _entry("db:figures") is None, "the figures cached a payload computed across a swap"
