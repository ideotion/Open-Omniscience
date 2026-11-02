"""The instant title index (src/database/fts_title.py): sync, backfill, order, parity, honesty.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Behavioural on purpose: every test drives real INSERT/UPDATE/DELETE statements through the
real triggers and asks the real FTS5 table what it holds.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import fts_title
from src.database.fts import ensure_fts, search_ids
from src.database.models import Article, Base, Source


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)


def _add(Session, titles, *, start=0, quarantined=None):
    with Session() as s:
        if not s.query(Source).count():
            s.add(Source(name="S", domain="x.test"))
            s.commit()
        for i, t in enumerate(titles, start=start):
            s.add(Article(url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=t,
                          content=f"body {i}", hash=f"h{i}", language="en", quarantined=quarantined))
        s.commit()


def _store(titles=()):
    eng = _engine()
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, future=True)
    ensure_fts(eng)
    if titles:
        _add(Session, titles)
    return eng, Session


def _ids(eng, q, **kw):
    with eng.begin() as c:
        return fts_title.title_prefix_ids(c, q, **kw)


def test_ensure_is_idempotent_and_builds_nothing():
    eng, Session = _store()
    _add(Session, ["Inflation rises"])
    with eng.begin() as c:
        before = c.execute(text("SELECT count(*) FROM article_fts_title_docsize")).scalar()
    ensure_fts(eng)
    ensure_fts(eng)
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM article_fts_title_docsize")).scalar() == before
        assert c.execute(text("SELECT count(*) FROM article_fts_title_state")).scalar() == 0  # no backfill at boot


def test_triggers_keep_the_index_in_sync():
    eng, Session = _store(["Inflation rises", "Inflow of refugees", "Elections today"])
    assert _ids(eng, "inf") == [2, 1]  # newest first
    assert _ids(eng, "infl") == [2, 1]
    assert _ids(eng, "inflo") == [2]
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET title = 'Zebra crossing' WHERE id = 2"))
    assert _ids(eng, "inf") == [1] and _ids(eng, "zeb") == [2]
    with eng.begin() as c:
        c.execute(text("DELETE FROM articles WHERE id = 1"))
    assert _ids(eng, "inf") == []


def test_an_update_of_other_columns_does_not_touch_the_title_index():
    eng, Session = _store(["Inflation rises"])
    with eng.begin() as c:
        digest = [tuple(r) for r in c.execute(text("SELECT id, block FROM article_fts_title_data")).all()]
        c.execute(text("UPDATE articles SET language = 'fr' WHERE id = 1"))
        assert digest == [tuple(r) for r in c.execute(text("SELECT id, block FROM article_fts_title_data")).all()]


def test_newest_first_and_limit():
    eng, Session = _store([f"Story {i}" for i in range(30)])
    ids = _ids(eng, "st", limit=5)
    assert ids == [30, 29, 28, 27, 26]


def test_the_last_word_is_a_prefix_and_earlier_words_are_whole_words():
    eng, Session = _store(["Central bank rate cut", "Central banks rate", "Bank central"])
    assert _ids(eng, "central ba") == [3, 2, 1]
    assert _ids(eng, "central bank r") == [1]  # "banks" is not the whole word "bank"
    assert _ids(eng, "cen") == [3, 2, 1]


def test_quarantined_articles_are_left_out_and_a_never_judged_one_stays():
    eng, Session = _store(["Inflation one"])
    _add(Session, ["Inflation two"], start=10, quarantined=True)
    _add(Session, ["Inflation three"], start=20, quarantined=False)
    ids = _ids(eng, "inflation")
    with eng.begin() as c:
        rows = {r[0]: r[1] for r in c.execute(text("SELECT id, quarantined FROM articles"))}
    assert all(rows[i] is not True and rows[i] != 1 for i in ids) and len(ids) == 2
    assert len(_ids(eng, "inflation", exclude_quarantined=False)) == 3


@pytest.mark.parametrize("q", ['"', "AND", "OR NOT", "NEAR(a b)", "a*", "(", ")", "x:y", "title:foo", "-bar", "\\", "'; DROP TABLE articles; --", "^start"])
def test_fts_syntax_typed_into_the_box_is_text_not_syntax(q):
    eng, Session = _store(["Inflation rises"])
    _ids(eng, q)  # must not raise
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM articles")).scalar() == 1


def test_an_empty_or_blank_query_searches_nothing():
    eng, Session = _store(["Inflation rises"])
    assert _ids(eng, "") == [] and _ids(eng, "   ") == []
    assert fts_title.build_match("") is None


def test_a_long_paste_is_bounded():
    m = fts_title.build_match("word " * 500)
    assert m is not None and m.count(" AND ") == fts_title.MAX_WORDS - 1


def test_backfill_indexes_history_resumably_and_reports_honestly():
    eng, Session = _store()
    with eng.begin() as c:  # history that predates the index: drop the triggers, add rows, put them back
        for t in ("ai", "ad", "au"):
            c.execute(text(f"DROP TRIGGER article_fts_title_{t}"))
    _add(Session, [f"History {i}" for i in range(25)])
    ensure_fts(eng)
    with eng.begin() as c:
        s0 = fts_title.status(c)
    assert s0["present"] and not s0["complete"] and s0["covered"] == 0 and s0["articles"] == 25
    assert _ids(eng, "hist") == []
    steps = 0
    while True:
        with eng.begin() as c:
            r = fts_title.backfill_step(c, batch=7, budget_s=0.0)  # a zero budget = exactly one batch per step
        steps += 1
        if r["done"]:
            break
        assert steps < 20
    assert steps == 4  # 25 titles / 7 per batch
    with eng.begin() as c:
        s1 = fts_title.status(c)
    assert s1["complete"] and s1["covered"] == 25
    assert _ids(eng, "hist", limit=3) == [25, 24, 23]
    # An article added while the backfill ran is covered by the trigger and not double-counted.
    _add(Session, ["History new"], start=100)
    with eng.begin() as c:
        assert fts_title.status(c)["covered"] == 26


def test_status_of_a_store_without_the_table():
    eng = _engine()
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        assert fts_title.status(c)["present"] is False
        assert fts_title.title_prefix_ids(c, "abc") == []


def test_arabic_titles_are_found_by_a_folded_or_vocalised_prefix():
    eng, Session = _store(["أحمد يزور المدرسة", "مَدْرَسَةٌ جديدة"])
    assert _ids(eng, "احمد") == [1]  # alef-hamza folded, the way the main index folds it
    assert _ids(eng, "مدرس") == [2]


def test_parity_with_the_main_index_for_titles():
    """Whatever the main index finds for a whole title word, the title index finds too."""
    titles = ["Climate talks resume", "Résumé des débats", "Energy policy and climate", "Économie en 2026", "Plain story"]
    eng, Session = _store(titles)
    with Session() as s:
        for word in ["climate", "resume", "economie", "energy", "story"]:
            main = set(search_ids(s, f"title:{word}") or [])
            assert main <= set(_ids(eng, word)), word


def test_an_untitled_article_does_not_keep_the_index_from_reporting_complete():
    eng, Session = _store(["Inflation rises"])
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET title = NULL WHERE id = 1"))
    _add(Session, ["Another story"], start=50)
    with eng.begin() as c:
        c.execute(text("DELETE FROM article_fts_title_state"))
    while True:
        with eng.begin() as c:
            if fts_title.backfill_step(c)["done"]:
                break
    with eng.begin() as c:
        st = fts_title.status(c)
    assert st["complete"] and st["articles"] == 1 and st["covered"] == 1
