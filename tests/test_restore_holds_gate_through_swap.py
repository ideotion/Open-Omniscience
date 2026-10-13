"""A restore holds the write gate from the settings carry to the replace, so a settings save in between lands in the NEW file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_carry_live_settings`` copies the live ``app_state`` rows into the working copy just before the swap. A settings save
(``kv_set_json``) takes the single-writer gate for its write but holds neither the corpus lease nor a guard of the swap window, so one
that committed between the carry's read and the replace returned success, was served from the in-process cache, and was gone at the
next start. ``_carry_and_swap`` closes the gap: the gate is held on the restore thread from before the carry to the end of
``swap_in_corpus``, a save during the hold waits and lands in the file that is live afterwards, and the settings cache is emptied
before the gate is let go.

The hold starts AFTER ``_checkpoint_before_swap`` (that runs on its own thread and needs the gate), and a restore that cannot get the
gate refuses with nothing written.
"""

from __future__ import annotations

import ast
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import src.backup.merge as merge
import src.backup.sqlite_backup as sqlite_backup
from src.config import kv_store
from src.database import library_generation
from src.database.writer import write_gate, write_lock

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
_PATIENCE_S = 30.0


def _file(path: Path, rows: dict[str, str]) -> Path:
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
        for k, v in rows.items():
            con.execute("INSERT INTO app_state VALUES (?, ?, '2026-10-13 00:00:00')", (k, v))
        con.commit()
    finally:
        con.close()
    return path


def _rows(path: Path) -> dict[str, str]:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT key, value FROM app_state"))
    finally:
        con.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    live = _file(tmp_path / "open_omniscience.db", {"settings.app": '{"v": 1}', "ui.note": '{"old": true}'})
    working = _file(tmp_path / "working.db", {"settings.app": '{"v": 1}', "ui.note": '{"old": true}'})
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: live)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)  # the app's engine is not this test's
    kv_store.kv_invalidate()
    yield tmp_path, live, working
    kv_store.kv_invalidate()


def _free_from_another_thread() -> bool:
    """Can a thread that is NOT the restore thread take the gate right now?"""
    got: list[bool] = []

    def probe() -> None:
        ok = write_gate.acquire(timeout=0)
        if ok:
            write_gate.release()
        got.append(ok)

    t = threading.Thread(target=probe)
    t.start()
    t.join(_PATIENCE_S)
    return bool(got and got[0])


def _wait_for_waiters(n: int) -> None:
    deadline = time.monotonic() + _PATIENCE_S
    while write_gate.stats()["waiters"] < n:
        assert time.monotonic() < deadline, "the save never reached the gate"
        time.sleep(0.01)


def _run_with_a_deadline(fn) -> BaseException | None:
    """Run ``fn`` on a thread that is given up on after ``_PATIENCE_S``: a deadlock fails the test instead of hanging the suite."""
    out: list[BaseException | None] = []

    def body() -> None:
        try:
            fn()
            out.append(None)
        except BaseException as exc:  # noqa: BLE001 - handed to the test
            out.append(exc)

    t = threading.Thread(target=body, daemon=True)
    t.start()
    t.join(_PATIENCE_S)
    assert out, "the restore thread did not finish: something between the carry and the replace is waiting for the gate"
    return out[0]


# --------------------------------------------------------------------------- #
#  the behaviour: a save during the hold waits and lands in the new file
# --------------------------------------------------------------------------- #
def test_a_settings_save_started_during_the_hold_waits_and_lands_in_the_new_file(world, monkeypatch):
    tmp_path, live, working = world
    real_swap = merge.swap_in_corpus
    saver: dict = {}

    def swap_with_a_save_in_flight(w, t, **kw):
        def save() -> None:
            kv_store.kv_set_json("settings.saved_during_the_hold", {"v": 7})

        saver["thread"] = threading.Thread(target=save, name="oo-test-saver")
        saver["thread"].start()
        _wait_for_waiters(1)  # it is at the gate, not past it
        assert "settings.saved_during_the_hold" not in _rows(live), "the save ran inside the hold"
        real_swap(w, t, **kw)

    report: dict = {}
    monkeypatch.setattr(merge, "swap_in_corpus", swap_with_a_save_in_flight)
    merge._carry_and_swap(working, live, report)
    saver["thread"].join(_PATIENCE_S)

    assert not saver["thread"].is_alive()
    assert _rows(live)["settings.saved_during_the_hold"] == '{"v": 7}', "the save was thrown away by the replace"
    assert kv_store.kv_get_json("settings.saved_during_the_hold") == {"v": 7}
    assert report["settings_carry"]["gate_held"] is True


def test_a_value_the_old_file_held_is_not_served_from_the_cache_after_the_swap(world):
    """``kv_invalidate`` is what keeps the value the OLD file held from being served for the life of the process."""
    tmp_path, live, working = world
    # 'spell.note' is not a carried key: the copy keeps its own value, so the live file's value is exactly what a stale cache would serve
    for path, who in ((live, "live"), (working, "copy")):
        con = sqlite3.connect(path)
        con.execute("INSERT INTO app_state VALUES ('spell.note', ?, 'x')", (f'{{"from": "{who}"}}',))
        con.commit()
        con.close()
    kv_store.kv_invalidate()
    assert kv_store.kv_get_json("spell.note") == {"from": "live"}  # now in the cache

    merge._carry_and_swap(working, live, {})

    assert kv_store.kv_get_json("spell.note") == {"from": "copy"}, "the cache kept serving what the replaced file held"


# --------------------------------------------------------------------------- #
#  the hold: acquired before the carry, kept to the end of the swap, released on every exit
# --------------------------------------------------------------------------- #
def test_the_gate_is_held_by_the_restore_thread_from_the_carry_to_the_end_of_the_swap_and_free_after(world, monkeypatch):
    tmp_path, live, working = world
    held_at: dict[str, bool] = {}
    real_carry = merge._carry_live_settings

    def carry(w):
        held_at["carry"] = not _free_from_another_thread()
        return real_carry(w)

    def swap(w, t, **kw):
        held_at["swap"] = not _free_from_another_thread()

    def invalidate(*a):
        held_at["invalidate"] = not _free_from_another_thread()

    monkeypatch.setattr(merge, "_carry_live_settings", carry)
    monkeypatch.setattr(merge, "swap_in_corpus", swap)
    monkeypatch.setattr(kv_store, "kv_invalidate", invalidate)

    merge._carry_and_swap(working, live, {})

    assert held_at == {"carry": True, "swap": True, "invalidate": True}
    assert _free_from_another_thread(), "the gate stayed held after the restore"


def test_the_gate_is_reentrant_for_everything_the_restore_thread_does_inside_the_hold(world, monkeypatch):
    """(a) of the review: something between the carry and the replace that takes the gate again on this thread must not wait on the hold."""
    tmp_path, live, working = world
    seen: dict = {}

    def swap(w, t, **kw):
        with write_lock(timeout=0.5):  # a bounded nested take: a non-reentrant gate would raise WriteGateBusy here
            seen["nested"] = True

    monkeypatch.setattr(merge, "swap_in_corpus", swap)
    assert _run_with_a_deadline(lambda: merge._carry_and_swap(working, live, {})) is None
    assert seen == {"nested": True}


def test_the_real_swap_inside_the_hold_finishes_with_no_thread_waiting_on_the_gate(world):
    """(a) of the review, from the other side: the real ``swap_in_corpus`` (the generation window, the side files, the replace) under the
    hold must finish. A step that took the gate on another thread and waited for it would never return; the deadline makes that a failure."""
    tmp_path, live, working = world
    con = sqlite3.connect(working)
    con.execute("INSERT INTO app_state VALUES ('settings.only_in_the_copy', '{}', 'x')")
    con.commit()
    con.close()
    before = library_generation.current()
    report: dict = {}

    err = _run_with_a_deadline(lambda: merge._carry_and_swap(working, live, report))

    assert err is None, repr(type(err))
    assert not working.exists()
    assert "settings.only_in_the_copy" in _rows(live)
    assert library_generation.current() > before
    assert _free_from_another_thread()


def test_a_restore_that_cannot_get_the_gate_refuses_and_touches_nothing(world, monkeypatch):
    tmp_path, live, working = world
    monkeypatch.setattr(merge, "_SWAP_GATE_S", 0.2)
    calls: list[str] = []
    monkeypatch.setattr(merge, "_carry_live_settings", lambda w: calls.append("carry") or {})
    monkeypatch.setattr(merge, "swap_in_corpus", lambda *a, **k: calls.append("swap"))
    release, held = threading.Event(), threading.Event()

    def other_writer() -> None:
        with write_lock():
            held.set()
            release.wait(_PATIENCE_S)

    t = threading.Thread(target=other_writer)
    t.start()
    assert held.wait(_PATIENCE_S)
    try:
        before = (_rows(live), working.exists())
        with pytest.raises(merge.RestoreRefused) as refused:
            merge._carry_and_swap(working, live, {})
        assert "nothing was written to your corpus" in str(refused.value)
        assert calls == [], "the carry or the swap ran without the gate"
        assert (_rows(live), working.exists()) == before
    finally:
        release.set()
        t.join(_PATIENCE_S)
    assert _free_from_another_thread()


def test_the_gate_is_let_go_when_the_swap_refuses_or_fails(world, monkeypatch):
    tmp_path, live, working = world
    invalidated: list[int] = []
    monkeypatch.setattr(kv_store, "kv_invalidate", lambda *a: invalidated.append(1))

    def busy(w, t, **kw):
        raise library_generation.LibraryBusy("still being opened")

    monkeypatch.setattr(merge, "swap_in_corpus", busy)
    with pytest.raises(merge.RestoreRefused):
        merge._carry_and_swap(working, live, {})
    assert _free_from_another_thread()

    def broken(w, t, **kw):
        raise OSError("replace failed")

    monkeypatch.setattr(merge, "swap_in_corpus", broken)
    with pytest.raises(OSError, match="replace failed"):
        merge._carry_and_swap(working, live, {})
    assert _free_from_another_thread()
    assert len(invalidated) == 2, "a swap that failed part-way must not leave the old file's values in the cache"


def test_with_the_gate_switched_off_the_swap_goes_on_and_the_report_says_it_was_not_held(world, monkeypatch):
    tmp_path, live, working = world
    monkeypatch.setenv("OO_WRITE_GATE", "0")
    report: dict = {}

    merge._carry_and_swap(working, live, report)

    assert report["settings_carry"]["gate_held"] is False
    assert not working.exists()


# --------------------------------------------------------------------------- #
#  the structure: the order in the source, so the hold cannot drift to the wrong side of the checkpoint
# --------------------------------------------------------------------------- #
def _func(name: str) -> ast.FunctionDef:
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _lines(node: ast.AST, name: str) -> list[int]:
    return sorted(
        c.lineno
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and (getattr(c.func, "id", None) == name or getattr(c.func, "attr", None) == name)
    )


def test_the_restore_takes_the_gate_after_the_checkpoint_and_never_carries_or_swaps_outside_the_hold():
    run = _func("run_restore")
    quiet, ckpt, hold = (_lines(run, "wait_for_quiescence"), _lines(run, "_checkpoint_before_swap"), _lines(run, "_carry_and_swap"))
    assert len(quiet) == len(ckpt) == len(hold) == 1
    assert quiet[0] < ckpt[0] < hold[0], "the checkpoint runs on its own thread and needs the gate: the hold must follow it"
    assert _lines(run, "_carry_live_settings") == [] and _lines(run, "swap_in_corpus") == [], "outside the hold, the gap is open again"


def test_the_hold_wraps_the_carry_and_the_swap_and_empties_the_cache_in_a_finally():
    fn = _func("_carry_and_swap")
    enter, carry, swap, inval = (
        _lines(fn, "enter_context"), _lines(fn, "_carry_live_settings"), _lines(fn, "swap_in_corpus"), _lines(fn, "kv_invalidate")
    )
    assert len(enter) == len(carry) == len(swap) == len(inval) == 1
    assert enter[0] < carry[0] < swap[0] < inval[0]
    assert _lines(fn, "_checkpoint_before_swap") == [], "a checkpoint inside the hold would wait on the thread that needs the gate"
    in_finally = [
        c.lineno
        for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        for s in t.finalbody
        for c in ast.walk(s)
        if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "kv_invalidate"
    ]
    assert in_finally == inval, "kv_invalidate must run on every exit from the swap"
