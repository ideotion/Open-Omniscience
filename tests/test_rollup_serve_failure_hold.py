"""A rollup build that ends in an error is not started again by the very next request (R172).

Before: ``_build_and_swap`` caught any exception that was not a mapped stop, logged it, returned ``"failed"`` and kept NOTHING, so with no rollup built
every request that wanted one started the same build again as soon as the build lock was free (measured 17 Oct on a 32,000-mention corpus with a
RuntimeError forced at the keyword_meta insert: 5 requests, 5 builds, no hold, no record, the boot step's row said "unknown").
After: the failure keeps a hold released by what releases a ``duckdb-limit`` hold (a larger limit, offload allowed, a smaller corpus, another
version), carrying the stage the build had reported (None and ``stage_why`` when none), the exception CLASS, the run of consecutive failures and
never the exception's text; a build that serves ends the run; ``status()`` and the boot step say it. A plain OutOfMemoryException stays the
``duckdb-limit`` stop it was.
"""

from __future__ import annotations

import json

import pytest

from src.analytics import rollup_hold, rollup_serve


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 7)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 1000)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1004.0)
    monkeypatch.setattr(rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": 1004.0, "offload_allowed": False})
    keep = {k: rollup_serve._STATE.get(k) for k in ("stopped", "failures", "failure_class", "last_outcome", "last_decline", "last_skip")}
    rollup_serve._STATE.update(stopped=None, failures=0, failure_class=None, last_outcome=None, last_decline=None, last_skip=None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", False)
    yield
    rollup_serve._STATE.update(keep)


def _run(monkeypatch, builds, *, raises=None, stage="aggregate"):
    """One dispatcher call whose in-memory build is replaced by ``raises`` (or returns None = served). Counts the calls in ``builds``."""
    def build():
        builds.append(1)
        rollup_serve._LAST_STAGE["value"] = stage
        if raises is not None:
            raise raises
        return None

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", build)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    return rollup_serve._build_and_swap()


def test_a_failed_build_is_held_and_five_requests_start_one_build(monkeypatch):
    builds: list[int] = []
    outcomes = [_run(monkeypatch, builds, raises=RuntimeError("SECRET-term /home/alice/x.db")) for _ in range(5)]
    assert len(builds) == 1, f"{len(builds)} builds for 5 requests: the failure was not held"
    assert outcomes[0] == "failed" and outcomes[1:] == ["declined"] * 4
    hold = rollup_serve._STATE["stopped"]
    assert hold["reason"] == "build-failed" and hold["engine_error_class"] == "RuntimeError" and hold["consecutive_failures"] == 1
    assert hold["stage"] == "aggregate" and "stage_why" not in hold
    kept = rollup_hold.read()
    assert kept["reason"] == "build-failed" and kept["consecutive_failures"] == 1
    blob = json.dumps(kept) + json.dumps(rollup_serve.status(), default=str)
    assert "SECRET" not in blob and "alice" not in blob, "the exception's text reached a record"


def test_an_unknown_stage_is_null_with_a_reason(monkeypatch):
    _run(monkeypatch, [], raises=ValueError("x"), stage=None)
    hold = rollup_serve._STATE["stopped"]
    assert "stage" not in hold and hold["stage_why"] == "not-recorded"


def test_status_and_the_boot_step_say_what_failed(monkeypatch):
    _run(monkeypatch, [], raises=KeyError("k"))
    st = rollup_serve.status()
    assert st["last_outcome"] == "failed" and st["consecutive_failures"] == 1 and st["last_failure_class"] == "KeyError"
    detail = rollup_serve.decline_detail()
    assert detail["reason"] == "build-failed" and detail["engine_error_class"] == "KeyError" and detail["consecutive_failures"] == 1


def test_the_boot_step_row_names_the_class_beside_its_own_error(monkeypatch):
    from src.api import boot_sequence as bs

    _run(monkeypatch, [], raises=KeyError("k"))
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: "failed")
    with pytest.raises(RuntimeError):
        bs._rollup_first_build()
    row = bs._STEPS["rollup"]["detail"]
    assert row["engine_error_class"] == "KeyError" and row["reason"] == "build-failed"


def test_the_run_counts_up_across_releases_and_a_build_that_serves_ends_it(monkeypatch):
    builds: list[int] = []
    _run(monkeypatch, builds, raises=RuntimeError("a"))
    rollup_serve._release_stopped()
    _run(monkeypatch, builds, raises=RuntimeError("b"))
    assert rollup_serve._STATE["stopped"]["consecutive_failures"] == 2 and rollup_serve.status()["consecutive_failures"] == 2
    rollup_serve._release_stopped()
    assert _run(monkeypatch, builds) == "built"
    st = rollup_serve.status()
    assert "consecutive_failures" not in st and "last_failure_class" not in st and "last_outcome" not in st, "absent means 0 since the last serve"
    assert rollup_serve._STATE["stopped"] is None


def test_a_restart_keeps_the_count_but_not_the_hold(monkeypatch):
    _run(monkeypatch, [], raises=RuntimeError("a"))
    assert rollup_serve._STATE["stopped"] is not None
    # a new process: nothing in memory, the file kept
    rollup_serve._STATE.update(stopped=None, failures=0, failure_class=None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", False)
    st = rollup_serve.status()
    assert st["consecutive_failures"] == 1 and st["last_failure_class"] == "RuntimeError"
    assert rollup_serve._STATE["stopped"] is None, "a failure hold is the process's own: the restart retries"
    builds: list[int] = []
    assert _run(monkeypatch, builds, raises=RuntimeError("b")) == "failed" and builds, "the first build after a restart runs"
    assert rollup_serve._STATE["stopped"]["consecutive_failures"] == 2, "the count carried over"
    assert _run(monkeypatch, builds, raises=RuntimeError("c")) == "declined" and len(builds) == 1, "and the second is held again"


def test_the_hold_is_released_by_what_releases_the_duckdb_limit_hold(monkeypatch):
    builds: list[int] = []
    _run(monkeypatch, builds, raises=RuntimeError("a"))
    assert _run(monkeypatch, builds, raises=RuntimeError("b")) == "declined"
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 2000.0)  # a larger limit
    assert _run(monkeypatch, builds, raises=RuntimeError("c")) == "failed", "a larger limit releases it, so the build runs (and fails again)"
    assert len(builds) == 2


def test_a_plain_out_of_memory_stays_the_duckdb_limit_stop_and_is_not_a_failure(monkeypatch):
    # BuildDeclined (and a plain OutOfMemoryException) are caught inside _build_inmemory_and_swap and returned as a skip; the stand-in returns that skip
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: {"reason": "duckdb-limit", "at": 1.0, "stage": "keywords", "duckdb_limit_mb": 1004.0, "mentions_count": 10, "epoch": 7})
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    assert rollup_serve._STATE["stopped"]["reason"] == "duckdb-limit" and "consecutive_failures" not in rollup_serve.status()


def test_the_persisted_store_is_not_touched(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    monkeypatch.setattr(rollup_serve, "_refresh_persisted_build", lambda: (_ for _ in ()).throw(RuntimeError("p")))
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "failed"
    assert rollup_serve._STATE["stopped"] is None and rollup_hold.read() is None


_WIDEST_STOP = {"reason": "duckdb-limit", "at": 1760000000.123456, "stage": "keywords", "duckdb_limit_mb": 1004.0, "offload_allowed": False,
                "epoch": 123456, "mentions_count": 20000000, "grew_mb": 1234.5, "observed_grew_mb": 1234.5, "mentions_total": 20000000,
                "rows_done": 19999999, "duckdb_threads": 2, "budget_total_mb": 16000.0, "budget_read_at": "2026-10-17T00:00:00Z", "shards": 16,
                "shard": 15, "split": 3, "query": "keyword_daily_by_day", "peak_mib": 1003.9, "resident_mib": 998.7,
                "engine_error_class": "OutOfMemoryException", "app_version": "0.5.0", "build_code": 12, "restored": True, "repeats": 12}


def _row_bytes() -> int:
    return len(json.dumps(rollup_serve.status(), default=str, separators=(",", ":")))


def test_the_worst_case_row_is_not_larger_than_it_was_before_the_failure_fields(monkeypatch):
    """columnar.json ``rollup_serve`` row, both rows made by the module's own code. Base: the widest duckdb-limit hold (kept and noted as the last
    decline, as a build does), the ``refresh`` constant present, no failure fields. After: that same hold without the constant, and the widest
    failure hold (a long class name, a run of 12, a stage) with the failure fields present. Both must be at or under the base."""
    monkeypatch.setattr(rollup_serve, "_stopped_hold", lambda: rollup_serve._STATE["stopped"])
    rollup_serve._keep_stopped(dict(_WIDEST_STOP))
    rollup_serve._note_decline("stopped", "build", {**rollup_serve._STATE["stopped"], "restored": True, "repeats": 12})
    clean_stop = _row_bytes()
    base = clean_stop + len(',"refresh":"change-gated"')
    rollup_serve._release_stopped()
    rollup_serve._STATE.update(last_decline=None, failures=11)
    _run(monkeypatch, [], raises=type("OutOfMemoryExceptionLongest", (RuntimeError,), {})("x"), stage="checkpoint")
    st = rollup_serve.status()
    assert st["consecutive_failures"] == 12 and st["stopped"]["reason"] == "build-failed"
    failed = _row_bytes()
    print(f"worst-case rollup_serve row: base {base} B; after: duckdb-limit hold {clean_stop} B, failure hold {failed} B")
    assert clean_stop < base and failed <= base, f"{clean_stop}/{failed} B against the base's {base} B"


def test_a_failure_run_and_a_duckdb_limit_hold_are_never_in_one_report(monkeypatch):
    _run(monkeypatch, [], raises=RuntimeError("a"))
    rollup_serve._release_stopped()
    rollup_serve._keep_stopped({"reason": "duckdb-limit", "at": 1.0, "stage": "keywords", "duckdb_limit_mb": 1004.0})
    st = rollup_serve.status()
    assert "consecutive_failures" not in st and st["stopped"]["reason"] == "duckdb-limit"


def test_a_stage_left_by_an_earlier_decline_is_not_the_stage_of_a_build_that_failed_before_it_reported_one(monkeypatch):
    rollup_serve._LAST_STAGE["value"] = "mentions"  # what a build that DECLINED at that stage leaves behind

    def build():
        raise ValueError("x")  # fails before the build reports any stage

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", build)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "failed"
    hold = rollup_serve._STATE["stopped"]
    assert "stage" not in hold and hold["stage_why"] == "not-recorded"


def test_the_stage_a_real_build_had_reached_is_the_failure_holds_stage(monkeypatch):
    """Through the real ``_build_inmemory_and_swap``: the build reports ``aggregate`` and then raises."""
    from contextlib import contextmanager

    import src.database.session as dbs
    from src.analytics import columnar, rollup_marker, serve_gate

    class Con:
        def close(self):
            pass

    @contextmanager
    def scope():
        yield object()

    def build(con, s, *, on_batch=None, snapshot=None):
        on_batch("aggregate", 1)
        raise ValueError("x")

    monkeypatch.setattr(columnar, "budget_snapshot", lambda: {"duckdb_limit_mb": 1004.0, "duckdb_threads": 2, "total_mb": 6000.0, "read_at": 0.0})
    monkeypatch.setattr(columnar, "connect", lambda **kw: Con())
    monkeypatch.setattr(columnar, "build_keyword_daily", build)
    monkeypatch.setattr(dbs, "session_scope", scope)
    monkeypatch.setattr(serve_gate, "change_token", lambda s: ("t", 1))
    monkeypatch.setattr(rollup_marker, "begin", lambda **kw: None)
    monkeypatch.setattr(rollup_marker, "clear", lambda: None)
    monkeypatch.setattr(rollup_serve, "_spill_setting", lambda: "")
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "failed"
    assert rollup_serve._STATE["stopped"]["stage"] == "aggregate"
