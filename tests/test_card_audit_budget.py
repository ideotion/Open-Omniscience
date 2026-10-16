"""The card audit takes its statement budget in seconds, and a bundle member keeps what is left of its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, two bundles: ``card-audit.json`` was a member with a 300 s deadline, but the endpoint reads through
``guarded_read``, which opens ITS OWN 60 s deadline (``OO_STATEMENT_TIMEOUT_S``). An inner ``statement_deadline``
replaces the outer one rather than nesting, so the member was cut at 60 s with 240 s unspent. ``guarded_read`` now takes
``deadline_s`` and the endpoint passes the caller's ``budget_s`` or what is left of the enclosing deadline.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import heavy
from src.api.diagnostics import corpus
from src.database import maintenance


def _session():
    return sessionmaker(bind=create_engine("sqlite://"))()


def _watch_deadlines(monkeypatch):
    """Record the ``seconds`` every ``statement_deadline`` is opened with, then run it as the real one."""
    seen: list = []
    real = maintenance.statement_deadline

    def _spy(session, seconds=None):
        seen.append(seconds)
        return real(session, seconds)

    monkeypatch.setattr(maintenance, "statement_deadline", _spy)
    return seen


def test_guarded_read_passes_its_deadline_to_the_statement_block(monkeypatch):
    seen = _watch_deadlines(monkeypatch)
    assert heavy.guarded_read(_session(), "budget-a", lambda: 1, deadline_s=240.0) == 1
    assert seen == [240.0]


def test_guarded_read_without_a_deadline_keeps_the_process_default(monkeypatch):
    seen = _watch_deadlines(monkeypatch)
    heavy.guarded_read(_session(), "budget-b", lambda: 1)
    assert seen == [None]


def test_a_requested_budget_wins_over_an_enclosing_deadline():
    db = _session()
    db.info[maintenance._DEADLINE_KEY] = time.monotonic() + 200
    assert corpus._card_audit_budget(db, 90) == (90.0, "requested")


def test_the_enclosing_deadline_is_what_is_left_of_it():
    db = _session()
    db.info[maintenance._DEADLINE_KEY] = time.monotonic() + 240
    seconds, source = corpus._card_audit_budget(db, None)
    assert source == "enclosing-deadline"
    assert 235 < seconds <= 240


def test_no_budget_and_no_enclosing_deadline_is_the_process_default():
    assert corpus._card_audit_budget(_session(), None) == (None, "default")


def test_an_expired_enclosing_deadline_does_not_become_a_negative_budget():
    db = _session()
    db.info[maintenance._DEADLINE_KEY] = time.monotonic() - 5
    assert corpus._card_audit_budget(db, None) == (None, "default")


def test_a_query_object_from_a_direct_call_is_not_taken_for_a_number():
    """The bundle calls ``card_audit(...)`` as a function and omits ``budget_s``; the default is a ``Query`` object."""
    from fastapi import Query

    assert corpus._card_audit_budget(_session(), Query(None))[1] == "default"
    assert corpus._card_audit_budget(_session(), True)[1] == "default"
    assert corpus._card_audit_budget(_session(), 0)[1] == "default"


@pytest.fixture
def stubbed_report(monkeypatch):
    from src.briefing import card_audit as ca

    monkeypatch.setattr(ca, "card_audit_report", lambda db, **kw: {"producers": {}})
    return None


def test_the_endpoint_inside_a_300s_member_gets_the_rest_of_it_not_60(monkeypatch, stubbed_report):
    seen = _watch_deadlines(monkeypatch)
    db = _session()
    db.info[maintenance._DEADLINE_KEY] = time.monotonic() + 300
    body = corpus.card_audit(depth="summary", determinism=True, download=False, db=db)
    # the outer 300 s deadline is spent as a member; the audit's own block opens with what is left of it
    assert seen and 290 < seen[0] <= 300
    assert b'"source":"enclosing-deadline"' in body.body.replace(b" ", b"")


def test_the_endpoint_reports_the_requested_budget(monkeypatch, stubbed_report):
    seen = _watch_deadlines(monkeypatch)
    body = corpus.card_audit(
        depth="summary", determinism=True, download=False, budget_s=45.0, db=_session()
    )
    assert seen == [45.0]
    assert b'"source":"requested"' in body.body.replace(b" ", b"")


def test_a_plain_call_reports_the_default(monkeypatch, stubbed_report):
    seen = _watch_deadlines(monkeypatch)
    body = corpus.card_audit(depth="summary", determinism=True, download=False, db=_session())
    assert seen == [None]
    assert b'"source":"default"' in body.body.replace(b" ", b"")
