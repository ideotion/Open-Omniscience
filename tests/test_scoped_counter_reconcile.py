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


@pytest.mark.parametrize("seed", range(6))
def test_an_import_that_moved_only_its_own_keywords_leaves_the_whole_corpus_exact(db, seed, monkeypatch):
    """Independent of the gathering query: the expected keywords come from the generator's own record of which keyword each
    imported article mentions. The live corpus is exact; the import then moves exactly its own keywords' counters (as a
    merge at 0 or a wrong carry delta would); after the scoped pass the WHOLE corpus must equal the truth."""
    import src.analytics.store as store

    monkeypatch.setattr(store, "_SCOPED_RUN_MIN", 3)
    rng = random.Random(100 + seed)
    live = _articles(db, 30)
    new = _articles(db, 8, start=500)
    kids = _keywords(db, 20)
    mentions: dict[int, list[int]] = {}
    for aid in live + new:
        mentions[aid] = rng.sample(kids, rng.randint(1, 6))
        for kid in mentions[aid]:
            _mention(db, kid, aid, rng.randint(1, 4))
    db.commit()
    reconcile_keyword_counters(db, now=T_OLD, budget_s=0, restart=True)
    truth = _counts(_state(db))
    moved = {kid for aid in new for kid in mentions[aid]}
    for kid in moved:
        db.query(Keyword).filter(Keyword.id == kid).update(
            {Keyword.mention_count: rng.randint(0, 3), Keyword.article_count: rng.randint(0, 3)}
        )
    db.commit()
    reconcile_keyword_counters_for_articles(db, new, now=T_NOW, budget_s=0)
    assert _counts(_state(db)) == truth


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


def test_the_import_stage_hands_its_articles_to_the_routed_reconcile():
    """Pinned on the source, as the neighbouring stage tests are: the stage reads every article the swap brought in and
    hands them (or None, when the group cannot be derived) to reconcile_counters_after_import, whose routes are pinned
    behaviourally below."""
    from src.backup import merge

    body = inspect.getsource(merge.run_restore)
    stage = body.split('with timings.stage("keyword_counter_reconcile"):', 1)[1].split("with timings.stage(", 1)[0]
    assert "reconcile_counters_after_import(_cnt_sess, _rc_ids)" in stage
    assert "if swap_batches is not None" in stage and "else None" in stage
    assert "table_name = 'articles'" in stage


def _routing_corpus(db, n_live: int, n_new: int):
    from src.analytics.store import reconcile_counters_after_import  # noqa: F401 - imported where used

    live = _articles(db, n_live)
    new = _articles(db, n_new, start=1000)
    a, b = _keywords(db, 2)
    for aid in live:
        _mention(db, a, aid, 1)
    for aid in new:
        _mention(db, b, aid, 1)
    db.commit()
    db.query(Keyword).filter(Keyword.id == a).update({Keyword.mention_count: n_live, Keyword.article_count: n_live})
    db.query(Keyword).filter(Keyword.id == b).update({Keyword.mention_count: n_new, Keyword.article_count: n_new})
    db.commit()
    return new, a, b


class _SweepSpy:
    def __init__(self, monkeypatch):
        import src.analytics.store as store

        self.calls: list[float | None] = []
        real = store.reconcile_keyword_counters

        def spy(session, **kw):
            self.calls.append(kw.get("budget_s"))
            return real(session, **kw)

        monkeypatch.setattr(store, "reconcile_keyword_counters", spy)


def test_route_no_group_or_a_large_import_sweeps_the_corpus(db, monkeypatch):
    from src.analytics.store import reconcile_counters_after_import

    new, _a, _b = _routing_corpus(db, 4, 4)
    spy = _SweepSpy(monkeypatch)
    out = reconcile_counters_after_import(db, None)
    assert "could not be derived" in out["scope"] and spy.calls == [None]
    out = reconcile_counters_after_import(db, new)  # 4 of 8 articles: over a quarter
    assert "over a quarter" in out["scope"] and "keywords_in_scope" not in out


def test_route_a_small_import_into_a_recently_swept_exact_corpus_skips_the_sweep(db, monkeypatch):
    from src.analytics.store import reconcile_counters_after_import

    new, a, b = _routing_corpus(db, 12, 1)
    reconcile_keyword_counters(db, budget_s=0, restart=True)
    spy = _SweepSpy(monkeypatch)
    out = reconcile_counters_after_import(db, new)
    assert out["keywords_in_scope"] == 1 and spy.calls == []
    assert out["sweep"] == {"skipped": "the counters are exact and a whole sweep is recent"}


def test_route_the_sweep_runs_when_no_whole_sweep_is_recent_even_if_the_envelope_says_exact(db, monkeypatch):
    """The independent read's finding: the envelope reads only keywords above 0, so a keyword stored at 0 over real
    mentions is invisible to it. Without a recent whole sweep the stage must still sweep, and the sweep repairs it."""
    from src.analytics.store import reconcile_counters_after_import

    new, a, b = _routing_corpus(db, 12, 1)
    hidden = _keywords(db, 1)[0]
    _mention(db, hidden, 1, 5)
    db.commit()  # stored at 0 over a real mention: the pre-2026-07-29 drift
    reconcile_keyword_counters_for_articles(db, list(range(1, 12 + 1)) + new, budget_s=0)  # stamps a, b and hidden
    db.query(Keyword).filter(Keyword.id == hidden).update({Keyword.mention_count: 0, Keyword.article_count: 0})
    db.commit()
    assert counter_envelope(db).is_exact(), "the envelope cannot see the hidden keyword: that is the gap"
    spy = _SweepSpy(monkeypatch)
    out = reconcile_counters_after_import(db, new)
    assert len(spy.calls) == 1 and out["sweep"]["complete"] is True
    assert _state(db)[hidden][:2] == (5, 1)
    spy.calls.clear()
    out = reconcile_counters_after_import(db, new)  # the sweep just landed: now it is recent
    assert spy.calls == [] and "skipped" in out["sweep"]


@pytest.mark.parametrize(("budget", "spent", "want"), [(30.0, 10.0, 20.0), (30.0, 31.0, "skip"), (0.0, 99.0, 0)])
def test_route_the_sweep_gets_what_the_scoped_pass_left_and_never_an_unbounded_zero_by_accident(
    db, monkeypatch, budget, spent, want
):
    import src.analytics.store as store
    from src.analytics.store import reconcile_counters_after_import

    new, _a, _b = _routing_corpus(db, 12, 1)
    monkeypatch.setenv("OO_RECONCILE_BUDGET_S", str(budget))
    clock = iter([0.0])
    monkeypatch.setattr("time.monotonic", lambda: next(clock, spent))
    monkeypatch.setattr(store, "reconcile_keyword_counters_for_articles", lambda s, ids, **kw: {"keywords_in_scope": 1})
    spy = _SweepSpy(monkeypatch)
    out = reconcile_counters_after_import(db, new)
    if want == "skip":
        assert spy.calls == [] and out["sweep"] == {"skipped": "the budget was spent on the imported keywords"}
    else:
        assert spy.calls == [pytest.approx(want)]


@pytest.mark.parametrize("which", ["sweep", "scoped"])
def test_an_ingest_cannot_land_between_the_compare_and_the_write(tmp_path, which, monkeypatch):
    """Plan's check on row 424: the reconcile reads the exact counts, compares them with the stored counters and writes the
    wrong ones, so the read must sit inside the write gate with the write. A writer that commits a new mention and its counter
    increment while the reconcile is between its GROUP BY and its compare would otherwise be undone: the compare sees the
    incremented counter, calls it wrong, and writes back the count from before the mention. Here the writer is started at
    exactly that point and given time to finish; it must instead wait for the gate, and every counter ends exact."""
    import threading

    from sqlalchemy import event

    from src.database.writer import connection_first, write_lock

    monkeypatch.setenv("OO_WRITE_GATE", "1")
    engine = app_sqlite_engine(str(tmp_path / "c.db"), future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, future=True)
    s = make()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    aids = _articles(s, 2)
    (kid,) = _keywords(s, 1)
    _mention(s, kid, aids[0], 3)
    s.query(Keyword).update({Keyword.mention_count: 3, Keyword.article_count: 1})
    s.commit()

    def ingest() -> None:
        w = make()
        try:
            connection_first(w)
            with write_lock():
                w.add(KeywordMention(keyword_id=kid, article_id=aids[1], count=4))
                w.query(Keyword).filter(Keyword.id == kid).update(
                    {Keyword.mention_count: Keyword.mention_count + 4, Keyword.article_count: Keyword.article_count + 1}
                )
                w.commit()
        finally:
            w.close()

    started: list[threading.Thread] = []

    def at_the_compare(conn, cursor, statement, params, context, executemany):
        low = statement.lower()
        if not started and low.startswith("select") and "keywords.mention_count" in low and "group by" not in low:
            t = threading.Thread(target=ingest)
            started.append(t)
            t.start()
            t.join(0.5)  # long enough to commit if nothing holds it back

    event.listen(engine, "before_cursor_execute", at_the_compare)
    try:
        if which == "sweep":
            reconcile_keyword_counters(s, now=T_NOW, budget_s=0, restart=True)
        else:
            reconcile_keyword_counters_for_articles(s, [aids[0]], now=T_NOW, budget_s=0)
    finally:
        event.remove(engine, "before_cursor_execute", at_the_compare)
    assert started, "the interleaving point was never reached"
    started[0].join(10)
    assert not started[0].is_alive()
    s.expire_all()
    k = s.get(Keyword, kid)
    assert (k.mention_count, k.article_count) == (7, 2), "the ingest's count was undone by the reconcile"
    s.close()
    engine.dispose()
