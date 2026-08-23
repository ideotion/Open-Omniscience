"""Regression test for the mandatory 4-lens adversarial skeptic matrix's
transactional-semantics finding #4 (LOW), PR-D / W1.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DIAGNOSED GAP: ``_release_transaction()`` (src/briefing/registry.py) already
logged a WARNING when its ``session.commit()`` failed, and already attempted a
best-effort ``session.rollback()`` to recover -- but if THAT rollback itself also
failed, the inner ``except Exception: pass`` swallowed it with ZERO diagnostic
trace. A commit-then-rollback double failure is rare, but were it to happen the
session would stay poisoned for every remaining producer in the SAME `run_all()`
pass (the identical PendingRollbackError cascade the write-gate/autoflush finding
named for warm_cache) -- and while each subsequent producer's OWN `run_all()`
except would still log ITS symptom, the true root cause (this rollback failing)
would never appear anywhere. This test proves the fix makes that failure VISIBLE
(logged) instead of silently swallowed, without ever letting it propagate past
`_release_transaction()` (it must still never raise -- rollback failure stays
non-fatal to the feed).
"""

from __future__ import annotations

import logging

import src.briefing.registry as registry


class _DoubleFailSession:
    """A minimal fake session whose commit() AND rollback() BOTH raise -- the
    exact double-failure `_release_transaction`'s inner except exists to survive.
    """

    def commit(self):
        raise RuntimeError("boom-commit")

    def rollback(self):
        raise RuntimeError("boom-rollback")


def test_a_rollback_failure_after_a_failed_commit_is_logged_not_swallowed(caplog):
    """MUST FAIL (no 'rollback ... ALSO failed' record) on the pre-fix code, where
    the inner except is a bare `pass`. PASSES once the rollback failure is logged."""
    with caplog.at_level(logging.WARNING, logger="src.briefing.registry"):
        # Must never raise -- a commit-AND-rollback double failure is still
        # non-fatal to the caller (`run_all`'s per-producer loop).
        registry._release_transaction(_DoubleFailSession())

    messages = [r.getMessage() for r in caplog.records]
    assert any("commit between producers failed" in m for m in messages), (
        "the original commit-failure warning must still fire"
    )
    assert any(
        "rollback" in m.lower() and ("also failed" in m.lower() or "failed" in m.lower())
        for m in messages
        if "commit between producers failed" not in m
    ), (
        "a rollback failure that follows a commit failure must be LOGGED, not "
        "silently swallowed by a bare `except: pass` -- otherwise there is zero "
        "diagnostic trace of the one scenario that actually poisons the shared "
        "session for the rest of the pass"
    )


def test_release_transaction_never_raises_on_a_double_failure():
    """Whatever the fix looks like, _release_transaction's whole POINT is that a
    DB failure here must never abort run_all's producer loop -- confirm that
    holds even for the double-failure case this finding is about."""
    registry._release_transaction(_DoubleFailSession())  # must not raise
