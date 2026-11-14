"""R695 (OPEN_QUEUE item 32's residual): the saved-watch pass that runs before Home's producers is bounded like a producer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. R666 put each briefing producer under its own 600 s bound, but ``_refresh_briefing`` called
``evaluate_watches(session)`` bare, before them: its reads hold the write-ahead log's read mark like a producer's, with no time
limit, and its per-watch ``except Exception`` would also have swallowed a timeout and stamped ``last_evaluated_at`` on every
watch it never evaluated.

What these tests pin, through the real refresh, a real SQLite store and the real ``statement_deadline``: the pass is stopped at the
bound and the producers still run; Home names the missing kind ("A watch matched"); the watches the pass did not reach are left
unstamped and the NEXT refresh evaluates them and fires (the ruling's addition); a pass that ran past the bound without raising is
named, and the loop stops between watches once the bound is spent; a watch's own error is still one bad watch; a stop inside the
ring lookup is never taken for a missing disclosure; no write runs while the deadline is armed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.analytics import watches as W
from src.briefing import registry, service
from src.briefing.card import Card
from src.database.models import Article, Base, Watch

_BOUND = 0.3  # seconds: the producers' bound, shrunk for the test
# A read that runs for seconds and cannot finish within _BOUND: the progress handler interrupts it.
_SLOW_SQL = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 30000000) SELECT count(*) FROM c"


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'w.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def home(monkeypatch, tmp_path):
    path = tmp_path / "briefing_cache.json"
    monkeypatch.setattr(service, "_cache_path", lambda: path)
    monkeypatch.setattr(service, "_article_count", lambda _s: 0)
    monkeypatch.setattr(service, "_stoplist_fingerprint", lambda: None)
    monkeypatch.setattr(ins, "warm_cache", lambda _s: {"warmed": []})
    monkeypatch.setattr(service, "dismissed_ids", lambda: set())
    monkeypatch.setattr(registry, "_disabled_names", lambda: set())
    monkeypatch.setattr(service, "PRODUCER_DEADLINE_S", _BOUND)
    ran: list[str] = []

    def _producers(*_a, **_k):
        ran.append("producers")
        return [Card(type="lonely_signal", key="k", title="t", summary="s", bucket="investigate", n=1, method="m",
                     caveat="c")], {"truncated": False}

    monkeypatch.setattr(service, "run_all_bounded", _producers)
    return ran


def _articles(db, n: int) -> list[int]:
    now = datetime.now(UTC)
    ids = []
    for i in range(n):
        a = Article(url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T", content="x",
                    hash=f"h{i}", language="en", published_at=now - timedelta(hours=1), created_at=now)
        db.add(a)
        db.flush()
        ids.append(a.id)
    db.commit()
    return ids


def _watches(db) -> tuple[int, int]:
    slow = W.create_watch(db, name="Slow", query="slow", threshold=2, window_days=7)
    later = W.create_watch(db, name="Later", query="later", threshold=2, window_days=7)
    db.commit()
    return slow.id, later.id


def _stamped(db, wid: int):
    db.expire_all()
    return db.get(Watch, wid).last_evaluated_at


def test_a_slow_watch_pass_is_stopped_at_the_bound_and_home_says_which_cards_are_missing(db, home, monkeypatch):
    ids = _articles(db, 3)
    slow_id, later_id = _watches(db)

    def _matcher(session, query):
        if query == "slow":
            session.execute(text(_SLOW_SQL)).scalar()
        return list(ids)

    monkeypatch.setattr(W, "_fts_matcher", _matcher)
    began = time.monotonic()
    payload = service.refresh_briefing(db)
    took = time.monotonic() - began
    assert took < 5, f"the watch pass was not bounded: the refresh took {took:.1f} s"
    assert home == ["producers"]  # the producers still ran after the stop
    assert [c["type"] for c in payload["cards"]] == ["lonely_signal"]
    assert payload["stopped_producers"] == ["watch_matches"]
    assert "incomplete_reason" not in payload  # R666's choice: no ten-minute repair loop for a bound stop
    view = service._present(payload, include_dismissed=False)
    assert view["stopped_producers"] == ["A watch matched"]
    # Neither watch is recorded as checked: the slow one was cut, the other never reached.
    assert _stamped(db, slow_id) is None and _stamped(db, later_id) is None


def test_the_next_refresh_evaluates_the_watches_the_stopped_pass_did_not_reach(db, home, monkeypatch):
    """The ruling's addition: a watch the bound stopped is evaluated (and fires) on the next run, never skipped as fresh."""
    ids = _articles(db, 3)
    slow_id, later_id = _watches(db)
    slow = {"now": True}

    def _matcher(session, query):
        if query == "slow" and slow["now"]:
            session.execute(text(_SLOW_SQL)).scalar()
        return list(ids)

    monkeypatch.setattr(W, "_fts_matcher", _matcher)
    service.refresh_briefing(db)
    db.commit()
    assert _stamped(db, slow_id) is None and _stamped(db, later_id) is None
    slow["now"] = False
    payload = service.refresh_briefing(db)
    db.commit()
    assert "stopped_producers" not in payload
    assert _stamped(db, slow_id) is not None and _stamped(db, later_id) is not None
    fired = {w["name"]: w for w in W.recent_fired_watches(db)}
    assert set(fired) == {"Slow", "Later"} and fired["Slow"]["n_articles"] == 3


def test_a_pass_that_ran_past_the_bound_without_raising_is_named_and_stops_between_watches(db, home, monkeypatch):
    """Python between statements is not interruptible, so the slow watch finishes: its firing and stamp are written (they are
    true). The loop then asks the deadline before the next watch (the progress handler fires only inside a long statement), so
    the watch after the bound is not run and not stamped; the refresh names the kind as stopped, as R666 does for a producer."""
    ids = _articles(db, 3)
    slow_id, later_id = _watches(db)

    def _matcher(_session, query):
        if query == "slow":
            time.sleep(_BOUND + 0.2)
        return list(ids)

    monkeypatch.setattr(W, "_fts_matcher", _matcher)
    payload = service.refresh_briefing(db)
    db.commit()
    assert payload["stopped_producers"] == ["watch_matches"]
    assert _stamped(db, slow_id) is not None and _stamped(db, later_id) is None
    assert {w["name"] for w in W.recent_fired_watches(db)} == {"Slow"}


def test_a_stop_inside_the_concept_lookup_is_not_taken_for_a_missing_disclosure(monkeypatch):
    """The ring lookup swallows its own errors (a disclosure must not break a pass), but not the deadline's interrupt: swallowed,
    the watch would be searched on the literal word only, stamped, and remember that narrower set (the Opus read of R695)."""
    import sqlite3

    from sqlalchemy.exc import OperationalError

    import src.analytics.queries as Q

    def _interrupted(_session):
        raise OperationalError("SELECT ...", {}, sqlite3.OperationalError("interrupted"))

    monkeypatch.setattr(Q, "keyword_frequency", _interrupted)
    with pytest.raises(OperationalError):
        W.watch_concept(object(), "flood")

    def _broken(_session):
        raise ValueError("no frequency table")

    monkeypatch.setattr(Q, "keyword_frequency", _broken)
    assert W.watch_concept(object(), "flood") is None  # any other failure is still a missing disclosure


def test_one_bad_watch_is_still_one_bad_watch(db, home, monkeypatch):
    ids = _articles(db, 3)
    slow_id, later_id = _watches(db)

    def _matcher(_session, query):
        if query == "slow":
            raise ValueError("bad query")
        return list(ids)

    monkeypatch.setattr(W, "_fts_matcher", _matcher)
    payload = service.refresh_briefing(db)
    db.commit()
    assert "stopped_producers" not in payload
    assert _stamped(db, slow_id) is not None and _stamped(db, later_id) is not None  # stamped as before: it was evaluated
    assert {w["name"] for w in W.recent_fired_watches(db)} == {"Later"}


def test_the_watch_pass_flushes_its_writes_outside_the_deadline(db, home, monkeypatch):
    """No write of the pass runs while its deadline is armed (an interrupted write would roll the session back): every flush during
    the refresh happens with no deadline on the session, and the pass's writes do land. The API's direct call (flush=True, the
    default) still flushes itself."""
    import inspect

    from sqlalchemy import event

    from src.database.maintenance import deadline_left_s

    ids = _articles(db, 3)
    _watches(db)
    monkeypatch.setattr(W, "_fts_matcher", lambda _s, _q: list(ids))
    flushes: list[float | None] = []
    event.listen(db, "before_flush", lambda session, _ctx, _inst: flushes.append(deadline_left_s(session)))
    service.refresh_briefing(db)
    assert flushes and all(left is None for left in flushes), flushes
    db.commit()
    assert {w["name"] for w in W.recent_fired_watches(db)} == {"Slow", "Later"}
    assert inspect.signature(W.evaluate_watches).parameters["flush"].default is True
