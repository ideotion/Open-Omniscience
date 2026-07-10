"""The /status noprobe fallback cache key — per-call by construction, bind-qualified.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The probe-unavailable fallback keyed on ``id(db)`` — a per-request Session address that
CPython RECYCLES, so within the cache TTL a later request's Session could land on the
same address and hit a cached /status computed for a DIFFERENT engine (wrong corpus) or
for a pre-write snapshot (with the ``data_version`` probe down, writes are invisible to
the key — the ALPHA lesson: per-connection state is blind on pools). The key is now a
monotonic nonce (can never recur) qualified by the BIND, so a wrong hit is impossible by
construction; the cost is caching (each noprobe call recomputes), never correctness.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.api.insights as insights
from src.database.models import Article, Base, Source


def _mk(tmp_path, name: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True)


@pytest.fixture(autouse=True)
def _probe_down(monkeypatch):
    """Simulate the probe-unavailable path (a pool/driver where PRAGMA data_version
    cannot be read) and reset the probe registry around each test."""
    insights._reset_status_probe_for_tests()
    monkeypatch.setattr(insights, "_data_version", lambda bind: None)
    yield
    insights._reset_status_probe_for_tests()


def test_noprobe_key_is_per_call_and_bind_qualified(tmp_path):
    engine, Sess = _mk(tmp_path, "a.db")
    s = Sess()
    k1 = insights._status_cache_key(s)
    k2 = insights._status_cache_key(s)  # SAME session, SAME address — still a new key
    assert k1 != k2, "per-call by construction: a recycled Session id can never collide"
    assert f"e{id(engine)}" in k1, "the bind qualifier keeps the key attributable"
    assert "noprobe" in k1
    s.close()


def test_two_engines_can_never_share_a_noprobe_key(tmp_path):
    """The wrong-corpus shape: even if two request Sessions were allocated at the same
    address (GC reuse), their keys differ — nonce plus bind, never id(db)."""
    engine_a, SessA = _mk(tmp_path, "a.db")
    engine_b, SessB = _mk(tmp_path, "b.db")
    sa, sb = SessA(), SessB()
    ka = insights._status_cache_key(sa)
    kb = insights._status_cache_key(sb)
    assert ka != kb
    assert f"e{id(engine_a)}" in ka and f"e{id(engine_b)}" in kb
    assert str(id(sa)) not in ka, "the Session address is no longer part of the key"
    sa.close(), sb.close()


def test_status_never_serves_stale_across_a_cross_connection_write(tmp_path, monkeypatch):
    """The two-connection behavioral skeptic (the ALPHA lesson): with the probe down and
    the TTL cache ACTIVE, a write on ANOTHER connection must still be visible to the next
    poll — the per-call key forfeits caching instead of ever serving the pre-write count."""
    monkeypatch.setattr(insights, "_CACHE_TTL_S", 120)  # cache active
    _engine, Sess = _mk(tmp_path, "c.db")

    seed = Sess()
    seed.add(Source(name="S", domain="x.test", country="fr"))
    seed.commit()
    seed.close()

    poller_a = Sess()
    before = insights.insights_status(db=poller_a)
    poller_a.close()

    writer = Sess()  # a DIFFERENT pooled connection than the poller's
    writer.add(
        Article(
            url="https://x.test/new", canonical_url="https://x.test/new", source_id=1,
            title="T", content="x", hash="n" * 16, language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
    )
    writer.commit()
    writer.close()

    poller_b = Sess()
    after = insights.insights_status(db=poller_b)
    poller_b.close()
    assert after["total_articles"] == before["total_articles"] + 1, (
        "the cross-connection write is visible immediately — a stale cached /status "
        "was the exact hazard of the recycled-id key"
    )
    assert after.get("cached") is not True, "noprobe polls recompute, never a wrong hit"
