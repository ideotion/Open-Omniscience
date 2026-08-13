"""The learned collector concurrency ceiling (src/scheduler/capacity.py).

The property that makes this safe to ship on every machine is the NEGATIVE one: a box
that has never backed off under memory pressure must behave byte-identically to before.
That is asserted first and in several directions, because a ceiling that leaked onto
healthy hardware would quietly halve everyone's collection throughput.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.scheduler import capacity
from src.scheduler.bandwidth import DEFAULT_SEED, BandwidthGovernor


@pytest.fixture()
def state(tmp_path):
    return tmp_path / "collect_capacity.json"


# --------------------------------------------------------------------------- #
#  The no-op property: hardware that never shows pressure is untouched.
# --------------------------------------------------------------------------- #


def test_a_machine_that_never_saw_pressure_seeds_at_the_configured_max(state):
    assert not state.exists()
    assert capacity.load_ceiling(state) is None
    assert capacity.seed_for(50, state) == 50


def test_a_clean_pass_on_an_unrecorded_machine_writes_nothing_at_all(state):
    out = capacity.record_pass(
        w_max=50, mem_low_ticks=0, mem_low_min_permits=None, state_path=state
    )
    assert out is None
    assert not state.exists(), "a healthy machine must carry no capacity state"


def test_many_clean_passes_never_start_lowering_a_healthy_machine(state):
    for _ in range(25):
        capacity.record_pass(
            w_max=50, mem_low_ticks=0, mem_low_min_permits=None, state_path=state
        )
    assert capacity.seed_for(50, state) == 50
    assert not state.exists()


# --------------------------------------------------------------------------- #
#  The measured direction: a pressured pass is remembered.
# --------------------------------------------------------------------------- #


def test_a_pressured_pass_seeds_the_next_one_at_the_floor_it_reached(state):
    capacity.record_pass(
        w_max=50, mem_low_ticks=28, mem_low_min_permits=1, state_path=state
    )
    assert capacity.load_ceiling(state) == 1
    assert capacity.seed_for(50, state) == 1


def test_pressure_never_raises_an_existing_ceiling(state):
    capacity.record_pass(w_max=50, mem_low_ticks=9, mem_low_min_permits=4, state_path=state)
    # A later pass that only got as low as 20 saw pressure too — it is not evidence
    # that the machine gained headroom.
    capacity.record_pass(w_max=50, mem_low_ticks=2, mem_low_min_permits=20, state_path=state)
    assert capacity.load_ceiling(state) == 4


def test_pressure_with_no_recorded_floor_invents_nothing(state):
    out = capacity.record_pass(
        w_max=50, mem_low_ticks=5, mem_low_min_permits=None, state_path=state
    )
    assert out is None
    assert not state.exists()


def test_a_pass_that_ran_no_monitor_leaves_the_ceiling_untouched(state):
    capacity.record_pass(w_max=50, mem_low_ticks=3, mem_low_min_permits=6, state_path=state)
    out = capacity.record_pass(
        w_max=50, mem_low_ticks=None, mem_low_min_permits=None, state_path=state
    )
    assert out == 6, "an absent measurement is not a measurement of no pressure"
    assert capacity.load_ceiling(state) == 6


# --------------------------------------------------------------------------- #
#  Recovery: a ceiling is a memory of pressure, not a life sentence.
# --------------------------------------------------------------------------- #


def test_clean_passes_relax_the_ceiling_and_then_clear_it(state):
    capacity.record_pass(w_max=50, mem_low_ticks=28, mem_low_min_permits=1, state_path=state)
    seen = []
    for _ in range(8):
        seen.append(
            capacity.record_pass(
                w_max=50, mem_low_ticks=0, mem_low_min_permits=None, state_path=state
            )
        )
        if seen[-1] is None:
            break
    assert seen == [2, 4, 8, 16, 32, None], seen
    assert not state.exists(), "back at the configured max -> carry no state"
    assert capacity.seed_for(50, state) == 50


def test_a_data_dir_moved_to_a_bigger_machine_heals_rather_than_pinning_it(state):
    # Recorded on a small box...
    capacity.record_pass(w_max=50, mem_low_ticks=30, mem_low_min_permits=1, state_path=state)
    # ...then carried to one that never trips the guard.
    for _ in range(6):
        capacity.record_pass(
            w_max=50, mem_low_ticks=0, mem_low_min_permits=None, state_path=state
        )
    assert capacity.seed_for(50, state) == 50


# --------------------------------------------------------------------------- #
#  Degrade paths: a hint must never break a pass.
# --------------------------------------------------------------------------- #


def test_a_corrupt_state_file_degrades_to_no_ceiling(state):
    state.write_text("{not json", "utf-8")
    assert capacity.load_ceiling(state) is None
    assert capacity.seed_for(50, state) == 50


@pytest.mark.parametrize("bad", [0, -3, "12", 1.5, True, None])
def test_a_nonsense_stored_ceiling_is_refused(state, bad):
    state.write_text(json.dumps({"schema": capacity.SCHEMA, "ceiling": bad}), "utf-8")
    assert capacity.load_ceiling(state) is None


def test_an_unwritable_state_path_does_not_raise(tmp_path):
    missing = tmp_path / "nope" / "deeper" / "collect_capacity.json"
    # No exception: the pass that just finished is worth more than the hint.
    capacity.record_pass(
        w_max=50, mem_low_ticks=4, mem_low_min_permits=2, state_path=missing
    )
    assert capacity.load_ceiling(missing) is None


def test_a_ceiling_above_the_configured_max_is_clamped(state):
    state.write_text(json.dumps({"schema": capacity.SCHEMA, "ceiling": 40}), "utf-8")
    assert capacity.seed_for(8, state) == 8


def test_the_report_separates_never_measured_from_measured_one(state):
    unmeasured = capacity.state_report(50, state)
    assert unmeasured["learned_ceiling"] is None
    assert unmeasured["measured"] is False
    assert unmeasured["seed_next_pass"] == 50

    capacity.record_pass(w_max=50, mem_low_ticks=28, mem_low_min_permits=1, state_path=state)
    measured = capacity.state_report(50, state)
    assert measured["learned_ceiling"] == 1
    assert measured["measured"] is True


def test_the_report_publishes_no_score_named_field(state):
    banned = ("score", "rating", "rank", "grade", "trust")
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in k.lower() for b in banned), k
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(capacity.state_report(50, state))


# --------------------------------------------------------------------------- #
#  The governor half.
# --------------------------------------------------------------------------- #


def test_an_explicit_seed_is_honoured_in_maximum_mode(state):
    """The bug that would have made the whole mechanism a no-op on the reporting box.

    ``maximum`` mode used to overwrite any explicit seed with ``w_max`` unconditionally,
    and ``maximum`` is precisely the mode a throughput-tuned install runs in.
    """
    gov = BandwidthGovernor(mode="maximum", w_max=50, seed=3)
    assert gov.permits == 3


def test_no_seed_still_opens_wide_in_maximum_mode_and_eases_in_on_target():
    assert BandwidthGovernor(mode="maximum", w_max=50).permits == 50
    assert BandwidthGovernor(mode="target", w_max=50).permits == min(DEFAULT_SEED, 50)


def test_memory_pressure_halves_while_other_contention_steps_by_one():
    gov = BandwidthGovernor(mode="maximum", w_max=50)
    permits, reason = gov.observe(0.0, mem_low=True)
    assert (permits, reason) == (25, "mem-low")

    other = BandwidthGovernor(mode="maximum", w_max=50)
    permits, reason = other.observe(0.0, writer_saturated=True)
    assert (permits, reason) == (49, "writer-saturated")

    cpu = BandwidthGovernor(mode="maximum", w_max=50)
    permits, reason = cpu.observe(0.0, cpu_saturated=True)
    assert (permits, reason) == (49, "cpu-saturated")


def test_the_descent_under_memory_pressure_reaches_the_floor_in_a_handful_of_ticks():
    """Each descending tick is a tick spent AT the pressure that caused it.

    The field log shows 28 linear ticks over 43 s on a box at 150-300 MB available;
    the same descent is 6 ticks here. The exact count is asserted because 'fewer' is
    the entire point of the change.
    """
    gov = BandwidthGovernor(mode="maximum", w_max=50)
    seen = [50]
    while seen[-1] > 1:
        seen.append(gov.observe(0.0, mem_low=True)[0])
    assert seen == [50, 25, 12, 6, 3, 1], seen


def test_memory_pressure_never_drives_permits_below_one():
    gov = BandwidthGovernor(mode="maximum", w_max=50, seed=1)
    for _ in range(10):
        assert gov.observe(0.0, mem_low=True)[0] == 1


# --------------------------------------------------------------------------- #
#  The wiring. Parsed, never grepped: the runner's own comments at both call
#  sites contain the words "capacity" and "seed", so any substring assertion
#  here would be satisfied by the explanation of code that had been deleted.
# --------------------------------------------------------------------------- #


def _runner_tree():
    import ast
    import pathlib

    import src.scheduler.runner as runner

    return ast.parse(pathlib.Path(runner.__file__).read_text(encoding="utf-8"))


def test_the_runner_seeds_the_governor_from_the_learned_ceiling():
    import ast

    calls = [
        n
        for n in ast.walk(_runner_tree())
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "BandwidthGovernor"
    ]
    assert calls, "the runner no longer constructs a BandwidthGovernor"
    for call in calls:
        seed = next((kw for kw in call.keywords if kw.arg == "seed"), None)
        assert seed is not None, (
            "the collection governor is built without seed= — every pass would "
            "restart at w_max and re-walk the descent this module exists to remember"
        )
        # ...and the seed must come from the learned ceiling, not a literal.
        assert isinstance(seed.value, ast.Call), ast.dump(seed.value)
        assert (
            getattr(seed.value.func, "attr", None) == "seed_for"
        ), ast.dump(seed.value.func)


# --------------------------------------------------------------------------- #
#  The shape contract. Driven through a REAL CollectionMonitor, because both
#  numbers are nested under "bottleneck" and a top-level read returns None for
#  each -- which record_pass correctly reads as "this pass said nothing", so the
#  ceiling would never be recorded and every test above would still pass.
# --------------------------------------------------------------------------- #


def test_from_summary_finds_the_numbers_where_a_real_pass_actually_puts_them(tmp_path, monkeypatch):
    from src.monitoring import collect_perf as cp

    monkeypatch.setattr(cp, "_log_path", lambda: tmp_path / "collect_perf.jsonl")

    gov = BandwidthGovernor(mode="maximum", w_max=8)
    monitor = cp.CollectionMonitor(
        governor=gov, pass_id="shape-probe", mode="rss", mem_floor_mb=10_000_000.0
    )
    monitor.start()
    monitor._tick()  # mem_floor is absurdly high, so this tick reads as mem-low
    summary = monitor.stop(result={"articles_stored": 0})

    assert summary is not None, "the probe produced no summary at all"
    ticks, floor = capacity.from_summary(summary)
    assert ticks is not None and ticks > 0, (
        "from_summary did not find mem_low_ticks in a real pass summary — the wiring "
        "would silently never record a ceiling"
    )
    assert floor is not None and floor >= 1
    # ...and the trap is real: the same keys are absent from the top level.
    assert summary.get("mem_low_ticks") is None
    assert summary.get("mem_low_min_permits") is None


def test_from_summary_refuses_an_unreadable_summary_rather_than_reading_zero():
    for bad in (None, {}, {"bottleneck": None}, {"bottleneck": []}, "nope"):
        assert capacity.from_summary(bad) == (None, None), bad
    # A pass that genuinely saw no pressure reports 0 — distinct from unreadable.
    assert capacity.from_summary(
        {"bottleneck": {"mem_low_ticks": 0, "mem_low_min_permits": None}}
    ) == (0, None)


def test_the_learned_ceiling_reaches_a_reader():
    """A ceiling nothing surfaces is a silent throttle: the operator sees 4 workers where
    they configured 50 and has nowhere to look. Guarded as a CALL, because the block's own
    comment names the module."""
    import ast
    import pathlib

    import src.api.diagnostics as diagnostics

    tree = ast.parse(pathlib.Path(diagnostics.__file__).read_text(encoding="utf-8"))
    called = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", None))
        in {"_capacity_report", "state_report"}
    ]
    assert called, "the learned ceiling is never reported anywhere"


def test_the_reader_gets_a_real_answer_on_this_machine():
    """The happy path, not just the degrade path — an `available: False` block that had
    quietly become permanent would look identical to a healthy absence otherwise."""
    from src.scheduler.settings import load_settings

    report = capacity.state_report(
        int(getattr(load_settings(), "collect_parallelism", 1) or 1)
    )
    assert report["schema"] == capacity.SCHEMA
    assert report["configured_max_workers"] >= 1
    assert report["seed_next_pass"] >= 1


def test_the_runner_records_each_finished_pass():
    import ast

    recorded = [
        n
        for n in ast.walk(_runner_tree())
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "record_pass"
    ]
    assert recorded, "nothing feeds the pass outcome back — the ceiling never learns"
    passed = {kw.arg for call in recorded for kw in call.keywords}
    assert {"w_max", "mem_low_ticks", "mem_low_min_permits"} <= passed, passed
