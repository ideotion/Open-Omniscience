"""Denormalised keyword counters (mention_count / article_count) — drift guards.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The whole point of these columns is that they stay EXACTLY equal to the live
``SUM(count)`` / ``COUNT(DISTINCT article_id)`` GROUP BY they replace — through
ingest AND re-index. The killer assertion :func:`assert_counters_match_join`
compares every stored counter to that live aggregate; the tests drive it across the
re-index paths that could drift (same article twice, changed content removing/adding
keywords) and prove it is NON-VACUOUS (a deliberately corrupted counter is caught,
and the backfill repairs it).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import (
    backfill_corpus,
    backfill_keyword_counters,
    index_article,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _article(db, hash_, text, *, title="T", when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title=title,
        content=text,
        hash=hash_,
        country="fr",
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def _live_counts(db) -> dict[int, tuple[int, int]]:
    """The authoritative per-keyword counters straight from the mentions table."""
    rows = (
        db.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .group_by(KeywordMention.keyword_id)
        .all()
    )
    return {kid: (int(m or 0), int(a or 0)) for kid, m, a in rows}


def assert_counters_match_join(db) -> None:
    """Every stored counter == the live GROUP BY (the drift detector).

    ``expire_all`` first so we read what is actually PERSISTED, not a stale ORM
    instance — a counter that was changed in memory but never committed would be
    caught here too.
    """
    db.expire_all()
    live = _live_counts(db)
    for kw in db.query(Keyword).all():
        exp_m, exp_a = live.get(kw.id, (0, 0))
        assert (kw.mention_count, kw.article_count) == (exp_m, exp_a), (
            f"counter drift on keyword {kw.id} {kw.normalized_term!r}: "
            f"stored=({kw.mention_count}, {kw.article_count}) live=({exp_m}, {exp_a})"
        )


def test_counters_match_join_after_ingest(db):
    _article(db, "h1", "Trade policy and climate policy shaped the talks. Trade trade trade.")
    _article(db, "h2", "Energy prices rose. Energy policy and climate policy dominated debate.")
    art3 = _article(db, "h3", "Election results surprised analysts and shifted the landscape.")
    for art in db.query(Article).all():
        index_article(db, art, extractor=BaselineExtractor())

    assert_counters_match_join(db)
    # Non-vacuous: there is real content, so at least one counter is > 1.
    assert db.query(func.max(Keyword.mention_count)).scalar() > 1
    # A keyword shared across two articles records article_count >= 2.
    shared = db.query(Keyword).filter_by(normalized_term="policy").one_or_none()
    if shared is not None:  # 'policy' survives the stoplist as content here
        assert shared.article_count >= 2
    assert art3 is not None


def test_reindex_same_article_does_not_double_counters(db):
    art = _article(db, "h1", "Trade policy and trade policy and trade policy again here now.")
    index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)
    before = {k.id: (k.mention_count, k.article_count) for k in db.query(Keyword).all()}

    # Re-indexing the SAME article must REPLACE its contribution, not add to it.
    index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)
    after = {k.id: (k.mention_count, k.article_count) for k in db.query(Keyword).all()}
    assert before == after  # unchanged, not doubled

    # A third pass is still stable.
    index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)


def test_reindex_changed_content_adjusts_counters(db):
    art = _article(db, "h1", "Trade policy and trade tariffs and trade barriers dominated.")
    index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)
    trade = db.query(Keyword).filter_by(normalized_term="trade").one()
    assert trade.article_count == 1 and trade.mention_count >= 1

    # Re-index with DISJOINT vocabulary: 'trade' is no longer mentioned by ANY
    # article, so the decrement path must take its counters to 0 (the drift risk).
    art.set_content("Energy prices and energy supply and energy markets shaped the week.")
    db.commit()
    index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)

    db.expire_all()
    trade = db.query(Keyword).filter_by(normalized_term="trade").one()
    assert (trade.mention_count, trade.article_count) == (0, 0)
    energy = db.query(Keyword).filter_by(normalized_term="energy").one()
    assert energy.article_count == 1 and energy.mention_count >= 1


def test_article_count_is_distinct_articles_not_occurrences(db):
    # 'satellite' mentioned MANY times in ONE article: mention_count high, article_count 1.
    a1 = _article(db, "h1", "Satellite satellite satellite satellite imagery confirmed it.")
    # 'satellite' mentioned in TWO articles -> article_count 2.
    a2 = _article(db, "h2", "A satellite passed overhead during the satellite launch window.")
    index_article(db, a1, extractor=BaselineExtractor())
    index_article(db, a2, extractor=BaselineExtractor())
    assert_counters_match_join(db)

    sat = db.query(Keyword).filter_by(normalized_term="satellite").one()
    assert sat.article_count == 2
    assert sat.mention_count >= 5  # 4 in a1 + >=1 in a2
    assert a1 and a2


def test_backfill_repairs_drift_and_guard_is_non_vacuous(db):
    for h, txt in [
        ("h1", "Trade policy and climate policy and trade policy dominated the summit."),
        ("h2", "Energy and climate policy and energy supply shaped the debate this week."),
    ]:
        index_article(db, _article(db, h, txt), extractor=BaselineExtractor())
    assert_counters_match_join(db)

    # Deliberately CORRUPT a counter, then prove the guard catches it (non-vacuous).
    kw = db.query(Keyword).order_by(Keyword.mention_count.desc()).first()
    kw.mention_count = kw.mention_count + 7
    kw.article_count = kw.article_count + 3
    db.commit()
    with pytest.raises(AssertionError):
        assert_counters_match_join(db)

    # The backfill recomputes from the live mentions and repairs it.
    res = backfill_keyword_counters(db)
    assert res["keywords"] >= 1 and res["with_mentions"] >= 1
    assert_counters_match_join(db)


def test_backfill_zeroes_keywords_with_no_mentions(db):
    art = _article(db, "h1", "Inflation and inflation expectations and inflation pressures rose.")
    index_article(db, art, extractor=BaselineExtractor())
    inflation = db.query(Keyword).filter_by(normalized_term="inflation").one()
    assert inflation.mention_count >= 1

    # Strip every mention (the article was retracted), leaving the keyword orphaned
    # with a stale non-zero counter. The backfill must zero it.
    db.query(KeywordMention).delete()
    inflation.mention_count = 99
    inflation.article_count = 9
    db.commit()
    backfill_keyword_counters(db)
    assert_counters_match_join(db)
    db.expire_all()
    inflation = db.query(Keyword).filter_by(normalized_term="inflation").one()
    assert (inflation.mention_count, inflation.article_count) == (0, 0)


def test_backfill_corpus_path_maintains_counters(db):
    # The GUI "index corpus" backfill path runs index_article per article, so the
    # incremental maintenance must also hold there.
    _article(db, "h1", "Drought and drought conditions and water scarcity gripped the region.")
    _article(db, "h2", "Floods and heavy rain and drought elsewhere marked the season.")
    r = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    assert r["indexed"] == 2
    assert_counters_match_join(db)


def test_reindex_all_batch_refreshes_every_article_paged(db):
    """§3.F: reindex_all_batch FORCE-re-indexes ALL articles (not just un-indexed)
    so a markup/extractor fix can drain stale rows. It pages via last_id and reports
    done; counters stay consistent after the drain."""
    from src.analytics.store import reindex_all_batch

    a1 = _article(db, "h1", "Trade policy and climate policy shaped the talks.")
    a2 = _article(db, "h2", "Energy policy and climate policy dominated the debate.")
    a3 = _article(db, "h3", "Election results surprised analysts across the region.")
    for art in (a1, a2, a3):
        index_article(db, art, extractor=BaselineExtractor())
    assert_counters_match_join(db)

    # Page in batches of 2: first batch covers a1+a2, second a3, then done.
    r1 = reindex_all_batch(db, extractor=BaselineExtractor(), limit=2, after_id=0)
    assert r1["reindexed"] == 2 and r1["last_id"] == a2.id and r1["done"] is False
    r2 = reindex_all_batch(db, extractor=BaselineExtractor(), limit=2, after_id=r1["last_id"])
    assert r2["reindexed"] == 1 and r2["done"] is True and r2["remaining"] == 0
    assert_counters_match_join(db)


def test_reindex_all_batch_drains_stale_keywords(db):
    """A re-index after an extractor fix removes keywords the old run produced. Simulate
    by indexing markup-y content, then re-indexing after stripping it: the stale tokens go."""
    from src.analytics.extract import strip_markup
    from src.analytics.store import reindex_all_batch

    art = _article(db, "h1", '<div class="x" style="max-width:10px">Trade policy and climate policy here.</div>')
    # Simulate an OLD engine that did NOT strip markup: index the raw content directly.
    art.content = '<div class="x" style="max-width:10px">Trade policy and climate policy here.</div>'
    db.commit()
    index_article(db, art, extractor=BaselineExtractor())
    # The current engine strips markup, so a re-index must not leave CSS/markup tokens.
    reindex_all_batch(db, extractor=BaselineExtractor(), limit=10, after_id=0)
    assert_counters_match_join(db)
    terms = {k.normalized_term for k in db.query(Keyword).filter(Keyword.mention_count > 0).all()}
    assert "div" not in terms and "max-width" not in terms, "stale markup keywords must be drained"
    # The current strip would have removed them at index time anyway (sanity).
    assert "<div" not in strip_markup(art.content)


def test_prune_orphan_keywords_removes_only_mention_less(db):
    """Keyword reduction (2026-06-21): prune_orphan_keywords GCs keywords with NO
    mentions left (the markup-drain / merge-orphan backlog) while keeping every keyword
    that still has a mention — junk-removal, never a cap."""
    from src.analytics.store import prune_orphan_keywords
    from src.database.models import Keyword, KeywordMention

    a1 = _article(db, "h1", "Trade policy and climate policy shaped the talks.")
    index_article(db, a1, extractor=BaselineExtractor())
    assert_counters_match_join(db)

    # Inject an ORPHAN keyword (no mentions) — simulates a term left after a re-index drain.
    orphan = Keyword(term="divstyle", normalized_term="divstyle", language="en")
    db.add(orphan)
    db.commit()
    before = db.query(func.count(Keyword.id)).scalar()
    has_mentions = {kid for (kid,) in db.query(KeywordMention.keyword_id).distinct()}

    r = prune_orphan_keywords(db)
    assert r["pruned"] >= 1
    # The orphan is gone; every keyword that had a mention survives.
    assert db.query(Keyword).filter_by(normalized_term="divstyle").one_or_none() is None
    surviving = {k.id for k in db.query(Keyword).all()}
    assert has_mentions <= surviving, "a keyword with mentions must never be pruned"
    assert db.query(func.count(Keyword.id)).scalar() == before - r["pruned"]
    assert_counters_match_join(db)


def test_prune_keeps_curated_orphan(db):
    """A mention-less keyword that the user curated into a family override is KEPT."""
    from src.analytics.store import prune_orphan_keywords
    from src.database.models import Keyword, KeywordFamilyOverride

    kw = Keyword(term="merged", normalized_term="merged", language="en")
    db.add(kw)
    db.add(KeywordFamilyOverride(normalized_term="merged", family_key="fam"))
    db.commit()
    r = prune_orphan_keywords(db)
    assert r["kept_curated"] >= 1
    assert db.query(Keyword).filter_by(normalized_term="merged").one_or_none() is not None


def test_mention_distribution_counts_orphans(db):
    """The engine report's mention_distribution surfaces the prunable (zero-mention)
    bucket so the keyword count is explainable before pruning."""
    from src.analytics.engine_report import _mention_distribution
    from src.database.models import Keyword

    a1 = _article(db, "h1", "Energy policy and climate policy dominated the debate.")
    index_article(db, a1, extractor=BaselineExtractor())
    db.add(Keyword(term="orphanx", normalized_term="orphanx", language="en"))
    db.commit()
    dist = _mention_distribution(db)
    assert dist["zero_mention"] >= 1
    assert "by_mentions" in dist and "51+" in dist["by_mentions"]
