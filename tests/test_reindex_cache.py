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


def test_a_raising_block_still_gives_the_connection_back_as_it_was(sess):
    before = _cache(sess)
    sess.rollback()
    with pytest.raises(RuntimeError), bulk_page_cache(sess, 256):
        assert _cache(sess) == -256 * 1024
        raise RuntimeError("boom")
    sess.rollback()  # the session's connection returns to the pool here
    sess.close()
    assert _cache(sess) == before


def test_leaving_the_block_checks_out_nothing(sess):
    assert not sess.in_transaction()
    with bulk_page_cache(sess, 256):
        sess.execute(text("SELECT 1"))
        sess.commit()
    assert not sess.in_transaction()
    assert sess.get_bind().pool.checkedout() == 0


def test_a_session_bound_to_a_connection_does_not_raise(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/d.db")
    with eng.connect() as conn:
        s = sessionmaker(bind=conn, future=True)()
        with bulk_page_cache(s, 256) as applied:
            assert applied in (0, 256)
        s.close()
    eng.dispose()


@pytest.mark.parametrize("size", [0, 256])
def test_the_original_exception_comes_through_unchanged(sess, size):
    with pytest.raises(KeyError, match="orig"), bulk_page_cache(sess, size):
        raise KeyError("orig")


def test_a_nested_block_raises_the_size_for_new_checkouts(sess):
    with bulk_page_cache(sess, 64), bulk_page_cache(sess, 256):
        sess.commit()
        sess.rollback()
        assert _cache(sess) == -256 * 1024


def test_a_nested_block_restores_the_true_original(sess):
    sess.execute(text("PRAGMA cache_size=-2000"))
    with bulk_page_cache(sess, 64):
        sess.execute(text("SELECT 1"))
        with bulk_page_cache(sess, 256):
            assert _cache(sess) == -256 * 1024
    sess.rollback()
    sess.close()
    assert _cache(sess) == -2000


def test_a_positive_page_count_is_left_alone(sess):
    sess.execute(text("PRAGMA cache_size=500000"))
    with bulk_page_cache(sess, 256):
        assert _cache(sess) == 500000


@pytest.mark.parametrize(
    ("kwargs", "expected_size"),
    [({"commit_batch": 200}, None), ({"commit_batch": 1}, 0), ({}, 0), ({"commit_batch": None}, 0)],
)
def test_reindex_articles_applies_the_cache_only_for_batched_commits(monkeypatch, kwargs, expected_size):
    import src.analytics.reindex_cache as rc
    import src.analytics.store as store

    seen = []

    @__import__("contextlib").contextmanager
    def fake(session, size_mb=None):
        seen.append(size_mb)
        yield 0

    monkeypatch.setattr(rc, "bulk_page_cache", fake)
    monkeypatch.setattr(store, "_reindex_articles_impl", lambda *a, **k: {"reindexed": 0, "failed": 0})
    store.reindex_articles(object(), extractor=None, article_ids=[], **kwargs)
    assert seen == [expected_size]
