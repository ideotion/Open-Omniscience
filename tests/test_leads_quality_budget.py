"""The Leads producer pass must be boundable, and the bound must survive the isolation.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-09: an all-diagnostics run sat 69 minutes inside
``leads-quality.json`` on a ~1M-article corpus and never finished, at member 53 of 55.

The member was NOT unguarded. It runs inline under a 300 s ``statement_deadline``, and
that deadline fires exactly as designed -- it raises ``StatementTimeout`` from the next
SQL statement. What it meets is ``run_all``'s per-producer ``except Exception``, which
exists so one bad producer can never blank Home. The guard fired; the isolation ate it;
the loop moved to the next producer and did it again.

So the lesson under the fix, and what these tests pin: a budget for a loop wrapped in
blanket exception isolation cannot BE an exception. It has to be control flow the
isolation cannot intercept. ``test_an_exception_bound_is_swallowed`` reproduces the
defeated version directly, so the reason for the ``break`` cannot quietly rot into
"someone preferred it".
"""

from __future__ import annotations

import src.briefing.registry as R
from src.briefing.card import Card


def _card(key: str) -> Card:
    return Card(
        type="test", key=key, bucket="watch", title=f"card {key}",
        summary="s", method="m", caveat="c", n=1,
    )


def _registry(monkeypatch, producers):
    monkeypatch.setattr(R, "_REGISTRY", list(producers))
    monkeypatch.setattr(R, "_disabled_names", lambda: frozenset())
    monkeypatch.setattr(R, "_wal_guard", lambda s: __import__("contextlib").nullcontext())
    monkeypatch.setattr(R, "_release_transaction", lambda s: None)


def test_the_budget_stops_the_pass_and_says_how_far_it_got(monkeypatch):
    """A spent budget must stop starting producers — and report the count, because a
    partial feed that does not say it is partial reads as cards having disappeared."""
    clock = {"t": 0.0}
    monkeypatch.setattr(R.time, "monotonic", lambda: clock["t"])

    def slow(name):
        def _p(_session):
            clock["t"] += 10.0
            return [_card(name)]
        return _p

    _registry(monkeypatch, [(f"p{i}", slow(f"p{i}")) for i in range(10)])
    cards, stats = R.run_all_bounded(object(), deadline=25.0)

    assert stats["truncated"] is True
    assert stats["producers_run"] == 3, "three fit in 25s at 10s each"
    assert stats["producers_total"] == 10
    assert len(cards) == 3


def test_no_deadline_runs_everything(monkeypatch):
    """Home's path. The bound is opt-in; the default must be byte-identical to before,
    or a perfectly healthy feed starts losing cards on a slow machine."""
    _registry(monkeypatch, [(f"p{i}", lambda _s, n=f"p{i}": [_card(n)]) for i in range(10)])
    cards, stats = R.run_all_bounded(object(), deadline=None)
    assert stats == {"producers_run": 10, "producers_total": 10, "truncated": False}
    assert len(cards) == 10


def test_run_all_is_unchanged_for_its_existing_callers(monkeypatch):
    """The old entry point still returns a bare list — Home is not asked to change."""
    _registry(monkeypatch, [(f"p{i}", lambda _s, n=f"p{i}": [_card(n)]) for i in range(4)])
    out = R.run_all(object())
    assert isinstance(out, list)
    assert len(out) == 4


def test_an_exception_bound_is_swallowed(monkeypatch):
    """THE REPRODUCER, and the reason the budget is a ``break``.

    This is the defeated design: a producer raising the very exception a statement
    deadline raises. The isolation catches it, the pass continues, and every later
    producer is reached — which is precisely how a nominally-bounded member ran for 69
    minutes. If this ever fails, blanket isolation has changed and the budget mechanism
    should be re-examined; it must NOT be 'fixed' by making the budget throw."""
    from src.database.maintenance import StatementTimeout

    reached: list[str] = []

    def boom(_session):
        raise StatementTimeout("deadline exceeded")

    def later(name):
        def _p(_session):
            reached.append(name)
            return [_card(name)]
        return _p

    _registry(monkeypatch, [("boom", boom), ("a", later("a")), ("b", later("b"))])
    cards, stats = R.run_all_bounded(object(), deadline=None)

    assert reached == ["a", "b"], "the isolation swallowed the timeout and carried on"
    assert stats["truncated"] is False, "nothing recorded that the budget had been hit"
    assert len(cards) == 2


def test_the_report_discloses_truncation(monkeypatch):
    """The payload — not just a log line — has to carry it, or a reader diffing two
    exports cannot tell a shorter feed from a shorter RUN."""
    from src.analytics import leads_quality as LQ

    clock = {"t": 0.0}
    monkeypatch.setattr(R.time, "monotonic", lambda: clock["t"])

    def slow(name):
        def _p(_session):
            clock["t"] += 100.0
            return [_card(name)]
        return _p

    _registry(monkeypatch, [(f"p{i}", slow(f"p{i}")) for i in range(5)])
    rep = LQ.leads_quality_report(object(), budget_s=250.0)

    assert rep["truncated"] is True
    assert rep["producers_run"] == 3
    assert rep["producers_total"] == 5
    assert "TRUNCATED" in rep["caveat"]
    assert "not a change in the feed" in rep["caveat"]


def test_an_unbudgeted_report_is_complete_and_says_nothing_about_truncation(monkeypatch):
    """Negative-space twin: the honest label must appear only when it is true."""
    from src.analytics import leads_quality as LQ

    _registry(monkeypatch, [(f"p{i}", lambda _s, n=f"p{i}": [_card(n)]) for i in range(3)])
    rep = LQ.leads_quality_report(object(), budget_s=None)
    assert rep["truncated"] is False
    assert "TRUNCATED" not in rep["caveat"]
    assert rep["count"] == 3
