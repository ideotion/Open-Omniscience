"""src/monitoring/win_power.py: the Windows power and console-end listeners (F7). The ctypes registration itself needs Windows; what
decides behaviour (the handlers' bodies, the bounded checkpoint, the off-Windows no-op) is driven here."""

from __future__ import annotations

import signal
import sqlite3
import types

from src.monitoring import win_power


def test_install_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(win_power, "sys", types.SimpleNamespace(platform="linux"))
    assert win_power.install() == []


def test_a_session_ending_console_event_records_and_raises_sigint(monkeypatch):
    raised: list = []
    noted: list = []
    monkeypatch.setattr(win_power, "signal", types.SimpleNamespace(SIGINT=signal.SIGINT, raise_signal=lambda s: raised.append(s)))
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "note_stop_signal", lambda n: noted.append(("sig", n)))
    monkeypatch.setattr(forensics, "record_shutdown_phase", lambda p, **k: noted.append((p, k.get("reason"))))
    slept: list = []
    for code, name in ((2, "CTRL_CLOSE_EVENT"), (5, "CTRL_LOGOFF_EVENT"), (6, "CTRL_SHUTDOWN_EVENT")):
        raised.clear()
        noted.clear()
        assert win_power.on_console_event(code, hold_s=7, sleep=slept.append) is True
        assert raised == [signal.SIGINT]
        assert noted == [("sig", name), ("os-ending", name)]
    assert slept == [7, 7, 7]  # it stays in the handler: returning would end the process before the graceful path ran


def test_ctrl_c_and_break_are_left_to_uvicorn():
    slept: list = []
    assert win_power.on_console_event(0, sleep=slept.append) is False  # CTRL_C_EVENT
    assert win_power.on_console_event(1, sleep=slept.append) is False  # CTRL_BREAK_EVENT
    assert slept == []


def test_suspend_runs_a_passive_checkpoint_and_resume_is_noted(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.setattr(win_power, "suspend_checkpoint", lambda **k: seen.append("cp") or {"outcome": "done"})
    win_power.on_power_event(4)
    win_power.on_power_event(18)
    kinds = [e["kind"] for e in win_power.last_events()[-2:]]
    assert seen == ["cp"] and kinds == ["suspend", "resume"]


def test_suspend_checkpoint_is_passive_never_truncate_and_skips_a_store_not_open_here(monkeypatch, tmp_path):
    from src.database import connect as connect_mod
    from src.database import session

    db = tmp_path / "t.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(session, "DB_FILE", str(db))
    monkeypatch.setattr(connect_mod, "locked_state", lambda p: "locked")
    assert win_power.suspend_checkpoint()["outcome"] == "skipped"

    statements: list = []

    class _Conn:
        def execute(self, sql):
            statements.append(sql)
            return types.SimpleNamespace(fetchone=lambda: (0, 3, 3))

        def interrupt(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(connect_mod, "locked_state", lambda p: "unlocked-plaintext")
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: _Conn())
    out = win_power.suspend_checkpoint()
    assert out["outcome"] == "done" and out["passive"] == [0, 3, 3]
    assert "PRAGMA wal_checkpoint(PASSIVE)" in statements
    assert not any("TRUNCATE" in s.upper() for s in statements)


def test_main_wires_it_in_serve():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert "win_power import install" in src


def test_suspend_checkpoint_returns_at_the_deadline_when_the_work_hangs(monkeypatch):
    import threading
    import time

    release = threading.Event()
    monkeypatch.setattr(win_power, "_passive_checkpoint", lambda b: release.wait(5) and {"outcome": "done"})
    began = time.monotonic()
    out = win_power.suspend_checkpoint(budget_s=0.1)
    release.set()
    assert out["outcome"] == "timeout" and time.monotonic() - began < 2
