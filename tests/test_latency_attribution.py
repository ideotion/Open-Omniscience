"""
Diagnostics round of 2026-09-30, rank 10: a route over the 500 ms bar says WHAT KIND of breach.

306 routes were over the bar across sixteen bundles and 287 of them had a window under 20, so
"which of these is a real slow read" could not be answered from an export: the reservoir mixed
completed requests with refused ones, kept no first call and no timestamp, and the published
lists were cut at 60 routes and 20 breaches.

Everything here is attribution BESIDE the existing number. ``p95_ms`` still counts every request
(a person waited for the refused ones) and no breach is ever excused, so each positive assertion
has its negative space: a refusal-driven breach still breaks the blanket pass, an absent figure is
``None`` and never ``0``, and a distance from an unlock that does not exist is absent rather than
zero.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.monitoring import latency, unlock_marker
from src.monitoring.search_timing import _walk_no_score


@pytest.fixture(autouse=True)
def _reset():
    latency._reset_for_tests()
    yield
    latency._reset_for_tests()


@pytest.fixture
def clock(monkeypatch):
    """A wall clock the test moves by hand: ``clock[0] = 1010.0`` before a ``record``."""
    now = [1000.0]
    monkeypatch.setattr(latency, "_wall", lambda: now[0])
    return now


def _row(route: str) -> dict:
    return {r["route"]: r for r in latency.summary()["routes"]}[route]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Refusals apart from completions                                              #
# --------------------------------------------------------------------------- #


def test_refusals_are_counted_apart_and_still_count_in_the_p95():
    for i in range(10):
        latency.record(i, "GET /api/articles", 200, 100.0)
    for i in range(3):
        latency.record(100 + i, "GET /api/articles", 503, 60000.0)
    row = _row("GET /api/articles")
    assert (row["completed_n"], row["refused_n"], row["error_n"]) == (10, 3, 0)
    assert row["window_n"] == 13
    assert row["p95_completed_ms"] == 100.0
    # A person waited those 60 seconds: the percentile stays honest about it.
    assert row["p95_ms"] == 60000.0


def test_every_status_lands_in_exactly_one_class():
    for i, status in enumerate((200, 304, 404, 423, 429, 503, 500, 502, 504)):
        latency.record(i, "GET /api/x", status, 10.0)
    row = _row("GET /api/x")
    assert (row["completed_n"], row["refused_n"], row["error_n"]) == (3, 3, 3)
    assert row["completed_n"] + row["refused_n"] + row["error_n"] == row["window_n"]


def test_a_route_that_never_completed_has_no_completed_p95_rather_than_a_zero():
    latency.record(1, "GET /api/insights/latest", 503, 60042.0)
    row = _row("GET /api/insights/latest")
    assert row["completed_n"] == 0
    assert row["p95_completed_ms"] is None, "'nothing completed' is not 'the completions were instant'"
    assert row["p95_ms"] == 60042.0


def test_a_refusal_driven_breach_is_attributed_but_never_excused():
    """The 2026-08-02 rule survives the split: a route over the bar only through refusals still
    breaks the blanket pass, because the attribution says what kind of breach it is and does not
    withdraw it."""
    latency.record(1, "GET /api/insights/latest", 503, 60000.0)
    latency.record(2, "GET /api/insights/latest", 503, 60000.0)
    for i in range(30):
        latency.record(i, "GET /api/slow", 200, 900.0)  # a genuinely slow read
    for i in range(25):
        latency.record(i, "GET /api/fast", 200, 20.0)
    bar = latency.summary()["snappy_bar"]
    assert bar["breaching"] == 2
    assert bar["breaching_refusal_or_error_driven"] == 1, "only the refused route"
    assert bar["all_interactive_pass"] is False
    verdicts = {r["route"]: r["verdict"] for r in bar["breaching_routes"]}
    assert verdicts["GET /api/insights/latest"] == "low-n", "the confidence label is unchanged"


def test_an_error_driven_breach_is_attributed_with_the_refusals_not_hidden():
    for i in range(3):
        latency.record(i, "GET /api/boom", 500, 30000.0)
    bar = latency.summary()["snappy_bar"]
    assert bar["breaching"] == 1 and bar["breaching_refusal_or_error_driven"] == 1
    row = _row("GET /api/boom")
    assert (row["completed_n"], row["refused_n"], row["error_n"]) == (0, 0, 3)


# --------------------------------------------------------------------------- #
# The first call                                                               #
# --------------------------------------------------------------------------- #


def test_a_breach_that_is_only_the_first_call_says_so():
    route = "GET /api/articles"
    latency.record(0, route, 200, 5000.0)
    for i in range(4):
        latency.record(i + 1, route, 200, 50.0)
    row = _row(route)
    assert row["first_ms"] == 5000.0 and row["first_status"] == 200
    assert row["first_in_window"] is True
    assert row["p95_ms"] == 5000.0, "the breach is real and stays in p95"
    assert row["p95_without_first_ms"] == 50.0
    bar = latency.summary()["snappy_bar"]
    assert bar["breaching"] == 1
    assert bar["breaching_first_call_only"] == 1
    assert bar["breaching_single_call"] == 0


def test_a_one_call_route_is_a_single_call_not_a_first_call_only_breach():
    """With one sample there is nothing to compare the first call with, so claiming 'only the
    first call' would be a statement about a baseline that does not exist."""
    latency.record(0, "GET /api/articles", 200, 5000.0)
    row = _row("GET /api/articles")
    assert row["p95_without_first_ms"] is None
    bar = latency.summary()["snappy_bar"]
    assert bar["breaching_single_call"] == 1
    assert bar["breaching_first_call_only"] == 0


def test_a_slow_route_stays_slow_without_its_first_call():
    route = "GET /api/slow"
    latency.record(0, route, 200, 900.0)
    for i in range(5):
        latency.record(i + 1, route, 200, 800.0)
    bar = latency.summary()["snappy_bar"]
    assert bar["breaching"] == 1
    assert bar["breaching_first_call_only"] == 0, "dropping the first call does not clear it"


def test_once_the_first_call_has_left_the_window_the_figure_without_it_is_absent():
    route = "GET /api/articles"
    latency.record(0, route, 200, 5000.0)
    for i in range(latency._RES_CAP + 87):
        latency.record(i + 1, route, 200, 50.0)
    row = _row(route)
    assert row["count"] == latency._RES_CAP + 88 and row["window_n"] == latency._RES_CAP
    assert row["first_ms"] == 5000.0, "since process start, like max_ms"
    assert row["first_in_window"] is False
    assert row["p95_without_first_ms"] is None, "computed over a window that no longer holds it"
    assert row["max_ms"] == 5000.0 and row["slowest"]["ms"] == 5000.0


# --------------------------------------------------------------------------- #
# The slowest call, in time                                                    #
# --------------------------------------------------------------------------- #


def test_the_slowest_call_is_kept_with_when_it_ended_and_a_tie_keeps_the_earlier(clock):
    route = "GET /api/articles"
    for t, ms in ((1000.0, 100.0), (1010.0, 900.0), (1020.0, 900.0), (1030.0, 300.0)):
        clock[0] = t
        latency.record(int(t), route, 200, ms)
    row = _row(route)
    assert row["slowest"]["ms"] == 900.0 == row["max_ms"]
    assert row["slowest"]["ended_at"] == _iso(1010.0), "the tie keeps the EARLIER call"
    assert row["first_ms"] == 100.0


def test_the_distance_from_the_unlock_is_signed_and_absent_without_one(clock):
    clock[0] = 1100.0
    latency.record(1, "GET /api/before", 200, 4000.0)
    before = _row("GET /api/before")
    assert before["slowest"]["started_after_unlock_s"] is None, "no unlock yet: absent, never 0"
    block = latency.summary()["unlock"]
    assert block["count"] == 0 and block["last_done_at"] is None and "no unlock" in block["reason"]

    unlock_marker.note_unlock_done(at=1200.0)
    clock[0] = 1210.0  # ended 10 s after the unlock, took 4 s -> began 6 s after it
    latency.record(2, "GET /api/after", 200, 4000.0)
    clock[0] = 1200.5  # ended 0.5 s after the unlock, took 3 s -> began 2.5 s BEFORE it
    latency.record(3, "POST /api/system/unlock", 200, 3000.0)

    assert _row("GET /api/after")["slowest"]["started_after_unlock_s"] == 6.0
    assert _row("POST /api/system/unlock")["slowest"]["started_after_unlock_s"] == -2.5, (
        "the request that performs the unlock begins before it finishes"
    )
    assert _row("GET /api/before")["slowest"]["started_after_unlock_s"] is None, (
        "history is not rewritten when an unlock arrives later"
    )
    block = latency.summary()["unlock"]
    assert block["count"] == 1 and block["last_done_at"] == _iso(1200.0) and block["reason"] is None


def test_the_forensics_unlock_record_stamps_the_unlock_and_stamps_it_first(monkeypatch):
    """``record_unlock_timing`` is where every finished unlock already passes, so the stamp lives
    there and ``api/unlock.py`` stays untouched. It stamps BEFORE writing the sentinel: a sentinel
    that cannot be written is the very condition that log exists to diagnose."""
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "_read_state", lambda: None)
    written: list[dict] = []
    monkeypatch.setattr(forensics, "_write_state", written.append)
    forensics.record_unlock_timing({"phases": [], "synchronous_total_ms": 1.0})
    assert unlock_marker.summary()["count"] == 1 and len(written) == 1
    assert latency.summary()["unlock"]["count"] == 1, "one stamp, read by both instruments"

    def _boom(_state):
        raise OSError("disk full")

    monkeypatch.setattr(forensics, "_write_state", _boom)
    with pytest.raises(OSError):
        forensics.record_unlock_timing({"phases": []})
    assert unlock_marker.summary()["count"] == 2, "stamped before the write that failed"


def test_a_clock_that_fails_costs_the_stamp_never_the_sample(monkeypatch):
    """``_call_facts`` reads the wall clock for a route's first and slowest call. If that read
    raised, the whole sample used to be dropped and a route row with count 0 was left behind."""
    def broken():
        raise OSError("clock unavailable")

    monkeypatch.setattr(latency, "_wall", broken)
    latency.record(1, "GET /api/articles", 200, 750.0)
    row = _row("GET /api/articles")
    assert row["count"] == 1 and row["window_n"] == 1 and row["p95_ms"] == 750.0
    assert row["slowest"] == {"ms": 750.0, "status": 200, "ended_at": None, "started_after_unlock_s": None}
    assert row["first_ms"] == 750.0


# --------------------------------------------------------------------------- #
# The bar itself: a figure AT it is over it                                    #
# --------------------------------------------------------------------------- #


def test_a_route_exactly_at_the_bar_is_over_it_and_not_attributed_away():
    """Both attribution counts compare against the bar with a strict `<`, because the breach test is
    `>=`: a route whose completed requests sit exactly AT the bar is a breach whose completions are
    not under it, so it is not 'only through refusals' and not 'only the first call'."""
    bar = latency._snappy_bar_ms()
    route = "GET /api/at-the-bar"
    latency.record(0, route, 200, bar)  # the first call
    for i in range(4):
        latency.record(i + 1, route, 200, bar)  # ...and the rest, exactly at the bar too
    row = _row(route)
    assert row["p95_ms"] == bar and row["p95_completed_ms"] == bar and row["p95_without_first_ms"] == bar
    snappy = latency.summary()["snappy_bar"]
    assert snappy["breaching"] == 1, "AT the bar is over it"
    assert snappy["breaching_refusal_or_error_driven"] == 0, "its completions are not under the bar"
    assert snappy["breaching_first_call_only"] == 0, "without its first call it is still at the bar"
    # One millisecond under the bar flips the attribution, which is what gives the above its teeth:
    # this route's first call is at the bar (so it breaches) and every other call is under it.
    below = "GET /api/just-under"
    latency.record(0, below, 200, bar)
    for i in range(4):
        latency.record(i + 1, below, 200, bar - 1.0)
    snappy = latency.summary()["snappy_bar"]
    assert snappy["breaching"] == 2, "both routes' p95 is a call AT the bar"
    assert snappy["breaching_first_call_only"] == 1, "only the one whose other calls are under it"


# --------------------------------------------------------------------------- #
# Nothing is cut                                                               #
# --------------------------------------------------------------------------- #


def test_every_route_and_every_breach_is_listed_not_the_first_sixty_or_twenty():
    for n in range(100):
        for i in range(25):
            latency.record(i, f"GET /api/r{n}", 200, 900.0)
    s = latency.summary()
    assert s["routes_total"] == 100 == len(s["routes"])
    bar = s["snappy_bar"]
    assert bar["breaching"] == 100 == len(bar["breaching_routes"])
    assert bar["failing"] == 100 == len(bar["failing_routes"])
    assert bar["interactive_routes"] == 100, "the denominator now reconciles with the list"


def test_the_one_bound_that_stays_is_published_with_what_it_dropped():
    for n in range(latency._ROUTES_CAP):
        latency.record(n, f"GET /scan/{n}", 404, 1.0)
    for n in range(5):
        latency.record(n, f"GET /scan/extra/{n}", 404, 1.0)
    latency.record(99, "GET /scan/0", 404, 1.0)  # a known route still records
    s = latency.summary()
    assert s["routes_total"] == latency._ROUTES_CAP
    assert s["route_keyspace"] == {
        "cap": latency._ROUTES_CAP,
        "routes": latency._ROUTES_CAP,
        "dropped_requests": 5,
    }
    assert _row("GET /scan/0")["count"] == 2


# --------------------------------------------------------------------------- #
# The summary does not hold the lock ``record`` takes                          #
# --------------------------------------------------------------------------- #


def test_the_rows_are_built_after_the_lock_record_takes_is_released(monkeypatch):
    """``record`` runs on the event-loop thread for every response and takes ``_LOCK``, so a
    ``summary`` that builds its rows (three sorts of each window) while holding it stalls the loop for
    as long as the building takes: tens of milliseconds at 300 routes with full windows."""
    for n in range(3):
        latency.record(n, f"GET /api/r{n}", 200, 10.0 + n)
    held: list[bool] = []
    real = latency._route_row

    def spy(key, r, bar_ms):
        held.append(latency._LOCK.locked())
        return real(key, r, bar_ms)

    monkeypatch.setattr(latency, "_route_row", spy)
    assert len(latency.summary()["routes"]) == 3
    assert held == [False, False, False]


def test_a_request_recorded_while_the_rows_are_built_does_not_change_a_row_already_copied(monkeypatch):
    """The copies are all taken under one hold of the lock, so every row describes one moment, and a
    row is built from its COPY: a live deque cannot be iterated while ``record`` appends to it, and
    reading the live record after the lock was released would publish a count the other rows
    were not measured at."""
    latency.record(1, "GET /api/a", 200, 10.0)
    latency.record(2, "GET /api/b", 200, 20.0)
    real = latency._route_row
    injected: list[int] = []

    def spy(key, r, bar_ms):
        # Lands while the first row is being built, i.e. after the copies. Only when the lock is
        # free: ``record`` would wait on it for ever from inside a summary that still held it.
        if not injected and not latency._LOCK.locked():
            injected.append(1)
            latency.record(3, "GET /api/b", 200, 9_000.0)
        return real(key, r, bar_ms)

    monkeypatch.setattr(latency, "_route_row", spy)
    rows = {r["route"]: r for r in latency.summary()["routes"]}
    assert injected == [1], "no request could be recorded while the rows were built"
    assert rows["GET /api/b"]["count"] == 1 and rows["GET /api/b"]["max_ms"] == 20.0
    assert latency._ROUTES["GET /api/b"]["count"] == 2, "the request itself was recorded"
    assert _row("GET /api/b")["count"] == 2, "and the next summary shows it"


# --------------------------------------------------------------------------- #
# Honesty guards                                                               #
# --------------------------------------------------------------------------- #


def test_a_status_that_cannot_be_classified_never_unevens_the_window():
    latency.record(1, "GET /api/x", None, 10.0)  # type: ignore[arg-type]
    assert latency.summary()["routes_total"] == 0, "refused before any state was touched"
    latency.record(2, "GET /api/x", 200, 10.0)
    r = latency._ROUTES["GET /api/x"]
    assert len(r["durations"]) == len(r["kinds"]) == 1


def test_the_summary_carries_no_score_like_key():
    for i in range(30):
        latency.record(i, "GET /api/a", 200 if i % 3 else 503, 40.0 + i)
    _walk_no_score(latency.summary())


def test_the_method_text_says_what_the_new_counts_are_and_that_they_do_not_excuse():
    method = latency.summary()["snappy_bar"]["method"]
    for needle in ("ATTRIBUTED, NEVER EXCUSED", "refused ones included", "423, 429 or 503", "overlap"):
        assert needle in method, needle


def test_the_method_text_does_not_claim_the_refusal_statuses_mean_one_thing():
    """503, 429 and 423 are mostly a locked database, a rate limit and a deadline -- and ALSO what
    the language-model bridge, the custody anchor, the heavy-computation guard and the Wikipedia
    lane answer. A text that said they were only the first group would explain a refusal by the
    wrong cause, so it says `mostly` and names the others."""
    method = latency.summary()["snappy_bar"]["method"]
    assert "mostly" in method and "does not say which one declined" in method
    for other in ("language-model bridge", "custody anchor", "Wikipedia lane"):
        assert other in method, other
