"""Import recomputes CORE-ENGINE metadata; AI artifacts kept verbatim.

P0-4 (maintainer ruling, field test 2026-06-19, #O-1): an imported backup may have
been produced by an OLDER extraction engine, so its keyword/date/place/entity rows can
be misaligned with the improved engine. On restore we merge raw articles + AI artifacts
verbatim, then re-run index_article on the IMPORTED articles. AI artifacts
(article_analyses summaries/translations, ai_keyword) are NOT touched by index_article,
so they survive byte-for-byte. This is consistent with the additive-merge non-negotiable
(nothing replaced/deleted — only the imported articles' DERIVED metadata is recomputed).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import reindex_articles
from src.database.models import (
    AiKeyword,
    Article,
    ArticleAnalysis,
    Base,
    KeywordMention,
    Source,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, hash_, text):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="Imported",
        content=text,
        hash=hash_,
        country="fr",
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_reindex_recomputes_core_engine_and_keeps_ai_artifacts_verbatim(db):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "imp1", "The election in France saw record inflation and a climate summit.")

    # The imported article carries AI artifacts (expensive LLM output) that must survive.
    db.add(
        ArticleAnalysis(
            article_id=art.id, kind="summary", result="An AI summary that must not change.", model="llama"
        )
    )
    db.add(AiKeyword(article_id=art.id, term="ai-only-term", kind="keyword", model="llama"))
    db.commit()

    # Simulate an old backup whose derived rows are absent/misaligned: no mentions yet.
    assert db.query(KeywordMention).filter_by(article_id=art.id).count() == 0

    out = reindex_articles(db, extractor=BaselineExtractor(), article_ids=[art.id])
    assert out["reindexed"] == 1 and out["failed"] == 0

    # CORE-ENGINE metadata recomputed with the CURRENT engine.
    mentions = db.query(KeywordMention).filter_by(article_id=art.id).count()
    assert mentions > 0, "imported article was not re-indexed by the current engine"

    # AI artifacts untouched (verbatim).
    ana = db.query(ArticleAnalysis).filter_by(article_id=art.id).all()
    assert len(ana) == 1 and ana[0].result == "An AI summary that must not change."
    ak = db.query(AiKeyword).filter_by(article_id=art.id).all()
    assert len(ak) == 1 and ak[0].term == "ai-only-term"


def test_reindex_articles_skips_missing_ids(db):
    out = reindex_articles(db, extractor=BaselineExtractor(), article_ids=[9999])
    assert out == {"reindexed": 0, "failed": 0}


def test_reindex_imported_articles_targets_only_merged_rows():
    """End-to-end on the live DB: only the articles named in merged_rows for a batch
    are re-indexed (not the whole corpus)."""
    from src.backup.merge import reindex_imported_articles
    from src.database.models import MergeBatch, MergedRow
    from src.database.session import init_db, session_scope

    init_db()
    merged_id = unmerged_id = batch_id = None
    try:
        with session_scope() as s:
            if not s.query(Source).filter_by(domain="reimp.test").first():
                s.add(Source(name="RS", domain="reimp.test", country="fr"))
                s.flush()
            merged = _article(s, "reimp-merged", "Sanctions and an energy crisis hit the economy.")
            unmerged = _article(s, "reimp-local", "A pandemic and a vaccine rollout dominated.")
            merged_id, unmerged_id = merged.id, unmerged.id
            batch = MergeBatch(artifact_kind="oo-backup-2", origin_fingerprint="unsigned", status="merged")
            s.add(batch)
            s.flush()
            batch_id = batch.id
            s.add(MergedRow(batch_id=batch_id, table_name="articles", row_id=merged_id))
            s.commit()

        out = reindex_imported_articles(batch_id)
        assert out["reindexed"] == 1 and out["failed"] == 0

        with session_scope() as s:
            assert s.query(KeywordMention).filter_by(article_id=merged_id).count() > 0
            # The non-imported local article was NOT touched (targeted, not corpus-wide).
            assert s.query(KeywordMention).filter_by(article_id=unmerged_id).count() == 0
    finally:
        with session_scope() as s:
            for aid in (merged_id, unmerged_id):
                if aid is not None:
                    s.query(KeywordMention).filter_by(article_id=aid).delete()
                    a = s.get(Article, aid)
                    if a is not None:
                        s.delete(a)
            if batch_id is not None:
                s.query(MergedRow).filter_by(batch_id=batch_id).delete()
                b = s.get(MergeBatch, batch_id)
                if b is not None:
                    s.delete(b)
            s.commit()
