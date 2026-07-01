"""Content-provenance S1: imported newsletters carry the newsletter channel, not
the mislabelled "news" default.

The ingest path KNOWS the channel (this is the newsletter/mailbox source), so it
is an asserted fact — never Source.source_type's default "news". This pins the
fix + the deterministic self-heal for rows created before S1.

CI-only (imports the ingestion API → fastapi); skip-guarded so it is clean in the
core sandbox. The pure vocab check runs everywhere.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.taxonomy import CANONICAL_SOURCE_TYPES
from src.database.models import Base, Source

pytest.importorskip("fastapi")  # the getters live in the ingestion API module

from src.api import ingestion as I  # noqa: E402


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


def test_newsletter_is_a_canonical_channel():
    # Runs everywhere (pure): the value the fix stamps must be in the vocab so the
    # taxonomy guard and any facet accept it.
    assert "newsletter" in CANONICAL_SOURCE_TYPES
    assert I._IMPORT_SOURCE_TYPE == "newsletter"


def test_created_import_sources_are_newsletter_not_news(db):
    nl = I._get_newsletter_source(db)
    mb = I._get_mailbox_source(db)
    assert nl.source_type == "newsletter"  # NOT the "news" default
    assert mb.source_type == "newsletter"
    assert nl.enabled is False and mb.enabled is False  # unchanged: import sources stay disabled


def test_self_heals_a_pre_s1_mislabelled_row(db):
    # A source created before S1 carries the default "news" — accessing it corrects it.
    db.add(Source(name=I._NEWSLETTER_NAME, domain=I._NEWSLETTER_DOMAIN,
                  enabled=False, source_type="news"))
    db.commit()
    healed = I._get_newsletter_source(db)
    assert healed.source_type == "newsletter"
    # Idempotent: a second access is a no-op on the same row.
    again = I._get_newsletter_source(db)
    assert again.id == healed.id and again.source_type == "newsletter"


def test_default_source_type_is_news_proving_the_bug(db):
    # Guard the premise: a plain Source defaults to "news", which is exactly why the
    # import paths must stamp the channel explicitly.
    s = Source(name="x", domain="x.example")
    db.add(s)
    db.commit()
    db.refresh(s)
    assert s.source_type == "news"
