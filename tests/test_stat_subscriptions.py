"""Scheduled stat-vintage auto-refresh (ruling 2026-06-17 #12).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A user fetch is RECORDED as a subscription; the scheduler REPLAYS due subscriptions to
capture new vintages. These tests pin the honest contract: idempotent recording,
freshness gating (only due subs replay), airplane gating (no socket offline), vintage-
additive storage, and best-effort isolation. No network — the getter is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, StatFigure
from src.ingest import activate_kill_switch, clear_kill_switch
from src.stats import subscriptions as S


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()
        clear_kill_switch()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _wb_payload(value):
    return [
        {"page": 1, "pages": 1, "per_page": 1, "total": 1},
        [{"indicator": {"id": "NY.GDP.MKTP.CD"}, "countryiso3code": "FRA",
          "date": "2021", "value": value, "unit": ""}],
    ]


def test_record_subscription_is_idempotent(db):
    s1 = S.record_subscription(db, source="worldbank", indicator="NY.GDP.MKTP.CD", country="FR")
    db.commit()
    s2 = S.record_subscription(db, source="worldbank", indicator="NY.GDP.MKTP.CD", country="FR")
    db.commit()
    assert s1.id == s2.id  # same fetch -> one subscription
    assert len(S.list_subscriptions(db)) == 1
    # A different country is a different subscription.
    S.record_subscription(db, source="worldbank", indicator="NY.GDP.MKTP.CD", country="DE")
    db.commit()
    assert len(S.list_subscriptions(db)) == 2


def test_due_logic_respects_interval(db):
    s = S.record_subscription(db, source="worldbank", indicator="X", country="FR", interval_days=30)
    db.commit()
    # Never fetched -> due.
    assert [x.id for x in S.due_subscriptions(db)] == [s.id]
    # Fetched just now -> not due.
    s.last_fetched_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    assert S.due_subscriptions(db) == []
    # Fetched 40 days ago -> due again.
    s.last_fetched_at = (datetime.now(UTC) - timedelta(days=40)).replace(tzinfo=None)
    db.commit()
    assert [x.id for x in S.due_subscriptions(db)] == [s.id]
    # Disabled -> never due.
    s.enabled = False
    db.commit()
    assert S.due_subscriptions(db) == []


def test_refresh_due_stores_a_new_vintage(db):
    S.record_subscription(db, source="worldbank", indicator="NY.GDP.MKTP.CD", country="FR")
    db.commit()
    clear_kill_switch()
    out = S.refresh_due(db, get=lambda url: _FakeResp(_wb_payload(2.9e12)))
    db.commit()
    assert out["refreshed"] == 1 and out["stored"] == 1 and out["skipped_offline"] == 0
    # The subscription is stamped + a figure landed.
    sub = S.list_subscriptions(db)[0]
    assert sub["last_fetched_at"] is not None and "stored 1" in sub["last_status"]
    assert db.execute(select(StatFigure)).scalars().first().value == 2.9e12
    # Now fresh -> a second refresh is not due.
    assert S.refresh_due(db, get=lambda url: _FakeResp(_wb_payload(3.0e12)))["refreshed"] == 0


def test_refresh_is_airplane_gated_no_socket(db):
    S.record_subscription(db, source="worldbank", indicator="X", country="FR")
    db.commit()
    activate_kill_switch()
    try:
        def forbidden(url):
            raise AssertionError("no socket may be opened in airplane mode")

        out = S.refresh_due(db, get=forbidden)
        assert out["skipped_offline"] == 1 and out["refreshed"] == 0 and out["stored"] == 0
    finally:
        clear_kill_switch()


def test_refresh_is_best_effort_per_subscription(db):
    S.record_subscription(db, source="worldbank", indicator="GOOD", country="FR")
    S.record_subscription(db, source="worldbank", indicator="BAD", country="FR")
    db.commit()
    clear_kill_switch()

    def getter(url):
        if "BAD" in url:
            raise RuntimeError("endpoint 500")
        return _FakeResp(_wb_payload(1.0))

    out = S.refresh_due(db, get=getter)
    db.commit()
    assert out["refreshed"] == 1 and out["errors"] == 1  # GOOD stored, BAD recorded
    statuses = {s["indicator"]: s["last_status"] for s in S.list_subscriptions(db)}
    assert "stored 1" in statuses["GOOD"] and statuses["BAD"].startswith("error:")


def test_refresh_does_not_carry_the_write_gate_across_the_next_fetch(monkeypatch):
    """H1-1: ``store_figures`` flushes (which takes the write gate and keeps it to the end of
    the transaction), so the next subscription's request used to run with the gate held.
    Probed on the REAL gate-wired ``SessionLocal``: while subscription 2's fetch is in flight
    the gate is free, and a second thread can take it. The twin proves the writes still pass
    THROUGH the gate (a never-taken gate would satisfy the first half just as well)."""
    import threading

    from src.database.session import init_db, session_scope
    from src.database.writer import write_gate

    init_db()
    clear_kill_switch()
    with session_scope() as s:
        S.record_subscription(s, source="worldbank", indicator="H1.ONE", country="FR")
        S.record_subscription(s, source="worldbank", indicator="H1.TWO", country="DE")

    fetches: list[str] = []
    seen: list[tuple[str, bool, bool]] = []
    grants_before = write_gate.stats()["grants"]

    def getter(url):
        fetches.append(url)
        taken = None
        if len(fetches) > 1:  # every fetch after the first has a flushed predecessor
            held = write_gate.stats()["held"]

            from src.database.writer import write_lock

            result: list[bool] = []

            def other_thread():
                with write_lock(timeout=2):
                    result.append(True)

            t = threading.Thread(target=other_thread)
            t.start()
            t.join(5)
            taken = bool(result)
            seen.append((url, held, taken))
        return _FakeResp(_wb_payload(1.0))

    with session_scope() as s:
        out = S.refresh_due(s, get=getter)
    # The suite database may hold other due subscriptions, so pin this test's own two rows.
    with session_scope() as s:
        mine = {r["indicator"]: r["last_status"] for r in S.list_subscriptions(s)
                if r["indicator"] in ("H1.ONE", "H1.TWO")}
    assert set(mine) == {"H1.ONE", "H1.TWO"}
    assert all(v.startswith("stored") for v in mine.values()), mine
    assert seen, "the second subscription's fetch never ran"
    assert all(held is False and taken for _u, held, taken in seen)
    assert write_gate.stats()["grants"] > grants_before  # the writes did go through the gate


def test_a_failed_store_ends_the_transaction_so_later_fetches_run_ungated(monkeypatch):
    """A ``store_figures`` that FLUSHES and then raises leaves the transaction open and the write
    gate held; the except branch must end it, or every later subscription's request runs gated.
    Gate-wired ``SessionLocal``; the failure is keyed on the indicator in the URL, not on order."""
    from src.database.session import init_db, session_scope
    from src.database.writer import write_gate
    import src.stats.store as store_mod

    init_db()
    clear_kill_switch()
    with session_scope() as s:
        S.record_subscription(s, source="worldbank", indicator="H1.BAD", country="FR")
        S.record_subscription(s, source="worldbank", indicator="H1.GOOD", country="DE")

    real = store_mod.store_figures
    last_url: list[str] = []
    held_at_fetch: dict[str, bool] = {}

    def flaky(session, figs):
        tally = real(session, figs)  # flushes: the gate is now held
        if "H1.BAD" in last_url[-1]:
            # A flush that FAILS poisons the transaction (needs a rollback) and keeps the gate.
            from src.database.models import StatSubscription

            first = session.query(StatSubscription).first()
            session.add(StatSubscription(id=first.id, source="worldbank", indicator="dup"))
            session.flush()  # IntegrityError
        return tally

    monkeypatch.setattr(store_mod, "store_figures", flaky)

    def getter(url):
        last_url.append(url)
        held_at_fetch["H1.GOOD" if "H1.GOOD" in url else "H1.BAD"] = write_gate.stats()["held"]
        return _FakeResp(_wb_payload(7.0))

    with session_scope() as s:
        S.refresh_due(s, get=getter)
    with session_scope() as s:
        by_ind = {r["indicator"]: r["last_status"] for r in S.list_subscriptions(s)}
    assert by_ind["H1.BAD"].startswith("error:"), by_ind
    assert by_ind["H1.GOOD"].startswith("stored"), by_ind
    # Whichever ran second fetched with the gate free (the failed one's transaction was ended).
    if len(last_url) >= 2 and "H1.BAD" in last_url[0]:
        assert held_at_fetch["H1.GOOD"] is False
