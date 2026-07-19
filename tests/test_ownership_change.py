"""Ownership-change deal-language producer (Leads-calibration S3.2, row 11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The deal-verb regex (acquir*/merg*/takeover/buyout/divest*/...) is ENGLISH ONLY. The
2026-07-18 field export caught it false-cognate-matching Romanian "merge" ("goes", as
in "Israelul merge la urne" = "Israel goes to the polls") against the English verb
stem "merg*" ("merger"/"merging"). These tests pin: an English deal-language article
still fires; a non-English article carrying the false-cognate substring never does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing.producers import ownership_change
from src.database.models import Article, Base, Source


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


def _art(db, aid, title, content, *, lang, days_ago=2):
    db.add(Article(
        id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
        source_id=1, title=title, content=content, hash=f"h{aid}", language=lang,
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
    ))


def test_fires_on_english_deal_language(db):
    db.add(Source(id=1, name="BizWire", domain="biz.test"))
    db.commit()
    _art(db, 1, "TechCo announces merger with rival firm",
         "The board approved the merger after months of negotiation.", lang="en")
    db.commit()
    cards = ownership_change(db)
    assert len(cards) == 1
    assert cards[0].article_ids == [1]


def test_romanian_merge_false_cognate_never_fires(db):
    """Row 11: Romanian "merge" (goes) is not the English verb "merge/merger"."""
    db.add(Source(id=1, name="RomaniaWire", domain="ro.test"))
    db.commit()
    _art(
        db, 1, "Israelul merge la urne in scrutinul de mâine",
        "Netanyahu a declarat ca Israelul merge la urne pentru un nou scrutin.",
        lang="ro",
    )
    db.commit()
    assert ownership_change(db) == []


def test_non_english_deal_language_stays_silent_even_with_real_english_verbs(db):
    """The language gate is on the ARTICLE's asserted language, not a text sniff --
    conservative (never guess a translation), even if English deal words appear."""
    db.add(Source(id=1, name="Wire", domain="wire.test"))
    db.commit()
    _art(db, 1, "Une entreprise acquiert un concurrent",
         "L'entreprise a acquis son concurrent dans le cadre d'une fusion (merger).",
         lang="fr")
    db.commit()
    assert ownership_change(db) == []
