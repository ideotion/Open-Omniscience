"""Rank 5, phase 0: the unlock page says what the passphrase check is doing when it has a
large log to recover, and how long this machine took the last time.

The verify connection inside ``POST /unlock`` recovers the previous session's -wal (the first
read) and writes it back into the database (the last close). The app is still locked while it
does, and the startup status is unreachable then, so the page could show only an elapsed clock.
What these tests pin:

* the record exists only while the attempt runs and is gone after it -- success, wrong
  passphrase or a crash inside the connect (a leftover would read "still recovering");
* the ONE path a locked app adds answers numbers only, and ``{"active": false}`` otherwise;
* the estimate is this machine's own last measured seconds per GiB -- absent, never a constant
  and never zero, when the machine has no measurement; and ``last_recovery`` survives an
  unlock that had no log (``last_unlock`` does not);
* a REAL encrypted store with a REAL leftover -wal, through the real ``unlock()`` function,
  shows the record while the real connect runs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.api import startup_status as ss
from src.monitoring import forensics
from tests.js_source_helper import function_source, page_source

_ROOT = Path(__file__).resolve().parents[1]
_GIB = 1024**3
_MIB = 1024 * 1024
_KEY = "unlock recovery test pass"


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(ss, "_recovery", None)
    return tmp_path


def _record(wal_bytes, verify_ms, extra_phases=()):
    phases = [{"phase": forensics.UNLOCK_VERIFY_PHASE, "ms": verify_ms}, *extra_phases]
    return {"wal_bytes_before_open": wal_bytes, "phases": phases, "synchronous_total_ms": verify_ms}


# --- the record -----------------------------------------------------------------------------


def test_the_record_is_inactive_until_an_attempt_sets_it(dd):
    assert ss.get_recovery() == {"active": False}


def test_the_record_carries_numbers_only_and_ends_with_its_attempt(dd):
    tok = ss.begin_recovery(3 * _GIB, 120.0, {"wal_bytes": 1.0 * _GIB, "seconds": 40.0})
    got = ss.get_recovery()
    assert got["active"] is True
    assert got["wal_bytes"] == 3 * _GIB and got["eta_s"] == 120.0
    assert got["basis"] == {"wal_bytes": 1.0 * _GIB, "seconds": 40.0}
    assert isinstance(got["elapsed_s"], float) and got["elapsed_s"] >= 0
    # numbers and the machine's own measurement: no path, no name, nothing a locked app withholds
    flat = json.dumps(got)
    assert str(dd) not in flat and "open_omniscience" not in flat
    ss.end_recovery(tok)
    assert ss.get_recovery() == {"active": False}


def test_a_later_attempt_keeps_its_own_record_when_an_earlier_one_ends(dd):
    first = ss.begin_recovery(1 * _GIB, None, None)
    second = ss.begin_recovery(2 * _GIB, None, None)
    ss.end_recovery(first)  # the first attempt finishing must not erase the second's record
    assert ss.get_recovery()["wal_bytes"] == 2 * _GIB
    ss.end_recovery(second)
    assert ss.get_recovery() == {"active": False}


def test_an_absent_estimate_stays_absent_not_zero(dd):
    ss.begin_recovery(2 * _GIB, None, None)
    got = ss.get_recovery()
    assert got["eta_s"] is None and got["basis"] is None


# --- the estimate's source ------------------------------------------------------------------


def test_a_large_unlock_is_kept_as_the_machines_measured_recovery(dd):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    rec = forensics.last_recovery()
    assert rec["wal_bytes"] == 2 * _GIB
    assert rec["seconds"] == 80.0 and rec["seconds_per_gib"] == 40.0


def test_a_small_log_is_not_a_rate(dd):
    # 1 MiB of log in 0.4 s is the key derivation, not a statement about logs
    forensics.record_unlock_timing(_record(1 * _MIB, 400.0))
    assert forensics.last_recovery() is None
    forensics.record_unlock_timing(_record(forensics.RECOVERY_RATE_MIN_BYTES - 1, 400.0))
    assert forensics.last_recovery() is None


@pytest.mark.parametrize(
    "bad",
    [
        {"wal_bytes_before_open": None, "phases": []},
        {"wal_bytes_before_open": True, "phases": [{"phase": forensics.UNLOCK_VERIFY_PHASE, "ms": 9}]},
        {"wal_bytes_before_open": 2 * _GIB, "phases": []},
        {"wal_bytes_before_open": 2 * _GIB, "phases": [{"phase": "other", "ms": 5000}]},
        {"wal_bytes_before_open": 2 * _GIB, "phases": [{"phase": forensics.UNLOCK_VERIFY_PHASE, "ms": 0}]},
        {"wal_bytes_before_open": 2 * _GIB, "phases": [{"phase": forensics.UNLOCK_VERIFY_PHASE, "ms": None}]},
    ],
)
def test_an_unmeasurable_record_yields_no_recovery(dd, bad):
    forensics.record_unlock_timing(bad)
    assert forensics.last_recovery() is None


def test_an_unlock_with_no_log_does_not_erase_the_last_recovery(dd):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    forensics.record_unlock_timing({"wal_bytes_before_open": None, "phases": [], "synchronous_total_ms": 300.0})
    assert forensics.session_forensics()["last_unlock"]["wal_bytes_before_open"] is None
    assert forensics.last_recovery()["seconds_per_gib"] == 40.0


def test_the_next_boot_carries_the_last_recovery_forward(dd):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    forensics.record_session_start()
    assert forensics.last_recovery()["seconds_per_gib"] == 40.0
    assert forensics.session_forensics()["last_recovery"]["seconds_per_gib"] == 40.0


def test_the_estimate_scales_this_machines_rate_and_names_its_basis(dd):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))  # 40 s per GiB
    eta, basis = forensics.recovery_estimate(3 * _GIB)
    assert eta == 120.0
    assert basis == {"wal_bytes": float(2 * _GIB), "seconds": 80.0}


def test_no_measurement_means_no_estimate_not_a_constant(dd):
    assert forensics.recovery_estimate(3 * _GIB) == (None, None)
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    assert forensics.recovery_estimate(0) == (None, None)


def test_a_damaged_sentinel_entry_is_no_measurement(dd):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    state = forensics._read_state()
    state["last_recovery"]["seconds_per_gib"] = "fast"
    forensics._write_state(state)
    assert forensics.last_recovery() is None
    assert forensics.recovery_estimate(_GIB) == (None, None)


# --- the locked app ---------------------------------------------------------------------------


def test_the_progress_path_is_served_while_locked_and_the_open_stores_status_is_not():
    """The gate matches by PREFIX and ``/api/system/unlock`` is already in the tuple, so the progress
    path was reachable before its own entry and the entry adds no reach (the Opus read of #1293);
    what this pins is the behaviour, and that the named entry is not duplicated."""
    from src.api.unlock import ALLOWED_WHILE_LOCKED, allowed_while_locked

    assert allowed_while_locked("/api/system/unlock-progress", "locked")
    # the post-unlock status stays behind the gate: it names phases of an OPEN store
    assert not allowed_while_locked("/api/system/startup-status", "locked")
    assert ALLOWED_WHILE_LOCKED.count("/api/system/unlock-progress") == 1


def test_the_progress_endpoint_answers_inactive_outside_an_attempt(dd):
    from src.api.unlock import unlock_progress

    assert unlock_progress() == {"active": False}
    tok = ss.begin_recovery(_GIB, None, None)
    assert unlock_progress()["active"] is True
    ss.end_recovery(tok)
    assert unlock_progress() == {"active": False}


def test_a_log_at_the_wal_resting_ceiling_is_not_a_recovery(dd, monkeypatch):
    """Opus read of #1293: ``journal_size_limit`` (64 MiB by default) truncates a log that ever grew
    past it back to EXACTLY that size, where it rests holding almost nothing, so a leftover log of
    exactly the ceiling used to read as "64 MB to apply" and to store key-derivation time as the
    machine's recovery rate. The floor is one byte above the ceiling in force."""
    monkeypatch.delenv("OO_WAL_SIZE_LIMIT_MB", raising=False)
    ceiling = 64 * _MIB
    assert forensics.recovery_floor_bytes() == ceiling + 1
    forensics.record_unlock_timing(_record(ceiling, 400.0))
    assert forensics.last_recovery() is None, "a log AT the resting ceiling is not a measurement"
    forensics.record_unlock_timing(_record(ceiling + 1, 400.0))
    assert forensics.last_recovery() is not None, "a log past the ceiling still is"
    from src.api import unlock as unlock_mod

    seen: list = []
    monkeypatch.setattr(ss, "begin_recovery", lambda *a, **k: seen.append(a) or 1)
    assert unlock_mod._begin_recovery_notice({"state": "present", "bytes": ceiling}) is None
    assert unlock_mod._begin_recovery_notice({"state": "present", "bytes": ceiling + 1}) == 1
    assert len(seen) == 1


def test_the_floor_follows_the_ceiling_in_force_and_never_drops_below_the_plain_floor(monkeypatch):
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "256")
    assert forensics.recovery_floor_bytes() == 256 * _MIB + 1
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "8")
    assert forensics.recovery_floor_bytes() == forensics.RECOVERY_RATE_MIN_BYTES
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "0")  # no limit: SQLite's default
    assert forensics.recovery_floor_bytes() == forensics.RECOVERY_RATE_MIN_BYTES
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "not a number")  # session.py falls back to 64
    assert forensics.recovery_floor_bytes() == 64 * _MIB + 1


# --- the real unlock path -----------------------------------------------------------------------

_CHILD = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from src.database.connect import connect
c = connect(sys.argv[2], key=sys.argv[3], create_encrypted=True, check_same_thread=False)
c.execute("PRAGMA journal_mode=WAL")
c.execute("PRAGMA wal_autocheckpoint=0")
c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v BLOB)")
c.commit()
wal = sys.argv[2] + "-wal"
while not os.path.exists(wal) or os.path.getsize(wal) < int(sys.argv[4]):
    c.execute("BEGIN")
    for _ in range(50):
        c.execute("INSERT INTO t(v) VALUES (?)", (os.urandom(3000),))
    c.execute("COMMIT")
os._exit(0)  # no close(): the log stays as a crash leaves it
"""


@pytest.fixture()
def finish_calls():
    """The keyword arguments the real ``unlock()`` handed to ``_finish_unlock``."""
    return []


@pytest.fixture()
def crashed_store(dd, monkeypatch, finish_calls):
    """A real encrypted store whose last session died with a >= 2 MiB log, wired to ``unlock()``."""
    db = dd / forensics._DB_NAME
    subprocess.run(
        [sys.executable, "-c", _CHILD, str(_ROOT), str(db), _KEY, str(2 * _MIB)],
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=120,
    )
    wal = Path(str(db) + "-wal")
    assert wal.exists() and wal.stat().st_size >= 2 * _MIB
    from src.api import unlock as unlock_mod
    from src.database import connect as connect_mod

    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: db)
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: finish_calls.append(kw))
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda *_a, **_k: None)
    # the lock state the real route reads; the file really is encrypted
    assert connect_mod.is_encrypted_file(db) is True
    # the bound under test is 64 MiB; a 2 MiB log keeps the test quick, and the bound is
    # read from the forensics module at call time so this patches the same name production reads
    monkeypatch.setattr(forensics, "RECOVERY_RATE_MIN_BYTES", 1 * _MIB)
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "0")  # no resting ceiling, so the 1 MiB floor stands
    return db, wal


@pytest.fixture()
def held_key(crashed_store, monkeypatch):
    """``crashed_store`` makes ``set_passphrase`` a no-op (the engine must not really switch keys); the open-app
    answers need the real behaviour of the in-memory key, so this gives it back: set, held, readable."""
    from src.database import connect as connect_mod

    monkeypatch.setattr(connect_mod, "_passphrase", None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: setattr(connect_mod, "_passphrase", p or None))
    return connect_mod


def test_the_real_unlock_shows_the_log_while_the_real_connect_runs(crashed_store, monkeypatch):
    db, wal = crashed_store
    wal_size = wal.stat().st_size
    forensics.record_unlock_timing(_record(512 * _MIB, 20_000.0))  # 40 s/GiB measured earlier
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    real = connect_mod.connect
    seen: dict = {}

    def spy(*a, **k):
        seen["during"] = ss.get_recovery()
        return real(*a, **k)

    monkeypatch.setattr(connect_mod, "connect", spy)
    out = unlock(PassphraseBody(passphrase=_KEY))
    assert out["unlocked"] is True
    during = seen["during"]
    assert during["active"] is True and during["wal_bytes"] == wal_size
    # this machine's own measurement (20 s for 0.5 GiB = 40 s/GiB) scaled to this log
    assert during["basis"] == {"wal_bytes": float(512 * _MIB), "seconds": 20.0}
    assert during["eta_s"] == pytest.approx(40.0 * wal_size / _GIB, abs=0.1)
    # and gone after: the log was really applied, and nothing reads "still recovering"
    assert ss.get_recovery() == {"active": False}
    assert not wal.exists() or wal.stat().st_size == 0


def test_a_wrong_passphrase_leaves_no_record_behind(crashed_store, monkeypatch):
    from fastapi import HTTPException

    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    real = connect_mod.connect
    seen: dict = {}

    def spy(*a, **k):
        seen["during"] = ss.get_recovery()
        return real(*a, **k)

    monkeypatch.setattr(connect_mod, "connect", spy)
    with pytest.raises(HTTPException) as err:
        unlock(PassphraseBody(passphrase="not the passphrase"))
    assert err.value.status_code == 403
    assert seen["during"]["active"] is True  # the wrong key still pays for the recovery
    assert seen["during"]["eta_s"] is None and seen["during"]["basis"] is None  # no measurement yet
    assert ss.get_recovery() == {"active": False}


def test_a_crash_inside_the_connect_leaves_no_record_behind(crashed_store, monkeypatch):
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    def boom(*_a, **_k):
        assert ss.get_recovery()["active"] is True
        raise OSError("disk unplugged")

    monkeypatch.setattr(connect_mod, "connect", boom)
    # the key is typed, so an unexpected failure leaves the unlock scrubbed and as a RuntimeError
    # that names the class it was; the record still ends
    with pytest.raises(RuntimeError, match=r"OSError: disk unplugged"):
        unlock(PassphraseBody(passphrase=_KEY))
    assert ss.get_recovery() == {"active": False}


def test_a_small_log_makes_no_record(dd, monkeypatch):
    from src.api.unlock import _begin_recovery_notice

    monkeypatch.setattr(forensics, "RECOVERY_RATE_MIN_BYTES", 64 * _MIB)
    assert _begin_recovery_notice({"state": "present", "bytes": 10 * _MIB}) is None
    assert _begin_recovery_notice({"state": "absent", "bytes": 0}) is None
    assert _begin_recovery_notice({"state": "unreadable", "bytes": None}) is None
    assert _begin_recovery_notice(None) is None
    assert ss.get_recovery() == {"active": False}


def test_a_notice_failure_never_blocks_an_unlock(dd, monkeypatch):
    from src.api import unlock as unlock_mod

    def boom(*_a, **_k):
        raise RuntimeError("status store broken")

    monkeypatch.setattr(ss, "begin_recovery", boom)
    assert unlock_mod._begin_recovery_notice({"state": "present", "bytes": 10 * _GIB}) is None
    monkeypatch.setattr(ss, "end_recovery", boom)
    unlock_mod._end_recovery_notice(3)  # swallowed


# --- the page ----------------------------------------------------------------------------------


def test_the_page_polls_during_the_post_and_stops_before_waiting_for_ready():
    src = page_source("unlock.html")
    assert 'id="prep-recovery"' in src and 'id="prep-rec-1"' in src and 'id="prep-rec-2"' in src
    body = function_source(src, "go")
    assert body.index("_startRecoveryPoll();") < body.index("await fn()")
    # the poll stops as soon as the POST returns (before the ready-wait) and in the failure path,
    # so neither a wrong passphrase nor a slow ready-wait leaves it running
    assert body.index("await fn()") < body.index("_stopRecoveryPoll()") < body.index("await waitReadyThenEnter(")
    assert body.index("catch (e) {") < body.rindex("_stopRecoveryPoll()")
    assert "/api/system/unlock-progress" in src


def test_the_page_states_its_numbers_and_never_a_percent():
    src = page_source("unlock.html")
    body = function_source(src, "recoveryLines")
    assert "%" not in body.replace("%s", ""), "a recovery sentence must not render a percent"
    assert "Applying up to {size} of writes the last session had not yet moved into your database" in body
    assert "no earlier measurement on this machine" in body
    # the basis of the estimate is shown beside it, and an overrun is stated, not hidden
    assert "past_size" in body and "eta_time" in body
    assert "That estimate has passed" in body


def test_every_recovery_sentence_is_translated_in_all_locales():
    keys = [
        "Applying up to {size} of writes the last session had not yet moved into your database. Nothing is downloaded.",
        "Last time on this machine, {past_size} took {past_time}, so this should take about {eta_time}.",
        "That estimate has passed; the step is still running.",
        "There is no earlier measurement on this machine to compare with. A large log can take several minutes.",
    ]
    loc = _ROOT / "src" / "static" / "locales"
    for path in sorted(loc.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), f"{path.name} lacks {k[:40]!r}"


def test_the_sentences_run_as_real_code_under_node_in_every_locale():
    """tests/unlock_recovery_node_test.js extracts the page's own functions and composes the
    sentences in all 12 locales (no placeholder left, no percent, an overrun stated)."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "unlock_recovery_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unlock recovery node test OK" in proc.stdout


# --- the close that froze the process -------------------------------------------------------------


def test_the_verify_connection_is_checkpointed_through_execute_before_it_closes(crashed_store, monkeypatch):
    """sqlcipher3's close() holds the GIL through the checkpoint it runs when it closes the last
    connection; the same checkpoint run through execute() releases it (measured in the helper's
    docstring). So the log must already be written back when close() is called."""
    db, wal = crashed_store
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    real = connect_mod.connect
    order: list = []

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *a, **k):
            order.append(("execute", sql))
            return self._inner.execute(sql, *a, **k)

        def close(self):
            order.append(("close", wal.stat().st_size if wal.exists() else 0))
            return self._inner.close()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: Spy(real(*a, **k)))
    assert wal.stat().st_size >= 2 * _MIB
    unlock(PassphraseBody(passphrase=_KEY))
    kinds = [o[0] for o in order]
    assert kinds == ["execute", "execute", "close"], order
    # the checkpoint never waits for a reader: the timeout is zeroed BEFORE it
    assert order[0][1] == "PRAGMA busy_timeout = 0"
    assert order[1][1] == "PRAGMA wal_checkpoint(TRUNCATE)"
    # when close() ran there was nothing left in the log for it to hold the GIL over
    assert order[2][1] == 0, f"{order[2][1]} bytes of log were still there when close() ran"


def test_a_reader_holding_the_log_does_not_make_the_unlock_wait(crashed_store):
    """Opus read of #1293: the verify connection inherits connect()'s 30 s busy timeout, and a
    TRUNCATE checkpoint with ANOTHER connection holding a read snapshot waits all of it while
    holding the WAL write lock (measured 30.12 s; the old close() skipped the checkpoint in
    0.00 s). A second process on the file, or a POST /unlock on an app that is already unlocked,
    reaches this. The checkpoint now returns busy at once and close() does what it always did."""
    import time

    db, wal = crashed_store
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    reader = connect_mod.connect(db, key=_KEY, check_same_thread=False)
    try:
        reader.execute("BEGIN")
        before = reader.execute("SELECT count(*) FROM t").fetchone()[0]
        assert before > 0
        t0 = time.monotonic()
        unlock(PassphraseBody(passphrase=_KEY))
        waited = time.monotonic() - t0
        assert waited < 10.0, f"the unlock waited {waited:.1f} s for a reader (busy_timeout is 30 s)"
        # the reader's snapshot and the data are untouched
        assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == before
    finally:
        reader.close()


def test_a_failed_checkpoint_falls_back_to_the_close_that_always_ran():
    from src.api.unlock import _close_after_checkpoint

    calls: list = []

    class Conn:
        def execute(self, *_a):
            calls.append("execute")
            raise RuntimeError("database is locked")

        def close(self):
            calls.append("close")

    _close_after_checkpoint(Conn())
    assert calls == ["execute", "close"]


def test_a_failed_checkpoint_is_logged_not_swallowed(caplog):
    """Opus read of #1293 / the coordinator's check: a write-back that fails (a full drive, an I/O
    error) was a DEBUG line, so the step ended "successfully" and the next the person heard of the
    drive was init_db failing on it. It is a WARNING now, with the driver's first line only."""
    import logging

    from src.api.unlock import _close_after_checkpoint

    class Conn:
        def execute(self, *_a):
            raise RuntimeError("disk I/O error\nSECRET trailing line")

        def close(self):
            pass

    with caplog.at_level(logging.WARNING, logger="api.unlock"):
        _close_after_checkpoint(Conn())
    (rec,) = [r for r in caplog.records if "written back" in r.getMessage()]
    assert rec.levelno == logging.WARNING
    assert "RuntimeError: disk I/O error" in rec.getMessage()
    assert "SECRET" not in rec.getMessage()


def test_the_real_unlock_hands_the_verify_and_the_log_to_the_forensic_record(crashed_store, finish_calls):
    """``_finish_unlock`` is patched out in this file's real-store tests, so nothing proved that
    ``unlock()`` passes the verify time and the pre-open log reading on: if either call site
    changed, the page would say "no earlier measurement" for ever and every other test here would
    stay green (the coordinator's check of #1293)."""
    db, wal = crashed_store
    wal_size = wal.stat().st_size
    from src.api.unlock import PassphraseBody, unlock

    unlock(PassphraseBody(passphrase=_KEY))
    (kw,) = finish_calls
    assert kw["verify_ms"] > 0
    assert kw["wal_state"]["state"] == "present" and kw["wal_state"]["bytes"] == wal_size


def test_the_timer_names_the_verify_phase_so_the_recovery_is_measured(dd):
    """The other link: ``add_phase(UNLOCK_VERIFY_PHASE, ms)`` then ``finish()`` is what puts a
    rate into ``last_recovery`` (the name is compared literally, not by a copy of it)."""
    from src.api.unlock import _forensic_timer

    t = _forensic_timer(wal_state={"state": "present", "bytes": 3 * _GIB})
    t.add_phase(forensics.UNLOCK_VERIFY_PHASE, 120_000.0)
    t.finish()
    rec = forensics.last_recovery()
    assert rec is not None and rec["seconds_per_gib"] == 40.0 and rec["wal_bytes"] == 3 * _GIB


def test_two_overlapping_attempts_run_one_after_the_other(held_key, monkeypatch):
    """The second attempt (a reload and a second click, a second tab) used to race the first: it
    replaced the first's recovery notice, read the log the first was still recovering and then
    recorded a rate several times too fast. It now waits its turn, and finds the app already open:
    it does not run an unlock again (no recovery notice, no engine disposal, the app is not marked
    unqueryable again and no second start-up upkeep starts: the PR 1306 check, S2). The key it
    brings is the held one, and the file is still asked, with one plain read connection and no notice
    (the check of the findings fix: an open app does not prove the key in memory opened the file)."""
    import threading
    import time

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    real = connect_mod.connect
    events: list = []
    answers: list = []
    first_inside = threading.Event()
    release_first = threading.Event()
    n = {"connect": 0}
    state = {"now": "locked"}

    def spy(*a, **k):
        n["connect"] += 1
        mine = n["connect"]
        events.append(("connect", mine, ss.get_recovery()["active"]))
        if mine == 1:
            first_inside.set()
            assert release_first.wait(30), "the test never released the first attempt"
        return real(*a, **k)

    def finish(**kw):
        events.append(("finish", kw["wal_state"]["state"]))
        state["now"] = "unlocked-encrypted"  # what the real finish leaves behind

    monkeypatch.setattr(connect_mod, "connect", spy)
    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: state["now"])
    t1 = threading.Thread(target=lambda: answers.append(unlock(PassphraseBody(passphrase=_KEY))))
    t2 = threading.Thread(target=lambda: answers.append(unlock(PassphraseBody(passphrase=_KEY))))
    t1.start()
    try:
        assert first_inside.wait(30)
        t2.start()
        time.sleep(0.4)
        assert n["connect"] == 1, "the second attempt started its own verify while the first was running"
    finally:
        release_first.set()  # never leave the first attempt parked, pass or fail
    t1.join(60)
    t2.join(60)
    assert not t1.is_alive() and not t2.is_alive()
    # ONE unlock (a verify under its recovery notice, and a finish): the second attempt found the app open and
    # only READ the file with the held key, under no notice
    assert [e[:2] for e in events] == [("connect", 1), ("finish", "present"), ("connect", 2)], events
    assert events[0][2] is True and events[2][2] is False, "the second read ran an unlock's recovery notice"
    assert answers == [{"unlocked": True, "state": "unlocked-encrypted"}] * 2, answers


def test_an_attempt_on_an_app_that_is_already_open_only_asks_the_file_read_only(held_key, monkeypatch):
    """Not only a queued attempt: a request that arrives after the unlock finished (a stale tab, a
    double click that lands late) is not run again. The held key it brings is asked of the FILE (one
    READ-ONLY connection, closed plainly) and nothing else happens: no checkpoint, no finish, no key swap."""
    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    calls: list = []

    class _Conn:
        def close(self):
            calls.append("close")

    def read(*a, **k):
        calls.append(("connect", k.get("key"), k.get("read_only")))
        return _Conn()

    connect_mod.set_passphrase(_KEY)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(connect_mod, "connect", read)
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn: calls.append("checkpoint"))
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: calls.append("finish"))
    assert unlock(PassphraseBody(passphrase=_KEY)) == {"unlocked": True, "state": "unlocked-encrypted"}
    assert calls == [("connect", _KEY, True), "close"], calls
    assert connect_mod.get_passphrase() == _KEY


def test_the_held_key_is_asked_of_the_real_file_too(crashed_store, held_key, finish_calls, monkeypatch):
    """The check of the findings fix, on a REAL encrypted store (the stubs above pin the wiring only): an app
    that reads as open holds a key that may never have opened the file (a mis-set ``OO_DB_PASSPHRASE``), and
    the same key typed into the unlock page was answered 200 without a read. Now the file is asked: the wrong
    held key typed again is refused, the right one answers, and neither runs a finish or replaces the key."""
    pytest.importorskip("sqlcipher3")
    from fastapi import HTTPException

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    wrong = "a wrong key from the environment"
    held_key.set_passphrase(wrong)
    with pytest.raises(HTTPException) as err:
        unlock(PassphraseBody(passphrase=wrong))
    assert err.value.status_code == 403
    assert held_key.get_passphrase() == wrong and finish_calls == []
    # and the right one, typed next, repairs the held key and runs the finish once (the repair path, real file)
    assert unlock(PassphraseBody(passphrase=_KEY))["unlocked"] is True
    assert held_key.get_passphrase() == _KEY and len(finish_calls) == 1
    # the right key held and typed again: the file answers, and nothing runs again
    assert unlock(PassphraseBody(passphrase=_KEY)) == {"unlocked": True, "state": "unlocked-encrypted"}
    assert held_key.get_passphrase() == _KEY and len(finish_calls) == 1


def _log_and_file(db: Path) -> tuple[bytes, bytes]:
    return db.read_bytes(), Path(str(db) + "-wal").read_bytes()


def test_asking_the_file_about_the_held_key_leaves_the_leftover_log_in_place(crashed_store, held_key, monkeypatch):
    """The check of the check (coordinator, #1325): with no pool open the question's connection is the LAST one on the
    file, and the last connection to close checkpoints a leftover log into the file and deletes it, with a wrong key
    as with the right one (``PRAGMA query_only`` does not stop that). The log a crash left is for whoever reads it
    next, so the question is asked read-only: right key, wrong key, and the log and the file are the same bytes."""
    pytest.importorskip("sqlcipher3")
    from fastapi import HTTPException

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    db, wal = crashed_store
    before = _log_and_file(db)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    held_key.set_passphrase("a wrong key from the environment")
    with pytest.raises(HTTPException) as err:
        unlock(PassphraseBody(passphrase="a wrong key from the environment"))
    assert err.value.status_code == 403
    assert wal.exists() and _log_and_file(db) == before, "a refused question consumed the leftover log"
    held_key.set_passphrase(_KEY)
    assert unlock(PassphraseBody(passphrase=_KEY)) == {"unlocked": True, "state": "unlocked-encrypted"}
    assert wal.exists() and _log_and_file(db) == before, "an answered question consumed the leftover log"


def test_a_wrong_passphrase_on_an_open_app_is_refused_not_told_it_worked(held_key, monkeypatch):
    """The state alone does not answer, so which key it is must still be checked: a second tab that types a
    misremembered passphrase after the first tab unlocked used to get 200 (THE passphrase has no recovery, so
    'that one was right' is the one false answer that costs something later). A key that is not the held one is
    checked against the file, which refuses a wrong one (403) and starts no work."""
    from fastapi import HTTPException

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    calls: list = []

    def refuse(*a, **k):
        calls.append("connect")
        raise connect_mod.WrongPassphraseError("Wrong passphrase — try again.")

    connect_mod.set_passphrase(_KEY)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(connect_mod, "connect", refuse)
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: calls.append("finish"))
    with pytest.raises(HTTPException) as err:
        unlock(PassphraseBody(passphrase="definitely-not-the-passphrase"))
    assert err.value.status_code == 403 and calls == ["connect"], "a wrong key was answered, or it started work"
    assert connect_mod.get_passphrase() == _KEY, "a refused key replaced the held one"


def test_the_right_passphrase_repairs_an_open_app_that_holds_a_wrong_key(held_key, monkeypatch):
    """With ``OO_DB_PASSPHRASE`` set wrong the app reads as open (the held key is trusted), and a POST /unlock with
    the RIGHT passphrase was refused with 403 by the comparison, where the verify used to repair it (the deep
    read's N4). A key that is not the held one is verified against the file: right replaces the held key and runs
    the finish."""
    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    calls: list = []
    connect_mod.set_passphrase("a-wrong-key-from-the-environment")
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: calls.append(("connect", k.get("key"))))
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: calls.append("close"))
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: calls.append("finish"))
    assert unlock(PassphraseBody(passphrase=_KEY))["unlocked"] is True
    assert calls == [("connect", _KEY), "close", "finish"], calls
    assert connect_mod.get_passphrase() == _KEY, "the right passphrase did not replace the wrong held one"


def test_a_finish_that_fails_returns_the_app_to_locked_so_the_retry_is_a_real_retry(held_key, monkeypatch):
    """A key in memory means 'a key is in memory', not 'the unlock finished'. Left after a failed finish (init_db on
    a full drive or a damaged file), the app read as open, the retry was answered from that state with nothing run,
    and the page waited on 'opening the database' for ever (the deep read of the findings PR, B1)."""
    from sqlalchemy.exc import OperationalError

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock
    from src.database import connect as connect_mod

    finishes: list = []
    disposed: list = []
    import src.database.session as session_mod

    monkeypatch.setattr(session_mod, "dispose_engine", lambda: disposed.append(1))

    # the failure the fix names arrives from SQLAlchemy (init_db on a full drive or a damaged file), which is
    # NOT an OSError, and a bare RuntimeError (a thread that cannot start) is another: any exception clears the key
    for failure in (
        OperationalError("INSERT", {}, Exception("database or disk is full")),
        OSError("no space left on device"),
        RuntimeError("anything else"),
    ):
        finishes.clear()
        disposed.clear()

        def finish(failure=failure, **kw):
            finishes.append(1)
            if len(finishes) == 1:
                raise failure

        monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
        connect_mod.set_passphrase(None)
        assert unlock_mod.app_lock_state() == "locked"
        # the typed key is scrubbed on the way out, so the failure leaves as a RuntimeError naming its class
        with pytest.raises(RuntimeError, match=type(failure).__name__):
            unlock(PassphraseBody(passphrase=_KEY))
        assert connect_mod.get_passphrase() is None and unlock_mod.app_lock_state() == "locked", repr(failure)
        assert disposed, "the pool keeps the connections init_db opened with the key; they go with it"
        assert unlock(PassphraseBody(passphrase=_KEY))["unlocked"] is True
        assert len(finishes) == 2, "the retry was answered without running the finish"
        connect_mod.set_passphrase(None)


def test_an_upkeep_thread_that_cannot_start_does_not_send_a_usable_app_back_to_the_lock_screen(monkeypatch):
    """``threading.Thread(...).start()`` raises ``RuntimeError`` ("can't start new thread") on the memory-starved
    machines this work is about. The upkeep is best-effort and ``init_db`` has made the store queryable, so
    the finish reports ready with the error instead of failing (and being locked again by its caller)."""
    import threading

    from src.api import main as main_mod
    from src.api import startup_status
    from src.api import unlock as unlock_mod
    from src.database import session as session_mod

    states: list = []
    monkeypatch.setattr(main_mod, "init_db", lambda: None)
    monkeypatch.setattr(session_mod, "dispose_engine", lambda: None)
    monkeypatch.setattr(startup_status, "mark_queryable", lambda: None)
    monkeypatch.setattr(startup_status, "set_startup", lambda *a, **k: states.append((a, k)))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")

    class Refusing:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading, "Thread", Refusing)
    unlock_mod._finish_unlock(wal_state=None, verify_ms=None)  # must not raise
    monkeypatch.undo()
    ready = [kw for a, kw in states if a and a[0] == "ready"]
    assert ready and "can't start new thread" in ready[-1]["error"], states


@pytest.mark.parametrize("bad", ["12", None, True, float("nan"), float("inf"), -5, 0])
def test_a_size_that_is_not_a_real_positive_number_is_no_estimate(dd, bad):
    forensics.record_unlock_timing(_record(2 * _GIB, 80_000.0))
    assert forensics.recovery_estimate(bad) == (None, None)


def test_a_key_with_a_lone_surrogate_is_refused_in_fixed_words_where_the_held_key_is_compared(held_key, monkeypatch, caplog):
    """The typed key is compared with the held one as UTF-8 bytes, and a lone surrogate cannot be encoded: Python's error names
    the character and its offset, a piece of the key no scrub knows, and it used to leave the route as it was raised. It is a 400 in
    fixed words that name no character. MUTATION TARGET: the encode outside the helper or outside the scrubbing block."""
    from fastapi import HTTPException

    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    held_key.set_passphrase(_KEY)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    typed = "ab\ud800cd-typed-key"
    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPException) as err:
        unlock(PassphraseBody(passphrase=typed))
    assert err.value.status_code == 400 and "UTF-8" in err.value.detail
    written = err.value.detail + "\n".join(f"{r.getMessage()}\n{r.exc_text or ''}" for r in caplog.records)
    assert "ud800" not in written and "position" not in written and "surrogate" not in written, written
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_a_held_key_with_a_lone_surrogate_leaves_the_compare_as_a_class_and_a_fixed_note(held_key, monkeypatch, caplog):
    """The held key can carry a lone surrogate too (the environment's bytes decoded with ``surrogateescape``), and the error that
    encoding it raises names that character and its offset: one character matches no held shape, so scrubbing cannot take it out.
    ``scrub_and_reraise`` records any ``UnicodeError`` as its class and a fixed note, and the error it raises, and the one
    Python keeps as its context, carry neither. MUTATION TARGETS: the encode outside the block; the class-only rule."""
    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    held_key.set_passphrase("held\udcffkey-long-enough")
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as err:
        unlock(PassphraseBody(passphrase="typed-key-fine"))
    written = str(err.value) + "".join(
        f"{r.getMessage()}\n{r.exc_text or ''}\n{getattr(r, 'scrubbed_traceback', '')}" for r in caplog.records
    )
    assert "udcff" not in written and "position" not in written and "surrogate" not in written, written
    # The error Python keeps as the context is emptied in place: its text still has the codec's frame, with no character
    # and not the offset (the key's lone surrogate is at 4).
    context = str(err.value.__context__)
    assert "udcff" not in context and "surrogate" not in context and "position 4" not in context, context
    # In place, field by field: the repr and the object hold no piece of the key either (MUTATION TARGET: _defang).
    assert "long-enough" not in repr(err.value.__context__) and err.value.__context__.object == "", repr(err.value.__context__)
    assert "UnicodeEncodeError" in str(err.value), err.value
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_the_unlock_compare_is_inside_the_scrubbing_block(held_key, monkeypatch):
    """An error the helper raises is converted with the typed key out of it. MUTATION TARGET: the compare outside the block
    (an ``HTTPException`` passes the block, so only another error type shows it)."""
    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    held_key.set_passphrase(_KEY)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")

    def names_the_key(passphrase):
        raise ValueError(f"cannot read {passphrase}")

    monkeypatch.setattr(unlock_mod, "_passphrase_bytes", names_the_key)
    typed = "typed-key-needs-no-secret"
    with pytest.raises(RuntimeError) as err:
        unlock(PassphraseBody(passphrase=typed))
    assert typed not in str(err.value) and "ValueError" in str(err.value), err.value


def test_the_held_key_question_with_a_wrong_short_key_is_answered_in_the_fixed_403_words(tmp_path, monkeypatch):
    """``_file_opens_with`` passes the same withheld words as ``_unlock_locked``: a key under the scrub's floor gets the fixed
    sentence, not the long withheld notice."""
    from fastapi import HTTPException

    from src.api import unlock as unlock_mod
    from src.database.connect import WrongPassphraseError

    def refuses(*a, **k):
        raise WrongPassphraseError("file is not a database: ab")

    import src.database.connect as connect_mod

    monkeypatch.setattr(connect_mod, "connect", refuses)
    with pytest.raises(HTTPException) as err:
        unlock_mod._file_opens_with(tmp_path / "x.db", "ab")
    assert err.value.status_code == 403
    assert err.value.detail == "the passphrase does not open this file (or the file is damaged)", err.value.detail


def test_an_implicit_unicode_context_is_withheld_and_emptied_too(held_key, monkeypatch):
    """The error raised inside an ``except UnicodeError`` has the first one as its context with no ``from``: the walk finds it
    there, and the converted error carries neither the character nor the key."""
    from src.api import unlock as unlock_mod
    from src.api.unlock import PassphraseBody, unlock

    held_key.set_passphrase(_KEY)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")

    def encodes_then_fails(passphrase):
        try:
            "typed\udcffkey-long-enough".encode()
        except UnicodeError:
            raise ValueError("could not encode")  # noqa: B904 - the implicit context is the case

    monkeypatch.setattr(unlock_mod, "_passphrase_bytes", encodes_then_fails)
    with pytest.raises(RuntimeError) as err:
        unlock(PassphraseBody(passphrase="typed-key-fine"))
    assert "UnicodeEncodeError" in str(err.value) and "udcff" not in str(err.value) and "position" not in str(err.value)
    # The first error is two links down (the converted error's context is the ValueError, whose context it is): emptied in place.
    first = err.value.__context__.__context__
    assert isinstance(first, UnicodeError) and first.object == "" and "long-enough" not in repr(first) and "udcff" not in repr(first), repr(first)
