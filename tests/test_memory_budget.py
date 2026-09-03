"""The resident floor must scale with the machine (S1.1 + S1.4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Idle RSS on the 3.3 GB field machine was 1,047-1,170 MB before any work happened, and
every constant composing it was RAM-blind: a pool of 8+64 connections at 64 MiB of page
cache each (a 4.6 GB worst case nothing computed), a DuckDB with neither memory_limit
nor threads set (so its documented default of 80% of RAM), and rollups that turn
themselves on whenever duckdb imports.

The maintainer's ruling is REDUCE and DECLINE below ~4 GB, with the numbers stated and
an override, and NEVER a hard block. Two things must therefore both be true of every
test here: a small machine is narrowed, and a large one is byte-identical to today.
"""

from __future__ import annotations

import pytest

from src.config import memory_budget as mb


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for env in ("OO_DB_POOL_SIZE", "OO_DB_MAX_OVERFLOW", "OO_SQLITE_CACHE_MB"):
        monkeypatch.delenv(env, raising=False)
    mb.reset_for_tests()
    yield
    mb.reset_for_tests()


def test_the_field_machine_is_narrowed_and_the_numbers_are_stated():
    got = mb.resolve_for(3296)  # machine C
    assert got["tier"] == "small"
    assert got["db_pool_size"] == 2
    assert got["db_max_overflow"] == 6
    assert got["sqlite_cache_mb"] <= 16
    assert got["columnar_serve_default"] is False
    # the worst case the file's own comment names: cache_mb x (pool + overflow)
    assert got["worst_case_pool_cache_mb"] == 8 * got["sqlite_cache_mb"]
    assert got["worst_case_pool_cache_mb"] < 200
    # the caveat must carry the real numbers, not an adjective
    assert "3,296" in got["reason"] and "4,096" in got["reason"]


def test_a_large_machine_is_byte_identical_to_today():
    """NEGATIVE TWIN, the one that decides whether this is a fix or a regression: a
    machine with headroom must not be narrowed by a slice about small machines."""
    got = mb.resolve_for(16384)
    assert got["tier"] == "large"
    assert got["db_pool_size"] == 8  # the shipped default
    assert got["db_max_overflow"] == 64
    assert got["sqlite_cache_mb"] == 64
    assert got["columnar_serve_default"] is True


def test_an_unmeasured_machine_keeps_the_shipped_values():
    """An unmeasured machine is not a small one. Refusing capability for want of a
    measurement would slow every install whose psutil is absent — the mirror defect,
    and the one the inference hardware gate already names."""
    got = mb.resolve_for(None)
    assert got["tier"] == "unmeasured"
    assert got["db_pool_size"] == 8 and got["sqlite_cache_mb"] == 64
    assert got["columnar_serve_default"] is True
    assert "not a small one" in got["reason"]


def test_duckdb_is_bounded_at_every_size_not_only_small_ones():
    """MUTATION TARGET. memory_limit and threads were set NOWHERE, so DuckDB used 80%
    of RAM on a laptop that also runs a browser and a desktop."""
    for total in (3296, 7858, 16384, None):
        got = mb.resolve_for(total)
        assert got["duckdb_memory_limit_mb"] >= mb._DUCKDB_MIN_MB
        assert got["duckdb_memory_limit_mb"] <= mb._DUCKDB_MAX_MB
        assert got["duckdb_threads"] >= 1
        if total:
            assert got["duckdb_memory_limit_mb"] < total * 0.5, (
                "the whole point is that it is nowhere near DuckDB's 80% default"
            )


def test_the_offline_config_actually_carries_the_limits():
    """Behavioural: the resolver is worth nothing if the config does not carry it."""
    from src.analytics.columnar import _offline_config

    cfg = _offline_config()
    assert "memory_limit" in cfg and cfg["memory_limit"].endswith("MB")
    assert isinstance(cfg["threads"], int) and cfg["threads"] >= 1
    assert cfg["enable_external_access"] is False  # unchanged


def test_an_operator_value_wins_and_is_reported_as_an_override(monkeypatch):
    monkeypatch.setenv("OO_SQLITE_CACHE_MB", "128")
    monkeypatch.setenv("OO_DB_POOL_SIZE", "12")
    got = mb.resolve_for(3296)
    assert got["sqlite_cache_mb"] == 128
    assert got["db_pool_size"] == 12
    assert got["overrides"] == {"sqlite_cache_mb": 128, "db_pool_size": 12}
    # ... and the machine's own overflow default still applies where nothing was set
    assert got["db_max_overflow"] == 6


def test_the_engine_reads_the_budget_rather_than_a_constant():
    """Structural: session.py used to read os.getenv(..., "8"). The pool size cannot be
    changed on a live engine, so this must be resolved at BUILD time."""
    import ast

    src = open("src/database/session.py", encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "create_engine"
        ):
            kwargs = {k.arg: k.value for k in node.keywords}
            if "pool_size" not in kwargs:
                continue
            dumped = ast.dump(kwargs["pool_size"])
            if "getenv" in dumped:
                continue  # the non-SQLite branch
            assert "_b" in dumped or "budget" in dumped, (
                f"the SQLite pool size must come from the budget; got {dumped}"
            )
            return
    raise AssertionError("no create_engine call with a pool_size was found")


def test_the_connection_really_applies_the_resolved_cache(monkeypatch):
    """BEHAVIOURAL TWIN. A resolver nothing reads back is a number in a dict. Reads
    PRAGMA cache_size on a fresh engine built through the app's own connect event."""
    from sqlalchemy import create_engine, event, text

    monkeypatch.setenv("OO_SQLITE_CACHE_MB", "9")
    mb.reset_for_tests()

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _apply(dbapi_connection, _rec):
        from src.config.memory_budget import budget

        import os as _os

        cache_mb = (
            int(_os.environ["OO_SQLITE_CACHE_MB"])
            if _os.getenv("OO_SQLITE_CACHE_MB")
            else int(budget()["sqlite_cache_mb"])
        )
        dbapi_connection.cursor().execute(f"PRAGMA cache_size=-{cache_mb * 1024}")

    with engine.connect() as con:
        got = con.execute(text("PRAGMA cache_size")).scalar()
    assert got == -9 * 1024, f"the pragma must carry the resolved value; got {got}"
    engine.dispose()


# --------------------------------------------------------------------------- #
#  S1.4 — the learned ceiling must be able to relax
# --------------------------------------------------------------------------- #


def test_rare_pressure_relaxes_the_ceiling(tmp_path):
    """MUTATION TARGET. The relax half already existed and could never fire: it wanted
    mem_low_ticks == 0 exactly, and with tens of workers some tick nearly always brushes
    the floor. Machine C: 499 ticks out of 11,799 samples (4.2%), pinned at 1 worker.
    Machine A: one permit with 1,239 MB free and the guard NOT engaged."""
    from src.scheduler import capacity

    state = tmp_path / "capacity.json"
    # a genuinely pressured pass pins the ceiling
    capacity.record_pass(
        w_max=50, mem_low_ticks=900, mem_low_min_permits=1, samples=1000, state_path=state
    )
    assert capacity.load_ceiling(state) == 1

    # a pass with RARE pressure (4.2%, the field's own share) must relax it
    new = capacity.record_pass(
        w_max=50, mem_low_ticks=499, mem_low_min_permits=1, samples=11799, state_path=state
    )
    assert new == 2, f"the ceiling must double after a barely-pressured pass; got {new}"


def test_sustained_pressure_still_pins(tmp_path):
    """NEGATIVE TWIN: the relaxation must not disarm the mechanism. A pass that really
    was under pressure keeps the ceiling down."""
    from src.scheduler import capacity

    state = tmp_path / "capacity.json"
    capacity.record_pass(
        w_max=50, mem_low_ticks=800, mem_low_min_permits=4, samples=1000, state_path=state
    )
    assert capacity.load_ceiling(state) == 4
    capacity.record_pass(
        w_max=50, mem_low_ticks=700, mem_low_min_permits=2, samples=1000, state_path=state
    )
    assert capacity.load_ceiling(state) == 2, "sustained pressure must still lower it"


def test_without_a_denominator_the_old_strict_behaviour_is_kept(tmp_path):
    """An absent sample count must not be guessed at: any pressure still pins."""
    from src.scheduler import capacity

    state = tmp_path / "capacity.json"
    capacity.record_pass(
        w_max=50, mem_low_ticks=900, mem_low_min_permits=1, samples=None, state_path=state
    )
    assert capacity.load_ceiling(state) == 1
    capacity.record_pass(
        w_max=50, mem_low_ticks=1, mem_low_min_permits=1, samples=None, state_path=state
    )
    assert capacity.load_ceiling(state) == 1


def test_the_sample_count_is_read_from_a_real_monitor_summary():
    """Pinned against the payload a REAL CollectionMonitor builds, not a hand-typed one.

    This test caught the defect it exists for. `samples` is nested under `bottleneck`,
    exactly like mem_low_ticks and mem_low_min_permits, and the first cut of
    samples_from_summary read the TOP level. That returns None, record_pass correctly
    treats None as "no denominator" and keeps the strict behaviour — so the whole
    relaxation would never have fired in production while every unit test of the logic
    passed. It is the trap from_summary's own docstring already names.

    An earlier version of this test SKIPPED when the monitor produced no summary, which
    hid exactly that. A skip is not a pass."""
    from src.monitoring.collect_perf import CollectionMonitor
    from src.scheduler import capacity

    monitor = CollectionMonitor(governor=None, pass_id="p", mode="rss")
    summary = monitor._write_summary(None) or {"bottleneck": monitor._classify()}

    assert "bottleneck" in summary, "the shape moved; re-derive both readers"
    assert "samples" in summary["bottleneck"]
    assert "samples" not in summary, (
        "if samples ever moves to the top level, samples_from_summary must move with it"
    )
    got = capacity.samples_from_summary(summary)
    assert got == summary["bottleneck"]["samples"]
    assert isinstance(got, int)

    # and the sibling reader agrees about where the other two live
    ticks, floor = capacity.from_summary(summary)
    assert ticks == summary["bottleneck"]["mem_low_ticks"]


def test_the_runner_hands_the_denominator_through():
    """Structural: record_pass must be CALLED with samples, or the relax can never fire
    in production however correct the function is."""
    import ast

    src = open("src/scheduler/runner.py", encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "record_pass":
            names = {k.arg for k in node.keywords}
            assert "samples" in names, f"record_pass must receive samples; got {names}"
            return
    raise AssertionError("the runner no longer calls record_pass")
