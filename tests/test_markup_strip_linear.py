"""The <style>/<script> strip is LINEAR, and the re-index yields to an exclusive import.

Both guards come from one field import (2026-08-04) that ran 15.4 h and never
finished. Its console named the first defect outright -- ``serial precompute still
on article 26324 after 17536 s (412351 chars ...)`` -- and its run journal named the
second: ``owns_the_machine: true`` with two ``reindex_resume`` milestones logged
INSIDE the merge that believed it had the machine to itself.
"""

from __future__ import annotations

import re
import threading
import time

import pytest

from src.analytics.extract import _strip_style_script, strip_markup

# The pattern as it shipped before 2026-08-05, kept HERE as the oracle: the new
# implementation must agree with it everywhere, and differ only in time.
_OLD = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)

_SHAPES = [
    "plain text no markup",
    "<style>body{color:red}</style>after",
    "<STYLE type='a'>x</STYLE >tail",
    "<script src='x'>var a='</b>';</script>ok",
    "<script>a<b</script>",
    "unclosed <style>body{} and then more text",
    "<style>one</style> mid <script>two</script> end",
    "<script>a</script><style>b</style>",
    "a < b and c > d",
    "<style></style>",
    "<script>\nmultiline\n</script>",
    "<style>x</style",
    "<div>keep</div>",
    "nested <script>outer <script> inner </script> tail",
    "<style>a</style> junk <style>b",
    "<script>x</script> <style>y",
    "<style>a<style>b</style>c",
    "</style>orphan",
    "<style>a</script>b</style>",
]


@pytest.mark.parametrize("text", _SHAPES)
def test_linear_strip_matches_the_regex_it_replaced(text: str) -> None:
    assert _strip_style_script(text) == _OLD.sub(" ", text)


def test_randomised_differential_against_the_old_regex() -> None:
    """The first draft passed every hand-written shape and was still WRONG.

    It advanced the copy cursor past an opener it had decided to skip, silently
    dropping the text before it -- a mistake only randomised inputs surfaced. The
    generator therefore leans on the shapes that broke it: unclosed openers,
    orphan closers, and both tags interleaved.
    """
    import random

    rnd = random.Random(5)
    words = ["alpha", "beta", "gamma"]

    def gen() -> str:
        parts = []
        for _ in range(rnd.randint(1, 16)):
            r = rnd.random()
            if r < 0.18:
                parts.append(f"<style>{rnd.choice(words)}</style>")
            elif r < 0.34:
                parts.append(f"<script>{rnd.choice(words)}<{rnd.choice(words)}</script>")
            elif r < 0.47:
                parts.append(f"<style>{rnd.choice(words)}")
            elif r < 0.57:
                parts.append(f"<script>{rnd.choice(words)}")
            elif r < 0.66:
                parts.append("</style>")
            elif r < 0.74:
                parts.append("</script>")
            elif r < 0.84:
                parts.append(f"<div class='{rnd.choice(words)}'>")
            else:
                parts.append(rnd.choice(words) + " ")
        return "".join(parts)

    for _ in range(4000):
        s = gen()
        assert _strip_style_script(s) == _OLD.sub(" ", s), s


def test_unclosed_openers_do_not_take_quadratic_time() -> None:
    """The defect, at the exact size of the article that wedged the field re-index.

    412,351 chars of ``<style>`` with no closer MEASURED 138.3 s under the old
    pattern and 0.030 s under this one. The bar is 10 s: ~330x clear of the
    linear implementation on a slow machine, ~14x inside the quadratic one, so it
    discriminates without flaking. Asserting a TIME is the point -- the output was
    always correct, only unusably slow.
    """
    text = ("<style>" * (412351 // 7))[:412351]
    t0 = time.monotonic()
    _strip_style_script(text)
    assert time.monotonic() - t0 < 10.0


def test_realistic_unclosed_script_spam_is_fast_through_strip_markup() -> None:
    """The whole public path, not just the helper (measured 25.7 s -> 0.007 s)."""
    text = ("<script type='x'> var a=1; alpha beta " * (412351 // 38))[:412351]
    t0 = time.monotonic()
    strip_markup(text)
    assert time.monotonic() - t0 < 10.0


def test_text_without_style_or_script_is_returned_unchanged_and_identical() -> None:
    """Clean text must come back as the SAME object: keyword offsets index into it."""
    clean = "A perfectly ordinary sentence about policy and elections."
    assert _strip_style_script(clean) is clean


# --------------------------------------------------------------------------- #
#  The re-index yields to an exclusive operation
# --------------------------------------------------------------------------- #
class _FakeScheduler:
    def __init__(self, held: bool) -> None:
        self._held = held
        self.calls = 0

    def holds_exclusive(self) -> bool:
        self.calls += 1
        return self._held

    def release(self) -> None:
        self._held = False


def _manager(tmp_path):
    from src.analytics.reindex_job import ReindexJobManager

    return ReindexJobManager(state_path=tmp_path / "reindex_job.json")


def test_yield_returns_immediately_when_no_exclusive_hold(tmp_path, monkeypatch) -> None:
    mgr = _manager(tmp_path)
    sched = _FakeScheduler(held=False)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: sched)
    t0 = time.monotonic()
    mgr._yield_to_exclusive()
    assert time.monotonic() - t0 < 1.0
    assert mgr.status()["parked_for_exclusive"] is False


def test_yield_parks_until_the_exclusive_hold_is_released(tmp_path, monkeypatch) -> None:
    """The negative-space twin of the test above: it must actually WAIT.

    Without this, a `_yield_to_exclusive` that returned unconditionally would pass
    every other test in this file while restoring the exact competition the fix
    exists to remove.
    """
    from src.analytics import reindex_job as rj

    mgr = _manager(tmp_path)
    sched = _FakeScheduler(held=True)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: sched)
    monkeypatch.setattr(rj, "_EXCLUSIVE_POLL_S", 0.02)

    done = threading.Event()
    threading.Thread(
        target=lambda: (mgr._yield_to_exclusive(), done.set()), daemon=True
    ).start()

    # It is parked while the hold stands...
    time.sleep(0.2)
    assert not done.is_set()
    assert mgr.status()["parked_for_exclusive"] is True

    # ...and resumes on its own once the hold is released.
    sched.release()
    assert done.wait(timeout=5.0)
    assert mgr.status()["parked_for_exclusive"] is False


def test_pause_releases_a_parked_job_immediately(tmp_path, monkeypatch) -> None:
    """Parking must not cost the operator control: the wait is on the stop event."""
    from src.analytics import reindex_job as rj

    mgr = _manager(tmp_path)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _FakeScheduler(True))
    monkeypatch.setattr(rj, "_EXCLUSIVE_POLL_S", 30.0)  # far longer than the test

    done = threading.Event()
    threading.Thread(
        target=lambda: (mgr._yield_to_exclusive(), done.set()), daemon=True
    ).start()
    time.sleep(0.1)
    mgr.pause()
    assert done.wait(timeout=5.0), "a paused job must not stay parked for a poll interval"
    assert mgr.status()["parked_for_exclusive"] is False


def test_an_unavailable_scheduler_never_parks_the_job(tmp_path, monkeypatch) -> None:
    """Degrade toward WORKING: an unreadable hold must not stall the re-index forever."""
    def _boom():
        raise RuntimeError("no scheduler here")

    mgr = _manager(tmp_path)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", _boom)
    t0 = time.monotonic()
    mgr._yield_to_exclusive()
    assert time.monotonic() - t0 < 1.0
    assert mgr.status()["parked_for_exclusive"] is False
