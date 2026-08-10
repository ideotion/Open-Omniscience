"""The concurrency sweep measures concurrency — not a latency multiplied by a guess.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-09: "I see my GPU working only 20% ... Shouldn't we test several
scenarios with a dedicated diagnostic tool that I'll run on this machine?"

Two things had to be pinned. The MECHANISM, because a bench that silently ran everything
serially would still publish a plausible-looking curve and nothing would say otherwise —
so the fake client has a KNOWN per-call cost and the sweep must reproduce the arithmetic.
And the HONESTY, because the whole point is that the shipped budget's multiplier was
never measured: an unreadable GPU must report None rather than 0 (opposite findings), a
level where everything failed must report no rate at all, and the linear extrapolation
must stay labelled as the assumption it restates.
"""

from __future__ import annotations

import time

from src.monitoring.llm_throughput import (
    DEFAULT_LEVELS,
    run_throughput_bench,
    run_throughput_selftest,
    summarise_levels,
)


class _Client:
    """A client whose call cost is fixed, so the sweep has a known right answer."""

    def __init__(self, seconds: float = 0.02, fail: bool = False) -> None:
        self.seconds = seconds
        self.fail = fail

    def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
        time.sleep(self.seconds)
        if self.fail:
            raise RuntimeError("backend said no")

        class _R:
            prompt_eval_count = 10
            eval_count = 20
            total_duration = None
            load_duration = None
            prompt_eval_duration = None
            eval_duration = None

        return _R()


def _bench(**kw):
    return run_throughput_bench(
        client=_Client(**kw.pop("client_kw", {})),
        model="fake",
        backend_name="vllm",
        **kw,
    )


# --------------------------------------------------------------------------- #
#  the mechanism
# --------------------------------------------------------------------------- #
def test_more_workers_really_finish_the_same_batch_sooner():
    """The load-bearing one. Without it a serial bench publishes a plausible curve."""
    r = _bench(levels=(1, 4), calls_per_level=8)
    by = {lv["concurrency"]: lv for lv in r["levels"]}
    assert by[4]["batch_wall_s"] < by[1]["batch_wall_s"], (
        f"4 workers must beat 1: {by[4]['batch_wall_s']}s vs {by[1]['batch_wall_s']}s"
    )
    # And the rate must move WITH it, since the rate is the batch's own.
    assert by[4]["calls_per_hour"] > by[1]["calls_per_hour"]


class _SaturatingClient(_Client):
    """A backend that cannot really serve more than ``lanes`` at once.

    This is the case the whole bench is about: a GPU already saturated at some level,
    where asking for more workers buys nothing. A perfectly-scaling double cannot tell
    a measured rate from an assumed one — both come out the same — so the discriminating
    fixture has to be the one that STOPS scaling."""

    def __init__(self, seconds: float = 0.02, lanes: int = 2) -> None:
        super().__init__(seconds=seconds)
        import threading

        self._sem = threading.Semaphore(lanes)

    def generate(self, prompt, **kw):
        with self._sem:
            return super().generate(prompt, **kw)


def test_the_rate_is_measured_not_a_latency_multiplied_by_the_worker_count():
    """The assumption ``llm_bench.budget_translation`` makes is 3600/p50 x workers. On a
    saturated backend that overstates the truth several-fold, which is exactly the shape
    of a report that says "plenty of headroom" beside a GPU sitting at 20%.

    THE LOAD-INDEPENDENT CLAIM IS THE ARITHMETIC ONE, and that ordering is the lesson
    this test carries. The ratio below is an anti-vacuity companion -- it shows the wrong
    formula would have answered differently here -- but a ratio THRESHOLD cannot prove
    anything on a shared test runner: measured under CPU contention, a PERFECTLY-SCALING
    client reads 0.047-0.101 of its own assumed rate, so any "must be under a half" bar
    passes for the client it is supposed to distinguish. Do not re-derive a discriminating
    threshold from timings; the identity is what discriminates.

    CALIBRATION, recorded so the next session does not re-measure it. At 16 workers over
    32 calls with 2 real lanes the ratio was 0.083-0.192 under 8 competing spinners and
    0.061-0.157 under 12 -- against a 0.5 bar, better than 3x margin. The previous shape
    (8 workers, 16 calls) reached 0.368 in the same harness and 0.52 in a real full-suite
    run, i.e. it sat inside its own noise. The fixture was made HARDER rather than the bar
    softer, which is the only legitimate direction when a guard goes red.
    """
    r = run_throughput_bench(
        levels=(16,),
        calls_per_level=32,
        client=_SaturatingClient(seconds=0.02, lanes=2),
        model="fake",
        backend_name="vllm",
    )
    lv = r["levels"][0]
    measured = lv["calls_per_hour"]

    # THE CLAIM: the published rate is the batch's own arithmetic. Not an equality —
    # TWO roundings sit between the true rate and the published one, and the band has to
    # carry both. The wall is published to 3 dp, which puts the true rate inside
    # [lo, hi]; the rate is then published as an INTEGER, which moves it a further half
    # either way. Omitting that second term is what reddened the macOS lane at
    # "65251 outside [65214, 65251]" — a true rate of 65250.5-ish rounding up past a
    # bound computed as though it had not been rounded at all. The wall's own band is
    # ~37/h wide here and the rate's rounding is 1/h, so the missing term is small but
    # decisive exactly at the edge, which is where a boundary assertion lives.
    wall_half, rate_half = 0.0005, 0.5
    lo = lv["n"] / (lv["batch_wall_s"] + wall_half) * 3600 - rate_half
    hi = lv["n"] / (lv["batch_wall_s"] - wall_half) * 3600 + rate_half
    assert lo <= measured <= hi, f"{measured} outside [{lo:.0f}, {hi:.0f}]"

    # ANTI-VACUITY: on this fixture the two formulas genuinely disagree, so the identity
    # above is not satisfied by both at once.
    assumed = (3600.0 / lv["call_wall_p50_s"]) * lv["concurrency"]
    assert measured < assumed / 2, (
        "with only two real lanes, sixteen workers cannot be twice the measured "
        f"rate: measured={measured}/h, assumed={round(assumed)}/h"
    )


def test_a_serial_batch_wall_is_the_sum_of_its_calls():
    r = _bench(levels=(1,), calls_per_level=6, client_kw={"seconds": 0.05})
    assert r["levels"][0]["batch_wall_s"] >= 6 * 0.05 * 0.9


def test_the_warmup_is_not_counted_in_any_level():
    """It carries model load and would land entirely on the baseline."""
    r = _bench(levels=(1,), calls_per_level=4)
    assert r["levels"][0]["requested_calls"] == 4
    assert r["levels"][0]["n"] == 4


# --------------------------------------------------------------------------- #
#  honesty
# --------------------------------------------------------------------------- #
def test_a_level_where_everything_failed_reports_no_rate():
    """Not a rate over zero samples, and not a zero — the errors are the finding."""
    r = _bench(levels=(2,), calls_per_level=4, client_kw={"fail": True})
    lv = r["levels"][0]
    assert lv["n"] == 0 and lv["failed_n"] == 4
    assert lv["calls_per_hour"] is None
    assert lv["errors"], "the reasons must travel, not just the count"


def test_an_unreadable_gpu_is_absent_rather_than_zero():
    """"We could not look" and "the GPU was idle" are opposite findings, and this bench
    exists because of a report that the GPU looked idle."""
    r = _bench(levels=(1,), calls_per_level=2)
    gpu = r["levels"][0]["gpu"]
    if gpu.get("available") is False:
        assert "utilization_mean_pct" not in gpu
        assert gpu.get("reason"), "an absence owes its reason"
    else:  # a machine that really has a card
        assert isinstance(gpu.get("utilization_mean_pct"), (int, float, type(None)))


def test_levels_above_the_configured_limit_are_labelled(monkeypatch):
    """They measure queueing, not concurrency. Reporting the plateau unlabelled would
    read as "concurrency stops helping here", which is a different claim."""
    import src.llm.concurrency as C

    monkeypatch.setattr(C, "concurrency_for", lambda _b: 4)
    r = _bench(levels=(2, 4, 8), calls_per_level=2)
    flags = {lv["concurrency"]: lv["beyond_server_limit"] for lv in r["levels"]}
    assert flags == {2: False, 4: False, 8: True}
    assert r["configured_concurrency"] == 4


def test_the_linear_extrapolation_is_named_as_the_assumption_it_restates():
    """It is llm_bench.budget_translation's multiplication, shown for comparison. If it
    ever reads as a measurement the bench has undone its own reason for existing."""
    reading = summarise_levels(
        [
            {"concurrency": 1, "calls_per_hour": 100},
            {"concurrency": 4, "calls_per_hour": 250},
        ],
        server_limit=8,
    )
    assert reading["best_concurrency"] == 4
    assert reading["speedup_over_serial"] == 2.5
    lin = reading["linear_extrapolation"]
    assert lin["at_best_concurrency"] == 400, "1x100 workers=4 -> the assumed 400"
    assert "not as a measurement" in lin["method"]


def test_no_curve_at_all_says_so_instead_of_picking_a_winner():
    reading = summarise_levels(
        [{"concurrency": 1, "calls_per_hour": None}], server_limit=None
    )
    assert reading["best_concurrency"] is None and reading["reason"]


def test_hitting_the_ceiling_points_at_the_restart_that_would_lift_it():
    """A best level AT the limit is not "concurrency stops helping" — it is "we could
    not look higher from here", and the operator is owed the difference."""
    reading = summarise_levels(
        [{"concurrency": 1, "calls_per_hour": 100}, {"concurrency": 4, "calls_per_hour": 380}],
        server_limit=4,
    )
    assert "RESTART" in reading["note"] and "OO_VLLM_CONCURRENCY" in reading["note"]


def test_an_unreachable_backend_reports_no_numbers():
    r = run_throughput_bench(levels=(1,), calls_per_level=1)
    if r.get("available") is not True:  # this sandbox has no model, which is the case
        assert "levels" not in r
        assert r.get("reason")


def test_no_field_name_carries_a_banned_substring():
    """The house convention is stricter than the canonical checker: the per-module
    walkers ban score/ranking/rating/grade as SUBSTRINGS of dict KEYS."""
    banned = ("score", "ranking", "rating", "grade")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                assert not any(b in low for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(_bench(levels=(1, 2), calls_per_level=2))
    walk(run_throughput_selftest())


# --------------------------------------------------------------------------- #
#  wiring
# --------------------------------------------------------------------------- #
def test_the_selftest_passes_and_is_registered_with_the_loop():
    from src.monitoring.recursive_loop import LOOP_SELFTESTS

    assert run_throughput_selftest()["passed"] is True
    names = {n for n, _m, _f in LOOP_SELFTESTS}
    assert "llm-throughput-selftest" in names


def test_the_default_sweep_starts_at_one_so_there_is_a_baseline():
    """Every comparison in the report is against serial; without level 1 there is
    nothing to compare to and speedup_over_serial silently disappears."""
    assert DEFAULT_LEVELS[0] == 1
