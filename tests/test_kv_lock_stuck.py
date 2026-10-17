"""R144(b): the stuck-lock detector of the settings hold (``kv_store._hold_lock``).

It REFUSES and NAMES (operation, kind of thread, UTC time; never a thread name) and never replaces the lock; it decides from WHERE the owner is
(no frame of the code that takes the lock on its stack, or no thread at all), so it has no timeout and no number. The lock is never touched to
look at it. Design: /mnt/project-files/fix-source-qualification/design-hold-lock-stuck-2026-10-16.md."""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from src.config import kv_store

_SECRET_NAME = "SECRET-REQUEST-CHOSEN-NAME"


@pytest.fixture
def lock(monkeypatch):
    """A fresh RLock and Condition for the module: a lock that a test leaves owned by a dead thread can never be released, so the real one is not used."""
    fresh = threading.RLock()
    monkeypatch.setattr(kv_store, "_hold_lock", fresh)
    monkeypatch.setattr(kv_store, "_hold", threading.Condition(fresh))
    monkeypatch.setattr(kv_store, "_hold_by", None)
    monkeypatch.setattr(kv_store, "_inflight", set())
    monkeypatch.setattr(kv_store, "_sections", {})
    return fresh


def _meets_the_stuck_lock(lock, call, *, operation: str | None):
    """Leave ``lock`` held by a thread that ends, then run ``call`` where a hang cannot take the suite with it: on a daemon thread that is
    given 10 s. Returns the exception it raised. Without the detector the call waits for ever on a lock nobody will release, so a missing
    check is a red test and not a stuck run. The asking thread is started BEFORE the owner ends: the system hands a dead thread's ident to the
    next thread it starts, and a thread that has the owner's ident re-enters the RLock (the one case the detector cannot see, and a reason
    to read this test as a statement about OTHER threads)."""
    raised: list[BaseException] = []
    go = threading.Event()

    def run() -> None:
        go.wait(10)
        try:
            call()
        except BaseException as exc:  # noqa: BLE001 - what the thread raised is the result
            raised.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    owner = _leave_it_held(lock, operation=operation)
    go.set()
    t.join(10)
    assert not t.is_alive(), "the call is waiting for ever on the stuck lock: nothing refused it"
    assert raised, "the call returned without meeting the stuck lock"
    return raised[0], owner


def _leave_it_held(lock, *, operation: str | None, name: str = _SECRET_NAME) -> int:
    """A thread that takes ``lock`` outside any section and ends without letting go. Returns its ident."""
    box: list[int] = []

    def run() -> None:
        if operation is not None:
            kv_store._sections[threading.get_ident()] = (operation, 1_700_000_000.0)  # noqa: SLF001
        lock.acquire()
        box.append(threading.get_ident())

    t = threading.Thread(target=run, name=name)
    t.start()
    t.join()
    return box[0]


def test_repr_of_an_rlock_still_names_its_owner_on_this_python():
    """The detector reads the owner from ``repr``; a Python that words it differently makes this red, not the detector silently blind."""
    lk = threading.RLock()
    assert kv_store._OWNER_OF_REPR.search(repr(lk)).group(1) == "0"  # noqa: SLF001
    with lk:
        assert int(kv_store._OWNER_OF_REPR.search(repr(lk)).group(1)) == threading.get_ident()  # noqa: SLF001


def test_a_save_meets_a_lock_left_held_by_a_thread_that_ended_and_is_refused_with_the_name(lock):
    def save() -> None:
        with kv_store._write_slot():  # noqa: SLF001
            raise AssertionError("the section must not be entered")

    exc, owner = _meets_the_stuck_lock(lock, save, operation="settings save")
    assert isinstance(exc, kv_store.KvLockStuck), repr(exc)
    assert (exc.operation, exc.thread_kind, exc.since_utc) == ("settings save", "a thread that no longer exists", "2023-11-14 22:13:20 UTC")
    assert exc.lock == "kv_store._hold"
    assert _SECRET_NAME not in str(exc) and str(owner) not in str(exc), "a thread name or ident is request-chosen or meaningless to the reader"
    assert "Nothing was written" in str(exc) and "Restart Open Omniscience" in str(exc)
    assert isinstance(exc, kv_store.KvWriteRefused), "the API already answers this as a 503 with the text as the detail"
    assert not kv_store._inflight, "a refused save is not counted as in flight"  # noqa: SLF001


def test_a_restore_hold_meets_it_and_holds_nothing(lock):
    def hold() -> None:
        with kv_store.hold_writes(0):
            raise AssertionError("the hold must not be taken")

    exc, _owner = _meets_the_stuck_lock(lock, hold, operation="restore hold")
    assert isinstance(exc, kv_store.KvLockStuck), repr(exc)
    assert exc.operation == "restore hold"
    assert kv_store._hold_by is None, "nothing was held, so nothing is left set"  # noqa: SLF001


def test_the_lock_is_not_replaced_and_not_touched(lock):
    owner = _leave_it_held(lock, operation="settings save")
    for _ in range(3):
        with pytest.raises(kv_store.KvLockStuck):
            kv_store._refuse_if_stuck()  # noqa: SLF001
    assert kv_store._hold_lock is lock, "never self-heals by replacing the lock"  # noqa: SLF001
    assert f"owner={owner} count=1" in repr(lock), "looking at it does not take it, release it or count it"


def test_an_owner_that_is_not_recorded_is_named_as_not_recorded_not_guessed(lock):
    _leave_it_held(lock, operation=None)
    with pytest.raises(kv_store.KvLockStuck) as err:
        kv_store._refuse_if_stuck()  # noqa: SLF001
    assert err.value.operation is None and err.value.since_utc is None
    assert "operation not recorded" in str(err.value) and "time not recorded" in str(err.value)


def test_a_live_worker_outside_the_sections_and_the_main_thread_are_told_apart(lock):
    release = threading.Event()
    taken = threading.Event()

    def worker() -> None:
        with lock:
            taken.set()
            release.wait(10)

    t = threading.Thread(target=worker)
    t.start()
    assert taken.wait(10)
    try:
        with pytest.raises(kv_store.KvLockStuck) as err:
            kv_store._refuse_if_stuck()  # noqa: SLF001
        assert err.value.thread_kind == "worker thread"
    finally:
        release.set()
        t.join()
    # the main thread owns it outside a section: seen from a worker
    lock.acquire()
    box: list[BaseException] = []

    def asker() -> None:
        try:
            kv_store._refuse_if_stuck()  # noqa: SLF001
        except kv_store.KvLockStuck as e:
            box.append(e)

    a = threading.Thread(target=asker)
    a.start()
    a.join()
    lock.release()
    assert box and box[0].thread_kind == "main thread"


def test_the_owner_asking_for_its_own_lock_is_never_stuck(lock):
    with lock:
        kv_store._refuse_if_stuck()  # noqa: SLF001 - re-entering is what an RLock is for


def test_a_holder_inside_the_section_is_waited_for_not_reported(lock, monkeypatch):
    """The owner is in ``hold_writes``' drain loop (``not _inflight`` runs under the lock, in the section's frame) when the asker looks."""
    inside = threading.Event()
    go = threading.Event()

    class Gate(set):
        def __len__(self) -> int:
            inside.set()
            go.wait(10)
            return 0

    monkeypatch.setattr(kv_store, "_inflight", Gate())
    holder = threading.Thread(target=lambda: kv_store.hold_writes(5.0).__enter__())
    holder.start()
    assert inside.wait(10), "the holder is in the drain loop with the lock"
    result: list[object] = []

    def ask() -> None:
        try:
            kv_store._refuse_if_stuck()  # noqa: SLF001
            result.append("not stuck")
        except kv_store.KvLockStuck as e:  # pragma: no cover - the failure this test exists for
            result.append(e)

    a = threading.Thread(target=ask)
    a.start()
    a.join(10)
    go.set()
    holder.join(10)
    assert result == ["not stuck"], result


def test_a_lock_that_is_not_a_plain_rlock_is_not_examined(monkeypatch):
    """The suite wraps the lock to plant interrupts; a wrapper whose repr names no owner makes the detector silent, never wrong."""

    class Wrapper:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(kv_store, "_hold_lock", Wrapper())
    kv_store._refuse_if_stuck()  # noqa: SLF001


def test_the_detector_has_no_timeout_and_no_number():
    """What makes an owner stuck is where it is, not how long: no clock reads, no deadline, no figure in the functions that decide."""
    tree = ast.parse(Path(kv_store.__file__).read_text(encoding="utf-8"))
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in {"_stuck_owner", "_refuse_if_stuck"}):
        src = ast.unparse(fn)
        assert "monotonic" not in src and "deadline" not in src and "timeout" not in src, fn.name
        assert not [c for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, float)], fn.name


def test_two_looks_that_find_different_owners_are_not_a_stuck_lock(monkeypatch):
    """An owner that left and another that entered between the looks is a lock in use. MUTATION TARGET: the comparison of the two looks."""
    looks = iter([(11, ("settings save", 1.0)), (12, ("settings save", 1.0)), (11, ("settings save", 2.0))])
    monkeypatch.setattr(kv_store, "_stuck_owner", lambda: next(looks))
    kv_store._refuse_if_stuck()  # noqa: SLF001 - owner 11 then 12
    looks = iter([(11, ("settings save", 1.0)), (11, ("settings save", 2.0))])
    monkeypatch.setattr(kv_store, "_stuck_owner", lambda: next(looks))
    kv_store._refuse_if_stuck()  # noqa: SLF001 - the same owner, a different entry: a second visit, not the same section left held
    looks = iter([(11, ("settings save", 1.0)), None])
    monkeypatch.setattr(kv_store, "_stuck_owner", lambda: next(looks))
    kv_store._refuse_if_stuck()  # noqa: SLF001 - gone on the second look
