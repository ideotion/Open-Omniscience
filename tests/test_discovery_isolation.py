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


#: Every row these tests write carries this in its domain (or belongs to a source that does), so the teardown removes exactly them.
_MARK = "discovery-isolation.example"


@pytest.fixture()
def db():
    """A session on the suite's store, cleaned of THIS module's rows only.

    It used to delete every candidate, article and source in the store before and after each test: in a process where an earlier test
    had left a row that references a source (a link, a fetch state, a keyword), ``DELETE FROM sources`` failed on its foreign key, the
    setup erred and its open transaction kept the write lock (random order, seed 1111) -- and where it succeeded it wiped other tests' rows from the store they share. The
    assertions below read this test's own rows instead of whole-table counts."""
    init_db()
    s = SessionLocal()
    try:
        yield s
        s.rollback()
        mine = [sid for (sid,) in s.query(Source.id).filter(Source.domain.like(f"%{_MARK}"))]
        s.query(SourceCandidate).filter(SourceCandidate.domain.like(f"%{_MARK}")).delete(synchronize_session=False)
        if mine:
            s.query(Article).filter(Article.source_id.in_(mine)).delete(synchronize_session=False)
            s.query(Source).filter(Source.id.in_(mine)).delete(synchronize_session=False)
        s.commit()
    finally:
        # A delete that raised above leaves its transaction open, and with it the store's write lock: every later test in the process
        # that writes then read "database is locked" (seed 1111: the old fixture's failed DELETE FROM sources was followed on the same
        # worker by eight lock errors in four other files). The rollback gives the lock back whatever happened.
        s.rollback()
        s.close()


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def test_discovery_failure_never_rolls_back_the_scrape(db, monkeypatch):
    """A UNIQUE collision inside discovery must be contained to its savepoint:
    run_discovery returns cleanly (never raises), the session stays usable, and
    the article the scrape stored before discovery survives the commit."""
    tag = uuid.uuid4().hex[:6]
    src = Source(name="S", domain=f"s-{tag}.{_MARK}", language="en")
    collide = f"collide-{tag}.{_MARK}"
    db.add(src)
    db.flush()
    db.add(
        Article(
            url=f"https://s-{tag}.{_MARK}/1",
            canonical_url=f"https://s-{tag}.{_MARK}/1",
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
            domain=collide, channel="catalog", status="candidate",
            first_seen=_now(), last_seen=_now(),
        )
    )
    db.flush()

    monkeypatch.setattr(channels, "citation_channel", lambda s, **k: [])

    def _colliding_catalog(s, **k):
        channels._add_candidate(s, domain=collide, name=None, channel="catalog", evidence={})
        return [collide]

    monkeypatch.setattr(channels, "catalog_channel", _colliding_catalog)

    out = channels.run_discovery(db, per_run=4)  # must NOT raise
    assert out["created"] == 0 and out.get("error") == "discovery_rolled_back"

    db.commit()  # the session must still be usable (not poisoned)
    assert db.query(Article).filter_by(source_id=src.id).count() == 1, "the scraped article must survive a discovery failure"
    assert db.query(SourceCandidate).filter_by(domain=collide).count() == 1, "no duplicate row"


def test_run_discovery_disabled_is_a_noop(db):
    assert channels.run_discovery(db, per_run=0) == {"enabled": False, "created": 0}
