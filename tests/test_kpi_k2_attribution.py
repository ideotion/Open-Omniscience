"""
Diagnostics round of 2026-09-30, rank 10: K2 says what its number is MADE OF.

K2 was red on sixteen of sixteen instances, nearly always on a route with one or two samples, and
the entry could not say whether that was a slow read, a refused request or the first call after an
unlock. These tests pin the method text that now says so -- and, as importantly, that it only SAYS:
the value, the n and the verdict are what the same latency summary gave before (the summary now
lists every route, so on an instance whose old cut at 60 had dropped the worst route the number can
move toward the true worst), and an attributed breach is still a breach. Every figure is read from
the latency summary; none is computed here.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import src.monitoring.latency as latency
from src.monitoring import unlock_marker
from src.monitoring.kpi import _k2_made_of, kpi_snapshot


@pytest.fixture(autouse=True)
def _reset():
    latency._reset_for_tests()
    yield
    latency._reset_for_tests()


def _k2() -> dict:
    return next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K2")


def _snappy(**extra) -> dict:
    return {
        "bar_ms": 500.0,
        "min_n": 20,
        "interactive_routes": 40,
        "breaching": 7,
        "breaching_low_n": 6,
        "breaching_refusal_or_error_driven": 3,
        "breaching_first_call_only": 2,
        "breaching_single_call": 4,
        **extra,
    }


def _worst(**extra) -> dict:
    return {
        "route": "GET /api/articles",
        "p95_ms": 61000.0,
        "window_n": 2,
        "snappy": "low-n",
        "slowest": {
            "ms": 61000.0,
            "status": 200,
            "ended_at": "2026-09-22T08:14:03+00:00",
            "started_after_unlock_s": 11.5,
        },
        **extra,
    }


def _summary(snappy=None, worst=None):
    return lambda: {"snappy_bar": snappy or _snappy(), "routes": [worst or _worst()]}


def test_the_method_names_the_slowest_call_and_where_it_sat_against_the_unlock(monkeypatch):
    monkeypatch.setattr(latency, "summary", _summary())
    method = _k2()["method"]
    assert "its slowest call took 61,000.0 ms (status 200)" in method
    assert "ended 2026-09-22T08:14:03+00:00" in method
    assert "it began 11.5 s after the latest unlock to finish before it ended" in method


def test_the_method_says_how_the_breaches_across_all_routes_divide(monkeypatch):
    monkeypatch.setattr(latency, "summary", _summary())
    method = _k2()["method"]
    assert "7 of 40 interactive routes are over the bar (6 of them on fewer than 20 samples)" in method
    assert "3 only through refused or errored requests" in method
    assert "2 only on their first call" in method
    assert "4 on a single call" in method
    assert "counted by route, and overlapping" in method


def test_none_of_it_changes_the_value_the_n_or_the_verdict(monkeypatch):
    """The attribution is beside K2's number, never instead of it: the same worst route gives the
    same red, with and without the keys that explain it."""
    monkeypatch.setattr(latency, "summary", _summary())
    attributed = _k2()
    legacy_route = {k: v for k, v in _worst().items() if k != "slowest"}
    monkeypatch.setattr(
        latency, "summary",
        lambda: {"snappy_bar": {"bar_ms": 500.0}, "routes": [legacy_route]},
    )
    legacy = _k2()
    assert (attributed["value"], attributed["n"], attributed["verdict"]) == (
        legacy["value"], legacy["n"], legacy["verdict"]
    ) == (61000.0, 2, "red")


def test_a_breach_that_is_only_refusals_is_still_red(monkeypatch):
    """A route whose breach is entirely refused/errored requests is attributed as such and is still
    over the bar: a person waited for those requests."""
    monkeypatch.setattr(
        latency, "summary",
        _summary(
            snappy=_snappy(breaching=1, breaching_low_n=1, breaching_refusal_or_error_driven=1,
                           breaching_first_call_only=0, breaching_single_call=1),
            worst=_worst(p95_ms=30000.0, slowest={"ms": 30000.0, "status": 503,
                                                   "ended_at": "2026-09-22T08:00:00+00:00",
                                                   "started_after_unlock_s": 4.0}),
        ),
    )
    k2 = _k2()
    assert k2["verdict"] == "red" and k2["value"] == 30000.0
    assert "(status 503)" in k2["method"]
    assert "1 only through refused or errored requests" in k2["method"]


def _slowest(d, **extra):
    return {"ms": 9000.0, "status": 200, "ended_at": "t", "started_after_unlock_s": d, **extra}


def test_the_request_that_performs_an_unlock_is_called_the_unlocks_own_and_no_other_is():
    """A negative distance means an unlock finished while the call ran. Only the two requests that
    PERFORM one are that unlock's own request: a status poll in flight across an unlock merely
    overlapped it, and saying otherwise would explain a slow poll by a thing it never did."""
    for route in ("POST /api/system/unlock", "POST /api/system/create-db"):
        call, _ = _k2_made_of(_snappy(), _worst(route=route, slowest=_slowest(-3.2)))
        assert "it began 3.2 s BEFORE an unlock finished while it ran (the unlock's own request)" in call
        assert "-3.2" not in call, "the sign is said in words, not printed as a minus"
    call, _ = _k2_made_of(_snappy(), _worst(route="GET /api/system/startup-status", slowest=_slowest(-3.2)))
    assert "it began 3.2 s BEFORE an unlock finished while it ran" in call
    assert "own request" not in call


def test_the_unlock_routes_are_routes_the_unlock_router_defines():
    """``UNLOCK_ROUTES`` names the two requests that perform an unlock by the key the latency log files
    them under (``METHOD template``), and nothing tied those strings to the router: a route renamed or
    moved would drop the words "(the unlock's own request)" and leave every distance as it was.
    Anchored to the router's own definitions (never the app singleton's route table, which is
    process-global state) and to the wiring's source: the router is included with no prefix, so a
    definition's path IS the template the latency log records."""
    from src.api import unlock as unlock_api

    defined = {f"{m} {r.path}" for r in unlock_api.router.routes for m in r.methods}
    assert defined >= unlock_marker.UNLOCK_ROUTES, sorted(unlock_marker.UNLOCK_ROUTES - defined)
    wiring = (Path(__file__).resolve().parents[1] / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")
    calls = re.findall(r"include_router\(([^)]*)\)", wiring)
    assert calls and all("prefix" not in c for c in calls), "a prefix would change every route's key"


def test_no_unlock_in_this_process_is_unknown_never_zero_seconds():
    call, _ = _k2_made_of(_snappy(), _worst(slowest=_slowest(None)), {"count": 0})
    assert "no unlock has finished in this process" in call
    assert "0 s" not in call and "began 0" not in call


def test_a_call_that_ended_before_an_unlock_that_has_since_finished_does_not_say_none_has():
    """The distance is fixed when the call is recorded and the words are chosen later: with an
    unlock on record now, 'no unlock has finished in this process' would be false."""
    call, _ = _k2_made_of(_snappy(), _worst(slowest=_slowest(None)), {"count": 1})
    assert "it ended before any unlock had finished in this process" in call
    assert "no unlock has finished" not in call


def test_a_call_whose_clock_failed_is_not_said_to_have_ended_before_an_unlock():
    """`_call_facts` returns no end time and no distance when the clock raises. With an unlock on record
    the words would otherwise read "it ended before any unlock had finished", a time nobody measured."""
    slowest = _slowest(None, ended_at=None)
    for unlock in ({"count": 3}, {"count": 0}, None):
        call, _ = _k2_made_of(_snappy(), _worst(slowest=slowest), unlock)
        assert "its end time was not recorded, so its distance from an unlock is unknown" in call, unlock
        assert "before any unlock" not in call and "no unlock has finished" not in call and "None" not in call


def test_a_summary_with_no_unlock_record_claims_nothing_about_unlocks():
    call, _ = _k2_made_of(_snappy(), _worst(slowest=_slowest(None)))
    assert "its distance from an unlock was not recorded" in call
    assert "no unlock has finished" not in call and "before any unlock" not in call


def test_a_figure_in_the_millions_is_printed_whole_not_in_scientific_notation():
    """Two of the sixteen K2 p95s in the 2026-09-30 round were above 10^6 ms: `:g` printed
    2.48079e+06 for them."""
    call, _ = _k2_made_of(_snappy(), _worst(slowest=_slowest(12.0, ms=2480790.0)))
    assert "took 2,480,790.0 ms" in call and "e+" not in call


def test_a_call_with_no_end_stamp_says_nothing_about_when_it_ended():
    call, _ = _k2_made_of(_snappy(), _worst(slowest=_slowest(5.0, ended_at=None)))
    assert "ended" not in call.replace("finish before it ended", "") and "None" not in call


def test_the_real_chain_records_a_slow_call_then_an_unlock_and_the_words_follow_the_unlock():
    """The sequence the second review reproduced: a slow call is recorded with no unlock on
    record, an unlock finishes, and the report is built afterwards. The call's distance is None
    (it was recorded before any unlock), and K2 must not claim that no unlock ever finished."""
    unlock_marker._reset_for_tests()
    try:
        latency.record(1, "GET /api/articles", 200, 61000.0)
        assert _k2()["method"].count("no unlock has finished in this process") == 1
        unlock_marker.note_unlock_done()
        method = _k2()["method"]
        assert "it ended before any unlock had finished in this process" in method
        assert "no unlock has finished" not in method
        assert latency.summary()["unlock"]["count"] == 1
    finally:
        unlock_marker._reset_for_tests()


def test_a_summary_that_predates_the_attribution_gets_no_stray_clause(monkeypatch):
    """Negative space: a route row with no `slowest` and a snappy_bar without the new counts must
    read exactly as K2 read before the round -- no `None`, no `0 of 0`, no dangling semicolon."""
    assert _k2_made_of({"bar_ms": 500.0}, {"route": "GET /x", "p95_ms": 900.0}) == ("", "")
    # ...and a REAL pre-round summary has the breach counts but not the attribution: it yields the
    # first half of the split and nothing invented for the second.
    legacy_bar = {"bar_ms": 500.0, "min_n": 20, "interactive_routes": 79, "breaching": 22,
                  "breaching_low_n": 20}
    assert _k2_made_of(legacy_bar, {"route": "GET /x"}) == (
        "", "22 of 79 interactive routes are over the bar (20 of them on fewer than 20 samples)",
    )
    monkeypatch.setattr(
        latency, "summary",
        lambda: {
            "snappy_bar": {"bar_ms": 500.0},
            "routes": [{"route": "GET /api/articles", "p95_ms": 900.0, "window_n": 25,
                        "snappy": "fail"}],
        },
    )
    method = _k2()["method"]
    assert method.endswith("(GET /api/articles, n=25); measured, per-process reservoir, counts only, no score")
    assert "None" not in method and "interactive routes are over" not in method


def test_a_partial_split_names_only_the_counts_it_has(monkeypatch):
    split = _k2_made_of(
        {"bar_ms": 500.0, "interactive_routes": 10, "breaching": 2, "breaching_single_call": 1},
        {},
    )[1]
    assert split == "2 of 10 interactive routes are over the bar; 1 on a single call (counted by route, and overlapping)"


def test_the_entry_carries_no_score_like_key(monkeypatch):
    monkeypatch.setattr(latency, "summary", _summary())
    k2 = _k2()

    def walk(o):
        if isinstance(o, dict):
            for key, v in o.items():
                assert not any(b in str(key).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(k2)
