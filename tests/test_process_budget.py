"""S04-13 S1 (Q1012 = a): the per-PROCESS bandwidth budget, composed with the governor.

    "A per-PROCESS budget composed with the collection-speed governor
    (``#rate-toggle``), never a second rate authority beside it; per-job caps stay
    omitted."

MOST OF THESE TESTS ARE ABOUT THE TWO PROPERTIES THAT CAN SILENTLY STOP HOLDING,
because both would leave a green suite and a wrong app:

  * **ONE authority.** The budget must be DERIVED from the governor's own mode and
    target. A second stored ceiling anywhere is the defect the ruling names, and it
    would look exactly like this one from outside until the two drifted.
  * **The refusals.** An unmeasurable download is absent with a reason, never a 0,
    and a sum missing a component says so. Both are one character away from their
    opposite in source (``if x`` versus ``if x is not None``), and no grep-level
    guard can tell those apart -- so every one of these drives the real function.

The clock and the samplers are real; the governor is the real class. Nothing here
is a hand-written double of a payload, because the recorded resolver-stub lesson is
that a double drifts and then agrees with the defect.
"""

from __future__ import annotations

import inspect

import pytest

from src.ingest.download_rate import RateRegistry, RateSampler, process_download_rate
from src.scheduler import process_budget
from src.scheduler.bandwidth import BandwidthGovernor


def _gov(mode: str = "target", target_kbps: int = 500) -> BandwidthGovernor:
    return BandwidthGovernor(mode=mode, target_kbps=target_kbps, w_max=50)


def _measuring_sampler(rate_bytes_per_s: float) -> RateSampler:
    """A sampler that really is measuring, on an INJECTED clock.

    ``RateSampler`` takes ``clock`` precisely so a rate can be asserted exactly
    instead of slept for; a real-time version of these tests would need a >1 s sleep
    (``_MIN_SPAN_S``) and would then be a timing threshold to recalibrate on the
    first slow runner -- the recorded shape this project keeps having to undo.
    """
    t = [1000.0]
    s = RateSampler(clock=lambda: t[0])
    s.observe(0)
    t[0] += 2.0
    s.observe(int(rate_bytes_per_s * 2))
    return s


def _register(reg: RateRegistry, key: str, sampler: RateSampler) -> None:
    """Place a clock-injected sampler into a real registry.

    Reaches past ``start()`` (which builds its own default-clock sampler) ONLY to
    substitute the clock. The aggregation being tested here -- ``live_rates`` ->
    ``process_download_rate`` -- is driven for real; ``tests/test_download_rate.py``
    already covers the start/reset path this skips.
    """
    reg._by_key[key] = sampler


# --------------------------------------------------------------------------- #
# ONE authority
# --------------------------------------------------------------------------- #


def test_the_budget_is_read_from_the_governor_never_stored_beside_it():
    """The ceiling follows the governor, because it IS the governor's own field.

    Mutating the governor's target must move the budget with no re-plumbing: that
    is what "composed with, never beside" means operationally. A module that had
    cached or copied the value would keep answering the old number here.
    """
    gov = _gov(target_kbps=500)
    assert process_budget.budget_kbps(gov) == 500
    gov.target_kbps = 1200
    assert process_budget.budget_kbps(gov) == 1200, (
        "the budget did not follow the governor's target -- it is being stored "
        "somewhere else, which is the second rate authority Q1012 forbids"
    )


def test_maximum_mode_has_no_ceiling_and_it_is_None_rather_than_zero():
    """``None`` and ``0`` are opposite instructions and must never be conflated.

    A 0 would read as "no bytes allowed" -- the strictest possible budget -- where
    the operator asked for the loosest. This is the recorded one-key-two-meanings
    defect in its most expensive direction.
    """
    assert process_budget.budget_kbps(_gov(mode="maximum")) is None
    out = process_budget.compose(_gov(mode="maximum"), 900.0)
    assert out["budget_kbps"] is None
    assert out["over_budget"] is None, "no ceiling cannot be exceeded"
    assert "maximum" in out["budget_reason"]


def test_a_missing_or_unreadable_target_yields_no_ceiling_rather_than_a_guess():
    class _Broken:
        mode = "target"
        target_kbps = "not a number"

    assert process_budget.budget_kbps(_Broken()) is None
    assert process_budget.budget_kbps(object()) is None


def test_no_second_ceiling_constant_lives_in_this_module():
    """Anti-vacuity for the claim above: the module must hold no rate number at all.

    ``budget_kbps`` reading the governor is only half the property. The other half
    is that there is nowhere else for a ceiling to be written down, so a future edit
    cannot quietly introduce one and still pass the test above.
    """
    src = inspect.getsource(process_budget)
    body = "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith(("#", "*"))
    )
    for suspicious in ("DEFAULT_TARGET", "MAX_KBPS", "_CEILING", "BUDGET_KBPS ="):
        assert suspicious not in body, (
            f"{suspicious!r} looks like a second rate authority in the one module "
            "whose whole purpose is that there is only one"
        )


# --------------------------------------------------------------------------- #
# The arithmetic
# --------------------------------------------------------------------------- #


def test_bytes_are_converted_to_the_governor_s_own_unit_before_being_added():
    """The two inputs arrive in DIFFERENT units and adding them raw is a 8000x error.

    The collector's figure is already kbit/s (``collect_perf._measure_rate`` does
    ``bytes * 8 / 1000``); the samplers report BYTES/s. 1 kbit/s is 125 bytes/s, so
    the conversion is the load-bearing line and it is asserted exactly rather than
    approximately.
    """
    assert process_budget.bytes_per_s_to_kbps(125.0) == 1.0
    assert process_budget.bytes_per_s_to_kbps(1000.0) == 8.0
    assert process_budget.bytes_per_s_to_kbps(0.0) == 0.0


def test_the_process_total_is_the_collector_plus_the_downloads():
    out = process_budget.compose(
        _gov(target_kbps=500),
        100.0,
        download_rate={"measured": True, "bytes_per_s": 12500.0, "unmeasured": []},
    )
    # 12500 B/s = 100 kbit/s, so the process is 200 against a 500 budget.
    assert out["downloads_kbps"] == 100.0
    assert out["process_kbps"] == 200.0
    assert out["collector_kbps"] == 100.0
    assert out["over_budget"] is False


def test_the_process_total_is_what_decides_over_budget_not_the_collector_alone():
    """The defect this whole slice exists to fix, stated as a test.

    Before composition the governor saw only the collector, so a download saturating
    the line left the app reporting itself comfortably under the operator's target.
    """
    out = process_budget.compose(
        _gov(target_kbps=500),
        50.0,  # the collector alone is nowhere near the budget
        download_rate={"measured": True, "bytes_per_s": 200_000.0, "unmeasured": []},
    )
    assert out["collector_kbps"] < 500
    assert out["process_kbps"] > 500
    assert out["over_budget"] is True, (
        "a file download saturating the line must put the PROCESS over budget; "
        "reading the collector alone is the pre-S04-13 blindness"
    )


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #


def test_an_unmeasurable_download_is_absent_with_a_reason_never_zero():
    out = process_budget.compose(
        _gov(),
        100.0,
        download_rate={
            "measured": False,
            "reason": "downloads are running but none is measurable yet",
            "unmeasured": [{"key": "oo-dump-en", "reason": "only one sample in the window so far"}],
        },
    )
    assert out["downloads_kbps"] is None, (
        "an unmeasurable download rendered as a number -- a 0 here claims the "
        "download is contributing nothing, which is not what was measured"
    )
    assert out["downloads_measured"] is False
    assert out["downloads_reason"] == "downloads are running but none is measurable yet"


def test_a_total_missing_a_component_is_flagged_as_a_lower_bound():
    out = process_budget.compose(
        _gov(),
        100.0,
        download_rate={
            "measured": True,
            "bytes_per_s": 1250.0,
            "unmeasured": [{"key": "osm-fr", "reason": "no bytes observed yet"}],
        },
    )
    assert out["partial"] is True
    assert out["unmeasured"], "the components left out must be named, not merely counted"
    assert "lower bound" in out["budget_reason"]


def test_an_idle_process_is_not_the_same_fact_as_an_unmeasurable_one():
    """Three states, not two. ``idle`` says there is nothing to measure."""
    out = process_budget.compose(_gov(), 10.0, download_rate=process_download_rate())
    assert out["downloads_idle"] is True
    assert out["downloads_measured"] is False
    assert out["partial"] is False, "nothing running is not a missing measurement"


def test_over_budget_by_a_download_says_that_cutting_collection_cannot_help():
    """The governor's only lever is collector permits. When the overage is not the
    collector's, the disclosure has to say so or an operator reads one-worker
    collection as a broken collector."""
    out = process_budget.compose(
        _gov(target_kbps=500),
        20.0,
        download_rate={"measured": True, "bytes_per_s": 500_000.0, "unmeasured": []},
    )
    assert out["over_budget"] is True
    assert "cannot recover it" in out["budget_reason"]
    assert out["governed_kbps"] == 20.0, (
        "the share the governor can actually move must be published separately "
        "from the share it cannot"
    )


# --------------------------------------------------------------------------- #
# The process-wide aggregator
# --------------------------------------------------------------------------- #


def test_the_aggregator_sums_only_samplers_that_are_really_measuring():
    reg = RateRegistry()
    _register(reg, "measured-one", _measuring_sampler(2500.0))
    young = RateSampler(clock=lambda: 1002.0)
    young.observe(0)  # one sample: a window that has only just opened
    _register(reg, "too-young", young)

    out = process_download_rate()
    assert out["measured"] is True
    assert out["bytes_per_s"] == pytest.approx(2500.0, rel=0.01)
    assert out["downloads_measured"] == 1
    keys = {u["key"] for u in out["unmeasured"]}
    assert "too-young" in keys, "a sampler that cannot measure must be NAMED, not dropped"
    reg.forget("measured-one")
    reg.forget("too-young")


def test_a_registry_that_goes_away_stops_being_counted():
    """The WeakSet is the mechanism: a manager that is collected takes its
    downloads with it, so a finished job cannot keep contributing to the budget."""
    reg = RateRegistry()
    _register(reg, "temporary", _measuring_sampler(2500.0))
    s = reg._by_key["temporary"]
    assert process_download_rate()["downloads_measured"] == 1
    del reg, s
    import gc

    gc.collect()
    assert process_download_rate()["downloads_measured"] == 0


# --------------------------------------------------------------------------- #
# The wiring. A composition nothing calls is the recorded dead end.
# --------------------------------------------------------------------------- #


def test_the_governor_is_fed_the_composed_process_rate_not_the_collector_share():
    """Drives the real ``_tick`` and asserts the number the CONTROLLER received.

    A source-level check that ``compose`` is imported would pass with the result
    thrown away; this one fails if the composed figure never reaches ``observe``.
    """
    from src.monitoring.collect_perf import CollectionMonitor

    seen: list[float] = []

    class _RecordingGov:
        mode = "target"
        target_kbps = 500
        permits = 10
        active = 3

        def observe(self, measured_kbps, **kw):
            seen.append(measured_kbps)
            return 10, "in-band"

        def stats(self):
            return {}

    reg = RateRegistry()
    _register(reg, "big-dump", _measuring_sampler(200_000.0))  # = 1600 kbit/s

    mon = CollectionMonitor(
        governor=_RecordingGov(),
        pass_id="test",
        mode="rss",
        rate_fn=lambda: 40.0,  # the collector's own share
        vitals_fn=lambda: {},
        writer_stats_fn=lambda: {},
    )
    mon._tick()
    reg.forget("big-dump")

    assert seen, "the governor was never asked to observe anything"
    assert seen[0] > 1000, (
        f"the governor received {seen[0]} -- that is the collector's share alone. "
        "The composed PROCESS rate is what the budget is about."
    )
