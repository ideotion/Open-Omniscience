"""The bulk re-index page cache: grows on this thread's connections for the run, restores them, leaves the pool alone."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from src.analytics.reindex_cache import bulk_page_cache, reindex_cache_mb


@pytest.fixture()
def sess(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/c.db", poolclass=QueuePool, pool_size=2, connect_args={"check_same_thread": False})
    s = sessionmaker(bind=eng, future=True)()
    yield s
    s.close()
    eng.dispose()


def _cache(session) -> int:
    return int(session.execute(text("PRAGMA cache_size")).scalar())


def test_grows_for_the_block_and_restores_after(sess):
    before = _cache(sess)
    with bulk_page_cache(sess, 256) as applied:
        assert applied == 256
        assert _cache(sess) == -256 * 1024
        sess.commit()  # the connection goes back to the pool and comes out again
        assert _cache(sess) == -256 * 1024
    sess.rollback()
    assert _cache(sess) == before


def test_other_threads_checkouts_are_untouched(sess):
    seen = []
    with bulk_page_cache(sess, 256):
        def other():
            with sess.get_bind().connect() as c:
                seen.append(int(c.exec_driver_sql("PRAGMA cache_size").scalar()))
        t = threading.Thread(target=other)
        t.start()
        t.join()
    assert seen and seen[0] != -256 * 1024


def test_zero_means_untouched_and_never_shrinks(sess):
    before = _cache(sess)
    with bulk_page_cache(sess, 0) as applied:
        assert applied == 0
        assert _cache(sess) == before
    sess.rollback()
    sess.execute(text("PRAGMA cache_size=-2097152"))
    with bulk_page_cache(sess, 256):
        assert _cache(sess) == -2097152


def test_env_override_and_typo(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_CACHE_MB", "0")
    assert reindex_cache_mb() == 0
    monkeypatch.setenv("OO_REINDEX_CACHE_MB", "300")
    assert reindex_cache_mb() == 300
    monkeypatch.setenv("OO_REINDEX_CACHE_MB", "lots")
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: 16000.0)
    assert reindex_cache_mb() == 1000  # a typo falls to the default, not to off
    monkeypatch.delenv("OO_REINDEX_CACHE_MB")
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: 2000.0)
    assert reindex_cache_mb() == 0
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: None)
    assert reindex_cache_mb() == 0
