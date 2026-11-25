"""The import's keyword-counter reconcile, scoped to the keywords the imported articles mention (row 424).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scoped pass must give every keyword it touches exactly the counters the whole-corpus sweep gives it, and leave every
keyword it does not touch as it found it (counters AND stamp), so the honesty envelope still sees drift that was already
elsewhere. Pinned on a hand-built mixed case and on random corpora against ``reconcile_keyword_counters`` itself.
"""

from __future__ import annotations

import inspect
import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics.store import (
    counter_envelope,
    reconcile_keyword_counters,
    reconcile_keyword_counters_for_articles,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from tests._app_engine import app_sqlite_engine

T_OLD = datetime(2026, 11, 1, tzinfo=UTC)
T_NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _articles(db, n: int, start: int = 0) -> list[int]:
    rows = [
        Article(
            url=f"https://x.test/{start + i}",
            canonical_url=f"https://x.test/{start + i}",
            source_id=1,
            title="T",
            content="c",
            hash=f"h{start + i}",
            language="en",
            created_at=T_OLD,
        )
        for i in range(n)
    ]
    db.add_all(rows)
    db.commit()
    return [a.id for a in rows]


def _keywords(db, n: int) -> list[int]:
    rows = [Keyword(term=f"k{i}", normalized_term=f"k{i}", language="en") for i in range(n)]
    db.add_all(rows)
    db.commit()
    return [k.id for k in rows]


def _mention(db, kid: int, aid: int, count: int) -> None:
    db.add(KeywordMention(keyword_id=kid, article_id=aid, count=count))


def _state(db) -> dict[int, tuple[int, int, datetime | None]]:
    db.expire_all()
    return {
        k.id: (int(k.mention_count or 0), int(k.article_count or 0), k.last_reconciled_at)
        for k in db.query(Keyword).order_by(Keyword.id)
    }


def _counts(state: dict) -> dict[int, tuple[int, int]]:
    return {k: (m, a) for k, (m, a, _t) in state.items()}


def test_a_mixed_import_matches_the_sweep_on_what_it_touches_and_leaves_the_rest(db):
    old = _articles(db, 3)
    new = _articles(db, 3, start=100)
    shared, only_old, only_new, drifted_elsewhere, quarantine_only = _keywords(db, 5)
    # The live corpus, swept once and exact.
    _mention(db, shared, old[0], 2)
    _mention(db, shared, old[1], 1)
    _mention(db, only_old, old[2], 4)
    _mention(db, drifted_elsewhere, old[2], 3)
    db.commit()
    reconcile_keyword_counters(db, now=T_OLD, budget_s=0, restart=True)
    # Drift that predates this import, on a keyword the import never mentions.
    db.query(Keyword).filter(Keyword.id == drifted_elsewhere).update({Keyword.mention_count: 99})
    # The import: an existing keyword gains mentions, a new keyword arrives at 0, a quarantined article mentions both.
    _mention(db, shared, new[0], 5)
    _mention(db, only_new, new[0], 1)
    _mention(db, only_new, new[1], 2)
    _mention(db, shared, new[2], 7)
    _mention(db, quarantine_only, new[2], 1)
    db.query(Article).filter(Article.id == new[2]).update({Article.quarantined: True})
    db.commit()
    before = _state(db)

    out = reconcile_keyword_counters_for_articles(db, new, now=T_NOW, budget_s=0)
    scoped = _state(db)

    touched = {shared, only_new, quarantine_only}
    assert out["keywords_in_scope"] == len(touched) and out["complete"] is True
    assert scoped[shared][:2] == (2 + 1 + 5, 3)  # the quarantined article's 7 counts for nothing (R101)
    assert scoped[only_new][:2] == (3, 2)
    assert scoped[quarantine_only][:2] == (0, 0)
    for kid in touched:
        assert scoped[kid][2] is not None and scoped[kid][2].replace(tzinfo=UTC) == T_NOW
    for kid in (only_old, drifted_elsewhere):
        assert scoped[kid] == before[kid], "a keyword the import does not mention keeps its counters and its stamp"

    reconcile_keyword_counters(db, now=T_NOW, budget_s=0, restart=True)
    swept = _state(db)
    for kid in touched:
        assert _counts(scoped)[kid] == _counts(swept)[kid]
    assert swept[drifted_elsewhere][0] == 3, "the sweep still repairs the drift the scoped pass left alone"


@pytest.mark.parametrize("run_min", [64, 2])
@pytest.mark.parametrize("seed", range(12))
def test_random_corpora_match_the_whole_corpus_sweep(db, seed, run_min, monkeypatch):
    """``run_min`` 2 reads every consecutive pair of imported ids as a BETWEEN range, and 64 none of them, so both ways of
    gathering the keywords are held to the sweep."""
    import src.analytics.store as store

    monkeypatch.setattr(store, "_SCOPED_RUN_MIN", run_min)
    monkeypatch.setattr(store, "_SCOPED_ARTICLE_CHUNK", 7)  # runs are cut at the chunk too
    rng = random.Random(seed)
    aids = _articles(db, 40)
    kids = _keywords(db, 25)
    for aid in aids:
        for kid in rng.sample(kids, rng.randint(0, 8)):
            _mention(db, kid, aid, rng.randint(1, 6))
    db.commit()
    for aid in rng.sample(aids, 5):
        db.query(Article).filter(Article.id == aid).update({Article.quarantined: True})
    for kid in rng.sample(kids, 8):  # wrong counters, inside and outside the import's reach
        db.query(Keyword).filter(Keyword.id == kid).update(
            {Keyword.mention_count: rng.randint(0, 50), Keyword.article_count: rng.randint(0, 9)}
        )
    db.commit()
    imported = rng.sample(aids, rng.randint(1, 15))
    touched = {m.keyword_id for m in db.query(KeywordMention).filter(KeywordMention.article_id.in_(imported))}
    before = _state(db)

    reconcile_keyword_counters_for_articles(db, imported, now=T_NOW, budget_s=0)
    scoped = _state(db)
    for kid in kids:
        if kid not in touched:
            assert scoped[kid] == before[kid]

    reconcile_keyword_counters(db, now=T_NOW, budget_s=0, restart=True)
    swept = _state(db)
    for kid in touched:
        assert scoped[kid] == swept[kid]


def test_small_chunks_and_a_spent_budget_stop_between_chunks_and_say_so(db, monkeypatch):
    import src.analytics.store as store

    monkeypatch.setattr(store, "_SCOPED_ARTICLE_CHUNK", 3)
    monkeypatch.setattr(store, "_SCOPED_KEYWORD_CHUNK", 2)
    aids = _articles(db, 7)
    kids = _keywords(db, 6)
    for i, aid in enumerate(aids):
        _mention(db, kids[i % 6], aid, i + 1)
    db.commit()
    full = reconcile_keyword_counters_for_articles(db, aids, now=T_NOW, budget_s=0)
    assert full["keywords"] == 6 and full["complete"] is True

    clock = iter([0.0])  # the pass's own start, then every later reading is past the budget
    monkeypatch.setattr("time.monotonic", lambda: next(clock, 100.0))
    part = reconcile_keyword_counters_for_articles(db, aids, now=T_NOW, budget_s=1.0)
    assert part["complete"] is False and part["keywords"] == 2, "the first chunk always runs, the rest wait"


def test_it_never_moves_the_sweeps_cursor_and_the_envelope_follows_the_stamps(db):
    from src.analytics.store import RECONCILE_CURSOR_KEY, _cursor_get, _cursor_set

    aids = _articles(db, 2)
    a, b = _keywords(db, 2)
    _mention(db, a, aids[0], 1)
    _mention(db, b, aids[1], 1)
    db.query(Keyword).update({Keyword.mention_count: 1, Keyword.article_count: 1})  # as index-time upkeep leaves them
    db.commit()
    _cursor_set(db, RECONCILE_CURSOR_KEY, 17)
    db.commit()
    reconcile_keyword_counters_for_articles(db, [aids[0]], now=T_NOW, budget_s=0)
    assert _cursor_get(db, RECONCILE_CURSOR_KEY) == 17
    # b has mentions and was never verified, so the counters are not all exact yet.
    assert not counter_envelope(db, now=T_NOW).is_exact()
    reconcile_keyword_counters_for_articles(db, aids, now=T_NOW, budget_s=0)
    assert counter_envelope(db, now=T_NOW + timedelta(minutes=1)).is_exact()


def test_the_import_reconciles_its_own_keywords_first_and_sweeps_only_when_not_exact():
    """Pinned on the source, as the neighbouring stage tests are: the scoped pass runs on the swap group's articles,
    the sweep follows only when the envelope is not exact, and an underivable group or an import over a quarter of the
    corpus sweeps everything."""
    from src.backup import merge

    body = inspect.getsource(merge.run_restore)
    stage = body.split('with timings.stage("keyword_counter_reconcile"):', 1)[1].split("with timings.stage(", 1)[0]
    assert "reconcile_keyword_counters_for_articles(" in stage
    assert "if swap_batches is not None" in stage and "_rc_ids is None or len(_rc_ids) * 4 > _rc_total" in stage
    assert "reconcile_keyword_counters(_cnt_sess)" in stage
    assert "counter_envelope(_cnt_sess).is_exact()" in stage
    assert "table_name = 'articles'" in stage
