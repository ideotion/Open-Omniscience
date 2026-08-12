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
    _ConcurrencyProbe,
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
def test_the_bench_really_runs_its_calls_concurrently():
    """THE LOAD-BEARING ONE: without it a serial bench publishes a plausible curve.

    This asserted ``parallel_wall < serial_wall`` until 2026-08-12, and that proxy was
    unsound in BOTH directions. ``run_concurrent`` is a plain for loop at
    ``max_workers <= 1`` and a ThreadPoolExecutor above it, so the parallel side pays a
    pool-creation cost the serial side never pays — a FIXED noise term against a fixed
    signal, not jitter that shrinks as the work grows.

    MEASURED, so the next session does not re-derive it. Under 8x CPU oversubscription
    (32 spinners on 4 cores) pool creation reached 132 ms against the 120 ms signal, and
    the shipped configuration failed 2/200 with a worst margin of -500 ms. Raising the
    signal is NOT the repair here: a 600 ms floor still failed 1/120, because the stall
    tail is unbounded rather than proportional. And in the other direction it was worse
    than flaky — against a genuinely serial pool both levels take the same time, so the
    comparison is near a coin flip and caught the defect it exists to catch only 29/40.

    So the claim is structural instead: with four workers, four calls really were in
    flight AT ONCE. A stall can delay that moment but cannot make it false. Same
    reasoning the rate assertion below carries one level down — do not re-derive a
    discriminating threshold from timings.
    """
    probe = _ConcurrencyProbe(parties=4)
    run_throughput_bench(
        levels=(4,), calls_per_level=8, client=probe, model="fake", backend_name="vllm"
    )
    assert probe.max_in_flight == 4, (
        f"four workers must put four calls in flight at once, saw {probe.max_in_flight}"
    )
    assert not probe.timed_out, "the pool never assembled"


def test_a_silently_serial_pool_is_detected_rather_than_read_as_merely_slow(monkeypatch):
    """NEGATIVE SPACE: the guard above must FAIL when the pool really is serial.

    Without this, ``max_in_flight == 4`` could be satisfied by an instrument that counts
    something other than genuine overlap, and nothing would say so."""
    from src.llm import concurrency as conc

    real = conc.run_concurrent
    monkeypatch.setattr(
        conc,
        "run_concurrent",
        lambda items, fn, *, max_workers=1: real(items, fn, max_workers=1),
    )
    # A short rendezvous: this tests the DETECTION, not the production timeout, and a
    # serial pool pays that timeout exactly once (it opens the gate on giving up).
    probe = _ConcurrencyProbe(parties=4, timeout=1.0)
    run_throughput_bench(
        levels=(4,), calls_per_level=8, client=probe, model="fake", backend_name="vllm"
    )
    assert probe.max_in_flight == 1
    assert probe.timed_out


def test_the_published_wall_covers_the_calls_it_reports():
    """A LOWER bound, so a scheduling stall can only ever satisfy it, never break it.

    This is what survives of the wall-clock claim: the timer measures the real work
    rather than publishing a fabricated figure."""
    r = _bench(levels=(1, 4), calls_per_level=8)
    by = {lv["concurrency"]: lv for lv in r["levels"]}
    assert by[1]["batch_wall_s"] >= 8 * 0.02 * 0.9
    assert by[4]["batch_wall_s"] >= 2 * 0.02 * 0.9


class _SaturatingClient(_Client):
    """A backend that cannot really serve more than ``lanes`` at once.

    This is the case the whole bench is about: a GPU already saturated at some level,
    where asking for more workers buys nothing. A perfectly-scaling double cannot tell
    a measured rate from an assumed one — both come out the same — so the discriminating
    fixture has to be the one that STOPS scaling."""

    def __init__(self, seconds: float = 0.02, lanes: int = 2) -> None:
        super().__init__(seconds=seconds)
        import threading

        self.lanes = lanes
        self._sem = threading.Semaphore(lanes)

    def generate(self, prompt, **kw):
        with self._sem:
            return super().generate(prompt, **kw)


def test_the_rate_is_measured_not_a_latency_multiplied_by_the_worker_count():
    """The assumption ``llm_bench.budget_translation`` makes is 3600/p50 x workers. On a
    saturated backend that overstates the truth several-fold, which is exactly the shape
    of a report that says "plenty of headroom" beside a GPU sitting at 20%.

    THE LOAD-INDEPENDENT CLAIM IS THE ARITHMETIC ONE, and that ordering is the lesson
    this test carries. Do not re-derive a discriminating threshold from timings; the
    identity is what discriminates.

    HISTORY, so the next session does not re-walk it. This carried a ratio bar
    (``measured < assumed / 2``) as its anti-vacuity companion, calibrated twice: the
    8-worker/16-call shape reached 0.368 in a contention harness and 0.52 in a real
    full-suite run, so the fixture was made HARDER (16 workers, 32 calls, 2 lanes),
    measuring 0.083-0.192 under 8 competing spinners and 0.061-0.157 under 12. It failed
    anyway — 1/12 at 0.522 under 32 — and the reason is structural rather than a matter
    of calibration: ``call_wall_p50_s`` is timed PER CALL and includes the semaphore
    wait, so ``assumed`` and ``measured`` are not independent. Contention inflates p50,
    ``assumed`` falls toward ``measured``, and the ratio drifts UP toward whatever bar is
    set. Two quantities that converge by construction cannot be separated by a threshold,
    so the companion is now (a) a structural cap on the fixture below and (b) a
    timing-free test that the band can reject the assumed formula's answer at all.
    """
    client = _SaturatingClient(seconds=0.02, lanes=2)
    r = run_throughput_bench(
        levels=(16,),
        calls_per_level=32,
        client=client,
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

    # THE FIXTURE MUST REALLY SATURATE, or the identity above has nothing to discriminate.
    # Stated as an UPPER bound derived from the semaphore: a `lanes`-lane backend cannot
    # exceed lanes/seconds however many workers are requested, so contention can only ever
    # satisfy this — and a fixture that quietly stopped saturating (someone raises `lanes`)
    # blows through it. This replaced a `measured < assumed / 2` ratio bar on 2026-08-12.
    #
    # WHY THE RATIO HAD TO GO, measured rather than assumed. `call_wall_p50_s` is timed
    # PER CALL and includes the semaphore wait, so `assumed` and `measured` are not
    # independent: as contention rises the queue inflates p50, `assumed` falls toward
    # `measured`, and the ratio drifts UP toward whatever bar is set. Across 15 runs under
    # 32 competing spinners it ran 0.115-0.238, but a tail run reached 0.522 and breached
    # the 0.5 bar. The two formulas converge by construction, so no bar is safe; the
    # timing-free companion test below is what now proves the band can reject the wrong
    # answer.
    assert lv["concurrency"] >= 4 * client.lanes, (
        "the fixture must request far more workers than it can serve, or it is not the "
        f"saturated case: concurrency={lv['concurrency']}, lanes={client.lanes}"
    )
    cap = client.lanes / client.seconds * 3600
    assert measured <= cap * 1.05, (
        f"{measured}/h exceeds what {client.lanes} lanes can serve ({cap:.0f}/h) — "
        "this fixture is no longer the saturated one"
    )


def test_the_rate_band_rejects_a_rate_computed_the_assumed_way():
    """ANTI-VACUITY for the identity above, with NO timing in it at all.

    The identity only means something if the band it checks can actually reject the wrong
    answer. Both figures here are arithmetic: 32 calls in 0.320 s is 360,000/h, while
    ``3600/p50 x workers`` over a 2-lane backend answers 2,880,000/h. One must land inside
    the band and the other outside, on numbers no scheduler can move."""
    n, wall, p50, workers = 32, 0.320, 0.02, 16
    lo = n / (wall + 0.0005) * 3600 - 0.5
    hi = n / (wall - 0.0005) * 3600 + 0.5

    assert lo <= n / wall * 3600 <= hi, "the batch's own arithmetic must be accepted"
    assumed = (3600.0 / p50) * workers
    assert not (lo <= assumed <= hi), (
        f"the assumed formula's answer ({assumed:.0f}/h) must be rejected by the band "
        f"[{lo:.0f}, {hi:.0f}], or the identity proves nothing"
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
