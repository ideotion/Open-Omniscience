"""The cross-file link check: it REPORTS, and it never repairs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``article_id`` crosses a database boundary SQLite cannot constrain, so the property
under test is that the disagreement is COUNTED honestly rather than tidied away. The
tidying is what these tests exist to forbid: a check that NULLed a dangling link
would report clean forever after, having destroyed the evidence that a version was
once indexed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db
from src.versioned import integrity, revisions, store
from src.versioned.models import VersionedEntity, VersionedRevision

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _article(corpus, slug: str) -> Article:
    """One minimally-valid corpus Article.

    Built field by field rather than through a factory because the NOT NULL set is
    exactly what a lane's ``article_id`` has to point at, and a helper that filled
    it from somewhere else would hide a change to it.
    """
    url = f"https://example.invalid/{slug}"
    return Article(
        title=slug,
        url=url,
        canonical_url=url,
        source_id=_source(corpus),
        content="x",
        hash=hashlib.sha256(url.encode("utf-8")).hexdigest(),
    )


def _source(corpus) -> int:
    """One corpus source, because ``Article.source_id`` is NOT NULL."""
    row = corpus.query(Source).filter_by(domain="example.invalid").one_or_none()
    if row is None:
        row = Source(name="Fixture", domain="example.invalid", country="FRA")
        corpus.add(row)
        corpus.flush()
    return row.id


#: The prefix every Article this file writes lives under, so the sweep below can find
#: them all and touch nothing else in the shared corpus.
CORPUS_PREFIX = "https://example.invalid/"


def _forget_our_articles() -> None:
    """Remove this file's Articles from the SHARED corpus.

    MEASURED, and NOT optional here — unlike in ``test_versioned_lane.py``, where the
    equivalent sweep is insulation. ``src/database/session.py`` builds its engine at
    IMPORT time (session.py:124), so ``monkeypatch.setenv("OO_DATA_DIR", ...)`` moves
    the LANE (whose engine cache is keyed on the resolved path) and does NOT move the
    corpus. Every test in this file therefore writes into one database, and the second
    one to insert ``.../page`` hits ``UNIQUE constraint failed: articles.hash``. That
    is the failure this function was written from, not one it was written against.
    """
    with SessionLocal() as corpus:
        corpus.query(Article).filter(Article.canonical_url.like(f"{CORPUS_PREFIX}%")).delete(
            synchronize_session=False
        )
        corpus.commit()


@pytest.fixture
def both(tmp_path, monkeypatch):
    """A lane of this test's own, plus the (shared) corpus, swept clean on both edges."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.create_lane("wiki")
    init_db()
    _forget_our_articles()
    try:
        yield
    finally:
        _forget_our_articles()
        store.dispose_all()


def _linked_revision(article_id: int | None, ref: str = "1") -> None:
    with store.lane_session("wiki") as session:
        entity = session.query(VersionedEntity).filter_by(external_id="oo:Page").one_or_none()
        if entity is None:
            entity = VersionedEntity(external_id="oo:Page", title="Page", watching=True)
            session.add(entity)
            session.flush()
            revisions.capture_baseline(
                session, entity, revision_ref="0", text="base\n", revised_at=T0
            )
        revisions.record_revision(
            session,
            entity,
            revision_ref=ref,
            text=f"body {ref}\n",
            revised_at=T0,
            article_id=article_id,
        )


def test_a_lane_with_no_links_reports_ZERO_OF_ZERO_not_clean_by_luck(both):
    """``0 of 0`` and ``0 of 4,912`` are different facts; the report keeps them apart."""
    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        report = integrity.check_article_links(lane, corpus)
    assert report.linked == 0
    assert report.dangling == 0
    assert report.clean is True


def test_a_link_the_corpus_HONOURS_is_not_counted_as_dangling(both):
    with SessionLocal() as corpus:
        article = _article(corpus, "page")
        corpus.add(article)
        corpus.commit()
        article_id = article.id

    _linked_revision(article_id)

    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        report = integrity.check_article_links(lane, corpus)
    assert report.linked == 1
    assert report.dangling == 0, report.as_dict()


def test_a_DELETED_article_makes_its_link_dangle_and_the_link_SURVIVES_the_check(both):
    """The whole point: the check reports, and leaves the lane exactly as it found it.

    Repairing would be a destructive guess — NULLing throws away the knowledge that
    this version WAS indexed, and only the operator knows whether the corpus or the
    lane is the stale one.
    """
    with SessionLocal() as corpus:
        article = _article(corpus, "page")
        corpus.add(article)
        corpus.commit()
        article_id = article.id

    _linked_revision(article_id)

    with SessionLocal() as corpus:
        corpus.query(Article).filter(Article.id == article_id).delete()
        corpus.commit()

    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        report = integrity.check_article_links(lane, corpus)
    assert report.dangling == 1, report.as_dict()
    assert report.linked == 1
    assert report.sample == [article_id]
    assert report.clean is False

    # ...and the lane still holds the link, untouched.
    with store.lane_session("wiki") as lane:
        row = lane.query(VersionedRevision).filter_by(revision_ref="1").one()
        assert row.article_id == article_id, "the check repaired what it was asked to report"


def test_the_report_carries_its_METHOD_and_its_CAVEAT_with_the_numbers(both):
    """A reader of the dict must not have to find the module to learn it is a
    point-in-time reading of two files with no shared transaction."""
    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        payload = integrity.check_article_links(lane, corpus).as_dict()
    assert payload["method"], payload
    assert "shared transaction" in payload["caveat"], payload["caveat"]
    assert payload["checked_at"], "the reading names no instant"


def test_the_check_survives_more_links_than_SQLITE_takes_VARIABLES(both):
    """A lane with tens of thousands of linked revisions is ordinary.

    An ``IN`` clause built from all of them raises ``too many SQL variables`` — on
    exactly the corpora large enough for this check to matter, and never in a small
    test written without thinking about it.
    """
    with SessionLocal() as corpus:
        rows = [_article(corpus, f"p{i}") for i in range(1200)]
        corpus.add_all(rows)
        corpus.commit()
        ids = [r.id for r in rows]

    with store.lane_session("wiki") as lane:
        entity = VersionedEntity(external_id="oo:Page", title="Page", watching=True)
        lane.add(entity)
        lane.flush()
        revisions.capture_baseline(lane, entity, revision_ref="0", text="b\n", revised_at=T0)
        for i, article_id in enumerate(ids, start=1):
            lane.add(
                VersionedRevision(
                    entity_id=entity.id,
                    revision_ref=str(i),
                    observed_at=T0,
                    revised_at=T0,
                    content_hash="0" * 64,
                    byte_size=1,
                    article_id=article_id,
                )
            )

    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        report = integrity.check_article_links(lane, corpus)
    assert report.linked == 1200, report.as_dict()
    assert report.dangling == 0, report.as_dict()


def test_the_link_check_SPLITS_its_work_instead_of_one_giant_IN_clause(both):
    """Asserted structurally, because the limit it guards cannot be reached in a test.

    MEASURED on this machine: both drivers accept 250,000 host parameters, so no
    affordable fixture reaches the ceiling and a "does it raise" test would be green
    for the wrong reason. The ceiling is a per-BUILD setting, though, so the property
    worth pinning is that the work is SPLIT — which is what protects an operator whose
    SQLCipher was compiled with a lower one.
    """
    from unittest.mock import patch

    from src.versioned.lanes import CHUNK_SIZE

    count = CHUNK_SIZE * 2 + 5
    with SessionLocal() as corpus:
        rows = [_article(corpus, f"chunk{i}") for i in range(count)]
        corpus.add_all(rows)
        corpus.commit()
        ids = [r.id for r in rows]

    with store.lane_session("wiki") as lane:
        entity = VersionedEntity(external_id="oo:Page", title="Page", watching=True)
        lane.add(entity)
        lane.flush()
        for i, article_id in enumerate(ids, start=1):
            lane.add(
                VersionedRevision(
                    entity_id=entity.id,
                    revision_ref=str(i),
                    observed_at=T0,
                    revised_at=T0,
                    content_hash="0" * 64,
                    byte_size=1,
                    article_id=article_id,
                )
            )

    with store.lane_session("wiki") as lane, SessionLocal() as corpus:
        with patch.object(corpus, "execute", wraps=corpus.execute) as spy:
            report = integrity.check_article_links(lane, corpus)
        statements = spy.call_count

    assert report.linked == count, report.as_dict()
    assert report.dangling == 0, report.as_dict()
    # ceil(805 / 400) == 3 statements against the corpus, never one.
    expected = -(-count // CHUNK_SIZE)
    assert statements == expected, (
        f"{count} ids went to the corpus in {statements} statement(s); expected {expected}"
    )
