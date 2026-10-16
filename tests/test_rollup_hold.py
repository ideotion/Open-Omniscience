"""A rollup build that DuckDB's own limit stopped is not started again by the next process.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install: the boot's build ran 921 s and hit DuckDB's 1,004 MB limit (no offload for an encrypted
corpus, so the limit is a wall). The stop was held in memory, so the next boot spent the same 921 s to find the same
wall. ``rollup_hold`` keeps the stop record across a restart and ``_stopped_build_verdict`` honours it; these tests pin
that the record is kept, restored and named as restored, carries nothing but codes and numbers, releases only on a
changed wall, and that a damaged file is named rather than taken for absence.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from src.analytics import rollup_hold, rollup_serve


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(rollup_hold, "_path", lambda: tmp_path / "rollup_stopped.json")
    for name in ("_boot_order_verdict", "_memory_verdict", "_last_build_verdict", "_affordability_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1005.0)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 7)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 12_000_000)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    keep = {k: rollup_serve._STATE[k] for k in ("last_skip", "stopped", "last_decline")}
    looked = rollup_serve._HOLD_LOOKED
    rollup_serve._STATE.update(last_skip=None, stopped=None, last_decline=None)
    rollup_serve._HOLD_LOOKED = True
    yield tmp_path / "rollup_stopped.json"
    rollup_serve._STATE.update(keep)
    rollup_serve._HOLD_LOOKED = looked


def _stop(monkeypatch, **extra):
    record = {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 1005.0, "stage": "aggregate",
              "rows_done": 12_004_191, "rss_mb": 1500.0, "begin_rss_mb": 300.0, "mentions_total": 12_004_191,
              "mentions_count": 12_000_000, "epoch": 7, "error": "Out of Memory Error: secret-looking engine text",
              **extra}
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: dict(record))
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"


def _restart():
    """What a new process starts with: no in-memory hold, and the file not yet looked at."""
    rollup_serve._STATE.update(stopped=None, last_skip=None, last_decline=None)
    rollup_serve._HOLD_LOOKED = False


def _build_attempts(monkeypatch):
    calls = []

    def attempt():
        calls.append(1)
        return None

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", attempt)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    return calls, rollup_serve._build_and_swap()


def test_a_stop_is_kept_on_disk_as_codes_and_numbers_only(monkeypatch, _env):
    _stop(monkeypatch)
    rec = json.loads(_env.read_text(encoding="utf-8"))
    assert rec["reason"] == "duckdb-limit" and rec["stage"] == "aggregate" and rec["duckdb_limit_mb"] == 1005.0
    assert rec["mentions_count"] == 12_000_000 and rec["epoch"] == 7 and rec["format"] == rollup_hold.FORMAT
    assert "error" not in rec and "secret" not in _env.read_text(encoding="utf-8"), "engine text is never kept"
    assert "rss_mb" not in rec, "only the fields a release rule reads"


def test_a_new_process_does_not_start_the_build_the_last_one_saw_stopped(monkeypatch):
    _stop(monkeypatch)
    _restart()
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "declined" and calls == [], "the scan was not started again"
    st = rollup_serve.status()
    assert st["stopped"]["restored"] is True and st["stopped"]["reason"] == "duckdb-limit"
    assert st["last_skip"]["restored"] is True and st["last_decline"]["source"] == "stopped"
    assert st["last_decline"]["reason"] == "duckdb-limit"


def test_status_shows_the_kept_stop_before_any_build_has_looked_at_it(monkeypatch):
    _stop(monkeypatch)
    _restart()
    assert rollup_serve.status()["stopped"]["restored"] is True


def test_a_larger_limit_releases_the_hold_and_the_file(monkeypatch, _env):
    _stop(monkeypatch)
    _restart()
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 2048.0)
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1]
    assert not _env.exists(), "a finished build leaves no stop behind"
    assert rollup_serve._STATE["stopped"] is None


def test_the_same_limit_with_a_bumped_epoch_and_the_same_corpus_stays_held_across_a_restart(monkeypatch, _env):
    _stop(monkeypatch, at=time.time() - rollup_serve.rollup_serve_ttl_s() - 60.0)
    _restart()
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)  # a re-index drain moved it
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "declined" and calls == []
    assert json.loads(_env.read_text(encoding="utf-8"))["epoch"] == 8, "the count is not repeated until it moves again"


def test_a_corpus_with_fewer_mentions_than_at_the_stop_releases_it_after_a_restart(monkeypatch, _env):
    _stop(monkeypatch, at=time.time() - rollup_serve.rollup_serve_ttl_s() - 60.0)
    _restart()
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 6_000_000)
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1]
    assert not _env.exists()


def test_a_guard_stop_is_kept_too_and_released_by_the_memory_rule_it_always_had(monkeypatch):
    _stop(monkeypatch, reason="mem-low", grew_mb=900.0, rss_mb=1500.0)
    _restart()
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 300.0, "avail_mb": 400.0})
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    v = rollup_serve._stopped_build_verdict()
    assert v and v["reason"] == "mem-low", "the machine still lacks what the build grew by"
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": 300.0, "avail_mb": 4000.0})
    assert rollup_serve._stopped_build_verdict() is None


@pytest.mark.parametrize("text", ["{not json", json.dumps({"format": 99, "reason": "duckdb-limit"}),
                                  json.dumps({"format": 1}), "[]"])
def test_a_damaged_record_is_named_and_ignored_not_half_trusted(monkeypatch, _env, caplog, text):
    _env.write_text(text, encoding="utf-8")
    _restart()
    with caplog.at_level(logging.WARNING):
        assert rollup_hold.read() is None
    assert any("rollup hold" in r.getMessage() for r in caplog.records), "absence and damage are told apart"
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1], "a record that cannot be trusted never blocks a build"


def test_a_missing_record_is_silent(caplog, _env):
    with caplog.at_level(logging.WARNING):
        assert rollup_hold.read() is None
    assert not [r for r in caplog.records if "rollup hold" in r.getMessage()]


def test_values_of_the_wrong_type_are_dropped_on_the_way_in_and_out(_env):
    rollup_hold.write({"reason": "duckdb-limit", "at": True, "duckdb_limit_mb": "huge", "epoch": 3.5,
                       "stage": "aggregate", "path": "/secret/place", "mentions_count": 5})
    kept = json.loads(_env.read_text(encoding="utf-8"))
    assert set(kept) == {"format", "reason", "stage", "mentions_count"}
    assert rollup_hold.write({"stage": "aggregate"}) is False, "no reason, no record"


def test_a_record_that_cannot_be_written_does_not_stop_the_build_own_hold(monkeypatch, tmp_path):
    monkeypatch.setattr(rollup_hold, "_path", lambda: tmp_path / "no-such-dir" / "x.json")
    _stop(monkeypatch)
    assert rollup_serve._STATE["stopped"]["reason"] == "duckdb-limit", "the in-memory hold still holds"


def test_a_build_that_finishes_removes_the_stop_whatever_released_it(monkeypatch, _env):
    rollup_hold.write({"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 1005.0})
    monkeypatch.setattr(rollup_serve, "_stopped_build_verdict", lambda: None)  # released by something else
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1]
    assert not _env.exists(), "a stale stop must not outlive the build that proved it wrong"


def test_a_stop_recorded_by_another_app_version_is_released_on_the_next_boot(monkeypatch, _env):
    _stop(monkeypatch)
    rec = json.loads(_env.read_text(encoding="utf-8"))
    assert rec["build_code"] == rollup_serve.BUILD_CODE_VERSION and rec["app_version"], "the file names the code that stopped"
    _restart()
    monkeypatch.setattr("src.__version__", "0.0.0-older", raising=False)
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1], "an upgrade gets its own attempt: the stop was a statement about the old code"
    assert not _env.exists()


def test_a_stop_recorded_by_another_build_code_is_released_too(monkeypatch, _env):
    _stop(monkeypatch)
    _restart()
    monkeypatch.setattr(rollup_serve, "BUILD_CODE_VERSION", rollup_serve.BUILD_CODE_VERSION + 1)
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1], "the build's own memory behaviour changed inside one app version"


def test_a_kept_stop_from_before_the_version_fields_existed_is_released(monkeypatch, _env):
    rollup_hold.write({"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 1005.0})
    _restart()
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "built" and calls == [1]


def test_the_same_version_keeps_the_stop(monkeypatch):
    _stop(monkeypatch)
    _restart()
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "declined" and calls == []


def _old(monkeypatch, **extra):
    _stop(monkeypatch, at=time.time() - rollup_serve.rollup_serve_ttl_s() - 60.0, **extra)


def test_a_drop_of_a_few_mentions_is_not_a_smaller_corpus(monkeypatch, _env):
    """The wall is the limit against the corpus: one pruned article leaves the same scan stopping at the same wall."""
    _old(monkeypatch)
    _restart()
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 11_999_999)
    calls, outcome = _build_attempts(monkeypatch)
    assert outcome == "declined" and calls == []
    kept = json.loads(_env.read_text(encoding="utf-8"))
    assert kept["mentions_count"] == 12_000_000, "the count the wall was measured at stays the base"


@pytest.mark.parametrize("count,released", [(11_520_000, False), (11_280_000, True)])
def test_the_margin_is_the_stated_share_of_the_count_at_the_stop(monkeypatch, count, released):
    assert rollup_serve._SHRINK_TO_RETRY == 0.05
    _old(monkeypatch)
    _restart()
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: count)  # 4% and 6% below 12,000,000
    calls, outcome = _build_attempts(monkeypatch)
    assert (outcome, calls) == (("built", [1]) if released else ("declined", []))


def test_the_whole_table_is_not_counted_more_than_once_a_minute_even_with_a_zero_ttl(monkeypatch):
    counted = []
    monkeypatch.setattr(rollup_serve, "rollup_serve_ttl_s", lambda: 0)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: counted.append(1) or 12_000_000)
    _stop(monkeypatch)  # just now
    _restart()
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)  # a re-index drain moves it
    for _ in range(3):
        assert rollup_serve._stopped_build_verdict()["reason"] == "duckdb-limit"
    assert counted == [], "the epoch moved but the stop is seconds old"
    rollup_serve._STATE["stopped"]["checked_at"] = time.time() - rollup_serve._COUNT_MIN_INTERVAL_S - 1
    rollup_serve._stopped_build_verdict()
    assert counted == [1]


def test_a_second_caller_waits_for_the_read_of_the_kept_stop_instead_of_seeing_nothing(monkeypatch):
    _stop(monkeypatch)
    _restart()
    real = rollup_hold.read
    entered, go = threading.Event(), threading.Event()

    def slow():
        entered.set()
        assert go.wait(10)
        return real()

    monkeypatch.setattr(rollup_hold, "read", slow)
    results: dict = {}
    first = threading.Thread(target=lambda: results.update(a=rollup_serve._stopped_hold()))
    first.start()
    assert entered.wait(10)
    second = threading.Thread(target=lambda: results.update(b=rollup_serve._stopped_hold()))
    second.start()
    second.join(0.3)
    assert second.is_alive() or results.get("b"), "it must not return 'no hold' while the file is being read"
    go.set()
    first.join(10)
    second.join(10)
    assert results["a"] and results["b"] and results["b"]["reason"] == "duckdb-limit"


def test_repeats_counts_the_echoes_of_a_stop_restored_from_the_file(monkeypatch):
    _stop(monkeypatch)
    _restart()
    for _ in range(3):
        assert _build_attempts(monkeypatch)[1] == "declined"
    d = rollup_serve.status()["last_decline"]
    assert d["source"] == "stopped" and d["restored"] is True and d["repeats"] == 2


def test_a_stop_under_a_passphrase_is_released_where_offload_is_allowed(monkeypatch, _env):
    monkeypatch.setattr(rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": 1005.0, "offload_allowed": False})
    _stop(monkeypatch)
    assert json.loads(_env.read_text(encoding="utf-8"))["offload_allowed"] is False
    _restart()
    calls, outcome = _build_attempts(monkeypatch)
    assert (outcome, calls) == ("declined", []), "still a wall"
    monkeypatch.setattr(rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": 1005.0, "offload_allowed": True})
    calls, outcome = _build_attempts(monkeypatch)
    assert (outcome, calls) == ("built", [1]) and not _env.exists()


def test_offload_that_was_allowed_at_the_stop_is_not_a_release(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": 1005.0, "offload_allowed": True})
    _stop(monkeypatch)
    _restart()
    assert _build_attempts(monkeypatch)[1] == "declined"
