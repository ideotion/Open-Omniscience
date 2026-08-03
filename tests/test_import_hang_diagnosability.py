"""The 2026-08-03 field import: what made a 2 h 20 m freeze impossible to diagnose.

THE RUN. A 650 MB import on a 2-core/4 GB box. Every one of its eighteen stages --
verify, reassemble, merge, swap -- finished in 118.6 seconds; the corpus was committed
and safe. Then the post-swap re-index ran for 3.02 hours and reached 41%, and the
operator killed it. Read as "the import took three and a half hours", which is how it
felt, that is a throughput problem. It was not:

    articles 1 -> 9,000        41.6 min   (3.6 art/s -- healthy for the hardware)
    then, at exactly 9,000      2 h 20 m   ZERO progress, until it was killed

9,000 is 18 x 500, an exact precompute-window boundary. During the freeze the run
journal recorded FOUR live child processes burning 0.57 cores continuously. Busy
workers producing nothing is a completely different fault from a deadlock, and
nothing in the logs could tell them apart.

These pin the three things that hid it. None of them makes anything faster; they make
the next occurrence a row in a log instead of a mystery.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading

import pytest


# --------------------------------------------------------------------------- #
#  1. The aggregate must not invent a child-CPU measurement it never took.
# --------------------------------------------------------------------------- #

def _quiet_run(runlog, tmp_path, monkeypatch):
    """A journal whose background sampler is stopped, so the beats below are the
    only ones in the window (the sampler mutates the same per-run state)."""
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "rl")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    monkeypatch.setattr(runlog, "_BEAT_INTERVAL_S", 3600.0)
    runlog._CURRENT = None
    rl = runlog.begin("import", label="x")
    assert rl is not None
    rl._stop.set()
    if rl._sampler is not None:
        rl._sampler.join(timeout=5)
    return rl


def _beat(rl, i, **extra):
    rec = {
        "t": f"2026-08-03T05:{i:02d}:00+00:00",
        "el_s": 100.0 + 15 * i,
        "phase": "reindexing",
        "counter": "reindex",
        "done": 9000,
        "d_cpu_s": 8.0,
    }
    rec.update(extra)
    rl._write(rec, beat=True, durable=False)


def test_a_window_where_the_child_walk_stood_down_reports_no_child_rate(tmp_path, monkeypatch):
    """THE FABRICATED ZERO.

    ``d_kids_cpu_s`` is OMITTED, never zeroed, whenever the child walk backs off --
    the beat says so in ``unmeasured``. Summing it with a default of 0 invents the
    measurement the omission exists to withhold, and invents the single worst
    reading: "the workers were idle".

    The operator's own summary said ``kids_cpu_s_per_wall_s: 0.0`` for a window in
    which ZERO of nine beats had measured children -- while other beats in the same
    freeze recorded four live children at 0.57 cores. The number said the pool was
    doing nothing; the truth was the exact opposite, and that one fact is what
    separates a wedged pool from a busy one.
    """
    from src.backup import runlog

    rl = _quiet_run(runlog, tmp_path, monkeypatch)
    for i in range(10):
        _beat(rl, i, child_walk="backoff", unmeasured=["kids: backoff"])

    recent = runlog.summarise(rl.run_id)["recent"]
    assert "kids_cpu_s_per_wall_s" not in recent, (
        "a window that measured no children must not publish a child-CPU rate -- "
        f"0.0 reads as 'the workers were idle', the opposite of the truth: {recent}"
    )
    assert "kids_unmeasured" in recent, f"the absence must be explained, not silent: {recent}"
    assert recent["cpu_s_per_wall_s"] > 0, "the PARENT rate is measured and must survive"


def test_a_window_that_did_measure_children_still_reports_the_rate(tmp_path, monkeypatch):
    """The negative-space twin. Turning a fabricated number into an honest gap is
    only correct if a genuinely measurable window still yields a REAL rate --
    otherwise it has traded invention for blindness, which looks conservative and
    is not."""
    from src.backup import runlog

    rl = _quiet_run(runlog, tmp_path, monkeypatch)
    for i in range(10):
        _beat(rl, i, kids_n=4, d_kids_cpu_s=8.5)  # the real freeze value: ~0.57 cores

    recent = runlog.summarise(rl.run_id)["recent"]
    assert "kids_unmeasured" not in recent
    assert recent["kids_cpu_s_per_wall_s"] == pytest.approx(0.57, abs=0.05), recent
    assert recent["kids_samples"] == 9


def test_a_partly_measured_window_says_the_denominator_is_partial(tmp_path, monkeypatch):
    """Averaging only the measured beats over the FULL window understates the rate.
    Honest either way -- but it must say which it is, or a partial reading passes as
    a whole-window one."""
    from src.backup import runlog

    rl = _quiet_run(runlog, tmp_path, monkeypatch)
    for i in range(10):
        if i % 2:
            _beat(rl, i, kids_n=4, d_kids_cpu_s=8.5)
        else:
            _beat(rl, i, child_walk="backoff", unmeasured=["kids: backoff"])

    recent = runlog.summarise(rl.run_id)["recent"]
    assert "kids_partial" in recent, f"a partial denominator must be disclosed: {recent}"


# --------------------------------------------------------------------------- #
#  2. A stalled POOL window must name itself while it is still stalled.
# --------------------------------------------------------------------------- #
def test_the_pool_window_watchdog_reports_partial_results_not_just_silence():
    """``_serial`` has named its slow article since 2026-08-02. The POOL path had
    nothing, so a window that never came back left only "done stopped at a multiple
    of 500" -- which cannot distinguish a wedged pool from workers grinding on
    pathological input. The watchdog reports how many of the window's results have
    arrived, which is precisely that distinction."""
    import inspect

    from src.analytics import reindex_parallel as rp

    src = inspect.getsource(rp.precompute_batch)
    assert "_SLOW_WINDOW_WARN_S" in src, "the pool window must be watched, not only the serial one"
    assert "oo-precompute-window-watchdog" in src
    # The load-bearing part is the PARTIAL COUNT: "0/500 after 20 min" and
    # "312/500 after 20 min" are different faults with different fixes.
    assert "received" in src, "the watchdog must report results-so-far, not merely elapsed time"
    assert rp._SLOW_WINDOW_WARN_S < rp._POOL_TIMEOUT_S, (
        "a window must be NAMED long before the timeout ends it, or the log arrives "
        "only once the evidence is gone"
    )


# --------------------------------------------------------------------------- #
#  3. Worker PROCESSES must not outlive the app.
# --------------------------------------------------------------------------- #
def test_shutdown_terminates_live_pool_workers():
    """The operator's second report: a Python process kept burning CPU after the app
    was shut off, and only restarting the environment cleared it.

    ``_abandon_pool`` does terminate workers -- but only from this module's own
    except/finally paths, i.e. only when the PARENT notices and unwinds. Shutdown does
    neither: it disposes the engine and SIGTERMs itself. A worker is a separate OS
    process, so nothing reaped it. Because the workers were BUSY rather than wedged,
    the parent never took an except path at all.
    """
    from src.analytics import reindex_parallel as rp

    class _FakeWorker:
        def __init__(self):
            self.alive = True
            self.terminated = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

    class _FakePool:
        def __init__(self, n):
            self._processes = {i: _FakeWorker() for i in range(n)}
            self.shut = False

        def shutdown(self, wait=True, cancel_futures=False):
            self.shut = True

    pool = _FakePool(4)  # the four live children the field journal recorded
    rp._register_pool(pool)
    try:
        killed = rp.terminate_live_pools()
    finally:
        rp._unregister_pool(pool)

    assert killed == 4, "every live worker must be terminated"
    assert all(w.terminated for w in pool._processes.values())
    assert pool.shut
    # ...and the registry is emptied, so a second call is a no-op rather than a crash.
    assert rp.terminate_live_pools() == 0


def test_the_shutdown_path_actually_calls_it():
    """The reaper works when called: registered workers die.

    SCOPE, stated because it is easy to over-read: this covers the HELPER, not the
    wiring -- it calls ``_reap_worker_processes`` directly, and still passes if
    nothing in the shutdown path ever calls it (verified by mutation). The WIRING is
    covered by ``test_request_shutdown_reaps_before_it_signals``, which drives
    ``_default_arm`` and does fail when the call is removed."""
    from src.analytics import reindex_parallel as rp
    from src.safety import shutdown

    class _FakeWorker:
        def __init__(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False

    class _FakePool:
        def __init__(self):
            self._processes = {0: _FakeWorker()}

        def shutdown(self, wait=True, cancel_futures=False):
            pass

    pool = _FakePool()
    rp._register_pool(pool)
    try:
        # _reap_worker_processes is what the arming thread runs before SIGTERM.
        shutdown._reap_worker_processes()
    finally:
        rp._unregister_pool(pool)

    assert not pool._processes[0].alive, (
        "shutdown must reap worker processes -- after SIGTERM to self there is "
        "nobody left to do it"
    )


def test_request_shutdown_reaps_before_it_signals(monkeypatch):
    """Order matters: reaping after the SIGTERM would never run.

    BEHAVIOURAL on purpose. The first draft asserted source ORDER and failed against
    correct code -- it matched the word SIGTERM inside the comment that EXPLAINS the
    ordering. That is the recorded trap where a source guard trips on its own
    explanation; the durable form drives the real path and watches what happens.
    """
    from src.analytics import reindex_parallel as rp
    from src.safety import shutdown

    order: list[str] = []

    class _FakeWorker:
        def is_alive(self):
            return True

        def terminate(self):
            order.append("reap")

    class _FakePool:
        _processes = {0: _FakeWorker()}

        def shutdown(self, wait=True, cancel_futures=False):
            pass

    # NOTE: do NOT monkeypatch shutdown.time.sleep -- `shutdown.time` IS the global
    # time module, so patching its attribute silently disables sleep for everything
    # in the process, including this test's own wait loop below. (Which is exactly
    # what happened: the poll spun 500 times instantly and gave up before the
    # shutdown thread ever ran.) `delay=0.0` gives the same effect, locally.
    done = threading.Event()

    def _fake_kill(*_a, **_k):
        order.append("sigterm")
        done.set()

    monkeypatch.setattr(shutdown.os, "kill", _fake_kill)

    # ISOLATE the process-global registry. Other suites in the same pytest process
    # legitimately leave real pools in it (the start-method probe registers one), and
    # this test asserts on WHAT GOT REAPED -- so without isolation it reads another
    # test's pool and fails for a reason that has nothing to do with the behaviour
    # under test. Passed alone, failed in a suite: the signature of a shared global.
    with rp._LIVE_POOLS_LOCK:
        saved = set(rp._LIVE_POOLS)
        rp._LIVE_POOLS.clear()
    pool = _FakePool()
    rp._register_pool(pool)
    try:
        shutdown._default_arm(0.0)
        assert done.wait(timeout=10), "the shutdown thread never reached the signal"
    finally:
        with rp._LIVE_POOLS_LOCK:
            rp._LIVE_POOLS.clear()
            rp._LIVE_POOLS.update(saved)

    assert "reap" in order, "shutdown must reap worker processes before signalling"
    assert "sigterm" in order, "the shutdown never signalled"
    assert order.index("reap") < order.index("sigterm"), (
        f"children must be reaped BEFORE the process signals itself, got {order}"
    )


# --------------------------------------------------------------------------- #
#  4. The one extractor that was never bounded.
# --------------------------------------------------------------------------- #
def test_extract_dates_is_bounded_like_its_two_siblings():
    """``extract_locations`` and ``extract_entities`` have capped their scan at
    60,000 characters since they were written -- locextract's constant literally says
    "bounded, like every scan". ``extract_dates``, in the same when/where/who pass,
    had no bound at all, so the per-article cost of the whole pass was set by the
    single largest body in the corpus. Measured before the cap:

        body      dates    places   entities
         10 KB     51 ms    264 ms      3 ms
        480 KB   2449 ms    161 ms     11 ms

    the capped two plateau, the uncapped one grows without limit.
    """
    from src.timemap import dateextract, entextract, locextract

    assert dateextract._MAX_SCAN == locextract._MAX_SCAN == entextract._MAX_SCAN, (
        "the three extractors in one pass must share one bound"
    )


def test_the_cap_is_disclosed_on_the_candidates_it_could_have_affected():
    """A recall change must be stated, not slipped in. The siblings set the precedent
    for the BOUND, not for hiding it: a caller has to be able to tell "no later dates
    in this article" from "we stopped looking"."""
    from src.timemap.dateextract import _MAX_SCAN, extract_dates

    short = "The summit was held on 14 March 2026 in Paris."
    got = extract_dates(short)
    assert got and "scan_truncated" not in got[0], "an un-truncated body claims nothing"

    long_body = "The treaty was signed on 3 April 2026. " + ("filler word " * 60_000)
    assert len(long_body) > _MAX_SCAN
    got = extract_dates(long_body)
    assert got, "a date INSIDE the cap must still be found"
    assert got[0]["scan_truncated"] == _MAX_SCAN, "the truncation must be disclosed"


def test_a_date_beyond_the_cap_is_missed_and_that_is_the_stated_cost():
    """The negative-space twin: pinning the LOSS, so nobody later reads the cap as
    free. If this ever passes without the cap being reconsidered, the bound moved."""
    from src.timemap.dateextract import _MAX_SCAN, extract_dates

    body = ("filler word " * 6_000) + " the treaty was signed on 3 April 2026."
    assert len(body) > _MAX_SCAN
    assert extract_dates(body) == [], "beyond the cap we do not look -- by design"
