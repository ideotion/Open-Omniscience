"""R171 for the run records: ``run_refusals_net`` and ``run_open`` take their state INSIDE the ``try`` that gives it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A ``KeyboardInterrupt`` can land between any two statements of the main thread. Both context managers used to change something before their
``try`` began, so an interrupt in that gap skipped the ``finally`` that undoes it:

* ``run_refusals_net`` set the ``_REFUSAL_SCOPE`` variable first. A scope nobody reset stayed the thread's current one, and every later net in
  the thread nested under it.
* ``run_open`` wrote the run OPEN to the journal and read the free bytes first. A run left open says it is still going, for the life of the
  process.

Each test below delivers the interrupt at the step the old code left uncovered, by a stand-in that does the real step and THEN raises (the
interrupt lands just after the statement changed something), and reads what is left behind. The three that reach the old gap fail on the old
code and pass on the new; the others guard the branches the new code added (an error before the scope exists, an interrupt before the run is
written) and the behaviour that did not change. ``tests/test_contextmanager_acquire_before_try.py`` is the scan that finds the same shape in a
function nobody has written yet; these tests pin the two it found in this module.
"""

from __future__ import annotations

import pytest

from src.monitoring import storage_events as se


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """A journal whose file is ``tmp_path``'s; the scope variable is put back to nothing after a test, whatever it did."""
    monkeypatch.setattr(se, "_path", lambda: tmp_path / "storage_events.json")
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 3600.0)
    se.reset_for_tests()
    real = se._REFUSAL_SCOPE
    real.set(None)
    yield
    real.set(None)
    se.reset_for_tests()


class _InterruptAfterTheSet:
    """Stands in for the scope variable: the real ``set`` happens, then the interrupt is raised, once. Every other call is the real one."""

    def __init__(self, real, *, fire_on_set_number: int = 1) -> None:
        self._real = real
        self._fire_on = fire_on_set_number
        self.sets = 0

    def get(self):
        return self._real.get()

    def set(self, value):
        out = self._real.set(value)
        self.sets += 1
        if self.sets == self._fire_on:
            raise KeyboardInterrupt
        return out


def _events(kind: str) -> list[dict]:
    return se.diagnostics_member(10_000_000)["kinds"][kind]["events"]


def test_an_interrupt_just_after_the_scope_is_set_leaves_no_scope_behind(journal, monkeypatch):
    real = se._REFUSAL_SCOPE
    monkeypatch.setattr(se, "_REFUSAL_SCOPE", _InterruptAfterTheSet(real))
    with pytest.raises(KeyboardInterrupt), se.run_refusals_net("export", via="volume-set"):
        pytest.fail("the body does not run: the interrupt landed before it")
    assert real.get() is None, "the scope of a start that never ran is not the thread's current one"
    assert _events("run_export") == [], "an interrupt is not a refusal and records nothing"


def test_an_interrupt_in_an_inner_net_leaves_the_outer_scope_current(journal, monkeypatch):
    real = se._REFUSAL_SCOPE
    with se.run_refusals_net("import", via="folder"):
        outer = real.get()
        assert outer is not None
        # the proxy fires on the NEXT set, the inner net's own
        monkeypatch.setattr(se, "_REFUSAL_SCOPE", _InterruptAfterTheSet(real))
        with pytest.raises(KeyboardInterrupt), se.run_refusals_net("import", via="folder"):
            pytest.fail("the body does not run")
        assert real.get() is outer, "the outer start's scope is current again, not the inner one's"
        monkeypatch.setattr(se, "_REFUSAL_SCOPE", real)
    assert real.get() is None


def test_an_error_raised_before_the_scope_exists_records_nothing_and_goes_on(journal, monkeypatch):
    """The scope is made inside the ``try`` now, so the handlers can run before it exists: they say nothing, because there is no scope to
    say whether a refusal was written, and the error is the caller's."""

    class _NoScope:
        def __init__(self, parent):
            raise MemoryError

    monkeypatch.setattr(se, "_RefusalScope", _NoScope)
    with pytest.raises(MemoryError), se.run_refusals_net("export", via="volume-set", refused_as=((MemoryError, "not-a-folder"),)):
        pytest.fail("the body does not run")
    assert se._REFUSAL_SCOPE.get() is None
    assert _events("run_export") == []


def test_the_net_still_records_a_refusal_and_restores_the_scope_when_nothing_is_interrupted(journal):
    real = se._REFUSAL_SCOPE
    with pytest.raises(OSError), se.run_refusals_net("export", via="volume-set"):
        assert real.get() is not None
        raise OSError(5, "I/O error")
    assert real.get() is None
    (event,) = _events("run_export")
    assert event["reason"] == se.RUN_REFUSALS["path-unreadable"] and event["error"] == "OSError"


def test_an_interrupt_in_the_free_space_read_ends_the_run_it_opened(journal, monkeypatch):
    """``run_started`` wrote the run OPEN; the interrupt lands in the read of the free bytes that follows it. The run must not stay open."""

    def interrupted(note, name, path=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(se, "run_free_space", interrupted)
    with pytest.raises(KeyboardInterrupt), se.run_open("import", via="single-file"):
        pytest.fail("the body does not run")
    (event,) = _events("run_import")
    assert event["open"] is False and event["outcome"] == "ended-without-a-recorded-outcome", "a run that never began its body is not still going"


def test_an_interrupt_before_the_run_is_written_leaves_no_run_and_no_error_of_its_own(journal, monkeypatch):
    def interrupted(what, **facts):
        raise KeyboardInterrupt

    monkeypatch.setattr(se, "run_started", interrupted)
    with pytest.raises(KeyboardInterrupt), se.run_open("import", via="single-file"):
        pytest.fail("the body does not run")
    assert _events("run_import") == [], "nothing was opened, so nothing is closed (ending a missing note does nothing)"


def test_a_run_open_still_hands_the_block_its_note_and_ends_as_before(journal):
    with se.run_open("import", via="single-file") as note:
        assert note is not None
        (running,) = _events("run_import")
        assert running["open"] is True
    assert _events("run_import")[0]["outcome"] == "ended-without-a-recorded-outcome"
