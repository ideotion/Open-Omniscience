"""Restore must collapse incoming-internal duplicates in tables that have no
schema-level unique constraint (commodity_prices, article_links,
article_source_relationships) -- the same class of gap the keyword_mentions
crash exposed (2026-07-16), just here it can never crash (no constraint to
violate) so it silently perpetuated duplicate-looking rows instead.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import (
    Article,
    ArticleLink,
    ArticleSourceRelationship,
    Base,
    CommodityPrice,
    ExternalSource,
    Source,
)

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.0.9",
    "alembic_rev": "head",
    "manifest": None,
}


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _add_article(s, *, hashv: str = "H1") -> int:
    src = s.query(Source).first()
    if src is None:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
    a = Article(
        url=f"https://wire.example/{hashv}",
        canonical_url=f"https://wire.example/{hashv}",
        source_id=src.id,
        title="t",
        content="c",
        hash=hashv,
        language="en",
        created_at=datetime.now(UTC),
    )
    s.add(a)
    s.flush()
    return int(a.id)


def _count(path: Path, table: str) -> int:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())  # noqa: S608
    finally:
        engine.dispose()


def test_incoming_duplicate_commodity_price_rows_collapse_to_one(tmp_path):
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()  # empty local corpus

    Maker = _corpus(staged)
    with Maker() as s:
        # Two rows sharing the exact same observation identity, no schema constraint
        # stops this -- the merge's own dedup key treats them as one observation.
        s.add(
            CommodityPrice(
                symbol="Nd", market="china_spot", observed_on=date(2026, 1, 1),
                price=100.0, currency="USD", unit="kg", source="fred",
            )
        )
        s.add(
            CommodityPrice(
                symbol="Nd", market="china_spot", observed_on=date(2026, 1, 1),
                price=100.0, currency="USD", unit="kg", source="fred",
            )
        )
        s.commit()

    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert _count(working, "commodity_prices") == 1
    assert counts["commodity_prices"]["new"] == 1


def test_incoming_duplicate_article_link_rows_collapse_to_one(tmp_path):
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s)
        s.add(ArticleLink(article_id=aid, url="https://x.test/ref", normalized_url="https://x.test/ref"))
        s.add(ArticleLink(article_id=aid, url="https://x.test/ref", normalized_url="https://x.test/ref"))
        s.commit()

    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert _count(working, "article_links") == 1
    assert counts["article_links"]["new"] == 1


def test_a_link_repeated_at_different_positions_is_not_collapsed(tmp_path):
    """A genuinely repeated hyperlink at TWO different positions in the same
    article is NOT a duplicate -- the collapse must only fire within a (article,
    url, position) group, never across distinct positions."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s)
        s.add(ArticleLink(article_id=aid, url="https://x.test/ref",
                           normalized_url="https://x.test/ref", position=10))
        s.add(ArticleLink(article_id=aid, url="https://x.test/ref",
                           normalized_url="https://x.test/ref", position=200))
        s.commit()

    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert _count(working, "article_links") == 2
    assert counts["article_links"]["new"] == 2


def test_incoming_duplicate_article_source_relationship_rows_collapse_to_one(tmp_path):
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s)
        ext = ExternalSource(domain="ext.example", name="Ext")
        s.add(ext)
        s.flush()
        s.add(
            ArticleSourceRelationship(
                article_id=aid, source_id=ext.id, relationship_type="cites",
            )
        )
        s.add(
            ArticleSourceRelationship(
                article_id=aid, source_id=ext.id, relationship_type="cites",
            )
        )
        s.commit()

    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert _count(working, "article_source_relationships") == 1
    assert counts["article_source_relationships"]["new"] == 1
