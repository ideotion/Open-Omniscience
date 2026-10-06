"""The memory tier is on the record of every session, with the moment it was decided
(2026-10-06 field diagnostics, the release-candidate thread).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THE 17 BUNDLES COULD NOT SAY. The in-memory keyword rollup runs on every tier but
``small``, and nobody could read why it was off on seven of the fifteen field machines: the
tier reached a report only on a pass-end summary line (three of seventeen bundles kept one),
and the budget behind it is resolved ONCE per process, from the RAM total read at that
instant. On a virtual machine whose memory is ballooned that total moves afterwards -- one
instance's one pass summary said ``small`` while its own records of the RAM total read 4,961,
5,921 and 4,600 MiB, and another machine's killed process read 6,759.9 to 6,907.7 MiB where
its retry read 4,349 MiB.

So the reading the budget was resolved from (tier, RAM total, cores, whether the tier leaves
the rollup on, and WHEN) now rides every boot record, the session's high-water header (read at
the next boot as the previous session's) and the crash report; the soak window carries it beside
the tier the machine would resolve to now. What these tests hold, mostly as negative space: the
budget is still resolved ONCE (a reading that re-resolved would change the pool under a running
app), an absent record stays absent (nothing is invented for an older build), a reading that
cannot be taken says so and never breaks a boot, and a difference between the two tiers is
shown as a fact and never as a verdict.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics import rollup_serve
from src.config import memory_budget as mb
from src.database.models import Base
from src.monitoring import chronology as ch
from src.monitoring import forensics, session_hwm
from src.monitoring import session_history as sh
from src.monitoring import soak_window as sw

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_700_000_000.0
_UNCAPPED = {"allocator": "glibc 2.39", "arena_cap": None, "effective": False,
             "source": "the environment the process started with",
             "note": "MALLOC_ARENA_MAX was not set"}


def _total(monkeypatch, mib: float | None) -> None:
    """The machine reads ``mib`` of RAM from now on (None: psutil cannot say)."""
    monkeypatch.setattr(mb, "total_ram_mb", lambda: mib)


@pytest.fixture
def fresh_budget(monkeypatch):
    """A process whose budget has not resolved yet, and is cleared again afterwards so no
    test leaves its tier behind for the next one (the reset runs before monkeypatch undoes
    the injected reader, so nothing re-resolves from it)."""
    mb.reset_for_tests()
    yield
    mb.reset_for_tests()


# --------------------------------------------------------------------------- #
#  The reading, and the fact that it never re-resolves the budget
# --------------------------------------------------------------------------- #
def test_the_reading_is_what_the_budget_was_resolved_from(monkeypatch, fresh_budget):
    """MUTATION TARGET. Tier, total, nominal size and the rollup default are the CACHED
    budget's own, so they cannot disagree with the budget the process runs on; the moment is
    the resolve's, an ISO UTC stamp."""
    _total(monkeypatch, 4093.8)  # a nominal 4 GiB machine: the 3% tolerance puts it on medium
    got = mb.resolved_reading()
    b = mb.budget()
    assert got["tier"] == b["tier"] == "medium"
    assert got["total_ram_mb"] == b["total_ram_mb"] == 4093.8
    assert got["nominal_ram_mb"] == b["nominal_ram_mb"] == 4096.0
    assert got["columnar_serve_default"] is True is b["columnar_serve_default"]
    assert got["cores"] is None or (isinstance(got["cores"], int) and got["cores"] >= 1)
    stamp = datetime.fromisoformat(got["resolved_at"].replace("Z", "+00:00"))
    assert stamp.tzinfo is not None and abs(time.time() - stamp.timestamp()) < 60


def test_the_cores_are_the_ones_the_machine_reported_and_unreadable_ones_are_not_made_up(monkeypatch, fresh_budget):
    """MUTATION TARGET. ``cores`` is the logical CPU count at the resolve: a count the
    platform cannot give is None, never 1 (one core is a finding, not an absence)."""
    _total(monkeypatch, 5000.0)
    monkeypatch.setattr(mb.os, "cpu_count", lambda: 6)
    assert mb.resolved_reading()["cores"] == 6
    mb.reset_for_tests()
    monkeypatch.setattr(mb.os, "cpu_count", lambda: None)
    assert mb.resolved_reading()["cores"] is None
    mb.reset_for_tests()

    def refuse() -> int:
        raise NotImplementedError

    monkeypatch.setattr(mb.os, "cpu_count", refuse)
    assert mb.resolved_reading()["cores"] is None


def test_a_machine_below_the_floor_reads_small_and_says_the_rollup_is_off_by_default(monkeypatch, fresh_budget):
    _total(monkeypatch, 3500.0)
    got = mb.resolved_reading()
    assert got["tier"] == "small" and got["columnar_serve_default"] is False
    assert got["nominal_ram_mb"] == 3500.0, "a genuinely smaller machine is never rounded up"


def test_an_unmeasured_machine_is_not_a_small_one(monkeypatch, fresh_budget):
    """The module's own rule, carried onto the record: RAM that could not be read is
    ``unmeasured`` with no total, and it keeps the shipped values (the rollup stays on)."""
    _total(monkeypatch, None)
    got = mb.resolved_reading()
    assert got["tier"] == "unmeasured" and got["total_ram_mb"] is None and got["nominal_ram_mb"] is None
    assert got["columnar_serve_default"] is True
    now = mb.reading_vs_now()
    assert now["now"]["tier"] == "unmeasured" and now["tier_differs"] is False


def test_the_moment_is_the_first_resolve_not_the_moment_of_each_look(monkeypatch, fresh_budget):
    """MUTATION TARGET. A stamp taken at every call would say the budget was decided just
    now, which is the one thing a reader of a crashed session cannot afford to believe."""
    _total(monkeypatch, 6000.0)
    clock = iter(["2026-10-06T07:15:55Z", "2026-10-06T21:15:11Z", "2026-10-07T00:00:00Z"])
    monkeypatch.setattr(mb, "_now_iso", lambda: next(clock))
    first = mb.resolved_reading()
    assert first["resolved_at"] == "2026-10-06T07:15:55Z"
    assert mb.resolved_reading()["resolved_at"] == "2026-10-06T07:15:55Z"
    mb.budget()
    assert mb.resolved_reading() == first


def test_looking_never_resolves_the_budget_again(monkeypatch, fresh_budget):
    """MUTATION TARGET. A budget that resolved again on a look would move the pool size, the
    page caches and DuckDB's limit under a running app: the reading is a record of a decision,
    and the decision is made once per process."""
    calls = []
    real = mb.resolve
    monkeypatch.setattr(mb, "resolve", lambda: calls.append(1) or real())
    _total(monkeypatch, 5000.0)
    mb.budget()
    for _ in range(3):
        mb.resolved_reading()
        mb.reading_vs_now()
        mb.budget()
    assert len(calls) == 1


def test_two_threads_asking_at_once_resolve_it_once(monkeypatch, fresh_budget):
    """MUTATION TARGET. The lock is defensive (today the budget resolves once, on the importing
    thread, before another thread exists), but a later caller could ask from another thread, and
    two resolves would leave a cache from one reading and a stamp from the other."""
    _total(monkeypatch, 5000.0)
    calls: list[int] = []
    real = mb.resolve
    gate = threading.Event()

    def slow() -> dict:
        calls.append(1)
        gate.wait(5)
        return real()

    monkeypatch.setattr(mb, "resolve", slow)
    seen: list[dict] = []
    threads = [threading.Thread(target=lambda: seen.append(mb.resolved_reading())) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1 and len(seen) == 4
    assert all(r == seen[0] for r in seen), "one reading, whichever thread asked"


def test_a_thread_that_waited_on_the_lock_does_not_stamp_the_budget_again(monkeypatch, fresh_budget):
    """MUTATION TARGET. The second thread waits while the first resolves, then finds the cache
    and must leave the moment alone: a stamp written by every thread that waited would say the
    budget was decided when the LAST of them got the lock. The clock is a counter here because
    the real one reads whole seconds, which makes two stamps look alike."""
    _total(monkeypatch, 5000.0)
    ticks = iter(range(1, 100))
    monkeypatch.setattr(mb, "_now_iso", lambda: f"tick-{next(ticks)}")
    inside = threading.Event()
    release = threading.Event()
    real = mb.resolve

    def slow() -> dict:
        inside.set()
        release.wait(5)
        return real()

    monkeypatch.setattr(mb, "resolve", slow)
    first = threading.Thread(target=mb.budget)
    first.start()
    assert inside.wait(5), "the first resolve is under way"
    second = threading.Thread(target=mb.budget)
    second.start()
    time.sleep(0.2)  # the second asks while the first holds the lock
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert mb.resolved_reading()["resolved_at"] == "tick-1", "the first resolve's moment, once"


def test_the_cache_is_not_published_before_its_moment_has_been_made(monkeypatch, fresh_budget):
    """MUTATION TARGET. A reader on the lock-free path that finds the cache must find the moment
    it was resolved at, or it reads a real budget as one that was injected (no moment): the
    moment is made and stored before the cache is. Watched from inside the moment's own clock,
    which runs after the resolve and before either store."""
    _total(monkeypatch, 5000.0)
    seen: list[bool] = []

    def clock() -> str:
        seen.append(mb._CACHE is None)
        return "2026-10-06T07:15:55Z"

    monkeypatch.setattr(mb, "_now_iso", clock)
    mb.budget()
    assert seen == [True], "the cache was already visible while its moment was being made"
    assert mb.resolved_reading()["resolved_at"] == "2026-10-06T07:15:55Z"


def test_a_budget_that_is_already_resolved_is_read_without_taking_the_lock(monkeypatch, fresh_budget):
    """MUTATION TARGET. After the first resolve every look takes the lock-free path: only the
    resolve holds the lock, and a caller must never queue behind it (the pool asks for the budget
    on every connection). Another thread holds the lock here, and the look still returns."""
    _total(monkeypatch, 5000.0)
    mb.budget()
    held = threading.Event()
    done = threading.Event()

    def hold() -> None:
        with mb._LOCK:
            held.set()
            done.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    seen: list[dict] = []
    looker = threading.Thread(target=lambda: seen.append(mb.resolved_reading()))
    looker.start()
    looker.join(2)
    finished = not looker.is_alive()
    done.set()
    holder.join(5)
    looker.join(5)
    assert finished and seen and seen[0]["tier"] == "medium", "a look queued behind the lock"


def test_a_resolve_that_asks_for_the_budget_again_fails_loudly_and_never_hangs():
    """MUTATION TARGET (``RLock`` -> ``Lock``). The lock is held while the budget resolves, so a
    resolve that reached ``budget()`` again would, behind a plain lock, never return -- the thread
    that imports the engine stuck and the app silent -- where the code before the lock raised a
    ``RecursionError``. Run in a child so a hang cannot take this process's lock with it: the child
    must end, and say why."""
    code = (
        "from src.config import memory_budget as mb\n"
        "mb.resolve = lambda: mb.budget()\n"
        "mb.budget()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0 and "RecursionError" in proc.stderr, proc.stderr[-400:]


def test_a_budget_that_was_injected_has_no_moment_and_the_facts_follow_it(monkeypatch, fresh_budget):
    """The facts are read from the cache itself, so a cache that was put there (by a test, or a
    future caller) is read as it is, and with no resolve there is no moment: none is invented.
    Whoever injects a cache clears the stamp too (``reset_for_tests()`` does both), because a
    stamp left over from a different resolve would be shown beside facts that are not its own."""
    monkeypatch.setattr(mb, "_CACHE", {"tier": "large", "total_ram_mb": 16000.0, "nominal_ram_mb": 16384.0,
                                       "columnar_serve_default": True})
    monkeypatch.setattr(mb, "_RESOLVED", None)
    got = mb.resolved_reading()
    assert got["tier"] == "large" and got["total_ram_mb"] == 16000.0
    assert got["resolved_at"] is None and got["cores"] is None


def test_a_total_that_moved_after_the_resolve_shows_as_two_readings_and_no_verdict(monkeypatch, fresh_budget):
    """MUTATION TARGET: the ballooned virtual machine. It resolved ``small`` and reads 4.7 GiB
    later; the budget is NOT re-resolved (the pool and the caches were sized from the first
    reading), and the second reading is shown beside it as a measured fact."""
    _total(monkeypatch, 3900.0)
    assert mb.resolved_reading()["tier"] == "small"
    _total(monkeypatch, 4800.0)
    out = mb.reading_vs_now()
    assert out["resolved"]["tier"] == "small" and out["resolved"]["total_ram_mb"] == 3900.0
    assert out["now"]["tier"] == "medium" and out["now"]["total_ram_mb"] == 4800.0
    assert out["tier_differs"] is True
    assert mb.budget()["tier"] == "small", "the budget the app runs on did not move"
    text = (out["method"] + " " + out["caveat"]).lower()
    assert "not re-resolved" in text and "restart" in text
    assert "unless the operator set them" in out["method"], "an operator's own pool or cache size wins"
    assert "not a finding" in out["caveat"], "a difference is a fact about the machine, never a verdict"
    assert not any(k in out for k in ("verdict", "score", "ok", "healthy"))


def test_a_total_that_did_not_move_is_not_reported_as_a_difference(monkeypatch, fresh_budget):
    _total(monkeypatch, 8300.0)
    mb.resolved_reading()
    out = mb.reading_vs_now()
    assert out["tier_differs"] is False and out["now"]["tier"] == out["resolved"]["tier"] == "large"


def test_a_total_that_moved_inside_one_tier_is_not_reported_as_a_difference(monkeypatch, fresh_budget):
    """MUTATION TARGET: ``tier_differs`` compares tier NAMES. A ballooned machine whose total moves
    between 4,961 and 5,921 MiB (the 2026-10-06 batch's own figures for one instance) stays
    ``medium`` and is not a difference: a field that flagged every moved total would flag every
    virtual machine."""
    _total(monkeypatch, 4961.0)
    assert mb.resolved_reading()["tier"] == "medium"
    _total(monkeypatch, 5921.0)
    out = mb.reading_vs_now()
    assert out["resolved"]["total_ram_mb"] == 4961.0 and out["now"]["total_ram_mb"] == 5921.0
    assert out["now"]["tier"] == out["resolved"]["tier"] == "medium"
    assert out["tier_differs"] is False


def test_two_totals_that_print_alike_are_told_apart_by_the_nominal_size_beside_them(monkeypatch, fresh_budget):
    """The tier is decided on the nominal size of the UNROUNDED reading and the totals are shown
    rounded to a tenth: 3,973.14 MiB is a nominal 4,096 MiB machine (medium) and 3,973.10 is not
    (small), and both print 3,973.1. The nominal size beside each one says why they differ."""
    _total(monkeypatch, 3973.14)
    assert mb.resolved_reading()["tier"] == "medium"
    _total(monkeypatch, 3973.10)
    out = mb.reading_vs_now()
    assert out["resolved"]["total_ram_mb"] == out["now"]["total_ram_mb"] == 3973.1
    assert out["tier_differs"] is True
    assert (out["resolved"]["nominal_ram_mb"], out["now"]["nominal_ram_mb"]) == (4096.0, 3973.1)


def test_a_difference_that_is_about_the_reading_and_not_the_machine_says_so(monkeypatch, fresh_budget):
    """A machine whose RAM could not be read at the resolve (``unmeasured``, which is not a small one)
    and can be read now differs by tier, and that difference is about the reader and not the
    machine: the caveat says so there, and only there."""
    _total(monkeypatch, None)
    assert mb.resolved_reading()["tier"] == "unmeasured"
    _total(monkeypatch, 4800.0)
    out = mb.reading_vs_now()
    assert out["tier_differs"] is True and out["now"]["tier"] == "medium"
    assert "could not be read" in out["caveat"] and "not about the machine" in out["caveat"]
    mb.reset_for_tests()
    _total(monkeypatch, 3900.0)
    mb.resolved_reading()
    _total(monkeypatch, 4800.0)
    assert "could not be read" not in mb.reading_vs_now()["caveat"], "two measured readings need no such note"


# --------------------------------------------------------------------------- #
#  Every boot record
# --------------------------------------------------------------------------- #
@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    monkeypatch.delenv("OO_COLUMNAR_SERVE", raising=False)
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: T0)
    yield tmp_path / "data"
    sh._reset_for_tests()


def test_a_boot_record_carries_the_tier_the_session_was_resolved_to(ledger, monkeypatch, fresh_budget):
    """MUTATION TARGET. The ledger spans updates and crashes: this is the tier of EVERY
    session, not only of the ones that finished a collection pass."""
    _total(monkeypatch, 3900.0)
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    rec = sh.record_boot(None)
    assert rec["memory_budget"] == mb.resolved_reading()
    assert rec["memory_budget"]["tier"] == "small" and rec["memory_budget"]["columnar_serve_default"] is False
    on_disk = sh.read_records()[0]
    assert on_disk["memory_budget"] == rec["memory_budget"], "written to the ledger, not only returned"


def test_a_boot_record_names_the_allocator_compactly(ledger, monkeypatch, fresh_budget):
    """MUTATION TARGET. The four fields that answer it; the sentence that explains them stays
    in the previous-session peaks, where the crash report reads it."""
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    rec = sh.record_boot(None)
    assert rec["allocator"] == {"allocator": "glibc 2.39", "arena_cap": None, "effective": False,
                                "source": "the environment the process started with"}
    assert "note" not in rec["allocator"]


def test_a_boot_record_says_whether_an_operator_forced_the_rollup_either_way(ledger, monkeypatch, fresh_budget):
    """A rollup that is off because the variable says so is not one that is off because the
    tier does: the tier alone could not tell the two apart."""
    got = {}
    for value, key in ((None, "auto"), ("0", "forced-off"), ("1", "forced-on")):
        if value is None:
            monkeypatch.delenv("OO_COLUMNAR_SERVE", raising=False)
        else:
            monkeypatch.setenv("OO_COLUMNAR_SERVE", value)
        sh._reset_for_tests()
        got[key] = sh.record_boot(None)["rollup_serve_mode"]
    assert got == {"auto": "auto", "forced-off": "forced-off", "forced-on": "forced-on"}


@pytest.mark.parametrize("failing", ["memory_budget", "allocator", "rollup_serve_mode"])
def test_a_reading_that_cannot_be_taken_says_so_and_never_breaks_a_boot(ledger, monkeypatch, fresh_budget, failing):
    """MUTATION TARGET: the ledger's own rule. Each of the three has its own handler, so one
    failing never takes the other two with it, and the boot is written either way. A failed
    read is recorded as one (the mode as ``unreadable (ErrorName)``, as a string because every
    other value of the field is one): ``None`` is the record of a build that kept nothing."""

    def boom(*_a, **_k):
        raise RuntimeError("no reading")

    _total(monkeypatch, 5000.0)
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    where = {
        "memory_budget": (mb, "resolved_reading"),
        "allocator": (session_hwm, "allocator_setting"),
        "rollup_serve_mode": (rollup_serve, "serve_mode"),
    }[failing]
    monkeypatch.setattr(*where, boom)
    rec = sh.record_boot(None)
    assert rec["kind"] == "boot" and sh.read_records()[0]["session_id"] == rec["session_id"]
    broken = {"memory_budget": {"error": "RuntimeError"}, "allocator": {"error": "RuntimeError"},
              "rollup_serve_mode": "unreadable (RuntimeError)"}
    assert rec[failing] == broken[failing]
    healthy = {
        "memory_budget": lambda v: v["tier"] == "medium",
        "allocator": lambda v: v["allocator"] == "glibc 2.39",
        "rollup_serve_mode": lambda v: v == "auto",
    }
    for key, ok in healthy.items():
        if key != failing:
            assert ok(rec[key]), f"{key} was lost to the failure of {failing}"


def test_the_chronology_carries_what_each_session_ran_under(ledger, monkeypatch, fresh_budget):
    """MUTATION TARGET. One copy per session, in ``sessions``: the boot EVENT already carries
    that session's pid and version and a second copy of the reading would be a repeat."""
    _total(monkeypatch, 3900.0)
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    rec = sh.record_boot(None)
    out = ch.chronology(anchor="install", now=T0 + 600)
    sess = out["sessions"][-1]
    assert sess["memory_budget"] == rec["memory_budget"] and sess["memory_budget"]["tier"] == "small"
    assert sess["allocator"] == rec["allocator"] and sess["rollup_serve_mode"] == "auto"
    boot = [e for e in out["events"] if e["kind"] == "boot"][-1]
    assert "memory_budget" not in boot["detail"] and "allocator" not in boot["detail"]


def test_a_session_from_before_the_reading_was_kept_has_none_and_nothing_is_invented(ledger, monkeypatch):
    sh._append({"kind": "boot", "session_id": "old-1", "at": ch._iso(T0), "pid": 1})
    sess = ch.chronology(anchor="install", now=T0 + 600)["sessions"][0]
    assert sess["memory_budget"] is None and sess["allocator"] is None and sess["rollup_serve_mode"] is None


def test_each_session_of_the_ledger_carries_its_own_tier_and_not_the_last_boots(ledger, monkeypatch):
    """MUTATION TARGET. The tier each boot resolved to is what the recommended option of the
    proposal reads before anything is decided: a machine whose memory moved resolves one tier at
    one boot and another at the next, and each session says its own."""
    for sid, at, tier, total in (("s-1", T0, "small", 3900.0), ("s-2", T0 + 3600, "medium", 4800.0)):
        sh._append({"kind": "boot", "session_id": sid, "at": ch._iso(at), "pid": 1,
                    "memory_budget": _reading(tier, total, tier != "small", ch._iso(at))})
    sessions = ch.chronology(anchor="install", now=T0 + 7200)["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-1", "s-2"]
    assert [s["memory_budget"]["tier"] for s in sessions] == ["small", "medium"]


# --------------------------------------------------------------------------- #
#  The crashed session's own record, read at the next boot
# --------------------------------------------------------------------------- #
@pytest.fixture
def hwm(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    session_hwm.reset_for_tests()
    yield
    session_hwm.reset_for_tests()


def _reading(tier: str, total: float, serve: bool, at: str) -> dict:
    return {"tier": tier, "total_ram_mb": total, "nominal_ram_mb": total, "cores": 2,
            "columnar_serve_default": serve, "resolved_at": at}


def test_the_dead_sessions_tier_travels_into_the_next_boots_report(hwm, monkeypatch):
    """MUTATION TARGET. A death is read against the tier THAT session ran under, not the one
    the survivor does: on a machine whose memory moves, the two can be different tiers."""
    small = _reading("small", 3900.0, False, "2026-10-06T07:15:55Z")
    medium = _reading("medium", 4800.0, True, "2026-10-06T21:15:11Z")
    monkeypatch.setattr(mb, "resolved_reading", lambda: dict(small))
    session_hwm.capture_previous()
    assert session_hwm.current()["memory_budget"] == small
    session_hwm.reset_for_tests()  # the process dies; a new one starts with only the file
    monkeypatch.setattr(mb, "resolved_reading", lambda: dict(medium))
    prev = session_hwm.capture_previous()
    assert prev is not None and prev["memory_budget"] == small, "the previous session's, not ours"
    assert session_hwm.current()["memory_budget"] == medium
    peaks = forensics._previous_peaks()
    assert peaks is not None and peaks["memory_budget"] == small
    assert "memory_budget" in peaks["method"] and "resolved once per process" in peaks["method"]


def test_a_reading_that_cannot_be_taken_is_in_the_header_as_the_error(hwm, monkeypatch):
    def boom():
        raise RuntimeError("no psutil")

    monkeypatch.setattr(mb, "resolved_reading", boom)
    session_hwm.capture_previous()
    assert session_hwm.current()["memory_budget"] == {"error": "RuntimeError"}


def test_the_crash_report_names_the_tier_beside_the_peaks_it_bounds():
    peaks = {
        "available": True, "rss_max_mb": 3800.0,
        "memory_budget": _reading("small", 3900.0, False, "2026-10-06T07:15:55Z"),
        "at_peak": {"rss_mb": 3800.0, "at": "2026-09-30T21:08:38+00:00", "threads": 29},
    }
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert ("memory tier (small; 3,900.0 MiB read, 2 logical CPUs; resolved at 2026-10-06T07:15:55Z): "
            "this tier leaves the in-memory keyword rollup off by default") in txt
    assert "OO_COLUMNAR_SERVE" in txt and "chronology.json" in txt, (
        "the line states the tier's default and says where an operator's own choice is recorded"
    )
    assert "resolved once, when the process started" in txt
    assert txt.index("memory tier (small") < txt.index("made of, at 3800.0 MB"), (
        "the tier is read before the memory it bounds"
    )
    peaks["memory_budget"] = _reading("medium", 4093.8, True, "2026-10-06T21:15:11Z")
    peaks["memory_budget"]["nominal_ram_mb"] = 4096.0
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "memory tier (medium; 4,093.8 MiB read, a nominal 4,096 MiB machine, 2 logical CPUs" in txt
    assert "this tier leaves the in-memory keyword rollup on by default" in txt
    peaks["memory_budget"]["cores"] = 1
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "1 logical CPU; resolved at" in txt, "one CPU is not \"1 logical CPUs\""


def test_the_crash_report_is_honest_about_a_machine_it_could_not_read_and_a_reading_that_failed():
    peaks = {"available": True, "rss_max_mb": 2800.0,
             "memory_budget": {"tier": "unmeasured", "total_ram_mb": None, "nominal_ram_mb": None,
                               "cores": None, "columnar_serve_default": True, "resolved_at": None}}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert ("memory tier (unmeasured; RAM not readable): "
            "this tier leaves the in-memory keyword rollup on by default") in txt
    peaks["memory_budget"] = {"error": "RuntimeError"}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "memory tier: not read (RuntimeError)" in txt


def test_a_reading_with_neither_a_tier_nor_an_error_renders_nothing():
    """MUTATION TARGET. A dict that says nothing is not a line that says "not recorded": absent
    stays absent (a half-written header, or a later set of fields that dropped the tier)."""
    peaks = {"available": True, "rss_max_mb": 2800.0, "memory_budget": {"cores": 2},
             "at_peak": {"rss_mb": 2800.0, "at": "t", "threads": 3}}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "made of, at 2800.0 MB" in txt and "memory tier" not in txt


def test_a_record_written_before_the_tier_was_kept_renders_without_it():
    peaks = {"available": True, "rss_max_mb": 2800.0, "at_peak": {"rss_mb": 2800.0, "at": "t", "threads": 3}}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "made of, at 2800.0 MB" in txt
    assert "memory tier" not in txt, "absent is absent: nothing is invented for an older record"


# --------------------------------------------------------------------------- #
#  The soak window
# --------------------------------------------------------------------------- #
@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _guard(monkeypatch, session, *, seconds, uptime=None, **state):
    from src.scheduler import memguard

    class _Fake(memguard.MemoryGuard):
        def state(self) -> dict:
            return {**super().state(), **state}

    monkeypatch.setattr(memguard, "memory_guard", _Fake())
    monkeypatch.setattr(
        forensics, "session_uptime",
        lambda: uptime or {"measured": True, "started_at": "2026-10-06T00:00:00+00:00", "seconds": seconds},
    )
    return sw.soak_window(session)["memory_guard"]


def test_the_soak_window_names_the_tier_in_every_state_the_guard_block_can_end_in(monkeypatch, session, fresh_budget):
    """MUTATION TARGET: the block returns early in four states (guard state unreadable, guard
    blind, window unknown, uptime under the rate floor) besides the one where it measures. The
    tier is a property of the process, so it rides all five, and it never decides ``measured``."""
    _total(monkeypatch, 3900.0)
    mb.resolved_reading()
    _total(monkeypatch, 4800.0)  # the machine moved after the resolve
    seeing = _guard(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=0,
                    total_engaged_s=0.0, readings_available=True)
    blind = _guard(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=0,
                   readings_available=False)
    young = _guard(monkeypatch, session, seconds=10.0, engagements=1, total_engaged_s=2.0,
                   readings_available=True)
    unknown = _guard(monkeypatch, session, seconds=0.0, uptime={"measured": False},
                     enabled=True, engagements=0, total_engaged_s=0.0, readings_available=True)
    assert (seeing["measured"], blind["measured"], young["measured"], unknown["measured"]) == (
        True, False, False, False)
    assert "window is unknown" in unknown["reason"]
    for block in (seeing, blind, young, unknown):
        got = block["memory_budget"]
        assert got["resolved"]["tier"] == "small" and got["now"]["tier"] == "medium"
        assert got["tier_differs"] is True

    from src.scheduler import memguard

    class _Broken(memguard.MemoryGuard):
        def state(self) -> dict:
            raise RuntimeError("no guard here")

    monkeypatch.setattr(memguard, "memory_guard", _Broken())
    broken = sw.soak_window(session)["memory_guard"]
    assert broken["measured"] is False and "memory-guard state unavailable" in broken["reason"]
    assert broken["memory_budget"]["resolved"]["tier"] == "small", (
        "the tier does not come from the guard, so a guard that cannot be read is not the "
        "reason to leave it out"
    )


def test_a_tier_that_cannot_be_read_is_the_error_in_the_soak_window_and_never_a_raise(monkeypatch, session):
    def boom():
        raise RuntimeError("no reading")

    monkeypatch.setattr(mb, "reading_vs_now", boom)
    got = _guard(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=0,
                 total_engaged_s=0.0, readings_available=True)
    assert got["memory_budget"] == {"error": "RuntimeError"} and got["measured"] is True
