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
import os
import sqlite3
import threading
import time

import pytest

from src.config import kv_store
from src.database.writer import write_gate, write_lock

_PATIENCE_S = 30.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    live = tmp_path / "open_omniscience.db"
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    kv_store.kv_invalidate()
    yield live
    kv_store.kv_invalidate()


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
    assert kv_store._inflight == 0, "a refused save must not stay counted as in flight"


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
    assert kv_store._inflight == 0


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
    assert kv_store._hold_by is None and kv_store._inflight == 0
    kv_store.kv_set_json("settings.after", {"v": 1})  # and a save is not made to wait


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
