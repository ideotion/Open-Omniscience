"""S3.2: a poll must never pay a whole-table COUNT(*) on the request thread.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``/api/database/stats`` is polled every 4 s by the Library storage view. It used
to be guarded by a cache keyed on ``(PRAGMA data_version, total_changes())`` --
both PER CONNECTION, so on a pooled engine the key never matched and every poll
recomputed inline (43 s for the mentions count on the field corpus). The tests
below pin the replacement: the counts are served from the last real computation
with a visible age, and the recompute happens on a background thread.

Every "the request thread issued no COUNT" assertion here is scoped BY THREAD
IDENT, because the background refresher does issue them -- on its own thread,
which is the entire point. An engine-wide capture would see both and could not
tell the fixed code from the broken code.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.api import database as dbmod
from src.api import library as libmod
from src.api import served_cache
from src.database.models import Base, Source
from src.database.session import SessionLocal, engine, init_db


def setup_module(_module):
    init_db()


@pytest.fixture(autouse=True)
def _clean_cache():
    served_cache.invalidate()
    yield
    served_cache.invalidate()


class _CountCapture:
    """Records COUNT statements issued ON THE CALLING THREAD only."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._ident = threading.get_ident()

    def __enter__(self):
        @event.listens_for(engine, "before_cursor_execute")
        def _on(conn, cursor, statement, params, ctx, many):  # noqa: ANN001
            if threading.get_ident() == self._ident and "count(" in statement.lower():
                self.statements.append(statement.splitlines()[0][:80])

        self._listener = _on
        return self

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._listener)
        return False


def _add_source() -> None:
    s = SessionLocal()
    try:
        s.add(Source(name=f"s-{uuid.uuid4().hex[:8]}", domain=f"{uuid.uuid4().hex[:8]}.test"))
        s.commit()
    finally:
        s.close()


def _poll() -> dict:
    s = SessionLocal()
    try:
        return dbmod.database_stats(s)
    finally:
        s.close()


def _age_out(key: str) -> None:
    """Push an entry past its TTL without waiting real seconds.

    ``checked_at`` is the refresh clock; ``built_at`` is the value's real age and
    is left alone, so a test that ages an entry out does not also fake how old
    the number it is about to assert on actually is.
    """
    with served_cache._LOCK:
        served_cache._CACHE[key]["checked_at"] -= 10_000


def _wait_for_refresh(key: str, predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with served_cache._LOCK:
            entry = served_cache._CACHE.get(key)
        if entry is not None and predicate(entry["payload"]):
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
# The brief's own test
# --------------------------------------------------------------------------- #
def test_a_poll_issues_no_count_statements_and_still_reports_the_new_count():
    """After a write, a poll reports the new number having scanned nothing.

    The three steps are the real ones: a first (cold) call computes, a write
    lands, the BACKGROUND refresher picks it up, and the next poll -- the one a
    browser makes every 4 s -- reads the fresh number off the cache.
    """
    _poll()  # cold: the first render pays one scan, and only one
    before = _poll()["counts"]["sources"]

    _add_source()
    _age_out("db:stats")

    with _CountCapture() as cap:
        stale = dbmod.database_stats(SessionLocal())
    assert cap.statements == [], "the poll that KICKS the refresh must not scan"
    assert stale["counts"]["sources"] == before, "it serves the last real value, not a guess"

    assert _wait_for_refresh("db:stats", lambda p: p["counts"]["sources"] == before + 1), (
        "the background refresh never produced the new count"
    )

    with _CountCapture() as cap:
        fresh = _poll()
    assert cap.statements == [], f"a poll paid COUNT(*) on the request thread: {cap.statements}"
    assert fresh["counts"]["sources"] == before + 1


def test_the_cold_first_render_is_the_only_call_that_scans():
    """Warm polls issue no COUNT at all -- the property the old probe never held.

    Measured through these same functions before the fix: six reads across two
    pooled connections produced six recomputes, a 0% hit rate.
    """
    with _CountCapture() as cap:
        _poll()
    assert cap.statements, "the cold call must really compute (else this test proves nothing)"

    for _ in range(4):
        with _CountCapture() as cap:
            out = _poll()
        assert cap.statements == [], "a warm poll scanned"
        assert out["cached"] is True


def test_concurrent_cold_polls_start_exactly_one_scan():
    """N simultaneous polls on a cold cache must not start N scans.

    This is the death-spiral shape the alert strip hit: a slow build, and every
    poll arriving during it starting its own.
    """
    computed = {"n": 0}
    ready = threading.Event()

    def _slow(session):
        computed["n"] += 1
        ready.wait(2.0)
        return {"marker": computed["n"]}

    results: list[dict] = []

    def _call():
        s = SessionLocal()
        try:
            results.append(served_cache.cached("t:cold", _slow, s, ttl_s=30))
        finally:
            s.close()

    threads = [threading.Thread(target=_call) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    ready.set()
    for t in threads:
        t.join(10)

    assert computed["n"] == 1, f"{computed['n']} concurrent scans started, expected 1"
    assert len(results) == 6 and all(r["marker"] == 1 for r in results)


# --------------------------------------------------------------------------- #
# Honesty of what is served
# --------------------------------------------------------------------------- #
def test_the_served_payload_states_its_real_age():
    _poll()
    with served_cache._LOCK:
        served_cache._CACHE["db:stats"]["built_at"] -= 42
    out = _poll()
    assert out["cache_age_s"] >= 42, "a served value must not understate its own age"
    assert out["as_of"] == out["computed_at"], "as_of and computed_at describe the same instant"


def test_an_unchanged_database_is_not_rebuilt_and_as_of_keeps_telling_the_truth():
    """Nothing written => nothing to recompute; the value stays old AND correct.

    The re-stamp touches the CHECK clock, never ``built_at``: re-stamping the
    build time would restart the age at zero and report a value computed minutes
    ago as fresh.
    """
    _poll()
    with served_cache._LOCK:
        entry = served_cache._CACHE["db:stats"]
        entry["built_at"] -= 300
        built_at = entry["built_at"]
    _age_out("db:stats")

    with _CountCapture() as cap:
        out = _poll()
    assert cap.statements == []
    assert out["cache_age_s"] >= 300, "the age must still reflect when the value was computed"
    with served_cache._LOCK:
        assert served_cache._CACHE["db:stats"]["built_at"] == built_at
    time.sleep(0.3)
    with served_cache._LOCK:
        assert served_cache._CACHE["db:stats"]["built_at"] == built_at, (
            "an idle app rebuilt anyway"
        )


def test_an_unavailable_probe_is_never_read_as_nothing_changed(monkeypatch):
    """``None`` means "no reading", which is not the same as "unchanged".

    Reading it as unchanged would freeze the counts forever on any install whose
    write gate is off -- the conservative direction is to fall back to the TTL.
    """
    # The probe must be unavailable when the entry is BUILT as well as when it is
    # read -- that is the real case (an install whose gate is off), and it is the
    # only one that discriminates. Warming first and patching after leaves a real
    # int stored against a None reading, which is unequal under either behaviour:
    # the mutation that reads None as "unchanged" SURVIVED that version of this
    # test, which is how the hole was found.
    monkeypatch.setattr(served_cache, "change_probe", lambda: None)
    _poll()
    with served_cache._LOCK:
        assert served_cache._CACHE["db:stats"]["probe"] is None, (
            "the entry must have been built with no probe reading"
        )
    _age_out("db:stats")
    kicked: list[str] = []
    monkeypatch.setattr(
        served_cache, "_kick_background_refresh", lambda key, compute: kicked.append(key)
    )
    _poll()
    assert kicked == ["db:stats"], "an unreadable probe must fall back to the TTL, not to 'fresh'"


# --------------------------------------------------------------------------- #
# The correctness nets
# --------------------------------------------------------------------------- #
def test_a_session_on_another_database_is_never_served_this_ones_counts(tmp_path):
    """The bind gate: a process-lifetime singleton must not answer for a database
    it was not built from."""
    _poll()
    other = create_engine(f"sqlite:///{tmp_path / 'other.db'}")
    Base.metadata.create_all(other)
    other_session = sessionmaker(bind=other)()
    try:
        computed = {"n": 0}

        def _compute(session):
            computed["n"] += 1
            return {"where": "other"}

        out = served_cache.cached("db:stats", _compute, other_session, ttl_s=30)
        assert computed["n"] == 1, "a foreign session was served this database's numbers"
        assert out["where"] == "other"
    finally:
        other_session.close()
        other.dispose()


def test_the_change_probe_is_comparable_across_pooled_connections():
    """The property the replaced probe could not hold.

    ``total_changes()`` counts only the calling connection's own writes and
    ``data_version`` does not tick for the connection that wrote, so two pooled
    connections disagree permanently. The gate's ``grants`` counter is one
    process-global int, so every connection reads the same value.
    """
    a, b = SessionLocal(), SessionLocal()
    try:
        a.execute(text("SELECT 1"))
        b.execute(text("SELECT 1"))
        assert served_cache.change_probe() == served_cache.change_probe()
        before = served_cache.change_probe()
        assert before is not None, "the write gate is on in the test env; the probe must read"

        # The old pair, computed here, is what a cache would have keyed on.
        def _old_probe(s):
            return (
                s.execute(text("PRAGMA data_version")).scalar(),
                s.execute(text("SELECT total_changes()")).scalar(),
            )

        assert _old_probe(a) != _old_probe(b), (
            "the old probe agreed across connections here, so this test would not "
            "discriminate -- check the pool really handed out two connections"
        )

        a.add(Source(name=f"p-{uuid.uuid4().hex[:8]}", domain=f"{uuid.uuid4().hex[:8]}.test"))
        a.commit()
        after = served_cache.change_probe()
        assert after != before, "a write must move the probe"
        assert after == served_cache.change_probe(), "and it must read the same from anywhere"
    finally:
        a.close()
        b.close()


def test_pure_reads_never_move_the_probe():
    """The negative twin of the test above: a probe that moved on reads would make
    the cache rebuild forever and be no better than no cache at all."""
    _poll()
    before = served_cache.change_probe()
    for _ in range(5):
        _poll()
    assert served_cache.change_probe() == before


def test_a_corpus_swap_drops_the_served_counts():
    """The explicit belt for the write the probe cannot see.

    A restore replaces the database file through raw connections that never touch
    the write gate, so ``grants`` does not move and the cache would keep serving
    pre-restore counts.
    """
    import pathlib

    from tests.py_source_helper import assert_calls_resolve

    _poll()
    assert "db:stats" in served_cache.status()["entries"]
    served_cache.invalidate()
    assert "db:stats" not in served_cache.status()["entries"]

    # RESOLVED, not grepped: the import line spells the same identifier, so a
    # substring search would pass with the CALL deleted and the import left
    # behind. (PR-10 shipped that hole once; tests/py_source_helper.py exists
    # because of it.)
    root = pathlib.Path(__file__).resolve().parents[1]
    assert_calls_resolve(root / "src/backup/merge.py", "invalidate_served_counts")


def test_stats_and_library_overview_share_one_cache_mechanism():
    """Two copies of a cache is how one gets fixed and the other quietly does not
    -- which is exactly what happened here (library.py carried a verbatim copy of
    the broken probe). Asserted behaviourally: both route into served_cache."""
    calls: list[str] = []
    real = served_cache.cached

    def _spy(key, compute, session, *, ttl_s):
        calls.append(key)
        return real(key, compute, session, ttl_s=ttl_s)

    served_cache.cached = _spy  # type: ignore[assignment]
    try:
        s = SessionLocal()
        try:
            dbmod.database_stats(s)
            libmod.library_overview(s)
            dbmod.library_figures(s)
        finally:
            s.close()
    finally:
        served_cache.cached = real  # type: ignore[assignment]

    assert "db:stats" in calls and "library:overview" in calls and "db:figures" in calls, calls


def test_figures_are_served_stale_rather_than_recomputed_inline():
    """The whole-table mentions count is the 43 s query; it must never ride a poll."""
    s = SessionLocal()
    try:
        dbmod.library_figures(s)  # cold
    finally:
        s.close()
    _age_out("db:figures")
    with _CountCapture() as cap:
        s = SessionLocal()
        try:
            out = dbmod.library_figures(s)
        finally:
            s.close()
    assert cap.statements == [], f"the figures poll scanned: {cap.statements}"
    assert "as_of" in out and out["cached"] is True
