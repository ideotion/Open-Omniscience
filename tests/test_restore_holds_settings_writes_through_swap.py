"""A restore holds SETTINGS WRITES from the settings carry to the replace, so a settings save in between lands in the NEW file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_carry_live_settings`` copies the live ``app_state`` rows into the working copy just before the swap. A settings save
(``kv_set_json``) holds neither the corpus lease nor a guard of the swap window, so one that committed between the carry's read and
the replace returned success, was served from the in-process cache, and was gone at the next start. ``_carry_and_swap`` closes the gap
with ``kv_store.hold_writes``: a save that starts meanwhile waits and lands in the file that is live afterwards (or is refused with
nothing written), the saves already in flight are waited for first, and the settings cache is emptied before the hold ends.

WHY NOT THE WRITE GATE (the independent read's block, measured): the swap's file steps wait for every handle on the live file to
close, and some threads check a connection out FIRST and then wait for the gate. A restore that held the gate made the swap wait for
a thread that waited for the swap. The hold takes no lock the gate or the corpus knows about; ``test_the_gate_stays_free_...`` pins it.
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


def _gate_is_free_for_another_thread() -> bool:
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


def _writes_are_held_by_this_thread() -> bool:
    return kv_store._hold_by == threading.get_ident()


def _run_with_a_deadline(fn) -> BaseException | None:
    """Run ``fn`` on a thread that is given up on after ``_PATIENCE_S``: a hang fails the test instead of hanging the suite."""
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
    assert out, "the restore thread did not finish"
    return out[0]


# --------------------------------------------------------------------------- #
#  the behaviour: a save during the hold waits and lands in the new file
# --------------------------------------------------------------------------- #
def test_a_settings_save_started_during_the_hold_waits_and_lands_in_the_new_file(world, monkeypatch):
    tmp_path, live, working = world
    real_swap = merge.swap_in_corpus
    saver: dict = {}

    def swap_with_a_save_in_flight(w, t, **kw):
        saver["thread"] = threading.Thread(
            target=lambda: kv_store.kv_set_json("settings.saved_during_the_hold", {"v": 7}), name="oo-test-saver"
        )
        saver["thread"].start()
        time.sleep(0.5)  # long enough for it to have run to the end if the hold did not stop it
        assert "settings.saved_during_the_hold" not in _rows(live), "the save ran inside the hold"
        assert saver["thread"].is_alive() and kv_store._inflight == 0, "the save is not waiting at the door"
        real_swap(w, t, **kw)

    report: dict = {}
    monkeypatch.setattr(merge, "swap_in_corpus", swap_with_a_save_in_flight)
    merge._carry_and_swap(working, live, report)
    saver["thread"].join(_PATIENCE_S)

    assert not saver["thread"].is_alive()
    assert _rows(live)["settings.saved_during_the_hold"] == '{"v": 7}', "the save was thrown away by the replace"
    assert kv_store.kv_get_json("settings.saved_during_the_hold") == {"v": 7}


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


def test_a_reader_that_began_before_the_replace_cannot_refill_the_cache_with_the_old_value(world, monkeypatch):
    """The independent read's S1, probed: a reader that missed the cache and read the OLD file just before the replace stored its value
    AFTER the invalidation."""
    tmp_path, live, working = world
    for path, who in ((live, "live"), (working, "copy")):
        con = sqlite3.connect(path)
        con.execute("INSERT INTO app_state VALUES ('spell.note', ?, 'x')", (f'{{"from": "{who}"}}',))
        con.commit()
        con.close()
    kv_store.kv_invalidate()
    read_old, go = threading.Event(), threading.Event()
    real_read = kv_store._read_value

    def slow_read(path, key, *, read_only):
        value = real_read(path, key, read_only=read_only)  # the OLD file's value, read now
        read_old.set()
        go.wait(_PATIENCE_S)  # ... and stored only after the swap and the invalidation
        return value

    monkeypatch.setattr(kv_store, "_read_value", slow_read)
    got: list = []
    reader = threading.Thread(target=lambda: got.append(kv_store.kv_get_json("spell.note")))
    reader.start()
    assert read_old.wait(_PATIENCE_S)
    merge._carry_and_swap(working, live, {})
    monkeypatch.setattr(kv_store, "_read_value", real_read)
    go.set()
    reader.join(_PATIENCE_S)

    assert got == [{"from": "live"}]  # what it read is what it returns ...
    assert kv_store.kv_get_json("spell.note") == {"from": "copy"}, "... but it must not be what the next reader is served"


# --------------------------------------------------------------------------- #
#  the hold: taken before the carry, kept to the end of the swap, released on every exit
# --------------------------------------------------------------------------- #
def test_writes_are_held_from_the_carry_to_the_end_of_the_swap_and_free_after(world, monkeypatch):
    tmp_path, live, working = world
    held_at: dict[str, bool] = {}
    real_carry = merge._carry_live_settings

    def carry(w):
        held_at["carry"] = _writes_are_held_by_this_thread()
        return real_carry(w)

    monkeypatch.setattr(merge, "_carry_live_settings", carry)
    monkeypatch.setattr(merge, "swap_in_corpus", lambda w, t, **k: held_at.update(swap=_writes_are_held_by_this_thread()))
    monkeypatch.setattr(kv_store, "kv_invalidate", lambda *a: held_at.update(invalidate=_writes_are_held_by_this_thread()))

    merge._carry_and_swap(working, live, {})

    assert held_at == {"carry": True, "swap": True, "invalidate": True}
    assert kv_store._hold_by is None, "the hold outlived the restore"


def test_the_gate_stays_free_during_the_swap_so_a_thread_holding_a_handle_can_let_go(world, monkeypatch):
    """The independent read's B1, from the Windows side: the replace waits for a handle that a thread holds, and that thread must take the
    gate to be refused as stale and let go. With the gate held by the restore the replace would wait for a thread that waits for it."""
    tmp_path, live, working = world
    real_replace = merge._replace_live_corpus
    handle_released = threading.Event()
    seen: dict = {}

    def replace_waiting_for_the_handle(w, t, **kw):
        def holder() -> None:  # a session that read first and now needs the gate to write (and be refused)
            with write_lock(timeout=5):
                handle_released.set()

        th = threading.Thread(target=holder)
        th.start()
        seen["released"] = handle_released.wait(10)  # the real retry loop would be waiting here
        th.join(_PATIENCE_S)
        return real_replace(w, t, **kw)

    monkeypatch.setattr(merge, "_replace_live_corpus", replace_waiting_for_the_handle)

    err = _run_with_a_deadline(lambda: merge._carry_and_swap(working, live, {}))

    assert err is None, repr(err)
    assert seen["released"] is True, "the gate was not free inside the hold: a handle holder could not take it to let go"
    assert not working.exists()


def test_the_real_swap_inside_the_hold_finishes(world):
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
    assert report["settings_carry"]["carried"] >= 0
    assert _gate_is_free_for_another_thread() and kv_store._hold_by is None


def test_a_save_in_flight_is_waited_for_before_the_carry(world, monkeypatch):
    """A save queued behind the gate is counted as in flight: the carry reads after it has landed, so the carry carries it."""
    tmp_path, live, working = world
    release, held = threading.Event(), threading.Event()

    def other_writer() -> None:
        with write_lock():
            held.set()
            release.wait(_PATIENCE_S)

    blocker = threading.Thread(target=other_writer)
    blocker.start()
    assert held.wait(_PATIENCE_S)
    saver = threading.Thread(target=lambda: kv_store.kv_set_json("settings.queued_behind_the_gate", {"v": 9}))
    saver.start()
    deadline = time.monotonic() + _PATIENCE_S
    while kv_store._inflight < 1:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    threading.Timer(0.3, release.set).start()  # the gate frees while the restore is waiting for the save

    err = _run_with_a_deadline(lambda: merge._carry_and_swap(working, live, {}))
    saver.join(_PATIENCE_S)
    blocker.join(_PATIENCE_S)

    assert err is None, repr(err)
    assert _rows(live)["settings.queued_behind_the_gate"] == '{"v": 9}', "the save in flight was not carried"


def test_a_restore_that_cannot_start_its_hold_refuses_and_touches_nothing(world, monkeypatch):
    tmp_path, live, working = world
    monkeypatch.setattr(merge, "_SWAP_SETTINGS_HOLD_S", 0.2)
    calls: list[str] = []
    monkeypatch.setattr(merge, "_carry_live_settings", lambda w: calls.append("carry") or {})
    monkeypatch.setattr(merge, "swap_in_corpus", lambda *a, **k: calls.append("swap"))
    release, held = threading.Event(), threading.Event()

    def other_writer() -> None:
        with write_lock():
            held.set()
            release.wait(_PATIENCE_S)

    blocker = threading.Thread(target=other_writer)
    blocker.start()
    assert held.wait(_PATIENCE_S)
    saver = threading.Thread(target=lambda: kv_store.kv_set_json("settings.stuck", {"v": 1}))
    saver.start()
    while kv_store._inflight < 1:
        time.sleep(0.01)
    try:
        before = (_rows(live), working.exists())
        with pytest.raises(merge.RestoreRefused) as refused:
            merge._carry_and_swap(working, live, {})
        assert "nothing was written to your corpus" in str(refused.value)
        assert calls == [], "the carry or the swap ran without the hold"
        assert (_rows(live), working.exists()) == before
        assert kv_store._hold_by is None, "a refused hold must not stay held"
    finally:
        release.set()
        saver.join(_PATIENCE_S)
        blocker.join(_PATIENCE_S)


def test_the_hold_is_let_go_when_the_swap_refuses_or_fails(world, monkeypatch):
    tmp_path, live, working = world
    invalidated: list[int] = []
    monkeypatch.setattr(kv_store, "kv_invalidate", lambda *a: invalidated.append(1))

    def busy(w, t, **kw):
        raise library_generation.LibraryBusy("still being opened")

    monkeypatch.setattr(merge, "swap_in_corpus", busy)
    with pytest.raises(merge.RestoreRefused):
        merge._carry_and_swap(working, live, {})
    assert kv_store._hold_by is None

    def broken(w, t, **kw):
        raise OSError("replace failed")

    monkeypatch.setattr(merge, "swap_in_corpus", broken)
    with pytest.raises(OSError, match="replace failed"):
        merge._carry_and_swap(working, live, {})
    assert kv_store._hold_by is None
    assert len(invalidated) == 2, "a swap that failed part-way must not leave the old file's values in the cache"


def test_the_hold_does_not_depend_on_the_write_gate(world, monkeypatch):
    """With ``OO_WRITE_GATE=0`` the single-writer gate does nothing; the settings hold still holds."""
    tmp_path, live, working = world
    monkeypatch.setenv("OO_WRITE_GATE", "0")
    real_swap = merge.swap_in_corpus
    saver: dict = {}

    def swap(w, t, **kw):
        saver["t"] = threading.Thread(target=lambda: kv_store.kv_set_json("settings.gate_off", {"v": 1}))
        saver["t"].start()
        time.sleep(0.3)
        assert "settings.gate_off" not in _rows(live)
        real_swap(w, t, **kw)

    monkeypatch.setattr(merge, "swap_in_corpus", swap)
    merge._carry_and_swap(working, live, {})
    saver["t"].join(_PATIENCE_S)
    assert _rows(live)["settings.gate_off"] == '{"v": 1}'


def test_the_refusal_is_the_restores_own_refusal_so_the_journal_reads_it_as_refused():
    assert issubclass(merge.RestoreRefused, merge.RestoreAborted)
    src = ast.unparse(_func("_carry_and_swap"))
    assert src.count("RestoreRefused(") == 2  # the hold and the library window; the generic handlers keep both as errors, not cancellations


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


def test_the_restore_holds_after_the_checkpoint_and_never_carries_or_swaps_outside_the_hold():
    run = _func("run_restore")
    quiet, ckpt, hold = (_lines(run, "wait_for_quiescence"), _lines(run, "_checkpoint_before_swap"), _lines(run, "_carry_and_swap"))
    assert len(quiet) == len(ckpt) == len(hold) == 1
    assert quiet[0] < ckpt[0] < hold[0]
    assert _lines(run, "_carry_live_settings") == [] and _lines(run, "swap_in_corpus") == [], "outside the hold, the gap is open again"


def test_the_hold_wraps_the_carry_and_the_swap_takes_no_gate_and_empties_the_cache_in_a_finally():
    fn = _func("_carry_and_swap")
    enter, carry, swap, inval = (
        _lines(fn, "enter_context"), _lines(fn, "_carry_live_settings"), _lines(fn, "swap_in_corpus"), _lines(fn, "kv_invalidate")
    )
    assert len(enter) == len(carry) == len(swap) == len(inval) == 1
    assert enter[0] < carry[0] < swap[0] < inval[0]
    assert _lines(fn, "hold_writes") != [] and _lines(fn, "write_lock") == [], "the single-writer gate is NOT what is held here"
    assert _lines(fn, "_checkpoint_before_swap") == []
    in_finally = [
        c.lineno
        for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        for s in t.finalbody
        for c in ast.walk(s)
        if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "kv_invalidate"
    ]
    assert in_finally == inval, "kv_invalidate must run on every exit from the swap"
