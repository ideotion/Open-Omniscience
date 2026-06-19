"""Counter freshness + reconcile + honesty envelope (data-architecture Slice 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintained counters (mention_count / article_count) are exact by construction
across ingest/re-index (test_keyword_counters.py). This file covers the SLICE-2
honesty layer on top: ``last_reconciled_at``, the bounded background reconcile, and
the envelope that discloses the counters as ``exact`` (freshly reconciled) vs
``estimated`` (unreconciled / stale, may have drifted via a cascade delete).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import (
    counter_envelope,
    index_article,
    maybe_reconcile_counters,
    reconcile_keyword_counters,
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


def _article(db, hash_, text, *, when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="Title",
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


def _assert_counters_match_join(db) -> None:
    db.expire_all()
    live = _live_counts(db)
    for kw in db.query(Keyword).all():
        exp = live.get(kw.id, (0, 0))
        assert (kw.mention_count, kw.article_count) == exp, (
            f"drift on keyword {kw.id} {kw.normalized_term!r}: "
            f"stored=({kw.mention_count},{kw.article_count}) live={exp}"
        )


def _ingest_some(db):
    ex = BaselineExtractor()
    index_article(db, _article(db, "a1", "Senate debates the federal budget bill today."),
                  extractor=ex)
    index_article(db, _article(db, "a2", "The federal budget passed after a long debate."),
                  extractor=ex)


# --------------------------------------------------------------------------- #


def test_fresh_ingest_is_exact_by_construction_but_envelope_is_estimated(db):
    """Counters are correct right after ingest, but until a reconcile VERIFIES them the
    envelope discloses `estimated` (last_reconciled_at is NULL = unverified)."""
    _ingest_some(db)
    _assert_counters_match_join(db)  # correct by construction
    env = counter_envelope(db)
    assert env.basis == "estimated"  # never reconciled -> unverified
    assert env.as_of  # real serve-time, never empty
    assert env.n and env.n > 0


def test_reconcile_stamps_and_reports_exact(db):
    _ingest_some(db)
    res = reconcile_keyword_counters(db)
    assert res["drift_repaired"] == 0  # ingest kept them exact
    assert res["with_mentions"] > 0
    _assert_counters_match_join(db)
    env = counter_envelope(db)
    assert env.basis == "exact"
    assert env.is_exact()
    # Every counter-backing keyword carries a watermark now.
    assert db.query(Keyword).filter(
        Keyword.mention_count > 0, Keyword.last_reconciled_at.is_(None)
    ).count() == 0


def test_injected_drift_shows_estimated_then_repairs_to_exact(db):
    """The acceptance scenario: drift accumulates un-reconciled (a cascade delete the
    incremental hook can't see), the envelope honestly flips to `estimated` once stale,
    and the reconcile repairs the value to the live GROUP BY and restores `exact`."""
    _ingest_some(db)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    reconcile_keyword_counters(db, now=t0)
    assert counter_envelope(db, now=t0).basis == "exact"

    # Inject drift: corrupt one keyword's counter directly (simulating a CASCADE delete
    # that bypassed the ORM maintenance hook). The watermark stays at t0.
    kw = db.query(Keyword).filter(Keyword.mention_count > 0).first()
    kw.mention_count = kw.mention_count + 999
    db.commit()

    later = t0 + timedelta(hours=25)  # past the 24h freshness window
    assert counter_envelope(db, now=later).basis == "estimated"

    res = reconcile_keyword_counters(db, now=later)
    assert res["drift_repaired"] == 1  # exactly the one we corrupted
    _assert_counters_match_join(db)  # repaired to the canonical truth
    assert counter_envelope(db, now=later).basis == "exact"


def test_envelope_goes_estimated_when_stale_by_window(db):
    _ingest_some(db)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    reconcile_keyword_counters(db, now=t0)
    # Within the window -> exact; beyond it -> estimated (may have drifted since).
    assert counter_envelope(db, now=t0 + timedelta(hours=1)).basis == "exact"
    assert counter_envelope(db, now=t0 + timedelta(hours=48)).basis == "estimated"


def test_empty_corpus_is_exact(db):
    env = counter_envelope(db)
    assert env.basis == "exact"
    assert env.value == 0 and env.n == 0


def test_maybe_reconcile_noops_when_fresh_runs_when_stale(db):
    _ingest_some(db)
    assert maybe_reconcile_counters(db).get("skipped") is None  # was estimated -> ran
    assert maybe_reconcile_counters(db) == {"skipped": "fresh"}  # now fresh -> no-op


def test_reconcile_matches_live_group_by_after_changes(db):
    """Counter ranking identical to the live GROUP BY through ingest, drift and repair."""
    _ingest_some(db)
    reconcile_keyword_counters(db)
    _assert_counters_match_join(db)
    # Add another article, re-reconcile, still matches.
    index_article(db, _article(db, "a3", "Budget talks continue in the Senate chamber."),
                  extractor=BaselineExtractor())
    reconcile_keyword_counters(db)
    _assert_counters_match_join(db)


def test_envelope_dict_has_no_score_shaped_key(db):
    _ingest_some(db)
    d = counter_envelope(db).to_dict()
    assert set(d) == {"value", "basis", "as_of", "method", "n"}
    assert not any(
        bad in k.lower() for k in d for bad in ("score", "trust", "rank", "rating", "verdict")
    )
