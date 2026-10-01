"""api_headroom counts the slots that are REALLY free, not only the ones the reservation promises.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

D44's arithmetic ("cap 8, pool 12, margin 4") promises the app four connections. It cannot free a
slot another app thread is sitting on: the status probe kept one for the life of the process (now
detached, tests/test_status_probe_detached.py), and a slow article list holds one for minutes. The
pool's own standing-holder reading (``pool_watch.standing_holders``) is now subtracted, so
``sufficient`` is a statement about the pool as it is. The default (nothing held) is the pure
arithmetic, unchanged.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from src.config import memory_budget as mb
from src.database import pool_watch
from src.database.pool_reserve import ReservingQueuePool, collector_role


def test_the_default_is_the_pure_arithmetic_and_unchanged():
    v = mb.api_headroom_for(8, pool_total=12)
    assert (v["headroom"], v["sufficient"], v["standing_holders"]) == (4, True, 0)
    assert v["headroom_before_standing"] == 4


def test_one_standing_holder_turns_the_small_tier_verdict_insufficient():
    v = mb.api_headroom_for(8, pool_total=12, standing=1)
    assert v["headroom_before_standing"] == 4 and v["headroom"] == 3
    assert v["standing_holders"] == 1
    assert v["sufficient"] is False, "3 really free against a margin of 4 is not sufficient"
    assert "1 connection(s)" in v["method"]


def test_a_negative_standing_reading_is_treated_as_none():
    assert mb.api_headroom_for(8, pool_total=12, standing=-3)["headroom"] == 4


@pytest.fixture()
def eng(tmp_path):
    e = create_engine(
        f"sqlite:///{tmp_path / 'sh.db'}", future=True, poolclass=ReservingQueuePool,
        pool_size=4, max_overflow=0, pool_timeout=1,
    )
    pool_watch.register(e)
    pool_watch._reset_for_tests()
    yield e
    e.dispose()


def test_standing_holders_counts_old_non_collector_checkouts_only(eng):
    app_thread = eng.connect()  # an app thread's checkout (not the collector)
    with collector_role():
        collector = eng.connect()
    try:
        rows = {bool(r["collector"]) for r in pool_watch.checked_out()}
        assert rows == {True, False}
        assert pool_watch.standing_holders(min_age_s=0.0) == 1, "the collector's is the reservation's"
        assert pool_watch.standing_holders(min_age_s=3600.0) == 0, "young checkouts are ordinary traffic"
    finally:
        app_thread.close()
        collector.close()
    assert pool_watch.standing_holders(min_age_s=0.0) == 0


def test_an_unattached_instrument_reads_none_not_zero(monkeypatch):
    monkeypatch.setattr(pool_watch, "_REGISTERED", False)
    assert pool_watch.standing_holders() is None


def test_the_pass_summary_subtracts_what_the_pool_watch_measured(monkeypatch):
    from src.database import session as sess
    from src.monitoring.collect_perf import CollectionMonitor

    class _Gov:
        w_max = 8

    class _Eng:
        pool = ReservingQueuePool(lambda: __import__("sqlite3").connect(":memory:"), pool_size=6, max_overflow=6)

    def verdict(standing):
        # the small tier's shape (pool 6 + 6, margin 4), whatever machine runs this test
        monkeypatch.setattr(mb, "budget", lambda: mb.resolve_for(3296))
        monkeypatch.setattr(pool_watch, "standing_holders", lambda *a, **k: standing)
        real = sess.engine
        sess.engine = _Eng()
        try:
            return CollectionMonitor(governor=_Gov(), pass_id="t", mode="press")._db_memory()[
                "api_headroom"
            ]
        finally:
            sess.engine = real

    clean = verdict(0)
    assert clean["sufficient"] is True and clean["standing_holders"] == 0
    held = verdict(2)
    assert held["sufficient"] is False and held["headroom"] == 2
    blind = verdict(None)
    assert blind["standing_unmeasured"] and blind["standing_holders"] == 0
