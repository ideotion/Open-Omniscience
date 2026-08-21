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


def test_a_machine_that_never_saw_pressure_has_no_opinion_about_the_seed(state):
    """None, never w_max. Returning w_max would start TARGET mode wide open instead of
    easing in from DEFAULT_SEED — a real behaviour change on machines this module is
    supposed to leave alone, and one that looks identical in maximum mode."""
    assert not state.exists()
    assert capacity.load_ceiling(state) is None
    assert capacity.seed_for(50, state) is None


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
    assert capacity.seed_for(50, state) is None
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
    assert capacity.seed_for(50, state) is None


def test_a_data_dir_moved_to_a_bigger_machine_heals_rather_than_pinning_it(state):
    # Recorded on a small box...
    capacity.record_pass(w_max=50, mem_low_ticks=30, mem_low_min_permits=1, state_path=state)
    # ...then carried to one that never trips the guard.
    for _ in range(6):
        capacity.record_pass(
            w_max=50, mem_low_ticks=0, mem_low_min_permits=None, state_path=state
        )
    assert capacity.seed_for(50, state) is None


# --------------------------------------------------------------------------- #
#  Degrade paths: a hint must never break a pass.
# --------------------------------------------------------------------------- #


def test_a_corrupt_state_file_degrades_to_no_ceiling(state):
    state.write_text("{not json", "utf-8")
    assert capacity.load_ceiling(state) is None
    assert capacity.seed_for(50, state) is None


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
    assert unmeasured["ramp_capped_at"] == 50

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


def test_an_unmeasured_machine_keeps_its_rate_modes_own_starting_point():
    """The regression this contract exists to prevent: seed_for once returned w_max on
    an unmeasured machine, and the runner passes it explicitly, so target mode started
    wide open at 50 instead of easing in from DEFAULT_SEED. Invisible in maximum mode,
    where both values are the same number."""
    assert BandwidthGovernor(mode="target", w_max=50, seed=None).permits == DEFAULT_SEED
    assert BandwidthGovernor(mode="maximum", w_max=50, seed=None).permits == 50


# --------------------------------------------------------------------------- #
#  The ramp cap. The ceiling bounds where a pass GOES, not just where it starts.
# --------------------------------------------------------------------------- #


def test_the_ramp_stops_at_the_learned_ceiling_instead_of_climbing_to_w_max():
    gov = BandwidthGovernor(mode="maximum", w_max=50, seed=2, ramp_ceiling=6)
    seen = []
    for i in range(12):
        seen.append(gov.observe(0.0, now=float(i) * 10.0)[0])
    assert max(seen) == 6, seen
    assert gov.observe(0.0, now=500.0) == (6, "at-learned-ceiling")


def test_with_no_ceiling_the_ramp_still_reaches_w_max_and_says_at_ceiling():
    gov = BandwidthGovernor(mode="maximum", w_max=8, seed=2)
    for i in range(12):
        gov.observe(0.0, now=float(i) * 10.0)
    assert gov.permits == 8
    assert gov.observe(0.0, now=500.0) == (8, "at-ceiling")


def test_a_ceiling_at_or_above_w_max_is_indistinguishable_from_none():
    """Clamped, and still reports the plain reason — the learned wording must not appear
    when nothing is actually being held back."""
    gov = BandwidthGovernor(mode="maximum", w_max=8, seed=8, ramp_ceiling=99)
    assert gov.ramp_ceiling == 8
    assert gov.observe(0.0, now=500.0) == (8, "at-ceiling")


def test_the_ramp_recovers_within_a_pass_but_only_back_to_the_ceiling():
    """A mid-pass dip must not strand the pass at the floor — it climbs back to where
    the pass began, and no further."""
    gov = BandwidthGovernor(mode="maximum", w_max=50, seed=8, ramp_ceiling=8)
    assert gov.observe(0.0, mem_low=True, now=1.0)[0] == 4  # pressure halves it
    for i in range(10):
        gov.observe(0.0, now=10.0 + i * 10.0)  # pressure gone; ramp back up
    assert gov.permits == 8


def test_target_mode_below_target_also_stops_at_the_learned_ceiling():
    gov = BandwidthGovernor(mode="target", target_kbps=500, w_max=50, seed=2, ramp_ceiling=5)
    for i in range(20):
        gov.observe(1.0, now=float(i) * 10.0)  # 1 KiB/s: forever below target
    assert gov.permits == 5
    # ...and says so, rather than "in-band", which would claim the rate is fine.
    assert gov.observe(1.0, now=500.0) == (5, "at-learned-ceiling")


def test_target_mode_without_a_ceiling_keeps_its_original_reasons():
    gov = BandwidthGovernor(mode="target", target_kbps=500, w_max=4, seed=4)
    assert gov.observe(1.0, now=100.0) == (4, "in-band")
    assert gov.observe(10_000.0, now=200.0) == (3, "above-target")
    assert gov.observe(1.0, now=300.0) == (4, "below-target")


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

    tree = _runner_tree()

    def _is_seed_for(node) -> bool:
        return isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "seed_for"

    # Local names bound from a seed_for(...) call, so the guard follows the binding
    # instead of demanding the call appear inline at the keyword.
    bound = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and _is_seed_for(n.value)
        for t in n.targets
        if isinstance(t, ast.Name)
    }

    def _from_learned_ceiling(node) -> bool:
        return _is_seed_for(node) or (isinstance(node, ast.Name) and node.id in bound)

    for call in calls:
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "seed" in kwargs, (
            "the collection governor is built without seed= — every pass would "
            "restart at w_max and re-walk the descent this module exists to remember"
        )
        assert "ramp_ceiling" in kwargs, (
            "the governor is built without ramp_ceiling= — the learned ceiling would "
            "bound only where a pass STARTS, and the ramp would climb back toward "
            "w_max inside the same pass and re-trigger the pressure"
        )
        for name in ("seed", "ramp_ceiling"):
            assert _from_learned_ceiling(kwargs[name]), f"{name}: {ast.dump(kwargs[name])}"
        # Both must be the SAME value: a pass seeded at one level and allowed to ramp
        # to another is not the behaviour either argument describes.
        seed_src = getattr(kwargs["seed"], "id", None)
        ramp_src = getattr(kwargs["ramp_ceiling"], "id", None)
        assert seed_src is not None and seed_src == ramp_src, (
            "seed and ramp_ceiling must come from one binding of the learned ceiling"
        )


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
    # Vitals are INJECTED rather than read from psutil: the contract under test is the
    # payload's shape, and a live memory reading would make it depend on how much RAM
    # the CI runner happens to have free (it runs on Linux, macOS and Windows).
    monitor = cp.CollectionMonitor(
        governor=gov,
        pass_id="shape-probe",
        mode="rss",
        mem_floor_mb=512.0,
        rate_fn=lambda: 0.0,
        vitals_fn=lambda: {"cpu_sys_pct": 1.0, "mem_avail_mb": 8.0, "rss_mb": 100.0},
        writer_stats_fn=lambda: {},
    )
    monitor.start()
    monitor._tick()  # 8 MB available against a 512 MB floor -> unambiguously mem-low
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
    assert report["ramp_capped_at"] >= 1


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
