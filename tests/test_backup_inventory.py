"""
Tests for the unified-backup inventory (what's available + sizes).

In-memory SQLite -> runs in CI. Blob totals are monkeypatched (the real ones read
the live download dirs).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup import inventory as inv
from src.database.models import Article, ArticleMentionedDate, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db):
    db.add(Source(name="S", domain="s.test"))
    db.flush()
    for i in range(2):
        a = Article(
            url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}",
            source_id=1, title="T", content="x", hash=f"h{i}", language="en",
        )
        db.add(a)
        db.flush()
        db.add(ArticleMentionedDate(article_id=a.id, mentioned_on=datetime.now(UTC).date()))
    db.commit()


def test_corpus_breakdown_counts_include_dates(db, monkeypatch):
    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 12345)
    _seed(db)
    out = inv.backup_inventory(db)
    assert out["corpus"]["always"] is True
    assert out["corpus"]["bytes"] == 12345
    b = out["corpus"]["breakdown"]
    assert b["articles"] == 2
    assert b["sources"] == 1
    assert b["dates"] == 2  # "dates, amongst else" are visibly inside the corpus


def test_blob_categories_are_mapped_and_default_zero(db, monkeypatch):
    monkeypatch.setattr(
        inv, "_blob_totals",
        lambda: {"models": {"count": 3, "bytes": 900}, "osm_regions": {"count": 1, "bytes": 500}},
    )
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    assert out["models"] == {"count": 3, "bytes": 900}
    assert out["maps"] == {"count": 1, "bytes": 500}   # osm_regions -> maps
    assert out["wiki"] == {"count": 0, "bytes": 0}     # absent -> zero


def test_no_session_still_returns_blob_inventory(monkeypatch):
    monkeypatch.setattr(inv, "_blob_totals", lambda: {"wiki_dumps": {"count": 2, "bytes": 7}})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 42)
    out = inv.backup_inventory(None)
    assert out["wiki"] == {"count": 2, "bytes": 7}
    assert out["corpus"]["bytes"] == 42
    assert "breakdown" not in out["corpus"]  # no session -> no counts, no crash
