"""Settings writes can be HELD by a restore: a save waits (bounded) and lands in the new file, or is refused with nothing written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``kv_store.hold_writes`` is what ``backup.merge._carry_and_swap`` holds from its read of the live settings to the replace of the
file. It takes NO lock the single-writer gate or the corpus knows about (a restore that held the gate waited for threads that wait
for it: the independent read's B1), so the properties here are about the hold itself: the saves in flight are waited for, a new save
waits at the door for ``OO_KV_WRITE_WAIT_S`` and is then refused with fixed words, the holder passes through, a thread that already
holds the gate is refused at once (it cannot wait without making the restore wait for its connection), and the suite runs with
``OO_KV_STRICT_GATE_ORDER=1`` so any caller that enters a settings write holding the gate fails a test.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from src.config import kv_store
from src.database.writer import write_gate, write_lock

_PATIENCE_S = 30.0


def _reset_hold_state() -> None:
    """Back to no hold and no write counted. A test that fails with a write counted or a hold taken would otherwise leave them for every
    later test of the session, which then refuses to start for a reason that is not theirs (one red cascading into twenty)."""
    with kv_store._hold_lock:
        kv_store._inflight.clear()
        kv_store._hold_by = None


@pytest.fixture
def store(tmp_path, monkeypatch):
    live = tmp_path / "open_omniscience.db"
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    kv_store.kv_invalidate()
    _reset_hold_state()
    real_inflight = kv_store._inflight  # the real set: a test may have patched the module's name by the time this runs
    yield live
    kv_store.kv_invalidate()
    leaked = (set(real_inflight), kv_store._hold_by)
    _reset_hold_state()  # so a leak fails the test that made it, not the twenty after it
    assert leaked == (set(), None), "the test ended with a settings write counted in flight or a hold taken"


def test_the_reset_helper_clears_a_hold_and_a_write_a_failed_test_left():
    kv_store._inflight.add(object())
    kv_store._hold_by = threading.get_ident()
    _reset_hold_state()
    assert not kv_store._inflight and kv_store._hold_by is None


def test_the_store_fixture_resets_before_and_after_the_test():
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "store").body
    yield_at = next(i for i, st in enumerate(body) if isinstance(st, ast.Expr) and isinstance(st.value, ast.Yield))

    def calls_reset(stmts):
        return any(
            isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", "") == "_reset_hold_state"
            for st in stmts
        )

    assert calls_reset(body[:yield_at]), "the fixture must reset the hold state before the test"
    assert calls_reset(body[yield_at + 1 :]), "the fixture must reset the hold state after the test"


def _stored(live, key):
    con = sqlite3.connect(live)
    try:
        row = con.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def test_the_suite_runs_with_the_strict_gate_order_guard_on():
    assert os.environ.get("OO_KV_STRICT_GATE_ORDER") == "1", "tests/conftest.py must switch the guard on, or the audit finds nothing"


def test_a_settings_write_entered_with_the_gate_held_fails_the_suite(store):
    with write_lock(), pytest.raises(AssertionError, match="holds the single-writer gate"):
        kv_store.kv_set_json("settings.x", {"v": 1})
    with write_lock(), pytest.raises(AssertionError, match="holds the single-writer gate"):
        kv_store.kv_delete("settings.x")
    assert _stored(store, "settings.x") is None
    assert len(kv_store.STRICT_VIOLATIONS) == 2, "the violation is recorded where an `except Exception` cannot swallow it"
    kv_store.STRICT_VIOLATIONS.clear()  # provoked on purpose: the suite's fixture would otherwise fail this test


def test_an_except_exception_around_a_save_does_not_hide_the_violation(store):
    with write_lock(), contextlib.suppress(Exception):  # what thirteen callers do
        kv_store.kv_set_json("settings.y", {"v": 1})
    assert kv_store.STRICT_VIOLATIONS
    kv_store.STRICT_VIOLATIONS.clear()


def test_without_a_hold_a_write_goes_straight_through_and_fills_the_cache(store):
    kv_store.kv_set_json("settings.a", {"v": 1})
    assert _stored(store, "settings.a") == '{"v": 1}' and kv_store.kv_get_json("settings.a") == {"v": 1}
    kv_store.kv_delete("settings.a")
    assert _stored(store, "settings.a") is None and kv_store.kv_get_json("settings.a") is None


def test_the_hold_waits_for_a_write_in_flight_and_a_hold_of_zero_does_not_wait(store):
    with kv_store._write_slot():  # a save somewhere between its start and its end
        with pytest.raises(kv_store.KvWriteBusy), kv_store.hold_writes(0):
            pass
        assert kv_store._hold_by is None, "a hold that could not start must hold nothing"
    with kv_store.hold_writes(0):  # nothing in flight now
        assert kv_store._hold_by == threading.get_ident()
    assert kv_store._hold_by is None


def test_the_hold_starts_once_the_write_in_flight_ends(store):
    slot = kv_store._write_slot()
    slot.__enter__()
    threading.Timer(0.3, lambda: slot.__exit__(None, None, None)).start()
    start = time.monotonic()
    with kv_store.hold_writes(_PATIENCE_S):
        assert time.monotonic() - start >= 0.25


def test_a_save_during_the_hold_waits_and_lands_after_it(store):
    done: list[float] = []
    with kv_store.hold_writes(1):
        t = threading.Thread(target=lambda: (kv_store.kv_set_json("settings.waits", {"v": 2}), done.append(time.monotonic())))
        t.start()
        time.sleep(0.3)
        assert not done and _stored(store, "settings.waits") is None
        released = time.monotonic()
    t.join(_PATIENCE_S)
    assert done and done[0] >= released and _stored(store, "settings.waits") == '{"v": 2}'


def test_a_save_that_waits_too_long_is_refused_with_nothing_written_in_fixed_words(store, monkeypatch):
    monkeypatch.setattr(kv_store, "KV_WRITE_WAIT_S", 0.2)
    errors: list[BaseException] = []

    def save() -> None:
        try:
            kv_store.kv_set_json("settings.refused", {"v": 3})
        except BaseException as exc:  # noqa: BLE001 - handed to the test
            errors.append(exc)

    with kv_store.hold_writes(1):
        t = threading.Thread(target=save)
        t.start()
        t.join(_PATIENCE_S)
    assert len(errors) == 1 and isinstance(errors[0], kv_store.KvWriteRefused)
    assert "nothing was written" in str(errors[0]) and str(errors[0]) == kv_store._REFUSED_TEXT
    assert _stored(store, "settings.refused") is None
    assert not kv_store._inflight, "a refused save must not stay counted as in flight"


class _InterruptedAdd(set):
    """A set whose ``add`` is interrupted (as a signal handler's KeyboardInterrupt is, between two statements of the slot): after the
    token is in (``after=True``) or before it is (``after=False``)."""

    def __init__(self, *, after: bool):
        super().__init__()
        self._after = after

    def add(self, item):
        if self._after:
            super().add(item)
        raise KeyboardInterrupt


@pytest.mark.parametrize("after", [True, False], ids=["after the write was counted", "before the write was counted"])
def test_an_interrupt_inside_the_slot_neither_leaks_a_count_nor_releases_another_writes(store, monkeypatch, after):
    """The count is one ``add`` and the release one lock-free ``remove`` of the write's own token (a KeyError for a token never counted is
    caught): an interrupt that lands after the add leaves nothing counted (a leaked count would make every later hold refuse to start
    until a restart), and one that lands before it releases nothing (a decrement of a write that was never counted would let a hold
    start with another save still writing the old file). This pins the contract of the set (a plain integer fails it by a TypeError,
    not by an ordering); the window that really leaks under signals is the release's lock, pinned by the test below. MUTATION TARGETS:
    ``remove`` replaced by ``clear``, or the release removed."""
    other = object()  # another settings write in flight on another thread
    flight = _InterruptedAdd(after=after)
    flight.update({other})
    monkeypatch.setattr(kv_store, "_inflight", flight)
    with pytest.raises(KeyboardInterrupt), kv_store._write_slot():
        pytest.fail("the slot must not be entered")
    assert set(flight) == {other}, "the interrupted write left a count, or released one that was not its own"
    with pytest.raises(kv_store.KvWriteBusy), kv_store.hold_writes(0):
        pass  # the other write is still waited for


class _InterruptedEnter:
    """``kv_store._hold_lock`` whose Nth ``with`` entry raises KeyboardInterrupt before the lock is taken, as a signal delivered while the lock
    is being taken does: before the body of the ``with`` runs."""

    def __init__(self, real, *, fail_on):
        self._real, self._fail_on, self._entries = real, fail_on, 0

    def __enter__(self):
        self._entries += 1
        if self._entries == self._fail_on:
            raise KeyboardInterrupt
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_an_interrupt_as_the_release_takes_the_lock_does_not_leave_the_write_counted(store, monkeypatch):
    """The release is a lock-free ``remove`` BEFORE the lock is taken to wake a hold: an interrupt delivered while ``with _hold_lock`` is
    entered (the second entry of a slot, the first being the count) used to arrive before the decrement and leave the write counted
    for ever, so every later hold refused to start until a restart (about 5 % of interrupted writes with real signals on CPython 3.13).
    MUTATION TARGET: the release moved back inside ``with _hold_lock``."""
    with monkeypatch.context() as patched:  # not monkeypatch.undo(): that would also revert the store fixture's DATABASE_URL
        patched.setattr(kv_store, "_hold_lock", _InterruptedEnter(kv_store._hold_lock, fail_on=2))
        with pytest.raises(KeyboardInterrupt), kv_store._write_slot():
            pass
        assert not kv_store._inflight, "the write stayed counted after its body ended"
    with kv_store.hold_writes(0):  # and a restore's hold starts at once
        assert kv_store._hold_by == threading.get_ident()


class _AfterFirstExit:
    """``kv_store._hold_lock`` that runs ``hook`` once, on the thread that left it, right after the lock is released at the end of the FIRST
    ``with`` block: the instant between a write's hold check and whatever the write does next."""

    def __init__(self, real, hook):
        self._real, self._hook, self._fired = real, hook, False

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        out = self._real.__exit__(*exc)
        if not self._fired:
            self._fired = True
            self._hook()
        return out

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_a_hold_that_starts_right_after_a_write_passed_the_check_waits_for_that_write(store, monkeypatch):
    """The count is taken in the SAME locked section as the hold check. A write that checked the hold and left the lock before counting
    itself leaves a gap in which a restore sets its hold, finds nothing in flight and starts switching the file, while the write goes
    on into the old one. The hold is started in that gap: it must find the write counted (zero budget, so it refuses at once).
    MUTATION TARGET: the ``_inflight.add(token)`` moved out of ``with _hold_lock`` (after it, or into the ``with _lock`` block). The hook fires
    on the FIRST release of ``_hold_lock`` in the slot, which is the section that checks the hold and counts; a new ``with _hold_lock`` in front of it
    would move the instant, and this test would then need the hook moved with it."""
    seen: list[str] = []

    def hold_in_the_gap() -> None:
        try:
            with kv_store.hold_writes(0):
                seen.append("held")
        except kv_store.KvWriteBusy:
            seen.append("busy")

    with monkeypatch.context() as patched:  # not monkeypatch.undo(): that would also revert the store fixture's DATABASE_URL
        patched.setattr(kv_store, "_hold_lock", _AfterFirstExit(kv_store._hold_lock, hold_in_the_gap))
        with kv_store._write_slot():
            pass
    assert seen == ["busy"], "a hold started after the write passed its check did not see the write"
    assert not kv_store._inflight and kv_store._hold_by is None


def test_a_delete_is_held_too(store):
    kv_store.kv_set_json("settings.keep", {"v": 1})
    with kv_store.hold_writes(1):
        t = threading.Thread(target=lambda: kv_store.kv_delete("settings.keep"))
        t.start()
        time.sleep(0.3)
        assert _stored(store, "settings.keep") == '{"v": 1}'
    t.join(_PATIENCE_S)
    assert _stored(store, "settings.keep") is None


def test_the_holder_itself_passes_through(store):
    with kv_store.hold_writes(1):
        kv_store.kv_set_json("settings.holder", {"v": 4})  # the restore thread, were it to save a setting, is not made to wait for itself
    assert _stored(store, "settings.holder") == '{"v": 4}'
    assert not kv_store._inflight


def test_a_thread_that_holds_the_gate_is_refused_at_once_during_a_hold(store, monkeypatch):
    """It cannot wait: a thread that holds the gate has a connection on the file the restore is about to replace."""
    monkeypatch.setenv("OO_KV_STRICT_GATE_ORDER", "0")  # this is the production behaviour; the suite's guard is tested above
    monkeypatch.setattr(kv_store, "KV_WRITE_WAIT_S", _PATIENCE_S)
    out: list = []

    def gate_holder() -> None:
        with write_lock():
            start = time.monotonic()
            try:
                kv_store.kv_set_json("settings.fast", {"v": 5})
            except kv_store.KvWriteRefused:
                out.append(time.monotonic() - start)

    with kv_store.hold_writes(1):
        t = threading.Thread(target=gate_holder)
        t.start()
        t.join(_PATIENCE_S)
    assert out and out[0] < 5, "it waited out the wait instead of being refused"
    assert not write_gate.held_by_current_thread()


def test_the_hold_is_not_reentrant_and_is_let_go_on_every_exit(store):
    with kv_store.hold_writes(1):
        with pytest.raises(RuntimeError), kv_store.hold_writes(1):
            pass
        assert kv_store._hold_by == threading.get_ident(), "a failed nested hold must not release the outer one"
    with pytest.raises(ValueError), kv_store.hold_writes(1):
        raise ValueError("body failed")
    assert kv_store._hold_by is None


def test_an_invalidation_during_a_write_keeps_its_value_out_of_the_cache(store, monkeypatch):
    """The write's own cache fill is skipped when an invalidation landed since it began: the next read goes to the file that is live."""
    real = kv_store._open

    def open_then_invalidate(path, **kw):
        kv_store.kv_invalidate()
        return real(path, **kw)

    monkeypatch.setattr(kv_store, "_open", open_then_invalidate)
    kv_store.kv_set_json("settings.skip", {"v": 6})
    assert (str(store), "settings.skip") not in kv_store._cache


def test_a_save_that_lands_after_another_keys_invalidation_does_not_leave_the_old_value_cached(store, monkeypatch):
    """The independent read's B1: the epoch is global, so ``kv_invalidate(other_key)`` during a save skipped its fill and left the OLDER value
    cached: the file said 2, the process served 1."""
    kv_store.kv_set_json("settings.k", {"v": 1})
    assert kv_store.kv_get_json("settings.k") == {"v": 1}
    real = kv_store._open

    def open_after_an_unrelated_invalidation(path, **kw):
        kv_store.kv_invalidate("some.other.key")
        return real(path, **kw)

    monkeypatch.setattr(kv_store, "_open", open_after_an_unrelated_invalidation)
    kv_store.kv_set_json("settings.k", {"v": 2})
    monkeypatch.setattr(kv_store, "_open", real)
    assert _stored(store, "settings.k") == '{"v": 2}'
    assert kv_store.kv_get_json("settings.k") == {"v": 2}, "the old value stayed cached over what was just saved"


def test_the_strict_read_does_not_fill_the_cache_after_an_invalidation(store, monkeypatch):
    con = sqlite3.connect(store)
    con.execute("INSERT INTO app_state VALUES ('spell.s', '{\"from\": \"old\"}', 'x')")
    con.commit()
    con.close()
    kv_store.kv_invalidate()
    real = kv_store._open

    def open_then_invalidate(path, **kw):
        conn = real(path, **kw)
        kv_store.kv_invalidate()  # lands while the read is in flight
        return conn

    monkeypatch.setattr(kv_store, "_open", open_then_invalidate)
    assert kv_store.kv_get_json_strict("spell.s") == {"from": "old"}
    assert (str(store), "spell.s") not in kv_store._cache


def test_a_failed_read_that_an_invalidation_overtook_is_not_held_against_the_live_file(store, monkeypatch):

    def failing(path, key, *, read_only):
        kv_store.kv_invalidate()
        raise OSError("the file was switched under it")

    monkeypatch.setattr(kv_store, "_read_value", failing)
    with pytest.raises(kv_store.KvReadError):
        kv_store.kv_get_json_checked("settings.l1")
    assert (str(store), "settings.l1") not in kv_store._failed


def _reader_that_read_the_old_file_then_waits(monkeypatch, read):
    """Run ``read()`` on a thread whose file read has finished (with the OLD value) and waits before it can fill the cache; returns a
    function that lets it go and returns the thread's result."""
    real = kv_store._read_value
    read_done, go = threading.Event(), threading.Event()
    out: dict = {}

    def slow(path, key, *, read_only):
        got = real(path, key, read_only=read_only)
        read_done.set()
        assert go.wait(_PATIENCE_S)
        return got

    monkeypatch.setattr(kv_store, "_read_value", slow)
    t = threading.Thread(target=lambda: out.setdefault("v", read()))
    t.start()
    assert read_done.wait(_PATIENCE_S)

    def release():
        go.set()
        t.join(_PATIENCE_S)
        monkeypatch.setattr(kv_store, "_read_value", real)
        return out.get("v")

    return release


def test_a_reader_that_read_the_file_before_a_save_cannot_fill_the_cache_over_it(store, monkeypatch):
    """The reader-over-writer race the first epoch left open (F1): the reader read the OLD file, the save committed and filled the cache with
    the NEW value, and the reader then stored its older one for the life of the process."""
    kv_store.kv_set_json("settings.r", {"v": 1})
    kv_store.kv_invalidate()  # cold cache: the next read goes to the file
    release = _reader_that_read_the_old_file_then_waits(monkeypatch, lambda: kv_store.kv_get_json_checked("settings.r"))
    kv_store.kv_set_json("settings.r", {"v": 2})
    assert release() == {"v": 1}, "the reader answers what it read; only the cache fill is refused"
    assert _stored(store, "settings.r") == '{"v": 2}'
    assert kv_store.kv_get_json("settings.r") == {"v": 2}, "the older value was stored over the save"


def test_a_reader_that_read_the_file_before_a_delete_cannot_bring_the_key_back(store, monkeypatch):
    kv_store.kv_set_json("settings.d", {"v": 1})
    kv_store.kv_invalidate()
    release = _reader_that_read_the_old_file_then_waits(monkeypatch, lambda: kv_store.kv_get_json_checked("settings.d"))
    kv_store.kv_delete("settings.d")
    release()
    assert kv_store.kv_get_json("settings.d") is None, "a deleted key was served from the cache"


def test_the_strict_reader_cannot_fill_the_cache_over_a_save_either(store, monkeypatch):
    kv_store.kv_set_json("settings.s", {"v": 1})
    kv_store.kv_invalidate()
    real_open = kv_store._open
    read_done, go = threading.Event(), threading.Event()

    def open_then_wait(path, **kw):
        conn = real_open(path, **kw)
        (value,) = conn.execute("SELECT value FROM app_state WHERE key = 'settings.s'").fetchone()
        conn.close()
        read_done.set()
        assert go.wait(_PATIENCE_S)
        return _Fixed(value)

    class _Fixed:
        """A connection that answers the row it read BEFORE the save, whatever the file holds now."""

        def __init__(self, value):
            self.value = value

        def execute(self, *a, **k):
            return self

        def fetchone(self):
            return (self.value,)

        def close(self):
            pass

    monkeypatch.setattr(kv_store, "_open", open_then_wait)
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("v", kv_store.kv_get_json_strict("settings.s")))
    t.start()
    assert read_done.wait(_PATIENCE_S)
    monkeypatch.setattr(kv_store, "_open", real_open)
    kv_store.kv_set_json("settings.s", {"v": 2})
    go.set()
    t.join(_PATIENCE_S)
    assert out["v"] == {"v": 1}
    assert kv_store.kv_get_json_strict("settings.s") == {"v": 2}


def test_the_cache_is_filled_inside_the_gate_so_two_saves_of_one_key_fill_in_the_order_they_committed():
    """Shape pin (the behavioural twin below makes the first save slow): inside the gate, in a ``finally`` (so a failure after the commit
    still moves the version), under the leaf lock, with the older entry dropped BEFORE the version moves."""
    import ast
    import inspect
    import textwrap

    for fn in (kv_store.kv_set_json, kv_store.kv_delete):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        gated = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.With) and any("write_lock" in ast.unparse(i.context_expr) for i in n.items)
        ]
        assert gated, f"{fn.__name__} lost its write_lock block"
        books = [
            w for g in gated for t in ast.walk(g) if isinstance(t, ast.Try) for f in t.finalbody for w in ast.walk(f)
            if isinstance(w, ast.With) and any(ast.unparse(i.context_expr) == "_lock" for i in w.items)
        ]
        assert books, f"{fn.__name__} keeps its bookkeeping outside the gate or outside a finally: two saves can fill in the wrong order"
        steps = [ast.unparse(st) for st in books[0].body]
        pop = next((i for i, st in enumerate(steps) if st.startswith("_cache.pop(")), None)
        bump = next((i for i, st in enumerate(steps) if st.startswith("_wver[path, key] =")), None)
        assert pop is not None and bump is not None, f"{fn.__name__} lost the cache drop or the version bump from its bookkeeping: {steps}"
        assert pop < bump, f"{fn.__name__} moves the version before it drops the older entry: a signal between them keeps the older entry"


def _make_close_fail(monkeypatch):
    """From now on a connection opened by the settings writer raises on ``close()`` AFTER closing: a save whose commit landed and whose
    cleanup then failed."""
    real_open = kv_store._open

    class _CloseFails:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def close(self):
            self._conn.close()
            raise OSError("close failed after the commit")

    monkeypatch.setattr(kv_store, "_open", lambda path, **k: _CloseFails(real_open(path, **k)))


def test_two_saves_of_one_key_fill_the_cache_in_the_order_they_held_the_gate_even_when_the_first_is_slow_to_fill(store, monkeypatch):
    """Deterministic: save A holds the gate first, save B queues for it. A is made slow AFTER it releases the gate, until B has saved;
    with the fill outside the gate A would then fill last and the cache would serve A's older value over B's."""
    from src.database import writer

    real = writer.write_lock
    a_in_gate, b_done = threading.Event(), threading.Event()

    @contextlib.contextmanager
    def lagging(timeout=None):
        with real(timeout):
            if threading.current_thread().name == "save-A":
                a_in_gate.set()
            yield
        if threading.current_thread().name == "save-A":
            assert b_done.wait(_PATIENCE_S)

    monkeypatch.setattr(writer, "write_lock", lagging)
    a = threading.Thread(target=lambda: kv_store.kv_set_json("settings.o", {"v": "A"}), name="save-A")

    def save_b():
        kv_store.kv_set_json("settings.o", {"v": "B"})
        b_done.set()

    b = threading.Thread(target=save_b, name="save-B")
    a.start()
    assert a_in_gate.wait(_PATIENCE_S)
    b.start()
    a.join(_PATIENCE_S)
    b.join(_PATIENCE_S)
    assert json.loads(_stored(store, "settings.o")) == {"v": "B"}
    assert kv_store.kv_get_json("settings.o") == {"v": "B"}, "the cache serves the older save over the file"


def test_a_save_whose_commit_landed_but_whose_close_failed_does_not_leave_the_older_value_cached(store, monkeypatch):
    kv_store.kv_set_json("settings.k", {"v": 1})
    assert kv_store.kv_get_json("settings.k") == {"v": 1}  # cached
    real_open = kv_store._open
    _make_close_fail(monkeypatch)
    with pytest.raises(OSError, match="close failed"):
        kv_store.kv_set_json("settings.k", {"v": 2})
    monkeypatch.setattr(kv_store, "_open", real_open)
    assert json.loads(_stored(store, "settings.k")) == {"v": 2}
    assert kv_store.kv_get_json("settings.k") == {"v": 2}, "the older value stayed cached over what the commit wrote"


def test_a_reader_that_read_before_a_commit_whose_save_then_failed_cannot_fill_its_older_value(store, monkeypatch):
    kv_store.kv_set_json("settings.r", {"v": 1})
    kv_store.kv_invalidate()
    release = _reader_that_read_the_old_file_then_waits(monkeypatch, lambda: kv_store.kv_get_json_checked("settings.r"))
    real_open = kv_store._open
    _make_close_fail(monkeypatch)
    with pytest.raises(OSError, match="close failed"):
        kv_store.kv_set_json("settings.r", {"v": 2})
    monkeypatch.setattr(kv_store, "_open", real_open)
    release()
    assert kv_store.kv_get_json("settings.r") == {"v": 2}


def test_a_failed_read_that_a_save_of_the_same_key_overtook_is_not_held_against_the_file(store, monkeypatch):
    kv_store.kv_set_json("settings.f", {"v": 1})
    kv_store.kv_invalidate()

    def failing(path, key, *, read_only):
        kv_store.kv_set_json("settings.f", {"v": 2})
        raise OSError("the read failed while the file moved on")

    monkeypatch.setattr(kv_store, "_read_value", failing)
    with pytest.raises(kv_store.KvReadError):
        kv_store.kv_get_json_checked("settings.f")
    assert (str(store), "settings.f") not in kv_store._failed


def test_concurrent_saves_of_one_key_leave_the_cache_equal_to_the_file(store):
    errors: list[str] = []

    def hammer(base):
        for i in range(25):
            kv_store.kv_set_json("settings.c", {"v": base + i})

    for _round in range(6):
        threads = [threading.Thread(target=hammer, args=(b * 100,)) for b in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(_PATIENCE_S)
        cached = kv_store.kv_get_json("settings.c")
        if cached != json.loads(_stored(store, "settings.c")):
            errors.append(f"cache {cached} != file {_stored(store, 'settings.c')}")
    assert not errors, errors


def test_a_violation_names_the_code_that_made_the_write_not_only_the_test_that_found_it(store):
    with write_lock(), contextlib.suppress(Exception):
        kv_store.kv_set_json("settings.who", {"v": 1})
    (line,) = kv_store.STRICT_VIOLATIONS
    kv_store.STRICT_VIOLATIONS.clear()
    assert "test_kv_store_write_hold.py:" in line and "in test_a_violation_names_the_code" in line, line
    assert "kv_store.py" not in line, "the caller is the frame outside kv_store"


def test_an_interrupt_during_the_drain_does_not_leave_the_hold_set(store):
    """A BaseException (the main thread's KeyboardInterrupt) while the hold waits for a write in flight: every later save would wait."""
    slot = kv_store._write_slot()
    slot.__enter__()

    class Interrupted(BaseException):
        pass

    real_wait = kv_store._hold.wait

    def interrupted(timeout=None):
        raise Interrupted

    kv_store._hold.wait = interrupted  # type: ignore[method-assign]
    try:
        with pytest.raises(Interrupted), kv_store.hold_writes(5):
            pass
    finally:
        kv_store._hold.wait = real_wait  # type: ignore[method-assign]
        slot.__exit__(None, None, None)
    assert kv_store._hold_by is None and not kv_store._inflight
    kv_store.kv_set_json("settings.after", {"v": 1})  # and a save is not made to wait


def test_an_interrupt_as_the_hold_is_set_does_not_leave_it_set(store, monkeypatch):
    """The hold is set inside the ``try``: a BaseException landing as the block that sets it ends (before the old code's ``try`` began)."""

    class Interrupted(BaseException):
        pass

    real = kv_store._hold_lock

    class Proxy:
        def __init__(self):
            self.exits = 0

        def __enter__(self):
            return real.__enter__()

        def __exit__(self, *exc):
            real.__exit__(*exc)
            self.exits += 1
            if self.exits == 1:
                raise Interrupted

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(kv_store, "_hold_lock", Proxy())
    with pytest.raises(Interrupted), kv_store.hold_writes(5):
        pass
    monkeypatch.setattr(kv_store, "_hold_lock", real)
    assert kv_store._hold_by is None
    kv_store.kv_set_json("settings.after", {"v": 1})  # and a save is not made to wait


def test_a_refused_second_hold_does_not_clear_the_first(store):
    with kv_store.hold_writes(5):
        with pytest.raises(RuntimeError), kv_store.hold_writes(5):
            pass
        assert kv_store._hold_by == threading.get_ident()
    assert kv_store._hold_by is None


def test_both_writers_go_through_the_write_slot():
    import inspect

    for fn in (kv_store.kv_set_json, kv_store.kv_delete):
        assert "_write_slot()" in inspect.getsource(fn), f"{fn.__name__} bypasses the hold"


def test_the_api_answers_a_refused_save_as_a_503_with_the_fixed_words():
    from starlette.requests import Request

    from src.api.main import app, settings_write_refused_handler

    assert kv_store.KvWriteRefused in app.exception_handlers, "the handler is not registered"
    request = Request({"type": "http", "method": "PUT", "path": "/api/settings", "headers": []})
    response = asyncio.run(settings_write_refused_handler(request, kv_store.KvWriteRefused(kv_store._REFUSED_TEXT)))
    assert response.status_code == 503
    assert kv_store._REFUSED_TEXT.encode("utf-8").decode("utf-8") in response.body.decode("utf-8")
    assert response.headers["retry-after"] == "30"
