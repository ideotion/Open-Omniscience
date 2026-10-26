"""The extraction is bracketed in the native in-flight black box, inside the lock and around the whole locked call.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/monitoring/native_inflight.py`` keeps a 128-byte memory-mapped counter file so the next boot can say which native
library was running when the process aborted. The ``lxml`` slot is wired here, in ``extract_article``, directly inside
``_LXML_LOCK`` and around ``_extract_locked``: the lock covers the parse, the walk and the release of the trees, and the
faulting frame of the 2026-10-14 abort could be any of them. A worker that is only WAITING for the lock must not count
as being in lxml, which is why the bracket is inside the lock.
"""

from __future__ import annotations

import threading

import pytest

from src.ingest import extract
from src.monitoring import native_inflight as ni

_LXML = ni.SLOTS.index("lxml")
_WAIT = 5.0


@pytest.fixture(autouse=True)
def _slots(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "_path", lambda: str(tmp_path / "diagnostics" / ni.FILE_NAME))
    ni._reset_for_tests()
    yield
    ni._reset_for_tests()


def _slot() -> tuple[int, int]:
    """(in flight, ever entered) for the lxml slot, read from the live file the way the next boot would read the bytes."""
    mm = ni._STATE["map"]
    if mm is None:
        return (0, 0)
    rec = ni.read_record(bytes(mm[:]))
    assert rec is not None
    return rec["slots"][_LXML]


def _lock_is_held_by_this_thread() -> bool:
    """The lock is an RLock, so ask from another thread: it cannot take it while this one holds it."""
    taken: list[bool] = []

    def probe() -> None:
        got = extract._LXML_LOCK.acquire(blocking=False)
        taken.append(got)
        if got:
            extract._LXML_LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(_WAIT)
    return taken == [False]


def test_the_slot_counts_one_call_in_flight_while_the_locked_body_runs(monkeypatch):
    seen: list[tuple[int, int]] = []

    def body(html, *, url=None):
        seen.append(_slot())
        return None

    monkeypatch.setattr(extract, "_extract_locked", body)
    assert extract.extract_article("<html><body>x</body></html>") is None
    assert seen == [(1, 1)]
    assert _slot() == (0, 1), "left again once the call returned, and the entry is remembered"


def test_a_raising_extraction_leaves_nothing_in_flight_and_still_raises(monkeypatch):
    def body(html, *, url=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(extract, "_extract_locked", body)
    with pytest.raises(RuntimeError, match="boom"):
        extract.extract_article("<html><body>x</body></html>")
    assert _slot() == (0, 1)
    assert not _lock_is_held_by_this_thread(), "the lock was given up as before"


def test_the_bracket_opens_inside_the_lock_and_closes_before_it_is_given_up(monkeypatch):
    events: list[str] = []

    class Recorder:
        def __init__(self, name):
            events.append(f"new {name}")

        def __enter__(self):
            events.append(f"enter lock_held={_lock_is_held_by_this_thread()}")

        def __exit__(self, *exc):
            events.append(f"exit lock_held={_lock_is_held_by_this_thread()}")

    monkeypatch.setattr(extract, "native_call", Recorder)
    monkeypatch.setattr(extract, "_extract_locked", lambda html, *, url=None: None)
    extract.extract_article("<html><body>x</body></html>")
    assert events == ["new lxml", "enter lock_held=True", "exit lock_held=True"]


def test_the_bracket_sits_between_the_gauge_marks_inside_the_hold(monkeypatch):
    """``holding()`` stays the first statement of the hold and ``released()`` the first of its ``finally``: the bracket opens
    after the one and closes before the other, on a return and on a raise, so the gauge never counts the bracket's own
    enter or exit as time outside the hold."""
    events: list[str] = []

    class Recorder:
        def __init__(self, name):
            pass

        def __enter__(self):
            events.append("enter")

        def __exit__(self, *exc):
            events.append("exit")

    def released() -> float:
        events.append("released")
        return 0.0

    monkeypatch.setattr(extract, "native_call", Recorder)
    monkeypatch.setattr(extract.lock_stats, "holding", lambda: events.append("holding"))
    monkeypatch.setattr(extract.lock_stats, "released", released)
    monkeypatch.setattr(extract, "_extract_locked", lambda html, *, url=None: None)
    extract.extract_article("<html><body>x</body></html>")
    assert events == ["holding", "enter", "exit", "released"]

    events.clear()

    def boom(html, *, url=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(extract, "_extract_locked", boom)
    with pytest.raises(RuntimeError, match="boom"):
        extract.extract_article("<html><body>x</body></html>")
    assert events == ["holding", "enter", "exit", "released"]


class _Tree:
    """Stands in for an lxml tree: records the slot's reading at the moment it is freed (libxml2's free is where a native abort can land)."""

    seen: list[tuple[int, int]] = []

    def __del__(self) -> None:
        _Tree.seen.append(_slot())


def test_the_trees_of_a_returning_extraction_are_freed_while_the_slot_counts_it_in_flight(monkeypatch):
    _Tree.seen = []

    def body(html, *, url=None):
        tree = _Tree()  # noqa: F841 - a frame local, the way bare_extraction holds its tree
        return None

    monkeypatch.setattr(extract, "_extract_locked", body)
    assert extract.extract_article("<html><body>x</body></html>") is None
    assert _Tree.seen == [(1, 1)], f"a tree was freed outside the bracket -- saw {_Tree.seen}"
    assert _slot() == (0, 1)


def test_the_trees_of_a_raising_extraction_are_freed_while_the_slot_counts_it_in_flight(monkeypatch):
    """On a raise the trees live on in the traceback's frames and are freed by ``_release_frames`` in ``except``: the
    bracket must still be open there, or a native abort in that free reads as 'nothing in flight'."""
    _Tree.seen = []

    def body(html, *, url=None):
        tree = _Tree()  # noqa: F841
        raise RuntimeError("boom")

    monkeypatch.setattr(extract, "_extract_locked", body)
    with pytest.raises(RuntimeError, match="boom"):
        extract.extract_article("<html><body>x</body></html>")
    assert _Tree.seen == [(1, 1)], f"the trees of a raising extraction were freed outside the bracket -- saw {_Tree.seen}"
    assert _slot() == (0, 1)


def test_a_worker_waiting_for_the_lock_is_not_counted_as_in_lxml(monkeypatch):
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []
    entered_by: list[str] = []

    class Spy(ni.native_call):
        def __enter__(self):
            entered_by.append(threading.current_thread().name)
            return super().__enter__()

    def body(html, *, url=None):
        order.append(html)
        if html == "first":
            inside.set()
            assert release.wait(_WAIT)
        return None

    monkeypatch.setattr(extract, "native_call", Spy)
    monkeypatch.setattr(extract, "_extract_locked", body)
    first = threading.Thread(target=extract.extract_article, args=("first",), name="first")
    second = threading.Thread(target=extract.extract_article, args=("second",), name="second")
    first.start()
    try:
        assert inside.wait(_WAIT)
        second.start()
        # Give the second thread time to run up to the lock and block there; a bracket opened BEFORE the lock would have
        # counted it by now.
        threading.Event().wait(0.3)
        assert _slot() == (1, 1), "one in lxml; the one waiting for the lock is not"
        assert entered_by == ["first"]
    finally:
        # also when an assertion above fails: a thread left holding the extraction lock would break every later test
        release.set()
        first.join(_WAIT)
        if second.is_alive() or second.ident is not None:
            second.join(_WAIT)
    assert order == ["first", "second"]
    assert entered_by == ["first", "second"]
    assert _slot() == (0, 2)


def test_a_page_with_no_content_never_reaches_the_bracket():
    assert extract.extract_article("   ") is None
    assert extract.extract_article("") is None
    assert _slot() == (0, 0)
