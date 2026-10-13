"""The Diagnostics build's two modes: records first, then the scans, Quick or Thorough (R124).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT MUST NOT REGRESS, one test each:

1. The records are read BEFORE the exclusive window is taken, so collection keeps running for them;
   the window is open for the scans and only for them, and it is closed again when the last scan
   ends or the build is stopped.
2. Quick spends ONE budget on the scans: a scan starts only while the floor is left, gets the
   smaller of its own deadline and the time left, and a scan that never starts is NAMED
   (``skipped-budget``, its estimate, the reason) -- in the member entry, in the archive and in
   the manifest's ``scans`` block -- and makes ``complete_profile`` False.
3. Thorough has no shared budget: every scan runs under its own deadline, as before.
4. Nothing a mode does is silent: a machine refusal still wins over a budget skip, a cut scan says
   the budget cut it, an unrecognised mode is Thorough (never a smaller build than asked for).
"""

from __future__ import annotations

import contextlib
import io
import json
import zipfile

import pytest

from src.api import diagnostics_plan as plan
from src.api.diagnostics import bundle as B

# Four scans with estimates that sort differently from the order they are listed in, and two records.
SCANS = {"s-slow.json": 200.0, "s-fast.json": 20.0, "s-mid.json": 60.0, "s-tiny.json": 5.0}


@pytest.fixture(autouse=True)
def _small_table(monkeypatch):
    monkeypatch.setattr(plan, "SCAN_EST_S", dict(SCANS))
    monkeypatch.setattr(plan, "SCAN_BUDGET_S", 100.0)
    monkeypatch.setattr(plan, "SCAN_FLOOR_S", 30.0)
    monkeypatch.setattr(B, "ram_declined_reason", lambda *a, **k: None)


class _Clock:
    """The build's clock, advanced by the members (a scan 'takes' what it is told to)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Window:
    """A stand-in for the exclusive window: records when it is open, yields the claim."""

    def __init__(self) -> None:
        self.open = False
        self.opened = 0
        self.closed = 0

    @contextlib.contextmanager
    def __call__(self):
        self.open = True
        self.opened += 1
        try:
            yield {"held": True, "paused_collection": True, "nested": False}
        finally:
            self.open = False
            self.closed += 1


def _build(members, **kw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = B._write_all_diagnostics_zip(members, z, **kw)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        files = {n: z.read(n) for n in z.namelist()}
    return results, json.loads(files["manifest.json"]), set(files), files.__getitem__


def _members(clock, window, seen, *, costs=None):
    """Two records and four scans, listed in a mixed order; each scan advances the clock."""
    costs = costs or {}

    def rec(name):
        def run():
            seen.append((name, window.open))
            return {"n": name}
        return run

    def scan(name):
        def run():
            seen.append((name, window.open))
            clock.now += costs.get(name, 10.0)
            return {"n": name}
        return run

    return [
        ("r-one.json", rec("r-one.json")),
        ("s-slow.json", scan("s-slow.json")),
        ("s-fast.json", scan("s-fast.json")),
        ("r-two.json", rec("r-two.json")),
        ("s-mid.json", scan("s-mid.json")),
        ("s-tiny.json", scan("s-tiny.json")),
    ]


# ---- the pure plan ------------------------------------------------------------------------------
@pytest.mark.parametrize("given", ["quick", "Quick", " QUICK ", "thorough", "Thorough"])
def test_a_recognised_mode_resolves_to_itself(given):
    assert plan.resolve_mode(given) == given.strip().lower()


@pytest.mark.parametrize("given", ["", "light", "quik", "fast", None, 3, object(), b"quick"])
def test_anything_unrecognised_is_thorough_never_a_smaller_build(given):
    assert plan.resolve_mode(given) == "thorough"


def test_records_keep_their_order_and_scans_go_shortest_first_with_ties_in_list_order(monkeypatch):
    monkeypatch.setattr(plan, "SCAN_EST_S", {"a.json": 30.0, "b.json": 10.0, "c.json": 30.0, "d.json": 10.0})
    members = [(n, None) for n in ("r1", "a.json", "b.json", "r2", "c.json", "d.json", "r3")]
    records, scans = plan.split_members(members)
    assert [m[0] for m in records] == ["r1", "r2", "r3"]
    assert [m[0] for m in scans] == ["b.json", "d.json", "a.json", "c.json"]


def test_a_scan_that_states_no_estimate_counts_as_the_longest_a_scan_was_ever_allowed(monkeypatch):
    monkeypatch.setattr(plan, "SCAN_EST_S", {"known.json": 20.0})
    assert plan.scan_est_s("unknown.json") == plan.DEFAULT_SCAN_S == 300.0
    assert plan.is_scan("known.json") and not plan.is_scan("unknown.json")


@pytest.mark.parametrize(
    ("cap", "elapsed", "budget", "expected"),
    [
        (300.0, 0.0, None, (300.0, False)),        # Thorough: no budget, the scan's own cap
        (300.0, 5000.0, None, (300.0, False)),     # ... however long the scans have taken
        (300.0, 0.0, 600.0, (300.0, False)),       # plenty left: its own cap
        (300.0, 300.0, 600.0, (300.0, False)),     # exactly the cap left: the cap, not a cut
        (300.0, 301.0, 600.0, (299.0, True)),      # less than the cap left: the time left, a cut
        (300.0, 570.0, 600.0, (30.0, True)),       # exactly the floor left: runs, with the floor
        (300.0, 570.5, 600.0, (None, False)),      # under the floor: does not start
        (300.0, 700.0, 600.0, (None, False)),      # already over: does not start
    ],
)
def test_the_deadline_of_a_scan_is_the_smaller_of_its_cap_and_the_time_left(cap, elapsed, budget, expected, monkeypatch):
    monkeypatch.setattr(plan, "SCAN_FLOOR_S", 30.0)
    assert plan.scan_deadline_s(cap, elapsed, budget) == expected


def test_the_shipped_table_names_the_sixteen_scans_and_every_one_is_a_real_member():
    # The shipped table, not the small one the other tests install.
    import importlib

    fresh = importlib.reload(plan)
    try:
        assert len(fresh.SCAN_EST_S) == 16
        names = {n for n, _ in B._all_diagnostics_members(None)}
        assert set(fresh.SCAN_EST_S) <= names, sorted(set(fresh.SCAN_EST_S) - names)
        assert all(0 < v <= fresh.DEFAULT_SCAN_S for v in fresh.SCAN_EST_S.values())
        assert fresh.SCAN_BUDGET_S == 600.0 and fresh.SCAN_FLOOR_S == 30.0
        # The three the plan names as costing their full deadline (or 167 s) where they ran.
        assert fresh.SCAN_EST_S["benchmark.json"] == 300.0
        assert fresh.SCAN_EST_S["source-audit.json"] == 300.0
        assert fresh.SCAN_EST_S["keyword-log-digest.json"] == 167.0
    finally:
        importlib.reload(plan)


# ---- the writer ---------------------------------------------------------------------------------
def test_the_records_run_before_the_window_and_the_scans_inside_it(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    results, man, _, _ = _build(_members(clock, window, seen), mode="thorough", scan_window=window)
    assert [n for n, _ in seen] == [
        "r-one.json", "r-two.json", "s-tiny.json", "s-fast.json", "s-mid.json", "s-slow.json",
    ]
    assert dict(seen) == {
        "r-one.json": False, "r-two.json": False,
        "s-tiny.json": True, "s-fast.json": True, "s-mid.json": True, "s-slow.json": True,
    }
    assert window.opened == 1 and window.closed == 1 and window.open is False
    assert [r["kind"] for r in results] == ["record"] * 2 + ["scan"] * 4
    assert man["run"]["exclusive"]["held"] is True
    assert man["run"]["phases"]["scans"]["members"] == 4
    assert man["run"]["phases"]["records"]["members"] == 2


def test_the_window_closes_before_the_manifest_is_made(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    state = {}
    real = B._all_diagnostics_manifest

    def spy(*a, **k):
        state["open_when_manifest_made"] = window.open
        return real(*a, **k)

    monkeypatch.setattr(B, "_all_diagnostics_manifest", spy)
    _build(_members(clock, window, seen), mode="quick", scan_window=window)
    assert state["open_when_manifest_made"] is False


def test_a_build_with_no_scan_never_takes_the_window():
    window = _Window()
    _, man, _, _ = _build([("r.json", lambda: {})], mode="quick", scan_window=window)
    assert window.opened == 0
    assert man["scans"]["planned"] == [] and man["scans"]["skipped"] == []
    assert man["run"]["exclusive"]["held"] is False  # said, not assumed
    assert man["profile"]["complete_profile"] is True


def test_a_caller_that_holds_the_machine_gets_one_window_over_everything_as_before(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    held = {"held": True, "paused_collection": False, "nested": False}
    _, man, _, _ = _build(_members(clock, window, seen), mode="thorough", exclusive=held, scan_window=window)
    assert window.opened == 0, "the writer must not open a second window inside the caller's"
    assert man["run"]["exclusive"] == held
    assert "whole build" in man["run"]["phases"]["records"]["note"]


def test_stopping_between_scans_closes_the_window_at_once(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return len(seen) >= 3  # after the two records and the first scan

    results, _, _, _ = _build(_members(clock, window, seen), mode="quick", scan_window=window, should_stop=stop)
    assert [n for n, _ in seen] == ["r-one.json", "r-two.json", "s-tiny.json"]
    assert window.opened == 1 and window.closed == 1 and window.open is False
    assert len(results) == 3


# ---- Quick --------------------------------------------------------------------------------------
def test_quick_skips_the_scans_the_budget_cannot_reach_and_names_each(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    # tiny 5 s est but costs 40, fast costs 40: 80 of 100 spent, 20 left < the 30 s floor.
    members = _members(clock, window, seen, costs={"s-tiny.json": 40.0, "s-fast.json": 40.0})
    results, man, names, read = _build(members, mode="quick", scan_window=window)
    by = {r["file"]: r for r in results}
    assert by["s-tiny.json"]["outcome"] == "ok" and by["s-fast.json"]["outcome"] == "ok"
    for skipped in ("s-mid.json", "s-slow.json"):
        e = by[skipped]
        assert e["outcome"] == "skipped-budget" and e["ok"] is False and e["bytes"] == 0
        assert "budget of 100 s" in e["skipped_reason"] and "Thorough" in e["skipped_reason"]
        assert skipped not in {n for n, _ in seen}, "a skipped scan must never run"
        assert skipped + ".skipped-budget.txt" in names and skipped not in names
        assert b"NOT collected" in read(skipped + ".skipped-budget.txt")
    assert man["mode"] == "quick" and man["scan_budget_s"] == 100.0
    scans = man["scans"]
    assert scans["planned"] == [
        {"file": "s-tiny.json", "est_s": 5.0}, {"file": "s-fast.json", "est_s": 20.0},
        {"file": "s-mid.json", "est_s": 60.0}, {"file": "s-slow.json", "est_s": 200.0},
    ]
    assert scans["ran"] == ["s-tiny.json", "s-fast.json"]
    assert [s["file"] for s in scans["skipped"]] == ["s-mid.json", "s-slow.json"]
    assert scans["skipped"][1]["est_s"] == 200.0 and scans["skipped"][1]["reason"]


def test_a_quick_build_is_never_a_complete_profile_and_says_why(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    members = _members(clock, window, seen, costs={"s-tiny.json": 60.0, "s-fast.json": 40.0})
    _, man, _, _ = _build(members, mode="quick", scan_window=window)
    prof = man["profile"]
    assert prof["complete_profile"] is False
    assert prof["declined"] == [], "nothing was declined: the budget is not a decline"
    assert "s-mid.json" in prof["note"] and "Thorough" in prof["note"] and "QUICK" in prof["note"]


def test_a_quick_build_whose_scans_all_fit_is_complete(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    _, man, _, _ = _build(_members(clock, window, seen), mode="quick", scan_window=window)
    assert man["profile"]["complete_profile"] is True
    assert man["scans"]["skipped"] == [] and len(man["scans"]["ran"]) == 4


def test_the_budget_counts_from_the_window_not_from_the_records(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)

    def slow_record():
        clock.now += 5000.0  # an hour-long record phase must not eat the scans' budget
        return {}

    members = [("r-slow.json", slow_record), *_members(clock, window, seen)[1:]]
    _, man, _, _ = _build(members, mode="quick", scan_window=window)
    assert man["scans"]["skipped"] == []


def test_a_scan_the_budget_cuts_gets_the_time_left_and_says_the_budget_set_it(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    seen: list[float] = []

    def nondb_bounded(fn, budget_s):
        seen.append(budget_s)
        clock.now += 10.0
        return fn()

    monkeypatch.setattr(B, "_run_nondb_member_bounded", nondb_bounded)
    monkeypatch.setattr(B, "_all_diag_nondb_member_deadline_s", lambda: 300.0)
    members = [("s-tiny.json", lambda: {}), ("s-fast.json", lambda: {})]
    results, _, _, _ = _build(members, mode="quick", scan_window=window)
    # 100 s budget, its own cap 300 s: both are cut by the budget, with 100 then 90 s.
    assert seen == [100.0, 90.0]
    assert [r["deadline_s"] for r in results] == [100.0, 90.0]
    assert all(r["budget_cut"] is True for r in results)


def test_thorough_gives_every_scan_its_own_deadline_and_no_budget(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    seen: list[float] = []

    def nondb_bounded(fn, budget_s):
        seen.append(budget_s)
        clock.now += 400.0  # far past what Quick would allow
        return fn()

    monkeypatch.setattr(B, "_run_nondb_member_bounded", nondb_bounded)
    monkeypatch.setattr(B, "_all_diag_nondb_member_deadline_s", lambda: 300.0)
    members = [("s-tiny.json", lambda: {}), ("s-fast.json", lambda: {}), ("s-mid.json", lambda: {})]
    results, man, _, _ = _build(members, mode="thorough", scan_window=window)
    assert seen == [300.0, 300.0, 300.0]
    assert all(r["outcome"] == "ok" and "budget_cut" not in r for r in results)
    assert man["mode"] == "thorough" and man["scan_budget_s"] is None
    assert man["scans"]["skipped"] == [] and man["scans"]["scan_budget_s"] is None
    assert man["scans"]["cut_by_budget"] == [], "Thorough has no budget to cut by"
    assert man["profile"]["complete_profile"] is True


def test_a_scan_over_the_database_gets_the_smaller_deadline_too(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    got: list[float] = []

    @contextlib.contextmanager
    def deadline(db, seconds):
        got.append(seconds)
        yield

    monkeypatch.setattr(B, "statement_deadline", deadline)
    monkeypatch.setattr(B, "deadline_expired", lambda db: True)  # cut by the deadline it was given
    monkeypatch.setattr(B, "_all_diag_db_member_deadline_s", lambda: 300.0)
    db = object()

    def make():
        def run():
            clock.now += 25.0
            return {"db": db is not None}
        return run

    results, man, names, _ = _build([("s-tiny.json", make()), ("s-fast.json", make())], mode="quick", scan_window=window, db=db)
    assert got[:2] == [100.0, 75.0]  # (a later call is the manifest's own corpus counters)
    assert [r["outcome"] for r in results] == ["partial-deadline", "partial-deadline"]
    assert [r.get("budget_cut") for r in results] == [True, True]
    assert "s-tiny.json" in names, "a cut scan keeps what it gathered"
    # ``ran`` counts both; the budget's effect on them is its own list, so a reader sees it without opening each entry.
    assert man["scans"]["cut_by_budget"] == ["s-tiny.json", "s-fast.json"]
    assert man["scans"]["partial"] == ["s-tiny.json", "s-fast.json"]


def test_a_non_database_scan_abandoned_at_the_budget_names_the_budget_in_its_marker(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    monkeypatch.setattr(B, "_run_nondb_member_bounded", lambda fn, budget: B._ALL_DIAG_DEADLINE_SENTINEL)
    monkeypatch.setattr(B, "_all_diag_nondb_member_deadline_s", lambda: 300.0)
    results, _, names, read = _build([("s-tiny.json", lambda: {})], mode="quick", scan_window=window)
    assert results[0]["outcome"] == "skipped-deadline" and results[0]["budget_cut"] is True
    text = read("s-tiny.json.skipped-deadline.txt").decode()
    assert "100s" in text and "Quick scan budget" in text
    # the thread that was reading it is not stopped (a thread cannot be): the marker and the entry both say so
    assert "can still be running" in text and results[0]["abandoned_running"] is True


def test_a_scan_that_finished_with_less_than_its_own_deadline_left_is_not_listed_as_cut_by_the_budget(monkeypatch):
    """``budget_cut`` on an entry says the budget SET the deadline; ``cut_by_budget`` lists the scans the budget STOPPED."""
    rows = [
        {"file": "s-tiny.json", "outcome": "partial-deadline", "budget_cut": True},   # stopped with what it had
        {"file": "s-fast.json", "outcome": "skipped-deadline", "budget_cut": True},   # stopped with nothing
        {"file": "s-mid.json", "outcome": "ok", "budget_cut": True, "wall_s": 3.0, "deadline_s": 40.0},  # finished
        {"file": "s-slow.json", "outcome": "partial-deadline"},                       # its own 300 s, not the budget's
    ]
    block = plan.scans_block(rows, mode="quick", budget_s=100.0)
    assert block["cut_by_budget"] == ["s-tiny.json", "s-fast.json"]
    assert block["partial"] == ["s-tiny.json", "s-slow.json"] and "s-mid.json" in block["ran"]


def test_a_scan_that_finishes_inside_a_shortened_deadline_keeps_the_note_on_its_entry_and_is_not_listed(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    monkeypatch.setattr(B, "_all_diag_nondb_member_deadline_s", lambda: 300.0)
    members = [("s-tiny.json", lambda: (clock.__setattr__("now", clock.now + 70.0), {})[1]), ("s-fast.json", lambda: {})]
    results, man, _, _ = _build(members, mode="quick", scan_window=window)
    by = {r["file"]: r for r in results}
    # 100 s budget, 70 s spent by the first: the second ran under the 30 s left (the budget set it) and finished at once
    assert by["s-fast.json"]["outcome"] == "ok" and by["s-fast.json"]["budget_cut"] is True and by["s-fast.json"]["deadline_s"] == 30.0
    assert man["scans"]["cut_by_budget"] == [] and "s-fast.json" in man["scans"]["ran"]


def test_a_record_member_abandoned_at_its_deadline_says_so_in_the_manifest_not_only_in_the_marker(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    monkeypatch.setattr(B, "_run_nondb_member_bounded", lambda fn, budget: B._ALL_DIAG_DEADLINE_SENTINEL)
    monkeypatch.setattr(B, "_all_diag_nondb_member_deadline_s", lambda: 300.0)
    results, _, _, read = _build([("r-one.json", lambda: {})], mode="quick", scan_window=window)
    assert results[0]["kind"] == "record" and results[0]["outcome"] == "skipped-deadline"
    assert "can still be running" in read("r-one.json.skipped-deadline.txt").decode()
    assert results[0]["abandoned_running"] is True


def test_the_runs_length_is_two_readings_of_the_monotonic_clock_not_two_wall_stamps(monkeypatch):
    """A wall clock stepped back an hour during the build made the run's ``total_wall_s`` negative (members and scans were
    already measured on the monotonic clock)."""
    import time

    clock = _Clock()
    monkeypatch.setattr(B, "_mono", clock)
    wall = {"now": 1_800_000_000.0}

    def stepping_wall() -> float:
        wall["now"] -= 3600.0  # every reading is an hour earlier than the one before
        return wall["now"]

    monkeypatch.setattr(time, "time", stepping_wall)
    results, man, _, _ = _build([("r-one.json", lambda: (clock.__setattr__("now", clock.now + 12.5), {})[1])], mode="thorough")
    assert man["run"]["total_wall_s"] == 12.5
    assert results[0]["wall_s"] == 12.5


def _db_scan_raising(clock, seconds, exc):
    def run():
        clock.now += seconds
        raise exc
    return run


@pytest.mark.parametrize("mode, says", [("quick", True), ("thorough", False)])
def test_a_database_scan_stopped_at_the_budget_says_the_budget_set_its_time(monkeypatch, mode, says):
    """The deadline marker of a scan the statement deadline stopped names the budget as the source of its time
    when the budget, not the scan's own deadline, set it; a Thorough build never says so."""
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)

    @contextlib.contextmanager
    def deadline(db, seconds):
        yield

    monkeypatch.setattr(B, "statement_deadline", deadline)
    monkeypatch.setattr(B, "_all_diag_db_member_deadline_s", lambda: 300.0)
    stop = B.StatementTimeout("read exceeded its deadline")
    results, _, names, read = _build(
        [("s-tiny.json", _db_scan_raising(clock, 10.0, stop))], mode=mode, scan_window=window, db=object()
    )
    assert results[0]["outcome"] == "skipped-deadline"
    text = read("s-tiny.json.skipped-deadline.txt").decode()
    assert "read exceeded its deadline" in text
    assert ("Quick scan budget" in text) is says
    if says:
        assert "the 100 s deadline" in text
    assert "abandoned_running" not in results[0], "a statement deadline stops the read itself: nothing was left running"


def test_a_scan_that_chained_the_timeout_into_a_503_gets_the_same_budget_note(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)

    @contextlib.contextmanager
    def deadline(db, seconds):
        yield

    monkeypatch.setattr(B, "statement_deadline", deadline)
    monkeypatch.setattr(B, "_all_diag_db_member_deadline_s", lambda: 300.0)

    def run():
        clock.now += 5.0
        try:
            raise B.StatementTimeout("read exceeded its deadline")
        except B.StatementTimeout as cause:
            raise B.HTTPException(status_code=503, detail="deadline") from cause

    results, _, _, read = _build([("s-tiny.json", run)], mode="quick", scan_window=window, db=object())
    assert results[0]["outcome"] == "skipped-deadline"
    assert "Quick scan budget" in read("s-tiny.json.skipped-deadline.txt").decode()


def test_a_refusal_by_the_machine_is_reported_as_the_machine_s_even_when_the_budget_is_spent(monkeypatch):
    clock, window = _Clock(), _Window()
    monkeypatch.setattr(B, "_mono", clock)
    monkeypatch.setattr(
        B, "ram_declined_reason",
        lambda name, **k: "this machine cannot hold it" if name == "s-slow.json" else None,
    )
    members = [("s-fast.json", lambda: (clock.__setattr__("now", clock.now + 95.0), {})[1]), ("s-slow.json", lambda: {})]
    results, man, names, _ = _build(members, mode="quick", scan_window=window)
    by = {r["file"]: r for r in results}
    assert by["s-slow.json"]["outcome"] == "declined-ram", "the machine's refusal is true on any run"
    assert "s-slow.json.declined.txt" in names and "s-slow.json.skipped-budget.txt" not in names
    assert man["scans"]["declined"] == ["s-slow.json"] and man["scans"]["skipped"] == []


def test_a_scan_that_reaches_the_floor_runs(monkeypatch):
    clock, window, seen = _Clock(), _Window(), []
    monkeypatch.setattr(B, "_mono", clock)
    # 70 s spent by the first, so exactly the 30 s floor is left for the second.
    members = _members(clock, window, seen, costs={"s-tiny.json": 70.0})
    results, _, _, _ = _build(members, mode="quick", scan_window=window)
    by = {r["file"]: r for r in results}
    assert by["s-fast.json"]["outcome"] == "ok" and by["s-fast.json"]["deadline_s"] == 30.0
    assert by["s-mid.json"]["outcome"] == "skipped-budget"


# ---- the callers --------------------------------------------------------------------------------
def test_the_job_route_defaults_to_quick_and_never_stores_the_choice(monkeypatch):
    import inspect

    sig = inspect.signature(B.all_diagnostics_job_start)
    assert sig.parameters["mode"].default.default == "quick"
    started: list[dict] = []
    monkeypatch.setattr(B._ALL_DIAG_JOB, "start", lambda **kw: started.append(kw) or {"state": "running"})
    for given, want in (("quick", "quick"), ("thorough", "thorough"), ("garbage", "thorough")):
        B.all_diagnostics_job_start(profile="full", mode=given)
        assert started[-1] == {"profile": "full", "mode": want}


def test_the_worker_and_the_build_default_to_every_scan_so_a_release_run_gets_a_whole_bundle():
    import inspect

    assert inspect.signature(B._all_diagnostics_worker).parameters["mode"].default == "thorough"
    assert inspect.signature(B._all_diagnostics_build).parameters["mode"].default == "thorough"
    assert inspect.signature(B._write_all_diagnostics_zip).parameters["mode"].default == "thorough"


def test_the_run_record_carries_the_mode(tmp_path, monkeypatch):
    from src.monitoring import diagnostics_runs as runs

    runs.reset_for_tests()
    monkeypatch.setattr(runs, "_path", lambda: tmp_path / "runs.jsonl")
    runs.begin_run("oo-all-diagnostics-x.zip", profile="full", mode="quick")
    member = runs.diagnostics_member()
    assert member["runs"][0]["mode"] == "quick"
    runs.reset_for_tests()


def test_the_release_run_reads_the_mode_and_the_skipped_scans_out_of_an_archive(tmp_path):
    from src.monitoring import release_run as rr

    path = tmp_path / "b.zip"
    manifest = {
        "mode": "quick",
        "members": [
            {"file": "a.json", "outcome": "ok", "ok": True},
            {"file": "s-mid.json", "outcome": "skipped-budget", "ok": False},
        ],
        "profile": {"name": "full", "complete_profile": False, "declined": []},
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("a.json", "{}")
        z.writestr("s-mid.json.skipped-budget.txt", "x")
    out = rr._read_bundle_archive(str(path))
    assert out["mode"] == "quick"
    assert out["skipped_budget_members"] == ["s-mid.json"]
    assert out["complete_profile"] is False
    assert ".skipped-budget.txt" in rr._MARKER_SUFFIXES
