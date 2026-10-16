"""What the next start says about a session the app ended itself for memory (B2): one real stop through the real sentinel and ledger,
then a second boot reads it back in the forensics report, the vitals' session block and the chronology."""
from __future__ import annotations

import pytest

from src.monitoring import chronology, forensics, session_hwm
from src.monitoring import session_history as sh
from src.scheduler import memguard, memstop


@pytest.fixture
def home(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setattr(forensics, "_STOP_SIGNAL", None)
    memstop.reset_for_tests()
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    chronology._VITALS_CACHE.update(at=0.0, value=None)
    _boot_reset(monkeypatch)
    yield data
    memstop.reset_for_tests()
    sh._reset_for_tests()
    session_hwm.reset_for_tests()


def _boot_reset(monkeypatch):
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(forensics, "_WAL_AT_BOOT", None)


def _stall_and_stop(monkeypatch, *, finish: bool):
    """Session A: a real guard, a real stall, the real stop. Only the process-wide effects (pausing the scheduler, the ladder, the
    SIGTERM) are replaced; ``finish`` then runs the lifespan's own clean-shutdown step, which the stop's SIGTERM leads to."""
    from src.safety import shutdown
    from src.scheduler import release, runner

    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0: False)
    monkeypatch.setattr(release, "release_residents", lambda: {"ok": True, "rss_after_mb": 1400.0})
    sent: list = []
    monkeypatch.setattr(shutdown, "request_shutdown", lambda **k: sent.append(k) or {"ok": True})
    forensics.record_session_start()
    clock = {"t": 9000.0}
    monkeypatch.setattr(memguard.time, "monotonic", lambda: clock["t"])
    g = memguard.MemoryGuard(trip_after=3, resume_after=2, release_fn=lambda: {"ok": True})
    for _ in range(220):
        clock["t"] += 1.5
        g.observe(rss_mb=1500.0, mem_avail_mb=48.0, mem_total_mb=3900.0)
    assert g._stop_thread is not None, "the stop starts on its own thread"
    g._stop_thread.join(30)
    assert sent == [{"confirm": True}], "the stop asked for the shutdown once"
    if finish:
        forensics.record_clean_shutdown()


_BOOTS = {"n": 0}


def _next_boot(monkeypatch):
    # Two boots in one second share a ledger id (it is a stamp and a pid), so each boot is placed a minute later.
    _BOOTS["n"] += 1
    real = sh.time.time()
    monkeypatch.setattr(sh.time, "time", lambda: real + 60.0 * _BOOTS["n"])
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    chronology._VITALS_CACHE.update(at=0.0, value=None)
    _boot_reset(monkeypatch)
    forensics.record_session_start()


def test_a_finished_stop_reads_back_with_its_numbers_and_its_reason(home, monkeypatch):
    _stall_and_stop(monkeypatch, finish=True)
    _next_boot(monkeypatch)
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "clean" and rep["shutdown_reason"] == "memory exhausted"
    stop = rep["memory_stop"]
    assert stop["decision"]["due"] is True and stop["decision"]["low_share"] == 1.0
    assert stop["steps"]["shutdown"]["ok"] is True and stop["bytes_read"] > 0
    prev = chronology.for_vitals(max_age_s=0.0)["previous_session_end"]
    assert prev["stopped_for"] == "memory" and prev["clean"] is True


def test_a_stop_the_kernel_cut_short_reads_as_ended_during_shutdown_with_the_record(home, monkeypatch):
    _stall_and_stop(monkeypatch, finish=False)
    _next_boot(monkeypatch)
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unclean-end-during-shutdown" and rep["shutdown_reason"] == "memory exhausted"
    assert rep["memory_stop"]["decision"]["due"] is True
    prev = chronology.for_vitals(max_age_s=0.0)["previous_session_end"]
    assert prev["stopped_for"] == "memory" and prev["clean"] is False, "a stop the kernel cut short still says why it was ending"


def test_an_older_record_never_reads_as_the_previous_sessions(home, monkeypatch):
    _stall_and_stop(monkeypatch, finish=True)
    _next_boot(monkeypatch)
    forensics.record_clean_shutdown()
    _next_boot(monkeypatch)  # a third boot: the record names session A, the previous session is B
    rep = forensics.previous_session_report()
    assert rep["memory_stop"] is None
    assert chronology.for_vitals(max_age_s=0.0)["previous_session_end"]["stopped_for"] is None


def test_the_ledger_reason_word_is_the_one_the_stop_writes():
    import inspect

    assert memstop.SHUTDOWN_REASON == "memory exhausted"
    assert '"memory exhausted"' in inspect.getsource(chronology)


def test_a_session_that_never_stopped_has_no_record(home, monkeypatch):
    forensics.record_session_start()
    forensics.record_clean_shutdown()
    _next_boot(monkeypatch)
    assert forensics.previous_session_report()["memory_stop"] is None


@pytest.mark.parametrize("said, kept", [("memory exhausted", "memory exhausted"), ("data drive disconnected", "data drive disconnected"),
                                         ("some text the sentinel happened to hold", "unrecognised"), (["a", "list"], "unrecognised"),
                                         ({"a": 1}, "unrecognised"), (7, "unrecognised")])
def test_the_ledger_carries_only_the_apps_own_shutdown_reasons(home, said, kept):
    forensics.record_session_start()
    rec = sh._close_previous({"state": "shutting-down", "shutdown_reason": said, "pid": 1}, None)
    assert rec["reason"] == kept, "a non-string or unknown value never raises, is never copied, and is never dropped silently"


def test_no_reason_in_the_sentinel_means_no_reason_key(home):
    forensics.record_session_start()
    rec = sh._close_previous({"state": "shutting-down", "pid": 1}, None)
    assert "reason" not in rec
