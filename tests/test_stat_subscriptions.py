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
