"""Keyword counters after a backup MERGE — the drift, and its repair.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FOUND 2026-07-29 while attacking a different question. Read-verified first, then
reproduced here BEFORE any fix was written (the project's reproducer-first rule).

THE MECHANISM, in two independent halves:

1. THE MERGE NEVER MOVES THE COUNTERS. ``_merge_keywords``' INSERT column list
   (src/backup/merge.py) carries term/normalized_term/language/frequency/... and NOT
   ``mention_count``/``article_count``, so a keyword arriving from a backup lands at
   the column default 0; an ALREADY-PRESENT keyword is matched by ``WHERE NOT EXISTS``
   and never updated at all. Meanwhile ``_merge_keyword_mentions`` copies the incoming
   ``keyword_mentions`` rows straight in. Result: real mentions, zero counters.

2. THE RE-INDEX THEN SUBTRACTS A CONTRIBUTION THAT WAS NEVER ADDED. ``index_article``
   captures ``old_contrib`` from the LIVE mention rows for that article -- which after
   a merge ARE the imported rows -- and applies ``new - old`` as the counter delta. So
   the merged mentions are treated as though they had already been counted.

Neither half is hypothetical: both are asserted below against the real
``index_article``/``reindex_articles``, and both were confirmed RED before the fix.

``src/backup/merge.py`` reconciles ``Source.article_count`` three lines from where the
keyword counters are left alone, for exactly this reason ("a wrong count shown as
exact"). This module pins the symmetric guarantee for keywords.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import backfill_keyword_counters, reindex_articles
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _reindex_importable() -> bool:
    """``reindex_articles`` pulls in ``src.database.write``, which uses PEP 695 generic
    syntax (``def f[T](...)``) and therefore needs Python >= 3.12. Probe the CAPABILITY
    rather than guessing from the platform (the project's own dbstat lesson); the repo
    targets 3.13, so this only ever skips on an older local interpreter, never in CI."""
    try:
        import src.database.write  # noqa: F401
    except SyntaxError:
        return False
    return True


_needs_reindex = pytest.mark.skipif(
    not _reindex_importable(),
    reason="reindex_articles needs src.database.write (PEP 695 generics, Python >= 3.12)",
)


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


def _live_counts(db) -> dict[int, tuple[int, int]]:
    return {
        kid: (int(m or 0), int(a or 0))
        for kid, m, a in db.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        ).group_by(KeywordMention.keyword_id)
    }


def _drifted(db) -> dict[int, tuple[tuple[int, int], tuple[int, int]]]:
    """{keyword_id: (stored, live)} for every keyword whose counter disagrees."""
    db.expire_all()
    live = _live_counts(db)
    out = {}
    for kw in db.query(Keyword).all():
        stored = (kw.mention_count or 0, kw.article_count or 0)
        exp = live.get(kw.id, (0, 0))
        if stored != exp:
            out[kw.id] = (stored, exp)
    return out


def _merge_one_article(db, *, hash_, text, terms):
    """Exactly what a restore's merge does for one imported article: insert the
    article, insert its keywords WITHOUT counter columns, insert its mentions.

    Deliberately hand-rolled rather than driving the full restore engine: this pins
    the ARITHMETIC, needs no staging/crypto, and stays readable as the specification
    of what the merge leaves behind.
    """
    art = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="T",
        content=text,
        hash=hash_,
        country="fr",
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(art)
    db.flush()
    for term, count in terms.items():
        kw = db.query(Keyword).filter_by(normalized_term=term).first()
        if kw is None:
            # NOTE the omission: no mention_count, no article_count -- the merge's
            # own INSERT column list, reproduced.
            kw = Keyword(term=term, normalized_term=term, language="en", frequency=0)
            db.add(kw)
            db.flush()
        db.add(
            KeywordMention(
                keyword_id=kw.id,
                article_id=art.id,
                count=count,
                observed_on=datetime(2024, 3, 1, tzinfo=UTC).date(),
                country="fr",
                source_id=1,
                extractor="baseline",
                created_at=datetime.now(UTC),
            )
        )
    db.commit()
    return art


# --------------------------------------------------------------------------- #
#  1. the merge leaves the counters behind
# --------------------------------------------------------------------------- #
def test_a_merge_leaves_every_counter_at_zero_while_the_mentions_are_real(db):
    _merge_one_article(db, hash_="m1", text="climate policy", terms={"climate": 3, "policy": 2})

    live = _live_counts(db)
    assert live, "the merged mentions are real rows"
    assert sum(m for m, _ in live.values()) == 5

    drift = _drifted(db)
    assert drift, (
        "REPRODUCED: every merged keyword's counter disagrees with the live aggregate"
    )
    assert all(stored == (0, 0) for stored, _ in drift.values()), (
        "the merge inserts keywords at the column default and never moves the counters"
    )


def test_an_existing_keyword_is_matched_but_never_updated(db):
    """The NOT EXISTS branch: a keyword the corpus ALREADY has gains merged mentions
    but keeps whatever counter it had, so the drift is not limited to new keywords."""
    _merge_one_article(db, hash_="m1", text="climate", terms={"climate": 2})
    backfill_keyword_counters(db)
    db.commit()
    assert not _drifted(db), "baseline: repaired"

    _merge_one_article(db, hash_="m2", text="climate again", terms={"climate": 4})
    drift = _drifted(db)
    kw = db.query(Keyword).filter_by(normalized_term="climate").one()
    assert kw.id in drift, "the second merge's mentions never reached the counter"
    assert drift[kw.id] == ((2, 1), (6, 2))


# --------------------------------------------------------------------------- #
#  2. the re-index makes it worse, not better
# --------------------------------------------------------------------------- #
@_needs_reindex
def test_the_post_merge_reindex_subtracts_a_contribution_never_added(db):
    """The half that makes this more than a cosmetic lag: ``old_contrib`` is read from
    the live mention rows, which after a merge ARE the imported rows -- so the delta
    nets to ~0 and the counters stay wrong even after the work that was supposed to
    make them right."""
    art = _merge_one_article(
        db, hash_="m1", text="Climate policy dominated the talks. Climate climate.",
        terms={"climate": 3, "policy": 2},
    )

    reindex_articles(db, extractor=BaselineExtractor(), article_ids=[art.id])
    db.commit()

    drift = _drifted(db)
    assert drift, (
        "REPRODUCED: the re-index did NOT repair the merged corpus's counters -- it "
        "read its 'old' contribution from the merged rows themselves"
    )


# --------------------------------------------------------------------------- #
#  3. the repair (what the fix must guarantee)
# --------------------------------------------------------------------------- #
def test_the_reconcile_repairs_the_drift_and_is_idempotent(db):
    _merge_one_article(db, hash_="m1", text="climate policy", terms={"climate": 3, "policy": 2})
    _merge_one_article(db, hash_="m2", text="policy energy", terms={"policy": 1, "energy": 7})
    assert _drifted(db), "precondition: drifted"

    backfill_keyword_counters(db)
    db.commit()
    assert not _drifted(db), "every counter now equals its live aggregate"

    backfill_keyword_counters(db)
    db.commit()
    assert not _drifted(db), "idempotent -- a second repair changes nothing"


def test_run_restore_reconciles_unconditionally_not_only_after_a_successful_reindex():
    """The drift comes from the MERGE, so it exists whether or not the re-index ran --
    and it must also be repaired on the re-index's own failure path.

    Scoped to run_restore's own body and to the ``if reindex_imported:`` block within
    it: a whole-file substring search would happily pass against code that only
    reconciles inside that branch, which is precisely the bug this pins against (the
    project's recorded "a removal guard is only as strong as the scope it searches"
    lesson).
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
    body = re.split(r"\n(?:async )?def run_restore\(", src.read_text(encoding="utf-8"))[1]
    nxt = re.search(r"\n(?:async )?(?:def|class) ", body)
    body = body[: nxt.start()] if nxt else body

    assert 'timings.stage("keyword_counter_reconcile")' in body
    assert "backfill_keyword_counters" in body

    # The reconcile must NOT live inside the `if reindex_imported:` block. That block
    # ends at the first line whose indentation returns to its own level, so slice it
    # out and assert the reconcile is not in it.
    start = body.index("if reindex_imported:")
    rest = body[start:]
    end = len(rest)
    for m in re.finditer(r"\n(        )(?=\S)", rest):  # back to 8-space (stage) indent
        if m.start() > 0:
            end = m.start()
            break
    reindex_block = rest[:end]
    assert "keyword_counter_reconcile" not in reindex_block, (
        "the counter reconcile is nested inside `if reindex_imported:` -- a restore that "
        "skips the re-index would then never repair the merge's counter drift"
    )


def test_the_reconcile_zeroes_a_keyword_whose_mentions_are_gone(db):
    """A counter must never linger high after its mentions disappear, or the repair
    would trade one wrong number for another."""
    _merge_one_article(db, hash_="m1", text="climate", terms={"climate": 3})
    backfill_keyword_counters(db)
    db.commit()

    db.query(KeywordMention).delete()
    db.commit()
    backfill_keyword_counters(db)
    db.commit()

    kw = db.query(Keyword).filter_by(normalized_term="climate").one()
    assert (kw.mention_count, kw.article_count) == (0, 0)
