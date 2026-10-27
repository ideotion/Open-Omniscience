"""R278 (audit 0.5.0, #1310 class): the rollup benchmark meets the start-time guards the served build meets.

Before: ``GET /api/diagnostics/rollup-benchmark`` built the whole-corpus keyword rollup in memory, the build that crashed the app in #1310, with
no verdict and no hold: it ran while a stop hold said the machine cannot afford it, while memory was short and beside a served build.
After: ``run_rollup_benchmark`` asks the same verdicts (judged as the in-memory build it is), holds the build lock, and DECLINES with the verdict's
reason code and builds nothing. (The cross-site guard on the GET route itself is a separate item.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("duckdb")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.analytics import columnar, rollup_marker, rollup_serve  # noqa: E402
from src.database.models import Base  # noqa: E402
from src.monitoring.rollup_benchmark import run_rollup_benchmark  # noqa: E402


@pytest.fixture()
def empty_session():
    """A real, empty corpus: the guard tests must fail on the patched builder (``never``), not on a missing session."""
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


class _Con:
    def close(self):
        pass


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    keys = ("con", "stopped", "failures", "failure_class", "last_outcome", "last_decline", "last_skip", "persisted", "built_at", "bind")
    keep = {k: rollup_serve._STATE.get(k) for k in keys}
    rollup_serve._STATE.update(con=None, stopped=None, failures=0, failure_class=None, last_outcome=None, last_decline=None,
                               last_skip=None, persisted=False, built_at=0.0, bind=None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", True)
    rollup_serve._PERSISTED_FELL_BACK["why"] = None
    for name in ("_boot_order_verdict", "_memory_verdict", "_last_build_verdict", "_affordability_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)

    def never(*a, **k):
        raise AssertionError("the benchmark built something past a verdict that refuses it")

    monkeypatch.setattr(columnar, "connect", never)
    monkeypatch.setattr(columnar, "build_keyword_daily", never)
    yield
    rollup_serve._STATE.update(keep)
    rollup_serve._BENCHMARK["running"] = False
    if rollup_serve._BUILD_LOCK.locked():  # a test that leaves the build lock held hangs every later waiter and the interpreter's exit
        rollup_serve._BUILD_LOCK.release()
        pytest.fail("a test left the build lock held")


def test_a_seeded_in_memory_stop_hold_makes_the_benchmark_decline_and_build_nothing(monkeypatch, empty_session):
    monkeypatch.setattr(rollup_serve, "_stopped_build_verdict", rollup_serve._stopped_build_verdict)  # the real one
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 500.0)
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 500.0, "epoch": 1}
    out = run_rollup_benchmark(empty_session, repeats=1)
    assert out["available"] is False and out["declined"] is True
    assert out["reason"] == "duckdb-limit" and out["source"] == "stopped"
    assert rollup_serve._STATE["last_skip"] is None, "a benchmark's refusal is not the serve's decline"


@pytest.mark.parametrize("verdict,source", [("_affordability_verdict", "affordability"), ("_last_build_verdict", "last-build"),
                                            ("_memory_verdict", "memory"), ("_boot_order_verdict", "boot-order")])
def test_each_start_time_verdict_declines_the_benchmark_with_its_own_reason(monkeypatch, empty_session, verdict, source):
    monkeypatch.setattr(rollup_serve, verdict, lambda: {"reason": "mem-short", "at": 1.0})
    out = run_rollup_benchmark(empty_session, repeats=1)
    assert (out["declined"], out["reason"], out["source"]) == (True, "mem-short", source)


def test_the_exclusive_window_declines_the_benchmark(monkeypatch, empty_session):
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: {"reason": "exclusive-window", "at": 1.0})
    out = run_rollup_benchmark(empty_session, repeats=1)
    assert out["declined"] is True and out["source"] == "exclusive"


def test_a_running_rollup_build_makes_the_benchmark_decline(monkeypatch, empty_session):
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    try:
        out = run_rollup_benchmark(empty_session, repeats=1)
        assert out["declined"] is True and out["reason"] == "build-running"
    finally:
        rollup_serve._BUILD_LOCK.release()


def test_the_benchmark_releases_the_build_lock_after_a_decline_and_after_an_error(monkeypatch, empty_session):
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: {"reason": "mem-low", "at": 1.0})
    assert run_rollup_benchmark(empty_session, repeats=1)["declined"] is True
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False), "a decline left the build lock held"
    rollup_serve._BUILD_LOCK.release()
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    with pytest.raises(AssertionError):  # the verdicts pass, so the run reaches the (patched) builder, which raises
        run_rollup_benchmark(empty_session, repeats=1)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False), "an error left the build lock held"
    rollup_serve._BUILD_LOCK.release()


def test_the_benchmark_judges_the_in_memory_build_even_when_the_persisted_store_is_active(monkeypatch, empty_session):
    """The affordability and killed-build verdicts stand aside for a persisted store; the benchmark always builds in memory, so it must not."""
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", rollup_serve._persisted_serve_active)  # the real one, which reads the setting
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    assert rollup_serve._persisted_serve_active() is True
    seen: list = []

    def afford():
        seen.append(rollup_serve._persisted_serve_active())
        return {"reason": "mem-short", "at": 1.0}

    monkeypatch.setattr(rollup_serve, "_affordability_verdict", afford)
    out = run_rollup_benchmark(empty_session, repeats=1)
    assert out["declined"] is True and seen == [False], "the verdict was asked about the persisted store"
    assert rollup_serve._persisted_serve_active() is True, "the view leaked past the benchmark"


def _arm_builder(monkeypatch, seen: dict, *, raises: bool = True):
    """Replace the engine with a stand-in that records what the kill marker looks like while the build runs."""
    monkeypatch.setattr(columnar, "connect", lambda *a, **k: _Con())

    def build(con, session, on_batch=None, **_k):
        seen["marker_during"] = rollup_marker.read()
        on_batch("mentions", 5)
        seen["stage_after_batch"] = (rollup_marker.read() or {}).get("stage")
        if raises:
            raise RuntimeError("the build died")
        return {"keyword_daily_rows": 0, "streamed_mentions": 0}

    monkeypatch.setattr(columnar, "build_keyword_daily", build)


def test_the_kill_marker_is_written_around_the_benchmark_build_and_cleared_after_an_error(monkeypatch, empty_session):
    """A benchmark killed mid-build (the #1310 end) must leave the record the next start's last-build verdict reads."""
    seen: dict = {}
    _arm_builder(monkeypatch, seen)
    with pytest.raises(RuntimeError):
        run_rollup_benchmark(empty_session, repeats=1)
    assert seen["marker_during"] is not None, "no in-progress marker was written while the benchmark built"
    assert seen["stage_after_batch"] == "mentions", "the marker's stage was not kept current by the build's batch hook"
    assert rollup_marker.read() is None, "the marker was left behind by a build that ended in a path Python saw"
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False), "an error left the build lock held"
    rollup_serve._BUILD_LOCK.release()


def test_another_servers_running_build_declines_the_benchmark(monkeypatch, empty_session):
    monkeypatch.setattr(rollup_marker, "begin", lambda **_k: False)
    out = run_rollup_benchmark(empty_session, repeats=1)
    assert (out["declined"], out["reason"], out["source"]) == (True, rollup_marker.ELSEWHERE, "last-build")


def test_the_status_does_not_call_a_running_benchmark_a_rebuild():
    with rollup_serve.benchmark_slot() as held:
        assert held is True
        st = rollup_serve.status()
        assert st["building"] is False and st["benchmark_running"] is True
        assert rollup_serve._BUILD_LOCK.locked()
    assert rollup_serve.status()["benchmark_running"] is False


def test_a_boot_wait_for_a_served_build_is_not_satisfied_by_a_benchmark_releasing_the_lock(monkeypatch):
    """``build_now_and_wait`` used to return the previous build's outcome when the lock it waited for was a benchmark's: the boot step then read
    "built" for a rollup nothing built."""
    ours: list = []

    def fake_build():
        ours.append(1)
        rollup_serve._BUILD_LOCK.release()  # the real one releases in its finally
        return "built-by-us"

    monkeypatch.setattr(rollup_serve, "_build_and_swap", fake_build)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "stale-previous-outcome")
    got: list = []
    with rollup_serve.benchmark_slot():
        t = threading.Thread(target=lambda: got.append(rollup_serve.build_now_and_wait()), daemon=True)
        t.start()
        time.sleep(0.2)  # the waiter is blocked on the benchmark's lock
        assert not got
    t.join(5)
    assert got == ["built-by-us"] and ours == [1], f"the wait returned {got!r} without running a served build"


def test_a_served_build_that_ends_while_a_boot_wait_waits_still_gives_its_outcome(monkeypatch):
    def not_ours():
        rollup_serve._BUILD_LOCK.release()
        raise AssertionError("the waiter started a build of its own")

    monkeypatch.setattr(rollup_serve, "_build_and_swap", not_ours)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "declined")
    got: list = []
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)  # stands for a running served build
    t = threading.Thread(target=lambda: got.append(rollup_serve.build_now_and_wait()), daemon=True)
    t.start()
    time.sleep(0.2)
    rollup_serve._BUILD_GEN["n"] += 1  # the served build's finally does this while it still holds the lock
    rollup_serve._BUILD_LOCK.release()
    t.join(5)
    assert got == ["declined"]


def test_inmemory_view_nests_and_restores_the_outer_setting():
    assert getattr(rollup_serve._STORE_VIEW, "inmemory", False) is False
    with rollup_serve.inmemory_view():
        with rollup_serve.inmemory_view():
            pass
        assert rollup_serve._STORE_VIEW.inmemory is True, "the inner exit cleared the outer view"
    assert rollup_serve._STORE_VIEW.inmemory is False


def test_the_stale_numbers_provenance_does_not_say_a_rebuild_follows_a_benchmark():
    with rollup_serve.benchmark_slot():
        assert rollup_serve.basis(30)["rebuilding"] is False
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    try:
        assert rollup_serve.basis(30)["rebuilding"] is True, "negative space: a served build still reads as a rebuild"
    finally:
        rollup_serve._BUILD_LOCK.release()


def test_a_second_benchmark_declined_by_the_slot_does_not_clear_the_first_ones_flag():
    with rollup_serve.benchmark_slot() as first:
        assert first is True
        with rollup_serve.benchmark_slot() as second:
            assert second is False
        assert rollup_serve._BENCHMARK["running"] is True and rollup_serve._BUILD_LOCK.locked()
    assert rollup_serve._BENCHMARK["running"] is False


def test_a_build_thread_that_cannot_start_counts_the_build_as_ended(monkeypatch):
    class _NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(rollup_serve.threading, "Thread", _NoThread)
    before = rollup_serve._BUILD_GEN["n"]
    rollup_serve._trigger_build_async()
    assert rollup_serve._BUILD_GEN["n"] == before + 1 and not rollup_serve._BUILD_LOCK.locked()


def test_the_benchmark_connects_with_the_serves_offload_rule_and_one_snapshot_and_cleans_up(monkeypatch, empty_session):
    """Left to DuckDB's default the offload folder is beside the working directory, in the clear, for an encrypted corpus: the serve passes its own rule."""
    seen: dict = {}
    removed: list = []

    class Con(_Con):
        closed = False

        def close(self):
            Con.closed = True

    monkeypatch.setattr(rollup_serve, "_spill_setting", lambda: "SPILL-RULE")
    monkeypatch.setattr(rollup_serve, "_remove_spill", lambda path: removed.append((path, Con.closed)))
    monkeypatch.setattr(columnar, "connect", lambda *a, **k: (seen.update(k), Con())[1])

    def build(con, session, on_batch=None, snapshot=None, **_k):
        seen["build_snapshot"] = snapshot
        raise RuntimeError("the build died")

    monkeypatch.setattr(columnar, "build_keyword_daily", build)
    with pytest.raises(RuntimeError):
        run_rollup_benchmark(empty_session, repeats=1)
    assert seen["spill"] == "SPILL-RULE"
    assert seen["snapshot"] is seen["build_snapshot"] and seen["snapshot"] is not None, "the connection and the build did not share one budget reading"
    assert Con.closed, "the connection was left open after the build raised"
    assert removed == [("SPILL-RULE", True)], "the offload folder was not removed after the connection was closed"
