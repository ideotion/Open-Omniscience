"""Offline source discovery must NEVER break the scrape (field log 2026-06-18).

Discovery runs as a best-effort step at the END of every collection pass, on the
SAME session as the scrape. A UNIQUE collision on ``source_candidates.domain``
used to raise during flush, poison the shared transaction, and roll back the
articles the scrape had just stored — so every pass was recorded ``ok: false``
and the corpus stopped growing ("scraping stopped"). Data collection is the heart
of the project, so a side feature must never be able to break it.

Two guarantees, pinned here:
  * run_discovery runs inside a SAVEPOINT — a failure rolls back only discovery's
    own rows; the outer transaction (the scraped articles) stays committable;
  * the channels never propose the same domain twice in one batch (the in-batch
    UNIQUE guard), which was the actual collision (the packaged catalog can list
    a domain more than once across language editions).

No fastapi / no network: drives SessionLocal directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

import src.discovery.channels as channels
from src.database.models import Article, Source, SourceCandidate
from src.database.session import SessionLocal, init_db


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    # deterministic slate
    s.query(SourceCandidate).delete()
    s.query(Article).delete()
    s.query(Source).delete()
    s.commit()
    yield s
    s.rollback()
    s.query(SourceCandidate).delete()
    s.query(Article).delete()
    s.query(Source).delete()
    s.commit()
    s.close()


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def test_discovery_failure_never_rolls_back_the_scrape(db, monkeypatch):
    """A UNIQUE collision inside discovery must be contained to its savepoint:
    run_discovery returns cleanly (never raises), the session stays usable, and
    the article the scrape stored before discovery survives the commit."""
    src = Source(name="S", domain=f"s-{uuid.uuid4().hex[:6]}.example", language="en")
    db.add(src)
    db.flush()
    db.add(
        Article(
            url="https://s.example/1",
            canonical_url="https://s.example/1",
            source_id=src.id,
            title="t",
            content="x " * 50,
            language="en",
            hash=uuid.uuid4().hex * 2,
        )
    )
    db.flush()
    # A candidate that already exists; force discovery to (wrongly) re-add it.
    db.add(
        SourceCandidate(
            domain="collide.example", channel="catalog", status="candidate",
            first_seen=_now(), last_seen=_now(),
        )
    )
    db.flush()

    monkeypatch.setattr(channels, "citation_channel", lambda s, **k: [])

    def _colliding_catalog(s, **k):
        channels._add_candidate(s, domain="collide.example", name=None, channel="catalog", evidence={})
        return ["collide.example"]

    monkeypatch.setattr(channels, "catalog_channel", _colliding_catalog)

    out = channels.run_discovery(db, per_run=4)  # must NOT raise
    assert out["created"] == 0 and out.get("error") == "discovery_rolled_back"

    db.commit()  # the session must still be usable (not poisoned)
    assert db.query(Article).count() == 1, "the scraped article must survive a discovery failure"
    assert db.query(SourceCandidate).filter_by(domain="collide.example").count() == 1, "no duplicate row"


def test_run_discovery_disabled_is_a_noop(db):
    assert channels.run_discovery(db, per_run=0) == {"enabled": False, "created": 0}
