"""A2/A5: the integrity read endpoints join the shared heavy-read admission guard.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

profile / actors / prominence / fixity run corpus-wide coordination scans and full-corpus
re-hashing — the exact "60-200 s, unbounded, no cache" reads that the Home-poll death spiral
piles onto the one SQLCipher connection (field test 2026-07-08, Item 8). They were the last
heavy ``def`` reads NOT behind :func:`src.api.heavy.guarded_read`. This pins the wiring at the
handler level (composing the real route functions, no crypto DB needed): the normal path
returns the leader's REAL value, a full cap fast-fails 429 WITHOUT running the compute, a
duplicate is single-flighted to ONE compute, a deadline overrun is 503 (never a truncated
"all clear"), and the cheap profile 404 stays OUTSIDE the guard.

Attacks the negative space (the #591 lesson): the refused/duplicate request must NOT run the
underlying scan.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api import heavy
from src.api import integrity as intg
from src.api.heavy import run_heavy
from src.database.maintenance import StatementTimeout


@pytest.fixture(autouse=True)
def _fast_guard(monkeypatch):
    monkeypatch.setenv("OO_HEAVY_CONCURRENCY", "4")
    monkeypatch.setenv("OO_HEAVY_ACQUIRE_TIMEOUT_S", "0.3")
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "0.3")
    heavy._reset_for_tests()
    yield
    heavy._reset_for_tests()


def _sqlite_session() -> Session:
    """A plain (unencrypted) SQLite session so flight_key/statement_deadline have a live DBAPI
    connection — no app DB, no crypto extra (CI-only) touched."""
    return sessionmaker(bind=create_engine("sqlite://"))()


# The four read handlers + the module attribute each one's heavy compute hangs off, so one
# parametrized body proves the whole sweep. Each fake returns a sentinel the guard must pass
# through verbatim (single-flight collapses duplicates, it never fabricates a value).
def _patch_all(monkeypatch, calls):
    def _spy(name, ret):
        def _fn(*a, **k):
            calls[name] = calls.get(name, 0) + 1
            return ret
        return _fn

    monkeypatch.setattr(intg.profile_mod, "source_profile", _spy("profile", {"found": True, "v": 1}))
    monkeypatch.setattr(intg.collapse_mod, "collapse_status", _spy("actors", {"actors": []}))
    monkeypatch.setattr(intg.collapse_mod, "story_prominence", _spy("prominence", {"stories": []}))
    monkeypatch.setattr(intg, "audit_fixity", _spy("fixity", {"mismatches": []}))


def _invoke(name: str, db):
    if name == "profile":
        return intg.get_profile(source="reuters.com", days=30, db=db)
    if name == "actors":
        return intg.get_actors(days=14, db=db)
    if name == "prominence":
        return intg.get_prominence(days=14, weight_by_novelty=False, db=db)
    return intg.get_fixity(limit=None, db=db)


ALL = ["profile", "actors", "prominence", "fixity"]


@pytest.mark.parametrize("name", ALL)
def test_normal_path_returns_the_real_value_through_the_guard(monkeypatch, name):
    calls: dict[str, int] = {}
    _patch_all(monkeypatch, calls)
    out = _invoke(name, _sqlite_session())
    assert isinstance(out, dict) and out  # the fake payload, passed through verbatim
    assert calls[name] == 1
    assert heavy.status()["counters"]["runs"] >= 1  # it ran under the guard


@pytest.mark.parametrize("name", ALL)
def test_full_cap_fast_fails_429_without_running_the_scan(monkeypatch, name):
    monkeypatch.setenv("OO_HEAVY_CONCURRENCY", "1")
    heavy._reset_for_tests()
    calls: dict[str, int] = {}
    _patch_all(monkeypatch, calls)

    holding = threading.Event()
    release = threading.Event()
    t = threading.Thread(
        target=lambda: run_heavy("held", lambda: (holding.set(), release.wait(2)))
    )
    t.start()
    assert holding.wait(2), "background leader never took the one slot"
    try:
        with pytest.raises(HTTPException) as ei:
            _invoke(name, _sqlite_session())
        assert ei.value.status_code == 429
        assert calls.get(name, 0) == 0, "a busy request must NOT run the heavy scan"
    finally:
        release.set()
        t.join(2)


def test_profile_404_is_outside_the_guard(monkeypatch):
    # A not-found source is a cheap, honest 404 — never shared as a heavy result.
    monkeypatch.setattr(
        intg.profile_mod, "source_profile", lambda *a, **k: {"found": False}
    )
    with pytest.raises(HTTPException) as ei:
        intg.get_profile(source="nope.example", days=30, db=_sqlite_session())
    assert ei.value.status_code == 404


def test_fixity_deadline_overrun_is_503_not_a_partial(monkeypatch):
    def _timeout(*a, **k):
        raise StatementTimeout("exceeded the 60s deadline")

    monkeypatch.setattr(intg, "audit_fixity", _timeout)
    with pytest.raises(HTTPException) as ei:
        intg.get_fixity(limit=None, db=_sqlite_session())
    # 503, never a truncated {"mismatches": []} masquerading as an all-clear.
    assert ei.value.status_code == 503


def test_duplicate_actors_requests_are_single_flighted_to_one_scan(monkeypatch):
    # A generous follower wait so the follower reliably parks in fl.event.wait to SHARE
    # (never a spurious 429), and the leader is held until the follower is registered — so
    # this DETERMINISTICALLY exercises the follow path, never a leader-retires-first race.
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "3")
    heavy._reset_for_tests()

    calls = [0]
    leader_in = threading.Event()
    release = threading.Event()

    def _slow_status(session, days):
        calls[0] += 1
        leader_in.set()
        release.wait(3)  # stays parked (holding the flight) until the follower is registered
        return {"actors": [], "days": days}

    monkeypatch.setattr(intg.collapse_mod, "collapse_status", _slow_status)
    # Same bind → the two requests share ONE flight. Reuse ONE session so the bind id matches.
    db = _sqlite_session()

    res: dict = {}
    t_lead = threading.Thread(target=lambda: res.__setitem__("lead", intg.get_actors(days=14, db=db)))
    t_lead.start()
    assert leader_in.wait(2), "leader scan never started"

    follower_started = threading.Event()

    def _follow():
        follower_started.set()
        res["follow"] = intg.get_actors(days=14, db=db)

    t_follow = threading.Thread(target=_follow)
    t_follow.start()
    # The leader cannot retire the flight while `release` is unset, so once the follower
    # thread is running it finds the live flight and parks in fl.event.wait to share. The
    # head start (≪ the 3s follower wait) guarantees it is parked before we let the leader
    # finish — deterministic, never a leader-retires-first race.
    assert follower_started.wait(2)
    time.sleep(0.2)
    release.set()
    t_lead.join(3)
    t_follow.join(3)

    assert res.get("lead") == res.get("follow") == {"actors": [], "days": 14}
    assert calls[0] == 1, "single-flight must collapse the duplicate coordination scan to ONE"
    assert heavy.status()["counters"]["shared"] >= 1
