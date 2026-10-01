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


def test_the_progress_path_is_served_while_locked_and_is_the_only_path_added():
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
def crashed_store(dd, monkeypatch):
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
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda *_a, **_k: None)
    # the lock state the real route reads; the file really is encrypted
    assert connect_mod.is_encrypted_file(db) is True
    # the bound under test is 64 MiB; a 2 MiB log keeps the test quick, and the bound is
    # read from the forensics module at call time so this patches the same name production reads
    monkeypatch.setattr(forensics, "RECOVERY_RATE_MIN_BYTES", 1 * _MIB)
    return db, wal


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
    with pytest.raises(OSError):
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
    assert "Applying {size} of writes the last session had not yet moved into your database" in body
    assert "no earlier measurement on this machine" in body
    # the basis of the estimate is shown beside it, and an overrun is stated, not hidden
    assert "past_size" in body and "eta_time" in body
    assert "That estimate has passed" in body


def test_every_recovery_sentence_is_translated_in_all_locales():
    keys = [
        "Applying {size} of writes the last session had not yet moved into your database. Nothing is downloaded.",
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
    assert kinds == ["execute", "close"], order
    assert order[0][1] == "PRAGMA wal_checkpoint(TRUNCATE)"
    # when close() ran there was nothing left in the log for it to hold the GIL over
    assert order[1][1] == 0, f"{order[1][1]} bytes of log were still there when close() ran"


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
